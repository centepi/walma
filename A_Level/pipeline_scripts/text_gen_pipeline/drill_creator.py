# pipeline_scripts/text_gen_pipeline/drill_creator.py
import io
import base64
import matplotlib.pyplot as plt
import google.generativeai as genai

from config import settings
from pipeline_scripts import utils
from pipeline_scripts import response_validator
from pipeline_scripts import postprocess_math
from pipeline_scripts import firestore_sanitizer
from pipeline_scripts.dynamic_chart_plotter import dynamic_chart_plotter, validate_config

from .drill_prompts import build_text_drill_prompt

from pipeline_scripts.content_creator import (
    _normalize_generated_object,
    _synthesize_answer_spec_if_missing
)

logger = utils.setup_logger(__name__)


def create_drill_question(
    gemini_model,
    task_input: dict,
    correction_feedback: str = ""
):
    """
    Generates a question from scratch using user specifications.

    This function mimics the logic of content_creator.create_question but:
    1. Uses 'build_text_drill_prompt' instead of 'build_creator_prompt'.
    2. Takes text inputs (topic, course) instead of image references.
    3. Performs the exact same Post-Processing (Math Sanitize + Visual Data Plotting).
    """
    topic = task_input.get("topic")
    course = task_input.get("course")
    difficulty = task_input.get("difficulty")
    details = task_input.get("additional_details", "")

    # 1. Build Prompt
    prompt = build_text_drill_prompt(
        topic=topic,
        course=course,
        difficulty=difficulty,
        additional_details=details,
        correction_prompt_section=correction_feedback
    )

    # 2. Call Gemini
    try:
        chat = gemini_model.start_chat()
        response = chat.send_message(prompt)
        raw_text_response = response.text
    except Exception as e:
        logger.error(f"Drill Generation Error for topic '{topic}': {e}")
        return None

    # 3. Validate JSON
    content_object = response_validator.validate_and_correct_response(
        chat, gemini_model, raw_text_response
    )

    if not content_object:
        logger.error(f"Failed to parse/validate drill response for '{topic}'.")
        return None

    # 4. Normalize & Sanitize
    content_object = _normalize_generated_object(content_object)
    content_object = postprocess_math.sanitize_generated_object(content_object)
    content_object = _synthesize_answer_spec_if_missing(content_object)

    # 5. Process Visual Data (Generate SVGs)
    visual_data = content_object.get("visual_data")
    if visual_data:
        logger.debug("Visual data present for drill question. Processing…")
        issues = validate_config(visual_data)
        if issues:
            print("Validation Issues:")
            for issue in issues:
                print(f"  ⚠️  {issue}")
        else:
            print("✅ Configuration is valid!")

            # --- SPLIT PATH: Firestore-safe copy vs Plot/Client numeric copy ---

            # A. Create a Firestore-safe copy (do NOT overwrite the numeric visual_data)
            try:
                sanitized_data = firestore_sanitizer.sanitize_for_firestore(visual_data)
                content_object["visual_data_firestore"] = sanitized_data
            except Exception as ex:
                logger.error(f"Failed to sanitize visual_data for Firestore: {ex}")

            # B. Use ORIGINAL visual_data for plotting and for the client
            charts = []
            if isinstance(visual_data, dict):
                charts = visual_data.get("charts", visual_data.get("graphs", [])) or []

            has_non_table = any(
                isinstance(c, dict) and str(c.get("type", "")).strip().lower() != "table"
                for c in charts
            )
            has_only_table = bool(charts) and not has_non_table

            if has_only_table:
                logger.debug("Visual data is table-only; skipping SVG generation.")
            else:
                try:
                    fig = dynamic_chart_plotter(visual_data)

                    buffer = io.BytesIO()
                    fig.savefig(buffer, format="svg")
                    plt.close(fig)

                    svg_data = buffer.getvalue().decode("utf-8")
                    buffer.close()

                    svg_base64 = base64.b64encode(svg_data.encode("utf-8")).decode("utf-8")

                    # UPDATED SCHEMA: svg_images array (and legacy svg_image)
                    fig_id = None
                    if charts and isinstance(charts[0], dict):
                        fig_id = charts[0].get("id")

                    content_object["svg_images"] = [{
                        "id": fig_id or "figure_1",
                        "label": "Figure 1",
                        "svg_base64": svg_base64,
                        "kind": "chart",
                    }]

                    # Backwards compatibility (remove later)
                    content_object["svg_image"] = svg_base64

                except Exception as ex:
                    logger.error(f"Failed to plot drill chart: {ex}")
    else:
        logger.debug("No visual data generated.")

    return content_object