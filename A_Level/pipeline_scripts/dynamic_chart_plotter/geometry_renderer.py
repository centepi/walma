"""
geometry_renderer.py — Geometry diagram rendering for dynamic_chart_plotter

This file contains ONLY:
- unified ALMA geometry renderer (plot_geometry)
- legacy geometry primitive renderers (circle/segment/ray/arc/polygon)
- small geometry drawing helpers (angle markers, semicircle construction, etc.)

It intentionally does NOT contain:
- bounds helpers / compute_geometry_bounds (move to geometry_bounds.py)
- dynamic_chart_plotter() orchestrator
- chart/table plotting implementations
- layout creation / dispatcher

Those live in:
- plotter.py         (controller/orchestrator/dispatcher)
- charts.py          (chart/table renderers)
- geometry_bounds.py (bounds helpers)

General utilities live in utils.py.
"""

from __future__ import annotations

from typing import Dict, Any, Optional, Tuple, List
import math

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Arc, Polygon, Wedge
from matplotlib.path import Path
from matplotlib.patches import PathPatch

from .utils import get_color_cycle

# ✅ NEW: shared, dependency-light helpers (no cycles)
from .geometry_common import (
    safe_float,
    normalize_arc_angles,
    semicircle_from_diameter,
    angle_from_points,
    resolve_sector_angles,
    line_style_to_matplotlib,
    looks_like_label_id,
)

# ============================================================================
# INTERNAL HELPERS
# ============================================================================

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


def _draw_radial_edge(
    ax: plt.Axes,
    center_xy: Tuple[float, float],
    r0: float,
    r1: float,
    theta_deg: float,
    *,
    color: str,
    linewidth: float,
    linestyle: str,
    zorder: int = 4,
) -> None:
    """Draw a straight radial edge between radii r0..r1 at angle theta_deg."""
    cx, cy = center_xy
    t = math.radians(theta_deg)
    x0 = cx + r0 * math.cos(t)
    y0 = cy + r0 * math.sin(t)
    x1 = cx + r1 * math.cos(t)
    y1 = cy + r1 * math.sin(t)
    line = ax.plot([x0, x1], [y0, y1], color=color, linewidth=linewidth, linestyle=linestyle, zorder=zorder)
    # ✅ Avoid rare “arc/edge clipped at frame” artefacts when bounds are tight.
    try:
        for ln in line:
            ln.set_clip_on(False)
    except Exception:
        pass


def _safe_linewidth(x: Any, default: float = 2.0) -> float:
    """Clamp linewidth to a sensible positive value so edges don't vanish."""
    try:
        v = float(x)
        if not math.isfinite(v) or v <= 0:
            return float(default)
        return v
    except Exception:
        return float(default)


def _internal_angle_span(theta1: float, theta2: float) -> Tuple[float, float]:
    """
    Given two angles (deg), return the *smaller* CCW span [t1,t2] in Matplotlib
    convention where t2 >= t1 and (t2-t1) <= 180 when possible.

    This produces “nice” angle markers and stable mid-angle label positions.
    """
    t1 = float(theta1)
    t2 = float(theta2)
    t1, t2 = normalize_arc_angles(t1, t2)
    span = t2 - t1
    if span > 180.0:
        # Swap to get the complementary smaller span
        t1, t2 = t2, t1 + 360.0
    return t1, t2


def _place_angle_text(
    ax: plt.Axes,
    *,
    vertex: Tuple[float, float],
    theta1: float,
    theta2: float,
    radius: float,
    text: str,
    color: str = "black",
    fontsize: int = 12,
    text_radius_scale: float = 1.25,
    extra_offset_pts: Tuple[float, float] = (0.0, 0.0),
    zorder: int = 6,
) -> None:
    """
    Place angle text near the midpoint of an angle marker, with a consistent
    offset that avoids overlapping rays.
    """
    try:
        t1, t2 = _internal_angle_span(theta1, theta2)
        mid = 0.5 * (t1 + t2)
        vx, vy = vertex
        rr = max(1e-6, float(radius)) * float(text_radius_scale)
        mx = vx + rr * math.cos(math.radians(mid))
        my = vy + rr * math.sin(math.radians(mid))

        dx_pts, dy_pts = extra_offset_pts
        ax.annotate(
            text,
            xy=(mx, my),
            xytext=(dx_pts, dy_pts),
            textcoords="offset points",
            ha="center",
            va="center",
            color=color,
            fontsize=int(fontsize),
            zorder=zorder,
            clip_on=False,  # ✅ don't disappear when very close to the frame
        )
    except Exception:
        pass


def _sample_arc_points(
    center_xy: Tuple[float, float],
    r: float,
    t1_deg: float,
    t2_deg: float,
    n: int = 72,
) -> List[Tuple[float, float]]:
    """
    Sample points along a circular arc from t1->t2 (degrees), CCW, where t2 >= t1.
    """
    try:
        cx, cy = center_xy
        if n < 8:
            n = 8
        ts = np.linspace(float(t1_deg), float(t2_deg), int(n))
        pts: List[Tuple[float, float]] = []
        for th in ts:
            rad = math.radians(float(th))
            pts.append((cx + float(r) * math.cos(rad), cy + float(r) * math.sin(rad)))
        return pts
    except Exception:
        return []


# ============================================================================
# GEOMETRY (ALMA) RENDERER
# ============================================================================

def plot_geometry(ax: plt.Axes, chart: Dict[str, Any], function_registry: Optional[Dict[str, Any]] = None) -> None:
    """
    Render a unified ALMA geometry chart.

    Supported object types:
      - point, segment, ray, circle, semicircle, arc, polygon, angle_marker, label, text
      - sector: proper sector with arc + two radii (+ optional fill)
      - annular_sector: ring sector between r_inner and r_outer (+ optional fill)
      - circular_segment: region bounded by an arc AB and chord AB (+ optional fill)

    Notes:
      - Unknown object types are ignored (never crash).
      - reveal:false objects are skipped.
      - Auto-label fallback for revealed points if no explicit label exists.
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
        x = safe_float(obj.get("x"))
        y = safe_float(obj.get("y"))
        if pid and x is not None and y is not None:
            points[pid] = (x, y)

    graph_id = str(chart.get("id", "geo")).strip() or "geo"
    base_col = get_color_cycle(graph_id)

    # Track explicit labels so we can auto-label only missing ones.
    explicitly_labeled: set[str] = set()
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        if bool(obj.get("reveal", True)) is False:
            continue
        if str(obj.get("type", "")).strip().lower() != "label":
            continue
        tgt = obj.get("target")
        if isinstance(tgt, str) and tgt.strip():
            explicitly_labeled.add(tgt.strip())

    # 1) Draw shapes/lines first (so points + labels sit on top)
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
                lw = _safe_linewidth(obj.get("linewidth", 2.0))
                ls = line_style_to_matplotlib(obj.get("line_style"))
                col = obj.get("color") or base_col
                line = ax.plot([x1, x2], [y1, y2], linewidth=lw, linestyle=ls, color=col, zorder=3)
                try:
                    for ln in line:
                        ln.set_clip_on(False)
                except Exception:
                    pass

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
                    lw = _safe_linewidth(obj.get("linewidth", 2.0))
                    ls = line_style_to_matplotlib(obj.get("line_style"))
                    col = obj.get("color") or base_col
                    line = ax.plot([x1, x_end], [y1, y_end], linewidth=lw, linestyle=ls, color=col, zorder=3)
                    try:
                        for ln in line:
                            ln.set_clip_on(False)
                    except Exception:
                        pass

        elif ot == "circle":
            center_id = obj.get("center")
            r = safe_float(obj.get("radius"))
            if isinstance(center_id, str) and center_id in points and r is not None and r > 0:
                (cx, cy) = points[center_id]
                fill = bool(obj.get("fill", False))
                alpha = float(obj.get("alpha", 0.10)) if fill else 1.0
                lw = _safe_linewidth(obj.get("linewidth", 2.0))
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
                patch.set_clip_on(False)  # ✅ avoid rare clipping at frame
                ax.add_patch(patch)

        elif ot == "semicircle":
            dia = obj.get("diameter")
            if isinstance(dia, list) and len(dia) >= 2:
                a_id, b_id = dia[0], dia[1]
                if isinstance(a_id, str) and isinstance(b_id, str) and a_id in points and b_id in points:
                    side = obj.get("side", "left")
                    (cx, cy), r, th1, th2 = semicircle_from_diameter(points[a_id], points[b_id], side=side)
                    if r > 0:
                        lw = _safe_linewidth(obj.get("linewidth", 2.0))
                        col = obj.get("color") or base_col
                        ls = line_style_to_matplotlib(obj.get("line_style"))
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
                        patch.set_clip_on(False)  # ✅ avoid rare clipping at frame
                        ax.add_patch(patch)

        elif ot == "arc":
            center_id = obj.get("center")
            r = safe_float(obj.get("radius"))
            if isinstance(center_id, str) and center_id in points and r is not None and r > 0:
                (cx, cy) = points[center_id]

                th1 = safe_float(obj.get("theta1_deg"))
                th2 = safe_float(obj.get("theta2_deg"))
                if th1 is not None and th2 is not None:
                    t1, t2 = normalize_arc_angles(th1, th2)
                else:
                    angs = resolve_sector_angles((cx, cy), points, obj)
                    if angs is None:
                        continue
                    t1, t2 = angs

                lw = _safe_linewidth(obj.get("linewidth", 2.0))
                col = obj.get("color") or base_col
                ls = line_style_to_matplotlib(obj.get("line_style"))
                patch = Arc(
                    (cx, cy),
                    width=2 * r,
                    height=2 * r,
                    angle=0,
                    theta1=t1,
                    theta2=t2,
                    color=col,
                    linewidth=lw,
                    linestyle=ls,
                    zorder=6,
                )
                patch.set_clip_on(False)  # ✅ avoid rare clipping at frame
                ax.add_patch(patch)

        elif ot == "sector":
            center_id = obj.get("center")
            r = safe_float(obj.get("radius"))
            if isinstance(center_id, str) and center_id in points and r is not None and r > 0:
                center_xy = points[center_id]
                angs = resolve_sector_angles(center_xy, points, obj)
                if angs is None:
                    continue
                t1, t2 = angs

                col = obj.get("color") or base_col
                lw = _safe_linewidth(obj.get("linewidth", 2.0))
                ls = line_style_to_matplotlib(obj.get("line_style"))
                fill = bool(obj.get("fill", False))
                alpha = float(obj.get("alpha", 0.15)) if fill else 1.0

                wedge = Wedge(
                    center_xy,
                    r,
                    t1,
                    t2,
                    width=None,
                    facecolor=col if fill else "none",
                    edgecolor=col,
                    linewidth=lw,
                    linestyle=ls,
                    alpha=alpha,
                    zorder=3,
                )
                wedge.set_clip_on(False)  # ✅ avoid rare clipping at frame
                ax.add_patch(wedge)

                # ✅ Always draw the curved boundary explicitly (Wedge edge can disappear on some backends).
                arc = Arc(
                    center_xy,
                    width=2 * r,
                    height=2 * r,
                    angle=0,
                    theta1=t1,
                    theta2=t2,
                    color=col,
                    linewidth=lw,
                    linestyle=ls,
                    zorder=7,
                )
                arc.set_clip_on(False)
                ax.add_patch(arc)

                if bool(obj.get("draw_radial_edges", True)):
                    _draw_radial_edge(ax, center_xy, 0.0, r, t1, color=col, linewidth=lw, linestyle=ls, zorder=7)
                    _draw_radial_edge(ax, center_xy, 0.0, r, t2, color=col, linewidth=lw, linestyle=ls, zorder=7)

        elif ot == "annular_sector":
            center_id = obj.get("center")
            r_in = safe_float(obj.get("r_inner", obj.get("radius_inner")))
            r_out = safe_float(obj.get("r_outer", obj.get("radius_outer")))
            if (
                isinstance(center_id, str) and center_id in points
                and r_in is not None and r_out is not None
                and r_out > r_in > 0
            ):
                center_xy = points[center_id]
                angs = resolve_sector_angles(center_xy, points, obj)
                if angs is None:
                    continue
                t1, t2 = angs

                col = obj.get("color") or base_col
                lw = _safe_linewidth(obj.get("linewidth", 2.0))
                ls = line_style_to_matplotlib(obj.get("line_style"))
                fill = bool(obj.get("fill", False))
                alpha = float(obj.get("alpha", 0.15)) if fill else 1.0

                width = float(r_out - r_in)
                wedge = Wedge(
                    center_xy,
                    r_out,
                    t1,
                    t2,
                    width=width,
                    facecolor=col if fill else "none",
                    edgecolor=col,
                    linewidth=lw,
                    linestyle=ls,
                    alpha=alpha,
                    zorder=3,
                )
                wedge.set_clip_on(False)
                ax.add_patch(wedge)

                outer_arc = Arc(
                    center_xy,
                    width=2 * r_out,
                    height=2 * r_out,
                    angle=0,
                    theta1=t1,
                    theta2=t2,
                    color=col,
                    linewidth=lw,
                    linestyle=ls,
                    zorder=7,
                )
                outer_arc.set_clip_on(False)
                ax.add_patch(outer_arc)

                inner_arc = Arc(
                    center_xy,
                    width=2 * r_in,
                    height=2 * r_in,
                    angle=0,
                    theta1=t1,
                    theta2=t2,
                    color=col,
                    linewidth=lw,
                    linestyle=ls,
                    zorder=7,
                )
                inner_arc.set_clip_on(False)
                ax.add_patch(inner_arc)

                if bool(obj.get("draw_radial_edges", True)):
                    _draw_radial_edge(ax, center_xy, r_in, r_out, t1, color=col, linewidth=lw, linestyle=ls, zorder=7)
                    _draw_radial_edge(ax, center_xy, r_in, r_out, t2, color=col, linewidth=lw, linestyle=ls, zorder=7)

        elif ot == "circular_segment":
            # Region bounded by arc AB and chord AB (a "segment" of a circle).
            # Required:
            # - center + radius
            # - either theta1_deg/theta2_deg OR from/to (angles inferred via resolve_sector_angles)
            #
            # Optional:
            # - fill (default True if provided as "shaded" region)
            # - alpha (default 0.18 if fill)
            # - major: true to shade the MAJOR segment (default False -> minor segment)
            # - draw_chord: true/false (default True)
            # - draw_arc: true/false (default True)
            center_id = obj.get("center")
            r = safe_float(obj.get("radius"))
            if isinstance(center_id, str) and center_id in points and r is not None and r > 0:
                center_xy = points[center_id]
                cx, cy = center_xy

                th1 = safe_float(obj.get("theta1_deg"))
                th2 = safe_float(obj.get("theta2_deg"))
                if th1 is not None and th2 is not None:
                    a1, a2 = normalize_arc_angles(th1, th2)
                else:
                    angs = resolve_sector_angles(center_xy, points, obj)
                    if angs is None:
                        continue
                    a1, a2 = angs
                    a1, a2 = normalize_arc_angles(a1, a2)

                # Default: shade MINOR segment (smaller arc). Allow major override.
                span = float(a2 - a1)
                want_major = bool(obj.get("major", False))
                if (span > 180.0 and not want_major) or (span <= 180.0 and want_major):
                    a1, a2 = a2, a1 + 360.0
                    span = float(a2 - a1)

                col = obj.get("color") or base_col
                lw = _safe_linewidth(obj.get("linewidth", 2.0))
                ls = line_style_to_matplotlib(obj.get("line_style"))

                fill = bool(obj.get("fill", True))
                alpha = float(obj.get("alpha", 0.18)) if fill else 1.0

                # Build a closed path: arc points (a1->a2), then chord back to start.
                n = int(obj.get("n_samples", 72) or 72)
                arc_pts = _sample_arc_points(center_xy, float(r), float(a1), float(a2), n=n)
                if len(arc_pts) >= 2:
                    verts: List[Tuple[float, float]] = []
                    codes: List[int] = []

                    # Move to first arc point
                    verts.append(arc_pts[0])
                    codes.append(Path.MOVETO)

                    # Line along the arc polyline
                    for p in arc_pts[1:]:
                        verts.append(p)
                        codes.append(Path.LINETO)

                    # Close via chord back to start (Path.CLOSEPOLY closes to MOVETO point)
                    verts.append(arc_pts[0])
                    codes.append(Path.CLOSEPOLY)

                    patch = PathPatch(
                        Path(verts, codes),
                        facecolor=col if fill else "none",
                        edgecolor="none",  # outlines are drawn explicitly below
                        alpha=alpha if fill else 1.0,
                        zorder=2,
                    )
                    patch.set_clip_on(False)
                    ax.add_patch(patch)

                    # Optional outlines: chord + arc
                    draw_chord = bool(obj.get("draw_chord", True))
                    draw_arc = bool(obj.get("draw_arc", True))

                    if draw_chord:
                        xA, yA = arc_pts[0]
                        xB, yB = arc_pts[-1]
                        line = ax.plot([xA, xB], [yA, yB], color=col, linewidth=lw, linestyle=ls, zorder=6)
                        try:
                            for ln in line:
                                ln.set_clip_on(False)
                        except Exception:
                            pass

                    if draw_arc:
                        arc = Arc(
                            (cx, cy),
                            width=2 * r,
                            height=2 * r,
                            angle=0,
                            theta1=float(a1),
                            theta2=float(a2),
                            color=col,
                            linewidth=lw,
                            linestyle=ls,
                            zorder=7,
                        )
                        arc.set_clip_on(False)
                        ax.add_patch(arc)

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
                    lw = _safe_linewidth(obj.get("linewidth", 2.0))
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
                    patch.set_clip_on(False)
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
                    lw = _safe_linewidth(obj.get("linewidth", 2.0))
                    col = obj.get("color") or "black"

                    # Draw arc marker
                    plot_angle_marker(
                        ax,
                        vertex=vertex,
                        p1=p1,
                        p2=p2,
                        radius=radius,
                        linewidth=lw,
                        color=col,
                        linestyle=line_style_to_matplotlib(obj.get("line_style")),
                    )

                    # ✅ Optional: stable angle text placement (prevents overlap / “far away” labels)
                    # Supported fields (non-breaking; ignored if absent):
                    # - "text": string (e.g. "120°" or "$\\theta$")
                    # - "label": alias for text
                    # - "value_deg": number -> formatted as "<n>°"
                    # - "text_radius_scale": float (default 1.25)
                    # - "text_offset_pts": [dx,dy] in points (default [0,0])
                    text = obj.get("text", obj.get("label"))
                    if text is None and obj.get("value_deg") is not None:
                        try:
                            v = float(obj.get("value_deg"))
                            if abs(v - round(v)) < 1e-6:
                                text = f"{int(round(v))}°"
                            else:
                                text = f"{v:g}°"
                        except Exception:
                            text = None

                    if isinstance(text, str) and text.strip():
                        try:
                            t1 = angle_from_points(vertex, p1)
                            t2 = angle_from_points(vertex, p2)
                            t1, t2 = _internal_angle_span(t1, t2)
                        except Exception:
                            t1, t2 = 0.0, 0.0

                        tr = safe_float(obj.get("text_radius_scale"))
                        tr = float(tr) if tr is not None else 1.25

                        off = obj.get("text_offset_pts")
                        if isinstance(off, list) and len(off) >= 2:
                            dxp = safe_float(off[0]) or 0.0
                            dyp = safe_float(off[1]) or 0.0
                            extra = (float(dxp), float(dyp))
                        else:
                            extra = (0.0, 0.0)

                        _place_angle_text(
                            ax,
                            vertex=vertex,
                            theta1=t1,
                            theta2=t2,
                            radius=radius,
                            text=text.strip(),
                            color=str(obj.get("text_color", col) or col),
                            fontsize=int(obj.get("text_fontsize", obj.get("fontsize", 12))),
                            text_radius_scale=tr,
                            extra_offset_pts=extra,
                            zorder=6,
                        )

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
        sc = ax.scatter([x], [y], s=size, color=col, zorder=8)
        try:
            sc.set_clip_on(False)
        except Exception:
            pass

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
                dx = safe_float(offset[0]) if isinstance(offset, list) and len(offset) >= 2 else 0.0
                dy = safe_float(offset[1]) if isinstance(offset, list) and len(offset) >= 2 else 0.0
                dx = dx if dx is not None else 0.0
                dy = dy if dy is not None else 0.0

                col = obj.get("color") or "black"
                ann = ax.annotate(
                    text,
                    xy=(x, y),
                    xytext=(dx, dy),
                    textcoords="offset points",
                    ha="center",
                    va="center",
                    color=col,
                    fontsize=int(obj.get("fontsize", 12)),
                    zorder=9,
                    clip_on=False,
                )
                try:
                    ann.set_clip_on(False)
                except Exception:
                    pass

        elif ot == "text":
            tx = safe_float(obj.get("x"))
            ty = safe_float(obj.get("y"))
            text = str(obj.get("text", "") or "")
            if tx is None or ty is None or not text:
                continue
            col = obj.get("color") or "black"
            t = ax.text(
                tx,
                ty,
                text,
                color=col,
                fontsize=int(obj.get("fontsize", 12)),
                ha="center",
                va="center",
                zorder=9,
                clip_on=False,
            )
            try:
                t.set_clip_on(False)
            except Exception:
                pass

    # 4) Auto-label fallback: if generator forgot labels, label revealed points.
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
        if pid in explicitly_labeled:
            continue
        if not looks_like_label_id(pid):
            continue
        if bool(obj.get("auto_label", True)) is False:
            continue

        (x, y) = points[pid]
        col = obj.get("label_color") or "black"
        fontsize = int(obj.get("label_fontsize", 12))
        ann = ax.annotate(
            pid,
            xy=(x, y),
            xytext=(6, 6),
            textcoords="offset points",
            ha="left",
            va="bottom",
            color=col,
            fontsize=fontsize,
            zorder=9,
            clip_on=False,
        )
        try:
            ann.set_clip_on(False)
        except Exception:
            pass


# ============================================================================
# LEGACY GEOMETRY PRIMITIVES (standalone chart objects)
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
    lw = _safe_linewidth(vf.get("linewidth", 2.0))

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
    patch.set_clip_on(False)
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
    lw = _safe_linewidth(vf.get("linewidth", 2.0))

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
    patch.set_clip_on(False)
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

    lw = _safe_linewidth(vf.get("linewidth", 2.0))
    col = vf.get("color") or get_color_cycle(graph_id)

    line = ax.plot([x1, x2], [y1, y2], linewidth=lw, color=col, zorder=4)
    try:
        for ln in line:
            ln.set_clip_on(False)
    except Exception:
        pass


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

    lw = _safe_linewidth(vf.get("linewidth", 2.0))
    col = vf.get("color") or get_color_cycle(graph_id)

    line = ax.plot([x1, x_end], [y1, y_end], linewidth=lw, color=col, zorder=4)
    try:
        for ln in line:
            ln.set_clip_on(False)
    except Exception:
        pass


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

    lw = _safe_linewidth(vf.get("linewidth", 2.0))
    col = vf.get("color") or get_color_cycle(graph_id)

    t1, t2 = normalize_arc_angles(th1, th2)
    patch = Arc(
        (cx, cy),
        width=2 * r,
        height=2 * r,
        angle=0,
        theta1=t1,
        theta2=t2,
        color=col,
        linewidth=lw,
        zorder=4,
    )
    patch.set_clip_on(False)
    ax.add_patch(patch)


# ============================================================================
# OPTIONAL: MARKERS
# ============================================================================

def plot_angle_marker(
    ax: plt.Axes,
    vertex: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    radius: float = 0.5,
    linewidth: float = 2.0,
    color: str = "black",
    linestyle: str = "-",
) -> None:
    """
    Draw a simple angle arc at 'vertex' between rays vertex->p1 and vertex->p2.

    Notes:
      - We choose the smaller internal angle span to avoid huge arcs.
      - clip_on=False to prevent “vanishing” when bounds are tight.
    """
    vx, vy = vertex
    a1 = math.degrees(math.atan2(p1[1] - vy, p1[0] - vx))
    a2 = math.degrees(math.atan2(p2[1] - vy, p2[0] - vx))

    t1, t2 = _internal_angle_span(a1, a2)

    arc = Arc(
        (vx, vy),
        width=2 * radius,
        height=2 * radius,
        angle=0,
        theta1=t1,
        theta2=t2,
        color=color,
        linewidth=linewidth,
        linestyle=linestyle,
        zorder=5,
    )
    arc.set_clip_on(False)
    ax.add_patch(arc)