import os
import re
import json
import time
import zipfile
import shutil
import requests
import pytesseract
import pandas as pd
from io import BytesIO
from PyPDF2 import PdfReader
from pdf2image import convert_from_path
from docx import Document
import streamlit as st
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

# === Load environment variables ===
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

# === UI Config ===
st.set_page_config(page_title="CV Filter App", layout="wide")

# === Streamlit Sidebar Option ===
st.sidebar.title("CV Filter Settings")

folder_path = st.sidebar.text_input(
    "📁 Enter the full path to the folder containing CVs:",
    placeholder="e.g., C:/Users/YourName/Documents/CVs"
)
if folder_path and not os.path.isdir(folder_path):
    st.sidebar.error("❌ Folder does not exist. Please check the path.")

keywords_input = st.sidebar.text_input("🔑 Keywords to filter on (comma-separated):", value="Python, SQL, T24, Agile")
extract_details = st.sidebar.checkbox("🤖 Extract detailed experience (via Gemini)", value=False)

process_triggered = st.button("🚀 Process CVs")

POPPLER_PATH = 'C:/Users/DELL/Downloads/Release-24.08.0-0/poppler-24.08.0/Library/bin'
TESSERACT_PATH = "C:/Program Files/Tesseract-OCR/tesseract.exe"

pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
KEYWORDS = [k.strip() for k in keywords_input.split(',') if k.strip()]

def extract_text_from_docx(docx_path):
    try:
        doc = Document(docx_path)
        return "\n".join([para.text for para in doc.paragraphs])
    except Exception:
        return ""

def match_keywords(text, keywords):
    text_lower = text.lower()
    found = [kw for kw in keywords if kw.lower() in text_lower]
    score = int(len(found) / len(keywords) * 100) if keywords else 0
    return found, score

def extract_details_llm(text, matched_keywords, match_score, filename):
    prompt = f"""
You are an expert resume parser.
From the following CV text, extract the candidate’s work experience as a JSON object ONLY.
Do NOT include any explanation, markdown, or text. Only output raw JSON.

The JSON format must be:
{{
  "total_experience_years": number,
  "experience_by_domain": {{
    "IT": number,
    "Finance": number
  }},
  "roles": [
    {{
      "Title": "Job Title",
      "Company": "Company Name",
      "Start": "Month Year",
      "End": "Month Year or Present",
      "Domain": "IT or Finance"
    }}
  ]
}}

If data not available, return empty fields (e.g., "roles": []).

CV Text:
{text}
"""

    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }

    try:
        response = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            headers=headers,
            json=payload
        )
        response.raise_for_status()
        llm_output = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        # st.write("Debug LLM Output:", llm_output)
        try:
            data = json.loads(llm_output)
        except json.JSONDecodeError:
            json_like = re.search(r'\{.*\}', llm_output, re.DOTALL)
            if json_like:
                data = json.loads(json_like.group())
            else:
                st.warning(f"⚠ Could not parse JSON:\n{llm_output}")
                return None

        # Ensure roles always exists
        if "roles" not in data:
            data["roles"] = []

        data['matched_keywords'] = matched_keywords
        data['match_score'] = match_score

        json_path = os.path.join(folder_path, f"{os.path.splitext(filename)[0]}_experience.json")
        excel_path = os.path.join(folder_path, f"{os.path.splitext(filename)[0]}_experience.xlsx")

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        df_roles = pd.DataFrame(data.get("roles", []))
        if not df_roles.empty:
            df_roles["Matched Keywords"] = ", ".join(matched_keywords)
            df_roles["Match Score"] = match_score
            df_roles.to_excel(excel_path, index=False)

        return data
    except requests.exceptions.HTTPError as e:
        st.error(f"Error from Gemini: {e}")
        return None
    except Exception as e:
        st.error(f"Unexpected error: {e}")
        return None

def process_cv(file_path):
    filename = os.path.basename(file_path)
    file_ext = filename.lower().split(".")[-1]
    extracted_text = ""

    try:
        if file_ext == 'pdf':
            reader = PdfReader(file_path)
            if reader.pages:
                extracted_text = "\n".join([page.extract_text() or "" for page in reader.pages])
            if not extracted_text.strip():
                pages = convert_from_path(file_path, 300, poppler_path=POPPLER_PATH)
                extracted_text = "\n".join([pytesseract.image_to_string(page) for page in pages])
        elif file_ext in ['doc', 'docx']:
            extracted_text = extract_text_from_docx(file_path)
        else:
            return None
    except Exception:
        return None

    matched_keywords, match_score = match_keywords(extracted_text, KEYWORDS)
    result_entry = {
        "Filename": filename,
        "Match Score": match_score,
        "Matched Keywords": ", ".join(matched_keywords)
    }

    data = None
    if extract_details and matched_keywords:
        data = extract_details_llm(extracted_text, matched_keywords, match_score, filename)
        if data:
            result_entry.update({
                "total_experience_years": data.get("total_experience_years"),
                "experience_by_domain": json.dumps(data.get("experience_by_domain", {})),
                "roles": json.dumps(data.get("roles", []))
            })

    return result_entry if matched_keywords else None

if process_triggered:
    if not folder_path or not os.path.isdir(folder_path):
        st.error("❌ Please provide a valid existing folder path.")
        st.stop()

    cv_files = [os.path.join(folder_path, f) for f in os.listdir(folder_path) if f.lower().endswith(('.pdf', '.docx', '.doc'))]

    if not cv_files:
        st.warning("⚠️ No valid CV files found in the folder.")
        st.stop()

    results = []
    matched_cvs = []
    total_files = len(cv_files)
    start_time = time.time()
    progress = st.progress(0)
    status_text = st.empty()

    def run_parallel():
        with ThreadPoolExecutor(max_workers=1) as executor:
            for idx, result in enumerate(executor.map(process_cv, cv_files)):
                percent_complete = int(((idx + 1) / total_files) * 100)
                elapsed = time.time() - start_time
                eta = (elapsed / (idx + 1)) * (total_files - idx - 1)
                status_text.text(f"⏳ Processed {idx + 1} of {total_files} CVs | ETA: {int(eta)}s")
                progress.progress(percent_complete)
                if result:
                    results.append(result)
                    matched_cvs.append(os.path.join(folder_path, result["Filename"]))

    run_parallel()

    df_summary = pd.DataFrame(results)
    if not df_summary.empty:
        st.subheader("📊 Summary Table")
        st.dataframe(df_summary, use_container_width=True)
    else:
        st.warning("No results to show.")

    if matched_cvs:
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zipf:
            for file_path in matched_cvs:
                zipf.write(file_path, os.path.basename(file_path))
        zip_buffer.seek(0)
        st.session_state['download_data'] = zip_buffer.read()

        st.success("🎉 CV processing complete!")
        st.download_button(
            label="📥 Download Matched CVs",
            data=st.session_state.get('download_data', b""),
            file_name="matched_cvs.zip",
            mime="application/zip"
        )
