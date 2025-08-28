import os
import re
import sys
import io
from PIL import Image
import google.generativeai as genai
from pdf2image import convert_from_path

# --- Path Correction ---
# Add the project's root directory (A_Level) to the system path.
A_LEVEL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if A_LEVEL_DIR not in sys.path:
    sys.path.append(A_LEVEL_DIR)

# Now we can import from the project root's subdirectories
from config import settings
from . import document_analyzer
from . import utils

# Setup logger for this module
logger = utils.setup_logger(__name__)

# Allow opening large images; we'll control size explicitly
Image.MAX_IMAGE_PIXELS = None

# --- Tunables (override in settings.py if you like) ---
CLASSIFY_RENDER_WIDTH = getattr(settings, "CLASSIFY_RENDER_WIDTH", 1600)  # px
CLASSIFY_TILE_MAX_HEIGHT = getattr(settings, "CLASSIFY_TILE_MAX_HEIGHT", 6000)  # px
CLASSIFY_TILE_OVERLAP = getattr(settings, "CLASSIFY_TILE_OVERLAP", 200)  # px
PDF_RENDER_DPI = getattr(settings, "PDF_RENDER_DPI", 200)  # dpi for pdf2image

# --- Helper Functions ---

def _get_id_sequence(items_list):
    """Creates a string 'signature' of the item IDs (e.g., '1-a-b-2-c')."""
    return "-".join([item.get('id', '') for item in items_list])

def _initialize_gemini_client():
    """Initializes and returns the Gemini client."""
    try:
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        model = genai.GenerativeModel(settings.GEMINI_MODEL_NAME)
        logger.info("Sorter: Gemini Vision client initialized.")
        return model
    except Exception as e:
        logger.error(f"Sorter: failed to initialize Gemini client: {e}")
        return None

def _downscale_width(img: Image.Image, max_w: int = CLASSIFY_RENDER_WIDTH) -> Image.Image:
    """Downscale image to a target max width while preserving aspect ratio."""
    if img.width <= max_w:
        return img
    h = int(img.height * (max_w / img.width))
    return img.resize((max_w, h), Image.LANCZOS)

def _iter_vertical_tiles(img: Image.Image, tile_h: int = CLASSIFY_TILE_MAX_HEIGHT, overlap: int = CLASSIFY_TILE_OVERLAP):
    """Yield vertical tiles (as PIL Images) covering the full height with overlap."""
    H = img.height
    y = 0
    while True:
        box = (0, y, img.width, min(y + tile_h, H))
        yield img.crop(box)
        if box[3] >= H:
            break
        y = y + tile_h - overlap

def _encode_png(img: Image.Image) -> bytes:
    """Encode PIL Image to PNG bytes (avoids WebP 16,383 px limit)."""
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()

# --- Core Vision-Based Classification ---

def classify_pdf_with_vision(pdf_path, vision_model):
    """
    Uses the Gemini Vision API to classify a PDF as 'questions', 'answers', or 'interleaved'.
    Renders the first page, downsizes, and sends PNG bytes (not WebP) to avoid encoder limits.
    """
    if not vision_model:
        logger.error("Sorter: vision model not available. Cannot classify.")
        return "unknown"

    try:
        # Render ONLY the first page for classification at a sane DPI
        images = convert_from_path(pdf_path, first_page=1, last_page=1, dpi=PDF_RENDER_DPI)
        if not images:
            logger.warning("Sorter: first page convert failed for '%s'.", os.path.basename(pdf_path))
            return "unknown"

        page = _downscale_width(images[0])

        # Usually the top of page is enough to decide. For very tall pages, we only send the first tile.
        tiles = list(_iter_vertical_tiles(page))
        image_for_model = tiles[0] if tiles else page

        prompt = """
        Analyze the attached image of a math worksheet page. Based on its layout and content, is this page from a 'questions-only' document, an 'answers-only' document (containing worked solutions), or an 'interleaved' document where questions are immediately followed by their answers? 
        
        Respond with only one word: 'questions', 'answers', or 'interleaved'.
        """

        logger.debug("Sorter: classifying '%s'…", os.path.basename(pdf_path))

        # IMPORTANT: Pass explicit PNG bytes to avoid default WebP encoding and its size cap
        response = vision_model.generate_content([
            prompt,
            {"mime_type": "image/png", "data": _encode_png(image_for_model)}
        ])

        classification = (response.text or "").strip().lower().replace('.', '')
        valid_classifications = ["questions", "answers", "interleaved"]
        if classification in valid_classifications:
            logger.info("Sorter: '%s' → %s", os.path.basename(pdf_path), classification)
            return classification
        else:
            logger.warning("Sorter: unexpected classification for '%s': '%s' → 'unknown'", os.path.basename(pdf_path), utils.truncate(classification, 60))
            return "unknown"

    except Exception as e:
        logger.error("Sorter: classification error for '%s' — %s", os.path.basename(pdf_path), e)
        return "unknown"

# --- Main Sorter Logic ---

def sort_and_group_documents(input_dir):
    """
    Analyzes all PDFs in a directory, classifies them using Vision AI, and groups them into processing jobs.
    """
    logger.info("Sorter: scanning directory '%s'", input_dir)
    
    vision_model = _initialize_gemini_client()
    if not vision_model:
        return []

    content_profiles = []
    pdf_files = []
    try:
        pdf_files = [f for f in os.listdir(input_dir) if f.lower().endswith('.pdf')]
        for pdf_file in pdf_files:
            pdf_path = os.path.join(input_dir, pdf_file)
            
            # Call the AI-powered analyzer
            items = document_analyzer.process_pdf_with_ai_analyzer(pdf_path)

            if items:
                profile = {
                    "path": pdf_path,
                    "items": items,
                    "id_set": set(item.get('id') for item in items)
                }
                content_profiles.append(profile)
    except FileNotFoundError:
        logger.error("Sorter: input directory not found: %s", input_dir)
        return []

    classified_docs = {
        "questions": [],
        "answers": [],
        "interleaved": [],
        "unknown": []
    }
    for profile in content_profiles:
        doc_type = classify_pdf_with_vision(profile['path'], vision_model)
        classified_docs[doc_type].append(profile)

    processing_jobs = []
    
    for doc in classified_docs["interleaved"]:
        processing_jobs.append({
            "type": "interleaved",
            "name": os.path.basename(doc['path']).replace('.pdf', ''),
            "content": doc['items']
        })
        logger.info("Sorter: job created — interleaved '%s'", os.path.basename(doc['path']))

    for q_doc in list(classified_docs["questions"]):
        best_match = None
        highest_similarity = 0.0
        
        for a_doc in list(classified_docs["answers"]):
            intersection = len(q_doc['id_set'].intersection(a_doc['id_set']))
            union = len(q_doc['id_set'].union(a_doc['id_set']))
            similarity = intersection / union if union > 0 else 0
            
            if similarity > highest_similarity:
                highest_similarity = similarity
                best_match = a_doc
        
        # Lowered threshold to be more tolerant of mismatches
        if highest_similarity > 0.35 and best_match is not None:
            q_name = os.path.basename(q_doc['path']).lower().replace('.pdf', '')
            base_name = re.sub(r'[-_](q|questions?).*$', '', q_name).strip()
            
            processing_jobs.append({
                "type": "paired",
                "name": base_name,
                "questions": q_doc['items'],
                "answers": best_match['items']
            })
            logger.info("Sorter: job created — paired '%s' (similarity=%.2f)", base_name, highest_similarity)
            
            classified_docs["questions"].remove(q_doc)
            classified_docs["answers"].remove(best_match)
        else:
            logger.warning("Sorter: no answer match for '%s' (best sim=%.2f)", os.path.basename(q_doc['path']), highest_similarity)

    for doc in classified_docs["questions"]:
        logger.warning("Sorter: unmatched question doc '%s'", os.path.basename(doc['path']))
    for doc in classified_docs["answers"]:
        logger.warning("Sorter: unmatched answer doc '%s'", os.path.basename(doc['path']))
    for doc in classified_docs["unknown"]:
        logger.error("Sorter: unknown-type doc '%s' (ignored)", os.path.basename(doc['path']))

    # Summary line
    summary = {
        "scanned": len(pdf_files),
        "profiles": len(content_profiles),
        "jobs": len(processing_jobs),
        "questions": len(classified_docs["questions"]),
        "answers": len(classified_docs["answers"]),
        "interleaved": len(classified_docs["interleaved"]),
        "unknown": len(classified_docs["unknown"]),
    }
    logger.info(
        "Sorter: SUMMARY — PDFs=%(scanned)d | Profiles=%(profiles)d | Jobs=%(jobs)d | "
        "Interleaved=%(interleaved)d | Unknown=%(unknown)d | UnmatchedQ=%(questions)d | UnmatchedA=%(answers)d",
        summary
    )

    return processing_jobs


def split_interleaved_items(mixed_items_list):
    """
    Splits a single list of mixed items from an interleaved document 
    into two separate lists: one for questions and one for answers.
    """
    question_items = []
    answer_items = []
    
    answer_markers = ['answer', 'solution']
    
    for item in mixed_items_list:
        content_start = (item.get('content') or '').lower().strip()
        is_answer = any(content_start.startswith(marker) for marker in answer_markers)
        
        if is_answer:
            answer_items.append(item)
        else:
            question_items.append(item)
            
    logger.info("Sorter: split interleaved → %d questions, %d answers", len(question_items), len(answer_items))
    return question_items, answer_items
