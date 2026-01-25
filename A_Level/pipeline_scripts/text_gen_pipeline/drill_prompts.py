from textwrap import dedent

from .prompts_visual_data_guide import get_visual_rules_snippet


def build_text_drill_prompt(
    *,
    topic: str,
    course: str,
    difficulty: str,
    # question_type removed as requested
    additional_details: str = "",
    correction_prompt_section: str = ""
) -> str:
    """
    Prompt for generating questions from scratch based on user topic/course/difficulty.
    Includes the visual_data specification (SELECTED snippet) and STRICT math rules to match existing pipeline standards.
    """
    correction_block = (
        f"\n**PREVIOUS ERROR & CORRECTION**:\n{correction_prompt_section.strip()}\n"
        if correction_prompt_section else ""
    )

    # ---------------------------------------------------------------------
    # VISUAL GUIDE SELECTION (keep prompts short)
    #
    # We inject ONLY the most relevant visual_data type guide(s), not the
    # entire catalog, to avoid bloating the prompt every call.
    #
    # Heuristic rules:
    # - If the user asks for shapes/geometry/Euclidean diagrams -> geometry.
    # - Otherwise default to a single common type guide (function) to keep
    #   the prompt short and consistent.
    # - If the model decides no visual_data is needed, it should omit it.
    # ---------------------------------------------------------------------
    combined = f"{topic or ''} {additional_details or ''}".lower()
    wants_geometry = any(
        k in combined
        for k in [
            "geometry",
            "euclid",
            "euclidean",
            "triangle",
            "circle",
            "chord",
            "tangent",
            "secant",
            "polygon",
            "angle",
            "concyclic",
            "quadrilateral",
            "shape",
            "diagram",
            "construction",
        ]
    )

    visual_rules = ""
    if wants_geometry:
        visual_rules = get_visual_rules_snippet(only_types=["geometry"])
    else:
        # Keep it short by default. If needed later, you can choose other types
        # or fall back to the full guide.
        visual_rules = get_visual_rules_snippet(only_types=["function"])

    prompt = f"""
    You are an expert Mathematics Content Creator for the **{course}** curriculum.

    --- SYSTEM CONTEXT (READ CAREFULLY) ---
    - You are generating a **single JSON object** that will be consumed by an automated mobile learning app (iPad) called ALMA.
    - Your JSON is parsed programmatically and the text fields (question_stem, question_text, solution_text, final_answer, and any text in visual_data) are rendered using **MathJax** inside a WebView.
    - The app does **not** see LaTeX documents, TeX preambles, or Markdown. It only sees the JSON fields described below.
    - MathJax supports **inline and display math inside $...$ or $$...$$** with standard LaTeX math commands, but it does **not** support full TeX layout or diagram environments.
    - Therefore, you **must not** use any LaTeX environments that require a full TeX engine, such as \\begin{{equation}}, \\begin{{align}}, \\begin{{displaymath}}, \\begin{{tikzcd}}, \\begin{{tikzpicture}}, \\begin{{CD}}, \\xymatrix, \\begin{{array}}, \\begin{{matrix}}, or any diagram-producing environment. All diagrams must be represented **only** through the visual_data JSON system.

    YOUR TASK:
    Create a **{difficulty}** level question on the topic: "{topic}".

    {correction_block}

    --- USER SPECIFICATIONS ---
    - Course/Level: {course} (Ensure notation and scope match this level exactly).
    - Difficulty: {difficulty} (Scale: Introductory -> Easy -> Medium -> Hard -> Challenge).
    - Specific Details: "{additional_details}"

    --- CONTENT GUIDELINES ---
    1. Self-Contained: The question must be solvable with the information provided.
    2. Single Question Shape: Provide a clear "question_stem" and exactly ONE part in "parts".
    3. Visuals: If the topic usually requires a diagram, generate the JSON visual_data object. If it's pure algebra, omit it.
    4. MCQ Handling: If the user asks for Multiple Choice, include "choices": [{{"label":"A","text":"..."}}, ...] and "correct_choice": "A" inside the part.
    5. No Drawing Requests: Do not ask the student to "sketch/draw/plot."
    6. Clean Answer: Choose values that lead to a neat final result (integers, simple fractions/surds) when applicable.
    7. No Phantom Diagrams: If you mention a diagram/figure, you MUST supply visual_data. If you do not supply visual_data, do not refer to a diagram/figure/picture; provide explicit textual givens instead.
    8. Piecewise / cases: If you use a piecewise definition (e.g. \\begin{{cases}} ... \\end{{cases}}), keep each row short and clean:
       - Exactly ONE & per row (left side is the value, right side is the condition).
       - Do NOT put long explanations or extra sentences inside cases. Keep the condition simple.
       - Place any long explanation in normal text AFTER the displayed formula, not inside the cases environment.
       - Avoid nested parentheses and long \\text{{...}} blocks inside cases.
    9. No LaTeX list environments: Do NOT use \\begin{{itemize}}, \\begin{{enumerate}}, \\begin{{description}}, or \\item.
       If you need to list givens, write plain sentences separated by real newlines (use \\n inside JSON strings). Do NOT use Markdown bullet list syntax.
    10. No LaTeX text-formatting commands in prose: do not use \\textbf{{...}}, \\emph{{...}}, \\textit{{...}}.

    --- VISUAL_DATA GUIDE (SELECTED) ---
    {visual_rules}

    --- OUTPUT FORMAT ---
    - Return a single JSON object only. No markdown code fences. No commentary.
    - Do not use the backtick character ` anywhere in any field.
    - Do not wrap $...$ or $$...$$ in backticks.

    {{
        "question_stem": "...",
        "parts": [
            {{
                "part_label": "a",
                "question_text": "...",
                "solution_text": "...",
                "final_answer": "..."
            }}
        ],
        "calculator_required": true,
        "visual_data": {{...}}
    }}

    --- PURPOSE OF SOLUTION AND FINAL ANSWER ---
    - solution_text is not a model answer for a student to read. It is an internal explanation for an AI tutor.
    - Focus on the mathematical reasoning needed to solve the question (key steps, definitions, theorems).
    - final_answer is a compact summary of the end result only.

    --- JSON ESCAPING RULES (CRITICAL) ---
    You are writing JSON. Inside any JSON string, you must follow BOTH of these:

    A) Newlines (JSON escape, NOT LaTeX):
    - To create a line break in a JSON string, write \\n in the JSON source.
    - To create a blank line, write \\n\\n in the JSON source.
    - DO NOT double-escape newlines. Never write \\\\n in the JSON source, or the student will see the visible characters "\\n".

    Correct vs incorrect newline examples (JSON source):
    - ✅ "question_text": "Line 1\\nLine 2"
    - ❌ "question_text": "Line 1\\\\nLine 2"   (WRONG: shows literal \\n)

    B) LaTeX commands (must be escaped for JSON):
    - Any LaTeX command backslash must be escaped in the JSON source.
    - That means: to produce \\frac in the final text seen by MathJax, the JSON source must contain \\\\frac.
    - Do NOT “double everything”. ONLY LaTeX command backslashes are doubled; JSON newlines stay as \\n.

    Why single backslashes break:
    - If you write a single backslash in JSON before certain letters (e.g., "\\t", "\\n", "\\f"),
      JSON treats them as escapes, the backslash disappears, and MathJax sees broken LaTeX.

    Examples (JSON source -> text after JSON parsing):
    - "question_text": "Find $\\\\\\\\frac{{1}}{{2}}$."  ->  Find $\\\\frac{{1}}{{2}}$.
    - "question_text": "Let $\\\\\\\\omega > 0$."       ->  Let $\\\\omega > 0$.
    - "question_text": "Mass $1\\\\\\\\text{{kg}}$."     ->  Mass $1\\\\text{{kg}}$.

    **MATH FORMATTING RULES (STRICT)**:
    - ALL mathematics must be inside $...$ or $$...$$.
    - Use standard LaTeX commands for mathematics: \\\\frac{{...}}{{...}}, \\\\sqrt{{...}}, \\\\cdot, \\\\times, \\\\ln, \\\\sin, \\\\cos, etc.
      (Remember: those are the JSON-source forms; backslashes are doubled.)
    - Never output plain-text math like sqrt(3x+1); always use LaTeX like \\\\sqrt{{3x+1}} (inside $...$ or $$...$$).
    - Do NOT use custom math markers like $begin:math:text$.
    - Do NOT use LaTeX math environments like \\begin{{equation}}...\\end{{equation}} or \\begin{{align}}...\\end{{align}}. Use $$...$$ instead.
    - Never use diagram-producing LaTeX environments (tikz, xymatrix, array/matrix environments). Any diagram must be expressed only through visual_data.
    - Do not use the LaTeX linebreak command \\\\ inside math. Use separate sentences or JSON \\n line breaks in the surrounding text.
    - All LaTeX macros must be inside math mode ($...$ or $$...$$) and must use braces when they take arguments.

    --- FINAL OUTPUT REMINDER ---
    Output ONLY the JSON object. No extra keys, no commentary, no markdown.
    """
    return dedent(prompt).strip()