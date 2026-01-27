from textwrap import dedent

from .prompts_visual_data_guide import get_visual_rules_snippet


def build_text_drill_prompt(
    *,
    topic: str,
    course: str,
    difficulty: str,
    # question_type removed as requested
    additional_details: str = "",
    correction_prompt_section: str = "",
) -> str:
    """
    Prompt for generating questions from scratch based on user topic/course/difficulty.

    IMPORTANT PIPELINE FACT:
    - Your validator can repair INVALID JSON escapes like \langle by turning them into \\langle.
    - But it CANNOT repair \text or \frac written with a single backslash in JSON source,
      because JSON treats \t and \f as VALID escapes (TAB / formfeed) and parsing succeeds.
    - Therefore the model MUST output LaTeX backslashes as DOUBLE backslashes in JSON source.
    """

    correction_block = (
        f"\n**PREVIOUS ERROR & CORRECTION**:\n{correction_prompt_section.strip()}\n"
        if correction_prompt_section
        else ""
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

    prompt = f"""
You are an expert Mathematics Content Creator for the **{course}** curriculum.

--- SYSTEM CONTEXT (READ CAREFULLY) ---
- You are generating a **single JSON object** that will be consumed by an automated mobile learning app (iPad) called ALMA.
- Your JSON is parsed programmatically and the text fields (question_stem, question_text, solution_text, final_answer, and any text in visual_data) are rendered using **MathJax** inside a WebView.
- The app does **not** see LaTeX documents, TeX preambles, or Markdown. It only sees the JSON fields described below.
- MathJax supports inline/display math inside $...$ or $$...$$ with standard LaTeX math commands.
- Therefore, you must NOT use full-TeX environments like:
  \\begin{{equation}}, \\begin{{align}}, \\begin{{tikzpicture}}, \\begin{{matrix}}, etc.
  All diagrams must be represented ONLY through the visual_data JSON system.

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
3. Visuals: If the topic usually requires a diagram/graph, include visual_data. If not needed, omit it.
4. MCQ Handling: If the user asks for Multiple Choice, include:
   - "choices": [{{"label":"A","text":"..."}}, ...]
   - "correct_choice": "A"
   inside the part.
5. No Drawing Requests: Do not ask the student to "sketch/draw/plot."
6. Clean Answer: Choose values that lead to neat final results.
7. No Phantom Diagrams: If you mention a diagram/figure/graph, you MUST supply visual_data.

8. Piecewise / cases:
- If you use a piecewise definition, use ONLY \\begin{{cases}} ... \\end{{cases}}.

9. No LaTeX list environments:
- Do NOT use \\begin{{itemize}}, \\begin{{enumerate}}, \\begin{{description}}, or \\item.
- If you need a list, use plain sentences separated by newlines.

10. No LaTeX text-formatting commands in prose:
- Do not use \\textbf{{...}}, \\emph{{...}}, \\textit{{...}}.

--- VISUAL_DATA GUIDE (SELECTED) ---
{visual_rules}

--- OUTPUT FORMAT ---
Return a single JSON object only.
No markdown code fences. No commentary. No backticks.

Example shape:
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
  "calculator_required": false,
  "visual_data": {{...}}
}}

Only include "visual_data" if you referenced any visual/graph/figure.

--- PURPOSE OF SOLUTION AND FINAL ANSWER ---
- solution_text is internal reasoning for an AI tutor/checker (NOT a student-facing worked solution).
- final_answer is a compact summary of the end result only.

--- JSON TECHNICAL RULES (CRITICAL) ---
You are writing JSON SOURCE. The app will json-parse it, then MathJax renders the resulting strings.

A) Newlines:
- To create a real line break inside a JSON string, use \\n (single backslash + n) in the JSON source.
Correct:
  "question_stem": "Line 1.\\nLine 2."
Wrong:
  "question_stem": "Line 1.\\\\nLine 2."  (shows \\n literally)

B) LaTeX backslashes inside JSON strings (MAIN RULE):
- In JSON SOURCE, every LaTeX command backslash MUST be escaped as DOUBLE backslash.
  That means: write \\\\text, \\\\frac, \\\\sqrt, \\\\theta, \\\\gamma, \\\\beta, \\\\mu, \\\\pi, \\\\to, \\\\circ, etc. in JSON source.

WHY:
- JSON treats \\t and \\f as valid escapes (TAB / formfeed).
- So if you write "\\text{{MeV}}" or "\\frac{{dx}}{{dt}}" with a single backslash in JSON source,
  JSON will silently corrupt the string and MathJax will break.

C) ABSOLUTE RULE: ALL MATH TOKENS MUST BE INSIDE $...$ OR $$...$$
This includes:
- greek letters (gamma, theta, beta, mu, pi)
- subscripts/superscripts (gamma_1, tau_0, pi^0)
- angles (30^\\circ)
- units written with \\text{{...}}
WRONG (will render as plain text and break):
  "two photons, gamma_1 and gamma_2."
  "theta = 30^\\\\circ"
RIGHT:
  "two photons, $\\\\gamma_1$ and $\\\\gamma_2$."
  "angle $\\\\theta = 30^\\\\circ$."
  "decay $\\\\pi^0 \\\\to \\\\gamma_1 + \\\\gamma_2$."

D) Units + \\text{{...}} (prevents the 'textMeV' bug):
- NEVER put leading/trailing spaces inside \\text{{...}}.
  - BAD:  $300\\,\\\\text{{ MeV }}$
  - BAD:  $300\\,\\\\text{{ MeV}}$
  - GOOD: $300\\,\\\\text{{MeV}}$
- Use LaTeX thin-space command \\, between a number and a unit.
  In JSON SOURCE that looks like: "\\\\," (because backslash must be doubled)
  Example JSON source:
    "M_0 = 300\\\\,\\\\text{{MeV}}/c^2"
    "E = 500\\\\,\\\\text{{MeV}}"

Correct JSON source examples (YOU MUST OUTPUT THESE FORMS EXACTLY):
  "question_text": "Units: $300\\\\,\\\\text{{MeV}}$."
  "question_text": "Compute $\\\\frac{{dx}}{{dt}}$."
  "question_text": "Angle $\\\\theta = 90^\\\\circ$."
  "question_text": "Decay $\\\\pi^0 \\\\to \\\\gamma_1 + \\\\gamma_2$."
  "question_text": "Speed $v_{{\\\\mu}} = 0.990c$."

Do NOT over-escape:
- Do NOT write \\\\\\\\text or \\\\\\\\frac in JSON source.

--- MATH FORMATTING RULES (STRICT) ---
- All math MUST be inside $...$ or $$...$$.
- Use standard LaTeX commands inside math: \\\\frac{{...}}{{...}}, \\\\sqrt{{...}}, \\\\cdot, \\\\times,
  \\\\ln, \\\\sin, \\\\cos, \\\\theta, \\\\gamma, \\\\beta, \\\\mu, \\\\pi, \\\\to, \\\\circ, \\\\text{{...}}, etc.
- Do NOT use \\begin{{equation}}...\\end{{equation}} or \\begin{{align}}...\\end{{align}}; use $$...$$ instead.
- Do not use the LaTeX linebreak command \\\\ inside math.

Return ONLY the JSON object.
"""
    return dedent(prompt).strip()