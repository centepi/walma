import os
import json
import logging
import datetime
from logging.handlers import RotatingFileHandler
from typing import Tuple, Dict, Any, List
from config import settings
from pdf2image import convert_from_path  # Use pdf2image instead of fitz


# -------- logging setup --------

def setup_logger(name, level_str=settings.LOG_LEVEL):
    """
    Sets up a module logger with a console stream handler.
    IMPORTANT: propagation is ON so messages also flow to the root,
    where the per-run file handler is attached.
    """
    log_level = getattr(logging, level_str.upper(), logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)5s | %(name)s | %(message)s')

    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # Avoid duplicate console handlers on repeated imports
    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        handler.setLevel(log_level)
        logger.addHandler(handler)

    # Let messages bubble up to the root so the run file handler can capture them
    logger.propagate = True
    return logger


# --- module-level logger
logger = setup_logger(__name__)


# -------- file logger for full run --------

def _ensure_logs_dir() -> str:
    logs_dir = os.path.join(settings.A_LEVEL_DIR, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    return logs_dir


def _make_run_log_path() -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return os.path.join(_ensure_logs_dir(), f"run_{ts}.log")


def get_run_logger_and_path() -> Tuple[logging.Logger, str]:
    """
    Ensure a dedicated file handler is attached to the ROOT logger for this run,
    and return (root_logger, file_path). If already attached, reuse the same file.
    """
    root = logging.getLogger()
    # Root should capture everything; module loggers may be INFO, we still want full trace in file
    root.setLevel(logging.DEBUG)

    # If a pipeline file handler already exists, reuse it
    for h in root.handlers:
        if getattr(h, "_is_pipeline_file", False) and isinstance(h, logging.FileHandler):
            try:
                return root, h.baseFilename  # type: ignore[attr-defined]
            except Exception:
                # If baseFilename is missing for some reason, fall through to create a new one
                break

    # Otherwise create a new rotating file handler
    log_path = _make_run_log_path()
    fh = RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(logging.Formatter('%(asctime)s | %(levelname)5s | %(name)s | %(message)s'))
    fh.setLevel(logging.DEBUG)
    fh._is_pipeline_file = True  # mark so we can detect/reuse later
    root.addHandler(fh)

    return root, log_path


# -------- small text helpers --------

def truncate(text: str, limit: int = 120, ellipsis: str = "…") -> str:
    """Shorten text to 'limit' characters with a tidy word boundary if possible."""
    if not text:
        return ""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return (cut if cut else text[:limit]) + ellipsis


def make_timestamp() -> str:
    """Timestamp safe for filenames."""
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


# -------- file IO helpers --------

def load_json_file(file_path):
    """Loads data from a JSON file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"File not found: {file_path}")
        return None
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from file: {file_path}")
        return None


def save_json_file(data, file_path):
    """Saves data to a JSON file, creating directories if they don't exist."""
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        logger.info(f"Data successfully saved to {file_path}")
    except Exception as e:
        logger.error(f"Error saving JSON to file {file_path}: {e}")


# -------- pdf helper --------

def convert_pdf_page_to_image(pdf_path, page_number=0):
    """
    Converts a single page of a PDF into an image object using pdf2image.
    Defaults to the first page (page_number=0).
    Returns an image object from the Pillow library.
    """
    try:
        # pdf2image uses 1-based page numbers, so we add 1
        page_to_convert = page_number + 1
        logger.info(f"Converting page {page_to_convert} of '{os.path.basename(pdf_path)}' with pdf2image...")

        # convert_from_path returns a list of images
        images = convert_from_path(pdf_path, first_page=page_to_convert, last_page=page_to_convert)

        if images:
            logger.info("Successfully converted page to an image.")
            return images[0]  # Return the first (and only) image in the list
        else:
            logger.error(f"pdf2image returned no images for page {page_to_convert}.")
            return None

    except Exception as e:
        logger.error(f"Failed to convert PDF page with pdf2image: {e}")
        logger.error("Please ensure the 'poppler' utility is installed on your system.")
        return None


# -------- run report helpers (new) --------

def start_run_report() -> Dict[str, Any]:
    """Initialize the run report dict and capture the run log file path."""
    _, log_file = get_run_logger_and_path()
    return {
        "started_at": make_timestamp(),
        "log_file": log_file,
        "jobs": [],
        "totals": {
            "jobs": 0,
            "groups": 0,
            "parts_processed": 0,
            "verified": 0,
            "rejected": 0,
            "uploaded_ok": 0,
            "upload_failed": 0,
        }
    }


def new_job_summary(job_name: str, job_type: str) -> Dict[str, Any]:
    return {
        "job_name": job_name,
        "type": job_type,
        "groups": 0,
        "parts_processed": 0,
        "verified": 0,
        "rejected": 0,
        "uploaded_ok": 0,
        "upload_failed": 0,
        "failures": []  # list of {"question_id": str, "reason": str}
    }


def append_failure(job_summary: Dict[str, Any], question_id: str, reason: str) -> None:
    job_summary.setdefault("failures", []).append({"question_id": str(question_id), "reason": truncate(reason, 140)})


def save_run_report(run_report: Dict[str, Any]) -> str:
    """
    Persist structured run report to processed_data/run_reports and print a concise summary.
    Also prints a one-line Failures summary if any exist.
    """
    report_dir = os.path.join(settings.PROCESSED_DATA_DIR, "run_reports")
    os.makedirs(report_dir, exist_ok=True)

    stamp = run_report.get("started_at") or make_timestamp()
    report_path = os.path.join(report_dir, f"run_report_{stamp}.json")

    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(run_report, f, indent=2, ensure_ascii=False)
        logger.info(f"Run report saved: {report_path}")
    except Exception as e:
        logger.error(f"Failed to save run report: {e}")

    # Emit concise summary
    totals = run_report.get("totals", {})
    logger.info(
        "SUMMARY — Jobs=%s | Groups=%s | Parts=%s | Verified=%s | Rejected=%s | Uploaded=%s | UploadFailed=%s",
        totals.get("jobs", 0),
        totals.get("groups", 0),
        totals.get("parts_processed", 0),
        totals.get("verified", 0),
        totals.get("rejected", 0),
        totals.get("uploaded_ok", 0),
        totals.get("upload_failed", 0),
    )

    # Emit one-line failures summary
    failed: List[str] = []
    for job in run_report.get("jobs", []):
        job_name = job.get("job_name")
        for f in job.get("failures", []):
            failed.append(f"{job_name}:{f.get('question_id')} — {f.get('reason')}")

    if failed:
        logger.warning("Failures: %s", "; ".join(failed))

    return report_path


if __name__ == '__main__':
    # Simple self-test
    logger.info("--- utils.py self-test ---")
    rr = start_run_report()
    rr["totals"]["jobs"] = 1
    js = new_job_summary("demo_job", "paired")
    append_failure(js, "1a", "example failure reason that is somewhat long and will be truncated in the output if needed.")
    rr["jobs"].append(js)
    save_run_report(rr)
    logger.info("--- utils.py self-test complete ---")
