"""
geometry_common.py — Shared geometry helpers for dynamic_chart_plotter

This file contains ONLY:
- small, dependency-light geometry helpers shared by:
  - geometry_renderer.py (drawing)
  - geometry_bounds.py   (bounds)

Keep this file free of imports from other project modules to avoid cycles.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
import math


# ============================================================================
# BASIC COERCION
# ============================================================================

def safe_float(x: Any) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


def line_style_to_matplotlib(line_style: Any) -> str:
    s = str(line_style or "").strip().lower()
    if s in {"dashed", "dash", "--"}:
        return "--"
    if s in {"dotted", "dot", ":"}:
        return ":"
    if s in {"dashdot", "-."}:
        return "-."
    return "-"  # default


# ============================================================================
# LABEL ID HEURISTICS (for auto-label fallback)
# ============================================================================

def looks_like_label_id(s: Any) -> bool:
    """
    Heuristic: does this point id look like a label we should auto-render?

    We only want to auto-label typical geometry point names like:
      A, B, C, O, P, Q, R, T, X, Y, Z
    and (optionally) short variants like A1, B2.

    We avoid auto-labeling:
      - long ids (e.g. "point_12", "vertex_left")
      - purely numeric ids
      - empty/None
    """
    if not isinstance(s, str):
        return False
    t = s.strip()
    if not t:
        return False

    # Too long -> probably not a "point label"
    if len(t) > 3:
        return False

    # Common: single uppercase letter
    if len(t) == 1 and t.isalpha() and t.upper() == t:
        return True

    # Common: A1, B2, etc.
    if len(t) == 2 and t[0].isalpha() and t[0].upper() == t[0] and t[1].isdigit():
        return True

    # Allow 3-char like A10 only if it’s letter + 2 digits
    if len(t) == 3 and t[0].isalpha() and t[0].upper() == t[0] and t[1:].isdigit():
        return True

    return False


# ============================================================================
# ANGLES / ARCS
# ============================================================================

def normalize_arc_angles(theta1: float, theta2: float) -> Tuple[float, float]:
    """
    Ensure theta2 >= theta1 by adding 360 if needed.
    Angles are degrees in Matplotlib conventions.
    """
    t1 = float(theta1)
    t2 = float(theta2)
    while t2 < t1:
        t2 += 360.0
    return t1, t2


def normalize_wedge_angles(theta1: float, theta2: float) -> Tuple[float, float]:
    """
    Matplotlib's Wedge/Arc can be flaky when:
      - the sweep is ~0 (theta1 ~= theta2), or
      - the sweep is >= 360, or
      - angles land on exact boundaries with floating noise.

    We keep angles in a "safe" form:
      - ensure theta2 >= theta1 (like normalize_arc_angles)
      - clamp sweep to < 360 (keep it drawable as a single wedge)
      - avoid exact 0 sweep by nudging by a tiny epsilon
    """
    t1, t2 = normalize_arc_angles(theta1, theta2)

    sweep = float(t2) - float(t1)

    # If someone accidentally asked for a full circle or more, clamp to just-under 360.
    if sweep >= 360.0:
        t2 = t1 + 359.999

    # If sweep is (effectively) zero, nudge to a tiny visible arc.
    if abs(float(t2) - float(t1)) < 1e-9:
        t2 = t1 + 1e-3

    return float(t1), float(t2)


def angle_deg(center: Tuple[float, float], pt: Tuple[float, float]) -> float:
    """Angle (deg) of pt relative to center."""
    cx, cy = center
    x, y = pt
    return math.degrees(math.atan2(y - cy, x - cx))


def angle_from_points(center_xy: Tuple[float, float], pt_xy: Tuple[float, float]) -> float:
    """
    Backwards-compatible alias used by geometry_renderer.py.

    Returns the Matplotlib-style polar angle (degrees) from center_xy to pt_xy.
    """
    return angle_deg(center_xy, pt_xy)


# ============================================================================
# SEMICIRCLE
# ============================================================================

def semicircle_from_diameter(
    a: Tuple[float, float],
    b: Tuple[float, float],
    side: str = "left",
) -> Tuple[Tuple[float, float], float, float, float]:
    """
    Build semicircle arc params (center, radius, theta1_deg, theta2_deg)
    from diameter endpoints a,b.

    - center: midpoint of AB
    - radius: |AB|/2
    - side:
        "left"  => take the semicircle to the LEFT of the directed segment A->B (CCW sweep)
        "right" => take the semicircle to the RIGHT of the directed segment A->B (the other half)
    """
    (x1, y1) = a
    (x2, y2) = b
    cx = 0.5 * (x1 + x2)
    cy = 0.5 * (y1 + y2)
    r = 0.5 * math.hypot(x2 - x1, y2 - y1)
    if r <= 0:
        return (cx, cy), 0.0, 0.0, 0.0

    ang1 = math.degrees(math.atan2(y1 - cy, x1 - cx))
    ang2 = math.degrees(math.atan2(y2 - cy, x2 - cx))

    s = str(side or "left").strip().lower()
    if s in {"right", "cw", "clockwise"}:
        theta1 = ang2
        theta2 = ang2 + 180.0
    else:
        theta1 = ang1
        theta2 = ang1 + 180.0

    theta1, theta2 = normalize_arc_angles(theta1, theta2)
    return (cx, cy), r, theta1, theta2


# ============================================================================
# SECTOR ANGLES (shared: renderer + bounds)
# ============================================================================

def resolve_sector_angles(
    center_xy: Tuple[float, float],
    points: Dict[str, Tuple[float, float]],
    obj: Dict[str, Any],
) -> Optional[Tuple[float, float]]:
    """
    Resolve a sector-like angle span.

    Accepted schemas:
      - theta1_deg/theta2_deg (floats)
      - from/to point ids (or start/end ids) relative to center
        { "from":"A", "to":"B" }  (or "start"/"end")
    """
    th1 = safe_float(obj.get("theta1_deg"))
    th2 = safe_float(obj.get("theta2_deg"))
    if th1 is not None and th2 is not None:
        # ✅ use wedge-safe normalization (fixes rare missing arc edge)
        return normalize_wedge_angles(th1, th2)

    a_id = obj.get("from", obj.get("start"))
    b_id = obj.get("to", obj.get("end"))
    if isinstance(a_id, str) and isinstance(b_id, str) and a_id in points and b_id in points:
        th1 = angle_deg(center_xy, points[a_id])
        th2 = angle_deg(center_xy, points[b_id])
        # ✅ use wedge-safe normalization (fixes rare missing arc edge)
        return normalize_wedge_angles(th1, th2)

    return None