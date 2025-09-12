import os
import re  # For LABEL_PATTERNS
from dotenv import load_dotenv

# --- Project paths ---
A_LEVEL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Expect .env one level ABOVE A_Level (e.g., your project root)
ENV_PATH = os.path.join(os.path.dirname(A_LEVEL_DIR), ".env")
load_dotenv(dotenv_path=ENV_PATH)

# --- API and Model Configuration ---
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
MATHPIX_APP_ID = os.getenv("MATHPIX_APP_ID")
MATHPIX_APP_KEY = os.getenv("MATHPIX_APP_KEY")

if not GOOGLE_API_KEY:
    print(f"Warning: GOOGLE_API_KEY not found. Looked for .env at: {ENV_PATH}")
    print("Content generation will fail. Ensure .env is in the project root and contains your key.")

GEMINI_MODEL_NAME = "gemini-2.5-pro"  # or your preferred model

# --- Firebase Configuration ---
FIREBASE_SERVICE_ACCOUNT_KEY_PATH = os.path.join(A_LEVEL_DIR, "config", "firebase_service_account.json")
FIREBASE_PROJECT_ID = "walma-609e7"

# --- File/Directory Paths (relative to A_Level folder) ---
INPUT_PDF_DIR = os.path.join(A_LEVEL_DIR, "input_pdfs")

PROCESSED_DATA_DIR = os.path.join(A_LEVEL_DIR, "processed_data")
EXTRACTED_ITEMS_SUBDIR = "01_extracted_items"
PAIRED_REFS_SUBDIR = "02_paired_references"

# --- PDF Parsing Configuration ---
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
LOG_LEVEL = "DEBUG"  # options: DEBUG, INFO, WARNING, ERROR

# --- Gemini Generation Context Prompt ---
GENERATION_CONTEXT_PROMPT = """You are an expert A-level Mathematics content creator specializing in the Edexcel syllabus.
Use the provided reference question+answer as inspiration ONLY for style, topic, difficulty, and structure.
Create a NEW and ORIGINAL A-level Mathematics question and a detailed solution.
"""

# --- Visual Keywords for detecting visual content needs ---
VISUAL_KEYWORDS = [
    "graph", "graphs", "sketch", "sketched", "diagram", "diagrams",
    "figure", "figures", "plot", "plots", "draw", "drawn", "drawing"
]

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
