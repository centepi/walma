# 2.group.py

import json
import os
import re
from dotenv import load_dotenv
import argparse # For command-line arguments

# -------------------- CONFIG --------------------
load_dotenv()
# Default input/output can be overridden by command-line args
DEFAULT_INPUT_DIR = "." # Assuming extracted JSONs are in the current directory
DEFAULT_OUTPUT_DIR = "grouped_output"

# Potential headers/footers to remove (add more specific regexes if needed)
CLEANING_PATTERNS = [
    re.compile(r"C1 Differentiation.*?PhysicsAndMathsTutor\.com", re.IGNORECASE),
    re.compile(r"Page \d+ of \d+", re.IGNORECASE),
    # Add more general or specific patterns for your PDFs
]

# Keywords that might indicate the start of an answer section
ANSWER_SECTION_KEYWORDS = [
    "answers",
    "solutions",
    "mark scheme",
    "marking scheme",
    "answer key"
]

# Regex to identify various label formats (numbers, letters, roman numerals)
# It captures the main value of the label for normalization.
# Order matters: more specific patterns first if ambiguity.
# Now captures: 1., 1), (1), (1). | a., a), (a), (a). | i., i), (i), (i).
# Allows for optional space after label.
LABEL_PATTERNS = [
    # Format: (regex_pattern, type, value_group_index_in_match)
    # Numeric labels: 1., (1), 12.
    (re.compile(r"^\s*(?P<label_match>(?P<value>\d{1,2}))\s*[.)]"), "num", "value"),
    (re.compile(r"^\s*(?P<label_match>\(\s*(?P<value>\d{1,2})\s*\))\s*[.]?"), "num", "value"),
    # Alphabetic labels: a., (a), Z. (case-insensitive for matching, stored as lower)
    (re.compile(r"^\s*(?P<label_match>(?P<value>[a-zA-Z]))\s*[.)](?![a-zA-Z])"), "alpha", "value"), # Negative lookahead for things like "e.g."
    (re.compile(r"^\s*(?P<label_match>\(\s*(?P<value>[a-zA-Z])\s*\))\s*[.]?"), "alpha", "value"),
    # Roman numeral labels (simplified: i, ii, iii, iv, v, vi, vii, viii, ix, x - case-insensitive)
    (re.compile(r"^\s*(?P<label_match>(?P<value>ix|iv|v?i{0,3}|x))\s*[.)]", re.IGNORECASE), "roman", "value"),
    (re.compile(r"^\s*(?P<label_match>\(\s*(?P<value>ix|iv|v?i{0,3}|x)\s*\))\s*[.]?", re.IGNORECASE), "roman", "value"),
]

# -------------------- TEXT CLEANING --------------------
def clean_text(text):
    for pattern in CLEANING_PATTERNS:
        text = pattern.sub("", text)
    # Remove excessive newlines
    text = re.sub(r'\n\s*\n', '\n\n', text)
    return text.strip()

# -------------------- TEXT STITCHING --------------------
def stitch_text(pages):
    return "\n\n".join([clean_text(p["page_text"]) for p in pages if p.get("page_text")])

# -------------------- ITEM EXTRACTION (Improved) --------------------
def extract_labeled_items(full_text):
    """
    Extracts all labeled items from text.
    Returns a list of dictionaries, each representing an item.
    e.g., [{'id': '1', 'type': 'num', 'raw_label': '1.', 'content': '...'},
            {'id': 'a', 'type': 'alpha', 'raw_label': '(a)', 'content': '...'}]
    """
    lines = full_text.splitlines()
    extracted_items = []
    current_item_content = []
    current_item_label_info = None

    for line_num, line_text in enumerate(lines):
        line_text_stripped = line_text.strip()
        if not line_text_stripped: # Skip empty lines, but they might delimit content
            if current_item_label_info: # Add to current content if item is active
                 current_item_content.append("") # Preserve paragraph breaks
            continue

        matched_label = None
        label_text_on_line = ""
        label_type = ""
        normalized_label_value = ""

        for pattern, l_type, val_group_name in LABEL_PATTERNS:
            match = pattern.match(line_text_stripped)
            if match:
                label_text_on_line = match.group("label_match")
                normalized_label_value = match.group(val_group_name).lower() # Normalize to lowercase
                label_type = l_type
                matched_label = True
                break # Found a label for this line

        if matched_label:
            # If there was a previously active item, save it
            if current_item_label_info:
                extracted_items.append({
                    "id": current_item_label_info["id"],
                    "type": current_item_label_info["type"],
                    "raw_label": current_item_label_info["raw_label"],
                    "content": "\n".join(current_item_content).strip()
                })
            
            # Start new item
            current_item_label_info = {
                "id": normalized_label_value,
                "type": label_type,
                "raw_label": label_text_on_line
            }
            current_item_content = [line_text_stripped[len(label_text_on_line):].strip()]
        elif current_item_label_info:
            # This line is part of the content of the current labeled item
            current_item_content.append(line_text_stripped)

    # Add the last processed item
    if current_item_label_info:
        extracted_items.append({
            "id": current_item_label_info["id"],
            "type": current_item_label_info["type"],
            "raw_label": current_item_label_info["raw_label"],
            "content": "\n".join(current_item_content).strip()
        })
        
    return extracted_items

# -------------------- SECTION SPLITTING (Revised) --------------------
def split_questions_and_answers(full_text, all_extracted_items):
    """
    Tries to split text into question and answer sections.
    If an explicit keyword is found, splits there.
    Otherwise, uses the list of all_extracted_items to find an implicit split point.
    Returns two lists of items: question_items, answer_items
    """
    question_items = []
    answer_items = []

    # 1. Try explicit keyword-based splitting
    split_point_char_index = -1
    answer_section_start_keyword_found = None

    for keyword in ANSWER_SECTION_KEYWORDS:
        # Search for whole word, case insensitive
        match = re.search(r'\b' + re.escape(keyword) + r'\b', full_text, re.IGNORECASE)
        if match:
            # Heuristic: check if this keyword is on its own line or prominent
            line_start = full_text.rfind('\n', 0, match.start()) + 1
            line_end = full_text.find('\n', match.end())
            if line_end == -1: line_end = len(full_text)
            line_containing_keyword = full_text[line_start:line_end].strip()
            
            # If keyword is a substantial part of the line, consider it a separator
            if len(line_containing_keyword) < len(keyword) * 3 : # Arbitrary threshold
                split_point_char_index = match.start()
                answer_section_start_keyword_found = keyword
                print(f"ℹ️ Found explicit separator keyword: '{answer_section_start_keyword_found}'")
                break
    
    if split_point_char_index != -1:
        question_text_segment = full_text[:split_point_char_index]
        answer_text_segment = full_text[split_point_char_index:] # Include keyword line in answers for now
        
        # Re-extract items for each segment if explicit split is used
        # (Alternatively, filter all_extracted_items based on their original position if available)
        print("INFO: Re-extracting items based on explicit split.")
        question_items = extract_labeled_items(question_text_segment)
        answer_items = extract_labeled_items(answer_text_segment)

        # Remove any answer section header from the first answer item if needed
        if answer_items and answer_section_start_keyword_found:
            first_answer_content = answer_items[0]['content']
            # Try to remove the keyword line from the content of the first answer
            # This is a simple attempt; might need refinement
            header_pattern = re.compile(r'^.*?' + re.escape(answer_section_start_keyword_found) + r'.*?\n?', re.IGNORECASE | re.DOTALL)
            cleaned_content = header_pattern.sub('', first_answer_content, 1).strip()
            if len(cleaned_content) < len(first_answer_content): # Check if something was removed
                 answer_items[0]['content'] = cleaned_content
            if not answer_items[0]['content'] and not answer_items[0]['id']: # if item became empty
                answer_items.pop(0)

    else:
        # 2. Try implicit splitting using all_extracted_items
        print("⚠️ No explicit answer section keyword found. Attempting implicit split...")
        if not all_extracted_items:
            print("❌ No items extracted from document. Cannot perform implicit split.")
            return [], []

        seen_top_level_ids = {} # Store first occurrence index of top-level (numeric) item IDs
        split_item_index = -1

        for i, item in enumerate(all_extracted_items):
            # Consider numeric items as primary cues for restarting (e.g. Q1, Q2... then A1, A2...)
            # Also consider if the sequence of sub-labels resets (e.g. 1a, 1b, then 1a again)
            if item['type'] == 'num': # Focus on main numeric labels for split detection
                if item['id'] in seen_top_level_ids:
                    # This numeric ID has been seen before. This is a strong candidate for split point.
                    # Example: Q1, Q2, Q3, ... Q1 (Answer), Q2 (Answer)
                    print(f"ℹ️ Implicit split: Numeric label '{item['id']}' (item {i}) previously seen at item {seen_top_level_ids[item['id']]}. Assuming start of answers.")
                    split_item_index = i
                    break
                seen_top_level_ids[item['id']] = i
            # More sophisticated logic could look for out-of-sequence sub-labels too,
            # but that adds complexity. Start with numeric label repetition.

        if split_item_index != -1:
            question_items = all_extracted_items[:split_item_index]
            answer_items = all_extracted_items[split_item_index:]
        else:
            print("⚠️ Could not determine implicit split point. Assuming all items are questions or structure is unknown.")
            # Fallback: treat all as questions, or handle as error depending on requirements
            question_items = all_extracted_items
            answer_items = [] # Or raise an error: raise ValueError("Could not split Q&A")

    return question_items, answer_items

# -------------------- MATCHING QUESTIONS TO ANSWERS (Revised) --------------------
def match_q_and_a(question_items_list, answer_items_list):
    grouped_output = []
    current_main_question_for_grouping = None

    # Create a dictionary for quick answer lookup: {'normalized_id': item_content}
    # Handle potential duplicate answer IDs by storing a list of contents (though ideally IDs are unique per section)
    answers_dict = {}
    for ans_item in answer_items_list:
        if ans_item['id'] not in answers_dict:
            answers_dict[ans_item['id']] = []
        answers_dict[ans_item['id']].append(ans_item['content'])
    
    # Helper to get an answer, consuming it if multiple exist for the same ID
    def get_answer_content(label_id):
        if label_id in answers_dict and answers_dict[label_id]:
            return answers_dict[label_id].pop(0) # Get and remove first available answer for this ID
        return f"Answer for {label_id} not found or already used"

    for q_item in question_items_list:
        q_id = q_item['id']
        q_content = q_item['content']
        q_type = q_item['type']
        q_raw_label = q_item['raw_label']

        if q_type == 'num': # Main question
            current_main_question_for_grouping = {
                "question_number": q_id,
                "raw_label": q_raw_label,
                "main_question_text": q_content,
                "solution_text": get_answer_content(q_id),
                "subquestions": []
            }
            grouped_output.append(current_main_question_for_grouping)
        elif q_type in ['alpha', 'roman']: # Subquestion
            if current_main_question_for_grouping:
                current_main_question_for_grouping['subquestions'].append({
                    "part_label": q_id,
                    "raw_label": q_raw_label,
                    "question_text": q_content,
                    "solution_text": get_answer_content(q_id)
                })
            else:
                # Orphan subquestion (appeared before a main numeric question)
                print(f"⚠️ Orphan subquestion '{q_raw_label}' (ID: {q_id}). Adding as standalone.")
                grouped_output.append({
                    "question_number": f"orphan_{q_id}",
                    "raw_label": q_raw_label,
                    "main_question_text": q_content,
                    "solution_text": get_answer_content(q_id),
                    "subquestions": []
                })
        else: # Unknown type
             print(f"❓ Unknown item type for label '{q_raw_label}' (ID: {q_id}). Skipping.")


    # Check for any unused answers
    unused_answers = {k: v for k, v in answers_dict.items() if v}
    if unused_answers:
        print(f"⚠️ Warning: {len(unused_answers)} answer ID(s) had unused content: {list(unused_answers.keys())}")
        # Optionally append them to the output if desired
        # for ans_id, ans_contents in unused_answers.items():
        #     for i, ans_content in enumerate(ans_contents):
        #         grouped_output.append({
        #             "question_number": f"unused_answer_{ans_id}" + (f"_part{i+1}" if len(ans_contents) > 1 else ""),
        #             "raw_label": f"Answer {ans_id}",
        #             "main_question_text": "N/A - Unused Answer",
        #             "solution_text": ans_content,
        #             "subquestions": []
        #         })


    return grouped_output

# -------------------- MAIN PROCESSING --------------------
def process_single_file(input_json_path, output_dir):
    base_name = os.path.basename(input_json_path)
    output_json_name = base_name.replace("_extracted.json", "_grouped.json")
    output_json_path = os.path.join(output_dir, output_json_name)

    print(f"\n📄 Processing: {input_json_path}")
    if not os.path.exists(input_json_path):
        print(f"❌ Input file '{input_json_path}' not found.")
        return

    with open(input_json_path, "r", encoding="utf-8") as f:
        data_from_extraction_script = json.load(f)

    # Stitch and clean all text first
    stitched_full_text = stitch_text(data_from_extraction_script["pages"])
    
    # Extract ALL labeled items from the entire document first
    print("🧠 Extracting all labeled items from document...")
    all_items_in_doc = extract_labeled_items(stitched_full_text)
    print(f"Found {len(all_items_in_doc)} potential items in total.")
    if not all_items_in_doc:
        print("❌ No labeled items found in the document. Cannot proceed.")
        # Optionally save an empty grouped file or an error status
        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump({"error": "No labeled items found", "source_file": input_json_path}, f, indent=2, ensure_ascii=False)
        return

    # Split into question and answer item lists
    print("🔪 Splitting into question and answer sections...")
    question_items_list, answer_items_list = split_questions_and_answers(stitched_full_text, all_items_in_doc)
    print(f"Identified {len(question_items_list)} question items and {len(answer_items_list)} answer items.")

    if not question_items_list:
        print("⚠️ No question items identified after splitting. Output might be incomplete.")
    if not answer_items_list:
        print("⚠️ No answer items identified after splitting. Solutions will be missing.")


    print("🔗 Matching questions to answers...")
    matched_data = match_q_and_a(question_items_list, answer_items_list)

    num_q = sum(1 for item in matched_data if "main_question_text" in item and item.get("question_number","").startswith("orphan_") == False and item.get("question_number","").startswith("unused_answer_") == False)
    num_sub_q = sum(len(item.get("subquestions", [])) for item in matched_data if "main_question_text" in item)
    print(f"📊 Matched {num_q} top-level questions and {num_sub_q} subquestions.")

    os.makedirs(output_dir, exist_ok=True)
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(matched_data, f, indent=2, ensure_ascii=False)
    print(f"✅ Saved grouped output to {output_json_path}")


def main():
    parser = argparse.ArgumentParser(description="Group extracted PDF text into Q&A pairs.")
    parser.add_argument(
        "input_files",
        metavar="INPUT_JSON",
        type=str,
        nargs='*', # Allow multiple files or a wildcard pattern if shell expands it
        help=f"Path to one or more '*_extracted.json' files. If empty, processes all in {DEFAULT_INPUT_DIR}."
    )
    parser.add_argument(
        "--input_dir",
        type=str,
        default=DEFAULT_INPUT_DIR,
        help=f"Directory to search for '*_extracted.json' files if no specific files are provided (default: {DEFAULT_INPUT_DIR})"
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory to save grouped JSON files (default: {DEFAULT_OUTPUT_DIR})"
    )
    args = parser.parse_args()

    files_to_process = args.input_files
    if not files_to_process: # No specific files given, scan input_dir
        if not os.path.isdir(args.input_dir):
            print(f"❌ Input directory '{args.input_dir}' not found.")
            return
        files_to_process = [
            os.path.join(args.input_dir, f)
            for f in os.listdir(args.input_dir)
            if f.lower().endswith("_extracted.json")
        ]
        if not files_to_process:
            print(f"❌ No '*_extracted.json' files found in '{args.input_dir}'.")
            return
        print(f"Found {len(files_to_process)} files to process in directory '{args.input_dir}'.")


    for input_json_path in sorted(files_to_process): # Sort for consistent processing order
        process_single_file(input_json_path, args.output_dir)

if __name__ == "__main__":
    main()