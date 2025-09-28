# prompts_presets.py
from textwrap import dedent

try:
    # Optional enum-like helper; fall back to strings if not present.
    from .constants import CASPolicy  # type: ignore
except Exception:
    class CASPolicy:
        OFF = "off"
        PREFER = "prefer"
        REQUIRE = "require"


def build_creator_prompt(
    *,
    context_header: str,
    full_reference_text: str,
    target_part_content: str,
    target_part_answer: str | None = "",
    correction_prompt_section: str | None = "",
    keep_structure: bool = False,
) -> str:
    """Prompt for the content generator."""
    keep_block = (
        """
        **KEEP AS CLOSE AS POSSIBLE (questions-only mode)**:
        - Preserve the structure, intent, and verbs of the target part (e.g., "Show that", "Hence", "Find", "Prove").
        - Keep the mathematical *type* (same skill) and the same number of sub-reasoning steps.
        - Change only surface details (numbers, coefficients, simple function parameters) to keep it original.
        - If the original required a sketch/diagram, convert that to a textual description (no drawing requests).
        - Do NOT copy sentences verbatim. Keep it semantically equivalent but reworded.
        """
        if keep_structure
        else ""
    )

    correction_block = f"\n{correction_prompt_section.strip()}\n" if correction_prompt_section else ""

    prompt = f"""
    {context_header.strip()}

    You are an expert A-level Mathematics content creator. Your task is to create a NEW, ORIGINAL, and SELF-CONTAINED A-level question.

    {correction_block}
    --- CONTEXT: THE FULL ORIGINAL QUESTION (for skill + style only; do NOT copy) ---
    {full_reference_text}

    --- INSPIRATION: THE TARGET PART ---
    - Reference Part Content: "{target_part_content}"
    - Reference Part Solution (if available): "{(target_part_answer or '').strip()}"

    --- YOUR TASK ---
    Create ONE self-contained question that tests the same mathematical skill as the target part above, following the specified OUTPUT FORMAT.

    **CRITICAL INSTRUCTIONS**:
    1.  **Self-Contained**: Provide a clear "question_stem" and exactly ONE part in "parts".
    2.  **Invent Values**: Use fresh numbers/functions/scenarios to avoid copying.
    3.  **Clean Answer**: Choose values that lead to a neat final result (integers, simple fractions/surds).
    4.  **Contextual Visuals Only**: Any 'visual_data' must aid understanding and must NOT encode the answer.
    5.  **Include Visuals if Appropriate**: Only when the skill is inherently visual.
    6.  **Calculator Use**: Set 'calculator_required' appropriately.
    7.  **NO DRAWING REQUESTS**: Do not ask to "sketch/draw/plot"; convert to textual reasoning.
    8.  **FINAL ANSWER FIELD**: Inside the single part object, include a concise 'final_answer' string (CAS-friendly).

    {dedent(keep_block).strip()}

    **MATH FORMATTING RULES (STRICT)**:
    - Use **LaTeX commands** for ALL mathematics: `\\frac{{...}}{{...}}`, `\\sqrt{{...}}`, `\\cdot`, `\\times`, `\\ln`, `\\sin`, `\\cos`, etc.
    - Prefer `\$begin:math:text$...\\$end:math:text$` for inline math and `\$begin:math:display$...\\$end:math:display$` for display. `$...$`/`$$...$$` and backticks are also accepted.
    - **NEVER** output plain-text math like `sqrt(3x+1)`, `sqrt3x+1`, `frac{{e^{{4x}}}}{{(2x+1)^3}}`, or exponents without braces.
    - Every macro that takes arguments **must** use braces: `\\sqrt{{3x+1}}`, `\\frac{{e^{{4x}}}}{{(2x+1)^3}}`, `(x-1)^3\\sqrt{{4x}}`.
    - Do not use Markdown styling like `**bold**` inside any field. If emphasis is needed, prefer plain text or `\\textbf{{...}}` inside math.

    **Examples — follow EXACTLY**:
    - OK:  ``Find the gradient of the curve `y = (x-1)^3\\sqrt{{4x}}` at `x = 4`.``  
    - OK:  ``Given `f(x) = \\frac{{e^{{4x}}}}{{(2x+1)^3}}`, find `f'(x)`.``  
    - BAD: `sqrt(3x+1)` → use `` `\\sqrt{{3x+1}}` ``  
    - BAD: `frac{{e^{{4x}}}}{{(2x+1)^3}}` → use `` `\\frac{{e^{{4x}}}}{{(2x+1)^3}}` ``

    **OUTPUT FORMAT**:
    Your output MUST be a single, valid JSON object with the structure:
    {{
      "question_stem": "A concise introduction/setup for your new question.",
      "parts": [
        {{
          "part_label": "a",
          "question_text": "The single task for the user to perform.",
          "solution_text": "The detailed, step-by-step solution to your new question.",
          "final_answer": "A SHORT, simplified final numeric value or algebraic expression only."
        }}
      ],
      "calculator_required": true,
      "visual_data": {{...}}  // Omit this key entirely if no visual is needed
    }}

    **'visual_data' structure (if needed)**:
    The 'visual_data' object must contain a 'graphs' array. You can also add OPTIONAL arrays for 'labeled_points' and 'shaded_regions'.
    Example:
    {{
        "graphs": [
            {{
                "id": "g1",
                "label": "y = f(x)",
                "explicit_function": "x**2 - 4*x + 7",
                "visual_features": {{
                    "type": "parabola",
                    "x_intercepts": null,
                    "y_intercept": 7,
                    "turning_points": [{{ "x": 2, "y": 3 }}],
                    "axes_range": {{ "x_min": -1, "x_max": 5, "y_min": 0, "y_max": 10 }}
                }}
            }}
        ],
        "labeled_points": [{{ "label": "A", "x": 1.0, "y": 4.0 }}],
        "shaded_regions": [
            {{
                "upper_bound_id": "g1",
                "lower_bound_id": "y=0",
                "x_start": 1.0,
                "x_end": 4.0
            }}
        ]
    }}

    **JSON TECHNICAL RULES**:
    - **Double-escape backslashes** inside JSON strings (e.g., `\\sqrt{{...}}`, `\\frac{{...}}{{...}}`).
    - Output **ONLY** the JSON object — **no** markdown code fences, headings, or commentary.
    - Keep strings single-line where possible; if you include newlines, use `\\n` in JSON.

    **FINAL CHECK**: Ensure the question has a clean solution; 'final_answer' is short & simplified; and the JSON is valid.
    """
    return dedent(prompt).strip()


def build_examiner_prompt(question_json_string: str, cas_policy: str = CASPolicy.OFF) -> str:
    """
    Prompt for the AI examiner. Returns JSON with is_correct/feedback/marks.
    If CAS is active upstream, the examiner is reminded to check consistency with final_answer/answer_spec.
    """
    cas_line = {
        CASPolicy.OFF: "If 'final_answer'/'answer_spec' are present, consider them; otherwise ignore.",
        CASPolicy.PREFER: "If 'final_answer'/'answer_spec' are present, ensure they match the worked solution.",
        CASPolicy.REQUIRE: "You MUST ensure 'final_answer' and 'answer_spec' are consistent with the worked solution.",
    }.get(cas_policy, "If 'final_answer'/'answer_spec' are present, ensure they match the worked solution.")

    prompt = f"""
    You are a meticulous A-level Mathematics examiner. Review the auto-generated item below.

    --- QUESTION JSON (verbatim) ---
    ```json
    {question_json_string}
    ```

    --- YOUR TASKS ---
    1) Verify the mathematics in 'solution_text' is correct and fully answers 'question_text'.
    2) {cas_line}
    3) Assign marks only if PERFECT.

    --- OUTPUT FORMAT ---
    If flawed:
    {{
      "is_correct": false,
      "feedback": "A brief, clear explanation of the mistake.",
      "marks": 0
    }}

    If perfect:
    {{
      "is_correct": true,
      "feedback": "OK",
      "marks": <integer 1..8>
    }}
    """
    return dedent(prompt).strip()