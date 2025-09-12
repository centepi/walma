import wolframalpha
import json
import os
import re
from dotenv import load_dotenv

# -------------------- CONFIG --------------------
load_dotenv()  # Load variables from .env file

WOLFRAM_APP_ID = os.getenv("WOLFRAM_APP_ID")
LEVELS_DIR = "levels_enriched"
CHECKED_DIR = "levels_verified"
LOG_DIR = "wolfram_logs"
os.makedirs(CHECKED_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

client = wolframalpha.Client(WOLFRAM_APP_ID)

# -------------------- WOLFRAM QUERY FUNCTION --------------------
def query_wolfram(expression):
    try:
        result = client.query(expression + ", exact result")
        answer = next(result.results).text
        return {"success": True, "response": answer}
    except Exception as e:
        return {"success": False, "error": str(e)}

# -------------------- CORE CHECKING SCRIPT --------------------
for filename in os.listdir(LEVELS_DIR):
    if not filename.endswith(".json"):
        continue

    with open(os.path.join(LEVELS_DIR, filename), "r", encoding="utf-8") as f:
        level_data = json.load(f)

    log_output = []
    any_errors = False

    for i, q in enumerate(level_data.get("questions", [])):
        question_text = " ".join(q.get("questionParts", []))
        answer_text = q.get("correctAnswer", "")

        if not answer_text:
            log_output.append({
                "question": question_text,
                "result": "Missing correctAnswer"
            })
            any_errors = True
            continue

        # Strip LaTeX formatting like \( \) or \[ \]
        raw_expr = re.sub(r"\\\(|\\\)|\\\[|\\\]", "", answer_text).strip()

        response = query_wolfram(raw_expr)

        if response["success"]:
            log_output.append({
                "question": question_text,
                "expected": raw_expr,
                "wolfram": response["response"],
                "match": None  # Can be used later by GPT
            })
        else:
            log_output.append({
                "question": question_text,
                "expected": raw_expr,
                "wolfram": None,
                "error": response["error"]
            })
            any_errors = True

    # Save log file for this level
    log_filename = filename.replace(".json", "_wolfram.json")
    with open(os.path.join(LOG_DIR, log_filename), "w", encoding="utf-8") as logf:
        json.dump(log_output, logf, indent=2)

    # Save untouched verified copy of the level
    with open(os.path.join(CHECKED_DIR, filename), "w", encoding="utf-8") as f:
        json.dump(level_data, f, indent=2)

    # Print summary only
    if any_errors:
        print(f"❌ Errors found in {filename}")
    else:
        print(f"✅ No errors in {filename}")

print("\n✅ Wolfram check complete.")
