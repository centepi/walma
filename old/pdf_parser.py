import os
import re
import pdfplumber
from config import settings
from . import utils

logger = utils.setup_logger(__name__, settings.LOG_LEVEL)

# All the functions (extract_and_clean_item_content, determine_dynamic_margin, 
# itemize_pdf_with_positional_awareness, process_pdf_to_items) are correct 
# from the last version and remain the same. I've included the full file for clarity.

def extract_and_clean_item_content(text):
    marks = []
    cleaned_text = text
    mark_pattern = re.compile(r"(\[.*?\])")
    found_marks = mark_pattern.findall(cleaned_text)
    if found_marks:
        marks = [m.strip("[]") for m in found_marks]
    cleaned_text = mark_pattern.sub("", cleaned_text)
    axis_pattern = re.compile(r"^[xy]\s*[-?\d\s.]+$", re.MULTILINE)
    cleaned_text = axis_pattern.sub("", cleaned_text)
    cleaned_text = re.sub(r'Visit http.*?\n?', '', cleaned_text, flags=re.IGNORECASE)
    cleaned_text = re.sub(r'\n\s*\n', '\n\n', cleaned_text).strip()
    return cleaned_text, marks

def determine_dynamic_margin(pdf_path, label_patterns):
    logger.info("Determining dynamic margin threshold...")
    potential_label_x_coords = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                words = page.extract_words(x_tolerance=1, y_tolerance=3)
                for word in words:
                    for pattern, _, _ in label_patterns:
                        if pattern.match(word['text']):
                            potential_label_x_coords.append(word['x0'])
                            break
    except Exception as e:
        logger.error(f"Error during dynamic margin analysis for {pdf_path}: {e}")
        return 72
    if not potential_label_x_coords:
        logger.warning("No potential labels found for dynamic margin analysis. Using default threshold.")
        return 72
    sorted_coords = sorted(list(set(potential_label_x_coords)))
    if len(sorted_coords) < 2: return 120 
    largest_gap = 0
    split_point = sorted_coords[0] + 100
    for i in range(len(sorted_coords) - 1):
        gap = sorted_coords[i+1] - sorted_coords[i]
        if gap > largest_gap:
            largest_gap = gap
            split_point = sorted_coords[i] + (gap / 2)
    if largest_gap > 150:
        dynamic_threshold = split_point
        logger.info(f"Dynamic margin threshold set to: {dynamic_threshold:.2f}")
    else:
        dynamic_threshold = 120 
        logger.info(f"No significant gap found. Using default threshold: {dynamic_threshold}")
    return dynamic_threshold

def itemize_pdf_with_positional_awareness(pdf_path, label_patterns, margin_threshold):
    extracted_items = []
    current_item_content_lines = []
    current_item_label_info = None
    current_item_bbox = {}

    def save_previous_item():
        if not current_item_label_info:
            return
        final_content = "\n".join(current_item_content_lines).strip()
        cleaned_content, extracted_marks = extract_and_clean_item_content(final_content)
        current_item_label_info['content'] = cleaned_content
        current_item_label_info['marks'] = extracted_marks
        current_item_label_info['bbox'] = [
            current_item_bbox.get('x0', 0),
            current_item_bbox.get('top', 0),
            current_item_bbox.get('x1', 0),
            current_item_bbox.get('bottom', 0)
        ]
        extracted_items.append(current_item_label_info)

    try:
        with pdfplumber.open(pdf_path) as pdf:
            logger.info(f"Opened PDF for positional parsing: {os.path.basename(pdf_path)} with {len(pdf.pages)} pages.")
            for page_num, page in enumerate(pdf.pages):
                words = page.extract_words(x_tolerance=1, y_tolerance=3, keep_blank_chars=True)
                lines = {}
                for word in words:
                    y0_key = round(word["top"] / 10) * 10
                    if y0_key not in lines: lines[y0_key] = []
                    lines[y0_key].append(word)

                for y0_key in sorted(lines.keys()):
                    line_words = sorted(lines[y0_key], key=lambda w: w['x0'])
                    line_text = " ".join(w['text'] for w in line_words).strip()
                    if not line_text: continue
                    
                    first_word = line_words[0]
                    matched_label_this_line = False
                    
                    if first_word['x0'] < margin_threshold:
                        for pattern, l_type, val_group_name in label_patterns:
                            match = pattern.match(line_text)
                            if match:
                                save_previous_item()
                                label_text_on_line = match.group("label_match")
                                normalized_label_value = match.group(val_group_name).lower()
                                current_item_label_info = {
                                    "id": normalized_label_value, "type": l_type, 
                                    "raw_label": label_text_on_line, "page_number": page_num
                                }
                                current_item_bbox = {'x0': first_word['x0'], 'top': first_word['top'], 'x1': line_words[-1]['x1'], 'bottom': line_words[-1]['bottom']}
                                content_on_label_line = line_text[len(label_text_on_line):].strip()
                                current_item_content_lines = [content_on_label_line] if content_on_label_line else []
                                matched_label_this_line = True
                                logger.debug(f"Page {page_num+1}: Found valid label '{label_text_on_line}'")
                                break
                    
                    if not matched_label_this_line:
                        if current_item_label_info:
                            current_item_content_lines.append(line_text)
                            current_item_bbox['x1'] = max(current_item_bbox.get('x1', 0), line_words[-1]['x1'])
                            current_item_bbox['bottom'] = max(current_item_bbox.get('bottom', 0), line_words[-1]['bottom'])
    except Exception as e:
        logger.error(f"An error occurred during positional parsing of {os.path.basename(pdf_path)}: {e}")
    save_previous_item()
    logger.info(f"Positional itemization complete. Found {len(extracted_items)} items.")
    return extracted_items


def process_pdf_to_items(pdf_file_path):
    """Orchestrates reading a PDF and itemizing its content, returning the list."""
    logger.info(f"--- Starting PDF processing for: {os.path.basename(pdf_file_path)} ---")
    dynamic_threshold = determine_dynamic_margin(pdf_file_path, settings.LABEL_PATTERNS)
    extracted_items = itemize_pdf_with_positional_awareness(pdf_file_path, settings.LABEL_PATTERNS, dynamic_threshold)
    if not extracted_items:
        logger.warning(f"No items were extracted from {pdf_file_path}.")
    return extracted_items

# --- NEW TEST BLOCK ADDED AT THE END ---
if __name__ == '__main__':
    """
    This test runner allows you to test ONLY the PDF parser without running the full pipeline.
    It processes all PDFs in both the questions and answers directories and saves the output locally.
    """
    print("--- PDF Parser Test Runner (Saves Intermediate Files) ---")
    subdirs_to_process = [settings.QUESTIONS_PDF_SUBDIR, settings.ANSWERS_PDF_SUBDIR]
    
    for subdir_name in subdirs_to_process:
        input_dir = os.path.join(settings.INPUT_PDF_DIR, subdir_name)
        output_dir = os.path.join(settings.PROCESSED_DATA_DIR, settings.EXTRACTED_ITEMS_SUBDIR, subdir_name)
        logger.info(f"--- Scanning for PDF files in: {input_dir} ---")
        
        if not os.path.isdir(input_dir):
            print(f"❌ ERROR: Input directory not found. Please create '{input_dir}'")
            continue
            
        pdf_files = [f for f in os.listdir(input_dir) if f.lower().endswith('.pdf')]
        
        if not pdf_files:
            print(f"🤷 No PDF files found to process in '{input_dir}'.")
        else:
            logger.info(f"Found {len(pdf_files)} PDF(s) to process in '{subdir_name}': {pdf_files}")
            total_success = 0
            for filename in pdf_files:
                pdf_path = os.path.join(input_dir, filename)
                
                # Unlike the main pipeline, this test WILL save the output to a file
                # so you can inspect it.
                base_filename = os.path.splitext(filename)[0]
                output_filename = f"{base_filename}_items.json"
                output_json_path = os.path.join(output_dir, output_filename)

                # Get the items
                items = process_pdf_to_items(pdf_path)

                # If items were found, save them
                if items:
                    utils.save_json_file(items, output_json_path)
                    total_success += 1
                
            print(f"\n--- {subdir_name.capitalize()} Processing Complete ---")
            print(f"✅ Successfully processed {total_success} out of {len(pdf_files)} PDF(s).")
            if total_success > 0: print(f"Please check the output JSON files in: {output_dir}")
            
    print("\n--- All Parsing Complete ---")