import os
import re
import json
import sys
import io
from PIL import Image
import google.generativeai as genai
from pdf2image import convert_from_path

# --- Path Correction ---
A_LEVEL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if A_LEVEL_DIR not in sys.path:
    sys.path.append(A_LEVEL_DIR)

from config import settings
from . import utils

logger = utils.setup_logger(__name__)

# --- Image safety & tiling knobs ---
# allow opening very large images; we’ll control size ourselves
Image.MAX_IMAGE_PIXELS = None

# Tunables: tweak in code or surface in settings if you prefer
MAX_RENDER_WIDTH = getattr(settings, "MAX_RENDER_WIDTH", 2200)   # px
TILE_MAX_HEIGHT = getattr(settings, "TILE_MAX_HEIGHT", 6000)     # px
TILE_OVERLAP     = getattr(settings, "TILE_OVERLAP", 200)        # px
PDF_RENDER_DPI   = getattr(settings, "PDF_RENDER_DPI", 200)      # dpi for pdf2image


def _initialize_gemini_client():
    """Initializes and returns the Gemini client."""
    try:
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        model = genai.GenerativeModel(settings.GEMINI_MODEL_NAME)
        logger.info("Document Analyzer: Gemini client initialized.")
        return model
    except Exception as e:
        logger.error(f"Document Analyzer: failed to initialize Gemini client: {e}")
        return None


def _parse_ai_response(response_text):
    """Safely parses the JSON string from the AI's response."""
    try:
        # The AI might wrap the JSON in markdown backticks, so we remove them
        clean_text = re.sub(r'^```json\s*|\s*```$', '', (response_text or "").strip())
        parsed = json.loads(clean_text)
        return parsed
    except json.JSONDecodeError as e:
        # Console: concise; File: include first chunk for diagnosis
        logger.warning("Document Analyzer: JSON decode failed — %s", utils.truncate(str(e), 160))
        logger.debug("Document Analyzer: raw AI text (first 1200 chars): %s", (response_text or "")[:1200])
        return None


# -------- Image helpers for robust handling of huge/tall pages --------

def _downscale_width(img: Image.Image, max_w: int = MAX_RENDER_WIDTH) -> Image.Image:
    """Downscale image to a target max width while preserving aspect ratio."""
    if img.width <= max_w:
        return img
    h = int(img.height * (max_w / img.width))
    return img.resize((max_w, h), Image.LANCZOS)


def _iter_vertical_tiles(img: Image.Image,
                         tile_h: int = TILE_MAX_HEIGHT,
                         overlap: int = TILE_OVERLAP):
    """
    Yield (tile_image, y_offset) slices covering the full height with overlap.
    Keeps each tile well below encoder limits and friendly for Vision models.
    """
    H = img.height
    y = 0
    while True:
        box = (0, y, img.width, min(y + tile_h, H))
        yield img.crop(box), y
        if box[3] >= H:
            break
        y = y + tile_h - overlap  # advance with overlap for context continuity


def _encode_png(img: Image.Image) -> bytes:
    """Encode a PIL image to PNG bytes (avoids WebP’s 16383px hard limit)."""
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def analyze_page_with_vision(image_obj, vision_model, page_number):
    """
    Uses Gemini Vision to extract all question/answer items and pedagogical notes from a single page image.
    Handles very tall Safari-exported PDFs by tiling vertically and sending PNG tiles.
    """
    prompt = """
    You are an expert document parsing AI specializing in A-Level Mathematics worksheets and mark schemes. Your task is to analyze the attached image and extract all distinct question or answer items into a structured format with unique, hierarchical IDs.

    **CONTEXT TRACKING**:
    - As you parse the page, you MUST keep track of the current main question number (e.g., a label like "Q1", "Q3", "Question 4").
    - All subsequent sub-parts (like (a), (b), (i), (ii)) belong to the most recently seen main question number.

    **INSTRUCTIONS**:
    1.  **Identify Items**: Go through the document and identify every unique question or answer item by its label (e.g., "Q1", "(a)", "(ii)").

    2.  **CRITICAL - Create Hierarchical ID**: For each item, create a unique `id`.
        - For a main question (e.g., "Q3"), normalize its ID to just the number (e.g., `"3"`).
        - For a sub-question (e.g., "(a)" under "Q3"), its ID MUST be a combination of the main question number and the sub-part's normalized letter/roman numeral (e.g., `"3a"`).
        - For a sub-sub-question (e.g., "(i)" under "(a)"), its ID should also be hierarchical (e.g., `"3ai"`).

    3.  **CRITICAL - Associate Content Correctly**:
        - **Row Alignment is Key**: A label in one column (e.g., '(b)') and the solution in the 'Scheme' column of that **same row** belong to the same item.
        - **Maintain Label Type**: Be consistent. If a question uses roman numerals (e.g., Q3(i), Q3(ii)), its corresponding answers are also likely labeled with roman numerals.

    4.  **Extract All Content**: For each item, extract the complete text from the main 'Scheme' or content column. This is the core question text or the mathematical solution.

    5.  **Extract Pedagogical Notes**: Look for a corresponding 'Notes' or 'Marks' column. Extract only the plain English explanations, excluding all marking codes (M1, A1, B1, cso, ft, awrt, etc.).

    6.  **Determine Type**: Classify each item's label as 'num' (for main questions like Q1), 'alpha' (a, b), or 'roman' (i, ii).

    **OUTPUT FORMAT**:
    Your output MUST be a single, valid JSON list of objects. Each object must have the following structure:
    {
      "id": "The UNIQUE HIERARCHICAL ID (e.g., '3', '3a', '3ai')",
      "type": "'num', 'alpha', or 'roman'",
      "raw_label": "The exact label as it appears in the text (e.g., 'Q3.', '(a)')",
      "content": "The full text of the question or the mathematical solution from the 'Scheme' column.",
      "pedagogical_notes": "The cleaned, plain English text from the 'Notes' column. If no useful notes exist, this must be an empty string `\"\"`."
    }

    **CRITICAL**:
    - The 'id' field is the most important. Ensure every item has a unique, hierarchical ID based on the main question number it falls under.
    - Ensure the output is ONLY the JSON list. Do not include any other text or explanations.

    Now, analyze the provided image and generate the JSON output.
    """

    try:
        logger.info("DocAnalyze: sending page %s to Vision API…", page_number + 1)

        # Normalize to a reasonable width to keep text legible and payload small
        img = _downscale_width(image_obj, MAX_RENDER_WIDTH)

        all_items = []
        tile_count = 0

        # Tile vertically so even "endless scroll" pages are safe
        for tile_img, y0 in _iter_vertical_tiles(img, TILE_MAX_HEIGHT, TILE_OVERLAP):
            tile_count += 1
            payload = _encode_png(tile_img)

            # Pass bytes explicitly as PNG to avoid WebP encoder limits
            response = vision_model.generate_content([
                prompt,
                {"mime_type": "image/png", "data": payload}
            ])

            extracted_data = _parse_ai_response(response.text)
            if not isinstance(extracted_data, list):
                logger.debug("DocAnalyze: tile %d on page %d returned no list.", tile_count, page_number + 1)
                continue

            # Add page number and (optionally) tile y-offset to each item
            for item in extracted_data:
                item['page_number'] = page_number
                item['tile_y_offset'] = y0  # useful if you ever align regions later

            all_items.extend(extracted_data)

        logger.info("DocAnalyze: page %s extracted %d items (tiles=%d).", page_number + 1, len(all_items), tile_count)
        return all_items

    except Exception as e:
        logger.error("DocAnalyze: Vision page analysis error on page %s — %s", page_number + 1, e)
        return []


def process_pdf_with_ai_analyzer(pdf_path):
    """
    Processes an entire PDF using the AI-powered vision analyzer.
    Converts each page to an image, then analyzes via Gemini Vision.
    Robust to single extremely tall pages (Safari "Export as PDF").
    """
    logger.info("DocAnalyze: starting analysis for '%s'", os.path.basename(pdf_path))
    vision_model = _initialize_gemini_client()
    if not vision_model:
        return []

    # 1) Convert PDF to images. Use a sane DPI to avoid massive rasters.
    try:
        page_images = convert_from_path(pdf_path, dpi=PDF_RENDER_DPI)
    except Exception as e:
        logger.error("DocAnalyze: could not convert PDF '%s' — %s", pdf_path, e)
        return []

    # 2) Analyze each page (with tiling inside analyze_page_with_vision)
    all_items = []
    total_pages = len(page_images)
    for i, image_obj in enumerate(page_images):
        logger.info("DocAnalyze: analyzing page %d/%d", i + 1, total_pages)
        page_items = analyze_page_with_vision(image_obj, vision_model, page_number=i)
        if page_items:
            all_items.extend(page_items)

    logger.info("DocAnalyze: finished '%s' — total extracted items: %d", os.path.basename(pdf_path), len(all_items))
    return all_items
