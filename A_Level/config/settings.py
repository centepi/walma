import os
import re  # For LABEL_PATTERNS
from dotenv import load_dotenv

# --- Project paths ---
A_LEVEL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Expect .env one level ABOVE A_Level (e.g., your project root)
ENV_PATH = os.path.join(os.path.dirname(A_LEVEL_DIR), ".env")
load_dotenv(dotenv_path=ENV_PATH)

# --- small helpers for env parsing ---
def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return float(v)
    except Exception:
        return default


def _env_list(name: str):
    """Parse comma/space separated env var into a list of strings, or None if missing/empty."""
    v = os.getenv(name)
    if not v:
        return None
    # accept commas or whitespace
    parts = [p.strip() for p in re.split(r"[,\s]+", v) if p.strip()]
    return parts or None


# --- API and Model Configuration ---
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
MATHPIX_APP_ID = os.getenv("MATHPIX_APP_ID")
MATHPIX_APP_KEY = os.getenv("MATHPIX_APP_KEY")

if not GOOGLE_API_KEY:
    print(f"Warning: GOOGLE_API_KEY not found. Looked for .env at: {ENV_PATH}")
    print("Content generation will fail. Ensure .env is in the project root and contains your key.")

# IMPORTANT: default to Flash, but allow override via env
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-1.5-flash")

# --- Firebase Configuration ---
FIREBASE_SERVICE_ACCOUNT_KEY_PATH = os.path.join(A_LEVEL_DIR, "config", "firebase_service_account.json")
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "walma-609e7")

# --- File/Directory Paths (relative to A_Level folder) ---
INPUT_PDF_DIR = os.path.join(A_LEVEL_DIR, "input_pdfs")

PROCESSED_DATA_DIR = os.path.join(A_LEVEL_DIR, "processed_data")
EXTRACTED_ITEMS_SUBDIR = "01_extracted_items"
PAIRED_REFS_SUBDIR = "02_paired_references"

# --- PDF Parsing / Vision Tunables (pulled up so they’re easy to tweak via env) ---
# Used by document_analyzer / document_sorter if present via getattr(settings, ...)
CLASSIFY_RENDER_WIDTH = int(os.getenv("CLASSIFY_RENDER_WIDTH", "1600"))       # px
CLASSIFY_TILE_MAX_HEIGHT = int(os.getenv("CLASSIFY_TILE_MAX_HEIGHT", "6000")) # px
CLASSIFY_TILE_OVERLAP = int(os.getenv("CLASSIFY_TILE_OVERLAP", "200"))        # px
PDF_RENDER_DPI = int(os.getenv("PDF_RENDER_DPI", "200"))                      # dpi

# When pairing separate Q and A PDFs, minimum Jaccard similarity on IDs
ANSWER_MATCH_MIN_SIMILARITY = _env_float("ANSWER_MATCH_MIN_SIMILARITY", 0.35)

# --- PDF label regex (question numbering) ---
# Regular expressions to identify question labels like "6.", "(a)", "(ii)", etc.
LABEL_PATTERNS = [
    (re.compile(r"^\s*(?P<label_match>(?P<value>\d{1,2}))\s*[.)]"), "num", "value"),
    (re.compile(r"^\s*(?P<label_match>\(\s*(?P<value>\d{1,2})\s*\))\s*[.]?"), "num", "value"),
    (re.compile(r"^\s*(?P<label_match>(?P<value>[a-zA-Z]))\s*[.)](?![a-zA-Z\.])"), "alpha", "value"),
    (re.compile(r"^\s*(?P<label_match>\(\s*(?P<value>[a-zA-Z])\s*\))\s*[.]?"), "alpha", "value"),
    (re.compile(r"^\s*(?P<label_match>(?P<value>ix|iv|v?i{0,3}|x))\s*[.)]", re.IGNORECASE), "roman", "value"),
    (re.compile(r"^\s*(?P<label_match>\(\s*(?P<value>ix|iv|v?i{0,3}|x)\s*\))\s*[.]?", re.IGNORECASE), "roman", "value"),
]

# --- Logging Configuration ---
# Set lower verbosity for cleaner output
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")  # options: DEBUG, INFO, WARNING, ERROR

# --- Generation knobs ---
# High-level context prompt (kept for backwards-compat behavior)
GENERATION_CONTEXT_PROMPT = """You are an expert A-level Mathematics content creator specializing in the Edexcel syllabus.
Use the provided reference question+answer as inspiration ONLY for style, topic, difficulty, and structure.
Create a NEW and ORIGINAL A-level Mathematics question and a detailed solution.
"""

# How closely to stick to the reference:
# - "inspired" (default): fresh values & wording, same skill
# - "near_copy": keep structure/wording as close as possible; change only what's necessary (e.g., drawing → text-based)
GENERATION_STYLE = os.getenv("GENERATION_STYLE", "inspired")  # "inspired" | "near_copy"

# Visual Keywords for detecting visual content needs
VISUAL_KEYWORDS = [
    "graph", "graphs", "sketch", "sketched", "diagram", "diagrams",
    "figure", "figures", "plot", "plots", "draw", "drawn", "drawing"
]

# --- Upload / pipeline toggles ---
# Where generated questions are stored.
# Keep "Topics" for current behavior, or pass a user-scoped root from the caller, e.g. "Users/{uid}/Uploads/{uploadId}"
DEFAULT_COLLECTION_ROOT = os.getenv("DEFAULT_COLLECTION_ROOT", "Topics")

# Write behavior: "preserve" (skip if doc exists) or "refresh" (merge/update existing)
WRITE_MODE = os.getenv("WRITE_MODE", "preserve")  # "preserve" | "refresh"

# If True, the pipeline will proceed when only questions are present (no answers PDF).
ALLOW_QUESTIONS_ONLY = _env_bool("ALLOW_QUESTIONS_ONLY", True)

# Optional: limit processing to specific main question numbers (e.g., "1,2,5")
QUESTIONS_TO_PROCESS = _env_list("QUESTIONS_TO_PROCESS")  # e.g., ["1","2","5"] or None

# Skip the Firestore upload step (useful for local testing)
SKIP_UPLOAD = _env_bool("SKIP_UPLOAD", False)

# --- CAS configuration ---
# CAS policy for final-answer validation: "off" | "prefer" | "require"
# - off:    don’t run CAS checks
# - prefer: run CAS; if it fails but AI checker passes, keep the question (log cas_ok=False)
# - require: run CAS; if it fails, treat as rejected and trigger one retry with feedback
CAS_POLICY = os.getenv("CAS_POLICY", "off")
CAS_NUMERIC_TOL = _env_float("CAS_NUMERIC_TOL", 1e-6)

# Attach a short CAS report into logs/feedback when available
CAS_ATTACH_REPORT = _env_bool("CAS_ATTACH_REPORT", True)

# --- Topic Metadata ---
# Keys MUST match the topic_id used by the pipeline (derived from filenames/job names).
TOPIC_METADATA = {
    "polynomial": {
        "topicName": "Polynomials",
        "section": "Algebra",
        "status": "active",
    },
    # Current run’s topic ID (typo preserved intentionally so uploads succeed):
    "surds and incdeces questions": {
        "topicName": "Surds and Indices",
        "section": "Algebra",
        "status": "active",
    },
    # If you later rename your PDFs to the correct spelling and want to migrate,
    # you can predefine the corrected key too:
    # "surds and indices questions": {
    #     "topicName": "Surds and Indices",
    #     "section": "Algebra",
    #     "status": "active",
    # },
}

if __name__ == "__main__":
    # Quick sanity check
    print(f"A_Level Project Directory: {A_LEVEL_DIR}")
    print(f"Looking for .env at: {ENV_PATH}")
    print(f"Google API Key Loaded: {'Yes' if GOOGLE_API_KEY else 'No - CHECK .env PATH AND CONTENT!'}")
    print(f"Gemini Model: {GEMINI_MODEL_NAME}")
    print(f"Firebase Service Account Key Path: {FIREBASE_SERVICE_ACCOUNT_KEY_PATH}")
    print("Firebase service account key JSON found." if os.path.exists(FIREBASE_SERVICE_ACCOUNT_KEY_PATH)
          else f"Warning: Firebase key NOT found at {FIREBASE_SERVICE_ACCOUNT_KEY_PATH}")
    print(f"Firebase Project ID: {FIREBASE_PROJECT_ID}")
    print(f"Input PDF Directory: {INPUT_PDF_DIR}")
    print(f"Number of label patterns defined: {len(LABEL_PATTERNS)}")
    print(f"Log level: {LOG_LEVEL}")
    print(f"GENERATION_STYLE: {GENERATION_STYLE}")
    print(f"CAS_POLICY: {CAS_POLICY}")
    print(f"CAS_NUMERIC_TOL: {CAS_NUMERIC_TOL}")
    print(f"CAS_ATTACH_REPORT: {CAS_ATTACH_REPORT}")
    print(f"SKIP_UPLOAD: {SKIP_UPLOAD}")