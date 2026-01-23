"""
geometry_bounds.py — Geometry bounds helpers for dynamic_chart_plotter

This file contains ONLY:
- geometry bounds helpers (so diagrams stay in-frame)
- simple detection helpers (geometry_present)

It intentionally does NOT contain:
- dynamic_chart_plotter() orchestrator
- chart/table plotting implementations
- geometry rendering primitives (those live in geometry_renderer.py)

Those live in:
- plotter.py            (controller/orchestrator/dispatcher)
- charts.py             (chart/table renderers)
- geometry_renderer.py  (geometry renderers)

General utilities live in utils.py.
"""

from __future__ import annotations

from typing import Dict, Any, Optional, Tuple, List
import math

# ✅ NEW: shared, dependency-light helpers (no cycles)
from .geometry_common import (
    safe_float,
    normalize_arc_angles,
    semicircle_from_diameter,
    resolve_sector_angles,
)

# ============================================================================
# PUBLIC HELPERS
# ============================================================================

def compute_geometry_bounds(config: Dict[str, Any], pad_frac: float = 0.10) -> Optional[Dict[str, float]]:
    """
    Compute a good axes_range for geometry diagrams so shapes/labels are in-frame.

    It inspects:
    - legacy chart objects of type: polygon/circle/segment/ray/arc
    - geometry chart objects of type: geometry (with `objects` list)
    - top-level labeled_points (if present)

    New (bounds-aware):
    - sectors / annular_sectors inside geometry objects are treated as circle-ish
      and we bound using outer radius (safe).
    - circular segments (arc + chord region) are treated as circle-ish too.

    Returns:
      {"x_min": ..., "x_max": ..., "y_min": ..., "y_max": ...} or None if nothing found.
    """
    if not isinstance(config, dict):
        return None

    charts = config.get("charts", config.get("graphs", [])) or []
    labeled_points = config.get("labeled_points", []) or []

    xs: List[float] = []
    ys: List[float] = []

    # If any circle-ish exists, we square the viewport at the end.
    saw_circle = False

    # Track radii of circle-ish objects so padding can scale appropriately.
    # (prevents “arc clipped” when labels/edges sit near the boundary)
    circle_radii: List[float] = []

    # Track presence of angle markers / labels so we can add extra margins.
    saw_angle_marker = False
    saw_text_or_label = False

    # --- chart-driven bounds ---
    for c in charts:
        if not isinstance(c, dict):
            continue
        t = str(c.get("type", "")).strip().lower()
        vf = c.get("visual_features") or {}
        if not isinstance(vf, dict):
            vf = {}

        # --------------------------------------------------------------------
        # unified "geometry" chart schema (ALMA visual_data)
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
                x = safe_float(obj.get("x"))
                y = safe_float(obj.get("y"))
                if pid and x is not None and y is not None:
                    pt[pid] = (x, y)
                    xs.append(x)
                    ys.append(y)

            for obj in objects:
                if not isinstance(obj, dict):
                    continue
                if bool(obj.get("reveal", True)) is False:
                    continue

                ot = str(obj.get("type", "")).strip().lower()

                if ot == "circle":
                    center_id = obj.get("center")
                    r = safe_float(obj.get("radius"))
                    if isinstance(center_id, str) and center_id in pt and r is not None and r > 0:
                        saw_circle = True
                        circle_radii.append(float(r))
                        cx, cy = pt[center_id]
                        xs.extend([cx - r, cx + r])
                        ys.extend([cy - r, cy + r])

                elif ot == "semicircle":
                    dia = obj.get("diameter")
                    if isinstance(dia, list) and len(dia) >= 2:
                        a_id, b_id = dia[0], dia[1]
                        if isinstance(a_id, str) and isinstance(b_id, str) and a_id in pt and b_id in pt:
                            saw_circle = True
                            (cx, cy), r, _, _ = semicircle_from_diameter(
                                pt[a_id], pt[b_id], side=obj.get("side", "left")
                            )
                            if r > 0:
                                circle_radii.append(float(r))
                                xs.extend([cx - r, cx + r])
                                ys.extend([cy - r, cy + r])

                elif ot == "arc":
                    # Safe bounds: use full circle bbox around center/radius
                    center_id = obj.get("center")
                    r = safe_float(obj.get("radius"))
                    if isinstance(center_id, str) and center_id in pt and r is not None and r > 0:
                        cx, cy = pt[center_id]
                        circle_radii.append(float(r))
                        xs.extend([cx - r, cx + r])
                        ys.extend([cy - r, cy + r])

                elif ot == "sector":
                    center_id = obj.get("center")
                    r = safe_float(obj.get("radius"))
                    if isinstance(center_id, str) and center_id in pt and r is not None and r > 0:
                        saw_circle = True
                        circle_radii.append(float(r))
                        cx, cy = pt[center_id]
                        xs.extend([cx - r, cx + r])
                        ys.extend([cy - r, cy + r])

                        # If we can resolve angles, include radial endpoints too
                        angs = resolve_sector_angles((cx, cy), pt, obj)
                        if angs is not None:
                            t1, t2 = angs
                            for th in (t1, t2):
                                rad = math.radians(th)
                                xs.append(cx + r * math.cos(rad))
                                ys.append(cy + r * math.sin(rad))

                elif ot == "annular_sector":
                    center_id = obj.get("center")
                    r_in = safe_float(obj.get("r_inner", obj.get("radius_inner")))
                    r_out = safe_float(obj.get("r_outer", obj.get("radius_outer")))
                    if (
                        isinstance(center_id, str) and center_id in pt
                        and r_in is not None and r_out is not None
                        and r_out > r_in > 0
                    ):
                        saw_circle = True
                        circle_radii.append(float(r_out))
                        cx, cy = pt[center_id]
                        xs.extend([cx - r_out, cx + r_out])
                        ys.extend([cy - r_out, cy + r_out])

                        # If we can resolve angles, include the 4 corner endpoints
                        angs = resolve_sector_angles((cx, cy), pt, obj)
                        if angs is not None:
                            t1, t2 = angs
                            for th in (t1, t2):
                                rad = math.radians(th)
                                xs.append(cx + r_in * math.cos(rad))
                                ys.append(cy + r_in * math.sin(rad))
                                xs.append(cx + r_out * math.cos(rad))
                                ys.append(cy + r_out * math.sin(rad))

                elif ot == "circular_segment":
                    # Treat as circle-ish; safe bounds via radius.
                    center_id = obj.get("center")
                    r = safe_float(obj.get("radius"))
                    if isinstance(center_id, str) and center_id in pt and r is not None and r > 0:
                        saw_circle = True
                        circle_radii.append(float(r))
                        cx, cy = pt[center_id]
                        xs.extend([cx - r, cx + r])
                        ys.extend([cy - r, cy + r])

                        # If we can resolve angles, include chord endpoints too (tightens + helps labels)
                        th1 = safe_float(obj.get("theta1_deg"))
                        th2 = safe_float(obj.get("theta2_deg"))
                        if th1 is not None and th2 is not None:
                            t1, t2 = normalize_arc_angles(th1, th2)
                        else:
                            angs = resolve_sector_angles((cx, cy), pt, obj)
                            if angs is None:
                                t1 = t2 = None
                            else:
                                t1, t2 = angs
                                t1, t2 = normalize_arc_angles(t1, t2)

                        if t1 is not None and t2 is not None:
                            # Use the same “minor/major” choice as renderer defaults:
                            span = float(t2 - t1)
                            want_major = bool(obj.get("major", False))
                            if (span > 180.0 and not want_major) or (span <= 180.0 and want_major):
                                t1, t2 = t2, t1 + _toggle360(t1, t2)
                            for th in (t1, t2):
                                rad = math.radians(float(th))
                                xs.append(cx + float(r) * math.cos(rad))
                                ys.append(cy + float(r) * math.sin(rad))

                elif ot == "polygon":
                    pids = obj.get("points") or []
                    if isinstance(pids, list):
                        for pid in pids:
                            if isinstance(pid, str) and pid in pt:
                                x, y = pt[pid]
                                xs.append(x)
                                ys.append(y)

                elif ot in {"segment", "ray"}:
                    a_id = obj.get("from") or obj.get("start") or obj.get("a")
                    b_id = obj.get("to") or obj.get("end") or obj.get("through") or obj.get("b")
                    for pid in (a_id, b_id):
                        if isinstance(pid, str) and pid in pt:
                            x, y = pt[pid]
                            xs.append(x)
                            ys.append(y)

                elif ot == "text":
                    saw_text_or_label = True
                    tx = safe_float(obj.get("x"))
                    ty = safe_float(obj.get("y"))
                    if tx is not None and ty is not None:
                        xs.append(tx)
                        ys.append(ty)

                elif ot == "label":
                    saw_text_or_label = True
                    target = obj.get("target")
                    if isinstance(target, str) and target in pt:
                        x, y = pt[target]
                        xs.append(x)
                        ys.append(y)

                elif ot == "angle_marker":
                    saw_angle_marker = True
                    # angle markers live near the vertex; include the vertex point
                    at_id = obj.get("at")
                    if isinstance(at_id, str) and at_id in pt:
                        x, y = pt[at_id]
                        xs.append(x)
                        ys.append(y)

            continue  # geometry chart handled

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
            try:
                cx = float(vf.get("center", {}).get("x"))
                cy = float(vf.get("center", {}).get("y"))
                r = float(vf.get("radius"))
                if r > 0:
                    saw_circle = True
                    circle_radii.append(float(r))
                    xs.extend([cx - r, cx + r])
                    ys.extend([cy - r, cy + r])
            except Exception:
                try:
                    cx = float(vf.get("center", {}).get("x"))
                    cy = float(vf.get("center", {}).get("y"))
                    px = float(vf.get("point_on_circle", {}).get("x"))
                    py = float(vf.get("point_on_circle", {}).get("y"))
                    r = math.hypot(px - cx, py - cy)
                    if r > 0:
                        saw_circle = True
                        circle_radii.append(float(r))
                        xs.extend([cx - r, cx + r])
                        ys.extend([cy - r, cy + r])
                except Exception:
                    pass

        elif t in {"segment", "ray"}:
            a = vf.get("a") or vf.get("start")
            b = vf.get("b") or vf.get("end")
            for p in (a, b):
                try:
                    xs.append(float(p["x"]))
                    ys.append(float(p["y"]))
                except Exception:
                    pass

        elif t == "arc":
            try:
                cx = float(vf.get("center", {}).get("x"))
                cy = float(vf.get("center", {}).get("y"))
                r = float(vf.get("radius"))
                if r > 0:
                    circle_radii.append(float(r))
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

    dx = max(1e-6, x_max - x_min)
    dy = max(1e-6, y_max - y_min)

    # ------------------------------------------------------------------------
    # PADDING POLICY
    #
    # The “arc cut off” issue is almost always: bounds are tight + equal_aspect
    # + patches/text extend just beyond limits. So:
    #   - Always pad by span * pad_frac
    #   - For circle-ish diagrams (sectors/arcs/segments), add an extra absolute margin
    #     proportional to the largest radius.
    #   - If we saw angle markers / labels, add a bit more.
    # ------------------------------------------------------------------------
    span = max(dx, dy)
    pad = span * float(pad_frac)

    extra = 0.0
    if circle_radii:
        extra += 0.12 * float(max(circle_radii))  # generous; still looks fine
    if saw_angle_marker:
        extra += 0.08 * span
    if saw_text_or_label:
        extra += 0.05 * span

    pad = pad + extra

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

    # If circle-ish object exists, force square viewport around overall content.
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

    return {
        "x_min": x_min - pad,
        "x_max": x_max + pad,
        "y_min": y_min - pad,
        "y_max": y_max + pad,
    }


def _toggle360(t1: float, t2: float) -> float:
    """
    Internal helper for segment angle flipping.
    We want to return a positive amount to add so that the swapped span is correct.
    """
    # In practice normalize_arc_angles already ensured t2 >= t1. When we swap
    # (t1,t2) -> (t2, t1+360), we just need +360.
    return 360.0


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