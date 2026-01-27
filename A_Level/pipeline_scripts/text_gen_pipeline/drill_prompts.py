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
    - JSON escaping is the root cause of repeated LaTeX corruption in this pipeline.
    - Therefore: the model must NEVER output a raw backslash "\\" in any LaTeX.
    - Instead, the model MUST use the token [[BS]] everywhere a LaTeX backslash would appear.
      After JSON parsing, the backend will replace [[BS]] -> "\\" safely.

    EXTRA CRITICAL:
    - NEVER output the LaTeX newline command inside math.
      That means: NEVER output [[BS]][[BS]]in, [[BS]][[BS]]times, [[BS]][[BS]]mathbb, etc.
      [[BS]][[BS]] inside $...$ or $$...$$ will be interpreted as a TeX linebreak and will break macros.
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
  [[BS]]begin{{equation}}, [[BS]]begin{{align}}, [[BS]]begin{{tikzpicture}}, [[BS]]begin{{matrix}}, etc.
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
- If you use a piecewise definition, use ONLY [[BS]]begin{{cases}} ... [[BS]]end{{cases}}.

9. No LaTeX list environments:
- Do NOT use [[BS]]begin{{itemize}}, [[BS]]begin{{enumerate}}, [[BS]]begin{{description}}, or [[BS]]item.
- If you need a list, use plain sentences separated by newlines.

10. No LaTeX text-formatting commands in prose:
- Do not use [[BS]]textbf{{...}}, [[BS]]emph{{...}}, [[BS]]textit{{...}}.

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

B) ABSOLUTE RULE: NEVER OUTPUT A RAW BACKSLASH FOR LATEX
- You MUST NOT output "\\" anywhere for LaTeX.
- Instead, use the token [[BS]] for EVERY LaTeX command backslash.

Examples (copy exactly):
- $[[BS]]gamma_1$, $[[BS]]theta$, $[[BS]]beta$, $[[BS]]mu$, $[[BS]]pi$
- $[[BS]]sqrt{{1 - [[BS]]beta^2}}$
- $[[BS]]frac{{dx}}{{dt}}$
- $30^{{[[BS]]circ}}$
- $[[BS]]pi^0 [[BS]]to [[BS]]gamma_1 + [[BS]]gamma_2$
- $E_{{[[BS]]gamma}}$ for photon energy symbol

IMPORTANT:
- Do NOT output "[[BS]][[BS]]" inside $...$ or $$...$$.
  That sequence is a TeX linebreak and will corrupt macros (it causes 'vinmathbbC^n', 'ntimesn', etc.).
  Always use a SINGLE [[BS]] before every LaTeX command:
  - RIGHT: $v [[BS]]in [[BS]]mathbb{{C}}^n$
  - WRONG: $v [[BS]][[BS]]in [[BS]][[BS]]mathbb{{C}}^n$
- Do NOT output "\\\\" either. Do NOT output "\\text". Do NOT output "\\frac". Use [[BS]]text / [[BS]]frac.
- The backend will convert [[BS]] -> "\\" after parsing. You must keep [[BS]] exactly as written (uppercase).

C) ABSOLUTE RULE: ALL MATH TOKENS MUST BE INSIDE $...$ OR $$...$$
This includes:
- greek letters (gamma, theta, beta, mu, pi)
- subscripts/superscripts (gamma_1, tau_0, pi^0)
- angles (30^{{[[BS]]circ}})
- set notation and linear algebra macros (\\in, \\mathbb, \\times, \\cdot, etc.) using [[BS]].

WRONG:
  "two photons, gamma_1 and gamma_2."
  "theta = 30^circ"
  "$v [[BS]][[BS]]in [[BS]][[BS]]mathbb{{C}}^n$"
  "$n [[BS]][[BS]]times n$"
RIGHT:
  "two photons, $[[BS]]gamma_1$ and $[[BS]]gamma_2$."
  "angle $[[BS]]theta = 30^{{[[BS]]circ}}$."
  "$v [[BS]]in [[BS]]mathbb{{C}}^n$"
  "$n [[BS]]times n$"

D) Units rule:
- You may write units as plain text outside math (preferred), e.g. "135 MeV/c^2".
- Do NOT use [[BS]]text{{...}} for units unless necessary.

E) No commas between a number and a unit:
BAD: "$M_0 = 135, ...$"
GOOD: "$M_0 = 135$ MeV/$c^2$"

--- MATH FORMATTING RULES (STRICT) ---
- All math MUST be inside $...$ or $$...$$.
- Use standard LaTeX commands (with [[BS]]): [[BS]]frac{{...}}{{...}}, [[BS]]sqrt{{...}}, [[BS]]cdot, [[BS]]times,
  [[BS]]ln, [[BS]]sin, [[BS]]cos, [[BS]]theta, [[BS]]gamma, [[BS]]beta, [[BS]]mu, [[BS]]pi, [[BS]]to, [[BS]]circ, [[BS]]in, [[BS]]mathbb, etc.
- Do NOT use [[BS]]begin{{equation}}...[[BS]]end{{equation}} or [[BS]]begin{{align}}...[[BS]]end{{align}}; use $$...$$ instead.
- Do not use the LaTeX linebreak command [[BS]][[BS]] inside math.

Return ONLY the JSON object.
"""
    return dedent(prompt).strip()