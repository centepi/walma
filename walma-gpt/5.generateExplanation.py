import json
import re
import os
from openai import OpenAI
from dotenv import load_dotenv

# -------------------- CONFIG --------------------
load_dotenv()  # Load variables from .env file

QUESTIONS_DIR = "levels"
ENRICHED_DIR = "levels_enriched"
TRACKER_FILE = "explainedLevels.json"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

os.makedirs(ENRICHED_DIR, exist_ok=True)

# -------------------- PROMPT SETUP --------------------
def get_explanation_prompt(question):
    return r"""
You are a math tutor for first-year university students. Your job is to walk through the following question **as if the student doesn't know how to do any part of it yet.**

Your explanation must:
- Break down **every small step** in full detail
- Assume the student does **not** know how to rearrange equations, take derivatives, or set up integrals unless you explain it
- Include **each intermediate computation**
- Write **plain language for each concept**, followed by the math
- End with a clear statement of how we reached the answer

Use LaTeX for all math and formatting:
- \( ... \) for inline math
- \[ ... \] for block math

Only return the explanation as a **JSON list of strings** like:
[
  "Step 1: Begin by doing X...",
  "...",
  "Final answer is Y."
]

Do NOT wrap it in a code block.
Do NOT return anything else.
Do NOT escape extra backslashes.

Question:
""" + json.dumps(question['questionParts'], indent=2) + """

Correct Answer:
""" + json.dumps(question['correctAnswer']) + """

Please return only the explanation as a list of strings.
"""

# -------------------- LOAD TRACKER --------------------
if os.path.exists(TRACKER_FILE):
    with open(TRACKER_FILE, "r", encoding="utf-8") as f:
        explained = set(json.load(f))
else:
    explained = set()

# -------------------- PROCESS FILES --------------------
for filename in os.listdir(QUESTIONS_DIR):
    if not filename.endswith(".json") or filename in explained:
        continue

    with open(os.path.join(QUESTIONS_DIR, filename), "r", encoding="utf-8") as f:
        level_data = json.load(f)

    success = True

    for i, q in enumerate(level_data.get("questions", [])):
        prompt = get_explanation_prompt(q)

        response = client.chat.completions.create(
            model="gpt-4-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful AI tutor."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=1500
        )

        result_text = response.choices[0].message.content.strip()

        # Remove code blocks
        if result_text.startswith("```json") and result_text.endswith("```"):
            result_text = result_text[7:-3].strip()

        # Sanitize unescaped backslashes
        result_text = re.sub(r'(?<!\\)\\(?![\\"/bfnrtu])', r'\\\\', result_text)

        try:
            explanation = json.loads(result_text)
            q["explanationParts"] = explanation
        except Exception as e:
            print(f"❌ Failed to parse JSON for question {i+1} in {filename}:", e)
            success = False
            break  # Retry later

    if success:
        out_path = os.path.join(ENRICHED_DIR, filename)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(level_data, f, indent=2)
        print(f"✅ Enriched explanations saved: {out_path}")

        explained.add(filename)
        with open(TRACKER_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(list(explained)), f, indent=2)
    else:
        print(f"⏭️ Skipped {filename} due to error. Will retry later.")
        break
