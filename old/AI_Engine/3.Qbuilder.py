import json
import os
import re
from openai import OpenAI
from dotenv import load_dotenv

# -------------------- CONFIG --------------------
load_dotenv()  # Load variables from .env file

INPUT_FILE = "2grouped_questions.json"
OUTPUT_DIR = "levels"
os.makedirs(OUTPUT_DIR, exist_ok=True)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# -------------------- HARD-CODED PROMPT WITH CONTEXT --------------------
SYSTEM_PROMPT = """
CONTEXT: This worksheet is designed for a wide range of math courses: A-level, IB, and university-level mathematics.

When you generate solution steps, each step must have these fields:
- step_type: a short, descriptive label (e.g. "differentiation (chain rule)", "trig identity", "matrix eigenvalues", "algebraic simplification", etc.).
  There is NO fixed list of step types; choose any label that best describes the mathematical operation or reasoning in that step.
- input_expr: the main math expression or object that step is operating on (or "" if not applicable).
- output_expr: the result of that operation (or "" if not applicable).
- explanation: a short, plain-text explanation of what is happening in this step.

For each generated question, also tag its difficulty as 'easy', 'medium', or 'hard' RELATIVE to typical students at this level. 
Use these guidelines:
- Easy: Routine question, direct use of definitions/theorems/techniques practiced extensively.
- Medium: Requires combining multiple ideas or a less obvious method.
- Hard: Requires deeper insight, chaining multiple concepts, or non-routine applications.

For each question you generate, return a JSON object with these fields:
- question_text: a clearly stated problem or prompt
- difficulty: "easy", "medium", or "hard"
- diagram_equations: a list of equations if a sketch/graph is involved (otherwise an empty list)
- solution_steps: an array of step objects, each with:
    {
      "step_type": "<string>",
      "input_expr": "<string>",
      "output_expr": "<string>",
      "explanation": "<string>"
    }

ALWAYS return valid JSON (one object or an array of objects). No additional text, no code fences.
"""

def escape_unescaped_backslashes(text):
    return re.sub(r'(?<!\\)\\(?![\\/\"bfnrtu])', r'\\\\', text)

def sanitize_json_text(text):
    # Remove triple backticks and 'json' if present
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    # Escape unescaped backslashes
    text = escape_unescaped_backslashes(text)
    return text

with open(INPUT_FILE, "r", encoding="utf-8") as infile:
    all_blocks = json.load(infile)

for idx, block in enumerate(all_blocks):
    print(f"🔨 Processing Q{idx+1}...")

    question_bundle = block["main_question_text"].strip() + "\n"
    if "subquestions" in block:
        for subq in block["subquestions"]:
            label = subq.get("part_label", "")
            question_bundle += f"\n({label}) {subq['question_text']}\nSolution: {subq['solution_text']}\n"
    else:
        question_bundle += "\n(No subquestions found.)"

    user_prompt = f"""
Here is a worked example question and its solutions.

Input:
{question_bundle}
"""

    response = client.chat.completions.create(
        model="gpt-4-turbo",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.4,
        max_tokens=3000
    )

    result_text = response.choices[0].message.content.strip()
    result_text = sanitize_json_text(result_text)

    # --- Retry logic for JSON parsing ---
    for attempt in range(3):
        try:
            generated_questions = json.loads(result_text)
            break  # Successfully parsed!
        except Exception as e:
            print(f"❌ JSON parsing failed for Q{idx+1} (attempt {attempt+1}): {e}")
            if attempt == 2:
                print("---- Raw Output Start ----")
                print(result_text[:1500])
                print("---- Raw Output End ----")
                # Save the bad output for inspection
                bad_path = os.path.join(OUTPUT_DIR, f"BAD_calc1_q{idx+1}.txt")
                with open(bad_path, "w", encoding="utf-8") as f:
                    f.write(result_text)
                print(f"⚠️ Gave up on Q{idx+1}, bad output saved to {bad_path}")
                generated_questions = None
                break
            print("♻️ Retrying with error context...")
            fix_prompt = f"The following JSON is invalid due to: {e}\nPlease ONLY return a valid JSON object:\n\n{result_text}"
            retry = client.chat.completions.create(
                model="gpt-4-turbo",
                messages=[
                    {"role": "system", "content": "You are a JSON fixer. Return only corrected JSON."},
                    {"role": "user", "content": fix_prompt}
                ],
                temperature=0,
                max_tokens=3000
            )
            result_text = sanitize_json_text(retry.choices[0].message.content.strip())

    if not generated_questions:
        continue  # Skip to next block if this one failed

    # Handle both dict and list outputs for safety
    if isinstance(generated_questions, dict):
        generated_questions = [generated_questions]
    elif not isinstance(generated_questions, list):
        print(f"❌ Unexpected output format for Q{idx+1}")
        continue

    out_path = os.path.join(OUTPUT_DIR, f"calc1_q{idx+1}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(generated_questions, f, indent=2)

    print(f"✅ Saved {len(generated_questions)} new questions to {out_path}")

print("🎉 All done.")
