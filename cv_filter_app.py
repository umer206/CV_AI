import os
import re
import json
import time
import zipfile
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor

import pytesseract
import pandas as pd
from PyPDF2 import PdfReader
from pdf2image import convert_from_path
from docx import Document
import streamlit as st
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# === UI Config ===
st.set_page_config(page_title="CV Filter App", layout="wide")

# === Streamlit Sidebar Option ===
st.sidebar.title("CV Filter Settings")

folder_path = st.sidebar.text_input("📁 Folder path containing CVs:")
if folder_path and not os.path.isdir(folder_path):
    st.sidebar.error("❌ Folder does not exist.")

keywords_input = st.sidebar.text_input("🔑 Keywords (comma-separated):", value="Python, SQL, T24, Agile")
extract_details = st.sidebar.checkbox("🤖 Extract detailed experience (via Gemini LLM)", value=False)

process_triggered = st.button("🚀 Process CVs")

# Constants
POPPLER_PATH = r'C:/Users/DELL/Downloads/Release-24.08.0-0/poppler-24.08.0/Library/bin'
TESSERACT_PATH = r"C:/Program Files/Tesseract-OCR/tesseract.exe"
pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

KEYWORDS = [k.strip() for k in keywords_input.split(',') if k.strip()]

# === Helper Functions ===

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

Return JSON in this format:
{{
  "total_experience_years": 6.5,
  "experience_by_domain": {{"IT": 3, "Finance": 2.5}},
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
    """.strip()

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    body = {
        "contents": [{"parts": [{"text": prompt}]}]
    }

    try:
        response = requests.post(url, headers=headers, json=body, timeout=30)
        response.raise_for_status()
        content = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        # Parse JSON
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            json_like_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_like_match:
                data = json.loads(json_like_match.group())
            else:
                return None
    except Exception as e:
        print(f"Error from Gemini: {e}")
        return None

    data["matched_keywords"] = matched_keywords
    data["match_score"] = match_score

    # Save JSON
    json_path = os.path.join(folder_path, f"{os.path.splitext(filename)[0]}_experience.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    # Save Excel
    excel_path = os.path.join(folder_path, f"{os.path.splitext(filename)[0]}_experience.xlsx")
    df_roles = pd.DataFrame(data.get("roles", []))
    if not df_roles.empty:
        df_roles["Matched Keywords"] = ", ".join(matched_keywords)
        df_roles["Match Score"] = match_score
        df_roles.to_excel(excel_path, index=False)

    return data

def process_cv(file_path):
    filename = os.path.basename(file_path)
    file_ext = filename.lower().split(".")[-1]
    extracted_text = ""

    try:
        if file_ext == 'pdf':
            reader = PdfReader(file_path)
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
    if not matched_keywords:
        return None

    result_entry = {
        "Filename": filename,
        "Match Score": match_score,
        "Matched Keywords": ", ".join(matched_keywords)
    }

    if extract_details:
        data = extract_details_llm(extracted_text, matched_keywords, match_score, filename)
        if data:
            # Format roles nicely
            roles = data.get("roles", [])
            if roles:
                roles_str = "\n".join(
                    f"- {r.get('title', '')} at {r.get('company', '')} ({r.get('start', '')} - {r.get('end', '')}, {r.get('domain', '')})"
                    for r in roles
                )
            else:
                roles_str = "N/A"

            result_entry.update({
                "total_experience_years": data.get("total_experience_years"),
                "experience_by_domain": json.dumps(data.get("experience_by_domain", {})),
                "Roles": roles_str
            })

    return result_entry

# === Main processing ===

if process_triggered:
    if not folder_path or not os.path.isdir(folder_path):
        st.error("❌ Please provide a valid folder path.")
        st.stop()

    cv_files = [os.path.join(folder_path, f) for f in os.listdir(folder_path) if f.lower().endswith(('.pdf', '.docx', '.doc'))]
    if not cv_files:
        st.warning("⚠️ No CV files found.")
        st.stop()

    results = []
    matched_cvs = []
    start_time = time.time()
    total_files = len(cv_files)
    progress = st.progress(0)
    status_text = st.empty()

    def run_parallel():
        with ThreadPoolExecutor(max_workers=1) as executor:
            for idx, result in enumerate(executor.map(process_cv, cv_files)):
                percent_complete = int(((idx + 1) / total_files) * 100)
                elapsed = time.time() - start_time
                eta = (elapsed / (idx + 1)) * (total_files - idx - 1)
                status_text.text(f"⏳ Processed {idx+1}/{total_files} | ETA: {int(eta)}s")
                progress.progress(percent_complete)
                if result:
                    results.append(result)
                    matched_cvs.append(os.path.join(folder_path, result["Filename"]))

    run_parallel()

    if results:
        df_summary = pd.DataFrame(results)
        st.subheader("📊 Summary Table")
        st.dataframe(df_summary, use_container_width=True)

        # ZIP matched CVs
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zipf:
            for f in matched_cvs:
                zipf.write(f, os.path.basename(f))
        zip_buffer.seek(0)

        st.download_button(
            label="📥 Download Matched CVs",
            data=zip_buffer,
            file_name="matched_cvs.zip",
            mime="application/zip"
        )
        st.success("🎉 Processing complete!")
    else:
        st.warning("⚠️ No matching CVs found.")
