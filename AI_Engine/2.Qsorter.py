#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
2.groupPDF.py

Usage:
  python 2.groupPDF.py <JSON_FILE_OR_FOLDER> [--output <filename>]

If <JSON_FILE_OR_FOLDER> is a single JSON file (e.g., "mydoc_extracted.json"),
we load it and parse out the text, then ask GPT to group into question objects.

If it's a folder, we look for all *.json files in that folder and process them
one by one, creating an output file for each, named <original>_grouped.json.

We rely on "page_text" fields from the JSON output of 1.extractPDF.py.

GPT will produce a structured JSON array of main questions/subparts:
[
  {
    "main_question_text": "...",
    "subquestions": [
      {
        "part_label": "a",
        "question_text": "...",
        "solution_text": "...",
        "diagram_description": null
      },
      ...
    ]
  }
]
"""

import json
import os
import re
import sys
from dotenv import load_dotenv
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# -------------------- CONFIG --------------------
load_dotenv()

# Default output if processing a single file
DEFAULT_OUTPUT_FILE = "2grouped_questions.json"


# -------------------- HELPER: ESCAPE UNESCAPED BACKSLASHES --------------------
def escape_unescaped_backslashes(text):
    """
    Replace unescaped backslashes with double backslashes to avoid JSON parse issues.
    """
    return re.sub(r'(?<!\\)\\(?![\\/\"bfnrtu])', r'\\\\', text)


# -------------------- MAIN PROCESSING: STITCH + GPT PARSE --------------------
def stitch_and_group(json_path, output_file=None):
    """
    1) Load <json_path>, which should contain a structure like:
       {
         "source_pdf": ...,
         "total_pages": ...,
         "pages": [
           { "page": 1, "page_text": "...", "latex": "...(optional)..." },
           ...
         ]
       }
    2) We gather all "page_text" into a single string, skipping empty pages.
    3) Prompt GPT with a 'system_prompt' and 'user_prompt' to parse into grouped Q&As.
    4) Write the output JSON to <output_file>.
    """

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # We expect "pages" to be an array
    pages = data.get("pages", [])
    stitched_content = []

    # If you only want to start once a question marker is found, you can replicate that logic.
    # For now, we just take all page_text:
    for page_obj in pages:
        text = page_obj.get("page_text", "").strip()
        if text:
            stitched_content.append(text)

    stitched_text = "\n\n".join(stitched_content)
    if not stitched_text.strip():
        print(f"❌ No usable text found in {json_path}. Skipping.")
        return

    print(f"🧩 Loaded {len(pages)} pages from {json_path}, total chars = {len(stitched_text)}")

    # GPT PROMPTS
    system_prompt = """
You are parsing a university-level math assignment.

Your job:
- For each main question (usually numbered [1], [2], [3], ...), identify any setup text that applies to all subparts.
- For each subpart ((a), (b), (c) or i, ii, iii), create an object with:
    - part_label (e.g., "a", "b", or "i", "ii")
    - question_text (prompt for that subpart)
    - solution_text (corresponding answer/explanation)
    - diagram_description (if present, else null) (We have no real diagrams now, so likely null.)

Output as a JSON array of objects, each with:
- main_question_text: string (can be empty if there’s no setup)
- subquestions: array as described above.

Do not paraphrase or rewrite. Do not add commentary. Only valid JSON. Do not wrap in a code block.
"""

    user_prompt = f"""
Here is the assignment text (possibly partial Q or A only):

{stitched_text}

Group it into main questions with subparts as described above, returning a JSON array of grouped objects.
"""

    # GPT request
    response = client.chat.completions.create(model="gpt-4-turbo",
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ],
    temperature=0.2,
    max_tokens=3900)

    raw_output = response.choices[0].message.content.strip()

    # SANITIZATION
    def parse_and_sanitize(raw):
        if raw.startswith("```json") and raw.endswith("```"):
            raw = raw[7:-3].strip()
        raw = escape_unescaped_backslashes(raw)
        return raw

    sanitized = parse_and_sanitize(raw_output)

    # Attempt up to 3 times to fix JSON if needed
    for attempt in range(3):
        try:
            grouped_questions = json.loads(sanitized)
            break
        except json.JSONDecodeError as e:
            print(f"❌ JSON parsing failed on attempt {attempt+1}:", e)
            if attempt == 2:
                # Final attempt
                print("🔎 Final raw output snippet:", sanitized[:1000])
                return
            print("♻️ Retrying with error context...")

            retry_prompt = f"""
The following JSON was invalid due to this error: {e}

Please fix ONLY the JSON formatting, return a valid JSON array,
and do not change any content.

Here is the broken JSON:

{sanitized}
"""
            retry_response = client.chat.completions.create(model="gpt-4-turbo",
            messages=[
                {"role": "system", "content": "You are a JSON fixer. Return only corrected JSON."},
                {"role": "user", "content": retry_prompt}
            ],
            temperature=0,
            max_tokens=3900)
            sanitized = parse_and_sanitize(retry_response.choices[0].message.content.strip())

    # If we get here with no exception, we have grouped_questions
    if not output_file:
        # Default naming scheme: <json_path>_grouped.json
        base = os.path.splitext(os.path.basename(json_path))[0]
        output_file = f"{base}_grouped.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(grouped_questions, f, indent=2, ensure_ascii=False)

    print(f"✅ Extracted and saved {len(grouped_questions)} main questions to {output_file}")


# -------------------- MAIN CLI ENTRY --------------------
def main():
    """
    Possible CLI usage:
      python 2.groupPDF.py input.json
        -> produces input_grouped.json

      python 2.groupPDF.py WS
        -> processes all *.json in folder WS, each to <basename>_grouped.json

      python 2.groupPDF.py input.json --output custom_out.json
        -> writes to custom_out.json
    """
    if len(sys.argv) < 2:
        print("Usage: python 2.groupPDF.py <JSON_FILE_OR_FOLDER> [--output <filename>]")
        sys.exit(1)

    input_arg = sys.argv[1]
    custom_output = None

    # Check for optional --output param
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            custom_output = sys.argv[idx + 1]

    if os.path.isdir(input_arg):
        # Process all *.json in that folder
        json_files = [f for f in os.listdir(input_arg) if f.lower().endswith(".json")]
        json_files.sort()

        for jf in json_files:
            json_path = os.path.join(input_arg, jf)
            # We'll ignore --output in folder mode, and produce <basename>_grouped.json
            print(f"\n=== Processing JSON: {json_path} ===")
            stitch_and_group(json_path, None)

    elif os.path.isfile(input_arg) and input_arg.lower().endswith(".json"):
        # Single file
        stitch_and_group(input_arg, custom_output)
    else:
        print(f"❌ Invalid input: {input_arg} is neither a folder nor a .json file.")
        sys.exit(1)


if __name__ == "__main__":
    main()
