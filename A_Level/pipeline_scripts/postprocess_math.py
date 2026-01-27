# pipeline_scripts/postprocess_math.py
"""
Deliberately MINIMAL math text sanitizer for generated content.

Goals for this simplified version:
- Do NOT rewrite LaTeX or change math delimiters at all.
- Only do very safe text cleanup:
  • Normalize newlines and non-breaking spaces.
  • Normalize different dash characters to a simple '-'.
  • Strip Markdown bold/underline markers **...** / __...__ OUTSIDE math segments.
- Preserve math segments as the model produced them, EXCEPT for ultra-targeted
  repairs of JSON-escape corruption (tabs/backspaces/formfeeds), the [[BS]] token scheme,
  and the TeX newline corruption case where the model emits double-backslash macros
  inside math (e.g. \\in, \\mathbb, \\cdot) which TeX treats as a linebreak.

Math segments are detected as:
  - $$ ... $$
  - \[ ... \]
  - \( ... \)
  - $ ... $
  - ` ... `   (legacy inline math)
"""

from __future__ import annotations
import re
from typing import Dict, Any, List

# -------------------------------------------------------------------
# [[BS]] backslash-token scheme
# The model outputs [[BS]] instead of "\" in LaTeX to avoid JSON escapes.
# After JSON parsing, we convert [[BS]] -> "\" in relevant string fields.
# -------------------------------------------------------------------
_BS_TOKEN = "[[BS]]"

# --- Regex building blocks ---

# Order matters: longer/multiline blocks first, then single-line
_MATH_SEG_RE = re.compile(
    r"(\$\$[\s\S]*?\$\$"      # $$ ... $$
    r"|\\\[[\s\S]*?\\\]"      # \[ ... \]
    r"|\\\([\s\S]*?\\\)"      # \( ... \)
    r"|\$[^$]*\$"             # $ ... $
    r"|`[^`]*`)",             # ` ... ` (legacy inline math)
    re.DOTALL,
)

# Markdown emphasis (outside math) to strip
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_MD_UNDER_RE = re.compile(r"__(.+?)__")

# LaTeX list environments to rewrite (outside math)
_ITEM_ENV_RE = re.compile(
    r"\\begin\{(itemize|enumerate|description)\}([\s\S]*?)\\end\{\1\}",
    re.DOTALL,
)


def _rewrite_latex_lists(non_math: str) -> str:
    """
    Rewrite LaTeX list environments like:

        \\begin{itemize}
        \\item A
        \\item B
        \\end{itemize}

    into simple text bullets:

        - A
        - B

    This runs ONLY on non-math segments, so any $...$ inside items is preserved.
    """
    if (
        not non_math
        or ("\\begin{itemize}" not in non_math and "\\begin{enumerate}" not in non_math and "\\begin{description}" not in non_math)
    ):
        return non_math

    def repl(match: re.Match) -> str:
        body = match.group(2) or ""
        # Split on \item, keep content after each
        parts = re.split(r"\\item", body)
        items = []
        for raw in parts:
            txt = raw.strip()
            if not txt:
                continue
            # Keep the item text as-is (may contain $...$ math)
            items.append(f"- {txt}")
        if not items:
            return ""
        # End with a newline so following text starts on a new line
        return "\n".join(items) + "\n"

    return _ITEM_ENV_RE.sub(repl, non_math)


# --- Basic text normalization (very conservative) ---

def _normalize_text_basics(s: str) -> str:
    """
    Extremely conservative normalization that is safe for both plain text
    and LaTeX:
      - Normalize Windows newlines.
      - Convert NBSP to regular space.
      - Normalize Unicode dashes to '-'.
    """
    if not isinstance(s, str):
        return s

    return (
        s.replace("\r\n", "\n").replace("\r", "\n")
         .replace("\u00a0", " ")
         .replace("−", "-").replace("–", "-").replace("—", "-")
    )


def _replace_bs_token(s: str) -> str:
    """Replace [[BS]] -> backslash everywhere (safe in both math and non-math)."""
    if not isinstance(s, str) or not s:
        return s
    if _BS_TOKEN not in s:
        return s
    return s.replace(_BS_TOKEN, "\\")


def _repair_json_escape_corruption_in_math(seg: str) -> str:
    """
    Repair the *post-JSON-parse* damage caused by valid JSON escapes inside LaTeX.

    If the model accidentally emitted single-backslash LaTeX in JSON source:
      "\text"  -> TAB + "ext"
      "\theta" -> TAB + "heta"
      "\tau"   -> TAB + "au"
      "\frac"  -> FORMFEED + "rac"
      "\beta"  -> BACKSPACE + "eta"

    By the time we see the string in Python, those are literal control chars:
      \\t (TAB = '\t'), \\f (FORMFEED = '\x0c'), \\b (BACKSPACE = '\x08').

    We ONLY repair these inside math segments.
    """
    if not isinstance(seg, str) or not seg:
        return seg

    # TAB-based macros
    seg = seg.replace("\text", r"\text")    # \t + "ext"
    seg = seg.replace("\theta", r"\theta")  # \t + "heta"
    seg = seg.replace("\tau", r"\tau")      # \t + "au"

    # FORMFEED-based macro
    seg = seg.replace("\frac", r"\frac")    # \f + "rac"

    # BACKSPACE-based macro
    seg = seg.replace("\beta", r"\beta")    # \b + "eta"

    return seg


def _repair_tex_newline_double_slash_macros_in_math(seg: str) -> str:
    """
    Repair TeX newline corruption inside math segments.

    If the model outputs double-backslash before a macro inside math, e.g.
        \\in, \\mathbb, \\cdot, \\times
    then TeX/MathJax interprets \\ as a linebreak, and the macro name gets
    printed as plain text (e.g. 'inmathbbZ', '2cdot3').

    Fix:
      - Collapse '\\\\<letters>' -> '\\<letters>'
      - Also collapse doubled spacing commands '\\\\,' '\\\\;' '\\\\:' '\\\\!' -> '\\,' '\\;' '\\:' '\\!'
    """
    if not isinstance(seg, str) or not seg:
        return seg

    # Collapse TeX newline form before macro names
    seg = re.sub(r"\\\\([A-Za-z]+)", r"\\\1", seg)

    # Collapse doubled spacing commands
    seg = re.sub(r"\\\\([,;:!])", r"\\\1", seg)

    return seg


# --- Core sanitizer ---

def sanitize_text(s: str) -> str:
    """
    Clean a single text field WITHOUT changing math delimiters.

    What it does:
      - basic unicode/newline cleanup on the full string.
      - replaces [[BS]] -> "\" on the full string (safe everywhere).
      - splits into math vs non-math segments.
      - on NON-math segments only:
          * strip **bold** and __underline__ markdown.
          * rewrite LaTeX list environments (itemize/enumerate/description) into simple bullets.
      - on MATH segments only:
          * ultra-targeted repair for JSON escape corruption control chars (\t, \f, \b).
          * ultra-targeted repair for TeX newline corruption where model emits \\macro inside math.
      - rejoins everything.
    """
    if not isinstance(s, str) or not s.strip():
        return s

    s = _normalize_text_basics(s)
    s = _replace_bs_token(s)

    parts: List[str] = []
    last = 0

    for m in _MATH_SEG_RE.finditer(s):
        # Non-math chunk before this math segment
        if m.start() > last:
            non = s[last:m.start()]
            non = _MD_BOLD_RE.sub(r"\1", non)
            non = _MD_UNDER_RE.sub(r"\1", non)
            non = _rewrite_latex_lists(non)
            parts.append(non)

        # Math segment: keep delimiters, only ultra-targeted repairs
        math_seg = m.group(0)
        math_seg = _repair_json_escape_corruption_in_math(math_seg)
        math_seg = _repair_tex_newline_double_slash_macros_in_math(math_seg)
        parts.append(math_seg)

        last = m.end()

    # Trailing non-math
    if last < len(s):
        non = s[last:]
        non = _MD_BOLD_RE.sub(r"\1", non)
        non = _MD_UNDER_RE.sub(r"\1", non)
        non = _rewrite_latex_lists(non)
        parts.append(non)

    return "".join(parts)


def sanitize_generated_object(obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply sanitize_text to the relevant fields of a generated question object.

    Intentionally minimal: we only run on:
      - question_stem
      - parts[0].question_text
      - parts[0].solution_text
      - parts[0].final_answer
    """
    if not isinstance(obj, dict):
        return obj

    # Top-level stem
    if "question_stem" in obj and isinstance(obj["question_stem"], str):
        obj["question_stem"] = sanitize_text(obj["question_stem"])

    # First part (if any)
    parts = obj.get("parts") or []
    if isinstance(parts, list) and parts:
        p0 = parts[0] or {}
        if isinstance(p0, dict):
            for k in ("question_text", "solution_text", "final_answer"):
                if k in p0 and isinstance(p0[k], str):
                    p0[k] = sanitize_text(p0[k])
            obj["parts"][0] = p0

    return obj