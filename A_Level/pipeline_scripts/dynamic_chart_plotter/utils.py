"""
utils.py — Shared helpers for the chart_plotter package

This file contains small, reusable utilities used by both:
- plotter.py (orchestrator / layout / dispatcher / appearance)
- charts.py  (actual plotting implementations)

It intentionally does NOT contain:
- dynamic_chart_plotter()
- create_composite_layout()
- plot_chart() dispatcher
- any chart plotting (function/scatter/bar/table/etc.)

Keep it “boring + stable”.
"""

import json
import warnings
from typing import Dict, List, Any, Optional, Callable, Tuple

import numpy as np
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")


# ============================================================================
# COLOR
# ============================================================================

def get_color_cycle(graph_id: str) -> str:
    """
    Get a color from matplotlib's color cycle based on graph ID.
    Deterministic per process run (Python's hash randomization can vary between runs).
    """
    colors = [
        "tab:blue",
        "tab:orange",
        "tab:green",
        "tab:red",
        "tab:purple",
        "tab:brown",
        "tab:pink",
        "tab:gray",
    ]
    return colors[hash(graph_id) % len(colors)]


# ============================================================================
# SAFE-ish EXPRESSION EVAL
# ============================================================================

def evaluate_function(func_str: str, x_vals: np.ndarray, var_name: str = "x") -> np.ndarray:
    """
    Safely evaluate a mathematical function string.

    Notes:
    - Default variable is 'x' for explicit functions.
    - For parametric curves, call with var_name='t' so expressions like 'sin(t)' work.
    """
    try:
        import re

        s = str(func_str)
        s = s.replace("^", "**")

        # Variable binding (default: x; parametric: t)
        v = x_vals
        var_name = str(var_name or "x").strip() or "x"

        # Insert implicit multiplication (common A-level notation):
        # 2x -> 2*x, 1.0x -> 1.0*x, 2(x+1) -> 2*(x+1), x(x+1) -> x*(x+1)
        #
        # IMPORTANT: do NOT break function calls like cos(t), sin(t).
        s = re.sub(r"(\d+(?:\.\d+)?)\s*([a-zA-Z])", r"\1*\2", s)  # number then variable
        s = re.sub(r"(\d+(?:\.\d+)?)\s*\(", r"\1*(", s)          # number then (
        s = re.sub(rf"\b{re.escape(var_name)}\s*\(", f"{var_name}*(", s)  # ONLY actual variable then (
        s = re.sub(r"\)\s*([a-zA-Z])", r")*\1", s)              # )x -> )*x
        s = re.sub(r"\)\s*\(", r")*(", s)                       # )( -> )*(

        fn_map = [
            ("arcsin", "np.arcsin"),
            ("arccos", "np.arccos"),
            ("arctan", "np.arctan"),
            ("sinh", "np.sinh"),
            ("cosh", "np.cosh"),
            ("tanh", "np.tanh"),
            ("sin", "np.sin"),
            ("cos", "np.cos"),
            ("tan", "np.tan"),
            ("exp", "np.exp"),
            ("log10", "np.log10"),
            ("log", "np.log"),
            ("sqrt", "np.sqrt"),
            ("abs", "np.abs"),
        ]
        for name, repl in fn_map:
            s = re.sub(rf"\b{name}\b", repl, s)

        s = re.sub(r"\bpi\b", "np.pi", s)

        with np.errstate(all="ignore"):
            y_vals = eval(
                s,
                {"__builtins__": {}},
                {"np": np, var_name: v},
            )

        if np.isscalar(y_vals):
            y_vals = np.full_like(v, y_vals, dtype=float)

        return np.asarray(y_vals, dtype=float)

    except Exception as e:
        print(f"⚠️ Error evaluating function '{func_str}': {e}")
        return np.zeros_like(x_vals)


# ============================================================================
# BINS / HISTOGRAM HELPERS
# ============================================================================

def _coerce_bin_pair(b: Any) -> Optional[Tuple[float, float]]:
    """
    Accept bins in many formats, including Firestore-safe strings.
    """
    if isinstance(b, (list, tuple)) and len(b) == 2:
        try:
            return float(b[0]), float(b[1])
        except Exception:
            return None

    if isinstance(b, str):
        s = b.strip()

        try:
            parsed = json.loads(s)
            if isinstance(parsed, (list, tuple)) and len(parsed) == 2:
                return float(parsed[0]), float(parsed[1])
        except Exception:
            pass

        try:
            import re
            nums = re.findall(r"[-+]?\d*\.?\d+", s)
            if len(nums) >= 2:
                return float(nums[0]), float(nums[1])
        except Exception:
            pass

    return None


# ============================================================================
# SHADED REGION HELPERS
# ============================================================================

def get_bound_values(
    bound_id: str,
    x_vals: np.ndarray,
    function_registry: Dict[str, Optional[Callable]],
) -> np.ndarray:
    """
    Resolve a shaded-region bound.
    """
    if bound_id in function_registry:
        func = function_registry[bound_id]
        if func is not None:
            return func(x_vals)
        return np.zeros_like(x_vals)

    if isinstance(bound_id, str) and bound_id.startswith("y="):
        try:
            val = float(bound_id.split("=", 1)[1])
            return np.full_like(x_vals, val)
        except Exception:
            print(f"⚠️ Could not parse constant bound: {bound_id}")
            return np.zeros_like(x_vals)

    print(f"⚠️ Bound '{bound_id}' not found in function registry")
    return np.zeros_like(x_vals)


# ============================================================================
# TABLE HELPERS
# ============================================================================

def get_table_colors(
    num_rows: int,
    num_cols: int,
    style: str,
    has_header: bool = False,
) -> List[List[str]]:
    colors: List[List[str]] = []
    for i in range(num_rows):
        if i == 0 and has_header:
            row_color = ["#4472C4"] * num_cols
        elif style == "striped":
            base_idx = i - (1 if has_header else 0)
            row_color = ["#E7E6E6"] * num_cols if base_idx % 2 == 0 else ["white"] * num_cols
        elif style == "minimal":
            row_color = ["white"] * num_cols
        else:
            row_color = ["#F2F2F2"] * num_cols
        colors.append(row_color)
    return colors


def latex_to_unicode(text: str) -> str:
    latex_map = {
        r"\le": "≤",
        r"\leq": "≤",
        r"\ge": "≥",
        r"\geq": "≥",
        r"\ne": "≠",
        r"\times": "×",
        r"\div": "÷",
        r"\pm": "±",
    }

    s = str(text).replace("$", "")
    for k, v in latex_map.items():
        s = s.replace(k, v)
    return s


def clean_table_text(text: str) -> str:
    s = str(text)
    s = s.replace("\\\\", "\\")
    s = latex_to_unicode(s)
    return s.strip()


# ============================================================================
# PLOT APPEARANCE
# ============================================================================

def setup_plot_appearance(ax: plt.Axes, config: Dict[str, Any]) -> None:
    """
    Apply axis-level styling only.

    IMPORTANT:
    - Do NOT call plt.tight_layout() here.
    - tight_layout/constrained_layout are figure-level policies and can
      clip titles/labels in composite (chart+table) figures.
    - Layout should be applied once in plotter.py after all subplots are drawn.
    """
    hide_axis_labels = bool(config.get("hide_axis_labels", False))
    if not hide_axis_labels:
        ax.set_xlabel(config.get("x_label", "x"), fontsize=13, fontweight="bold")
        ax.set_ylabel(config.get("y_label", "y"), fontsize=13, fontweight="bold")
    else:
        ax.set_xlabel("")
        ax.set_ylabel("")

    if "title" in config:
        ax.set_title(config["title"], fontsize=15, fontweight="bold", pad=20)

    axes_range = config.get("global_axes_range", config.get("axes_range"))
    if isinstance(axes_range, dict):
        ax.set_xlim(axes_range.get("x_min", -10), axes_range.get("x_max", 10))
        ax.set_ylim(axes_range.get("y_min", -10), axes_range.get("y_max", 10))

    show_nums = bool(config.get("show_axis_numbers", False))
    if not show_nums:
        # Hide values: remove tick labels + tick marks, but KEEP the x/y axis lines.
        ax.set_xticklabels([])
        ax.set_yticklabels([])
        ax.tick_params(length=0)

        # Default: no grid in hide-values mode unless explicitly requested.
        if "grid" not in config:
            ax.grid(False)
        else:
            if config.get("grid", True):
                ax.grid(True, alpha=0.3, which=config.get("grid_style", "major"))
            else:
                ax.grid(False)

        # Keep only the actual axes (left/bottom). Hide the frame (top/right).
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_visible(True)
        ax.spines["bottom"].set_visible(True)
    else:
        ax.tick_params(length=4)
        if config.get("grid", True):
            ax.grid(True, alpha=0.3, which=config.get("grid_style", "major"))

    handles, labels = ax.get_legend_handles_labels()
    pairs = [(h, l) for h, l in zip(handles, labels) if str(l).strip()]
    if pairs:
        h2, l2 = zip(*pairs)
        ax.legend(h2, l2, loc=config.get("legend_location", "best"), fontsize=11)

    if config.get("equal_aspect"):
        ax.set_aspect("equal", adjustable="box")

    if config.get("axes_through_origin"):
        ax.axhline(0, color="k", alpha=0.3, linewidth=0.8)
        ax.axvline(0, color="k", alpha=0.3, linewidth=0.8)

# ============================================================================
# VALIDATION
# ============================================================================

def validate_config(config: Dict[str, Any]) -> List[str]:
    """
    Validate configuration and return a list of issues.
    """
    issues: List[str] = []

    if not isinstance(config, dict):
        return ["Configuration must be a dictionary"]

    charts = config.get("charts", config.get("graphs", []))

    if not isinstance(charts, list) or not charts:
        issues.append("No charts found in configuration")
        return issues

    def _is_num(x: Any) -> bool:
        try:
            float(x)
            return True
        except Exception:
            return False

    def _get_points_index(objs: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        idx: Dict[str, Dict[str, Any]] = {}
        for o in objs:
            if not isinstance(o, dict):
                continue
            if str(o.get("type", "")).strip().lower() != "point":
                continue
            pid = str(o.get("id", "")).strip()
            if not pid:
                continue
            idx[pid] = o
        return idx

    for i, chart in enumerate(charts):
        if not isinstance(chart, dict):
            issues.append(f"Chart {i} must be a dictionary")
            continue

        chart_id = chart.get("id", i)
        chart_type = str(chart.get("type", "function")).strip().lower()

        if chart_type == "function" and "explicit_function" not in chart:
            issues.append(f"Chart '{chart_id}' missing explicit_function")

        elif chart_type == "parametric":
            pf = chart.get("parametric_function")
            pr = chart.get("parameter_range")

            if not isinstance(pf, dict):
                issues.append(f"Chart '{chart_id}' missing parametric_function")
            else:
                if not str(pf.get("x", "")).strip():
                    issues.append(f"Parametric chart '{chart_id}' missing parametric_function.x")
                if not str(pf.get("y", "")).strip():
                    issues.append(f"Parametric chart '{chart_id}' missing parametric_function.y")

            if not isinstance(pr, dict):
                issues.append(f"Parametric chart '{chart_id}' missing parameter_range")
            else:
                if pr.get("t_min", None) is None:
                    issues.append(f"Parametric chart '{chart_id}' missing parameter_range.t_min")
                if pr.get("t_max", None) is None:
                    issues.append(f"Parametric chart '{chart_id}' missing parameter_range.t_max")

        elif chart_type == "histogram":
            vf = chart.get("visual_features", {}) or {}
            bins = vf.get("bins", [])
            freqs = vf.get("frequencies", [])

            if len(bins) != len(freqs):
                issues.append(f"Histogram '{chart_id}' bins/frequencies mismatch")

            heights = vf.get("heights")
            if heights is None:
                issues.append(
                    f"Histogram '{chart_id}' missing heights; will be inferred from frequencies/bin widths."
                )
            elif isinstance(heights, list) and len(heights) != len(bins):
                issues.append(f"Histogram '{chart_id}' bins/heights mismatch")

            for b in bins:
                if _coerce_bin_pair(b) is None:
                    issues.append(f"Histogram '{chart_id}' has invalid bin {b!r}")

        elif chart_type == "table":
            vf = chart.get("visual_features", {}) or {}
            rows = vf.get("rows", [])
            headers = vf.get("headers", [])
            if rows:
                expected = len(headers) if headers else len(rows[0])
                for r_i, row in enumerate(rows):
                    if len(row) != expected:
                        issues.append(
                            f"Table '{chart_id}' row {r_i} has incorrect column count"
                        )

        # --------------------------------------------------------------------
        # NEW: GEOMETRY (ALMA) VALIDATION
        # --------------------------------------------------------------------
        elif chart_type == "geometry":
            objs = chart.get("objects")
            if not isinstance(objs, list) or not objs:
                issues.append(f"Geometry chart '{chart_id}' missing/invalid objects list")
                continue

            pts = _get_points_index([o for o in objs if isinstance(o, dict)])
            has_any_point = bool(pts)

            # Validate points are numeric
            for pid, o in pts.items():
                if not _is_num(o.get("x")) or not _is_num(o.get("y")):
                    issues.append(f"Geometry chart '{chart_id}' point '{pid}' has non-numeric x/y")

            # Track labels
            label_count = 0
            referenced_points: List[str] = []

            for j, o in enumerate(objs):
                if not isinstance(o, dict):
                    issues.append(f"Geometry chart '{chart_id}' object {j} must be a dictionary")
                    continue

                ot = str(o.get("type", "")).strip().lower()
                if not ot:
                    issues.append(f"Geometry chart '{chart_id}' object {j} missing type")
                    continue

                if ot == "label":
                    label_count += 1
                    tgt = o.get("target")
                    txt = str(o.get("text", "") or "").strip()
                    if not isinstance(tgt, str) or not tgt.strip():
                        issues.append(f"Geometry chart '{chart_id}' label object {j} missing target")
                    else:
                        referenced_points.append(tgt)
                        if tgt not in pts:
                            issues.append(f"Geometry chart '{chart_id}' label targets unknown point '{tgt}'")
                    if not txt:
                        issues.append(f"Geometry chart '{chart_id}' label for '{tgt}' missing text")

                elif ot in {"segment", "ray"}:
                    a = o.get("from") or o.get("start")
                    b = o.get("to") or o.get("through") or o.get("end")
                    if not isinstance(a, str) or not isinstance(b, str):
                        issues.append(f"Geometry chart '{chart_id}' {ot} object {j} missing from/to")
                    else:
                        referenced_points.extend([a, b])
                        if a not in pts:
                            issues.append(f"Geometry chart '{chart_id}' {ot} references unknown point '{a}'")
                        if b not in pts:
                            issues.append(f"Geometry chart '{chart_id}' {ot} references unknown point '{b}'")

                elif ot == "circle":
                    c = o.get("center")
                    r = o.get("radius")
                    if not isinstance(c, str) or not c.strip():
                        issues.append(f"Geometry chart '{chart_id}' circle object {j} missing center")
                    else:
                        referenced_points.append(c)
                        if c not in pts:
                            issues.append(f"Geometry chart '{chart_id}' circle references unknown center '{c}'")
                    if not _is_num(r) or float(r) <= 0:
                        issues.append(f"Geometry chart '{chart_id}' circle object {j} has invalid radius")

                elif ot == "arc":
                    c = o.get("center")
                    r = o.get("radius")
                    th1 = o.get("theta1_deg")
                    th2 = o.get("theta2_deg")
                    if not isinstance(c, str) or not c.strip():
                        issues.append(f"Geometry chart '{chart_id}' arc object {j} missing center")
                    else:
                        referenced_points.append(c)
                        if c not in pts:
                            issues.append(f"Geometry chart '{chart_id}' arc references unknown center '{c}'")
                    if not _is_num(r) or float(r) <= 0:
                        issues.append(f"Geometry chart '{chart_id}' arc object {j} has invalid radius")
                    if not _is_num(th1) or not _is_num(th2):
                        issues.append(f"Geometry chart '{chart_id}' arc object {j} missing/invalid theta1/theta2")

                # ✅ NEW: semicircle support validation (renderer lives in geometry.py)
                elif ot == "semicircle":
                    # Accept either:
                    #  A) center + radius + orientation
                    #  B) diameter endpoints (from/to) + side
                    center = o.get("center")
                    radius = o.get("radius")
                    a = o.get("from") or o.get("a")
                    b = o.get("to") or o.get("b")

                    if isinstance(center, str) and center.strip():
                        referenced_points.append(center)
                        if center not in pts:
                            issues.append(f"Geometry chart '{chart_id}' semicircle references unknown center '{center}'")
                        if not _is_num(radius) or float(radius) <= 0:
                            issues.append(f"Geometry chart '{chart_id}' semicircle object {j} has invalid radius")
                    elif isinstance(a, str) and isinstance(b, str):
                        referenced_points.extend([a, b])
                        if a not in pts:
                            issues.append(f"Geometry chart '{chart_id}' semicircle references unknown point '{a}'")
                        if b not in pts:
                            issues.append(f"Geometry chart '{chart_id}' semicircle references unknown point '{b}'")
                    else:
                        issues.append(
                            f"Geometry chart '{chart_id}' semicircle object {j} must provide "
                            f"either center+radius or from/to diameter endpoints"
                        )

                elif ot == "polygon":
                    pids = o.get("points")
                    if not isinstance(pids, list) or len(pids) < 3:
                        issues.append(f"Geometry chart '{chart_id}' polygon object {j} missing/invalid points")
                    else:
                        for pid in pids:
                            if not isinstance(pid, str) or not pid.strip():
                                issues.append(f"Geometry chart '{chart_id}' polygon object {j} has non-string point id")
                                continue
                            referenced_points.append(pid)
                            if pid not in pts:
                                issues.append(f"Geometry chart '{chart_id}' polygon references unknown point '{pid}'")

                elif ot == "angle_marker":
                    at_id = o.get("at")
                    cps = o.get("corner_points")
                    if not isinstance(at_id, str) or not at_id.strip():
                        issues.append(f"Geometry chart '{chart_id}' angle_marker object {j} missing at")
                    else:
                        referenced_points.append(at_id)
                        if at_id not in pts:
                            issues.append(f"Geometry chart '{chart_id}' angle_marker references unknown point '{at_id}'")

                    if not isinstance(cps, list) or len(cps) != 3:
                        issues.append(f"Geometry chart '{chart_id}' angle_marker object {j} missing/invalid corner_points")
                    else:
                        for pid in cps:
                            if not isinstance(pid, str) or not pid.strip():
                                issues.append(
                                    f"Geometry chart '{chart_id}' angle_marker object {j} has non-string corner point id"
                                )
                                continue
                            referenced_points.append(pid)
                            if pid not in pts:
                                issues.append(f"Geometry chart '{chart_id}' angle_marker references unknown point '{pid}'")

                    r = o.get("radius", 0.6)
                    if not _is_num(r) or float(r) <= 0:
                        issues.append(f"Geometry chart '{chart_id}' angle_marker object {j} has invalid radius")

                elif ot == "text":
                    # free text can be in axes coords; just require x/y numeric when provided
                    if o.get("x") is None or o.get("y") is None:
                        issues.append(f"Geometry chart '{chart_id}' text object {j} missing x/y")
                    else:
                        if not _is_num(o.get("x")) or not _is_num(o.get("y")):
                            issues.append(f"Geometry chart '{chart_id}' text object {j} has non-numeric x/y")
                    if not str(o.get("text", "") or "").strip():
                        issues.append(f"Geometry chart '{chart_id}' text object {j} missing text")

                elif ot == "point":
                    # already validated in pts pass
                    pass

                else:
                    # Unknown geometry object type (won't render)
                    issues.append(f"Geometry chart '{chart_id}' unsupported object type '{ot}'")

            # ✅ Pedagogy / usability guard:
            # If you provided points and referenced them (or have named points), require at least one label.
            # This prevents the “no labels” screenshot case from silently passing.
            if has_any_point and label_count == 0:
                issues.append(f"Geometry chart '{chart_id}' has points but no label objects (labels required)")

    return issues