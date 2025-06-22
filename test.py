import os
import json
import ollama
import pytesseract
import pandas as pd
from pdf2image import convert_from_path

# === CONFIG ===

PDF_PATH = 'C:/Users/DELL/Downloads/OneDrive_2_6-3-2025/ASFA CV_2025-05-15.pdf'
POPPLER_PATH = 'C:/Users/DELL/Downloads/Release-24.08.0-0/poppler-24.08.0/Library/bin'
TESSERACT_PATH = "C:/Program Files/Tesseract-OCR/tesseract.exe"
MODEL_NAME = "llama3"

# Set Tesseract path
pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

# === STEP 1: Convert PDF to images and extract text ===
print("📄 Converting PDF to images and extracting text...")
try:
    pages = convert_from_path(PDF_PATH, 300, poppler_path=POPPLER_PATH)
    extracted_text = "\n".join([pytesseract.image_to_string(page) for page in pages])
except Exception as e:
    print(f"❌ Error during PDF processing: {e}")
    exit()

print("✅ Text extracted.\nPreview:")
print(extracted_text[:500])

# === STEP 2: Ask LLM to extract structured experience ===
print("\n🤖 Asking Ollama (LLaMA 3) for structured experience extraction...")

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
{extracted_text}
"""

try:
    response = ollama.chat(model=MODEL_NAME, messages=[{"role": "user", "content": prompt}])
    llm_output = response["message"]["content"]
    data = json.loads(llm_output)
except json.JSONDecodeError:
    print("❌ LLM did not return valid JSON:")
    print(llm_output)
    exit()
except Exception as e:
    print(f"❌ Error communicating with Ollama: {e}")
    exit()

# === STEP 3: Save output ===
json_path = os.path.join(os.path.dirname(PDF_PATH), "parsed_experience.json")
excel_path = os.path.join(os.path.dirname(PDF_PATH), "parsed_experience.xlsx")

with open(json_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)

df = pd.DataFrame(data.get("roles", []))
df.to_excel(excel_path, index=False)

print(f"\n✅ Experience data saved to:\n- {json_path}\n- {excel_path}")
