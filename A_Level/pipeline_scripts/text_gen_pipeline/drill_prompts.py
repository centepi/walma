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
    # - Otherwise default to "full guide" (rare) ONLY if caller explicitly
    #   asks for it (not implemented here), else include nothing extra.
    # - If the model decides no visual_data is needed, it should omit it.
    #
    # If you want to force a specific type from the caller, you can add an
    # optional parameter later (e.g., visual_guide_types=["histogram"]).
    # For now, we infer from the topic/details to keep API unchanged.
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
    - Your JSON is parsed programmatically and the text fields (`question_stem`, `question_text`, `solution_text`, `final_answer`, and any text in `visual_data`) are rendered using **MathJax** inside a WebView.
    - The app does **not** see LaTeX documents, TeX preambles, or Markdown. It only sees the JSON fields described below.
    - MathJax supports **inline and display math inside `$...$` or `$$...$$`** with standard LaTeX math commands, but it does **not** support full TeX layout or diagram environments.
    - Therefore, you **must not** use any LaTeX environments that require a full TeX engine, such as `\\begin{{equation}}`, `\\begin{{align}}`, `\\begin{{displaymath}}`, `\\begin{{tikzcd}}`, `\\begin{{tikzpicture}}`, `\\begin{{CD}}`, `\\xymatrix`, `\\begin{{array}}`, `\\begin{{matrix}}`, or any diagram-producing environment. All diagrams must be represented **only** through the `visual_data` JSON system.

    YOUR TASK:
    Create a **{difficulty}** level question on the topic: **"{topic}"**.

    {correction_block}

    --- USER SPECIFICATIONS ---
    - **Course/Level**: {course} (Ensure notation and scope match this level exactly).
    - **Difficulty**: {difficulty} (Scale: Introductory -> Easy -> Medium -> Hard -> Challenge).
    - **Specific Details**: "{additional_details}"

    --- CONTENT GUIDELINES ---
    1. **Self-Contained**: The question must be solvable with the information provided.
    2. **Single Question Shape**: Provide a clear "question_stem" and exactly ONE part in "parts".
    3. **Visuals**: If the topic usually requires a diagram, generate the JSON `visual_data` object. If it's pure algebra, omit it.
    4. **MCQ Handling**: If the user asks for Multiple Choice, include "choices": [{{"label":"A", "text":"..."}}...] and "correct_choice": "A" inside the part.
    5. **No Drawing Requests**: Do not ask the student to "sketch/draw/plot."
    6. **Clean Answer**: Choose values that lead to a neat final result (integers, simple fractions/surds) when applicable.
    7. **No Phantom Diagrams**: If you mention a diagram/figure, you **must** supply `visual_data`. If you do not supply `visual_data`, do **not** refer to a diagram/figure/picture; provide explicit textual givens instead.
    8. **Piecewise / cases**: If you use a piecewise definition (e.g. `\\begin{{cases}} ... \\end{{cases}}`), keep each row short and clean:
       - Exactly ONE `&` per row (left side is the value, right side is the condition).
       - Do NOT put long explanations, “i.e.” clauses, or extra sentences inside `cases`. Keep the condition simple.
       - Place any long explanation or extra wording in normal text AFTER the displayed formula, not inside the `cases` environment.
       - Avoid nested parentheses and long `\\text{{...}}` blocks inside `cases`.
    9. **No LaTeX list environments**: Do NOT use `\\begin{{itemize}}`, `\\begin{{enumerate}}`, `\\begin{{description}}`, or any similar LaTeX list environment in any field. Do NOT use `\\item`. If you need to list facts or given values, write them as plain sentences separated by newlines, or as simple text bullets like `- first fact`, `- second fact`, using normal text (not inside math mode).
    10. **No LaTeX text-formatting commands in prose**: do **not** use `\\textbf{{...}}`, `\\emph{{...}}`, `\\textit{{...}}`, or similar styling commands in the question text or explanations. If you want emphasis, rewrite the sentence in plain words without any special formatting.

    --- VISUAL_DATA GUIDE (SELECTED) ---
    {visual_rules}

    --- OUTPUT FORMAT ---
    Do not use the backtick character ` anywhere in any field.
    Do not wrap $...$ or $$...$$ in backticks. No Markdown inline-code formatting.
    Return a single JSON object.
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
        "calculator_required": boolean,
        "visual_data": {{...}} // Optional
    }}

    --- PURPOSE OF SOLUTION AND FINAL ANSWER ---
    - `solution_text` is **not** a model answer for a student to read. It is an internal explanation for an **AI tutor** that will mark and discuss student work.
    - The goal of `solution_text` is to concisely make clear:
      - main mathematical steps,
      - definitions, constructions, or theorems used,
      - expected conclusions throughout stages of the solution.
    - It does **not** need to be written as a fully polished proof. Assume the reader is a mathematically competent AI.
    - Avoid re-stating the problem or copying the question text. Focus on the reasoning needed to solve the question.
    - `final_answer` is a compact summary of the final mathematical conclusions.
    - `final_answer` should only contain essential end results, not another full solution.

    **MATH FORMATTING RULES (STRICT)**:
    - Use **LaTeX commands** for ALL mathematics: `\\frac{{...}}{{...}}`, `\\sqrt{{...}}`, `\\cdot`, `\\times`, `\\ln`, `\\sin`, `\\cos`, etc.
    - Use `$...$` for inline math and `$$...$$` for display math.
    - Do **NOT** use any custom math markers like `$begin:math:text$`.
    - Do **NOT** use LaTeX math environments such as `\\begin{{equation}} ... \\end{{equation}}`, `\\begin{{align}} ... \\end{{align}}`, or `\\begin{{displaymath}} ... \\end{{displaymath}}`. Use `$$...$$` instead.
    - Never use diagram-producing LaTeX environments such as `\\begin{{tikzcd}} ... \\end{{tikzcd}}`, `\\begin{{tikzpicture}} ... \\end{{tikzpicture}}`, `\\begin{{CD}} ... \\end{{CD}}`, `\\xymatrix{{...}}`, `\\begin{{array}} ... \\end{{array}}`, `\\begin{{matrix}} ... \\end{{matrix}}`. Any diagram must be expressed **only** through the `visual_data` JSON system.
    - **Backslashes**: in the final math, every LaTeX command must start with a single backslash (e.g. `\\frac`, `\\sqrt`). Do **NOT** produce commands that effectively start with two backslashes in the final string (like `\\\\frac`).
    - Do **not** use the LaTeX linebreak command `\\\\` inside math. If you need a new sentence, write a new sentence in plain text.
    - All LaTeX macros MUST start with a backslash and MUST be inside math mode.
    - **NEVER** output plain-text math like `sqrt(3x+1)`; always use LaTeX forms like `\\sqrt{{3x+1}}`.
    - Every macro that takes arguments **must** use braces.
    - Do not use Markdown styling like `**bold**` inside any field, and do **not** use LaTeX text-formatting commands such as `\\textbf{{...}}` in prose.
    """
    
    return dedent(prompt).strip()