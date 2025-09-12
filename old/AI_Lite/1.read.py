# 1.read.py

import os
import json
import pdfplumber

FOLDER_NAME = "WorkSheets"

def extract_text_from_pdf(pdf_path):
    print(f"📄 Reading PDF: {pdf_path}")
    result = {
        "source_pdf": pdf_path,
        "pages": []
    }

    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            result["pages"].append({
                "page": i + 1,
                "page_text": text.strip()
            })
            print(f"✅ Page {i + 1}: {len(text.strip())} chars")

    return result

def save_json(data, out_path):
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"💾 Saved to {out_path}")

def process_folder(folder_path):
    pdf_files = [f for f in os.listdir(folder_path) if f.lower().endswith(".pdf")]
    if not pdf_files:
        print(f"❌ No PDF files found in {folder_path}")
        return
    for pdf_file in sorted(pdf_files):
        pdf_path = os.path.join(folder_path, pdf_file)
        base_name = os.path.splitext(pdf_file)[0]
        data = extract_text_from_pdf(pdf_path)
        output_file = f"{base_name}_extracted.json"
        save_json(data, output_file)

if __name__ == "__main__":
    if not os.path.exists(FOLDER_NAME):
        print(f"❌ Folder '{FOLDER_NAME}' not found. Please create it and add PDFs.")
    else:
        process_folder(FOLDER_NAME)
