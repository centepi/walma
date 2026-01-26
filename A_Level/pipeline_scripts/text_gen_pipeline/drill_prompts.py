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
    Includes the visual_data specification (SELECTED snippet) and STRICT math rules.

    CRITICAL:
    This prompt teaches the model how to write JSON that will later be parsed and then rendered by MathJax.
    We use a RAW f-string (rf-string) so backslashes in the rules are shown literally to the model.
    """
    correction_block = (
        f"\n**PREVIOUS ERROR & CORRECTION**:\n{correction_prompt_section.strip()}\n"
        if correction_prompt_section else ""
    )

    # ---------------------------------------------------------------------
    # VISUAL GUIDE SELECTION (keep prompts short)
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

    if wants_geometry:
        visual_rules = get_visual_rules_snippet(only_types=["geometry"])
    else:
        visual_rules = get_visual_rules_snippet(only_types=["function"])

    # ✅ RAW f-string so the model sees literal backslashes in the rules below.
    # ⚠️ Because this is an f-string, any literal { or } shown to the model must be written as {{ or }} here.
    prompt = rf"""
You are an expert Mathematics Content Creator for the **{course}** curriculum.

--- SYSTEM CONTEXT (READ CAREFULLY) ---
- You are generating a **single JSON object** that will be consumed by an automated mobile learning app (iPad) called ALMA.
- Your JSON is parsed programmatically and the text fields (question_stem, question_text, solution_text, final_answer, and any text in visual_data) are rendered using **MathJax** inside a WebView.
- The app does **not** see LaTeX documents, TeX preambles, or Markdown. It only sees the JSON fields described below.
- MathJax supports **inline and display math inside $...$ or $$...$$** with standard LaTeX math commands.
- Therefore, you **must not** use any LaTeX environments that require a full TeX engine, such as:
  \begin{{equation}}, \begin{{align}}, \begin{{displaymath}}, \begin{{tikzcd}}, \begin{{tikzpicture}},
  \begin{{CD}}, \xymatrix, \begin{{array}}, \begin{{matrix}}, or any diagram-producing environment.
  All diagrams must be represented **only** through the visual_data JSON system.

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
4. MCQ Handling: If the user asks for Multiple Choice, include:
   - "choices": [{{"label":"A","text":"..."}}, ...]
   - "correct_choice": "A"
   inside the part.
5. No Drawing Requests: Do not ask the student to "sketch/draw/plot."
6. Clean Answer: Choose values that lead to neat final results (integers, simple fractions/surds) when applicable.
7. No Phantom Diagrams: If you mention a diagram/figure, you MUST supply visual_data. If you do not supply visual_data, do not refer to a diagram/figure/picture.

8. Piecewise / cases:
- If you use a piecewise definition, use ONLY \begin{{cases}} ... \end{{cases}}.
- Keep each row short and clean.
- Avoid long explanations inside cases; put explanations in normal text after the displayed formula.

9. No LaTeX list environments:
- Do NOT use \begin{{itemize}}, \begin{{enumerate}}, \begin{{description}}, or \item.
- If you need a list, write plain sentences separated by real newlines (see JSON newline rules below).

10. No LaTeX text-formatting commands in prose:
- Do not use \textbf{{...}}, \emph{{...}}, \textit{{...}}.

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
- solution_text is internal reasoning for an AI tutor/checker (not a student-facing worked solution).
- final_answer is a compact summary of the end result only.

--- JSON ESCAPING RULES (CRITICAL) ---
You are writing JSON. The app will parse your JSON, then render the resulting strings with MathJax.

A) Newlines (IMPORTANT):
- To create a real line break inside a JSON string, use the normal JSON escape: \n
- Write it as \n (single backslash + n) in the JSON source.
- Do NOT write \\n in the JSON source. That produces the visible characters "\n" in the app.

Correct:
  "question_stem": "Line 1.\nLine 2."
Wrong:
  "question_stem": "Line 1.\\nLine 2."   (this shows \n literally)

B) LaTeX commands (THIS HAS BEEN BREAKING YOUR OUTPUT):
- Write LaTeX exactly as it should appear to the student, with a SINGLE backslash:
  \frac, \sqrt, \theta, \gamma, \text, \circ, \leq, \pi, etc.
- Do NOT “JSON-escape” LaTeX yourself by doubling backslashes.
  (The backend parser/validator will repair JSON backslashes safely.)

Correct (what the student should ultimately see / what MathJax expects):
  "$\frac{{1}}{{2}}$"
  "$\theta = 120^\circ$"
  "$\text{{MeV}}$"
Wrong (over-escaped, breaks MathJax):
  "$\\theta$" or "$\\text{{MeV}}$"

--- MATH FORMATTING RULES (STRICT) ---
- All math MUST be inside $...$ or $$...$$.
- Use standard LaTeX commands inside math: \frac{{...}}{{...}}, \sqrt{{...}}, \cdot, \times, \ln, \sin, \cos, \theta, \gamma, \circ, \text{{...}}, etc.
- Do NOT use custom math markers.
- Do NOT use \begin{{equation}}...\end{{equation}} or \begin{{align}}...\end{{align}}; use $$...$$ instead.
- Do not use the LaTeX linebreak command \\ inside math.
- Never output plain-text math like sqrt(3x+1); always use LaTeX like \sqrt{{3x+1}} (inside $...$ or $$...$$).

Return ONLY the JSON object.
"""
    return dedent(prompt).strip()