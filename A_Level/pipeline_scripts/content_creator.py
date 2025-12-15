import os
import re
import json
import google.generativeai as genai
from typing import Optional, Dict, Any, List  # ✅ include Dict/Any too (used in type hints)

from config import settings
from . import utils
from . import graph_utils  # ok to keep if used later
from . import response_validator
from .prompts_presets import build_creator_prompt
from .constants import CASPolicy
from . import postprocess_math  # <- math text sanitizer (minimal & safe)

# ✅ NEW chart plotter (NOT legacy)
from .dynamic_chart_plotter.plotter import dynamic_chart_plotter
from .dynamic_chart_plotter.utils import validate_config

from . import firestore_sanitizer

import datetime
import io
import base64
import matplotlib.pyplot as plt

logger = utils.setup_logger(__name__)


def initialize_gemini_client():
    """Initializes the Gemini client with the API key."""
    try:
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        logger.info(
            "Content Creator's Gemini client initialized successfully. Using model: %s",
            settings.GEMINI_MODEL_NAME,
        )
        return genai.GenerativeModel(settings.GEMINI_MODEL_NAME)
    except Exception as e:
        logger.error(f"Failed to initialize Content Creator's Gemini client: {e}")
        return None


# -------------------------
# Output normalization
# -------------------------

def _coerce_str(x):
    return x if isinstance(x, str) else ("" if x is None else str(x))


def _standard_label(idx_or_label):
    """
    Normalize a choice label to a single uppercase letter A..Z.
    Accepts raw labels like 'a', 'A)', '(b)', 'Option C', or an index.
    """
    if isinstance(idx_or_label, int):
        return chr(ord('A') + max(0, idx_or_label))
    s = _coerce_str(idx_or_label).strip()
    m = re.search(r'([A-Za-z])', s)
    if m:
        return m.group(1).upper()
    return ""


def _normalize_choices(raw):
    """
    Normalize incoming 'choices' into a list of {"label":"A","text":"..."}.
    Accepts list[str], list[dict], or dict[label->text].
    Drops empty texts. Trims strings. Returns (choices, dropped_count).
    """
    choices = []
    dropped = 0

    if raw is None:
        return [], 0

    # dict form: {"A": "...", "B": "..."}
    if isinstance(raw, dict):
        # keep stable A..Z order if possible
        items = sorted(raw.items(), key=lambda kv: _standard_label(kv[0]))
        for k, v in items:
            lab = _standard_label(k)
            txt = _coerce_str(v).strip()
            if lab and txt:
                choices.append({"label": lab, "text": txt})
            else:
                dropped += 1
        return choices, dropped

    # list form
    if isinstance(raw, list):
        # list of strings -> map to A, B, C...
        if all(isinstance(x, str) for x in raw):
            for i, txt in enumerate(raw):
                txt = _coerce_str(txt).strip()
                if txt:
                    choices.append({"label": _standard_label(i), "text": txt})
                else:
                    dropped += 1
            return choices, dropped

        # list of dicts
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                # treat as string
                txt = _coerce_str(item).strip()
                if txt:
                    choices.append({"label": _standard_label(i), "text": txt})
                else:
                    dropped += 1
                continue
            lab = _standard_label(item.get("label", i))
            txt = _coerce_str(item.get("text", "")).strip()
            if lab and txt:
                choices.append({"label": lab, "text": txt})
            else:
                dropped += 1
        # de-dup by label, first win
        seen = set()
        norm = []
        for ch in choices:
            if ch["label"] in seen:
                continue
            seen.add(ch["label"])
            norm.append(ch)
        return norm, dropped

    # unknown type
    return [], 0


def _find_choice_by_text(choices, text):
    """Find a choice whose text matches 'text' (case/space-insensitive)."""
    if not text:
        return None
    t = re.sub(r'\s+', ' ', _coerce_str(text)).strip().lower()
    for ch in choices or []:
        c = re.sub(r'\s+', ' ', _coerce_str(ch.get("text"))).strip().lower()
        if c == t:
            return ch
    return None


def _normalize_mcq_fields(obj: dict) -> dict:
    """
    If parts[0] contains 'choices', normalize:
      - parts[0].choices => [{"label":"A","text":"..."}]
      - parts[0].correct_choice => single uppercase letter matching a choice
      - final_answer => the text/value of the correct option (not the letter)
      - add top-level is_mcq: True
    If choices invalid/too few, remove MCQ fields to avoid partial/broken items.
    """
    try:
        parts = obj.get("parts") or []
        if not parts:
            return obj
        part = parts[0] or {}

        raw_choices = part.get("choices", None)
        if raw_choices is None:
            # Not an MCQ; nothing to do
            return obj

        choices, dropped = _normalize_choices(raw_choices)

        # Only keep if we have at least 3 options (prefer 4–5)
        if len(choices) < 3:
            logger.debug("MCQ normalize: insufficient choices (%d). Dropping MCQ fields.", len(choices))
            part.pop("choices", None)
            part.pop("correct_choice", None)
            return obj

        # Cap to 6 options max, keep A.. order
        choices = sorted(choices, key=lambda ch: ch["label"])[:6]
        part["choices"] = choices

        # Normalize/derive correct_choice
        cc_label = _standard_label(part.get("correct_choice", ""))
        final_answer = _coerce_str(part.get("final_answer", "")).strip()

        # If final_answer is a single letter, prefer that as cc
        if not cc_label and re.fullmatch(r"[A-Za-z]", final_answer or ""):
            cc_label = _standard_label(final_answer)

        # If still empty, try to infer by matching final_answer to a choice's text
        if not cc_label and final_answer:
            ch = _find_choice_by_text(choices, final_answer)
            if ch:
                cc_label = ch["label"]

        # If still empty, default to A
        if not cc_label:
            cc_label = "A"

        # Ensure cc exists in choices; else fallback to first
        valid_labels = {c["label"] for c in choices}
        if cc_label not in valid_labels:
            logger.debug(
                "MCQ normalize: correct_choice '%s' not in labels %s; defaulting to first.",
                cc_label,
                sorted(valid_labels),
            )
            cc_label = choices[0]["label"]

        part["correct_choice"] = cc_label

        # Ensure final_answer equals the correct option's TEXT (not just the letter)
        correct_text = next((c["text"] for c in choices if c["label"] == cc_label), "")
        if correct_text:
            part["final_answer"] = correct_text

        # Mark top-level hint
        obj["is_mcq"] = True

        # Optional: enforce a typical 4–5 option count by trimming if >5 (keep first 5)
        if len(part["choices"]) > 5:
            part["choices"] = part["choices"][:5]

        return obj
    except Exception as e:
        logger.debug("MCQ normalize: skipped due to error: %s", e)
        return obj


def _normalize_generated_object(obj: dict) -> dict:
    """
    Guard-rails for the raw model JSON:
      - ensure parts is a 1-length list with label defaulting to 'a'
      - trim strings
      - default calculator_required
      - drop empty visual_data dicts
      - MCQ-aware normalization (choices/correct_choice/final_answer/is_mcq)
    (Math-specific cleanup is handled separately by postprocess_math.)
    """
    if not isinstance(obj, dict):
        return obj or {}

    # Trim top-level strings
    for key in ("question_stem",):
        if key in obj and isinstance(obj[key], str):
            obj[key] = obj[key].strip()

    # Parts normalization
    parts = obj.get("parts") or []
    if isinstance(parts, dict):
        parts = [parts]
    if not parts:
        parts = [{
            "part_label": "a",
            "question_text": "",
            "solution_text": "",
            "final_answer": ""
        }]

    part = parts[0] or {}
    part.setdefault("part_label", "a")
    part["part_label"] = str(part["part_label"]).strip() or "a"

    for k in ("question_text", "solution_text", "final_answer"):
        if k in part and isinstance(part[k], str):
            part[k] = part[k].strip()

    obj["parts"] = [part]

    # calculator_required default
    if "calculator_required" not in obj:
        obj["calculator_required"] = False

    # Clean empty visual_data
    if isinstance(obj.get("visual_data"), dict) and not obj["visual_data"]:
        obj.pop("visual_data", None)

    # --- MCQ normalization (if choices present) ---
    obj = _normalize_mcq_fields(obj)

    return obj


# -------------------------
# Lightweight answer_spec synthesis (optional)
# -------------------------
_DERIVATIVE_CUES = re.compile(
    r"(differentiate|dy/dx|f'\(x\)|derivative\s+of|find\s+f'\(x\))",
    re.IGNORECASE,
)
_FUNC_EQ_PAT = re.compile(
    r"(?:^|[\s,:;])(?:y\s*=\s*|[a-zA-Z]\s*\(\s*x\s*\)\s*=\s*)(?P<expr>[^;.\n\r]+)",
    re.IGNORECASE,
)


def _pyexpr(s: str) -> str:
    """Normalize common math text to Python/SymPy-ish."""
    if not isinstance(s, str):
        return s
    t = s.strip()
    t = t.replace("^", "**")
    t = t.replace("×", "*").replace("·", "*")
    t = t.replace("−", "-").replace("—", "-").replace("–", "-")
    t = t.replace("ln", "log")
    return t


def _maybe_build_derivative_spec(stem: str, qtext: str, final_answer: str) -> Optional[dict]:
    """
    If the question clearly asks for a general derivative (not 'at x=a'),
    and we can spot y=f(x) / f(x)=..., build:
        {"kind":"derivative","of":"<expr>","result":"<final_answer>","order":1}
    """
    if not final_answer or not isinstance(final_answer, str):
        return None

    text = f"{stem}\n{qtext}"
    if not _DERIVATIVE_CUES.search(text):
        return None

    # Heuristic: avoid 'at x = a' pure numeric gradient questions
    if re.search(r"\bat\s*x\s*=\s*[-+]?\d+(\.\d+)?\b", text, re.IGNORECASE):
        return None

    m = _FUNC_EQ_PAT.search(text)
    if not m:
        return None

    of_expr = _pyexpr(m.group("expr"))
    res_expr = _pyexpr(final_answer)

    # Very rough guard: result should look like an expression in x (not just a number)
    if re.fullmatch(r"[-+]?\d+(\.\d+)?", res_expr):
        return None

    return {
        "kind": "derivative",
        "of": of_expr,
        "result": res_expr,
        "order": 1,
        "variables": ["x"],
    }


def _synthesize_answer_spec_if_missing(content_object: dict) -> dict:
    """
    If CAS is not OFF and answer_spec is missing, attempt a tiny set of heuristics
    to provide one. Currently supports general-derivative cases only.
    """
    try:
        if (settings.CAS_POLICY or CASPolicy.OFF).lower().strip() == CASPolicy.OFF:
            return content_object

        if isinstance(content_object.get("answer_spec"), dict):
            return content_object  # already present

        part = (content_object.get("parts") or [{}])[0]
        stem = content_object.get("question_stem", "")
        qtext = part.get("question_text", "")
        final_ans = part.get("final_answer", "")

        spec = _maybe_build_derivative_spec(stem, qtext, final_ans)
        if spec:
            content_object["answer_spec"] = spec
            logger.debug("CAS: synthesized answer_spec=%s", spec)
        return content_object
    except Exception as e:
        logger.debug("CAS: synthesize skipped due to error: %s", e)
        return content_object


# -------------------------
# Auto domain/skill anchoring (prompt-only; zero new deps)
# -------------------------

_VISUAL_CUES = re.compile(
    r"\b(diagram|figure|graph|sketch|curve|axes|plot|asymptote|locus|contour|surface|manifold|topology|homeomorph|open set|closed set|connected|compact|quotient|metric|basis|neighbourhood|neighborhood)\b",
    re.IGNORECASE
)

_ANCHOR_TOKENS = [
    "topology", "metric", "open set", "closed set", "connected", "compact",
    "continuity", "homeomorphism", "quotient", "basis", "subspace",
    "neighbourhood", "neighborhood", "accumulation point", "limit point",
    "graph", "axes", "locus", "contour", "surface", "curve",
    "proof", "show that", "hence", "therefore",
]


def _extract_anchor_terms(*texts: str, limit: int = 8) -> List[str]:
    joined = " ".join([t for t in texts if isinstance(t, str)])
    low = joined.lower()

    hits = []
    for tk in _ANCHOR_TOKENS:
        if tk in low:
            hits.append(tk)

    extra = []
    for w in re.findall(r"[a-zA-Z][a-zA-Z\-]{4,}", low):
        if w in hits:
            continue
        if any(c.isdigit() for c in w):
            continue
        if w in {"which", "their", "therefore", "where", "given", "using", "hence", "since", "prove"}:
            continue
        extra.append(w)

    out = []
    for w in hits + extra:
        if w not in out:
            out.append(w)
        if len(out) >= limit:
            break
    return out


def _build_auto_context_header(full_reference_text: str, target_part_content: str) -> str:
    visual_hint = bool(_VISUAL_CUES.search(f"{full_reference_text}\n{target_part_content}"))
    tags = _extract_anchor_terms(full_reference_text, target_part_content, limit=8)

    lines = []
    lines.append("### AUTO DOMAIN & SKILL LOCK")
    lines.append("- Stay in the SAME mathematical domain and subtopic as the source (do not switch topics).")
    lines.append("- Match difficulty and number of reasoning steps as closely as possible.")
    lines.append("- Preserve the specific skill(s) being assessed; change only surface parameters.")
    if tags:
        lines.append(f"- Source topic/skill cues: {', '.join(tags)}.")
    if visual_hint:
        lines.append(
            "- The source appears VISUAL-HEAVY. "
            "If the diagram used in the question is one listed that you can make, "
            "then include 'visual_data'. "
            "If you ever write a question and reference any visual element, "
            "it must be the case that you also produce that 'visual_data'. "
            "If the diagram they use is not one listed that you can make, "
            "then you must remake the question as close to the topic as possible "
            "without needing the visual element. "
            "Most importantly, if you reference any visual element you MUST include its respective 'visual_data' object."
        )
        lines.append("- The source appears VISUAL. For simple Cartesian cases, INCLUDE a 2D analytic graph via 'visual_data' (do not ask the student to draw). Avoid any non-graph shapes.")
    return "\n".join(lines)


# -------------------------
# Main API
# -------------------------
def create_question(
    gemini_model,
    full_reference_text,
    target_part_ref,
    correction_feedback=None,
    keep_structure: bool = False,
):
    target_part_id = target_part_ref.get("original_question", {}).get("id", "N/A")
    target_part_content = target_part_ref.get("original_question", {}).get("content", "")
    target_part_answer = target_part_ref.get("original_answer", {}).get("content", "")

    if correction_feedback:
        logger.info(f"Regenerating for part '{target_part_id}' with checker/CAS feedback.")
        logger.debug("Full correction feedback for %s: %s", target_part_id, correction_feedback)
        correction_prompt_section = (
            f"\n--- CORRECTION INSTRUCTIONS ---\n"
            f'Your previous attempt was REJECTED for the following reason: "{correction_feedback}"\n'
            f"You MUST generate the question again and fix this specific error while still following all original instructions.\n"
        )
    else:
        logger.info(f"Generating new question inspired by part '{target_part_id}'.")
        correction_prompt_section = ""

    try:
        auto_header = _build_auto_context_header(full_reference_text or "", target_part_content or "")
    except Exception as e:
        logger.debug("Auto-context header build failed (non-fatal): %s", e)
        auto_header = ""

    base_header = (getattr(settings, "GENERATION_CONTEXT_PROMPT", "") or "").strip()
    effective_context_header = "\n\n".join([h for h in (base_header, auto_header) if h]).strip()

    prompt = build_creator_prompt(
        context_header=effective_context_header,
        full_reference_text=full_reference_text,
        target_part_content=target_part_content,
        target_part_answer=target_part_answer,
        correction_prompt_section=correction_prompt_section,
        keep_structure=bool(keep_structure),
    )

    try:
        chat = gemini_model.start_chat()
        response = chat.send_message(prompt)
        raw_text_response = response.text
    except Exception as e:
        logger.error(f"An error occurred during question generation for seed '{target_part_id}': {e}")
        return None

    content_object = response_validator.validate_and_correct_response(
        chat, gemini_model, raw_text_response
    )

    if not content_object:
        logger.error(f"Failed to generate or validate content for seed '{target_part_id}'.")
        return None

    content_object = _normalize_generated_object(content_object)
    content_object = postprocess_math.sanitize_generated_object(content_object)
    content_object = _synthesize_answer_spec_if_missing(content_object)

    # 4) Process any visual data
    visual_data = content_object.get("visual_data")
    if visual_data:
        logger.debug("Visual data present for seed '%s'. Processing…", target_part_id)

        try:
            issues = validate_config(visual_data)
        except Exception as ex:
            issues = [f"validate_config raised exception: {ex}"]

        if issues:
            print("Validation Issues:")
            for issue in issues:
                print(f"  ⚠️  {issue}")
        else:
            print("✅ Configuration is valid!")

        # --- Firestore-safe copy (do NOT overwrite numeric visual_data) ---
        try:
            sanitized_data = firestore_sanitizer.sanitize_for_firestore(visual_data)

            # Restore any table charts from original visual_data so tables are never Firestore-mangled.
            if isinstance(visual_data, dict) and isinstance(sanitized_data, dict):
                charts_key = "charts" if "charts" in visual_data else "graphs"
                orig_charts = visual_data.get(charts_key, []) or []
                sani_charts = sanitized_data.get(charts_key, []) or []

                if (
                    isinstance(orig_charts, list)
                    and isinstance(sani_charts, list)
                    and len(orig_charts) == len(sani_charts)
                ):
                    for i, orig_c in enumerate(orig_charts):
                        if isinstance(orig_c, dict) and str(orig_c.get("type", "")).strip().lower() == "table":
                            sani_charts[i] = orig_c
                    sanitized_data[charts_key] = sani_charts

            content_object["visual_data_firestore"] = sanitized_data
        except Exception as ex:
            logger.error("Failed to sanitize visual_data for Firestore: %s", ex)

        # --- IMPORTANT CHANGE ---
        # Tables are now rendered as normal SVG charts (TableChartView removed),
        # so we ALWAYS generate SVG if visual_data exists (including table-only).
        fig = None
        try:
            fig = dynamic_chart_plotter(visual_data)

            buffer = io.BytesIO()
            fig.savefig(buffer, format="svg")
            svg_data = buffer.getvalue().decode("utf-8")
            buffer.close()

            svg_base64 = base64.b64encode(svg_data.encode("utf-8")).decode("utf-8")

            fig_id = None
            if isinstance(visual_data, dict):
                charts_for_id = visual_data.get("charts", visual_data.get("graphs", [])) or []
                if isinstance(charts_for_id, list) and charts_for_id:
                    first = charts_for_id[0] if isinstance(charts_for_id[0], dict) else {}
                    fig_id = first.get("id")

            content_object["svg_images"] = [{
                "id": fig_id or "figure_1",
                "label": "Figure 1",
                "svg_base64": svg_base64,
                "kind": "chart",
            }]

            # Backwards-compat (optional): keep old key for older clients.
            content_object["svg_image"] = svg_base64

        except Exception as ex:
            logger.error("Failed to plot chart for seed '%s': %s", target_part_id, ex)
        finally:
            try:
                if fig is not None:
                    plt.close(fig)
            except Exception:
                pass

    else:
        logger.debug("No visual data generated for seed '%s'.", target_part_id)

    return content_object


def request_ai_correction(chat_session, error_message, original_text, context_text=None):
    """Asks the AI to correct its last response based on a validation error."""
    short_err = utils.truncate(str(error_message), limit=140)
    logger.debug("Requesting AI self-correction. Reason: %s", short_err)

    prompt = f"""
    Your last response could not be parsed and failed with the following error: '{error_message}'.

    Here is the full, problematic response you sent:
    --- FAULTY RESPONSE ---
    {original_text}
    --- END FAULTY RESPONSE ---

    Please provide the same content again, but ensure it is a single, perfectly valid JSON object with all backslashes and special characters correctly escaped for JSON.
    Do not include any explanation or apologies, only the corrected JSON object.
    """
    try:
        response = chat_session.send_message(prompt)
        logger.debug("Self-correction response received (first 200 chars): %s", (response.text or "")[:200])
        return response.text
    except Exception as e:
        logger.error(f"An error occurred during AI self-correction request: {e}")
        return None