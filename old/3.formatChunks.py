import json
import os
from openai import OpenAI
from dotenv import load_dotenv

# -------------------- CONFIG --------------------
load_dotenv()
INPUT_FILE = "week_plan.json"
OUTPUT_FILE = "formatted_questions.json"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# -------------------- LOAD GROUPED QUESTIONS --------------------
with open(INPUT_FILE, "r", encoding="utf-8") as f:
    grouped = json.load(f)

all_subquestions = []

# -------------------- PROCESS MAIN + SUBQUESTIONS --------------------
for i, main in enumerate(grouped):
    main_text = main.get("main_question_text", "")
    subqs = main.get("subquestions", [])
    for j, sub in enumerate(subqs):
        part_label = sub.get("part_label", chr(97 + j))  # fallback to 'a', 'b', etc. if missing
        sub_id = f"Q{i+1}{part_label}"
        question_text = sub.get("question_text", "")
        solution_text = sub.get("solution_text", "")
        diagram_desc = sub.get("diagram_description", None)

        # --- Generate concise dev description with GPT ---
        dev_system_prompt = """
You are an assistant summarizing a math question for an internal developer/admin dashboard.
Summarize the main math task of the following question in 6 words or fewer. No punctuation, no titles, not student-facing.
If the question is a simple computation or asks for a proof, state that directly.
Return ONLY the summary phrase.
"""
        dev_user_prompt = f"""
Main question: {main_text}

Subquestion: {question_text}
"""
        try:
            dev_response = client.chat.completions.create(
                model="gpt-4-turbo",
                messages=[
                    {"role": "system", "content": dev_system_prompt},
                    {"role": "user", "content": dev_user_prompt}
                ],
                temperature=0,
                max_tokens=30
            )
            dev_description = dev_response.choices[0].message.content.strip()
        except Exception as e:
            dev_description = "No dev description"

        # --- Assemble record ---
        all_subquestions.append({
            "question_id": sub_id,
            "main_question_text": main_text,
            "part_label": part_label,
            "question_text": question_text,
            "solution_text": solution_text,
            "diagram_description": diagram_desc,
            "dev_description": dev_description
        })

print(f"✅ Flattened {len(all_subquestions)} subquestions from {len(grouped)} main questions.")

# -------------------- SAVE STRUCTURED SUBQUESTIONS --------------------
with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(all_subquestions, f, indent=2)

print(f"✅ Saved all subquestions to {OUTPUT_FILE}")
