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

# ✅ NEW chart plotter (no legacy imports)
# NOTE: adjust this import path ONLY if your new package lives elsewhere.
from pipeline_scripts.dynamic_chart_plotter.plotter import dynamic_chart_plotter
from pipeline_scripts.dynamic_chart_plotter.utils import validate_config

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

        # Always run validation, but treat issues as warnings (do NOT gate plotting).
        try:
            issues = validate_config(visual_data)
        except Exception as ex:
            issues = [f"validate_config raised exception: {ex}"]

        if issues:
            print("Validation Issues (warnings):")
            for issue in issues:
                print(f"  ⚠️  {issue}")
        else:
            print("✅ Configuration is valid!")

        # --- SPLIT PATH: Firestore-safe copy vs Plot/Client numeric copy ---

        # A. Create a Firestore-safe copy (do NOT overwrite the numeric visual_data)
        # IMPORTANT: keep TABLE charts unmodified (tables are content, not numeric geometry).
        try:
            sanitized_data = firestore_sanitizer.sanitize_for_firestore(visual_data)

            # Restore any table charts from the original visual_data so tables never get "Firestore-mangled".
            if isinstance(visual_data, dict) and isinstance(sanitized_data, dict):
                charts_key = "charts" if "charts" in visual_data else "graphs"
                orig_charts = visual_data.get(charts_key, []) or []
                sani_charts = sanitized_data.get(charts_key, []) or []

                if isinstance(orig_charts, list) and isinstance(sani_charts, list) and len(orig_charts) == len(sani_charts):
                    for i, (orig_c, _) in enumerate(zip(orig_charts, sani_charts)):
                        if isinstance(orig_c, dict) and str(orig_c.get("type", "")).strip().lower() == "table":
                            sani_charts[i] = orig_c
                    sanitized_data[charts_key] = sani_charts

            content_object["visual_data_firestore"] = sanitized_data
        except Exception as ex:
            logger.error(f"Failed to sanitize visual_data for Firestore: {ex}")

        # B. Use ORIGINAL visual_data for plotting and for the client
        charts = []
        if isinstance(visual_data, dict):
            charts = visual_data.get("charts", visual_data.get("graphs", [])) or []

        # ✅ CHANGE: ALWAYS generate an SVG if visual_data exists (including table-only).
        fig = None
        try:
            fig = dynamic_chart_plotter(visual_data)

            buffer = io.BytesIO()
            fig.savefig(
                buffer,
                format="svg",
                bbox_inches="tight",
                pad_inches=0.02,
            )
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
        finally:
            try:
                if fig is not None:
                    plt.close(fig)
            except Exception:
                pass
    else:
        logger.debug("No visual data generated.")

    return content_object