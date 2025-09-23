# pipeline_scripts/checks_cas.py
"""
CAS helpers + tiny answer_spec synthesis.

This module provides two things:

1) CAS policy runner + reconciler
   - run_cas_validation(question_object, policy=None) -> (cas_ok, cas_report)
   - reconcile_examiner_and_cas(examiner_feedback, cas_ok, cas_report, policy=None) -> merged_feedback
   - apply_cas_policy(question_object, examiner_feedback, policy=None)
       -> (final_ok, final_feedback, cas_ok, cas_report)

2) answer_spec synthesis for common cases (currently: general derivatives)
   - build_answer_spec_from_generated(obj) -> dict | None

Your pipeline can:
- call build_answer_spec_from_generated() right after generation to attach an
  answer_spec when the model didn’t provide one, then
- call apply_cas_policy() to run/merge CAS with the AI examiner verdict.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple, Optional
import re

from config import settings
from . import utils
from .constants import CASPolicy
from . import cas_validator

logger = utils.setup_logger(__name__)

# =============================================================================
# Section A — CAS policy runner / reconciler
# =============================================================================


def run_cas_validation(
    question_object: Dict[str, Any],
    policy: str | None = None,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Run CAS validation for a question_object depending on policy.

    Returns:
        cas_ok: bool
        cas_report: dict with at least:
            {
              "policy": <policy>,
              "skipped": <bool>,         # present when CAS not run
              "reason": <str>,           # why skipped/failed (optional)
              "validator": <full report> # present when CAS ran
            }
    """
    chosen_policy = (policy or settings.CAS_POLICY or CASPolicy.OFF).lower().strip()

    # No CAS at all
    if chosen_policy == CASPolicy.OFF:
        return True, {"policy": chosen_policy, "skipped": True, "reason": "CAS disabled (policy=off)"}

    # Need an answer_spec to do anything meaningful
    spec = (question_object or {}).get("answer_spec")
    if not isinstance(spec, dict):
        if chosen_policy == CASPolicy.REQUIRE:
            return (
                False,
                {
                    "policy": chosen_policy,
                    "skipped": False,
                    "reason": "answer_spec missing (policy=require)",
                },
            )
        # prefer: don't fail the item, just note it
        return True, {
            "policy": chosen_policy,
            "skipped": True,
            "reason": "answer_spec missing (policy=prefer) — CAS not run",
        }

    try:
        ok, report = cas_validator.validate(question_object)
        return bool(ok), {
            "policy": chosen_policy,
            "skipped": False,
            "validator": report,
        }
    except Exception as e:
        # Defensive: never crash the pipeline on CAS
        logger.error("CAS: unexpected error — %s", e)
        # REQUIRE -> fail hard; PREFER -> allow through
        if chosen_policy == CASPolicy.REQUIRE:
            return False, {
                "policy": chosen_policy,
                "skipped": False,
                "reason": f"CAS internal error: {e}",
            }
        return True, {
            "policy": chosen_policy,
            "skipped": True,
            "reason": f"CAS internal error (ignored under prefer): {e}",
        }


def reconcile_examiner_and_cas(
    examiner_feedback: Dict[str, Any] | None,
    cas_ok: bool,
    cas_report: Dict[str, Any],
    policy: str | None = None,
) -> Dict[str, Any]:
    """
    Merge AI examiner feedback with CAS results according to policy.

    Inputs:
        examiner_feedback: {"is_correct": bool, "feedback": str, "marks": int}
        cas_ok: bool from run_cas_validation
        cas_report: dict from run_cas_validation
        policy: optional override; defaults to settings.CAS_POLICY

    Returns a new feedback dict (same shape as examiner_feedback).
    """
    chosen_policy = (policy or settings.CAS_POLICY or CASPolicy.OFF).lower().strip()
    fb = dict(examiner_feedback or {"is_correct": False, "feedback": "No examiner feedback.", "marks": 0})

    # If CAS was skipped (no spec or off), just append a note and return
    if cas_report.get("skipped", False) or chosen_policy == CASPolicy.OFF:
        note = cas_report.get("reason", "CAS not run.")
        fb["feedback"] = _append_note(fb.get("feedback"), f"[CAS: {note}]")
        return fb

    # CAS ran:
    if cas_ok:
        fb["feedback"] = _append_note(fb.get("feedback"), "[CAS: checks passed]")
        return fb

    # CAS failed:
    details = cas_report.get("validator") or {"reason": cas_report.get("reason", "CAS failed")}
    cas_reason = _shorten(details)

    if chosen_policy == CASPolicy.REQUIRE:
        # Override: must fail
        fb["is_correct"] = False
        fb["marks"] = 0
        fb["feedback"] = _append_note(
            f"Overridden by CAS (policy=require). {fb.get('feedback','')}".strip(),
            f"[CAS: {cas_reason}]",
        )
        return fb

    # PREFER: keep examiner's verdict but annotate
    fb["feedback"] = _append_note(fb.get("feedback"), f"[CAS warning: {cas_reason}]")
    return fb


def apply_cas_policy(
    question_object: Dict[str, Any],
    examiner_feedback: Dict[str, Any] | None,
    policy: str | None = None,
) -> Tuple[bool, Dict[str, Any], bool, Dict[str, Any]]:
    """
    Convenience: run CAS, then reconcile with examiner feedback, and return a final verdict.

    Returns:
        final_ok: bool                 -> final is_correct
        final_feedback: dict           -> merged feedback payload
        cas_ok: bool                   -> raw CAS pass/fail
        cas_report: dict               -> CAS report
    """
    cas_ok, cas_report = run_cas_validation(question_object, policy=policy)
    merged = reconcile_examiner_and_cas(examiner_feedback, cas_ok, cas_report, policy=policy)
    final_ok = bool(merged.get("is_correct"))
    return final_ok, merged, cas_ok, cas_report


def _append_note(base: str | None, note: str) -> str:
    base = (base or "").strip()
    if not base:
        return note
    if note in base:
        return base
    return f"{base}\n{note}"


def _shorten(d: Dict[str, Any] | str, limit: int = 240) -> str:
    if isinstance(d, str):
        return d[:limit]
    # prefer validator.reason if exists; else compact the dict
    reason = (d or {}).get("reason")
    if isinstance(reason, str) and reason:
        return reason[:limit]
    return utils.truncate(str(d), limit=limit)


# =============================================================================
# Section B — Lightweight answer_spec synthesis (export: build_answer_spec_from_generated)
# =============================================================================

# cues & patterns for derivative-style questions
_DERIVATIVE_CUES = re.compile(
    r"(differentiat(?:e|ing)|find\s+(?:dy/dx|d\s*y\s*/\s*dx|f'(x)|the\s+derivative)|derivative\s+of)",
    re.IGNORECASE,
)

# capture RHS of y=..., f(x)=..., g(x)=..., etc., until newline/period/semicolon
_FUNC_EQ_PAT = re.compile(
    r"(?:^|[\s,:;])(?:y\s*=\s*|[a-zA-Z]\s*\(\s*x\s*\)\s*=\s*)(?P<expr>[^;.\n\r]+)",
    re.IGNORECASE,
)

_AT_X_NUMERIC = re.compile(r"\bat\s*x\s*=\s*[-+]?\d+(?:\.\d+)?\b", re.IGNORECASE)


def _coerce_str(v) -> str:
    return (v or "").strip()


def _pyexpr(s: str) -> str:
    """Normalize math text into a Python/SymPy-friendly expression."""
    t = _coerce_str(s)
    if not t:
        return t
    t = t.replace("^", "**")
    t = t.replace("×", "*").replace("·", "*")
    t = t.replace("−", "-").replace("—", "-").replace("–", "-")
    # SymPy uses log(x) for natural log
    t = re.sub(r"\bln\s*\(", "log(", t)
    # implicit multiplication like 2x -> 2*x (only simple cases)
    t = re.sub(r"(\d)([a-zA-Z])", r"\1*\2", t)
    return t


def _looks_pure_number(expr: str) -> bool:
    return bool(re.fullmatch(r"\s*[-+]?\d+(?:\.\d+)?\s*", expr))


def _extract_function_expr(text: str) -> Optional[str]:
    """Find f(x) RHS from text like 'y = ...' or 'f(x) = ...'."""
    m = _FUNC_EQ_PAT.search(text or "")
    if not m:
        return None
    return _pyexpr(m.group("expr"))


def _maybe_derivative_spec(stem: str, qtext: str, final_answer: str) -> Optional[Dict[str, Any]]:
    """
    Build an answer_spec for general derivative tasks:
      {"kind":"derivative","of":"<expr>","result":"<final_answer>","order":1,"variables":["x"]}
    Skip if it's a numeric-at-a-point gradient.
    """
    if not final_answer:
        return None

    combined = f"{stem}\n{qtext}"
    if not _DERIVATIVE_CUES.search(combined):
        return None
    if _AT_X_NUMERIC.search(combined):
        # this is a gradient at x=a; we’re not synthesizing specs for those (yet)
        return None

    of_expr = _extract_function_expr(combined)
    if not of_expr:
        return None

    result_expr = _pyexpr(final_answer)
    # crude guard: if the "final answer" is just a lone number, it's probably not a general derivative
    if _looks_pure_number(result_expr):
        return None

    return {
        "kind": "derivative",
        "of": of_expr,
        "result": result_expr,
        "order": 1,
        "variables": ["x"],
    }


def build_answer_spec_from_generated(obj: dict) -> Optional[Dict[str, Any]]:
    """
    Given a validated generated object (with parts[0] and final_answer),
    try to synthesize a minimal answer_spec the CAS validator can check.

    Returns:
        dict | None
    """
    if not isinstance(obj, dict):
        return None
    parts = obj.get("parts") or []
    if not parts or not isinstance(parts[0], dict):
        return None

    stem = _coerce_str(obj.get("question_stem"))
    qtext = _coerce_str(parts[0].get("question_text"))
    final_answer = _coerce_str(parts[0].get("final_answer"))

    # 1) general derivative
    spec = _maybe_derivative_spec(stem, qtext, final_answer)
    if spec:
        return spec

    # (Future: add heuristics for simplification equality, product/quotient derivative forms, etc.)
    return None