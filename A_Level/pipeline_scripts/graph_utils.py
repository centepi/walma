import numpy as np
import sympy as sp
import re
import traceback
from . import utils

logger = utils.setup_logger(__name__)


def generate_sampled_points(explicit_function: str, axes_range: dict, critical_x_values: list = None, num_points: int = 50):
    """
    Generates sampled (x, y) pairs, ensuring critical x-values are included for precision.
    """
    x_min = axes_range.get("x_min", -2)
    x_max = axes_range.get("x_max", 2)

    # Base evenly spaced points
    base_x_values = np.linspace(x_min, x_max, num_points)

    # Add critical x-values (turning points, intercepts, region edges) within range
    all_x_values = set(base_x_values)
    if critical_x_values:
        for x_val in critical_x_values:
            if x_val is not None and x_min <= x_val <= x_max:
                all_x_values.add(x_val)

    # Sort to draw the curve correctly
    sorted_x_values = sorted(list(all_x_values))

    sampled_points = []

    # Normalize RHS (allow "f(x) = ..." or "y = ...")
    rhs = (explicit_function or "").strip()
    match_f_x = re.search(r"^[a-zA-Z]\(x\)\s*=\s*(.+)", rhs)
    match_y = re.search(r"^[yY]\s*=\s*(.+)", rhs)
    if match_f_x:
        rhs = match_f_x.group(1).strip()
    elif match_y:
        rhs = match_y.group(1).strip()

    # Make expression Python/SymPy friendly
    rhs = re.sub(r'(\d)([a-zA-Z])', r'\1*\2', rhs)  # 2x -> 2*x
    rhs = rhs.replace('^', '**')
    x_sym = sp.Symbol('x')

    # Preferred: SymPy evaluation
    try:
        expr = sp.sympify(rhs)
        for val in sorted_x_values:
            y = expr.subs(x_sym, val)
            if y.is_real:
                sampled_points.append({"x": float(val), "y": float(y.evalf())})
        logger.debug("Graph: sampled %d pts with SymPy for '%s'", len(sampled_points), utils.truncate(explicit_function, 80))
        return sampled_points
    except Exception as e:
        logger.warning("Graph: SymPy failed for '%s' — %s. Falling back to eval.", utils.truncate(rhs, 80), utils.truncate(str(e), 120))

    # Fallback: restricted eval (simple expressions)
    try:
        if "=" in rhs:
            logger.error("Graph: eval fallback cannot parse function string containing '=': '%s'", utils.truncate(rhs, 120))
            return []

        fallback_points = []
        for val in sorted_x_values:
            local_vars = {"x": val}
            y = eval(rhs, {"__builtins__": {}}, local_vars)  # no builtins for safety
            fallback_points.append({"x": float(val), "y": float(y)})
        logger.debug("Graph: sampled %d pts with eval fallback for '%s'", len(fallback_points), utils.truncate(explicit_function, 80))
        return fallback_points
    except Exception as e:
        logger.error("Graph: eval fallback failed for '%s' — %s", utils.truncate(rhs, 120), utils.truncate(str(e), 160))
        logger.debug("Graph: eval traceback:\n%s", traceback.format_exc())
        return []


def calculate_combined_axes_range_from_points(graphs: list, margin: float = 0.05) -> dict:
    """
    Calculate a single combined axes_range that includes ALL sampled points,
    intercepts, and turning points for multiple graphs.
    """
    all_x = []
    all_y = []
    sampled_x = []

    for graph in graphs or []:
        features = graph.get("visual_features", {})
        if not isinstance(features, dict):
            continue

        # x-intercepts
        all_x.extend(x for x in (features.get("x_intercepts") or []) if isinstance(x, (int, float)))

        # y-intercept implies x=0
        if isinstance(features.get("y_intercept"), (int, float)):
            all_x.append(0)
            all_y.append(features.get("y_intercept"))

        # turning points
        for tp in features.get("turning_points") or []:
            if isinstance(tp, dict):
                all_x.append(tp.get("x"))
                all_y.append(tp.get("y"))

        # sampled points
        for pt in features.get("sampled_points") or []:
            if isinstance(pt, dict):
                all_x.append(pt.get("x"))
                all_y.append(pt.get("y"))
                sampled_x.append(pt.get("x"))

    # Filter invalids
    all_x = [v for v in all_x if isinstance(v, (int, float))]
    all_y = [v for v in all_y if isinstance(v, (int, float))]
    sampled_x = [v for v in sampled_x if isinstance(v, (int, float))]

    if not all_x or not all_y:
        return {"x_min": -2.0, "x_max": 2.0, "y_min": -2.0, "y_max": 2.0}

    x_min, x_max = (min(sampled_x), max(sampled_x)) if sampled_x else (min(all_x), max(all_x))
    y_min, y_max = min(all_y), max(all_y)

    x_margin = (x_max - x_min) * 0.02 or 0.1
    y_margin = (y_max - y_min) * margin or 0.5

    if x_min == x_max:
        x_min -= 0.5
        x_max += 0.5
    if y_min == y_max:
        y_min -= 0.5
        y_max += 0.5

    return {
        "x_min": round(x_min - x_margin, 3),
        "x_max": round(x_max + x_margin, 3),
        "y_min": round(y_min - y_margin, 3),
        "y_max": round(y_max + y_margin, 3),
    }


def process_and_sample_visual_data(visual_data: dict):
    """
    Main function to process a visual_data object. Gathers all critical points
    and ensures each graph's sampled points are precise.
    """
    if not visual_data or not isinstance(visual_data, dict):
        return

    global_critical_x = set()
    for region in visual_data.get("shaded_regions", []):
        global_critical_x.add(region.get("x_start"))
        global_critical_x.add(region.get("x_end"))
    for point in visual_data.get("labeled_points", []):
        global_critical_x.add(point.get("x"))

    for graph in visual_data.get("graphs", []):
        features = graph.get("visual_features", {})
        if not isinstance(features, dict):
            continue

        local_critical_x = set()
        for x_int in features.get("x_intercepts") or []:
            local_critical_x.add(x_int)
        for tp in features.get("turning_points") or []:
            local_critical_x.add(tp.get("x"))

        combined_critical_x = list(filter(None, global_critical_x.union(local_critical_x)))

        func = graph.get("explicit_function")
        axes_range = features.get("axes_range")
        if func and axes_range:
            points = generate_sampled_points(func, axes_range, combined_critical_x)
            features["sampled_points"] = points
            logger.debug("Graph: generated %d precise points for '%s'", len(points), utils.truncate(func, 80))
        else:
            # Demoted to DEBUG: not a failure, just no sampling needed/possible
            logger.debug("Graph: skipping sampling for graph %s (missing function or axes_range).", graph.get("id"))
