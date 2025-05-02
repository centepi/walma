import json
import re
import os
from openai import OpenAI
from dotenv import load_dotenv

# -------------------- CONFIG --------------------
load_dotenv()  # Load variables from .env file

INPUT_FILE = "formatted_levels.json"
LEVEL_OUTPUT_DIR = "levels"
CHUNK_TRACKER_FILE = "builtChunks.json"  # Keeps track of completed chunks

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)


# -------------------- LOAD CHUNKS --------------------
with open(INPUT_FILE, "r", encoding="utf-8") as f:
    chunks = json.load(f)

if os.path.exists(CHUNK_TRACKER_FILE):
    with open(CHUNK_TRACKER_FILE, "r", encoding="utf-8") as f:
        built_indices = set(json.load(f))
else:
    built_indices = set()

# -------------------- FIND NEXT UNBUILT CHUNK --------------------
next_index = None
for i, chunk in enumerate(chunks):
    if i not in built_indices:
        next_index = i
        break

if next_index is None:
    print("✅ All chunks have been built into levels.")
    exit()

chunk = chunks[next_index]
original_content = chunk["content"]
description = chunk.get("description", "")

# -------------------- GPT PROMPT --------------------
system_prompt = r"""
You are an expert AI math tutor creating a high-quality multiple choice level for a learning app called ALMA.
Use the provided explanation as inspiration to:

Create a complete level with **3 rigorous, logically connected questions** that:
- Begin with setup or basic understanding
- Progress into deeper interpretation or problem solving
- End with a question as challenging as the original explanation

Each question must include:
- `questionParts`: a list of text and LaTeX strings
- `options`: 4 total (1 correct, 3 plausible wrong)
- `correctAnswer`: must exactly match one of the `options`
- `explanationParts`: a clear, step-by-step explanation that walks through the reasoning

Also include:
- `diagram_request`: a suggested diagram that could help clarify concepts

Your output must be **valid JSON** and nothing else.

Use:
- \\( ... \\) for inline math
- \\[ ... \\] for block math

Do **not** wrap in a code block.
Do **not** escape extra backslashes. Just make the output valid JSON.
"""

user_prompt = f"""
Title: {chunk['title']}
Description: {description}

Content:
{original_content}

Please generate a full 3-question level as described.
"""
# -------------------- GPT CALL --------------------
response = client.chat.completions.create(
    model="gpt-4-turbo",
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ],
    temperature=0.3,
    max_tokens=3000
)

result_text = response.choices[0].message.content.strip()

# -------------------- SANITIZE RESPONSE --------------------
if result_text.startswith("```json") and result_text.endswith("```"):
    result_text = result_text[7:-3].strip()

# Replace unescaped backslashes before parsing
result_text = re.sub(r'(?<!\\)\\(?![\\"/bfnrtu])', r'\\\\', result_text)

# -------------------- PARSE AND SAVE --------------------
try:
    parsed = json.loads(result_text)
    os.makedirs(LEVEL_OUTPUT_DIR, exist_ok=True)

    level_id = f"calc2_week9_level{next_index + 1}"
    filename = os.path.join(LEVEL_OUTPUT_DIR, f"{level_id}.json")

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(parsed, f, indent=2)

    print(f"✅ Saved: {filename}")

    # Mark chunk as built
    built_indices.add(next_index)
    with open(CHUNK_TRACKER_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(built_indices)), f, indent=2)

except Exception as e:
    print("❌ Failed to parse extracted JSON:", e)
    print("--- Extracted JSON ---\n", result_text)