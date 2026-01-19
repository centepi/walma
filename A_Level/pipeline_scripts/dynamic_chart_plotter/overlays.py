"""
overlays.py — Non-chart overlays / annotations for the chart_plotter package

This file contains ONLY:
- visual features (intercepts, turning points, asymptotes)
- labeled points
- shaded regions
- simple geometry primitives (e.g., polygons)

It intentionally does NOT contain:
- chart/table plotting implementations (function/scatter/bar/histogram/table/etc.)
- dynamic_chart_plotter()
- layout creation
- dispatcher

Those live in:
- charts.py  (chart/table renderers)
- plotter.py (controller/orchestrator/dispatcher)

General utilities live in utils.py.
"""

import matplotlib.pyplot as plt
import numpy as np
from typing import Dict, List, Any, Optional, Callable, Tuple

from matplotlib.patches import Polygon

from .utils import (
    get_color_cycle,
    get_bound_values,
)


# ============================================================================
# BASIC GEOMETRY (POLYGONS)
# ============================================================================

def plot_polygon(
    ax: plt.Axes,
    chart: Dict[str, Any],
    function_registry: Dict[str, Optional[Callable]]
) -> None:
    """
    Plot a simple filled/outlined polygon.

    Expected shape:
    {
      "id": "poly1",
      "type": "polygon",
      "label": "Triangle ABC",
      "visual_features": {
        "points": [{"x":0,"y":0},{"x":4,"y":0},{"x":1,"y":3}],
        "closed": true,              // optional (default True)
        "fill": false,               // optional (default False)
        "alpha": 0.2                 // optional (default 0.2, only used if fill=True)
      }
    }
    """
    graph_id = chart.get("id", "unknown")
    function_registry[graph_id] = None

    vf = chart.get("visual_features", {}) or {}
    pts = vf.get("points", []) or []
    if not isinstance(pts, list) or len(pts) < 3:
        print(f"⚠️ Polygon '{graph_id}' missing/invalid points (need >= 3)")
        return

    xy: List[Tuple[float, float]] = []
    for p in pts:
        try:
            xy.append((float(p["x"]), float(p["y"])))
        except Exception:
            print(f"⚠️ Polygon '{graph_id}' has invalid point {p!r}")
            return

    closed = bool(vf.get("closed", True))
    fill = bool(vf.get("fill", False))
    alpha = float(vf.get("alpha", 0.2)) if fill else 1.0

    # Label visibility matches other chart types
    show_label = bool(vf.get("show_label", False))
    safe_label = (chart.get("label", "") or "") if show_label else ""

    patch = Polygon(
        xy,
        closed=closed,
        fill=fill,
        alpha=alpha,
        edgecolor=get_color_cycle(graph_id),
        facecolor=get_color_cycle(graph_id) if fill else "none",
        linewidth=2.0,
        label=safe_label or None,
    )
    ax.add_patch(patch)


# ============================================================================
# VISUAL FEATURES (PEDAGOGY / ANNOTATIONS)
# ============================================================================

def add_visual_features(
    ax: plt.Axes,
    features: Dict[str, Any],
    x_vals: np.ndarray,
    y_vals: np.ndarray
) -> None:
    """
    Add visual features like intercepts, turning points, asymptotes, etc.
    """
    # ---- Pedagogy guardrails (avoid giving away answers) ----
    reveal_intercepts = bool(features.get('reveal_intercepts', False))
    reveal_turning_points = bool(features.get('reveal_turning_points', False))
    reveal_asymptotes = bool(features.get('reveal_asymptotes', False))
    reveal_coordinates = bool(features.get('reveal_coordinates', False))

    # Mark x-intercepts
    if reveal_intercepts and features.get('x_intercepts') is not None:
        x_intercepts = features['x_intercepts']
        if isinstance(x_intercepts, (list, tuple)):
            for x_int in x_intercepts:
                ax.plot(x_int, 0, 'ro', markersize=8, zorder=5)
                ax.axvline(x=x_int, color='red', linestyle='--', alpha=0.5, linewidth=1)

    # Mark y-intercept
    if reveal_intercepts and features.get('y_intercept') is not None:
        y_int = features['y_intercept']
        ax.plot(0, y_int, 'go', markersize=8, zorder=5)
        ax.axhline(y=y_int, color='green', linestyle='--', alpha=0.5, linewidth=1)

    # Mark turning points (critical points, extrema)
    if reveal_turning_points and features.get('turning_points'):
        for tp in features['turning_points']:
            x_tp, y_tp = tp['x'], tp['y']
            ax.plot(x_tp, y_tp, 'bs', markersize=10, zorder=5)
            if reveal_coordinates:
                ax.annotate(
                    f'({x_tp:.1f}, {y_tp:.1f})',
                    xy=(x_tp, y_tp),
                    xytext=(10, 10),
                    textcoords='offset points',
                    fontsize=9,
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.3),
                    arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0')
                )

    # Mark asymptotes
    if reveal_asymptotes and features.get('vertical_asymptotes'):
        for va in features['vertical_asymptotes']:
            ax.axvline(x=va, color='purple', linestyle=':', alpha=0.7, linewidth=1.5)

    if reveal_asymptotes and features.get('horizontal_asymptote') is not None:
        ha = features['horizontal_asymptote']
        ax.axhline(y=ha, color='purple', linestyle=':', alpha=0.7, linewidth=1.5)


def plot_labeled_point(ax: plt.Axes, point: Dict[str, Any]) -> None:
    """
    Plot a labeled point with annotation.

    Pedagogy:
    - By default, labeled points are hidden.
    - If you want the point visible, set point["reveal"] = True.
    - If the point is visible, the label is shown (because otherwise there is no purpose).
    """
    if not bool(point.get('reveal', False)):
        return

    x, y = point['x'], point['y']
    label = point.get('label', '')
    color = point.get('color', 'black')
    marker_size = point.get('marker_size', 8)

    ax.plot(x, y, 'o', color=color, markersize=marker_size, zorder=5)

    # Always show label if the point is revealed
    offset = point.get('offset', (12, 12))
    if label:
        ax.annotate(
            label,
            xy=(x, y),
            xytext=offset,
            textcoords='offset points',
            fontsize=11,
            fontweight='bold',
            bbox=dict(
                boxstyle='round,pad=0.4',
                facecolor='white',
                edgecolor='black',
                alpha=0.8
            ),
            arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0.3')
        )


def plot_shaded_region(
    ax: plt.Axes,
    region: Dict[str, Any],
    function_registry: Dict[str, Optional[Callable]]
) -> None:
    """
    Plot a shaded region between two curves or between a curve and a constant.
    """
    upper_bound_id = region['upper_bound_id']
    lower_bound_id = region['lower_bound_id']
    x_start = region['x_start']
    x_end = region['x_end']
    color = region.get('color', 'lightblue')
    alpha = region.get('alpha', 0.3)
    label = region.get('label', None)

    x_region = np.linspace(x_start, x_end, 300)

    y_upper = get_bound_values(upper_bound_id, x_region, function_registry)
    y_lower = get_bound_values(lower_bound_id, x_region, function_registry)

    ax.fill_between(x_region, y_lower, y_upper, alpha=alpha, color=color, label=label)