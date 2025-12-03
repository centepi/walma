# pipeline_scripts/text_gen_pipeline/drill_runner.py

import os
import uuid
import concurrent.futures
from typing import Tuple, Any, List

from config import settings
from pipeline_scripts import utils, content_creator, content_checker, checks_cas, cas_validator, firebase_uploader
from pipeline_scripts.firebase_uploader import UploadTracker
# Import the creator from the file sitting next to this one
from pipeline_scripts.text_gen_pipeline import drill_creator

logger = utils.setup_logger(__name__)

# --- Task State Class ---
# This tracks the life of a single question in the batch
class DrillTask:
    def __init__(self, topic, course, difficulty, question_type, details, question_num):
        self.input_data = {
            "topic": topic, 
            "course": course, 
            "difficulty": difficulty,
            "question_type": question_type, 
            "additional_details": details
        }
        self.question_num = str(question_num)
        self.attempt = 0
        self.generated_object = None
        self.feedback_object = None
        self.cas_ok = True
        self.cas_last_report = None
        self.correction_feedback = None
        self.is_complete = False

# --- Worker Functions (Run in Parallel) ---

def parallel_drill_gen_worker(params: Tuple[Any, DrillTask]) -> DrillTask:
    """Worker 1: Generates the JSON question"""
    model, task = params
    task.attempt += 1
    logger.info(f"Drill Q{task.question_num} | Attempt {task.attempt}")
    
    # CALLS THE CREATOR
    generated = drill_creator.create_drill_question(
        model, task.input_data, task.correction_feedback
    )
    
    if generated:
        # Check if we need to add an answer spec for CAS
        spec = checks_cas.build_answer_spec_from_generated(generated)
        if spec:
            generated["answer_spec"] = spec
        task.generated_object = generated
    
    return task

def parallel_cas_worker(task: DrillTask) -> DrillTask:
    """Worker 2: Validates Math using SymPy (CAS)"""
    if settings.CAS_POLICY == "off" or not task.generated_object:
        return task
        
    try:
        cas_ok, report = cas_validator.validate(task.generated_object)
        task.cas_ok = cas_ok
        task.cas_last_report = report
    except Exception as e:
        task.cas_ok = True
        task.cas_last_report = {"kind": "internal", "reason": f"CAS Error: {e}"}
        
    if not task.cas_ok and settings.CAS_POLICY == "require":
        reason = (task.cas_last_report or {}).get("reason", "Unknown")
        task.correction_feedback = f"CAS Validation Failed: {reason}"
        
    return task

def parallel_verify_worker(params: Tuple[Any, DrillTask]) -> DrillTask:
    """Worker 3: Uses AI to double-check the question logic"""
    model, task = params
    if not task.generated_object:
        return task
        
    feedback = content_checker.verify_and_mark_question(model, task.generated_object)
    task.feedback_object = feedback
    return task

# --- Main Background Runner ---

def run_text_drill_background(
    uid: str,
    upload_id: str,
    topic: str,
    course: str,
    difficulty: str,
    quantity: int = 3,
    question_type: str = "Standard",
    additional_details: str = "",
    folder_id: str = "",
    unit_name: str = ""
):
    """
    Executed as a BackgroundTask. 
    1. Generates N questions in parallel.
    2. Manages UploadTracker (for UI progress).
    3. Retries failed generations.
    4. Saves to Firestore.
    """
    logger.info(f"Starting Drill Background Job: {topic} ({quantity} questions)")

    # 1. Init Services
    db_client = firebase_uploader.initialize_firebase()
    model_gen = content_creator.initialize_gemini_client()
    model_check = content_checker.initialize_gemini_client()
    tracker = UploadTracker(uid, upload_id)
    
    if not all([db_client, model_gen, model_check]):
        tracker.error("AI Service Initialization Failed")
        return

    # 2. Prepare Tasks
    tasks = [
        DrillTask(topic, course, difficulty, question_type, additional_details, i+1) 
        for i in range(quantity)
    ]
    
    # 3. Processing Loop (Pass 1 - Generate All)
    tracker.event_note(f"Generating {quantity} questions...")
    
    # We use ThreadPoolExecutor to run 5 things at once
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        # Step A: Generate
        tasks = list(executor.map(parallel_drill_gen_worker, [(model_gen, t) for t in tasks]))
        # Step B: CAS Validate
        tasks = list(executor.map(parallel_cas_worker, tasks))
        # Step C: AI Verify
        tasks = list(executor.map(parallel_verify_worker, [(model_check, t) for t in tasks]))

    # 4. Filter Retries (Identify which ones failed)
    retry_list = []
    for t in tasks:
        is_good = t.feedback_object and t.feedback_object.get("is_correct")
        cas_pass = t.cas_ok or settings.CAS_POLICY != "require"
        
        if is_good and cas_pass:
            t.is_complete = True
        else:
            # Prepare feedback for the retry
            if not t.correction_feedback:
                if t.feedback_object:
                    t.correction_feedback = t.feedback_object.get("feedback")
                else:
                    t.correction_feedback = "Generation failed or invalid JSON."
            retry_list.append(t)

    # 5. Retry Loop (Pass 2 - Fix Failures)
    if retry_list:
        tracker.event_note(f"Refining {len(retry_list)} questions...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            retry_list = list(executor.map(parallel_drill_gen_worker, [(model_gen, t) for t in retry_list]))
            retry_list = list(executor.map(parallel_cas_worker, retry_list))
            retry_list = list(executor.map(parallel_verify_worker, [(model_check, t) for t in retry_list]))

    # 6. Finalize & Upload
    collection_path = f"Users/{uid}/Uploads/{upload_id}/Questions"
    uploaded_count = 0
    
    for t in tasks:
        # Determine final status (check if retry succeeded or original was good)
        is_good = t.feedback_object and t.feedback_object.get("is_correct")
        cas_pass = t.cas_ok or settings.CAS_POLICY != "require"

        if t.generated_object and is_good and cas_pass:
            final_obj = t.generated_object
            
            # Metadata
            final_obj["topic"] = topic
            final_obj["course"] = course
            final_obj["difficulty"] = difficulty
            final_obj["mode"] = "text_drill"
            final_obj["question_number"] = t.question_num
            final_obj["total_marks"] = t.feedback_object.get("marks", 0)
            
            # Clean empty visual data
            if final_obj.get("visual_data") == {}:
                del final_obj["visual_data"]

            # Upload 
            if firebase_uploader.upload_content(db_client, collection_path, t.question_num, final_obj):
                uploaded_count += 1
                # Fire event so UI progress bar moves
                tracker.event_question_created(label=t.question_num, index=int(t.question_num), question_id=t.question_num)
            else:
                tracker.event(type="error", message=f"Upload Failed Q{t.question_num}")
        else:
            tracker.event(type="reject", message=f"Q{t.question_num} Failed Verification")

    # 7. Close Tracker
    tracker.complete(result_unit_id=upload_id, question_count=uploaded_count)
    
    # Final Status Update
    firebase_uploader.upload_content(
        db_client,
        f"Users/{uid}/Uploads",
        upload_id,
        {"status": "complete", "drill_mode": True}
    )
    
    logger.info(f"Drill Complete. {uploaded_count}/{quantity} uploaded.")