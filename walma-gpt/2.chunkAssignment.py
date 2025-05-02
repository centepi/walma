import json
import os
from openai import OpenAI
from dotenv import load_dotenv

# -------------------- CONFIG --------------------
load_dotenv()  # Load .env variables from the root directory

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

INPUT_FILE = "extracted_combined.json"
OUTPUT_FILE = "week_plan.json"

# -------------------- LOAD INPUT --------------------
with open(INPUT_FILE, "r", encoding="utf-8") as f:
    pages = json.load(f)

stitched_content = []
seen_question_marker = False

for page in pages:
    text = page["mathpix_text"].strip()
    if not seen_question_marker:
        if "[1]" in text:
            seen_question_marker = True
        else:
            continue

    stitched_content.append(text)

    desc = page.get("diagram_description", "").strip() if isinstance(page.get("diagram_description"), str) else ""
    if desc and "no visual content" not in desc.lower() and "no diagrams" not in desc.lower():
        stitched_content.append(f"(Diagram Description: {desc})")

stitched_text = "\n\n".join(stitched_content)
print(f"🧩 Stitched assignment loaded. Total characters: {len(stitched_text)}")

# -------------------- GPT CHUNKING --------------------
system_prompt = """
You are helping split a math assignment into logical learning chunks for an education app.

Split the stitched content into **at least 4 and at most 5** chunks.
Each chunk should include a complete question with its answer or related discussion — never cut a question or solution in half. Keep them grouped.

⚠️ VERY IMPORTANT:
- Do NOT paraphrase or rewrite.
- Do NOT add JSON or labels.
- Return clean chunks, each separated clearly by the divider:

--- CHUNK ---

Each chunk will become one level. Each level should feel self-contained and teach a single topic or idea clearly.
"""

user_prompt = f"""
Here is the stitched assignment content:

{stitched_text}

Split it into 4–5 complete learning chunks, using the format above.
"""

response = client.chat.completions.create(
    model="gpt-4-turbo",
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ],
    temperature=0.2,
    max_tokens=3900
)

# -------------------- PARSE + SAVE --------------------
raw_output = response.choices[0].message.content.strip()
chunks = [c.strip() for c in raw_output.split("--- CHUNK ---") if c.strip()]

print(f"✅ Extracted {len(chunks)} clean chunks.")
if len(chunks) < 4:
    print("⚠️ Warning: GPT returned fewer than 4 chunks. You may want to review manually.")

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(chunks, f, indent=2)

print(f"✅ Saved to {OUTPUT_FILE}")
