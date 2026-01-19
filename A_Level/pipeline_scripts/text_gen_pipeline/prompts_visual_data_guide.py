"""
prompts_visual_data_guide.py — Canonical visual_data specification for ALMA prompts.

This file contains ONLY:
- VISUAL_RULES_SNIPPET (the full visual_data guide block)

It intentionally does NOT contain:
- prompt-builder functions
- model calls
- other pipeline logic

Keep it “boring + stable”.
"""

from textwrap import dedent

# NOTE:
# - This is kept as a RAW string (r""") so backslashes like \\theta stay exactly as written.
# - We still pass it through dedent() when injecting it into prompts.
VISUAL_RULES_SNIPPET = r"""
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
                    "x_max": 60,
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

**Key Points for Parametric Curves:**
- Use `t` as the parameter variable (do NOT use `x`/`u`/`\\theta` as the parameter name).
- `parametric_function.x` and `parametric_function.y` must be expressions in terms of `t`.
- Expressions must be Python-compatible / evaluable (e.g., `cos(t)`, `sin(t)`, `t**2`).
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

def get_visual_rules_snippet() -> str:
    """
    Return the visual rules snippet with consistent indentation removed.
    This is a helper so callers don't forget to dedent().
    """
    return dedent(VISUAL_RULES_SNIPPET).strip()