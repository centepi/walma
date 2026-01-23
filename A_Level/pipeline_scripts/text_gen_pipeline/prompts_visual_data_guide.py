"""
prompts_visual_data_guide.py — Canonical visual_data specification for ALMA prompts.

This file contains ONLY:
- VISUAL_RULES_SNIPPET (the full visual_data guide block)
- small helpers to retrieve the relevant snippet(s)

It intentionally does NOT contain:
- prompt-builder functions
- model calls
- other pipeline logic

Keep it “boring + stable”.
"""

from textwrap import dedent
from typing import Iterable, Optional, Set

# NOTE:
# - These are kept as RAW strings (r""") so backslashes like \\theta stay exactly as written.
# - We still pass them through dedent() when injecting them into prompts.
#
# IMPORTANT GOAL (per your request):
# - The model should NOT have to read every chart type every time.
# - We keep a short CORE snippet + per-type snippets.
# - Callers (e.g., drill_prompts.py) choose ONE type and inject only that.
#
# Backwards compatibility:
# - VISUAL_RULES_SNIPPET remains as the "full" block (CORE + ALL types).
# - New helper lets you request CORE + only specific types.


# ============================================================================
# CORE (ALWAYS INCLUDED WHEN REQUESTING SNIPPETS)
# ============================================================================

_VISUAL_RULES_CORE = r"""
**'visual_data' STRUCTURE - COMPREHENSIVE GUIDE**:

The `visual_data` object adapts its structure based on the chart type being visualized.

**IMPORTANT**:
- Always include a `"charts"` array at the top-level of `visual_data`.
- Do NOT use `"graphs"` in new content (legacy only). Use `"charts"`.

**MULTI-DIAGRAM RULE**:
Your `visual_data` MAY contain one **or more** chart objects.
If your question text refers to multiple diagrams/graphs, you MUST include multiple chart objects in the `charts` array.

---

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

# ============================================================================
# TYPE SNIPPETS (CALLER SHOULD SELECT ONE MOST OF THE TIME)
# ============================================================================

_VISUAL_RULES_TYPE_FUNCTION = r"""
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
                },

                "hide_values": false,                // optional; if true, axis numbers are hidden
                "show_label": false                  // optional; if true, legend label may appear
            }
        }
    ],
    "labeled_points": [
        {"label": "A", "x": 1.0, "y": 4.0, "reveal": false}
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
"""

_VISUAL_RULES_TYPE_HISTOGRAM = r"""
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
                },

                "hide_values": false
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
"""

_VISUAL_RULES_TYPE_BAR = r"""
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
                },

                "hide_values": false
            }
        }
    ]
}

**Key Points for Bar Charts:**
- "categories": Array of category labels (strings)
- "values": Array of bar heights (numbers, must match category count)
- Categories are typically on x-axis
- Use for discrete, non-continuous data
"""

_VISUAL_RULES_TYPE_SCATTER = r"""
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
                },

                "hide_values": false
            }
        }
    ]
}

**Key Points for Scatter Plots:**
- "data_points": Array of {x, y} coordinate pairs
- "trend_line": Optional object with enabled flag and equation string
- Use for bivariate relationships or correlation studies
"""

_VISUAL_RULES_TYPE_BOX = r"""
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
                },

                "hide_values": false
            }
        }
    ]
}

**Key Points for Box Plots:**
- "min_values", "q1_values", "median_values", "q3_values", "max_values": Five-number summary
- "outliers": Optional array of individual outlier points
- Use for statistical distribution analysis
"""

_VISUAL_RULES_TYPE_CUMULATIVE = r"""
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
                },

                "hide_values": false
            }
        }
    ]
}

**Key Points for Cumulative Frequency:**
- "upper_class_boundaries": Array of class boundaries
- "cumulative_frequencies": Running total of frequencies
- Use for percentile analysis and quartile determination
"""

_VISUAL_RULES_TYPE_PARAMETRIC = r"""
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
                },

                "hide_values": false,
                "show_label": false
            }
        }
    ]
}

**Key Points for Parametric Curves:**
- Use `t` as the parameter variable (do NOT use `x`/`u`/`\\theta` as the parameter name).
- `parametric_function.x` and `parametric_function.y` must be expressions in terms of `t`.
- Expressions must be Python-compatible / evaluable (e.g., `cos(t)`, `sin(t)`, `t**2`).
"""

_VISUAL_RULES_TYPE_TABLE = r"""
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
"""

_VISUAL_RULES_TYPE_COMPOSITE = r"""
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
"""

# NOTE: We are adding a "geometry" type entry so the prompt can request polygons/circles/lines
# (This is the piece that will stop the model from only emitting "function" charts for Euclidean geometry.)
_VISUAL_RULES_TYPE_GEOMETRY = r"""
### **TYPE: GEOMETRY / EUCLIDEAN DIAGRAMS (SEGMENTS, CIRCLES, ARCS, SECTORS)**
Use this when the diagram is a geometric construction (triangles, circles, chords, tangents, angle-chasing, arcs, sectors, etc.).
Prefer this over "function" unless you truly need a coordinate graph.

Top-level structure:
{
  "charts": [
    {
      "id": "geo1",
      "type": "geometry",
      "label": "Diagram",
      "visual_features": {
        "axes_range": {"x_min": -1, "x_max": 11, "y_min": -1, "y_max": 8},
        "equal_aspect": true,
        "hide_values": true
      },
      "objects": [ ... ]
    }
  ]
}

**CRITICAL DIAGRAM QUALITY RULES (READ THIS)**:
- Your `axes_range` MUST include ALL diagram content: arcs, sector boundaries, labels, and any text like angle measures.
  - Do NOT set axes_range tightly around only the points. Always add margin.
  - If you draw any circle/arc/sector of radius R centered at (cx,cy), your axes_range must extend beyond [cx-R, cx+R] and [cy-R, cy+R] with extra space for labels.
- Angle/arc labels must be placed sensibly:
  - They MUST NOT overlap the main diagram lines/graphs.
  - They MUST NOT be extremely far away from the arc/angle they describe.
  - Use small, consistent offsets (typically 6–14 "offset points" for point labels).
  - For angle measures near an arc (e.g., "$60^\\circ$"), prefer a `text` object positioned near the mid-angle on the arc (see below).

**SUPPORTED GEOMETRY OBJECT TYPES** (inside `objects`):
- point
- segment
- ray
- circle
- semicircle
- arc
- polygon
- angle_marker
- sector
- annular_sector
- label
- text

---

## 1) POINTS (required for anything referenced)
{"type":"point","id":"A","x":1,"y":1,"reveal":true}

RULES:
- Every point referenced anywhere by id (A,B,C,O,T,P,...) MUST appear as a point object with that exact `id`.
- If the question text mentions named points, you MUST include visible labels for them (label objects with reveal:true).

---

## 2) SEGMENTS / RAYS
{"type":"segment","from":"A","to":"B"}

{"type":"ray","from":"A","to":"B","length":100}  // length optional

Optional styling:
- "linewidth": number (default 2)
- "line_style": "solid|dashed|dotted|dashdot"
- "color": string

---

## 3) CIRCLES
{"type":"circle","center":"O","radius":3.5,"fill":false,"alpha":0.10}

RULES:
- center MUST be an existing point id.
- radius MUST be a positive number.

---

## 4) SEMICIRCLES (diameter endpoints)
{"type":"semicircle","diameter":["A","B"],"side":"left"}

RULES:
- "diameter" is [A,B] where A and B are existing point ids.
- "side" chooses which half to draw: "left" (default) or "right".

---

## 5) ARCS
Schema A (explicit angles):
{"type":"arc","center":"O","radius":4,"theta1_deg":20,"theta2_deg":110}

Schema B (endpoints by point ids; angles inferred):
{"type":"arc","center":"O","radius":4,"from":"A","to":"B"}

RULES:
- center MUST be an existing point id.
- radius MUST be a positive number.
- Use EITHER (theta1_deg/theta2_deg) OR (from/to). Do NOT invent other fields.

---

## 6) ANGLE MARKERS
{"type":"angle_marker","at":"B","corner_points":["A","B","C"],"radius":0.6}

RULES:
- corner_points must be [p1, vertex, p2] and vertex must equal `at`.
- All point ids must exist.

---

## 7) SECTORS / ANNULAR SECTORS
Sector:
{"type":"sector","center":"O","radius":6,"theta1_deg":20,"theta2_deg":110,"fill":false,"alpha":0.15}

Annular sector:
{"type":"annular_sector","center":"O","r_inner":4,"r_outer":7,"theta1_deg":20,"theta2_deg":110,"fill":false,"alpha":0.15}

Alternative endpoint form (angles inferred):
{"type":"sector","center":"O","radius":6,"from":"A","to":"B"}

RULES:
- Use EITHER (theta1_deg/theta2_deg) OR (from/to).
- For annular_sector you MUST provide r_inner and r_outer with r_outer > r_inner > 0.
- If you mention a sector/annular sector in the question text, you MUST include the object.

---

## 8) POLYGONS
{"type":"polygon","points":["A","B","C"],"closed":true,"fill":false,"alpha":0.15}

---

## 9) LABELS / TEXT (PLACEMENT MATTERS)
Label a named point:
{"type":"label","target":"A","text":"A","offset":[10,10],"reveal":true}

RULES FOR POINT LABELS (label objects):
- Use `offset` as "offset points" relative to the point.
- Keep offsets small and consistent: usually [6,6], [8,8], [10,10], or [12,8].
- Do NOT use huge offsets (like 40+) unless absolutely necessary.
- Ensure the label does not overlap a segment/arc passing through the point:
  - Example: if the point lies on a line going up-right, offset to up-left instead.

Angle/arc measure label (e.g., "$60^\\circ$") — use a `text` object placed near the arc, NOT on top of lines:
{"type":"text","x":4.2,"y":3.8,"text":"$60^\\circ$","fontsize":12}

RULES FOR ANGLE/ARC MEASURE TEXT (text objects):
- Place it near the arc/angle it describes (close, but not touching the curve).
- Avoid overlap with the arc itself and with other diagram lines.
- Do NOT place it far away from the angle (it should clearly refer to the nearby arc).
- IMPORTANT: keep the text position inside the axes_range with margin.

Free text at coordinates (general):
{"type":"text","x":2.5,"y":4.0,"text":"$\\angle ABC$","fontsize":12}

---

**Key Defaults for Euclidean Geometry**
- Set "equal_aspect": true to avoid stretched circles.
- Prefer "hide_values": true so axis numbers do not appear.
- Do NOT ask the student to draw; the diagram must be sufficient to solve the question.
"""

# Map of normalized type names -> snippets
_TYPE_TO_SNIPPET = {
    "function": _VISUAL_RULES_TYPE_FUNCTION,
    "histogram": _VISUAL_RULES_TYPE_HISTOGRAM,
    "bar": _VISUAL_RULES_TYPE_BAR,
    "scatter": _VISUAL_RULES_TYPE_SCATTER,
    "box_plot": _VISUAL_RULES_TYPE_BOX,
    "cumulative": _VISUAL_RULES_TYPE_CUMULATIVE,
    "parametric": _VISUAL_RULES_TYPE_PARAMETRIC,
    "table": _VISUAL_RULES_TYPE_TABLE,
    "composite": _VISUAL_RULES_TYPE_COMPOSITE,
    "geometry": _VISUAL_RULES_TYPE_GEOMETRY,
}


def _normalize_types(types: Optional[Iterable[str]]) -> Set[str]:
    out: Set[str] = set()
    if not types:
        return out
    for t in types:
        s = str(t or "").strip().lower()
        if s:
            out.add(s)
    return out


def get_visual_rules_snippet(
    *,
    only_types: Optional[Iterable[str]] = None,
    include_core: bool = True,
) -> str:
    """
    Return a visual rules snippet.

    Usage:
    - Default (only_types=None): returns the FULL guide (CORE + all types).
    - only_types=["geometry"]: returns CORE + geometry block only.
    - only_types=["histogram","table"]: returns CORE + those blocks.

    This helper is intentionally small and "boring".
    """
    wanted = _normalize_types(only_types)

    chunks = []
    if include_core:
        chunks.append(_VISUAL_RULES_CORE.strip())

    if not wanted:
        # Full guide
        for _, snippet in _TYPE_TO_SNIPPET.items():
            chunks.append(snippet.strip())
    else:
        # Specific types only
        for t in wanted:
            snippet = _TYPE_TO_SNIPPET.get(t)
            if snippet:
                chunks.append(snippet.strip())

    return dedent("\n\n---\n\n".join(chunks)).strip()


# Backwards compatibility: keep the old name that means "everything".
VISUAL_RULES_SNIPPET = get_visual_rules_snippet()