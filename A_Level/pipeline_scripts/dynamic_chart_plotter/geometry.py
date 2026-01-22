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
# INTERNAL HELPERS
# ============================================================================

def _safe_float(x: Any) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


def _line_style_to_matplotlib(line_style: Any) -> str:
    s = str(line_style or "").strip().lower()
    if s in {"dashed", "dash", "--"}:
        return "--"
    if s in {"dotted", "dot", ":"}:
        return ":"
    if s in {"dashdot", "-."}:
        return "-."
    return "-"  # default


def _get_axes_range_from_chart(chart: Dict[str, Any]) -> Optional[Dict[str, float]]:
    vf = chart.get("visual_features") or {}
    if isinstance(vf, dict) and isinstance(vf.get("axes_range"), dict):
        return vf.get("axes_range")
    return None


def _apply_geometry_viewport(ax: plt.Axes, chart: Dict[str, Any]) -> None:
    """
    Apply geometry viewport settings if present on chart.visual_features:
      - axes_range
      - equal_aspect
    """
    vf = chart.get("visual_features") or {}
    if not isinstance(vf, dict):
        return

    ar = vf.get("axes_range")
    if isinstance(ar, dict):
        try:
            ax.set_xlim(ar.get("x_min", -10), ar.get("x_max", 10))
            ax.set_ylim(ar.get("y_min", -10), ar.get("y_max", 10))
        except Exception:
            pass

    if bool(vf.get("equal_aspect", False)):
        try:
            ax.set_aspect("equal", adjustable="box")
        except Exception:
            pass


# ============================================================================
# BOUNDS HELPERS
# ============================================================================

def compute_geometry_bounds(config: Dict[str, Any], pad_frac: float = 0.10) -> Optional[Dict[str, float]]:
    """
    Compute a good axes_range for geometry diagrams so shapes/labels are in-frame.

    It inspects:
    - legacy chart objects of type: polygon/circle/segment/ray/arc
    - geometry chart objects of type: geometry (with `objects` list)
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

    # ✅ Track whether any circle exists so we can square the viewport.
    saw_circle = False

    # --- chart-driven bounds ---
    for c in charts:
        if not isinstance(c, dict):
            continue
        t = str(c.get("type", "")).strip().lower()
        vf = c.get("visual_features") or {}
        if not isinstance(vf, dict):
            vf = {}

        # --------------------------------------------------------------------
        # NEW: unified "geometry" chart schema (ALMA visual_data)
        # chart.type == "geometry" and chart.objects contains primitives:
        # point/segment/circle/label/text/angle_marker...
        # --------------------------------------------------------------------
        if t == "geometry":
            objects = c.get("objects") or []
            if not isinstance(objects, list):
                objects = []

            # Build point registry first (id -> (x,y))
            pt: Dict[str, Tuple[float, float]] = {}
            for obj in objects:
                if not isinstance(obj, dict):
                    continue
                if str(obj.get("type", "")).strip().lower() != "point":
                    continue
                pid = str(obj.get("id", "")).strip()
                x = _safe_float(obj.get("x"))
                y = _safe_float(obj.get("y"))
                if pid and x is not None and y is not None:
                    pt[pid] = (x, y)
                    xs.append(x)
                    ys.append(y)

            # Include extents for circles + free text positions
            for obj in objects:
                if not isinstance(obj, dict):
                    continue
                ot = str(obj.get("type", "")).strip().lower()

                if ot == "circle":
                    # center may be a point id (string) in ALMA schema
                    center_id = obj.get("center")
                    r = _safe_float(obj.get("radius"))
                    if isinstance(center_id, str) and center_id in pt and r is not None and r > 0:
                        saw_circle = True
                        cx, cy = pt[center_id]
                        xs.extend([cx - r, cx + r])
                        ys.extend([cy - r, cy + r])

                elif ot == "text":
                    tx = _safe_float(obj.get("x"))
                    ty = _safe_float(obj.get("y"))
                    if tx is not None and ty is not None:
                        xs.append(tx)
                        ys.append(ty)

                elif ot == "label":
                    # labels are attached to a target point id; keep bounds at that point
                    target = obj.get("target")
                    if isinstance(target, str) and target in pt:
                        x, y = pt[target]
                        xs.append(x)
                        ys.append(y)

            continue  # geometry chart handled; move to next chart

        # --------------------------------------------------------------------
        # LEGACY geometry primitives (standalone chart objects)
        # --------------------------------------------------------------------
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
                if r > 0:
                    saw_circle = True
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
                    if r > 0:
                        saw_circle = True
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
                if r > 0:
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

    # ✅ FIX: uniform padding based on dominant span (prevents “too vertical” + circle clipping)
    span = max(dx, dy)
    pad = span * float(pad_frac)

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

    # Recompute after min-span expansion
    dx = max(1e-6, x_max - x_min)
    dy = max(1e-6, y_max - y_min)

    # ✅ FIX: if a circle exists, force a square viewport around the overall content.
    if saw_circle:
        cx = 0.5 * (x_min + x_max)
        cy = 0.5 * (y_min + y_max)
        half = 0.5 * max(dx, dy) + pad
        return {
            "x_min": cx - half,
            "x_max": cx + half,
            "y_min": cy - half,
            "y_max": cy + half,
        }

    # Non-circle geometry: still use uniform padding so skinny dimension isn’t under-padded.
    return {
        "x_min": x_min - pad,
        "x_max": x_max + pad,
        "y_min": y_min - pad,
        "y_max": y_max + pad,
    }


def geometry_present(config: Dict[str, Any]) -> bool:
    """
    True if config contains any geometry-type chart objects.

    Supports:
    - legacy primitive charts: polygon/circle/segment/ray/arc
    - unified ALMA geometry chart: type == "geometry"
    """
    if not isinstance(config, dict):
        return False
    charts = config.get("charts", config.get("graphs", [])) or []
    for c in charts:
        if not isinstance(c, dict):
            continue
        t = str(c.get("type", "")).strip().lower()
        if t == "geometry":
            return True
        if t in {"polygon", "circle", "segment", "ray", "arc"}:
            return True
    return False


# ============================================================================
# GEOMETRY (ALMA) RENDERER
# ============================================================================

def plot_geometry(ax: plt.Axes, chart: Dict[str, Any], function_registry: Optional[Dict[str, Any]] = None) -> None:
    """
    Render a unified ALMA geometry chart.

    Expected (ALMA schema):
    {
      "id": "geo1",
      "type": "geometry",
      "label": "Diagram",
      "objects": [
        {"type":"point","id":"A","x":0,"y":6,"reveal":true},
        {"type":"segment","from":"A","to":"B","line_style":"dashed"},
        {"type":"circle","center":"O","radius":5.0},
        {"type":"label","target":"A","text":"A","offset":[-15,10],"reveal":true},
        {"type":"text","x":5,"y":6.5,"text":"$10 \\\\text{ cm}$"}
      ],
      "visual_features": {
        "axes_range": {"x_min":-2,"x_max":12,"y_min":-2,"y_max":12},
        "equal_aspect": true,
        "hide_values": true
      }
    }
    """
    if not isinstance(chart, dict):
        return

    objects = chart.get("objects") or []
    if not isinstance(objects, list):
        objects = []

    # Apply viewport hints if present (axes_range + equal_aspect)
    _apply_geometry_viewport(ax, chart)

    # Registry: point id -> (x,y)
    points: Dict[str, Tuple[float, float]] = {}
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        if str(obj.get("type", "")).strip().lower() != "point":
            continue
        pid = str(obj.get("id", "")).strip()
        x = _safe_float(obj.get("x"))
        y = _safe_float(obj.get("y"))
        if pid and x is not None and y is not None:
            points[pid] = (x, y)

    graph_id = str(chart.get("id", "geo")).strip() or "geo"
    base_col = get_color_cycle(graph_id)

    # 1) Draw segments/rays/arcs/circles first (so labels sit on top)
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        if bool(obj.get("reveal", True)) is False:
            continue

        ot = str(obj.get("type", "")).strip().lower()

        if ot == "segment":
            a_id = obj.get("from")
            b_id = obj.get("to")
            if isinstance(a_id, str) and isinstance(b_id, str) and a_id in points and b_id in points:
                (x1, y1) = points[a_id]
                (x2, y2) = points[b_id]
                lw = float(obj.get("linewidth", 2.0))
                ls = _line_style_to_matplotlib(obj.get("line_style"))
                col = obj.get("color") or base_col
                ax.plot([x1, x2], [y1, y2], linewidth=lw, linestyle=ls, color=col, zorder=3)

        elif ot == "ray":
            s_id = obj.get("from") or obj.get("start")
            t_id = obj.get("to") or obj.get("through") or obj.get("end")
            if isinstance(s_id, str) and isinstance(t_id, str) and s_id in points and t_id in points:
                (x1, y1) = points[s_id]
                (x2, y2) = points[t_id]
                dx, dy = (x2 - x1), (y2 - y1)
                norm = math.hypot(dx, dy)
                if norm > 1e-9:
                    dx /= norm
                    dy /= norm
                    length = float(obj.get("length", 100.0))
                    x_end = x1 + dx * length
                    y_end = y1 + dy * length
                    lw = float(obj.get("linewidth", 2.0))
                    ls = _line_style_to_matplotlib(obj.get("line_style"))
                    col = obj.get("color") or base_col
                    ax.plot([x1, x_end], [y1, y_end], linewidth=lw, linestyle=ls, color=col, zorder=3)

        elif ot == "circle":
            center_id = obj.get("center")
            r = _safe_float(obj.get("radius"))
            if isinstance(center_id, str) and center_id in points and r is not None and r > 0:
                (cx, cy) = points[center_id]
                fill = bool(obj.get("fill", False))
                alpha = float(obj.get("alpha", 0.10)) if fill else 1.0
                lw = float(obj.get("linewidth", 2.0))
                col = obj.get("color") or base_col
                patch = Circle(
                    (cx, cy),
                    radius=r,
                    fill=fill,
                    alpha=alpha,
                    edgecolor=col,
                    facecolor=col if fill else "none",
                    linewidth=lw,
                    zorder=2,
                )
                ax.add_patch(patch)

        elif ot == "arc":
            center_id = obj.get("center")
            r = _safe_float(obj.get("radius"))
            th1 = _safe_float(obj.get("theta1_deg"))
            th2 = _safe_float(obj.get("theta2_deg"))
            if (
                isinstance(center_id, str) and center_id in points
                and r is not None and r > 0
                and th1 is not None and th2 is not None
            ):
                (cx, cy) = points[center_id]
                lw = float(obj.get("linewidth", 2.0))
                col = obj.get("color") or base_col
                ls = _line_style_to_matplotlib(obj.get("line_style"))
                patch = Arc(
                    (cx, cy),
                    width=2 * r,
                    height=2 * r,
                    angle=0,
                    theta1=th1,
                    theta2=th2,
                    color=col,
                    linewidth=lw,
                    linestyle=ls,
                    zorder=4,
                )
                ax.add_patch(patch)

        elif ot == "polygon":
            pids = obj.get("points") or []
            if isinstance(pids, list) and len(pids) >= 3 and all(isinstance(p, str) for p in pids):
                xy: List[Tuple[float, float]] = []
                ok = True
                for pid in pids:
                    if pid not in points:
                        ok = False
                        break
                    xy.append(points[pid])
                if ok:
                    closed = bool(obj.get("closed", True))
                    fill = bool(obj.get("fill", False))
                    alpha = float(obj.get("alpha", 0.15)) if fill else 1.0
                    lw = float(obj.get("linewidth", 2.0))
                    col = obj.get("color") or base_col
                    patch = Polygon(
                        xy,
                        closed=closed,
                        fill=fill,
                        alpha=alpha,
                        edgecolor=col,
                        facecolor=col if fill else "none",
                        linewidth=lw,
                        zorder=2,
                    )
                    ax.add_patch(patch)

        elif ot == "angle_marker":
            at_id = obj.get("at")
            cps = obj.get("corner_points") or []
            if isinstance(at_id, str) and at_id in points and isinstance(cps, list) and len(cps) == 3:
                p1_id, v_id, p2_id = cps[0], cps[1], cps[2]
                if (
                    isinstance(p1_id, str) and isinstance(v_id, str) and isinstance(p2_id, str)
                    and p1_id in points and v_id in points and p2_id in points
                    and v_id == at_id
                ):
                    vertex = points[v_id]
                    p1 = points[p1_id]
                    p2 = points[p2_id]
                    radius = float(obj.get("radius", 0.6))
                    lw = float(obj.get("linewidth", 2.0))
                    col = obj.get("color") or "black"
                    plot_angle_marker(ax, vertex=vertex, p1=p1, p2=p2, radius=radius, linewidth=lw, color=col)

    # 2) Draw points (on top of lines)
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        if str(obj.get("type", "")).strip().lower() != "point":
            continue
        if bool(obj.get("reveal", True)) is False:
            continue

        pid = str(obj.get("id", "")).strip()
        if pid not in points:
            continue
        (x, y) = points[pid]
        col = obj.get("color") or "black"
        size = float(obj.get("size", 18.0))
        ax.scatter([x], [y], s=size, color=col, zorder=5)

    # 3) Labels and free text last
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        if bool(obj.get("reveal", True)) is False:
            continue

        ot = str(obj.get("type", "")).strip().lower()

        if ot == "label":
            target = obj.get("target")
            text = str(obj.get("text", "") or "")
            if not text:
                continue
            if isinstance(target, str) and target in points:
                (x, y) = points[target]
                offset = obj.get("offset") or [0, 0]
                dx = _safe_float(offset[0]) if isinstance(offset, list) and len(offset) >= 2 else 0.0
                dy = _safe_float(offset[1]) if isinstance(offset, list) and len(offset) >= 2 else 0.0
                dx = dx if dx is not None else 0.0
                dy = dy if dy is not None else 0.0

                col = obj.get("color") or "black"
                ax.annotate(
                    text,
                    xy=(x, y),
                    xytext=(dx, dy),
                    textcoords="offset points",
                    ha="center",
                    va="center",
                    color=col,
                    fontsize=int(obj.get("fontsize", 12)),
                    zorder=6,
                )

        elif ot == "text":
            tx = _safe_float(obj.get("x"))
            ty = _safe_float(obj.get("y"))
            text = str(obj.get("text", "") or "")
            if tx is None or ty is None or not text:
                continue
            col = obj.get("color") or "black"
            ax.text(
                tx,
                ty,
                text,
                color=col,
                fontsize=int(obj.get("fontsize", 12)),
                ha="center",
                va="center",
                zorder=6,
            )


# ============================================================================
# GEOMETRY PRIMITIVES (LEGACY STANDALONE CHARTS)
# ============================================================================

def plot_polygon_geom(ax: plt.Axes, chart: Dict[str, Any]) -> None:
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
# OPTIONAL: MARKERS (used by ALMA angle_marker too)
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