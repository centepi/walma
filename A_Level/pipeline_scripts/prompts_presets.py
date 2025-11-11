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

    # --- NEW SECTION: DOMAIN & SKILL LOCK ---
    domain_skill_block = """
    **DOMAIN & SKILL LOCK**
    Before generating the new question, carefully infer the following from the original context:
    - **Domain/Topic**: Identify the main mathematical area (e.g., topology, graph theory, linear algebra, calculus, statistics, etc.).
    - **Core Skills**: Identify what kinds of reasoning or techniques were required (e.g., prove equivalence, construct counterexample, apply definition, compute derivative, solve system, interpret a graph, etc.).
    - **Difficulty Level**: Match the level of reasoning, abstraction, and number of steps in the original. Do not simplify.
    - **Structure Awareness**: If the original question used proof-style verbs (“Show that”, “Hence”, “Prove”), retain that proof-oriented nature. If it was computational, remain computational.
    - **Visual Awareness**: If the original question relied on a diagram or visual representation, describe that structure clearly in text form (e.g., define a topological space, describe a network, or specify coordinates for a shape) rather than removing it.

    You MUST:
    - Keep the same domain and core skills.
    - Match the original difficulty band (no trivialisation).
    - Keep a similar number of reasoning or calculation steps.
    - Never drift to unrelated topics. For example:
        • If the source was topology, do NOT switch to geometry or trigonometry.
        • If the source was graph theory, do NOT output calculus or algebra problems.
        • If the source was a proof question, do NOT replace it with a numerical computation.
    """

    # --- NEW SECTION: DIAGRAM DISCIPLINE ---
    diagram_block = """
    **DIAGRAM DISCIPLINE (No Phantom Figures)**
    - Do **not** mention a “diagram/figure/picture” **unless** you actually include a `visual_data` object in the JSON.
    - If you cannot (or should not) provide `visual_data`, rewrite the givens explicitly in text so the problem is fully solvable without any image.
      Use neutral phrasing such as “Consider a two-component link with four signed crossings …” instead of “The diagram shows …”.
    - When replacing visuals, encode necessary information textually (e.g., signed crossing sequence, incidence lists for arcs at crossings,
      adjacency data, coordinates/parameters), preserving the same skill and step count.
    """

    prompt = f"""
    {context_header.strip()}

    You are an expert A-level Mathematics content creator. Your task is to create a NEW, ORIGINAL, and SELF-CONTAINED A-level question.

    {correction_block}

    --- CONTEXT: THE FULL ORIGINAL QUESTION (for skill + style only; do NOT copy) ---
    {full_reference_text}

    --- INSPIRATION: THE TARGET PART ---
    - Reference Part Content: "{target_part_content}"
    - Reference Part Solution (if available): "{(target_part_answer or '').strip()}"

    {dedent(domain_skill_block).strip()}

    {dedent(diagram_block).strip()}

    --- YOUR TASK ---
    Create ONE self-contained question that tests the same mathematical skill as the target part above, following the specified OUTPUT FORMAT.

    **CRITICAL INSTRUCTIONS**:
    1.  **Single Question Shape**: Provide a clear "question_stem" and exactly ONE part in "parts".
        - If the task naturally fits in one sentence, you may leave "question_stem" empty and put the whole prompt in "parts[0].question_text".
        - Never duplicate the same sentence across stem and part.
    2.  **Multiple-Choice Handling (IMPORTANT)**:
        - If the source looks like a multiple-choice item (a single prompt with several short labelled options such as A/B/C/D or (a)/(b)/(c) that are *answers*, not sub-parts),
          then produce **ONE** question with options inside the single part — **do not** create separate questions per option.
        - In this MCQ case, include inside the single part:
            * "choices": a list of 4–5 options, each as {{ "label": "A", "text": "<option text with LaTeX where needed>" }}.
            * "correct_choice": the label of the correct option, e.g., "B".
            * Keep "solution_text" explaining why the correct option is right (and briefly why others are wrong).
            * Set "final_answer" to the **mathematical value or exact text** of the correct option (not just the letter),
              so computer algebra checks can still apply when appropriate (e.g., use "1/2" rather than "B").
        - **Never** split MCQ options into separate parts or separate questions.
    3.  **Invent Values**: Use fresh numbers/functions/scenarios to avoid copying.
    4.  **Clean Answer**: Choose values that lead to a neat final result (integers, simple fractions/surds) when applicable.
    5.  **Contextual Visuals Only**: Any 'visual_data' must aid understanding and must NOT encode the answer.
    6.  **Include Visuals if Appropriate**: Only when the skill is inherently visual.
    7.  **Calculator Use**: Set 'calculator_required' appropriately.
    8.  **NO DRAWING REQUESTS**: Do not ask to "sketch/draw/plot"; convert to textual reasoning.
    9.  **FINAL ANSWER FIELD**: Inside the single part object, include a concise 'final_answer' string.
    10. **No Phantom Diagrams**: If you mention a diagram/figure, you **must** supply `visual_data`. If you do not supply `visual_data`, do **not** refer to a diagram/figure/picture; provide explicit textual givens instead.

    {dedent(keep_block).strip()}

    **MATH FORMATTING RULES (STRICT)**:
    - Use **LaTeX commands** for ALL mathematics: `\\frac{{...}}{{...}}`, `\\sqrt{{...}}`, `\\cdot`, `\\times`, `\\ln`, `\\sin`, `\\cos`, etc.
    - Use `$begin:math:text$...$end:math:text$` for inline math and `$begin:math:display$...$end:math:display$` for display math. `$...$` and `$$...$$` are also accepted. **Do not put a backslash before `$begin:` or `$end:` and do not wrap these fences in extra `$` or backticks.**
    - **NEVER** output plain-text math like `sqrt(3x+1)`, `sqrt3x+1`, `frac{{e^{{4x}}}}{{(2x+1)^3}}`, or exponents without braces.
    - Every macro that takes arguments **must** use braces: `\\sqrt{{3x+1}}`, `\\frac{{e^{{4x}}}}{{(2x+1)^3}}`, `(x-1)^3\\sqrt{{4x}}`.
    - Do not use Markdown styling like `**bold**` inside any field. If emphasis is needed, prefer plain text or `\\textbf{{...}}` inside math.

    **Examples — follow EXACTLY**:
    - Non-MCQ OK:  Find the gradient of the curve $y = (x-1)^3\\sqrt{{4x}}$ at $x=4$.
    - Non-MCQ OK:  Given $f(x) = \\frac{{e^{{4x}}}}{{(2x+1)^3}}$, find $f'(x)$.
    - MCQ OK (shape only): one stem + one part whose `question_text` states the task; include  
      `"choices": [{{"label":"A","text":"..."}}, {{"label":"B","text":"..."}}, ...]`,  
      `"correct_choice": "B"`, and set `"final_answer"` to the correct option’s value/text.
    - BAD: Treating each option (A/B/C/…) as separate questions.

     **OUTPUT FORMAT**:
    Your output MUST be a single, valid JSON object with the following structure:
    {{
    "question_stem": "A concise introduction/setup for your new question.",
    "parts": [
        {{
        "part_label": "a",
        "question_text": "The single task for the user to perform.",
        "solution_text": "The detailed, step-by-step solution to your new question."
        }}
    ],
    "calculator_required": true,
    "visual_data": {{...}} // Omit this key entirely if no visual is needed
    }}

    **'visual_data' STRUCTURE - COMPREHENSIVE GUIDE**:

    The 'visual_data' object adapts its structure based on the chart type being visualized. Always include a 'charts' array (not 'graphs' for non-explicit-function charts). Choose ONE of the following chart type structures:

    ---

    ### **TYPE 1: EXPLICIT MATHEMATICAL FUNCTIONS (y = f(x))**
    Use this for traditional function plots, parabolas, polynomials, trigonometric functions, etc.

    Structure:
    {{
        "charts": [
            {{
                "id": "g1",
                "label": "y = f(x)",
                "type": "function",
                "explicit_function": "A Python-compatible expression like 'x**2 - 4*x + 7'",
                "visual_features": {{
                    "type": "parabola|cubic|polynomial|trigonometric|exponential|logarithmic|rational",
                    "x_intercepts": [1.0, 3.0] or null,
                    "y_intercept": 7 or null,
                    "turning_points": [
                        {{"x": 2.0, "y": 3.0, "type": "minimum|maximum|inflection"}}
                    ] or null,
                    "vertical_asymptotes": [x_value1, x_value2] or null,
                    "horizontal_asymptote": y_value or null,
                    "axes_range": {{
                        "x_min": -1,
                        "x_max": 5,
                        "y_min": 0,
                        "y_max": 10
                    }}
                }}
            }}
        ],
        "labeled_points": [
            {{"label": "A", "x": 1.0, "y": 4.0}}
        ] // Optional
        "shaded_regions": [
            {{
                "upper_bound_id": "g1",
                "lower_bound_id": "y=0",
                "x_start": 1.0,
                "x_end": 4.0
            }}
        ] // Optional
    }}

    ---

    ### **TYPE 2: HISTOGRAMS**
    Use this for frequency distributions, grouped data, or continuous data analysis.

    Structure:
    {{
        "charts": [
            {{
                "id": "h1",
                "label": "Distribution of Heights",
                "type": "histogram",
                "visual_features": {{
                    "type": "histogram",
                    "bins": [
                        [150, 160],
                        [160, 170],
                        [170, 180],
                        [180, 190]
                    ],
                    "frequencies": [5, 12, 18, 8],
                    "axes_range": {{
                        "x_min": 145,
                        "x_max": 195,
                        "y_min": 0,
                        "y_max": 20
                    }}
                }}
            }}
        ]
    }}

    **Key Points for Histograms:**
    - "bins": Array of [lower, upper] intervals (each bin is a 2-element array)
    - "frequencies": Array of frequency counts (must match number of bins)
    - All intervals should be contiguous and non-overlapping
    - Do NOT include frequency density; use raw frequencies
    - Include axes_range to ensure proper scaling

    ---

    ### **TYPE 3: BAR CHARTS**
    Use this for categorical data, discrete comparisons, or grouped data.

    Structure:
    {{
        "charts": [
            {{
                "id": "b1",
                "label": "Sales by Region",
                "type": "bar",
                "visual_features": {{
                    "type": "bar",
                    "categories": ["North", "South", "East", "West"],
                    "values": [45, 38, 52, 31],
                    "axes_range": {{
                        "x_min": -0.5,
                        "x_max": 3.5,
                        "y_min": 0,
                        "y_max": 60
                    }}
                }}
            }}
        ]
    }}

    **Key Points for Bar Charts:**
    - "categories": Array of category labels (strings)
    - "values": Array of bar heights (numbers, must match category count)
    - Categories are typically on x-axis
    - Use for discrete, non-continuous data

    ---

    ### **TYPE 4: SCATTER PLOTS**
    Use this for correlation analysis, bivariate data, or point relationships.

    Structure:
    {{
        "charts": [
            {{
                "id": "s1",
                "label": "Age vs Income",
                "type": "scatter",
                "visual_features": {{
                    "type": "scatter",
                    "data_points": [
                        {{"x": 25, "y": 30000}},
                        {{"x": 35, "y": 55000}},
                        {{"x": 45, "y": 75000}},
                        {{"x": 55, "y": 85000}}
                    ],
                    "trend_line": {{
                        "enabled": true,
                        "equation": "y = 1200*x + 5000"
                    }} // Optional
                    "axes_range": {{
                        "x_min": 20,
                        "x_max": 60,
                        "y_min": 20000,
                        "y_max": 90000
                    }}
                }}
            }}
        ]
    }}

    **Key Points for Scatter Plots:**
    - "data_points": Array of {{x, y}} coordinate pairs
    - "trend_line": Optional object with enabled flag and equation string
    - Use for bivariate relationships or correlation studies

    ---

    ### **TYPE 5: BOX PLOTS / BOX-AND-WHISKER PLOTS**
    Use this for distribution, quartiles, and outlier detection.

    Structure:
    {{
        "charts": [
            {{
                "id": "bp1",
                "label": "Test Score Distribution",
                "type": "box_plot",
                "visual_features": {{
                    "type": "box_plot",
                    "groups": ["Group A", "Group B"],
                    "min_values": [35, 42],
                    "q1_values": [60, 58],
                    "median_values": [75, 72],
                    "q3_values": [85, 80],
                    "max_values": [98, 95],
                    "outliers": [
                        {{"group": "Group A", "value": 110}},
                        {{"group": "Group B", "value": 105}}
                    ] // Optional
                    "axes_range": {{
                        "x_min": -0.5,
                        "x_max": 1.5,
                        "y_min": 30,
                        "y_max": 120
                    }}
                }}
            }}
        ]
    }}

    **Key Points for Box Plots:**
    - "min_values", "q1_values", "median_values", "q3_values", "max_values": Five-number summary
    - "outliers": Optional array of individual outlier points
    - Use for statistical distribution analysis

    ---

    ### **TYPE 6: CUMULATIVE FREQUENCY CURVES**
    Use this for cumulative distributions or percentage analysis.

    Structure:
    {{
        "charts": [
            {{
                "id": "cf1",
                "label": "Cumulative Frequency Distribution",
                "type": "cumulative",
                "visual_features": {{
                    "type": "cumulative_frequency",
                    "upper_class_boundaries": [10, 20, 30, 40, 50],
                    "cumulative_frequencies": [3, 11, 24, 35, 40],
                    "axes_range": {{
                        "x_min": 0,
                        "x_max": 55,
                        "y_min": 0,
                        "y_max": 45
                    }}
                }}
            }}
        ]
    }}

    **Key Points for Cumulative Frequency:**
    - "upper_class_boundaries": Array of class boundaries
    - "cumulative_frequencies": Running total of frequencies
    - Use for percentile analysis and quartile determination

    ---

    ### **TYPE 7: PARAMETRIC CURVES**
    Use this for parametric equations or advanced function representations.

    Structure:
    {{
        "charts": [
            {{
                "id": "p1",
                "label": "Parametric Curve",
                "type": "parametric",
                "parametric_function": {{
                    "x": "3*cos(t)",
                    "y": "2*sin(t)"
                }},
                "parameter_range": {{
                    "t_min": 0,
                    "t_max": 6.283185307179586
                }},
                "visual_features": {{
                    "type": "parametric",
                    "axes_range": {{
                        "x_min": -4,
                        "x_max": 4,
                        "y_min": -3,
                        "y_max": 3
                    }}
                }}
            }}
        ]
    }}

    
    ---

    ### **TYPE 8: TABLES**
    Use this for displaying raw data, frequency distributions, two-way tables, function values, or summary statistics.

    Structure:
    
    {{
        "charts": [
            {{
                "id": "t1",
                "type": "table",
                "label": "Frequency Distribution",
                "visual_features": {{
                    "type": "table",
                    "headers": ["Class Interval", "Frequency", "Cumulative Frequency"],
                    "rows": [
                        ["0-10", "5", "5"],
                        ["10-20", "12", "17"],
                        ["20-30", "18", "35"],
                        ["30-40", "8", "43"]
                    ],
                    "table_style": "standard|striped|minimal",
                    "position": "standalone|above_chart|below_chart|beside_chart",
                    "associated_chart_id": "h1"  
                }}
            }}
        ]
    }}

    
    ---

    ### **TYPE 9: COMPOSITE (CHART + TABLE)**
    Use this when you need to display both a chart and its underlying data table together.

    Structure:
    
    {{
        "charts": [
            {{
                "id": "h1",
                "type": "histogram",
                "label": "Score Distribution",
                "visual_features": {{
                    "type": "histogram",
                    "bins": [[0, 10], [10, 20], [20, 30], [30, 40]],
                    "frequencies": [5, 12, 18, 8],
                    "axes_range": {{"x_min": 0, "x_max": 40, "y_min": 0, "y_max": 20}}
                }}
            }},
            {{
                "id": "t1",
                "type": "table",
                "label": "Frequency Table",
                "visual_features": {{
                    "type": "table",
                    "headers": ["Score Range", "Frequency"],
                    "rows": [
                        ["0-10", "5"],
                        ["10-20", "12"],
                        ["20-30", "18"],
                        ["30-40", "8"]
                    ],
                    "table_style": "striped",
                    "position": "below_chart",
                    "associated_chart_id": "h1"
                }}
            }}
        ],
        "layout": "composite"  // Triggers multi-panel layout
    }}


    **JSON TECHNICAL RULES**:
    - **Double-escape backslashes for LaTeX commands** inside JSON strings (e.g., `\\sqrt{{...}}`, `\\frac{{...}}{{...}}`). **Do not escape the `$` characters** in math fences (`$begin:...$`, `$end:...$`).
    - Output **ONLY** the JSON object — **no** markdown code fences, headings, or commentary.
    - Keep strings single-line where possible; if you include newlines, use `\\n` in JSON.

    **FINAL CHECK**:
    - If MCQ: exactly one part, include choices + correct_choice; final_answer equals the correct option’s value/text.
    - If non-MCQ: no choices; provide a clean final_answer.
    - **If you mention any diagram/figure, the JSON must include `visual_data`; otherwise do not mention a diagram/figure at all.**
    - Ensure the JSON is valid.
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
    3) **If 'choices' are present**: ensure there is exactly one correct option; 'correct_choice' label matches the option intended; and 'final_answer' equals the correct option’s value/text (not just the label).
    4) Assign marks only if PERFECT.

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