import sys
import base64
import requests
import json
from pdf2image import convert_from_path
from dotenv import load_dotenv
import os

# -------------------- CONFIG --------------------
load_dotenv()  # Loads environment variables from .env

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MATHPIX_APP_ID = os.getenv("MATHPIX_APP_ID")
MATHPIX_APP_KEY = os.getenv("MATHPIX_APP_KEY")
# ------------------------------------------------


# -------------------- MATHPIX IMAGE OCR --------------------
def analyze_math_with_mathpix(image_path):
    print(f"📐 Sending {image_path} to MathPix for math OCR...")
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
    text = data.get("text", "[MathPix text unavailable]")
    latex = data.get("latex_styled", "[MathPix LaTeX unavailable]")
    return text.strip(), latex.strip()


# -------------------- GPT VISION DIAGRAM DESCRIPTION --------------------
def analyze_diagrams_with_gpt_vision(image_path, page_num, context_text):
    print(f"👁️ Using GPT Vision to describe diagrams on page {page_num}...")
    with open(image_path, "rb") as img_file:
        img_bytes = img_file.read()
        img_base64 = base64.b64encode(img_bytes).decode()

    system_message = (
        "You are a math diagram summarizer. "
        "Detect whether the image contains any diagram or sketch. "
        "If it does, describe it clearly in no more than two concise sentences. "
        "If it's just text or doesn't include anything visual, say 'none'."
    )

    payload = {
        "model": "gpt-4-turbo",
        "messages": [
            {"role": "system", "content": system_message},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_base64}"}},
                    {"type": "text", "text": context_text[:800]}
                ]
            }
        ],
        "max_tokens": 300
    }

    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json=payload
        )
        result = response.json()
        desc = result["choices"][0]["message"]["content"].strip()
        if desc.lower() == "none" or "no diagram" in desc.lower():
            return None
        return desc
    except Exception as e:
        print("❌ GPT Vision error:", e)
        return None


# -------------------- MAIN FUNCTION --------------------
def extract_pdf_full(pdf_path):
    print("🖼️ Converting PDF pages to images...")
    images = convert_from_path(pdf_path)
    all_pages = []

    for i, img in enumerate(images):
        page_num = i + 1
        img_path = f"page_{page_num}.png"
        img.save(img_path, "PNG")

        print(f"\n📄 Processing Page {page_num}...")
        math_text, latex = analyze_math_with_mathpix(img_path)
        diagram_description = analyze_diagrams_with_gpt_vision(img_path, page_num, math_text)

        page_data = {
            "page": page_num,
            "mathpix_text": math_text
        }

        # Only include LaTeX if it's usable
        if latex.strip() and "[MathPix LaTeX unavailable]" not in latex:
            page_data["latex"] = latex

        if diagram_description:
            page_data["diagram_description"] = diagram_description

        all_pages.append(page_data)

    with open("extracted_combined.json", "w", encoding="utf-8") as f:
        json.dump(all_pages, f, indent=2, ensure_ascii=False)

    print("✅ Saved structured results to extracted_combined.json")

# -------------------- CLI ENTRY POINT --------------------
if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python extractPDF.py <path_to_pdf>")
        sys.exit(1)

    extract_pdf_full(sys.argv[1])