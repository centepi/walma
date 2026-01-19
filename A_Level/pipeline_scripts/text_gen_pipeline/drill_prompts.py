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
    Includes the FULL visual_data specification and STRICT math rules to match existing pipeline standards.
    """
    correction_block = (
        f"\n**PREVIOUS ERROR & CORRECTION**:\n{correction_prompt_section.strip()}\n"
        if correction_prompt_section else ""
    )

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
    3. **Visuals**: If the topic (e.g., Geometry, Graph Theory) usually requires a diagram, generate the JSON `visual_data` object. If it's a pure algebra problem, omit it.
    4. **MCQ Handling**: If the user asks for Multiple Choice, include "choices": [{{"label":"A", "text":"..."}}...] and "correct_choice": "A" inside the part.
    5. **No Drawing Requests**: Do not ask the student to "sketch/draw/plot."
    6. **Clean Answer**: Choose values that lead to a neat final result (integers, simple fractions/surds) when applicable.
    7. **No Phantom Diagrams**: If you mention a diagram/figure, you **must** supply `visual_data`. If you do not supply `visual_data`, do **not** refer to a diagram/figure/picture; provide explicit textual givens instead.
    8. **Piecewise / cases**: If you use a piecewise definition (e.g. `\\begin{{cases}} ... \\end{{cases}}`), keep each row short and clean:
       - Exactly ONE `&` per row (left side is the value, right side is the condition).
       - Do NOT put long explanations, “i.e.” clauses, or extra sentences inside `cases`. Keep the condition simple (for example: `\\text{{if }} x = p/q \\text{{ in lowest terms}}`).
       - Place any long explanation or extra wording in normal text AFTER the displayed formula, not inside the `cases` environment.
       - Avoid nested parentheses and long `\\text{{...}}` blocks inside `cases`.
    9. **No LaTeX list environments**: Do NOT use `\\begin{{itemize}}`, `\\begin{{enumerate}}`, `\\begin{{description}}`, or any similar LaTeX list environment in any field. Do NOT use `\\item`. If you need to list facts or given values, write them as plain sentences separated by newlines, or as simple text bullets like `- first fact`, `- second fact`, using normal text (not inside math mode).
    10. **No LaTeX text-formatting commands in prose**: do **not** use `\\textbf{{...}}`, `\\emph{{...}}`, `\\textit{{...}}`, or similar styling commands in the question text or explanations. If you want emphasis, rewrite the sentence in plain words without any special formatting.

    {get_visual_rules_snippet()}
    
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
    - It does **not** need to be written as a fully polished, pedagogical, line-by-line textbook proof. Assume the reader is a mathematically competent AI, not a struggling student.
    - Avoid re-stating the problem or copying the question text. Focus on the mathematical reasoning needed to solve the question, not on motivational exposition or extra teaching commentary.
    - `final_answer` is a compact summary of the final mathematical conclusions, for quick reference by the tutor and checker.
    - `final_answer` should only contain the essential end results (values, classifications, properties), **not** another full solution or long explanation. Do not duplicate the entire solution in `final_answer`.

    **MATH FORMATTING RULES (STRICT)**:
    - Use **LaTeX commands** for ALL mathematics: `\\frac{{...}}{{...}}`, `\\sqrt{{...}}`, `\\cdot`, `\\times`, `\\ln`, `\\sin`, `\\cos`, etc.
    - Use `$...$` for inline math and `$$...$$` for display math.
    - Do **NOT** use `\$begin:math:display$ \\.\\.\\. \\$end:math:display$`, backticks, or any custom math markers like `$begin:math:text$`.
    - Do **NOT** use LaTeX math environments such as `\$begin:math:display$ \\.\\.\\. \\$end:math:display$`, `\$begin:math:text$ \\.\\.\\. \\$end:math:text$`, `\\begin{{equation}} ... \\end{{equation}}`, `\\begin{{align}} ... \\end{{align}}`, or `\\begin{{displaymath}} ... \\end{{displaymath}}`. If you want a standalone displayed formula, wrap it in `$$...$$` instead.
    - Never use diagram-producing LaTeX environments such as `\\begin{{tikzcd}} ... \\end{{tikzcd}}`, `\\begin{{tikzpicture}} ... \\end{{tikzpicture}}`, `\\begin{{CD}} ... \\end{{CD}}`, `\\xymatrix{{...}}`, `\\begin{{array}} ... \\end{{array}}`, `\\begin{{matrix}} ... \\end{{matrix}}`, or any custom diagram environment. Any diagram, commutative square, or geometric picture must be expressed **only** through the `visual_data` JSON system, not through LaTeX.
    - **Backslashes**: in the final math, every LaTeX command must start with a single backslash (for example `\\frac`, `\\sqrt`, `\\begin{{cases}}`). Do **NOT** produce commands that effectively start with two backslashes in the final string (such as `\\\\frac`, `\\\\sqrt`, or `\\\\begin{{cases}}`); these render as plain text and break MathJax.
    - Do **not** use the LaTeX linebreak command `\\\\` inside math (no `\\\\` at the TeX level). If you need a new sentence, end the sentence in plain text instead of using a LaTeX linebreak.
    - All LaTeX macros MUST start with a backslash and MUST be inside math mode:
      - Always write things like `\\text{{Re}}(s)`, `\\operatorname{{Re}}(s)`, `\\lfloor x \\rfloor`, `\\{{x\\}}`, `\\gcd(p,q)`, `\\Gamma(s)`.
      - NEVER write macros without the backslash (for example `ext{{Re}}(s)`, `text{{Re}}(s)`, `operatorname{{Re}}(s)`, `gcd(p,q)`, `floor x`, etc.).
      - NEVER place these macros in plain text outside `$...$` or `$$...$$`. Wrap them in math fences.
    - **NEVER** output plain-text math like `sqrt(3x+1)`, `sqrt3x+1`, `frac{{e^{{4x}}}}{{(2x+1)^3}}`, or exponents without braces.
    - Every macro that takes arguments **must** use braces: `\\sqrt{{3x+1}}`, `\\frac{{e^{{4x}}}}{{(2x+1)^3}}`, `(x-1)^3\\sqrt{{4x}}`.
    - Do not use Markdown styling like `**bold**` inside any field, and do **not** use LaTeX text-formatting commands such as `\\textbf{{...}}` or `\\emph{{...}}` in prose. If emphasis is needed in the question text, simply use plain wording without any special styling.
    - Do **NOT** introduce LaTeX list environments in math or text (for example `\\begin{{itemize}}`, `\\begin{{enumerate}}`, `\\item`). When you need a list of known facts, write them as plain sentences separated by newlines, or as simple text bullets such as `- fact one`, `- fact two`.
    """
    
    return dedent(prompt).strip()