from textwrap import dedent

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

    # --- 1. FULL VISUAL DATA GUIDE (Exact copy from prompts_presets.py, with JSON rules fixed) ---
    visual_rules_snippet = """
    **'visual_data' STRUCTURE - COMPREHENSIVE GUIDE**:

    The 'visual_data' object adapts its structure based on the chart type being visualized. Always include a 'charts' array (not 'graphs' for non-explicit-function charts). Your `visual_data` MAY contain one **or more** chart objects. If your question text refers to multiple diagrams/graphs, you MUST include multiple chart objects in the `charts` array. Choose the appropriate structure for each chart object you include.
    ---

    ### **TYPE 1: EXPLICIT MATHEMATICAL FUNCTIONS (y = f(x))**
    Use this for traditional function plots, parabolas, polynomials, trigonometric functions, etc.

    Structure:
    {
        "charts": [
            {
                "id": "g1",
                "label": "y = f(x)",
                "type": "function",
                "explicit_function": "A Python-compatible expression like 'x**2 - 4*x + 7'",
                "visual_features": {
                    "type": "parabola|cubic|polynomial|trigonometric|exponential|logarithmic|rational",
                    "x_intercepts": [1.0, 3.0] or null,
                    "y_intercept": 7 or null,
                    "turning_points": [
                        {"x": 2.0, "y": 3.0, "type": "minimum|maximum|inflection"}
                    ] or null,
                    "vertical_asymptotes": [x_value1, x_value2] or null,
                    "horizontal_asymptote": y_value or null,
                    "axes_range": {
                        "x_min": -1,
                        "x_max": 5,
                        "y_min": 0,
                        "y_max": 10
                    }
                }
            }
        ],
        "labeled_points": [
            {"label": "A", "x": 1.0, "y": 4.0}
        ], // Optional
        "shaded_regions": [
            {
                "upper_bound_id": "g1",
                "lower_bound_id": "y=0",
                "x_start": 1.0,
                "x_end": 4.0
            }
        ] // Optional
    }

    ---

    ### **TYPE 2: HISTOGRAMS**
    Use this for frequency distributions, grouped data, or continuous data analysis.

    Structure:
    {
        "charts": [
            {
                "id": "h1",
                "label": "Distribution of Heights",
                "type": "histogram",
                "visual_features": {
                    "type": "histogram",
                    "bins": [
                        [150, 160],
                        [160, 170],
                        [170, 180],
                        [180, 190]
                    ],
                    "frequencies": [5, 12, 18, 8],
                    "axes_range": {
                        "x_min": 145,
                        "x_max": 195,
                        "y_min": 0,
                        "y_max": 20
                    }
                }
            }
        ]
    }

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
    {
        "charts": [
            {
                "id": "b1",
                "label": "Sales by Region",
                "type": "bar",
                "visual_features": {
                    "type": "bar",
                    "categories": ["North", "South", "East", "West"],
                    "values": [45, 38, 52, 31],
                    "axes_range": {
                        "x_min": -0.5,
                        "x_max": 3.5,
                        "y_min": 0,
                        "y_max": 60
                    }
                }
            }
        ]
    }

    **Key Points for Bar Charts:**
    - "categories": Array of category labels (strings)
    - "values": Array of bar heights (numbers, must match category count)
    - Categories are typically on x-axis
    - Use for discrete, non-continuous data

    ---

    ### **TYPE 4: SCATTER PLOTS**
    Use this for correlation analysis, bivariate data, or point relationships.

    Structure:
    {
        "charts": [
            {
                "id": "s1",
                "label": "Age vs Income",
                "type": "scatter",
                "visual_features": {
                    "type": "scatter",
                    "data_points": [
                        {"x": 25, "y": 30000},
                        {"x": 35, "y": 55000},
                        {"x": 45, "y": 75000},
                        {"x": 55, "y": 85000}
                    ],
                    "trend_line": {
                        "enabled": true,
                        "equation": "y = 1200*x + 5000"
                    }, // Optional
                    "axes_range": {
                        "x_min": 20,
                        "x_max": 60},
                        "y_min": 20000,
                        "y_max": 90000
                    }
                }
            }
        ]
    }

    **Key Points for Scatter Plots:**
    - "data_points": Array of {x, y} coordinate pairs
    - "trend_line": Optional object with enabled flag and equation string
    - Use for bivariate relationships or correlation studies

    ---

    ### **TYPE 5: BOX PLOTS / BOX-AND-WHISKER PLOTS**
    Use this for distribution, quartiles, and outlier detection.

    Structure:
    {
        "charts": [
            {
                "id": "bp1",
                "label": "Test Score Distribution",
                "type": "box_plot",
                "visual_features": {
                    "type": "box_plot",
                    "groups": ["Group A", "Group B"],
                    "min_values": [35, 42],
                    "q1_values": [60, 58],
                    "median_values": [75, 72],
                    "q3_values": [85, 80],
                    "max_values": [98, 95],
                    "outliers": [
                        {"group": "Group A", "value": 110},
                        {"group": "Group B", "value": 105}
                    ], // Optional
                    "axes_range": {
                        "x_min": -0.5,
                        "x_max": 1.5,
                        "y_min": 30,
                        "y_max": 120
                    }
                }
            }
        ]
    }

    **Key Points for Box Plots:**
    - "min_values", "q1_values", "median_values", "q3_values", "max_values": Five-number summary
    - "outliers": Optional array of individual outlier points
    - Use for statistical distribution analysis

    ---

    ### **TYPE 6: CUMULATIVE FREQUENCY CURVES**
    Use this for cumulative distributions or percentage analysis.

    Structure:
    {
        "charts": [
            {
                "id": "cf1",
                "label": "Cumulative Frequency Distribution",
                "type": "cumulative",
                "visual_features": {
                    "type": "cumulative_frequency",
                    "upper_class_boundaries": [10, 20, 30, 40, 50],
                    "cumulative_frequencies": [3, 11, 24, 35, 40],
                    "axes_range": {
                        "x_min": 0,
                        "x_max": 55,
                        "y_min": 0,
                        "y_max": 45
                    }
                }
            }
        ]
    }

    **Key Points for Cumulative Frequency:**
    - "upper_class_boundaries": Array of class boundaries
    - "cumulative_frequencies": Running total of frequencies
    - Use for percentile analysis and quartile determination

    ---

    ### **TYPE 7: PARAMETRIC CURVES**
    Use this for parametric equations or advanced function representations.

    Structure:
    {
        "charts": [
            {
                "id": "p1",
                "label": "Parametric Curve",
                "type": "parametric",
                "parametric_function": {
                    "x": "3*cos(t)",
                    "y": "2*sin(t)"
                },
                "parameter_range": {
                    "t_min": 0,
                    "t_max": 6.283185307179586
                },
                "visual_features": {
                    "type": "parametric",
                    "axes_range": {
                        "x_min": -4,
                        "x_max": 4,
                        "y_min": -3,
                        "y_max": 3
                    }
                }
            }
        ]
    }

    ---

    ### **TYPE 8: TABLES**
    Use this for displaying raw data, frequency distributions, two-way tables, function values, or summary statistics.

    Structure:
    {
        "charts": [
            {
                "id": "t1",
                "type": "table",
                "label": "Frequency Distribution",
                "visual_features": {
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
                }
            }
        ]
    }

    ---

    ### **TYPE 9: COMPOSITE (CHART + TABLE)**
    Use this when you need to display both a chart and its underlying data table together.

    Structure:
    {
        "charts": [
            {
                "id": "h1",
                "type": "histogram",
                "label": "Score Distribution",
                "visual_features": {
                    "type": "histogram",
                    "bins": [[0, 10], [10, 20], [20, 30], [30, 40]],
                    "frequencies": [5, 12, 18, 8],
                    "axes_range": {"x_min": 0, "x_max": 40, "y_min": 0, "y_max": 20}
                }
            },
            {
                "id": "t1",
                "type": "table",
                "label": "Frequency Table",
                "visual_features": {
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
                }
            }
        ],
        "layout": "composite"  // Triggers multi-panel layout
    }

    **JSON TECHNICAL RULES**:
    - **Backslashes & math fences for LaTeX (VERY IMPORTANT)**:
      - You are writing a JSON object directly. Inside any JSON string, every backslash in a LaTeX command **must be escaped as `\\\\`** in the JSON source so that, after JSON parsing, the final string seen by the student has a **single** backslash.
      - All LaTeX commands MUST still live **inside** `$...$` or `$$...$$` in the final string. The dollar signs are written literally in JSON; only the backslashes are doubled.
      - For example, to produce the final text:
        - `Let $H = \\ell^2(\\mathbb{N})$ and $y \\in \\operatorname{Ran}(T)$.`
        your JSON must contain:
        - `"question_stem": "Let $H = \\\\ell^2(\\\\mathbb{N})$ and $y \\\\in \\\\operatorname{Ran}(T)$."`
        After JSON parsing, this becomes `Let $H = \\ell^2(\\mathbb{N})$ and $y \\in \\operatorname{Ran}(T)$.`, which MathJax renders correctly.
      - Never output bare `\\mathbb{N}`, `\\infty`, `\\rightharpoonup`, `\\|Ax_n\\|` with only a **single** backslash **in the JSON source** (for example `"x_n \\rightharpoonup 0"`). That is invalid JSON and will cause the entire response to be rejected with an `Invalid \\escape` error. In JSON, the source must be `\\\\mathbb{N}`, `\\\\infty`, `\\\\rightharpoonup`, etc., so that the parsed string has `\\mathbb{N}`, `\\infty`, `\\rightharpoonup`.
    - Do **NOT** escape the `$` characters used for math fences (`$...$`, `$$...$$`).
    - Output **ONLY** the JSON object — **no** markdown code fences, headings, or commentary.
    - If you need a line break inside a string, use the **normal JSON newline escape** (one backslash + `n` in the JSON source):
      - ✅ CORRECT JSON: `"question_stem": "Sentence one.\\nSentence two."`  (after parsing, this becomes two lines.)
      - ❌ INCORRECT JSON: `"question_stem": "Sentence one.\\\\nSentence two."`  (this produces the *visible* characters `\\n` in the final string.)
    - Never output the characters `\\n` or `\\\\n` as visible text in any field. Newlines must be represented only by JSON newline escapes that turn into real line breaks after parsing.
    """

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
    5. **No Drawing Requests**: Do not ask the student to "sketch/draw/plot." If a 2D graph is appropriate, you (the generator) provide it via `visual_data`.
    6. **Clean Answer**: Choose values that lead to a neat final result (integers, simple fractions/surds) when applicable.
    7. **No Phantom Diagrams**: If you mention a diagram/figure, you **must** supply `visual_data`. If you do not supply `visual_data`, do **not** refer to a diagram/figure/picture; provide explicit textual givens instead.
    8. **Piecewise / cases**: If you use a piecewise definition (e.g. `\\begin{{cases}} ... \\end{{cases}}`), keep each row short and clean:
       - Exactly ONE `&` per row (left side is the value, right side is the condition).
       - Do NOT put long explanations, “i.e.” clauses, or extra sentences inside `cases`. Keep the condition simple (for example: `\\text{{if }} x = p/q \\text{{ in lowest terms}}`).
       - Place any long explanation or extra wording in normal text AFTER the displayed formula, not inside the `cases` environment.
       - Avoid nested parentheses and long `\\text{{...}}` blocks inside `cases`.
    9. **No LaTeX list environments**: Do NOT use `\\begin{{itemize}}`, `\\begin{{enumerate}}`, `\\begin{{description}}`, or any similar LaTeX list environment in any field. Do NOT use `\\item`. If you need to list facts or given values, write them as plain sentences separated by newlines, or as simple text bullets like `- first fact`, `- second fact`, using normal text (not inside math mode).
    10. **No LaTeX text-formatting commands in prose**: do **not** use `\\textbf{{...}}`, `\\emph{{...}}`, `\\textit{{...}}`, or similar styling commands in the question text or explanations. If you want emphasis, rewrite the sentence in plain words without any special formatting.

    {dedent(visual_rules_snippet).strip()}
    
    --- OUTPUT FORMAT ---
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
    - The goal of `solution_text` is to make clear:
      - what the main mathematical steps are,
      - which definitions, constructions, or theorems are used,
      - and what conclusions are expected at each stage of the solution.
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