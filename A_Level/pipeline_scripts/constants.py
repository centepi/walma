# pipeline_scripts/constants.py
"""
Project-wide small constants & enums.

Import examples:
    from .constants import CASPolicy, GenerationStyle, Keys, MARKS_MIN, MARKS_MAX
"""

from typing import Final, Set, Dict


# --------- Policies / Modes ---------

class CASPolicy:
    """How strictly to enforce CAS verification of the final answer."""
    OFF: Final[str] = "off"
    PREFER: Final[str] = "prefer"
    REQUIRE: Final[str] = "require"

    ALL: Final[Set[str]] = {OFF, PREFER, REQUIRE}


class GenerationStyle:
    """How closely to mirror the source question when re-generating."""
    INSPIRED: Final[str] = "inspired"     # default: fresh values & wording, same skill
    NEAR_COPY: Final[str] = "near_copy"   # preserve structure/wording where possible

    ALL: Final[Set[str]] = {INSPIRED, NEAR_COPY}


# --------- JSON Keys (keep in one place so we don’t typo them) ---------

class Keys:
    class Question:
        STEM: Final[str] = "question_stem"
        PARTS: Final[str] = "parts"
        CALCULATOR_REQUIRED: Final[str] = "calculator_required"
        VISUAL_DATA: Final[str] = "visual_data"
        ANSWER_SPEC: Final[str] = "answer_spec"   # CAS spec for auto-checking
        FINAL_ANSWER: Final[str] = "final_answer" # optional short final answer string

        TOPIC: Final[str] = "topic"
        NUMBER: Final[str] = "question_number"
        TOTAL_MARKS: Final[str] = "total_marks"

    class Part:
        LABEL: Final[str] = "part_label"
        TEXT: Final[str] = "question_text"
        SOLUTION: Final[str] = "solution_text"

    class Examiner:
        IS_CORRECT: Final[str] = "is_correct"
        FEEDBACK: Final[str] = "feedback"
        MARKS: Final[str] = "marks"
        CAS_OK: Final[str] = "cas_ok"             # bool (if CAS was run)
        CAS_REPORT: Final[str] = "cas_report"     # dict/string summary if available

    class Visual:
        GRAPHS: Final[str] = "graphs"
        LABELED_POINTS: Final[str] = "labeled_points"
        SHADED_REGIONS: Final[str] = "shaded_regions"

        class Graph:
            ID: Final[str] = "id"
            LABEL: Final[str] = "label"
            EXPLICIT_FUNCTION: Final[str] = "explicit_function"  # Python/SymPy friendly
            FEATURES: Final[str] = "visual_features"

        class Features:
            TYPE: Final[str] = "type"
            X_INTERCEPTS: Final[str] = "x_intercepts"
            Y_INTERCEPT: Final[str] = "y_intercept"
            TURNING_POINTS: Final[str] = "turning_points"
            AXES_RANGE: Final[str] = "axes_range"
            SAMPLED_POINTS: Final[str] = "sampled_points"

        class Axes:
            X_MIN: Final[str] = "x_min"
            X_MAX: Final[str] = "x_max"
            Y_MIN: Final[str] = "y_min"
            Y_MAX: Final[str] = "y_max"


# --------- Marks & Attempts ---------

MARKS_MIN: Final[int] = 1
MARKS_MAX: Final[int] = 8
DEFAULT_MARKS: Final[int] = 4
GENERATION_RETRY_LIMIT: Final[int] = 2  # initial + 1 retry on failure


# --------- Unicode normalization helpers ---------
# (Optional) A small map that modules can use before SymPy parsing/graph sampling.
# Keep minimal so we don’t over-normalize user math.
UNICODE_MATH_MAP: Final[Dict[str, str]] = {
    "−": "-",     # minus
    "–": "-",     # en dash used as minus sometimes
    "—": "-",     # em dash used as minus sometimes
    "×": "*",     # multiplication sign
    "∗": "*",     # asterisk operator
    "·": "*",     # dot operator (often used as multiply)
    "√": "sqrt",  # square root
    "π": "pi",    # pi
    "⁄": "/",     # fraction slash
}

# Characters that often wrap math but are not wanted for parsing; consumers may strip.
WRAPPING_QUOTES: Final[Set[str]] = {"“", "”", "„", "‟", "«", "»", "‹", "›", "′", "″", "‴", "❛", "❜", "❝", "❞"}


# --------- Firestore collection names (shared) ---------

FIRESTORE_QUESTIONS_SUBCOLLECTION: Final[str] = "Questions"