#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
1.extractPDF.py

If no arguments are supplied, it defaults to searching for PDFs in 'WS' folder.
Otherwise, usage:
  python 1.extractPDF.py <FOLDER_OR_PDF_PATH> [--split half]
"""

import sys
import base64
import requests
import json
from pdf2image import convert_from_path
from dotenv import load_dotenv
import os

load_dotenv()
MATHPIX_APP_ID = os.getenv("MATHPIX_APP_ID")
MATHPIX_APP_KEY = os.getenv("MATHPIX_APP_KEY")

DEFAULT_FOLDER = "WS"  # The folder we default to if none provided

def build_output_filename(pdf_path, suffix="_extracted.json"):
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    return f"{base}{suffix}"

def analyze_math_with_mathpix(image_path):
    print(f"📐 Sending {image_path} to MathPix for OCR...")
    with open(image_path, "rb") as img:
        img_bytes = img.read()

    response = requests.post(
        "https://api.mathpix.com/v3/text",
        headers={
            "app_id": MATHPIX_APP_ID,
            "app_key": MATHPIX_APP_KEY,
            "Content-type": "application/json"
        },
        json={
            "src": f"data:image/png;base64,{base64.b64encode(img_bytes).decode()}",
            "formats": ["text", "latex_styled"],
            "ocr": ["math", "text"]
        }
    )

    data = response.json()
    extracted_text = data.get("text", "[MathPix text unavailable]")
    extracted_latex = data.get("latex_styled", "[MathPix LaTeX unavailable]")

    return extracted_text.strip(), extracted_latex.strip()

def extract_pdf_full(pdf_path):
    print(f"🖼️ Converting PDF '{pdf_path}' pages to images...")
    images = convert_from_path(pdf_path)
    total_pages = len(images)
    print(f"Found {total_pages} pages in the PDF...")

    pages_data = []
    for i, img in enumerate(images):
        page_num = i + 1
        img_path = f"page_{page_num}.png"
        img.save(img_path, "PNG")

        print(f"\n📄 Processing Page {page_num}...")
        page_text, page_latex = analyze_math_with_mathpix(img_path)

        page_info = {
            "page": page_num,
            "page_text": page_text
        }

        if page_latex and "[MathPix LaTeX unavailable]" not in page_latex:
            page_info["latex"] = page_latex

        pages_data.append(page_info)

        # os.remove(img_path)  # optional cleanup if desired

    result_data = {
        "source_pdf": pdf_path,
        "total_pages": total_pages,
        "pages": pages_data
    }
    return result_data

def write_json_to_file(data, out_path):
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"✅ Saved structured results to {out_path}")

def process_pdf(pdf_path, split_half=False):
    data = extract_pdf_full(pdf_path)
    total_pages = data["total_pages"]
    pages = data["pages"]

    if split_half and total_pages > 1:
        midpoint = total_pages // 2

        questions_data = {
            "source_pdf": pdf_path,
            "total_pages": midpoint,
            "pages": pages[:midpoint]
        }
        solutions_data = {
            "source_pdf": pdf_path,
            "total_pages": total_pages - midpoint,
            "pages": pages[midpoint:]
        }

        q_out = build_output_filename(pdf_path, suffix="_questions.json")
        s_out = build_output_filename(pdf_path, suffix="_solutions.json")

        write_json_to_file(questions_data, q_out)
        write_json_to_file(solutions_data, s_out)
    else:
        out_file = build_output_filename(pdf_path, suffix="_extracted.json")
        write_json_to_file(data, out_file)

def process_folder(folder_path, split_half=False):
    pdf_files = [
        f for f in os.listdir(folder_path)
        if f.lower().endswith(".pdf")
    ]
    pdf_files.sort()

    for pdf in pdf_files:
        pdf_path = os.path.join(folder_path, pdf)
        print(f"\n=== Processing PDF: {pdf_path} ===")
        process_pdf(pdf_path, split_half=split_half)

if __name__ == '__main__':
    # If no args, default to 'WS' folder
    if len(sys.argv) == 1:
        print(f"No arguments provided. Defaulting to folder '{DEFAULT_FOLDER}'...")
        input_arg = DEFAULT_FOLDER
        split_flag = False
    else:
        input_arg = sys.argv[1]
        split_flag = False
        if len(sys.argv) > 2 and sys.argv[2] == "--split":
            split_flag = True

    if os.path.isdir(input_arg):
        process_folder(input_arg, split_half=split_flag)
    elif os.path.isfile(input_arg) and input_arg.lower().endswith(".pdf"):
        process_pdf(input_arg, split_half=split_flag)
    else:
        print(f"❌ Invalid input: {input_arg} is neither a folder nor a PDF file.")
        sys.exit(1)
