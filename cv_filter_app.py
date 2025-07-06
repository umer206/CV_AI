import os
import re
import json
import time
import zipfile
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

# === Load env variables ===
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

# === UI Config ===
st.set_page_config(page_title="CV Filter App", layout="wide")

# === Streamlit Sidebar Option ===
st.sidebar.title("CV Filter Settings")

# Folder path input
folder_path = st.sidebar.text_input(
    "📁 Enter the full path to the folder containing CVs:",
    placeholder="e.g., C:/Users/YourName/Documents/CVs"
)
if folder_path and not os.path.isdir(folder_path):
    st.sidebar.error("❌ Folder does not exist. Please check the path.")

keywords_input = st.sidebar.text_input("🔑 Keywords to filter on (comma-separated):", value="Python, SQL, T24, Agile")
extract_details = st.sidebar.checkbox("🤖 Extract detailed experience (via LLM)", value=False)

# Process Button
process_triggered = st.button("🚀 Process CVs")

# Constants
POPPLER_PATH = 'C:/Users/DELL/Downloads/Release-24.08.0-0/poppler-24.08.0/Library/bin'
TESSERACT_PATH = "C:/Program Files/Tesseract-OCR/tesseract.exe"

# Set Tesseract path
pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

# Convert keyword string to list
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
    From the following CV text, extract the candidate’s work experience:

    - Total years of experience
    - Experience by domain (e.g., IT, Finance)
    - List of roles with title, company, duration, and inferred domain

    Return the result in this JSON format:

    {{
      "total_experience_years": 6.5,
      "experience_by_domain": {{
        "IT": 3,
        "Finance": 2.5
      }},
      "roles": [
        {{
          "title": "Software Engineer",
          "company": "XYZ Corp",
          "start": "Jan 2020",
          "end": "June 2023",
          "domain": "IT"
        }}
      ]
    }}

    CV Text:
    {text}
    """

    headers = {"Content-Type": "application/json"}
    params = {"key": GEMINI_API_KEY}
    body = {"contents": [{"parts": [{"text": prompt}]}]}

    try:
        time.sleep(1)  # slow down requests to avoid rate limit
        response = requests.post(GEMINI_URL, params=params, headers=headers, json=body)
        response.raise_for_status()
        data_raw = response.json()
        llm_output = data_raw['candidates'][0]['content']['parts'][0]['text']

        try:
            data = json.loads(llm_output)
        except json.JSONDecodeError:
            json_like = re.search(r'\{.*\}', llm_output, re.DOTALL)
            if json_like:
                data = json.loads(json_like.group())
            else:
                return None
    except Exception as e:
        st.error(f"Error from Gemini: {e}")
        return None

    data['matched_keywords'] = matched_keywords
    data['match_score'] = match_score

    json_path = os.path.join(folder_path, f"{os.path.splitext(filename)[0]}_experience.json")
    excel_path = os.path.join(folder_path, f"{os.path.splitext(filename)[0]}_experience.xlsx")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    df = pd.DataFrame(data.get("roles", []))
    if not df.empty:
        df["Matched Keywords"] = ", ".join(matched_keywords)
        df["Match Score"] = match_score
        df.to_excel(excel_path, index=False)

    return data


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
            result_entry.update(data)

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
                percent = int(((idx + 1) / total_files) * 100)
                elapsed = time.time() - start_time
                eta = (elapsed / (idx + 1)) * (total_files - idx - 1)
                status_text.text(f"⏳ Processed {idx + 1}/{total_files} CVs | ETA: {int(eta)}s")
                progress.progress(percent)
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
            for file in matched_cvs:
                zipf.write(file, os.path.basename(file))
        zip_buffer.seek(0)
        st.session_state['download_data'] = zip_buffer.read()

        st.success("🎉 CV processing complete!")
        st.download_button(
            label="📥 Download Matched CVs",
            data=st.session_state.get('download_data', b""),
            file_name="matched_cvs.zip",
            mime="application/zip"
        )
