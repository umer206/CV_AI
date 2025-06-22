# CV_AI
CVify - AI Integrated

----------------------DATA FLOW-------------------- 
User Inputs
   ↓
Folder of PDF CVs + Keyword List
   ↓
[For each CV file in folder]
   ├──> 1. Text Extraction
   │       ├── PyPDF2 (native text)
   │       └── OCR fallback (pdf2image + pytesseract)
   │
   ├──> 2. Keyword Matching
   │       └── Extract keywords matched + match score
   │
   └──> [If user enabled LLM + match found]
           └── 3. Send text to LLM
               └── Extract structured data (roles, experience, domains)
   ↓
Store per-CV results:
   ├── JSON (structured LLM output)
   └── Excel (roles table if present)
   ↓
Build Summary Table
   ↓
Render in UI:
   ├── Streamlit Data Table (summary)
   ├── Download Button (zip matched CVs)
   └── Progress & ETA feedback
