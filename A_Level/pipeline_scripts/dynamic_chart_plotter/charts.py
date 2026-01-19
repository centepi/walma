"""
charts.py — Chart/table plotting implementations (renderers only)

This file contains ONLY:
- chart/table plotting implementations (function/parametric/scatter/bar/histogram/box/cumulative/table)
- per-chart local parsing helpers (table row normalization)

It intentionally does NOT include:
- dynamic_chart_plotter()
- layout creation
- dispatcher
- overlays/annotations (labeled points, shaded regions, visual features)
- geometry primitives (polygon, etc.)

Those live in:
- plotter.py   (controller/orchestrator/dispatcher)
- overlays.py  (annotations + shaded regions + simple geometry)

General utilities live in utils.py.
"""

import matplotlib.pyplot as plt
import numpy as np
from typing import Dict, List, Any, Optional, Callable, Tuple

from .utils import (
    evaluate_function,
    get_color_cycle,
    _coerce_bin_pair,
    get_table_colors,
    clean_table_text,
)

from .overlays import add_visual_features


# ============================================================================
# TABLE
# ============================================================================

def plot_table(ax: plt.Axes, table_config: Dict[str, Any]) -> None:
    """
    Plot a table using matplotlib's table functionality.

    Robust to Firestore-sanitized row formats, e.g.:
      - rows: [["a", "b"], ["c", "d"]] (ideal)
      - rows: [{"0": "a", "1": "b"}, {"0": "c", "1": "d"}]
      - rows: [{"0": "['a','b']"}, {"0": "['c','d']"}]  (stringified list inside a dict)
      - rows: ["['a','b']", "['c','d']"]                (stringified list)
    """
    import json
    import ast

    def _parse_stringified_list(s: str) -> Optional[List[Any]]:
        ss = str(s).strip()
        if not ss:
            return None
        # Try JSON first
        try:
            parsed = json.loads(ss)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
        # Then Python literal list like "['a', 'b']"
        try:
            parsed = ast.literal_eval(ss)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
        return None

    def _row_to_list(row: Any) -> Optional[List[Any]]:
        # Already a list/tuple row
        if isinstance(row, (list, tuple)):
            return list(row)

        # A dict row: try to interpret as {colIndex: value, ...}
        if isinstance(row, dict):
            # If it looks like a single wrapped stringified list, unwrap it.
            if len(row) == 1:
                only_val = next(iter(row.values()))
                if isinstance(only_val, str):
                    parsed = _parse_stringified_list(only_val)
                    if parsed is not None:
                        return parsed
                # Or a single nested list
                if isinstance(only_val, (list, tuple)):
                    return list(only_val)

            # Otherwise: sort keys numerically when possible
            items = []
            for k, v in row.items():
                # keys might be "0", 0, "1" etc.
                try:
                    kk = int(k)
                except Exception:
                    kk = k
                items.append((kk, v))

           # Prefer numeric sort if most keys are ints
            # Prefer numeric sort if most keys are ints
            try:
                items_sorted = sorted(items, key=lambda kv: (isinstance(kv[0], str), kv[0]))
            except Exception:
                items_sorted = items

            return [v for _, v in items_sorted]

        # A bare string row that might be "['a','b']"
        if isinstance(row, str):
            parsed = _parse_stringified_list(row)
            if parsed is not None:
                return parsed

        return None

    visual_features = table_config.get('visual_features', {}) or {}
    headers = visual_features.get('headers', []) or []
    raw_rows = visual_features.get('rows', []) or []
    table_style = visual_features.get('table_style', 'standard')
    label = table_config.get('label', '')

    # Validate table data
    if not raw_rows:
        print(f"⚠️ No rows found in table '{table_config.get('id', 'unknown')}'")
        return

    cleaned_headers = [clean_table_text(h) for h in headers] if headers else []

    # Normalize rows into a clean List[List[str]]
    normalized_rows: List[List[str]] = []
    for r in raw_rows:
        row_list = _row_to_list(r)
        if row_list is None:
            # Last-ditch: accept single cell row
            row_list = [r]
        cleaned = [clean_table_text(cell) for cell in row_list]
        normalized_rows.append(cleaned)

    # Determine expected column count
    expected_cols = len(cleaned_headers) if cleaned_headers else (
        len(normalized_rows[0]) if normalized_rows and len(normalized_rows[0]) > 0 else 0
    )
    if expected_cols <= 0:
        print(f"⚠️ Could not determine column count for table '{table_config.get('id', 'unknown')}'")
        return

    # Pad / truncate rows to expected_cols (keeps Matplotlib table stable)
    fixed_rows: List[List[str]] = []
    for row in normalized_rows:
        if len(row) < expected_cols:
            row = row + [""] * (expected_cols - len(row))
        elif len(row) > expected_cols:
            row = row[:expected_cols]
        fixed_rows.append(row)

    # Prepare table data with cleaned text
    if cleaned_headers:
        table_data = [cleaned_headers] + fixed_rows
        num_table_rows = len(fixed_rows) + 1
        has_header = True
    else:
        table_data = fixed_rows
        num_table_rows = len(fixed_rows)
        has_header = False

    # Generate colors with correct column count
    cell_colors = get_table_colors(num_table_rows, expected_cols, table_style, has_header=has_header)

    # Turn off axis
    ax.axis('off')
    ax.axis('tight')

    # Create the table
    mpl_table = ax.table(
        cellText=table_data,
        cellLoc='center',
        loc='center',
        cellColours=cell_colors,
        colWidths=[1.0 / expected_cols] * expected_cols
    )

    # Style the table
    mpl_table.auto_set_font_size(False)
    mpl_table.set_fontsize(10)
    mpl_table.scale(1, 2)  # Scale row height for readability

    # Apply header styling if present
    if cleaned_headers:
        for i in range(expected_cols):
            cell = mpl_table[(0, i)]
            cell.set_text_props(weight='bold', size=11, color='white')
            cell.set_facecolor('#4472C4')
            cell.set_edgecolor('black')
            cell.set_linewidth(1.5)

    # Apply border styling to all cells
    for _, cell in mpl_table.get_celld().items():
        cell.set_edgecolor('black')
        cell.set_linewidth(0.5 if table_style == 'minimal' else 1)

    # Add label/title if present
    if label:
        ax.set_title(label, fontsize=12, fontweight='bold', pad=10)


# ============================================================================
# CURVES / FUNCTIONS
# ============================================================================

def plot_explicit_function(
    ax: plt.Axes,
    graph: Dict[str, Any],
    function_registry: Dict[str, Optional[Callable]]
) -> None:
    graph_id = graph.get('id', 'unknown')
    label = graph.get('label', '')

    x_min, x_max = ax.get_xlim()

    # If limits are still Matplotlib defaults (0..1), fall back to any
    # per-graph axes_range, then to (-10, 10).
    if x_min == 0.0 and x_max == 1.0:
        vf = graph.get('visual_features', {}) or {}
        axes_range = vf.get('axes_range') if isinstance(vf.get('axes_range'), dict) else None
        if axes_range:
            x_min = axes_range.get('x_min', -10)
            x_max = axes_range.get('x_max', 10)
        else:
            x_min, x_max = -10, 10

    x_vals = np.linspace(x_min, x_max, 1000)
    func_str = graph['explicit_function']

    # Store safe callable for later use (e.g. shaded regions)
    create_safe_function = lambda s: (lambda x: evaluate_function(s, x))
    function_registry[graph_id] = create_safe_function(func_str)

    y_vals = evaluate_function(func_str, x_vals)

    visual_features = graph.get('visual_features', {}) or {}
    show_label = bool(visual_features.get('show_label', False))
    safe_label = label if show_label else ""

    ax.plot(
        x_vals,
        y_vals,
        label=safe_label,
        linewidth=2.5,
        color=get_color_cycle(graph_id),
    )

    if bool(visual_features.get('render_features', False)):
        add_visual_features(ax, visual_features, x_vals, y_vals)


def plot_parametric_curve(
    ax: plt.Axes,
    graph: Dict[str, Any],
    function_registry: Dict[str, Optional[Callable]]
) -> None:
    graph_id = graph.get('id', 'unknown')
    label = graph.get('label', '')

    param_funcs = graph['parametric_function']
    t_range = graph.get('parameter_range', {'t_min': 0, 't_max': 2 * np.pi})
    t_vals = np.linspace(t_range['t_min'], t_range['t_max'], 1000)

    # IMPORTANT:
    # Parametric functions are defined in terms of 't' (not 'x').
    x_param = evaluate_function(param_funcs['x'], t_vals, var_name="t")
    y_param = evaluate_function(param_funcs['y'], t_vals, var_name="t")

    # No explicit callable stored (not used by shaded regions currently)
    function_registry[graph_id] = None

    visual_features = graph.get('visual_features', {}) or {}
    show_label = bool(visual_features.get('show_label', False))
    safe_label = label if show_label else ""

    ax.plot(
        x_param,
        y_param,
        label=safe_label,
        linewidth=2.5,
        color=get_color_cycle(graph_id),
    )


# ============================================================================
# DATA PLOTS
# ============================================================================

def plot_scatter(
    ax: plt.Axes,
    graph: Dict[str, Any],
    function_registry: Dict[str, Optional[Callable]]
) -> None:
    graph_id = graph.get('id', 'unknown')
    label = graph.get('label', '')
    color = get_color_cycle(graph_id)

    visual_features = graph.get('visual_features', {}) or {}
    data_points = visual_features.get('data_points', [])

    if not data_points:
        print(f"⚠️ No data points found in scatter plot '{graph_id}'")
        return

    x_data = np.array([point['x'] for point in data_points])
    y_data = np.array([point['y'] for point in data_points])

    show_label = bool(visual_features.get('show_label', False))
    safe_label = label if show_label else ""

    ax.scatter(x_data, y_data, label=safe_label, s=100, alpha=0.7, color=color, zorder=5)

    trend_line = visual_features.get('trend_line', {}) or {}
    if trend_line.get('enabled', False) and bool(trend_line.get('reveal', False)):
        trend_eq = str(trend_line.get('equation', '')).strip()
        if trend_eq:
            rhs = trend_eq.split('=', 1)[1].strip() if '=' in trend_eq else trend_eq
            x_trend = np.linspace(float(x_data.min()), float(x_data.max()), 100)
            y_trend = evaluate_function(rhs, x_trend)

            show_trend_label = bool(trend_line.get('show_label', False))
            trend_label = (trend_line.get('label') or 'Trend line') if show_trend_label else ""

            ax.plot(x_trend, y_trend, '--', color=color, alpha=0.6, linewidth=2, label=trend_label)

    function_registry[graph_id] = None


def plot_bar_chart(
    ax: plt.Axes,
    graph: Dict[str, Any],
    function_registry: Dict[str, Optional[Callable]]
) -> None:
    graph_id = graph.get('id', 'unknown')
    label = graph.get('label', '')
    color = get_color_cycle(graph_id)

    visual_features = graph.get('visual_features', {}) or {}
    categories = visual_features.get('categories', [])
    values = visual_features.get('values', [])

    if len(categories) != len(values):
        print(f"⚠️ Category and value count mismatch in bar chart '{graph_id}'")
        return
    if not categories:
        print(f"⚠️ No categories found in bar chart '{graph_id}'")
        return

    show_label = bool(visual_features.get('show_label', False))
    safe_label = label if show_label else ""

    x_pos = np.arange(len(categories))
    ax.bar(
        x_pos,
        values,
        label=safe_label,
        alpha=0.7,
        color=color,
        edgecolor='black',
        linewidth=1.5
    )

    ax.set_xticks(x_pos)
    ax.set_xticklabels(categories, rotation=0)

    function_registry[graph_id] = None


def plot_histogram(
    ax: plt.Axes,
    graph: Dict[str, Any],
    function_registry: Dict[str, Optional[Callable]]
) -> None:
    """
    Histogram rendering (pedagogy-safe):

    We plot bar HEIGHTS in "Frequency Density (units)" (i.e. the y-axis units
    shown to the student), NOT raw frequencies (student counts).

    Required visual_features keys:
      - bins: list of [lo, hi] pairs (or Firestore-sanitized strings)
      - heights: list of bar heights in "units" (same length as bins)

    Accepted alias for heights:
      - frequency_density_units

    We intentionally DO NOT plot visual_features["frequencies"] because that
    can both (a) break the chart scale and (b) give away answers.
    """
    graph_id = graph.get('id', 'unknown')
    label = graph.get('label', '')
    color = get_color_cycle(graph_id)

    visual_features = graph.get('visual_features', {}) or {}
    raw_bins = visual_features.get('bins', [])

    # Heights in "units" (what the histogram axis shows)
    heights = visual_features.get('heights', None)
    if heights is None:
        heights = visual_features.get('frequency_density_units', None)
    heights = heights or []

    if not raw_bins:
        print(f"⚠️ No bins found in histogram '{graph_id}'")
        return

    if not heights:
        print(
            f"⚠️ Histogram '{graph_id}' missing 'heights' (frequency density units). "
            f"Refusing to plot to avoid incorrect/answer-leaking render."
        )
        return

    if len(raw_bins) != len(heights):
        print(f"⚠️ Bin and height count mismatch in histogram '{graph_id}'")
        return

    # Accept bins even if Firestore-sanitized into strings like "[0, 5]"
    bins: List[Tuple[float, float]] = []
    for b in raw_bins:
        pair = _coerce_bin_pair(b)
        if pair is None:
            print(f"⚠️ Unparseable bin in histogram '{graph_id}': {b!r}")
            return
        lo, hi = pair
        bins.append((lo, hi))

    show_label = bool(visual_features.get('show_label', False))
    safe_label = label if show_label else ""

    bin_centers = np.array([(lo + hi) / 2 for (lo, hi) in bins], dtype=float)
    bin_widths = np.array([(hi - lo) for (lo, hi) in bins], dtype=float)

    ax.bar(
        bin_centers,
        heights,
        width=bin_widths,
        align='center',
        label=safe_label,
        alpha=0.7,
        color=color,
        edgecolor='black',
        linewidth=1.5
    )

    # Make x-axis readable: place ticks at bin boundaries.
    try:
        edges: List[float] = []
        for (lo, hi) in bins:
            edges.extend([lo, hi])
        edges = sorted(set(edges))
        if edges:
            ax.set_xticks(edges)
    except Exception:
        pass

    function_registry[graph_id] = None


def plot_box_plot(
    ax: plt.Axes,
    graph: Dict[str, Any],
    function_registry: Dict[str, Optional[Callable]]
) -> None:
    graph_id = graph.get('id', 'unknown')
    label = graph.get('label', '')
    color = get_color_cycle(graph_id)

    visual_features = graph.get('visual_features', {}) or {}
    groups = visual_features.get('groups', ['Data'])
    min_vals = visual_features.get('min_values', [])
    q1_vals = visual_features.get('q1_values', [])
    median_vals = visual_features.get('median_values', [])
    q3_vals = visual_features.get('q3_values', [])
    max_vals = visual_features.get('max_values', [])
    outliers = visual_features.get('outliers', [])

    n_groups = len(groups)
    if not all(len(v) == n_groups for v in [min_vals, q1_vals, median_vals, q3_vals, max_vals]):
        print(f"⚠️ Data length mismatch in box plot '{graph_id}'")
        return

    stats = []
    for i in range(n_groups):
        q1, med, q3 = q1_vals[i], median_vals[i], q3_vals[i]
        iqr = q3 - q1

        # NOTE: do NOT clamp whiskers; boxplots can be negative.
        whisker_low = min_vals[i] if min_vals[i] is not None else (q1 - 1.5 * iqr)
        whisker_high = max_vals[i] if max_vals[i] is not None else (q3 + 1.5 * iqr)

        stats.append({
            'label': groups[i],
            'whislo': whisker_low,
            'q1': q1,
            'med': med,
            'q3': q3,
            'whishi': whisker_high,
            'fliers': [o['value'] for o in outliers if o.get('group') == groups[i]],
        })

    bp = ax.bxp(stats, patch_artist=True, widths=0.6)
    for patch in bp['boxes']:
        patch.set_facecolor(color)
        patch.set_alpha(0.7)

    show_label = bool(visual_features.get('show_label', False))
    safe_label = label if show_label else ""
    ax.set_title(safe_label)

    if outliers and bool(visual_features.get('render_outliers', False)):
        for outlier in outliers:
            group_idx = groups.index(outlier.get('group', groups[0]))
            ax.scatter(
                group_idx + 1,
                outlier['value'],
                color='red',
                s=100,
                marker='o',
                zorder=5,
                label='Outliers' if outlier == outliers[0] else ''
            )

    function_registry[graph_id] = None


def plot_cumulative_frequency(
    ax: plt.Axes,
    graph: Dict[str, Any],
    function_registry: Dict[str, Optional[Callable]]
) -> None:
    graph_id = graph.get('id', 'unknown')
    label = graph.get('label', '')
    color = get_color_cycle(graph_id)

    visual_features = graph.get('visual_features', {}) or {}
    boundaries = visual_features.get('upper_class_boundaries', [])
    cum_frequencies = visual_features.get('cumulative_frequencies', [])

    if len(boundaries) != len(cum_frequencies):
        print(f"⚠️ Boundary and cumulative frequency count mismatch in CF curve '{graph_id}'")
        return
    if not boundaries:
        print(f"⚠️ No class boundaries found in cumulative frequency plot '{graph_id}'")
        return

    show_label = bool(visual_features.get('show_label', False))
    safe_label = label if show_label else ""

    x_vals = np.array([0] + list(boundaries))
    y_vals = np.array([0] + list(cum_frequencies))

    ax.plot(
        x_vals,
        y_vals,
        marker='o',
        linewidth=2.5,
        markersize=6,
        label=safe_label,
        color=color,
        alpha=0.7
    )

    function_registry[graph_id] = None