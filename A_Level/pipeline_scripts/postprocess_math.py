# pipeline_scripts/postprocess_math.py
"""
Minimal, safe math text sanitizer for generated content.

Goals:
- Remove Markdown emphasis (**...**, __...__) OUTSIDE math.
- Fix common TeX slip-ups INSIDE math:
  • sqrt(...)  -> \sqrt{...}
  • bare 'frac{' -> '\frac{'
  • ensure \sin, \cos, \tan, \ln, \log, etc. (upright)
- Keep already-correct TeX entirely unchanged.
- Preserve delimiters: $$...$$, \[...\], \(...\), $...$, and (for legacy) `...`
- Canonicalize legacy Alma fences `$begin:math:*$ ... $end:math:*$` (optionally wrapped in backticks)
  to standard MathJax delimiters before processing.
"""

from __future__ import annotations
import re
from typing import Dict, Any, List

# --- Canonicalize legacy custom fences to standard TeX ---
_INLINE_FENCE_RE = re.compile(r"`?\$begin:math:text\$([\s\S]*?)\$end:math:text\$`?", re.DOTALL)
_DISPLAY_FENCE_RE = re.compile(r"`?\$begin:math:display\$([\s\S]*?)\$end:math:display\$`?", re.DOTALL)

def _canon_custom_fences(s: str) -> str:
    """Convert `$begin:math:*$...$end:math:*$` (with optional backticks) to \( ... \) / \[ ... \]."""
    if not isinstance(s, str) or not s:
        return s
    s = _INLINE_FENCE_RE.sub(lambda m: r"\(" + m.group(1) + r"\)", s)
    s = _DISPLAY_FENCE_RE.sub(lambda m: r"\[" + m.group(1) + r"\]", s)
    return s

# --- Regex building blocks ---
# Order matters: longer/multiline blocks first, then single-line
_MATH_SEG_RE = re.compile(
    r"(\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$[^$]*\$|`[^`]*`)",
    re.DOTALL,
)

# Markdown emphasis (outside math) to strip
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_MD_UNDER_RE = re.compile(r"__(.+?)__")

# Inside-math fixes
# sqrt(...) without backslash (inside a math segment's content)
_SQRT_PAREN_RE = re.compile(r"(?<!\\)sqrt\s*$begin:math:text$\\s*([^)]+?)\\s*$end:math:text$")
# 'frac{' without backslash
_FRAC_MISSING_BS_RE = re.compile(r"(^|[^\\])frac\s*\{")
# common functions without backslash (word boundary, not already escaped)
_FUNCS_RE = re.compile(
    r"(?<!\\)\b(sin|cos|tan|sec|csc|cot|asin|acos|atan|arcsin|arccos|arctan|ln|log)\b"
)

# Normalize Windows newlines, stray NBSP, dashes, middle dots, etc.
def _normalize_text_basics(s: str) -> str:
    if not isinstance(s, str):
        return s
    return (
        s.replace("\r\n", "\n").replace("\r", "\n")
         .replace("\u00a0", " ")
         .replace("−", "-").replace("–", "-").replace("—", "-")
         .replace("·", "*").replace("×", "*")
    )

def _fix_inside_math(body: str) -> str:
    # sqrt(...) -> \sqrt{...}
    body = _SQRT_PAREN_RE.sub(lambda m: r"\sqrt{" + m.group(1).strip() + "}", body)
    # bare 'frac{' -> '\frac{'
    body = _FRAC_MISSING_BS_RE.sub(lambda m: (m.group(1) + r"\frac{"), body)
    # functions -> \sin, \cos, ...
    body = _FUNCS_RE.sub(lambda m: "\\" + m.group(1), body)
    return body

def _process_math_segment(seg: str) -> str:
    """Apply inside-math fixes but preserve original delimiters."""
    if seg.startswith("$$") and seg.endswith("$$"):
        inner = seg[2:-2]
        return "$$" + _fix_inside_math(inner) + "$$"
    if seg.startswith(r"$begin:math:display$") and seg.endswith(r"$end:math:display$"):
        inner = seg[2:-2]
        return r"$begin:math:display$" + _fix_inside_math(inner) + r"$end:math:display$"
    if seg.startswith(r"$begin:math:text$") and seg.endswith(r"$end:math:text$"):
        inner = seg[2:-2]
        return r"$begin:math:text$" + _fix_inside_math(inner) + r"$end:math:text$"
    if seg.startswith("$") and seg.endswith("$"):
        inner = seg[1:-1]
        return "$" + _fix_inside_math(inner) + "$"
    if seg.startswith("`") and seg.endswith("`"):
        # Legacy: treat backticks as inline math; keep ticks.
        inner = seg[1:-1]
        return "`" + _fix_inside_math(inner) + "`"
    return seg  # fallback (shouldn't happen)

def sanitize_text(s: str) -> str:
    """
    Clean a single text field.
    """
    if not isinstance(s, str) or not s.strip():
        return s

    s = _normalize_text_basics(s)
    s = _canon_custom_fences(s)  # convert legacy fences to standard TeX

    # Tokenize math vs non-math
    parts: List[str] = []
    last = 0
    for m in _MATH_SEG_RE.finditer(s):
        # non-math chunk before this math seg
        if m.start() > last:
            non = s[last:m.start()]
            # strip Markdown emphasis ONLY outside math
            non = _MD_BOLD_RE.sub(r"\1", non)
            non = _MD_UNDER_RE.sub(r"\1", non)
            parts.append(non)
        seg = m.group(0)
        parts.append(_process_math_segment(seg))
        last = m.end()
    # trailing non-math
    if last < len(s):
        non = s[last:]
        non = _MD_BOLD_RE.sub(r"\1", non)
        non = _MD_UNDER_RE.sub(r"\1", non)
        parts.append(non)

    return "".join(parts)

def sanitize_generated_object(obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply sanitize_text to the relevant fields of a generated question object.
    """
    if not isinstance(obj, dict):
        return obj

    for key in ("question_stem",):
        if key in obj and isinstance(obj[key], str):
            obj[key] = sanitize_text(obj[key])

    parts = obj.get("parts") or []
    if isinstance(parts, list) and parts:
        p0 = parts[0] or {}
        for k in ("question_text", "solution_text", "final_answer"):
            if k in p0 and isinstance(p0[k], str):
                p0[k] = sanitize_text(p0[k])
        obj["parts"][0] = p0

    return obj