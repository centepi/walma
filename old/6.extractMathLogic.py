import os
import json
import re

# -------------------- CONFIG --------------------
LEVELS_DIR = "levels_enriched"  # Full level data
WOLFRAM_QUERIES_DIR = "wolfram_queries"  # New folder for stripped math logic
os.makedirs(WOLFRAM_QUERIES_DIR, exist_ok=True)

# -------------------- HELPER: Extract clean expression --------------------
def extract_math(expression):
    """Strip LaTeX formatting like \( ... \), \[ ... \]"""
    return re.sub(r"\\\(|\\\)|\\\[|\\\]", "", expression).strip()

# -------------------- MAIN EXTRACTION --------------------
for filename in os.listdir(LEVELS_DIR):
    if not filename.endswith(".json"):
        continue

    with open(os.path.join(LEVELS_DIR, filename), "r", encoding="utf-8") as f:
        level = json.load(f)

    questions = level.get("questions") or level.get("Questions")
    if not questions:
        continue

    output = {}

    for i, q in enumerate(questions):
        qid = f"Q{i+1}"
        logic_block = {}

        # Extract question text
        question_text = " ".join(q.get("questionParts", []))
        logic_block["question"] = question_text

        # Extract correct answer math
        correct = q.get("correctAnswer")
        if correct:
            logic_block["correct_math"] = extract_math(correct)

        # Extract all options (optional but useful)
        options = q.get("options", [])
        logic_block["all_options"] = [extract_math(opt) for opt in options]

        # Extract equations from explanation if any
        explanation = q.get("explanationParts", [])
        math_lines = [extract_math(line) for line in explanation if re.search(r"\\\(|\\\[", line)]
        if math_lines:
            logic_block["explanation_equations"] = math_lines

        output[qid] = logic_block

    # Save stripped output for Wolfram
    out_path = os.path.join(WOLFRAM_QUERIES_DIR, filename)
    with open(out_path, "w", encoding="utf-8") as out:
        json.dump(output, out, indent=2)

print("✅ Extracted Wolfram-friendly math logic into:", WOLFRAM_QUERIES_DIR)
