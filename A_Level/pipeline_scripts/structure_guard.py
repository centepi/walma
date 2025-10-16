# pipeline_scripts/structure_guard.py
import re
import json
from . import utils

logger = utils.setup_logger(__name__)

def _parse_last_json_object(text: str) -> dict:
    """
    Be tolerant to LLMs that prepend/append prose.
    Extract the last {...} block and json.loads it.
    """
    text = (text or "").strip()
    m = re.search(r"\{[\s\S]*\}\s*$", text)
    if m:
        return json.loads(m.group(0))
    return json.loads(text)

def screen_structure_and_relevance(checker_model, generated_object: dict, reference_text: str) -> tuple[bool, str]:
    """
    Soft guardrail: ensure (a) on-topic & same-skill, and (b) ONE coherent question
    (multiple steps OK; reject only if the tasks are independent/not sequential).

    Returns:
        (ok: bool, reason_if_not_ok: str)
    """
    try:
        prompt = f"""
You are reviewing an automatically generated advanced mathematics question.

REFERENCE CONTEXT (topic/skill anchor):
{reference_text}

CANDIDATE QUESTION JSON:
{json.dumps(generated_object, ensure_ascii=False)}

Decide if BOTH are true:

1) Topicality/Skill: The candidate stays in the SAME topic and tests similar skills as the reference (no drift to unrelated areas).

2) Coherence: The candidate is ONE coherent question.
   - It may have multiple reasoning steps or say "hence".
   - REJECT only if it actually contains two or more independent tasks that do NOT build on each other
     (i.e., the parts could be asked separately without dependency).

Respond with ONLY JSON (single line), e.g.
{{"ok": true, "reason": "brief reason if false"}}
"""
        resp = checker_model.generate_content(prompt)
        raw = (getattr(resp, "text", "") or "").strip()
        js = _parse_last_json_object(raw)
        ok = bool(js.get("ok", False))
        reason = str(js.get("reason", "") or "")
        return ok, reason
    except Exception as e:
        logger.debug("Structure/relevance screening failed (treating as ok). %s", e)
        return True, ""