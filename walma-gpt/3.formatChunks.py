import json
import os
from openai import OpenAI
from dotenv import load_dotenv

# -------------------- CONFIG --------------------
load_dotenv()  # Load variables from .env file

INPUT_FILE = "week_plan.json"
OUTPUT_FILE = "formatted_levels.json"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)


# -------------------- LOAD CHUNKS --------------------
with open(INPUT_FILE, "r", encoding="utf-8") as f:
    chunks = json.load(f)

# -------------------- FORMAT EACH CHUNK --------------------
levels = []

for i, chunk in enumerate(chunks):
    print(f"📦 Formatting chunk {i + 1}/{len(chunks)}...")

    system_prompt = """
You are helping build a math learning app.

For each input, return a 5–6 word description of what the student will learn from the content. Do NOT include a title. Do NOT rephrase the content. Just generate a short description of the learning goal.

⚠️ Return only the description as a raw string. Nothing else.
"""

    user_prompt = f"""
Here is the raw learning content:

{chunk}

What is this about? Return just a short description, no punctuation, 5–6 words max.
"""

    response = client.chat.completions.create(
        model="gpt-4-turbo",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.2,
        max_tokens=30
    )

    short_description = response.choices[0].message.content.strip()

    level = {
        "title": f"Level {i + 1}",
        "description": short_description,
        "content": chunk.strip()
    }
    levels.append(level)

# -------------------- SAVE STRUCTURED LEVELS --------------------
with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(levels, f, indent=2)

print(f"✅ Saved {len(levels)} structured levels to {OUTPUT_FILE}")
