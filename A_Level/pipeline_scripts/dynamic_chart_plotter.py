"""
Dynamic Chart Plotter - Enhanced Python Module
================================================

A flexible, production-ready function that generates various types of mathematical
charts and graphs based on JSON configuration input aligned with the enhanced
prompt for A-level Mathematics.

Supports:
  • Explicit mathematical functions (y = f(x))
  • Parametric curves (x = f(t), y = g(t))
  • Histograms with bins and frequencies
  • Bar charts with categories
  • Scatter plots with optional trend lines
  • Box plots with five-number summaries
  • Cumulative frequency curves
  • Labeled point annotations
  • Shaded regions between curves
  • Customizable axes, grid, and styling

Author: AI Engineering
Date: 2025-11-07
License: MIT
"""

import matplotlib.pyplot as plt
import numpy as np
import json
from typing import Dict, List, Any, Optional, Callable, Tuple, Union
import warnings

warnings.filterwarnings('ignore')


# ============================================================================
# MAIN DYNAMIC CHART PLOTTER FUNCTION
# ============================================================================

def dynamic_chart_plotter(config: Dict[str, Any]) -> plt.Figure:
    """
    Dynamic function to plot various charts and graphs based on JSON configuration.
    """
    # Validate input
    if not isinstance(config, dict):
        raise TypeError("Config must be a dictionary")

    # Support both 'charts' (new) and 'graphs' (legacy) keys
    charts = config.get('charts', config.get('graphs', []))
    if charts is None:
        charts = []
    if not isinstance(charts, list):
        raise TypeError("'charts'/'graphs' must be a list of chart objects")

    # Determine layout type
    layout_mode = config.get('layout', 'single')

    # Check for tables and their positioning
    tables = [c for c in charts if isinstance(c, dict) and str(c.get('type', '')).strip().lower() == 'table']
    non_tables = [c for c in charts if isinstance(c, dict) and str(c.get('type', '')).strip().lower() != 'table']

    # ------------------------------------------------------------------------
    # USABILITY DEFAULTS (so visuals actually help)
    #
    # 1) For data-reading charts (hist/bar/scatter/cumulative/box), axis numbers
    #    MUST be shown, otherwise the chart is useless.
    #
    #    IMPORTANT: do NOT use setdefault here, because configs coming from the
    #    model/pipeline often include show_axis_numbers=False implicitly, which
    #    would permanently suppress ticks. We override to True when needed.
    #
    # 2) If multiple curves are drawn on one axes (e.g., two functions),
    #    curve labels must be enabled so the diagram can be referenced meaningfully.
    #
    # 3) If the caller didn't provide a global axes_range, but the first chart has
    #    visual_features.axes_range, promote it so setup_plot_appearance() can apply it.
    # ------------------------------------------------------------------------
    try:
        chart_types = [
            str(c.get("type", "")).strip().lower()
            for c in non_tables
            if isinstance(c, dict)
        ]

        data_reading_types = {"histogram", "bar", "scatter", "cumulative", "box_plot"}
        if any(t in data_reading_types for t in chart_types):
            # FORCE axis numbers on for data-reading charts (user needs values to answer).
            if config.get("show_axis_numbers") is not True:
                config["show_axis_numbers"] = True

        # Promote a chart-level axes_range to global if none was provided
        if not config.get("global_axes_range") and not config.get("axes_range"):
            for c in non_tables:
                if not isinstance(c, dict):
                    continue
                vf = c.get("visual_features")
                if isinstance(vf, dict) and isinstance(vf.get("axes_range"), dict):
                    config["axes_range"] = vf.get("axes_range")
                    break

        curve_types = {"function", "parametric"}
        curve_charts = [
            c for c in non_tables
            if isinstance(c, dict) and str(c.get("type", "")).strip().lower() in curve_types
        ]
        if len(curve_charts) >= 2:
            used_labels = set()
            for i, c in enumerate(curve_charts, start=1):
                vf = c.get("visual_features")
                if not isinstance(vf, dict):
                    vf = {}
                    c["visual_features"] = vf

                vf.setdefault("show_label", True)

                # Ensure each curve has a usable, non-empty, unique label.
                existing_label = str(c.get("label", "") or "").strip()
                if not existing_label:
                    existing_label = str(c.get("id", "") or "").strip() or f"g{i}"

                candidate = existing_label
                if candidate in used_labels:
                    candidate = f"{candidate}{i}"
                used_labels.add(candidate)
                c["label"] = candidate
    except Exception:
        # Never crash plotting due to defaulting logic.
        pass

    # Determine subplot configuration
    if layout_mode == 'composite' or tables:
        fig, axes = create_composite_layout(config, tables, non_tables)
    else:
        # Standard single-chart layout
        fig, ax = plt.subplots(figsize=(12, 8))
        axes = {'main': ax}

    # Store function objects for later reference
    # NOTE: some chart types store None (e.g., parametric/scatter), so Optional is required.
    function_registry: Dict[str, Optional[Callable]] = {}

    # Process charts (non-tables)
    if 'main' in axes:
        for chart in non_tables:
            plot_chart(axes['main'], chart, function_registry)

        # Process labeled points
        labeled_points = config.get('labeled_points')
        if isinstance(labeled_points, list):
            for point in labeled_points:
                if isinstance(point, dict):
                    plot_labeled_point(axes['main'], point)

        # Process shaded regions
        shaded_regions = config.get('shaded_regions')
        if isinstance(shaded_regions, list):
            for region in shaded_regions:
                if isinstance(region, dict):
                    plot_shaded_region(axes['main'], region, function_registry)

        # Set up the plot appearance for main chart
        setup_plot_appearance(axes['main'], config)

    # Process tables
    if 'table' in axes:
        for table in tables:
            plot_table(axes['table'], table)

    # Global title if specified (composite only)
    if 'title' in config and layout_mode == 'composite':
        fig.suptitle(config['title'], fontsize=16, fontweight='bold', y=0.98)

    # NOTE: avoid calling plt.tight_layout() here because setup_plot_appearance()
    # already tightens (and composite figures often need the suptitle spacing).
    return fig


def create_composite_layout(config: Dict[str, Any],
                            tables: List[Dict[str, Any]],
                            charts: List[Dict[str, Any]]) -> tuple:
    """
    Create figure with composite layout for charts and tables.
    """
    axes: Dict[str, plt.Axes] = {}

    # Determine positioning
    if not tables:
        # No tables, standard layout
        fig, ax = plt.subplots(figsize=(12, 8))
        axes['main'] = ax
        return fig, axes

    if not charts:
        # Only tables, no charts
        fig, ax = plt.subplots(figsize=(12, 6))
        axes['table'] = ax
        return fig, axes

    # Determine table position from first table
    position = tables[0].get('visual_features', {}).get('position', 'below_chart')

    if position == 'above_chart':
        # Table on top, chart below
        fig, (ax_table, ax_chart) = plt.subplots(
            2, 1, figsize=(12, 10),
            gridspec_kw={'height_ratios': [1, 3]}
        )
        axes['table'] = ax_table
        axes['main'] = ax_chart

    elif position == 'below_chart':
        # Chart on top, table below
        fig, (ax_chart, ax_table) = plt.subplots(
            2, 1, figsize=(12, 10),
            gridspec_kw={'height_ratios': [3, 1]}
        )
        axes['main'] = ax_chart
        axes['table'] = ax_table

    elif position == 'beside_chart':
        # Side-by-side layout
        fig, (ax_chart, ax_table) = plt.subplots(
            1, 2, figsize=(16, 8),
            gridspec_kw={'width_ratios': [2, 1]}
        )
        axes['main'] = ax_chart
        axes['table'] = ax_table

    else:  # 'standalone'
        # Table only
        fig, ax = plt.subplots(figsize=(12, 6))
        axes['table'] = ax

    return fig, axes


# ============================================================================
# MAIN CHART PLOTTING DISPATCHER
# ============================================================================

def plot_chart(ax: plt.Axes, chart: Dict[str, Any],
               function_registry: Dict[str, Optional[Callable]]) -> None:
    """
    Dispatcher function to route chart plotting to appropriate handler.
    """
    chart_type = str(chart.get('type', 'function')).strip().lower()

    if chart_type == 'function':
        plot_explicit_function(ax, chart, function_registry)
    elif chart_type == 'parametric':
        plot_parametric_curve(ax, chart, function_registry)
    elif chart_type == 'scatter':
        plot_scatter(ax, chart, function_registry)
    elif chart_type == 'bar':
        plot_bar_chart(ax, chart, function_registry)
    elif chart_type == 'histogram':
        plot_histogram(ax, chart, function_registry)
    elif chart_type == 'box_plot':
        plot_box_plot(ax, chart, function_registry)
    elif chart_type == 'cumulative':
        plot_cumulative_frequency(ax, chart, function_registry)
    elif chart_type == 'table':
        # Tables are handled separately in layout logic
        pass
    else:
        raise ValueError(f"Unsupported chart type: {chart_type}")


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
    cleaned_rows = []
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


def get_table_colors(num_rows: int, num_cols: int, style: str,
                     has_header: bool = False) -> List[List[str]]:
    """
    Generate cell colors based on table style.
    """
    colors: List[List[str]] = []
    for i in range(num_rows):
        if i == 0 and has_header:
            row_color = ['#4472C4'] * num_cols
        elif style == 'striped':
            base_idx = i - (1 if has_header else 0)
            row_color = (['#E7E6E6'] * num_cols) if base_idx % 2 == 0 else (['white'] * num_cols)
        elif style == 'minimal':
            row_color = ['white'] * num_cols
        else:  # 'standard'
            row_color = ['#F2F2F2'] * num_cols
        colors.append(row_color)
    return colors


def latex_to_unicode(text: str) -> str:
    """Convert LaTeX mathematical notation to Unicode equivalents."""
    latex_to_unicode_map = {
        r'\le': '≤',
        r'\leq': '≤',
        r'\ge': '≥',
        r'\geq': '≥',
        r'\ne': '≠',
        r'\times': '×',
        r'\div': '÷',
        r'\pm': '±',
    }

    text = str(text).replace('$', '')
    for latex_cmd, unicode_char in latex_to_unicode_map.items():
        text = text.replace(latex_cmd, unicode_char)
    return text


def clean_table_text(text: str) -> str:
    """Clean and normalize table cell text for safe rendering."""
    text = str(text)
    text = text.replace('\\\\', '\\')  # Handle double backslashes from JSON
    text = latex_to_unicode(text)
    return text.strip()


# ============================================================================
# SPECIALIZED PLOTTING FUNCTIONS FOR EACH CHART TYPE
# ============================================================================

def plot_explicit_function(ax: plt.Axes, graph: Dict[str, Any],
                           function_registry: Dict[str, Optional[Callable]]) -> None:
    graph_id = graph.get('id', 'unknown')
    label = graph.get('label', '')

    axes_range = None
    if 'visual_features' in graph and 'axes_range' in graph['visual_features']:
        axes_range = graph['visual_features']['axes_range']
        x_min = axes_range.get('x_min', -10)
        x_max = axes_range.get('x_max', 10)
    else:
        x_min, x_max = -10, 10

    x_vals = np.linspace(x_min, x_max, 1000)
    func_str = graph['explicit_function']

    create_safe_function = lambda s: (lambda x: evaluate_function(s, x))
    function_registry[graph_id] = create_safe_function(func_str)

    y_vals = evaluate_function(func_str, x_vals)

    visual_features = graph.get('visual_features', {}) or {}
    show_label = bool(visual_features.get('show_label', False))
    safe_label = label if show_label else ""

    ax.plot(x_vals, y_vals, label=safe_label, linewidth=2.5, color=get_color_cycle(graph_id))

    if bool(visual_features.get('render_features', False)):
        add_visual_features(ax, visual_features, x_vals, y_vals)


def plot_parametric_curve(ax: plt.Axes, graph: Dict[str, Any],
                          function_registry: Dict[str, Optional[Callable]]) -> None:
    graph_id = graph.get('id', 'unknown')
    label = graph.get('label', '')

    param_funcs = graph['parametric_function']
    t_range = graph.get('parameter_range', {'t_min': 0, 't_max': 2 * np.pi})
    t_vals = np.linspace(t_range['t_min'], t_range['t_max'], 1000)

    x_param = evaluate_function(param_funcs['x'], t_vals)
    y_param = evaluate_function(param_funcs['y'], t_vals)

    function_registry[graph_id] = None

    visual_features = graph.get('visual_features', {}) or {}
    show_label = bool(visual_features.get('show_label', False))
    safe_label = label if show_label else ""

    ax.plot(x_param, y_param, label=safe_label, linewidth=2.5, color=get_color_cycle(graph_id))


def plot_scatter(ax: plt.Axes, graph: Dict[str, Any],
                 function_registry: Dict[str, Optional[Callable]]) -> None:
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
            x_trend = np.linspace(x_data.min(), x_data.max(), 100)
            y_trend = evaluate_function(rhs, x_trend)

            show_trend_label = bool(trend_line.get('show_label', False))
            trend_label = (trend_line.get('label') or 'Trend line') if show_trend_label else ""

            ax.plot(x_trend, y_trend, '--', color=color, alpha=0.6, linewidth=2, label=trend_label)

    function_registry[graph_id] = None


def plot_bar_chart(ax: plt.Axes, graph: Dict[str, Any],
                   function_registry: Dict[str, Optional[Callable]]) -> None:
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
    ax.bar(x_pos, values, label=safe_label, alpha=0.7, color=color,
           edgecolor='black', linewidth=1.5)

    ax.set_xticks(x_pos)
    ax.set_xticklabels(categories, rotation=0)

    function_registry[graph_id] = None


def _coerce_bin_pair(b: Any) -> Optional[Tuple[float, float]]:
    """
    Accept bins in any of these shapes:
      - [0, 5]
      - (0, 5)
      - "[0, 5]"  (Firestore-safe form)
      - "0,5" / "0 5" / "0-5"  (fallback)
    Returns (lo, hi) floats or None if unparseable.
    """
    if isinstance(b, (list, tuple)) and len(b) == 2:
        try:
            return float(b[0]), float(b[1])
        except Exception:
            return None

    if isinstance(b, str):
        s = b.strip()

        # Try JSON array first: "[0, 5]"
        try:
            parsed = json.loads(s)
            if isinstance(parsed, (list, tuple)) and len(parsed) == 2:
                return float(parsed[0]), float(parsed[1])
        except Exception:
            pass

        # Fallback: pull two numbers from the string
        try:
            import re
            nums = re.findall(r"[-+]?\d*\.?\d+", s)
            if len(nums) >= 2:
                return float(nums[0]), float(nums[1])
        except Exception:
            pass

    return None


def plot_histogram(ax: plt.Axes, graph: Dict[str, Any],
                   function_registry: Dict[str, Optional[Callable]]) -> None:
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

    ax.bar(bin_centers, frequencies, width=bin_widths, align='center',
           label=safe_label, alpha=0.7, color=color,
           edgecolor='black', linewidth=1.5)

    # Make x-axis readable: place ticks at bin boundaries.
    try:
        edges = []
        for (lo, hi) in bins:
            edges.extend([lo, hi])
        edges = sorted(set(edges))
        if edges:
            ax.set_xticks(edges)
    except Exception:
        pass

    function_registry[graph_id] = None


def plot_box_plot(ax: plt.Axes, graph: Dict[str, Any],
                  function_registry: Dict[str, Optional[Callable]]) -> None:
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

        # FIX: do NOT clamp whiskers to 0; boxplots can be negative.
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
            ax.scatter(group_idx + 1, outlier['value'], color='red', s=100,
                       marker='o', zorder=5,
                       label='Outliers' if outlier == outliers[0] else '')

    function_registry[graph_id] = None


def plot_cumulative_frequency(ax: plt.Axes, graph: Dict[str, Any],
                              function_registry: Dict[str, Optional[Callable]]) -> None:
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

    ax.plot(x_vals, y_vals, marker='o', linewidth=2.5, markersize=6,
            label=safe_label, color=color, alpha=0.7)

    function_registry[graph_id] = None

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def evaluate_function(func_str: str, x_vals: np.ndarray) -> np.ndarray:
    """
    Safely evaluate a mathematical function string.

    Converts common mathematical notation to NumPy equivalents and evaluates
    the expression. Handles both scalar and array inputs.

    Supported functions:
    - Trigonometric: sin, cos, tan, arcsin, arccos, arctan
    - Exponential/Logarithmic: exp, log, log10
    - Other: sqrt, abs, sinh, cosh, tanh
    """
    try:
        import re

        s = str(func_str)

        # 1) Power operator
        s = s.replace('^', '**')

        # 2) Replace known function names using word boundaries (prevents e.g. arcsin -> arcnp.sin)
        #    Order matters: longer names first.
        fn_map = [
            ('arcsin', 'np.arcsin'),
            ('arccos', 'np.arccos'),
            ('arctan', 'np.arctan'),
            ('sinh', 'np.sinh'),
            ('cosh', 'np.cosh'),
            ('tanh', 'np.tanh'),
            ('sin', 'np.sin'),
            ('cos', 'np.cos'),
            ('tan', 'np.tan'),
            ('exp', 'np.exp'),
            ('log10', 'np.log10'),
            ('log', 'np.log'),
            ('sqrt', 'np.sqrt'),
            ('abs', 'np.abs'),
        ]
        for name, repl in fn_map:
            s = re.sub(rf'\b{name}\b', repl, s)

        # 3) Constants (word-boundary so we don’t corrupt identifiers)
        s = re.sub(r'\bpi\b', 'np.pi', s)
        # NOTE: we intentionally do NOT replace bare "e" globally because it corrupts strings like "exp".
        # If you need Euler's constant, prefer "np.e" in generated configs.

        # Handle the case where x_vals might be a single value
        x = x_vals

        # Evaluate the function with error suppression for invalid values
        # SECURITY: lock down eval() so the expression cannot access builtins/imports/etc.
        with np.errstate(all='ignore'):
            y_vals = eval(
                s,
                {"__builtins__": {}},
                {"np": np, "x": x}
            )

        # Handle scalar results
        if np.isscalar(y_vals):
            y_vals = np.full_like(x_vals, y_vals, dtype=float)

        # Ensure ndarray float
        y_vals = np.asarray(y_vals, dtype=float)

        return y_vals

    except Exception as e:
        print(f"⚠️ Error evaluating function '{func_str}': {e}")
        return np.zeros_like(x_vals)


def add_visual_features(ax: plt.Axes, features: Dict[str, Any],
                       x_vals: np.ndarray, y_vals: np.ndarray) -> None:
    """
    Add visual features like intercepts, turning points, asymptotes, etc.
    """

    # ---- Pedagogy guardrails (avoid giving away answers) ----
    # Nothing in here should render unless the caller opted-in via features['render_features'].
    # Still, keep these local switches so we can be strict per-feature.
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
                    xy=(x_tp, y_tp), xytext=(10, 10),
                    textcoords='offset points', fontsize=9,
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

    # ---- Pedagogy guardrails (avoid giving away answers) ----
    if not bool(point.get('reveal', False)):
        return

    x, y = point['x'], point['y']
    label = point.get('label', '')
    color = point.get('color', 'black')
    marker_size = point.get('marker_size', 8)

    ax.plot(x, y, 'o', color=color, markersize=marker_size, zorder=5)

    # Always show label if the point is revealed (otherwise it’s pointless)
    offset = point.get('offset', (12, 12))
    if label:
        ax.annotate(
            label,
            xy=(x, y),
            xytext=offset,
            textcoords='offset points',
            fontsize=11,
            fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.4', facecolor='white',
                      edgecolor='black', alpha=0.8),
            arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0.3')
        )


def plot_shaded_region(ax: plt.Axes, region: Dict[str, Any],
                      function_registry: Dict[str, Callable]) -> None:
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


def get_bound_values(bound_id: str, x_vals: np.ndarray,
                    function_registry: Dict[str, Callable]) -> np.ndarray:
    """
    Get y values for a bound (either from function registry or constant).

    Handles both function references and constant values like "y=0" or "y=5".
    """
    if bound_id in function_registry:
        func = function_registry[bound_id]
        if func is not None:
            return func(x_vals)
        else:
            return np.zeros_like(x_vals)

    elif bound_id.startswith('y='):
        try:
            const_val = float(bound_id.split('=')[1])
            return np.full_like(x_vals, const_val)
        except (ValueError, IndexError):
            print(f"⚠️ Could not parse constant bound: {bound_id}")
            return np.zeros_like(x_vals)

    else:
        print(f"⚠️ Bound '{bound_id}' not found in function registry")
        return np.zeros_like(x_vals)


def setup_plot_appearance(ax: plt.Axes, config: Dict[str, Any]) -> None:
    """
    Set up the overall appearance and styling of the plot.

    NOTE:
    - Axis labels (x/y) are always shown.
    - Axis *numbers* are hidden by default unless config["show_axis_numbers"] is True.
      dynamic_chart_plotter() will FORCE show_axis_numbers=True for data-reading charts.
    """

    # Set labels
    x_label = config.get('x_label', 'x')
    y_label = config.get('y_label', 'y')
    ax.set_xlabel(x_label, fontsize=13, fontweight='bold')
    ax.set_ylabel(y_label, fontsize=13, fontweight='bold')

    # Set title
    if 'title' in config:
        ax.set_title(config['title'], fontsize=15, fontweight='bold', pad=20)

    # Set grid
    grid_enabled = config.get('grid', True)
    grid_style = config.get('grid_style', 'major')
    if grid_enabled:
        ax.grid(True, alpha=0.3, which=grid_style)

    # Set axis ranges - support both 'global_axes_range' and 'axes_range'
    axes_range_config = config.get('global_axes_range', config.get('axes_range'))
    if axes_range_config:
        x_min = axes_range_config.get('x_min', -10)
        x_max = axes_range_config.get('x_max', 10)
        y_min = axes_range_config.get('y_min', -10)
        y_max = axes_range_config.get('y_max', 10)
        ax.set_xlim(x_min, x_max)
        ax.set_ylim(y_min, y_max)

    # Axis numbers
    show_axis_numbers = bool(config.get('show_axis_numbers', False))
    if not show_axis_numbers:
        ax.set_xticklabels([])
        ax.set_yticklabels([])
        ax.tick_params(axis='both', which='both', length=0)
    else:
        ax.tick_params(axis='both', which='both', length=4)

    # Add legend if there are labeled items
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        filtered = [(h, l) for (h, l) in zip(handles, labels) if str(l).strip()]
        if filtered:
            handles2, labels2 = zip(*filtered)
            legend_loc = config.get('legend_location', 'best')
            ax.legend(handles2, labels2, loc=legend_loc, fontsize=11, framealpha=0.9)

    # Set equal aspect ratio if specified
    if config.get('equal_aspect', False):
        ax.set_aspect('equal', adjustable='box')

    # Add axis through origin if requested
    if config.get('axes_through_origin', False):
        ax.axhline(y=0, color='k', linewidth=0.8, alpha=0.3)
        ax.axvline(x=0, color='k', linewidth=0.8, alpha=0.3)

    # Tight layout
    plt.tight_layout()


def get_color_cycle(graph_id: str) -> str:
    """
    Get a color from matplotlib's color cycle based on graph ID.
    """
    colors = ['tab:blue', 'tab:orange', 'tab:green', 'tab:red',
              'tab:purple', 'tab:brown', 'tab:pink', 'tab:gray']

    hash_val = hash(graph_id) % len(colors)
    return colors[hash_val]

# ============================================================================
# VALIDATION FUNCTION
# ============================================================================

def validate_config(config: Dict[str, Any]) -> List[str]:
    """
    Validate the configuration and return any issues found.
    """
    issues = []

    if not isinstance(config, dict):
        issues.append("Configuration must be a dictionary")
        return issues

    charts = config.get('charts', config.get('graphs', []))

    if not charts:
        issues.append("No charts found in configuration")
    elif isinstance(charts, list):
        for i, chart in enumerate(charts):
            if not isinstance(chart, dict):
                issues.append(f"Chart {i} must be a dictionary")
                continue

            if 'id' not in chart:
                issues.append(f"Chart {i} missing required 'id' field")

            chart_type = str(chart.get('type', 'function')).strip().lower()

            if chart_type == 'function':
                if 'explicit_function' not in chart:
                    issues.append(f"Chart '{chart.get('id', i)}' missing 'explicit_function'")

            elif chart_type == 'parametric':
                if 'parametric_function' not in chart:
                    issues.append(f"Chart '{chart.get('id', i)}' missing 'parametric_function'")

            elif chart_type == 'histogram':
                vf = chart.get('visual_features', {}) or {}
                if 'bins' not in vf or 'frequencies' not in vf:
                    issues.append(f"Histogram '{chart.get('id', i)}' missing 'bins' or 'frequencies'")
                elif len(vf['bins']) != len(vf['frequencies']):
                    issues.append(f"Histogram '{chart.get('id', i)}': bins and frequencies length mismatch")
                else:
                    # Allow bins to be Firestore-sanitized strings like "[0, 5]"
                    for b in vf.get("bins", []):
                        if _coerce_bin_pair(b) is None:
                            issues.append(f"Histogram '{chart.get('id', i)}' has unparseable bin: {b!r}")
                            break

            elif chart_type == 'bar':
                vf = chart.get('visual_features', {}) or {}
                if 'categories' not in vf or 'values' not in vf:
                    issues.append(f"Bar chart '{chart.get('id', i)}' missing 'categories' or 'values'")
                elif len(vf['categories']) != len(vf['values']):
                    issues.append(f"Bar chart '{chart.get('id', i)}': categories and values length mismatch")

            elif chart_type == 'scatter':
                vf = chart.get('visual_features', {}) or {}
                if 'data_points' not in vf:
                    issues.append(f"Scatter plot '{chart.get('id', i)}' missing 'data_points'")

            elif chart_type == 'box_plot':
                vf = chart.get('visual_features', {}) or {}
                required_fields = ['min_values', 'q1_values', 'median_values', 'q3_values', 'max_values']
                for field in required_fields:
                    if field not in vf:
                        issues.append(f"Box plot '{chart.get('id', i)}' missing '{field}'")

            elif chart_type == 'cumulative':
                vf = chart.get('visual_features', {}) or {}
                if 'upper_class_boundaries' not in vf or 'cumulative_frequencies' not in vf:
                    issues.append(f"Cumulative frequency '{chart.get('id', i)}' missing boundaries or frequencies")
                elif len(vf['upper_class_boundaries']) != len(vf['cumulative_frequencies']):
                    issues.append(f"Cumulative frequency '{chart.get('id', i)}': length mismatch")

            elif chart_type == 'table':
                vf = chart.get('visual_features', {}) or {}
                if 'rows' not in vf:
                    issues.append(f"Table '{chart.get('id', i)}' missing 'rows' field")
                    continue

                rows = vf['rows']
                headers = vf.get('headers', [])

                if rows:
                    expected_cols = len(headers) if headers else len(rows[0])
                    for row_idx, row in enumerate(rows):
                        if len(row) != expected_cols:
                            issues.append(
                                f"Table '{chart.get('id', i)}' row {row_idx}: "
                                f"expected {expected_cols} columns, got {len(row)}"
                            )

                position = vf.get('position', 'standalone')
                if position in ['above_chart', 'below_chart', 'beside_chart']:
                    associated_id = vf.get('associated_chart_id')
                    if associated_id:
                        chart_ids = [c.get('id') for c in charts]
                        if associated_id not in chart_ids:
                            issues.append(
                                f"Table '{chart.get('id', i)}' references "
                                f"non-existent chart '{associated_id}'"
                            )

            else:
                issues.append(f"Unsupported chart type: {chart_type}")

    else:
        issues.append("'charts' or 'graphs' must be a list")

    if 'labeled_points' in config:
        if not isinstance(config['labeled_points'], list):
            issues.append("'labeled_points' must be a list")
        else:
            for i, point in enumerate(config['labeled_points']):
                required_fields = ['label', 'x', 'y']
                for field in required_fields:
                    if field not in point:
                        issues.append(f"Labeled point {i} missing required field: '{field}'")

    if 'shaded_regions' in config:
        if not isinstance(config['shaded_regions'], list):
            issues.append("'shaded_regions' must be a list")
        else:
            for i, region in enumerate(config['shaded_regions']):
                required_fields = ['upper_bound_id', 'lower_bound_id', 'x_start', 'x_end']
                for field in required_fields:
                    if field not in region:
                        issues.append(f"Shaded region {i} missing required field: '{field}'")

    return issues