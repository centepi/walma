import os
import re
import json
from config import settings
from . import utils
from . import document_analyzer
from . import document_sorter
from . import item_matcher
from . import content_creator
from . import firebase_uploader
from . import content_checker

logger = utils.setup_logger(__name__)


# ---------- grouping logic ----------

def group_paired_items(paired_refs):
    """
    Groups a flat list of items into hierarchical structures for context gathering.
    This version uses the item's ID to detect the start of a new main question group.
    """
    grouped_questions = []
    current_main_question_group = None
    current_main_question_id = None

    for pair in paired_refs:
        question_id = pair.get("question_id")
        if not question_id:
            logger.warning("Skipping a pair because it lacks a 'question_id'.")
            continue

        # Extract the main question number (e.g., '4' from '4b' or '12' from '12ai')
        match = re.match(r'(\d+)', question_id)
        if not match:
            logger.warning(f"Could not determine main question number from id: '{question_id}'. Skipping.")
            continue

        main_id = match.group(1)

        # If the main question number changes, start a new group.
        if main_id != current_main_question_id:
            current_main_question_id = main_id
            current_main_question_group = {"main_pair": pair, "sub_question_pairs": []}
            grouped_questions.append(current_main_question_group)
        # Otherwise, if it's the same main question, add it as a sub-question.
        else:
            if current_main_question_group:
                current_main_question_group["sub_question_pairs"].append(pair)
            else:
                # Edge case safeguard.
                logger.warning(
                    f"Found a sub-question pair (id: {question_id}) with no preceding main question. "
                    "Creating a new group for it."
                )
                current_main_question_group = {"main_pair": pair, "sub_question_pairs": []}
                grouped_questions.append(current_main_question_group)

    logger.info(f"Grouped items into {len(grouped_questions)} main question structures.")
    return grouped_questions




def convert_raw_to_required(raw_data):
    # Extract the question stem from the first question item
    question_stem = raw_data['questions'][0]['content']
    
    # Build a dictionary for answers by ID
    answers_by_id = {ans['id']: ans['content'] for ans in raw_data['answers']}
    
    # Prepare the parts
    parts = []
    for question in raw_data['questions'][1:]:  # skip the first item (stem)
        part_label = question['raw_label'].strip('()') if question['raw_label'] else ''
        question_text = question['content']
        solution_text = answers_by_id.get(question['id'], '')

        parts.append({
            'part_label': part_label,
            'question_text': question_text,
            'solution_text': solution_text
        })

    # Build the final structured format
    required_format = {
        'question_stem': question_stem,
        'parts': parts,
        'calculator_required': False,  # You can update this dynamically if needed
        'topic': raw_data.get('name', 'general'),
        'question_number': raw_data['questions'][1]['id'],  # assumes part a follows q number
        'total_marks': None  # Set manually if known
    }

    return required_format

# --- Example usage ---

import json



# Convert and print result

# print(json.dumps(structured_data, indent=4, ensure_ascii=False))

def get_max_question_id(db_client):
    # from google.cloud import firestore

    # # Initialize Firestore client
    # db = firestore.Client()

    # Reference to the collection
    collection_name = 'UserQuestions'
    collection_ref = db_client.collection(collection_name)

    # Get all documents in the collection
    docs = collection_ref.stream()

    # Track whether the collection has any documents
    has_documents = False
    max_question_id = None

    for doc in docs:
        has_documents = True
        data = doc.to_dict()
        question_id = int(data.get('question_id'))

        if isinstance(question_id, (int, float)):  # Ensure it's numeric
            if max_question_id is None or question_id > max_question_id:
                max_question_id = question_id

    if not has_documents:
        print(f"The collection '{collection_name}' does not exist or is empty.")
        return 1
    else:
        print(f"The collection '{collection_name}' exists.")
        if max_question_id is not None:
            print(f"The maximum question_id is: {max_question_id}")
            return max_question_id+1
        else:
            print(f"No numeric 'question_id' fields found in the collection.")



# ---------- main pipeline with concise logging + run report ----------

def run_full_pipeline():
    """The main orchestrator for the 'Self-Contained Skills' generation process."""
    logger.info("--- Starting Full Content Pipeline (Generator-Checker Model) ---")

    # Start run report (also captures the per-run log file path)
    run_report = utils.start_run_report()

    # 1) Initialization
    db_client = firebase_uploader.initialize_firebase()
    gemini_content_model = content_creator.initialize_gemini_client()
    print(gemini_content_model)
    gemini_checker_model = content_checker.initialize_gemini_client()
    if not db_client or not gemini_content_model or not gemini_checker_model:
        logger.error("Initialization failed (db/model). Aborting.")
        utils.save_run_report(run_report)
        return

    # 2) Sort and Group Source Documents
    processing_jobs = document_sorter.sort_and_group_documents(settings.INPUT_PDF_DIR)
    if not processing_jobs:
        logger.warning("Smart Sorter found no processing jobs. Exiting pipeline.")
        utils.save_run_report(run_report)
        return

    run_report["totals"]["jobs"] = len(processing_jobs)

    # 3) Process Each Job
    for job in processing_jobs:
        print('llm - ',job)
        structured_data = convert_raw_to_required(job)
        print('required - ', structured_data)
        print(json.dumps(structured_data, indent=4, ensure_ascii=False))
        new_question_id = str(get_max_question_id(db_client))
        print(new_question_id)
        new_question_object = structured_data
        new_question_object['question_id'] = new_question_id
        # job_type = job.get("type")
        # base_name = job.get("name", "untitled")
        # logger.info(f"Processing Job: '{base_name}' (Type: {job_type})")

        # job_summary = utils.new_job_summary(base_name, job_type)
        collection_path = f"UserQuestions"
        ok = firebase_uploader.upload_content(db_client, collection_path, new_question_id, new_question_object)
        print(ok)
        # q_items, a_items = None, None

        # if job_type == "paired":
        #     q_items = job.get("questions")
        #     a_items = job.get("answers")
        # elif job_type == "interleaved":
        #     q_items, a_items = document_sorter.split_interleaved_items(job.get("content"))

        # if not (q_items and a_items):
        #     logger.warning(f"Skipping job '{base_name}' due to missing question or answer items.")
        #     run_report["jobs"].append(job_summary)
        #     continue


        # 3a) Match items
    #     paired_refs, _ = item_matcher.match_items_with_ai(q_items, a_items)
    #     if not paired_refs:
    #         logger.warning(f"No item pairs could be matched for job '{base_name}'. Skipping.")
    #         run_report["jobs"].append(job_summary)
    #         continue

    #     hierarchical_groups = group_paired_items(paired_refs)
    #     job_summary["groups"] = len(hierarchical_groups)
    #     run_report["totals"]["groups"] += len(hierarchical_groups)

    #     # 4) Generate, Verify (with retry), and Upload
    #     questions_to_process = getattr(settings, "QUESTIONS_TO_PROCESS", None)  # None or list of main IDs

    #     for group in hierarchical_groups:
    #         # Filter by main id if needed
    #         main_q_pair = group.get("main_pair", {}) or {}
    #         main_qid = main_q_pair.get("question_id") or (main_q_pair.get("original_question", {}) or {}).get("id", "N/A")
    #         m = re.match(r"(\d+)", str(main_qid))
    #         main_id_for_filter = m.group(1) if m else str(main_qid)

    #         if questions_to_process and main_id_for_filter not in questions_to_process:
    #             logger.info(f"Skipping group {main_id_for_filter} due to QUESTIONS_TO_PROCESS filter.")
    #             continue

    #         all_pairs = [group["main_pair"]] + group.get("sub_question_pairs", [])
    #         full_reference_text = "\n".join(
    #             f"Part ({p.get('question_id') or (p.get('original_question', {}) or {}).get('id', '')}): "
    #             f"{((p.get('original_question', {}) or {}).get('content') or '').strip()}"
    #             for p in all_pairs
    #         )

    #         for target_pair in all_pairs:
    #             qid = target_pair.get("question_id") or (target_pair.get("original_question", {}) or {}).get("id", "N/A")
    #             q_text = ((target_pair.get("original_question", {}) or {}).get("content") or "").strip()

    #             # Prefer worked solution; fall back to notes
    #             a_text = (
    #                 ((target_pair.get("original_answer", {}) or {}).get("content") or "") or
    #                 ((target_pair.get("original_answer", {}) or {}).get("pedagogical_notes") or "")
    #             ).strip()

    #             if not q_text:
    #                 logger.info(f"Skipping '{qid}': no source question text.")
    #                 continue

    #             job_summary["parts_processed"] += 1
    #             run_report["totals"]["parts_processed"] += 1

    #             new_question_object = None
    #             feedback_object = None
    #             correction_feedback = None

    #             for attempt in range(2):  # 1 initial + 1 retry on checker feedback
    #                 logger.info(f"{base_name} | {qid} | Attempt {attempt + 1}/2")

    #                 generated_object = content_creator.create_question(
    #                     gemini_content_model,
    #                     full_reference_text,              # full group context
    #                     target_pair,                      # the specific Q/A pair for this part
    #                     correction_feedback=correction_feedback
    #                 )

    #                 if not generated_object:
    #                     logger.error(f"{base_name} | {qid} | Generation failed on attempt {attempt + 1}.")
    #                     continue

    #                 feedback_object = content_checker.verify_and_mark_question(
    #                     gemini_checker_model,
    #                     generated_object
    #                 )

    #                 if feedback_object and feedback_object.get("is_correct"):
    #                     new_question_object = generated_object
    #                     logger.info(f"{base_name} | {qid} | ✅ Verified on attempt {attempt + 1} (marks={feedback_object.get('marks', 0)})")
    #                     break
    #                 elif feedback_object:
    #                     correction_feedback = feedback_object.get("feedback") or ""
    #                     # Demote attempt-level rejection to DEBUG to keep console concise
    #                     logger.debug(f"{base_name} | {qid} | Rejected (attempt {attempt + 1}) — {utils.truncate(correction_feedback, 120)}")
    #                     logger.debug(f"{base_name} | {qid} | Full reject reason: {correction_feedback}")
    #                 else:
    #                     logger.error(f"{base_name} | {qid} | Checker failed (attempt {attempt + 1}).")
    #                     correction_feedback = "Checker did not return feedback. Regenerate from scratch."

    #             # Finalize and upload if verified
    #             if new_question_object:
    #                 # Clean empty visual_data for your app model (as before)
    #                 if new_question_object.get("visual_data") == {}:
    #                     logger.debug(f"{base_name} | {qid} | Removing empty 'visual_data'.")
    #                     del new_question_object["visual_data"]

    #                 new_question_id = str(qid)  # use the hierarchical id like '1a', '3', etc.
    #                 new_question_object["topic"] = base_name
    #                 new_question_object["question_number"] = new_question_id
    #                 new_question_object["total_marks"] = (feedback_object or {}).get("marks", 0)

    #                 # Save locally for audit/debug
    #                 os.makedirs("processed_data", exist_ok=True)
    #                 utils.save_json_file(new_question_object, f"processed_data/{base_name}_Q{new_question_id}.json")

    #                 # Console summary for upload
    #                 stem_preview = (new_question_object.get("question_stem") or new_question_object.get("prompt") or "").replace("\n", " ")
    #                 logger.info(
    #                     f"{base_name} | {qid} | Uploading — Marks={new_question_object['total_marks']}, Stem='{stem_preview[:60]}...'"
    #                 )
                    # Upload via uploader
                    # collection_path = f"UserQuestions"
                    # ok = firebase_uploader.upload_content(db_client, collection_path, new_question_id, new_question_object)
                #     if ok:
                #         job_summary["uploaded_ok"] += 1
                #         run_report["totals"]["uploaded_ok"] += 1
                #     else:
                #         job_summary["upload_failed"] += 1
                #         run_report["totals"]["upload_failed"] += 1

                #     job_summary["verified"] += 1
                #     run_report["totals"]["verified"] += 1
                # else:
                #     job_summary["rejected"] += 1
                #     run_report["totals"]["rejected"] += 1
                #     # Record last known reason
                #     if correction_feedback:
                #         utils.append_failure(job_summary, str(qid), correction_feedback)
                #     else:
                #         utils.append_failure(job_summary, str(qid), "verification failed")

    #     run_report["jobs"].append(job_summary)

    # logger.info("--- Full Content Pipeline Finished ---")
    # utils.save_run_report(run_report)


if __name__ == '__main__':
    run_full_pipeline()
