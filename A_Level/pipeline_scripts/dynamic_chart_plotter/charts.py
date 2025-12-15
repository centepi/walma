"""
charts.py — Chart-specific plotting functions

This file contains ONLY the chart/table plotting implementations plus
related per-chart helpers (visual features, labeled points, shaded regions).

It intentionally does NOT include:
- dynamic_chart_plotter()
- layout creation
- dispatcher

Those live in plotter.py.

General utilities live in utils.py.
"""

import matplotlib.pyplot as plt
import numpy as np
from typing import Dict, List, Any, Optional, Callable, Tuple

from .utils import (
    evaluate_function,
    get_color_cycle,
    _coerce_bin_pair,
    get_bound_values,
    get_table_colors,
    clean_table_text,
)


# ============================================================================
# TABLE
# ============================================================================

def plot_table(ax: plt.Axes, table_config: Dict[str, Any]) -> None:
    """
    Plot a table using matplotlib's table functionality.
    """
    visual_features = table_config.get('visual_features', {}) or {}
    headers = visual_features.get('headers', []) or []
    rows = visual_features.get('rows', []) or []
    table_style = visual_features.get('table_style', 'standard')
    label = table_config.get('label', '')

    # Validate table data
    if not rows:
        print(f"⚠️ No rows found in table '{table_config.get('id', 'unknown')}'")
        return

    cleaned_headers = [clean_table_text(h) for h in headers] if headers else []
    cleaned_rows: List[List[str]] = []
    for row in rows:
        cleaned_row = [clean_table_text(cell) for cell in row]
        cleaned_rows.append(cleaned_row)

    # Prepare table data with cleaned text
    if cleaned_headers:
        table_data = [cleaned_headers] + cleaned_rows
        num_table_rows = len(cleaned_rows) + 1
        has_header = True
    else:
        table_data = cleaned_rows
        num_table_rows = len(cleaned_rows)
        has_header = False

    # Determine expected column count (use row width when no headers)
    expected_cols = len(cleaned_headers) if cleaned_headers else (
        len(cleaned_rows[0]) if cleaned_rows and len(cleaned_rows[0]) > 0 else 0
    )
    if expected_cols <= 0:
        print(f"⚠️ Could not determine column count for table '{table_config.get('id', 'unknown')}'")
        return

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

    if 'visual_features' in graph and 'axes_range' in (graph.get('visual_features') or {}):
        axes_range = graph['visual_features']['axes_range']
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

    x_param = evaluate_function(param_funcs['x'], t_vals)
    y_param = evaluate_function(param_funcs['y'], t_vals)

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
    graph_id = graph.get('id', 'unknown')
    label = graph.get('label', '')
    color = get_color_cycle(graph_id)

    visual_features = graph.get('visual_features', {}) or {}
    raw_bins = visual_features.get('bins', [])
    frequencies = visual_features.get('frequencies', [])

    if len(raw_bins) != len(frequencies):
        print(f"⚠️ Bin and frequency count mismatch in histogram '{graph_id}'")
        return
    if not raw_bins:
        print(f"⚠️ No bins found in histogram '{graph_id}'")
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
        frequencies,
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