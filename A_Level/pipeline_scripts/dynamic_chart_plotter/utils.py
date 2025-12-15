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

def evaluate_function(func_str: str, x_vals: np.ndarray) -> np.ndarray:
    """
    Safely evaluate a mathematical function string.
    """
    try:
        import re

        s = str(func_str)

        s = s.replace("^", "**")

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

        x = x_vals

        with np.errstate(all="ignore"):
            y_vals = eval(
                s,
                {"__builtins__": {}},
                {"np": np, "x": x},
            )

        if np.isscalar(y_vals):
            y_vals = np.full_like(x_vals, y_vals, dtype=float)

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
    ax.set_xlabel(config.get("x_label", "x"), fontsize=13, fontweight="bold")
    ax.set_ylabel(config.get("y_label", "y"), fontsize=13, fontweight="bold")

    if "title" in config:
        ax.set_title(config["title"], fontsize=15, fontweight="bold", pad=20)

    if config.get("grid", True):
        ax.grid(True, alpha=0.3, which=config.get("grid_style", "major"))

    axes_range = config.get("global_axes_range", config.get("axes_range"))
    if isinstance(axes_range, dict):
        ax.set_xlim(axes_range.get("x_min", -10), axes_range.get("x_max", 10))
        ax.set_ylim(axes_range.get("y_min", -10), axes_range.get("y_max", 10))

    show_nums = bool(config.get("show_axis_numbers", False))
    if not show_nums:
        ax.set_xticklabels([])
        ax.set_yticklabels([])
        ax.tick_params(length=0)
    else:
        ax.tick_params(length=4)

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

    plt.tight_layout()


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

    for i, chart in enumerate(charts):
        if not isinstance(chart, dict):
            issues.append(f"Chart {i} must be a dictionary")
            continue

        chart_id = chart.get("id", i)
        chart_type = str(chart.get("type", "function")).strip().lower()

        if chart_type == "function" and "explicit_function" not in chart:
            issues.append(f"Chart '{chart_id}' missing explicit_function")

        elif chart_type == "parametric" and "parametric_function" not in chart:
            issues.append(f"Chart '{chart_id}' missing parametric_function")

        elif chart_type == "histogram":
            vf = chart.get("visual_features", {}) or {}
            bins = vf.get("bins", [])
            freqs = vf.get("frequencies", [])
            if len(bins) != len(freqs):
                issues.append(f"Histogram '{chart_id}' bins/frequencies mismatch")
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

    return issues