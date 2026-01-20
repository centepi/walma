"""
geometry.py — Geometry diagram primitives for dynamic_chart_plotter

This file contains ONLY:
- geometry plotting primitives (circle/segment/ray/arc/angle markers/polygons)
- geometry bounds helpers (so diagrams stay in-frame)

It intentionally does NOT contain:
- dynamic_chart_plotter() orchestrator
- chart/table plotting implementations (histogram/scatter/bar/function/etc.)
- layout creation / dispatcher

Those live in:
- charts.py   (chart/table renderers)
- plotter.py  (controller/orchestrator/dispatcher)

General utilities live in utils.py.
"""

from __future__ import annotations

from typing import Dict, Any, Optional, Tuple, List
import math

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Arc, Polygon

from .utils import get_color_cycle


# ============================================================================
# BOUNDS HELPERS
# ============================================================================

def compute_geometry_bounds(config: Dict[str, Any], pad_frac: float = 0.10) -> Optional[Dict[str, float]]:
    """
    Compute a good axes_range for geometry diagrams so shapes/labels are in-frame.

    It inspects:
    - chart objects of type: polygon/circle/segment/ray/arc
    - top-level labeled_points (if present)

    Returns:
      {"x_min": ..., "x_max": ..., "y_min": ..., "y_max": ...} or None if nothing found.
    """
    if not isinstance(config, dict):
        return None

    charts = config.get("charts", config.get("graphs", [])) or []
    labeled_points = config.get("labeled_points", []) or []

    xs: List[float] = []
    ys: List[float] = []

    # --- chart-driven bounds ---
    for c in charts:
        if not isinstance(c, dict):
            continue
        t = str(c.get("type", "")).strip().lower()
        vf = c.get("visual_features") or {}
        if not isinstance(vf, dict):
            vf = {}

        if t == "polygon":
            pts = vf.get("points") or []
            if isinstance(pts, list):
                for p in pts:
                    try:
                        xs.append(float(p["x"]))
                        ys.append(float(p["y"]))
                    except Exception:
                        pass

        elif t == "circle":
            # Support: center + radius
            try:
                cx = float(vf.get("center", {}).get("x"))
                cy = float(vf.get("center", {}).get("y"))
                r = float(vf.get("radius"))
                xs.extend([cx - r, cx + r])
                ys.extend([cy - r, cy + r])
            except Exception:
                # Support alt: through points (center + point_on_circle)
                try:
                    cx = float(vf.get("center", {}).get("x"))
                    cy = float(vf.get("center", {}).get("y"))
                    px = float(vf.get("point_on_circle", {}).get("x"))
                    py = float(vf.get("point_on_circle", {}).get("y"))
                    r = math.hypot(px - cx, py - cy)
                    xs.extend([cx - r, cx + r])
                    ys.extend([cy - r, cy + r])
                except Exception:
                    pass

        elif t in {"segment", "ray"}:
            a = vf.get("a") or vf.get("start")
            b = vf.get("b") or vf.get("end")  # for ray, "end" is just a direction hint
            for p in (a, b):
                try:
                    xs.append(float(p["x"]))
                    ys.append(float(p["y"]))
                except Exception:
                    pass

        elif t == "arc":
            # Arc around a center, radius
            try:
                cx = float(vf.get("center", {}).get("x"))
                cy = float(vf.get("center", {}).get("y"))
                r = float(vf.get("radius"))
                xs.extend([cx - r, cx + r])
                ys.extend([cy - r, cy + r])
            except Exception:
                pass

    # --- labeled points can expand bounds too ---
    if isinstance(labeled_points, list):
        for p in labeled_points:
            if not isinstance(p, dict):
                continue
            try:
                xs.append(float(p["x"]))
                ys.append(float(p["y"]))
            except Exception:
                pass

    if not xs or not ys:
        return None

    x_min = float(min(xs))
    x_max = float(max(xs))
    y_min = float(min(ys))
    y_max = float(max(ys))

    # Handle degenerate case (all points same)
    dx = max(1e-6, x_max - x_min)
    dy = max(1e-6, y_max - y_min)

    pad_x = dx * float(pad_frac)
    pad_y = dy * float(pad_frac)

    # Ensure minimum visible span
    min_span = 1.0
    if (x_max - x_min) < min_span:
        cx = 0.5 * (x_min + x_max)
        x_min = cx - 0.5 * min_span
        x_max = cx + 0.5 * min_span
    if (y_max - y_min) < min_span:
        cy = 0.5 * (y_min + y_max)
        y_min = cy - 0.5 * min_span
        y_max = cy + 0.5 * min_span

    return {
        "x_min": x_min - pad_x,
        "x_max": x_max + pad_x,
        "y_min": y_min - pad_y,
        "y_max": y_max + pad_y,
    }


def geometry_present(config: Dict[str, Any]) -> bool:
    """
    True if config contains any geometry-type chart objects.
    """
    if not isinstance(config, dict):
        return False
    charts = config.get("charts", config.get("graphs", [])) or []
    for c in charts:
        if not isinstance(c, dict):
            continue
        t = str(c.get("type", "")).strip().lower()
        if t in {"polygon", "circle", "segment", "ray", "arc"}:
            return True
    return False


# ============================================================================
# GEOMETRY PRIMITIVES
# ============================================================================

def plot_polygon_geom(ax: plt.Axes, chart: Dict[str, Any]) -> None:
    """
    Geometry polygon (triangle/quadrilateral/etc).

    Expected:
    {
      "id":"poly1",
      "type":"polygon",
      "label":"Triangle",
      "visual_features":{
        "points":[{"x":0,"y":0},{"x":4,"y":0},{"x":1,"y":3}],
        "closed": true,
        "fill": false,
        "alpha": 0.15,
        "linewidth": 2.0
      }
    }
    """
    graph_id = str(chart.get("id", "poly")).strip() or "poly"
    vf = chart.get("visual_features") or {}
    if not isinstance(vf, dict):
        vf = {}

    pts = vf.get("points") or []
    if not isinstance(pts, list) or len(pts) < 3:
        return

    xy: List[Tuple[float, float]] = []
    for p in pts:
        try:
            xy.append((float(p["x"]), float(p["y"])))
        except Exception:
            return

    closed = bool(vf.get("closed", True))
    fill = bool(vf.get("fill", False))
    alpha = float(vf.get("alpha", 0.15)) if fill else 1.0
    lw = float(vf.get("linewidth", 2.0))

    show_label = bool(vf.get("show_label", False))
    label = (chart.get("label", "") or "").strip() if show_label else ""

    col = vf.get("color") or get_color_cycle(graph_id)

    patch = Polygon(
        xy,
        closed=closed,
        fill=fill,
        alpha=alpha,
        edgecolor=col,
        facecolor=col if fill else "none",
        linewidth=lw,
        label=label or None,
        zorder=3,
    )
    ax.add_patch(patch)


def plot_circle(ax: plt.Axes, chart: Dict[str, Any]) -> None:
    """
    Circle primitive.

    Expected:
    {
      "id":"c1",
      "type":"circle",
      "label":"(optional)",
      "visual_features":{
        "center":{"x":0,"y":0},
        "radius": 3.0,                    // OR use point_on_circle instead of radius
        "point_on_circle":{"x":3,"y":0},  // optional alternative to radius
        "fill": false,
        "alpha": 0.10,
        "linewidth": 2.0
      }
    }
    """
    graph_id = str(chart.get("id", "c")).strip() or "c"
    vf = chart.get("visual_features") or {}
    if not isinstance(vf, dict):
        vf = {}

    center = vf.get("center") or {}
    if not isinstance(center, dict):
        return

    try:
        cx = float(center["x"])
        cy = float(center["y"])
    except Exception:
        return

    r: Optional[float] = None
    if vf.get("radius", None) is not None:
        try:
            r = float(vf["radius"])
        except Exception:
            r = None
    if r is None and isinstance(vf.get("point_on_circle"), dict):
        try:
            px = float(vf["point_on_circle"]["x"])
            py = float(vf["point_on_circle"]["y"])
            r = math.hypot(px - cx, py - cy)
        except Exception:
            r = None
    if r is None or r <= 0:
        return

    fill = bool(vf.get("fill", False))
    alpha = float(vf.get("alpha", 0.10)) if fill else 1.0
    lw = float(vf.get("linewidth", 2.0))

    show_label = bool(vf.get("show_label", False))
    label = (chart.get("label", "") or "").strip() if show_label else ""

    col = vf.get("color") or get_color_cycle(graph_id)

    patch = Circle(
        (cx, cy),
        radius=r,
        fill=fill,
        alpha=alpha,
        edgecolor=col,
        facecolor=col if fill else "none",
        linewidth=lw,
        label=label or None,
        zorder=2,
    )
    ax.add_patch(patch)


def plot_segment(ax: plt.Axes, chart: Dict[str, Any]) -> None:
    """
    Line segment primitive.

    Expected:
    {
      "id":"s1",
      "type":"segment",
      "visual_features":{
        "a":{"x":0,"y":0},
        "b":{"x":4,"y":2},
        "linewidth": 2.0
      }
    }
    """
    graph_id = str(chart.get("id", "seg")).strip() or "seg"
    vf = chart.get("visual_features") or {}
    if not isinstance(vf, dict):
        vf = {}

    a = vf.get("a") or vf.get("start")
    b = vf.get("b") or vf.get("end")
    if not isinstance(a, dict) or not isinstance(b, dict):
        return

    try:
        x1, y1 = float(a["x"]), float(a["y"])
        x2, y2 = float(b["x"]), float(b["y"])
    except Exception:
        return

    lw = float(vf.get("linewidth", 2.0))
    col = vf.get("color") or get_color_cycle(graph_id)

    ax.plot([x1, x2], [y1, y2], linewidth=lw, color=col, zorder=4)


def plot_ray(ax: plt.Axes, chart: Dict[str, Any]) -> None:
    """
    Ray primitive: starts at a point and extends in the direction of another point.

    Expected:
    {
      "id":"r1",
      "type":"ray",
      "visual_features":{
        "start":{"x":0,"y":0},
        "through":{"x":2,"y":1},
        "length": 100,          // optional; default extends to edge using a big length
        "linewidth": 2.0
      }
    }
    """
    graph_id = str(chart.get("id", "ray")).strip() or "ray"
    vf = chart.get("visual_features") or {}
    if not isinstance(vf, dict):
        vf = {}

    s = vf.get("start") or vf.get("a")
    t = vf.get("through") or vf.get("b") or vf.get("end")
    if not isinstance(s, dict) or not isinstance(t, dict):
        return

    try:
        x1, y1 = float(s["x"]), float(s["y"])
        x2, y2 = float(t["x"]), float(t["y"])
    except Exception:
        return

    dx, dy = (x2 - x1), (y2 - y1)
    norm = math.hypot(dx, dy)
    if norm <= 1e-9:
        return

    dx /= norm
    dy /= norm

    length = float(vf.get("length", 100.0))
    x_end = x1 + dx * length
    y_end = y1 + dy * length

    lw = float(vf.get("linewidth", 2.0))
    col = vf.get("color") or get_color_cycle(graph_id)

    ax.plot([x1, x_end], [y1, y_end], linewidth=lw, color=col, zorder=4)


def plot_arc(ax: plt.Axes, chart: Dict[str, Any]) -> None:
    """
    Arc primitive (useful for angle/arc markers).

    Expected:
    {
      "id":"a1",
      "type":"arc",
      "visual_features":{
        "center":{"x":0,"y":0},
        "radius": 2.0,
        "theta1_deg": 0,
        "theta2_deg": 60,
        "linewidth": 2.0
      }
    }
    """
    graph_id = str(chart.get("id", "arc")).strip() or "arc"
    vf = chart.get("visual_features") or {}
    if not isinstance(vf, dict):
        vf = {}

    center = vf.get("center") or {}
    if not isinstance(center, dict):
        return

    try:
        cx = float(center["x"])
        cy = float(center["y"])
        r = float(vf["radius"])
        th1 = float(vf["theta1_deg"])
        th2 = float(vf["theta2_deg"])
    except Exception:
        return

    lw = float(vf.get("linewidth", 2.0))
    col = vf.get("color") or get_color_cycle(graph_id)

    patch = Arc(
        (cx, cy),
        width=2 * r,
        height=2 * r,
        angle=0,
        theta1=th1,
        theta2=th2,
        color=col,
        linewidth=lw,
        zorder=4,
    )
    ax.add_patch(patch)


# ============================================================================
# OPTIONAL: MARKERS (not used unless you wire them in later)
# ============================================================================

def plot_angle_marker(
    ax: plt.Axes,
    vertex: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    radius: float = 0.5,
    linewidth: float = 2.0,
    color: str = "black",
) -> None:
    """
    Draw a simple angle arc at 'vertex' between rays vertex->p1 and vertex->p2.
    This is a helper for future use; not part of the JSON schema unless you add it.
    """
    vx, vy = vertex
    a1 = math.degrees(math.atan2(p1[1] - vy, p1[0] - vx))
    a2 = math.degrees(math.atan2(p2[1] - vy, p2[0] - vx))

    # Normalize sweep to shortest positive direction
    while a2 < a1:
        a2 += 360.0
    if (a2 - a1) > 270.0:
        a1, a2 = a2, a1 + 360.0

    arc = Arc(
        (vx, vy),
        width=2 * radius,
        height=2 * radius,
        angle=0,
        theta1=a1,
        theta2=a2,
        color=color,
        linewidth=linewidth,
        zorder=5,
    )
    ax.add_patch(arc)