import streamlit as st
import os
import re
import shutil
import tempfile
from docx import Document
import pandas as pd
import PyPDF2
import spacy
from pdf2image import convert_from_path
from PIL import Image
import pytesseract

# Load spaCy model
nlp = spacy.load("en_core_web_sm")

# Poppler path (update this to your system path)
POPPLER_PATH = r"C:\Users\DELL\Downloads\Release-24.08.0-0\poppler-24.08.0\Library\bin"  # <-- Change this to your poppler path

# --- Extract Text Functions ---
def extract_text_from_pdf(file_path):
    text = ""
    is_image_based = False
    try:
        with open(file_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            for page in reader.pages:
                content = page.extract_text()
                if content:
                    text += content
                else:
                    is_image_based = True
    except:
        is_image_based = True

    if is_image_based or not text.strip():
        try:
            images = convert_from_path(file_path, poppler_path=POPPLER_PATH)
            text = ""
            for img in images:
                text += pytesseract.image_to_string(img)
        except Exception as e:
            print(f"OCR failed: {e}")

    return text, is_image_based

def extract_text_from_docx(file_path):
    try:
        doc = Document(file_path)
        return "\n".join([para.text for para in doc.paragraphs])
    except:
        return ""

# --- Name Extraction ---
def extract_name_with_spacy(text):
    doc = nlp(text)
    for ent in doc.ents:
        if ent.label_ == "PERSON" and 2 <= len(ent.text.split()) <= 4:
            return ent.text
    return "N/A"

# --- Info Extraction ---
def extract_candidate_info(text):
    email_match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}", text)
    email = email_match.group().strip() if email_match else "N/A"

    phone_match = re.search(r"(03\d{2}[-\s]?\d{7})", text)
    phone = phone_match.group().strip() if phone_match else "N/A"

    linkedin_match = re.search(r"(https?://)?(www\\.)?linkedin\\.com/in/[A-Za-z0-9\-_/]{5,}", text)
    linkedin = linkedin_match.group().strip() if linkedin_match else "N/A"
    if linkedin != "N/A" and not linkedin.startswith("http"):
        linkedin = "https://" + linkedin

    name = extract_name_with_spacy(text)

    return {
        "Name": name,
        "Email": email,
        "Phone": phone,
        "LinkedIn": linkedin,
    }

def match_keywords(text, keywords):
    text_lower = text.lower()
    found = [kw for kw in keywords if kw.lower() in text_lower]
    score = int(len(found) / len(keywords) * 100) if keywords else 0
    return found, score


# --- Process Files ---
def process_files(source_folder, keywords):
    matched_files = []
    manual_review_files = []
    data = []

    dest_dir = os.path.join(source_folder, "matched")
    manual_dir = os.path.join(dest_dir, "manual_review")
    os.makedirs(dest_dir, exist_ok=True)
    os.makedirs(manual_dir, exist_ok=True)

    for file in os.listdir(source_folder):
        path = os.path.join(source_folder, file)
        ext = file.lower()

        if not os.path.isfile(path) or not ext.endswith(('.pdf', '.docx')):
            continue

        if ext.endswith('.pdf'):
            text, is_image = extract_text_from_pdf(path)
        else:
            text = extract_text_from_docx(path)
            is_image = False

        candidate_info = extract_candidate_info(text)
        matched_keywords, score = match_keywords(text, keywords)

        record = {
            "Filename": file,
            "Name": candidate_info.get("Name", "N/A"),
            "Email": candidate_info.get("Email", "N/A"),
            "Phone": candidate_info.get("Phone", "N/A"),
            "LinkedIn": candidate_info.get("LinkedIn", "N/A"),
            "Match Score": score,
            "Matched Keywords": ", ".join(matched_keywords) if matched_keywords else "N/A",
            "Manual Review": "Yes" if is_image else "No",
            "Match": "Yes" if matched_keywords else "No"
        }

        data.append(record)

        if matched_keywords:
            shutil.copy(path, os.path.join(dest_dir, file))
        if is_image:
            shutil.copy(path, os.path.join(manual_dir, file))

    return data, dest_dir

# --- Streamlit UI ---
st.set_page_config("CV Filter App", layout="wide")
col1, col2 = st.columns([4, 6])

with col1:
    st.markdown("# CVify")
    st.markdown("###### Fast. Focused. Filtered.")

with col2:
    st.markdown("#### ")

uploaded_zip = st.file_uploader("Upload Zipped CVs (PDF/DOCX)", type=["zip"])
keyword_input = st.text_input("Keywords (comma-separated)", "Python, SQL, T24, Agile")

if st.button("Process"):
    if not uploaded_zip:
        st.error("Please upload a zip file.")
    else:
        temp_dir = tempfile.mkdtemp()
        zip_path = os.path.join(temp_dir, "cvs.zip")
        with open(zip_path, "wb") as f:
            f.write(uploaded_zip.read())

        shutil.unpack_archive(zip_path, temp_dir)

        keywords = [k.strip() for k in keyword_input.split(",") if k.strip()]
        st.success("Processing CVs...")
        result_data, matched_folder = process_files(temp_dir, keywords)

        if result_data:
            df = pd.DataFrame(result_data)
            st.subheader("📊 Match Results")

            filtered_df = df[(df["Match"] == "Yes") | (df["Manual Review"] == "Yes")]

            def highlight_manual_review(row):
                color = "#9e8942" if row["Manual Review"] == "Yes" else ""
                return ['background-color: {}'.format(color)] * len(row)

            st.dataframe(
                filtered_df.style.apply(highlight_manual_review, axis=1),
                use_container_width=True
            )

            excel_path = os.path.join(temp_dir, "CV_Report.xlsx")
            df.to_excel(excel_path, index=False)
            with open(excel_path, "rb") as f:
                st.download_button("📥 Download Excel Report", f, file_name="CV_Report.xlsx")

            matched_zip = shutil.make_archive(os.path.join(temp_dir, "matched_cv_output"), 'zip', matched_folder)
            with open(matched_zip, "rb") as f:
                st.download_button("📥 Download Matched CVs", f, file_name="Matched_CVs.zip")

            total = len(df)
            matched = df["Match"].value_counts().get("Yes", 0)
            manual_review = df["Manual Review"].value_counts().get("Yes", 0)

            st.info(f"✅ {matched}/{total} CVs matched keywords.")
            if manual_review:
                st.warning(f"⚠️ {manual_review} CVs may be image-based and need manual review.")
        else:
            st.warning("No valid CVs found or none matched.")
