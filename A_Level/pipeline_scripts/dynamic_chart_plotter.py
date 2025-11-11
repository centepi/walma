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
from typing import Dict, List, Any, Optional, Callable
import warnings

warnings.filterwarnings('ignore')


# ============================================================================
# MAIN DYNAMIC CHART PLOTTER FUNCTION
# ============================================================================

def dynamic_chart_plotter(config: Dict[str, Any]) -> plt.Figure:
    """
    Dynamic function to plot various charts and graphs based on JSON configuration.
    
    Supports explicit mathematical functions, parametric curves, histograms,
    bar charts, scatter plots, box plots, cumulative frequency curves, labeled
    annotations, shaded regions, and customizable visual features.
    
    Parameters:
    -----------
    config : dict
        Configuration dictionary containing:
        - charts: List of chart objects to plot (replaces 'graphs')
        - labeled_points: Optional list of labeled points to annotate
        - shaded_regions: Optional list of regions to shade between curves
        - title: Optional plot title
        - global_axes_range: Optional global axis limits
        - equal_aspect: Optional boolean for equal aspect ratio
        - x_label, y_label: Optional axis labels
    
    Returns:
    --------
    matplotlib.figure.Figure
        The generated matplotlib figure object
    
    Raises:
    -------
    TypeError
        If config is not a dictionary
    ValueError
        If chart type is not supported or required fields are missing
    
    Example:
    --------
    # Example 1: Explicit function
    config = {
        "charts": [{
            "id": "g1",
            "type": "function",
            "label": "y = x^2",
            "explicit_function": "x**2",
            "visual_features": {"type": "parabola"}
        }],
        "title": "Quadratic Function"
    }
    
    # Example 2: Histogram
    config = {
        "charts": [{
            "id": "h1",
            "type": "histogram",
            "label": "Distribution",
            "visual_features": {
                "type": "histogram",
                "bins": [[0, 10], [10, 20], [20, 30]],
                "frequencies": [5, 8, 3]
            }
        }]
    }
    
    fig = dynamic_chart_plotter(config)
    plt.show()
    """
    
    # # Validate input
    # if not isinstance(config, dict):
    #     raise TypeError("Config must be a dictionary")
    
    # # Create figure and axis
    # fig, ax = plt.subplots(figsize=(12, 8))
    
    # # Store function objects for later reference (e.g., for shaded regions)
    # function_registry: Dict[str, Callable] = {}
    
    # # Support both 'charts' (new) and 'graphs' (legacy) keys
    # charts = config.get('charts', config.get('graphs', []))
    
    # # Process charts
    # for chart in charts:
    #     plot_chart(ax, chart, function_registry)
    
    # # Process labeled points
    # if 'labeled_points' in config:
    #     for point in config['labeled_points']:
    #         plot_labeled_point(ax, point)
    
    # # Process shaded regions
    # if 'shaded_regions' in config:
    #     for region in config['shaded_regions']:
    #         plot_shaded_region(ax, region, function_registry)
    
    # # Set up the plot appearance
    # setup_plot_appearance(ax, config)
    
    # return fig
    # Validate input
    if not isinstance(config, dict):
        raise TypeError("Config must be a dictionary")
    
    # Support both 'charts' (new) and 'graphs' (legacy) keys
    charts = config.get('charts', config.get('graphs', []))
    
    # Determine layout type
    layout_mode = config.get('layout', 'single')
    
    # Check for tables and their positioning
    tables = [c for c in charts if c.get('type') == 'table']
    non_tables = [c for c in charts if c.get('type') != 'table']
    
    # Determine subplot configuration
    if layout_mode == 'composite' or tables:
        fig, axes = create_composite_layout(config, tables, non_tables)
    else:
        # Standard single-chart layout
        fig, ax = plt.subplots(figsize=(12, 8))
        axes = {'main': ax}
    
    # Store function objects for later reference
    function_registry: Dict[str, Callable] = {}
    
    # Process charts (non-tables)
    if 'main' in axes:
        for chart in non_tables:
            plot_chart(axes['main'], chart, function_registry)
        
        # Process labeled points
        if 'labeled_points' in config:
            for point in config['labeled_points']:
                plot_labeled_point(axes['main'], point)
        
        # Process shaded regions
        if 'shaded_regions' in config:
            for region in config['shaded_regions']:
                plot_shaded_region(axes['main'], region, function_registry)
        
        # Set up the plot appearance for main chart
        setup_plot_appearance(axes['main'], config)
    
    # Process tables
    if 'table' in axes:
        for table in tables:
            plot_table(axes['table'], table)
    
    # Global title if specified
    if 'title' in config and layout_mode == 'composite':
        fig.suptitle(config['title'], fontsize=16, fontweight='bold', y=0.98)
    
    plt.tight_layout()
    
    return fig

def create_composite_layout(config: Dict[str, Any], 
                            tables: List[Dict[str, Any]], 
                            charts: List[Dict[str, Any]]) -> tuple:
    """
    Create figure with composite layout for charts and tables.
    
    Parameters:
    -----------
    config : dict
        Full configuration
    tables : list
        List of table configurations
    charts : list
        List of chart configurations
    
    Returns:
    --------
    tuple
        (figure, dict of axes)
    """
    
    axes = {}
    
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
        fig, (ax_table, ax_chart) = plt.subplots(2, 1, figsize=(12, 10), 
                                                  gridspec_kw={'height_ratios': [1, 3]})
        axes['table'] = ax_table
        axes['main'] = ax_chart
    
    elif position == 'below_chart':
        # Chart on top, table below
        fig, (ax_chart, ax_table) = plt.subplots(2, 1, figsize=(12, 10), 
                                                  gridspec_kw={'height_ratios': [3, 1]})
        axes['main'] = ax_chart
        axes['table'] = ax_table
    
    elif position == 'beside_chart':
        # Side-by-side layout
        fig, (ax_chart, ax_table) = plt.subplots(1, 2, figsize=(16, 8), 
                                                  gridspec_kw={'width_ratios': [2, 1]})
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
               function_registry: Dict[str, Callable]) -> None:
    """
    Dispatcher function to route chart plotting to appropriate handler.
    
    Routes to specialized plotting functions based on chart type.
    
    Parameters:
    -----------
    ax : matplotlib.axes.Axes
        The axes object to plot on
    chart : dict
        Chart configuration containing id, type, and function definition
    function_registry : dict
        Registry to store function objects for later reference
    
    Raises:
    -------
    ValueError
        If chart type is not recognized
    """
    
    chart_type = chart.get('type', 'function')  # Default to function for backward compatibility
    
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
        # This is a no-op in single-axis plotting
        pass
    else:
        raise ValueError(f"Unsupported chart type: {chart_type}")


def plot_table(ax: plt.Axes, table_config: Dict[str, Any]) -> None:
    """
    Plot a table using matplotlib's table functionality.
    
    Parameters:
    -----------
    ax : matplotlib.axes.Axes
        The axes object to plot the table on
    table_config : dict
        Table configuration containing headers, rows, and styling
    
    Example:
    --------
    table_config = {
        "id": "t1",
        "type": "table",
        "visual_features": {
            "headers": ["Class", "Frequency"],
            "rows": [["0-10", "5"], ["10-20", "12"]],
            "table_style": "striped"
        }
    }
    """
    
    visual_features = table_config.get('visual_features', {})
    headers = visual_features.get('headers', [])
    rows = visual_features.get('rows', [])
    table_style = visual_features.get('table_style', 'standard')
    label = table_config.get('label', '')
    
    # Validate table data
    if not rows:
        print(f"⚠️ No rows found in table '{table_config.get('id', 'unknown')}'")
        return
    
    # Check row consistency
    # expected_cols = len(headers) if headers else len(rows[0])
    # for i, row in enumerate(rows):
    #     if len(row) != expected_cols:
    #         print(f"⚠️ Row {i} has {len(row)} columns, expected {expected_cols}")
    
    # # Prepare table data (combine headers and rows)
    # if headers:
    #     table_data = [headers] + rows
    #     cell_colors = get_table_colors(len(rows) + 1, table_style, has_header=True)
    # else:
    #     table_data = rows
    #     cell_colors = get_table_colors(len(rows), table_style, has_header=False)

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

    # Determine expected column count
    expected_cols = len(cleaned_headers) if headers else len(cleaned_rows)
    
    # Prepare table data
    # if headers:
    #     table_data = [headers] + rows
    #     num_table_rows = len(rows) + 1
    #     has_header = True
    # else:
    #     table_data = rows
    #     num_table_rows = len(rows)
    #     has_header = False
    
    # Generate colors with CORRECT column count
    cell_colors = get_table_colors(num_table_rows, expected_cols,  # ✅ Pass num_cols!
                                   table_style, has_header=has_header)
    
    # Turn off axis
    ax.axis('off')
    ax.axis('tight')
    
    # Create the table
    mpl_table = ax.table(
        cellText=table_data,
        cellLoc='center',
        loc='center',
        cellColours=cell_colors,
        colWidths=[1.0/expected_cols] * expected_cols
    )
    
    # Style the table
    mpl_table.auto_set_font_size(False)
    mpl_table.set_fontsize(10)
    mpl_table.scale(1, 2)  # Scale row height for readability
    
    # Apply header styling if present
    if headers:
        for i in range(expected_cols):
            cell = mpl_table[(0, i)]
            cell.set_text_props(weight='bold', size=11)
            cell.set_facecolor('#4472C4')
            cell.set_text_props(color='white')
            cell.set_edgecolor('black')
            cell.set_linewidth(1.5)
    
    # Apply border styling to all cells
    for key, cell in mpl_table.get_celld().items():
        cell.set_edgecolor('black')
        cell.set_linewidth(0.5 if table_style == 'minimal' else 1)
    
    # Add label/title if present
    if label:
        ax.set_title(label, fontsize=12, fontweight='bold', pad=10)


def get_table_colors(num_rows: int, num_cols: int, style: str, 
                     has_header: bool = False) -> List[List[str]]:
    """
    Generate cell colors based on table style.
    
    Parameters:
    -----------
    num_rows : int
        Number of rows in the table (including header if present)
    style : str
        Table style: 'standard', 'striped', or 'minimal'
    has_header : bool
        Whether the first row is a header
    
    Returns:
    --------
    List[List[str]]
        2D list of color codes for each cell
    """
    
    colors = []
    
    # for i in range(num_rows):
    #     if i == 0 and has_header:
    #         # Header row (will be overridden in plot_table)
    #         row_color = ['#4472C4'] * 10  # Placeholder
    #     elif style == 'striped':
    #         # Alternating row colors
    #         row_color = ['#E7E6E6'] * 10 if (i - (1 if has_header else 0)) % 2 == 0 else ['white'] * 10
    #     elif style == 'minimal':
    #         # All white
    #         row_color = ['white'] * 10
    #     else:  # 'standard'
    #         # Light gray
    #         row_color = ['#F2F2F2'] * 10
        
    #     colors.append(row_color)

    for i in range(num_rows):
        if i == 0 and has_header:
            row_color = ['#4472C4'] * num_cols  # ✅ Dynamic!
        elif style == 'striped':
            row_color = (['#E7E6E6'] * num_cols) 
            # if is_even_row else (['white'] * num_cols)  # ✅ Dynamic!
        elif style == 'minimal':
            row_color = ['white'] * num_cols  # ✅ Dynamic!
        else:  # 'standard'
            row_color = ['#F2F2F2'] * num_cols  # ✅ Dynamic!
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
        # ... add others as needed
    }
    
    text = str(text).replace('$', '')  # Remove math mode delimiters
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
                          function_registry: Dict[str, Callable]) -> None:
    """
    Plot explicit mathematical function y = f(x).
    
    Parameters:
    -----------
    ax : matplotlib.axes.Axes
        The axes object to plot on
    graph : dict
        Graph configuration with explicit_function
    function_registry : dict
        Registry to store function objects
    """
    
    graph_id = graph.get('id', 'unknown')
    label = graph.get('label', '')
    
    # Determine the range for plotting
    axes_range = None
    if 'visual_features' in graph and 'axes_range' in graph['visual_features']:
        axes_range = graph['visual_features']['axes_range']
        x_min = axes_range.get('x_min', -10)
        x_max = axes_range.get('x_max', 10)
    else:
        x_min, x_max = -10, 10
    
    # Create x values
    x_vals = np.linspace(x_min, x_max, 1000)
    
    # Parse and evaluate explicit function
    func_str = graph['explicit_function']
    
    # Create lambda function for registry
    create_safe_function = lambda s: lambda x: evaluate_function(s, x)
    function_registry[graph_id] = create_safe_function(func_str)
    
    # Evaluate function over x range
    y_vals = evaluate_function(func_str, x_vals)
    
    # Plot the function
    ax.plot(x_vals, y_vals, label=label, linewidth=2.5, color=get_color_cycle(graph_id))
    
    # Add special features if specified
    if 'visual_features' in graph:
        add_visual_features(ax, graph['visual_features'], x_vals, y_vals)


def plot_parametric_curve(ax: plt.Axes, graph: Dict[str, Any], 
                         function_registry: Dict[str, Callable]) -> None:
    """
    Plot parametric curve defined by x(t) and y(t).
    
    Parameters:
    -----------
    ax : matplotlib.axes.Axes
        The axes object to plot on
    graph : dict
        Graph configuration with parametric_function
    function_registry : dict
        Registry to store function objects
    """
    
    graph_id = graph.get('id', 'unknown')
    label = graph.get('label', '')
    
    # Handle parametric functions x(t), y(t)
    param_funcs = graph['parametric_function']
    t_range = graph.get('parameter_range', {'t_min': 0, 't_max': 2*np.pi})
    t_vals = np.linspace(t_range['t_min'], t_range['t_max'], 1000)
    
    x_param = evaluate_function(param_funcs['x'], t_vals)
    y_param = evaluate_function(param_funcs['y'], t_vals)
    
    # Store function as None since parametric doesn't fit standard y=f(x)
    function_registry[graph_id] = None
    
    ax.plot(x_param, y_param, label=label, linewidth=2.5, 
            color=get_color_cycle(graph_id))


def plot_scatter(ax: plt.Axes, graph: Dict[str, Any], 
                function_registry: Dict[str, Callable]) -> None:
    """
    Plot scatter plot with optional trend line.
    
    Parameters:
    -----------
    ax : matplotlib.axes.Axes
        The axes object to plot on
    graph : dict
        Graph configuration with data_points in visual_features
    function_registry : dict
        Registry to store function objects
    """
    
    graph_id = graph.get('id', 'unknown')
    label = graph.get('label', '')
    color = get_color_cycle(graph_id)
    
    visual_features = graph.get('visual_features', {})
    data_points = visual_features.get('data_points', [])
    
    if not data_points:
        print(f"⚠️ No data points found in scatter plot '{graph_id}'")
        return
    
    x_data = np.array([point['x'] for point in data_points])
    y_data = np.array([point['y'] for point in data_points])
    
    # Plot scatter points
    ax.scatter(x_data, y_data, label=label, s=100, alpha=0.7, color=color, zorder=5)
    
    # Plot trend line if specified
    trend_line = visual_features.get('trend_line', {})
    if trend_line.get('enabled', False):
        trend_eq = trend_line.get('equation', '')
        if trend_eq:
            # Use a small x range for trend line
            x_trend = np.linspace(x_data.min(), x_data.max(), 100)
            y_trend = evaluate_function(trend_eq.split('=')[1].strip(), x_trend)
            ax.plot(x_trend, y_trend, '--', color=color, alpha=0.6, linewidth=2, label='Trend line')
    
    # Store as None for data points
    function_registry[graph_id] = None


def plot_bar_chart(ax: plt.Axes, graph: Dict[str, Any], 
                  function_registry: Dict[str, Callable]) -> None:
    """
    Plot bar chart with categories.
    
    Parameters:
    -----------
    ax : matplotlib.axes.Axes
        The axes object to plot on
    graph : dict
        Graph configuration with categories and values
    function_registry : dict
        Registry to store function objects
    """
    
    graph_id = graph.get('id', 'unknown')
    label = graph.get('label', '')
    color = get_color_cycle(graph_id)
    
    visual_features = graph.get('visual_features', {})
    categories = visual_features.get('categories', [])
    values = visual_features.get('values', [])
    
    if len(categories) != len(values):
        print(f"⚠️ Category and value count mismatch in bar chart '{graph_id}'")
        return
    
    if not categories:
        print(f"⚠️ No categories found in bar chart '{graph_id}'")
        return
    
    # Plot bar chart
    x_pos = np.arange(len(categories))
    ax.bar(x_pos, values, label=label, alpha=0.7, color=color, edgecolor='black', linewidth=1.5)
    
    # Set category labels
    ax.set_xticks(x_pos)
    ax.set_xticklabels(categories, rotation=0)
    
    # Store as None for categorical data
    function_registry[graph_id] = None


def plot_histogram(ax: plt.Axes, graph: Dict[str, Any], 
                  function_registry: Dict[str, Callable]) -> None:
    """
    Plot histogram with bins and frequencies.
    
    Parameters:
    -----------
    ax : matplotlib.axes.Axes
        The axes object to plot on
    graph : dict
        Graph configuration with bins and frequencies
    function_registry : dict
        Registry to store function objects
    """
    
    graph_id = graph.get('id', 'unknown')
    label = graph.get('label', '')
    color = get_color_cycle(graph_id)
    
    visual_features = graph.get('visual_features', {})
    bins = visual_features.get('bins', [])
    frequencies = visual_features.get('frequencies', [])
    
    if len(bins) != len(frequencies):
        print(f"⚠️ Bin and frequency count mismatch in histogram '{graph_id}'")
        return
    
    if not bins:
        print(f"⚠️ No bins found in histogram '{graph_id}'")
        return
    
    # Calculate bin centers and widths
    bin_centers = np.array([(b[0] + b[1]) / 2 for b in bins])
    bin_widths = np.array([b[1] - b[0] for b in bins])
    
    # Plot histogram using bar chart
    ax.bar(bin_centers, frequencies, width=bin_widths, align='center', 
           label=label, alpha=0.7, color=color, edgecolor='black', linewidth=1.5)
    
    # Store as None for histogram data
    function_registry[graph_id] = None


# def plot_box_plot(ax: plt.Axes, graph: Dict[str, Any], 
#                  function_registry: Dict[str, Callable]) -> None:
#     """
#     Plot box plot (box-and-whisker plot) with quartiles.
    
#     Parameters:
#     -----------
#     ax : matplotlib.axes.Axes
#         The axes object to plot on
#     graph : dict
#         Graph configuration with five-number summary
#     function_registry : dict
#         Registry to store function objects
#     """
    
#     graph_id = graph.get('id', 'unknown')
#     label = graph.get('label', '')
#     color = get_color_cycle(graph_id)
    
#     visual_features = graph.get('visual_features', {})
#     groups = visual_features.get('groups', ['Data'])
#     min_vals = visual_features.get('min_values', [])
#     q1_vals = visual_features.get('q1_values', [])
#     median_vals = visual_features.get('median_values', [])
#     q3_vals = visual_features.get('q3_values', [])
#     max_vals = visual_features.get('max_values', [])
#     outliers = visual_features.get('outliers', [])
    
#     # Verify data lengths match
#     n_groups = len(groups)
#     if not all(len(v) == n_groups for v in [min_vals, q1_vals, median_vals, q3_vals, max_vals]):
#         print(f"⚠️ Data length mismatch in box plot '{graph_id}'")
#         return
    
#     # Create box plot data structure
#     box_data = []
#     for i in range(n_groups):
#         box_data.append([min_vals[i], q1_vals[i], median_vals[i], q3_vals[i], max_vals[i]])
    
#     # Plot using matplotlib's boxplot
#     bp = ax.boxplot(box_data, labels=groups, patch_artist=True, widths=0.6)
    
#     # Customize box colors
#     for patch in bp['boxes']:
#         patch.set_facecolor(color)
#         patch.set_alpha(0.7)
    
#     # Plot outliers if present
#     if outliers:
#         for outlier in outliers:
#             group_idx = groups.index(outlier.get('group', groups[0]))
#             ax.scatter(group_idx + 1, outlier['value'], color='red', s=100, 
#                       marker='o', zorder=5, label='Outliers' if outlier == outliers[0] else '')
    
#     # Store as None for box plot data
#     function_registry[graph_id] = None

def plot_box_plot(ax: plt.Axes, graph: Dict[str, Any], 
                 function_registry: Dict[str, Callable]) -> None:
    """
    Plot box plot (box-and-whisker plot) with quartiles.
    Parameters:
    -----------
    ax : matplotlib.axes.Axes
        The axes object to plot on
    graph : dict
        Graph configuration with five-number summary
    function_registry : dict
        Registry to store function objects
    """
    graph_id = graph.get('id', 'unknown')
    label = graph.get('label', '')
    color = get_color_cycle(graph_id)

    visual_features = graph.get('visual_features', {})
    groups = visual_features.get('groups', ['Data'])
    min_vals = visual_features.get('min_values', [])
    q1_vals = visual_features.get('q1_values', [])
    median_vals = visual_features.get('median_values', [])
    q3_vals = visual_features.get('q3_values', [])
    max_vals = visual_features.get('max_values', [])
    outliers = visual_features.get('outliers', [])

    # Verify data lengths match
    n_groups = len(groups)
    if not all(len(v) == n_groups for v in [min_vals, q1_vals, median_vals, q3_vals, max_vals]):
        print(f"⚠️ Data length mismatch in box plot '{graph_id}'")
        return

    # Create box plot data structure
    stats = []
    for i in range(n_groups):
        q1, med, q3 = q1_vals[i], median_vals[i], q3_vals[i]
        # Handle missing min/max: extend whiskers based on IQR
        iqr = q3 - q1
        whisker_low = min_vals[i] if min_vals[i] is not None else max(0, q1 - 1.5 * iqr)
        whisker_high = max_vals[i] if max_vals[i] is not None else q3 + 1.5 * iqr

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

    ax.set_title(label)
    # Plot outliers if present
    if outliers:
        for outlier in outliers:
            group_idx = groups.index(outlier.get('group', groups[0]))
            ax.scatter(group_idx + 1, outlier['value'], color='red', s=100, 
                      marker='o', zorder=5, label='Outliers' if outlier == outliers[0] else '')
    # Store as None for box plot data
    function_registry[graph_id] = None


def plot_cumulative_frequency(ax: plt.Axes, graph: Dict[str, Any], 
                              function_registry: Dict[str, Callable]) -> None:
    """
    Plot cumulative frequency curve.
    
    Parameters:
    -----------
    ax : matplotlib.axes.Axes
        The axes object to plot on
    graph : dict
        Graph configuration with class boundaries and cumulative frequencies
    function_registry : dict
        Registry to store function objects
    """
    
    graph_id = graph.get('id', 'unknown')
    label = graph.get('label', '')
    color = get_color_cycle(graph_id)
    
    visual_features = graph.get('visual_features', {})
    boundaries = visual_features.get('upper_class_boundaries', [])
    cum_frequencies = visual_features.get('cumulative_frequencies', [])
    
    if len(boundaries) != len(cum_frequencies):
        print(f"⚠️ Boundary and cumulative frequency count mismatch in CF curve '{graph_id}'")
        return
    
    if not boundaries:
        print(f"⚠️ No class boundaries found in cumulative frequency plot '{graph_id}'")
        return
    
    # Prepend origin point for proper curve
    x_vals = np.array([0] + list(boundaries))
    y_vals = np.array([0] + list(cum_frequencies))
    
    # Plot cumulative frequency curve
    ax.plot(x_vals, y_vals, marker='o', linewidth=2.5, markersize=6, 
            label=label, color=color, alpha=0.7)
    
    # Store as None for cumulative frequency data
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
    
    Parameters:
    -----------
    func_str : str
        Mathematical expression as string (e.g., "x**2 + 3*x + 2")
    x_vals : np.ndarray or float
        Input values for x
    
    Returns:
    --------
    np.ndarray
        Evaluated function values
    """
    
    try:
        # Replace common mathematical notation
        replacements = {
            '^': '**',
            'sin': 'np.sin',
            'cos': 'np.cos',
            'tan': 'np.tan',
            'arcsin': 'np.arcsin',
            'arccos': 'np.arccos',
            'arctan': 'np.arctan',
            'sinh': 'np.sinh',
            'cosh': 'np.cosh',
            'tanh': 'np.tanh',
            'exp': 'np.exp',
            'log': 'np.log',
            'log10': 'np.log10',
            'sqrt': 'np.sqrt',
            'abs': 'np.abs',
            'pi': 'np.pi',
            'e': 'np.e'
        }
        
        processed_str = func_str
        for old, new in replacements.items():
            processed_str = processed_str.replace(old, new)
        
        # Handle the case where x_vals might be a single value
        x = x_vals
        
        # Evaluate the function with error suppression for invalid values
        with np.errstate(all='ignore'):
            y_vals = eval(processed_str)
        
        # Handle scalar results
        if np.isscalar(y_vals):
            y_vals = np.full_like(x_vals, y_vals, dtype=float)
        
        # Replace NaN and Inf with appropriate values for plotting
        y_vals = np.asarray(y_vals, dtype=float)
        
        return y_vals
    
    except Exception as e:
        print(f"⚠️ Error evaluating function '{func_str}': {e}")
        return np.zeros_like(x_vals)


def add_visual_features(ax: plt.Axes, features: Dict[str, Any], 
                       x_vals: np.ndarray, y_vals: np.ndarray) -> None:
    """
    Add visual features like intercepts, turning points, asymptotes, etc.
    
    Parameters:
    -----------
    ax : matplotlib.axes.Axes
        The axes object to plot on
    features : dict
        Dictionary containing visual feature specifications
    x_vals : np.ndarray
        X values of the plotted function
    y_vals : np.ndarray
        Y values of the plotted function
    """
    
    # Mark x-intercepts
    if features.get('x_intercepts') is not None:
        x_intercepts = features['x_intercepts']
        if isinstance(x_intercepts, (list, tuple)):
            for x_int in x_intercepts:
                ax.plot(x_int, 0, 'ro', markersize=8, zorder=5)
                ax.axvline(x=x_int, color='red', linestyle='--', alpha=0.5, linewidth=1)
    
    # Mark y-intercept
    if features.get('y_intercept') is not None:
        y_int = features['y_intercept']
        ax.plot(0, y_int, 'go', markersize=8, zorder=5)
        ax.axhline(y=y_int, color='green', linestyle='--', alpha=0.5, linewidth=1)
    
    # Mark turning points (critical points, extrema)
    if features.get('turning_points'):
        for tp in features['turning_points']:
            x_tp, y_tp = tp['x'], tp['y']
            ax.plot(x_tp, y_tp, 'bs', markersize=10, zorder=5)
            ax.annotate(f'({x_tp:.1f}, {y_tp:.1f})', 
                       xy=(x_tp, y_tp), xytext=(10, 10),
                       textcoords='offset points', fontsize=9,
                       bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.3),
                       arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'))
    
    # Mark asymptotes
    if features.get('vertical_asymptotes'):
        for va in features['vertical_asymptotes']:
            ax.axvline(x=va, color='purple', linestyle=':', alpha=0.7, linewidth=1.5)
    
    if features.get('horizontal_asymptote') is not None:
        ha = features['horizontal_asymptote']
        ax.axhline(y=ha, color='purple', linestyle=':', alpha=0.7, linewidth=1.5)


def plot_labeled_point(ax: plt.Axes, point: Dict[str, Any]) -> None:
    """
    Plot a labeled point with annotation.
    
    Parameters:
    -----------
    ax : matplotlib.axes.Axes
        The axes object to plot on
    point : dict
        Point configuration with 'label', 'x', 'y'
    """
    
    x, y = point['x'], point['y']
    label = point.get('label', '')
    color = point.get('color', 'black')
    marker_size = point.get('marker_size', 8)
    
    # Plot the point
    ax.plot(x, y, 'o', color=color, markersize=marker_size, zorder=5)
    
    # Add label annotation
    offset = point.get('offset', (12, 12))
    ax.annotate(label, 
               xy=(x, y), 
               xytext=offset,
               textcoords='offset points',
               fontsize=11, 
               fontweight='bold',
               bbox=dict(boxstyle='round,pad=0.4', facecolor='white', 
                        edgecolor='black', alpha=0.8),
               arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0.3'))


def plot_shaded_region(ax: plt.Axes, region: Dict[str, Any], 
                      function_registry: Dict[str, Callable]) -> None:
    """
    Plot a shaded region between two curves or between a curve and a constant.
    
    Parameters:
    -----------
    ax : matplotlib.axes.Axes
        The axes object to plot on
    region : dict
        Region configuration with upper_bound_id, lower_bound_id, x_start, x_end
    function_registry : dict
        Registry of stored functions
    """
    
    upper_bound_id = region['upper_bound_id']
    lower_bound_id = region['lower_bound_id']
    x_start = region['x_start']
    x_end = region['x_end']
    color = region.get('color', 'lightblue')
    alpha = region.get('alpha', 0.3)
    label = region.get('label', None)
    
    # Create x values for the region
    x_region = np.linspace(x_start, x_end, 300)
    
    # Get upper bound values
    y_upper = get_bound_values(upper_bound_id, x_region, function_registry)
    
    # Get lower bound values
    y_lower = get_bound_values(lower_bound_id, x_region, function_registry)
    
    # Fill the region
    ax.fill_between(x_region, y_lower, y_upper, alpha=alpha, color=color, label=label)


def get_bound_values(bound_id: str, x_vals: np.ndarray, 
                    function_registry: Dict[str, Callable]) -> np.ndarray:
    """
    Get y values for a bound (either from function registry or constant).
    
    Handles both function references and constant values like "y=0" or "y=5".
    
    Parameters:
    -----------
    bound_id : str
        Either a graph ID or constant specification (e.g., "y=0")
    x_vals : np.ndarray
        X values at which to evaluate the bound
    function_registry : dict
        Registry of available functions
    
    Returns:
    --------
    np.ndarray
        Y values for the bound
    """
    
    if bound_id in function_registry:
        func = function_registry[bound_id]
        if func is not None:
            return func(x_vals)
        else:
            return np.zeros_like(x_vals)
    
    elif bound_id.startswith('y='):
        # Handle constant functions like y=0, y=5
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
    
    Handles titles, labels, grid, axis ranges, legend, and other visual settings.
    
    Parameters:
    -----------
    ax : matplotlib.axes.Axes
        The axes object to format
    config : dict
        Configuration dictionary with optional styling parameters
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
    
    # Set axis ranges - support both 'global_axes_range' and direct chart 'axes_range'
    axes_range_config = config.get('global_axes_range', config.get('axes_range'))
    if axes_range_config:
        x_min = axes_range_config.get('x_min', -10)
        x_max = axes_range_config.get('x_max', 10)
        y_min = axes_range_config.get('y_min', -10)
        y_max = axes_range_config.get('y_max', 10)
        ax.set_xlim(x_min, x_max)
        ax.set_ylim(y_min, y_max)
    
    # Add legend if there are labeled items
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        legend_loc = config.get('legend_location', 'best')
        ax.legend(loc=legend_loc, fontsize=11, framealpha=0.9)
    
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
    
    Parameters:
    -----------
    graph_id : str
        Unique identifier for the graph
    
    Returns:
    --------
    str
        Color specification
    """
    
    colors = ['tab:blue', 'tab:orange', 'tab:green', 'tab:red', 
              'tab:purple', 'tab:brown', 'tab:pink', 'tab:gray']
    
    # Use hash of graph_id to select color
    hash_val = hash(graph_id) % len(colors)
    return colors[hash_val]


# ============================================================================
# VALIDATION FUNCTION
# ============================================================================

def validate_config(config: Dict[str, Any]) -> List[str]:
    """
    Validate the configuration and return any issues found.
    
    Parameters:
    -----------
    config : dict
        Configuration to validate
    
    Returns:
    --------
    List[str]
        List of validation warnings/errors
    """
    
    issues = []
    
    # Check for required structure
    if not isinstance(config, dict):
        issues.append("Configuration must be a dictionary")
        return issues
    
    # Support both 'charts' (new) and 'graphs' (legacy) keys
    charts = config.get('charts', config.get('graphs', []))
    
    # Validate charts
    if not charts:
        issues.append("No charts found in configuration")
    elif isinstance(charts, list):
        for i, chart in enumerate(charts):
            if not isinstance(chart, dict):
                issues.append(f"Chart {i} must be a dictionary")
                continue
            
            if 'id' not in chart:
                issues.append(f"Chart {i} missing required 'id' field")
            
            chart_type = chart.get('type', 'function')
            
            # Validate based on chart type
            if chart_type == 'function':
                if 'explicit_function' not in chart:
                    issues.append(f"Chart '{chart.get('id', i)}' missing 'explicit_function'")
            
            elif chart_type == 'parametric':
                if 'parametric_function' not in chart:
                    issues.append(f"Chart '{chart.get('id', i)}' missing 'parametric_function'")
            
            elif chart_type == 'histogram':
                vf = chart.get('visual_features', {})
                if 'bins' not in vf or 'frequencies' not in vf:
                    issues.append(f"Histogram '{chart.get('id', i)}' missing 'bins' or 'frequencies'")
                elif len(vf['bins']) != len(vf['frequencies']):
                    issues.append(f"Histogram '{chart.get('id', i)}': bins and frequencies length mismatch")
            
            elif chart_type == 'bar':
                vf = chart.get('visual_features', {})
                if 'categories' not in vf or 'values' not in vf:
                    issues.append(f"Bar chart '{chart.get('id', i)}' missing 'categories' or 'values'")
                elif len(vf['categories']) != len(vf['values']):
                    issues.append(f"Bar chart '{chart.get('id', i)}': categories and values length mismatch")
            
            elif chart_type == 'scatter':
                vf = chart.get('visual_features', {})
                if 'data_points' not in vf:
                    issues.append(f"Scatter plot '{chart.get('id', i)}' missing 'data_points'")
            
            elif chart_type == 'box_plot':
                vf = chart.get('visual_features', {})
                required_fields = ['min_values', 'q1_values', 'median_values', 'q3_values', 'max_values']
                for field in required_fields:
                    if field not in vf:
                        issues.append(f"Box plot '{chart.get('id', i)}' missing '{field}'")
            
            elif chart_type == 'cumulative':
                vf = chart.get('visual_features', {})
                if 'upper_class_boundaries' not in vf or 'cumulative_frequencies' not in vf:
                    issues.append(f"Cumulative frequency '{chart.get('id', i)}' missing boundaries or frequencies")
                elif len(vf['upper_class_boundaries']) != len(vf['cumulative_frequencies']):
                    issues.append(f"Cumulative frequency '{chart.get('id', i)}': length mismatch")
            elif chart.get('type') == 'table':
                vf = chart.get('visual_features', {})
                
                # Check for rows
                if 'rows' not in vf:
                    issues.append(f"Table '{chart.get('id', i)}' missing 'rows' field")
                    continue
                
                rows = vf['rows']
                headers = vf.get('headers', [])
                
                # Validate row consistency
                if rows:
                    expected_cols = len(headers) if headers else len(rows[0])
                    
                    for row_idx, row in enumerate(rows):
                        if len(row) != expected_cols:
                            issues.append(
                                f"Table '{chart.get('id', i)}' row {row_idx}: "
                                f"expected {expected_cols} columns, got {len(row)}"
                            )
                
                # Validate position and association
                position = vf.get('position', 'standalone')
                if position in ['above_chart', 'below_chart', 'beside_chart']:
                    associated_id = vf.get('associated_chart_id')
                    if associated_id:
                        # Check if associated chart exists
                        chart_ids = [c.get('id') for c in charts]
                        if associated_id not in chart_ids:
                            issues.append(
                                f"Table '{chart.get('id', i)}' references "
                                f"non-existent chart '{associated_id}'"
                            )
    
    else:
        issues.append("'charts' or 'graphs' must be a list")
    
    # Validate labeled points
    if 'labeled_points' in config:
        if not isinstance(config['labeled_points'], list):
            issues.append("'labeled_points' must be a list")
        else:
            for i, point in enumerate(config['labeled_points']):
                required_fields = ['label', 'x', 'y']
                for field in required_fields:
                    if field not in point:
                        issues.append(f"Labeled point {i} missing required field: '{field}'")
    
    # Validate shaded regions
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



# """
# Dynamic Chart Plotter - Comprehensive Python Module
# =====================================================

# A flexible, production-ready function that generates various types of mathematical
# charts and graphs based on JSON configuration input.

# Supports:
#   • Explicit mathematical functions (y = f(x))
#   • Parametric curves (x = f(t), y = g(t))
#   • Data point visualizations (line, scatter, bar)
#   • Labeled point annotations
#   • Shaded regions between curves
#   • Customizable axes, grid, and styling

# Author: AI Engineering
# Date: 2025-10-30
# License: MIT
# """

# import matplotlib.pyplot as plt
# import numpy as np
# import json
# from typing import Dict, List, Any, Optional, Callable
# import warnings

# warnings.filterwarnings('ignore')


# # ============================================================================
# # MAIN DYNAMIC CHART PLOTTER FUNCTION
# # ============================================================================

# def dynamic_chart_plotter(config: Dict[str, Any]) -> plt.Figure:
#     """
#     Dynamic function to plot various charts and graphs based on JSON configuration.
    
#     Supports explicit mathematical functions, parametric curves, data points,
#     labeled annotations, shaded regions, and customizable visual features.
    
#     Parameters:
#     -----------
#     config : dict
#         Configuration dictionary containing:
#         - graphs: List of graph objects to plot
#         - labeled_points: Optional list of labeled points to annotate
#         - shaded_regions: Optional list of regions to shade between curves
#         - title: Optional plot title
#         - global_axes_range: Optional global axis limits
#         - equal_aspect: Optional boolean for equal aspect ratio
    
#     Returns:
#     --------
#     matplotlib.figure.Figure
#         The generated matplotlib figure object
    
#     Raises:
#     -------
#     TypeError
#         If config is not a dictionary
    
#     Example:
#     --------
#     config = {
#         "graphs": [{
#             "id": "g1",
#             "label": "y = x^2",
#             "explicit_function": "x**2"
#         }],
#         "title": "My Chart"
#     }
#     fig = dynamic_chart_plotter(config)
#     plt.show()
#     """
    
#     # Validate input
#     if not isinstance(config, dict):
#         raise TypeError("Config must be a dictionary")
    
#     # Create figure and axis
#     fig, ax = plt.subplots(figsize=(12, 8))
    
#     # Store function objects for later reference (e.g., for shaded regions)
#     function_registry: Dict[str, Callable] = {}
    
#     # Process graphs
#     if 'graphs' in config:
#         for graph in config['graphs']:
#             plot_graph(ax, graph, function_registry)
    
#     # Process labeled points
#     if 'labeled_points' in config:
#         for point in config['labeled_points']:
#             plot_labeled_point(ax, point)
    
#     # Process shaded regions
#     if 'shaded_regions' in config:
#         for region in config['shaded_regions']:
#             plot_shaded_region(ax, region, function_registry)
    
#     # Set up the plot appearance
#     setup_plot_appearance(ax, config)
    
#     return fig


# # ============================================================================
# # HELPER FUNCTIONS
# # ============================================================================

# def plot_graph(ax: plt.Axes, graph: Dict[str, Any], 
#                function_registry: Dict[str, Callable]) -> None:
#     print("at plot graph")
#     """
#     Plot a single graph based on its configuration.
    
#     Supports three types of graphs:
#     1. Explicit mathematical functions: y = f(x)
#     2. Parametric functions: x = f(t), y = g(t)
#     3. Data points: discrete x, y values
    
#     Parameters:
#     -----------
#     ax : matplotlib.axes.Axes
#         The axes object to plot on
#     graph : dict
#         Graph configuration containing id, label, and function definition
#     function_registry : dict
#         Registry to store function objects for later reference
#     """
    
#     graph_id = graph.get('id', 'unknown')
#     label = graph.get('label', '')
    
#     # Determine the range for plotting
#     axes_range = None
#     if 'visual_features' in graph and 'axes_range' in graph['visual_features']:
#         axes_range = graph['visual_features']['axes_range']
#         x_min = axes_range.get('x_min', -10)
#         x_max = axes_range.get('x_max', 10)
#     else:
#         x_min, x_max = -10, 10
    
#     # Create x values
#     x_vals = np.linspace(x_min, x_max, 1000)
    
#     # Handle different types of function definitions
#     if 'explicit_function' in graph:
#         # Parse and evaluate explicit function
#         func_str = graph['explicit_function']
        
#         # Create lambda function for registry
#         create_safe_function = lambda s: lambda x: evaluate_function(s, x)
#         function_registry[graph_id] = create_safe_function(func_str)
        
#         # Evaluate function over x range
#         y_vals = evaluate_function(func_str, x_vals)
        
#         # Plot the function
#         ax.plot(x_vals, y_vals, label=label, linewidth=2.5, color=get_color_cycle(graph_id))
        
#         # Add special features if specified
#         if 'visual_features' in graph:
#             add_visual_features(ax, graph['visual_features'], x_vals, y_vals)
    
#     elif 'parametric_function' in graph:
#         # Handle parametric functions x(t), y(t)
#         param_funcs = graph['parametric_function']
#         t_range = graph.get('parameter_range', {'t_min': 0, 't_max': 2*np.pi})
#         t_vals = np.linspace(t_range['t_min'], t_range['t_max'], 1000)
        
#         x_param = evaluate_function(param_funcs['x'], t_vals)
#         y_param = evaluate_function(param_funcs['y'], t_vals)
        
#         # Store function as None since parametric doesn't fit standard y=f(x)
#         function_registry[graph_id] = None
        
#         ax.plot(x_param, y_param, label=label, linewidth=2.5, 
#                 color=get_color_cycle(graph_id))
    
#     elif 'data_points' in graph:
#         # Handle discrete data points
#         data = graph['data_points']
#         x_data = np.array([point['x'] for point in data])
#         y_data = np.array([point['y'] for point in data])
        
#         plot_type = graph.get('plot_type', 'line')
#         color = get_color_cycle(graph_id)
        
#         if plot_type == 'scatter':
#             ax.scatter(x_data, y_data, label=label, s=100, alpha=0.7, color=color)
#         elif plot_type == 'bar':
#             ax.bar(x_data, y_data, label=label, alpha=0.7, color=color, width=0.6)
#         elif plot_type == 'line':
#             ax.plot(x_data, y_data, label=label, linewidth=2.5, 
#                    marker='o', markersize=6, color=color)
        
#         # Store as None for data points
#         function_registry[graph_id] = None
    
#     elif 'visual_features' in graph and 'bins' in graph['visual_features'] and 'frequencies' in graph['visual_features']:
#         bins = graph['bins']
#         frequencies = graph['frequencies']

#         # Plot the histogram manually using bar chart
#         plt.bar(
#             x=[(b[0] + b[1]) / 2 for b in bins],  # bin centers
#             height=frequencies,
#             width=[b[1] - b[0] for b in bins],    # bin widths
#             align='center',
#             edgecolor='black'
#         )


# def evaluate_function(func_str: str, x_vals: np.ndarray) -> np.ndarray:
#     """
#     Safely evaluate a mathematical function string.
    
#     Converts common mathematical notation to NumPy equivalents and evaluates
#     the expression. Handles both scalar and array inputs.
    
#     Supported functions:
#     - Trigonometric: sin, cos, tan, arcsin, arccos, arctan
#     - Exponential/Logarithmic: exp, log, log10
#     - Other: sqrt, abs, sinh, cosh, tanh
    
#     Parameters:
#     -----------
#     func_str : str
#         Mathematical expression as string (e.g., "x**2 + 3*x + 2")
#     x_vals : np.ndarray or float
#         Input values for x
    
#     Returns:
#     --------
#     np.ndarray
#         Evaluated function values
#     """
    
#     try:
#         # Replace common mathematical notation
#         replacements = {
#             '^': '**',
#             'sin': 'np.sin',
#             'cos': 'np.cos',
#             'tan': 'np.tan',
#             'arcsin': 'np.arcsin',
#             'arccos': 'np.arccos',
#             'arctan': 'np.arctan',
#             'sinh': 'np.sinh',
#             'cosh': 'np.cosh',
#             'tanh': 'np.tanh',
#             'exp': 'np.exp',
#             'log': 'np.log',
#             'log10': 'np.log10',
#             'sqrt': 'np.sqrt',
#             'abs': 'np.abs',
#             'pi': 'np.pi',
#             'e': 'np.e'
#         }
        
#         processed_str = func_str
#         for old, new in replacements.items():
#             processed_str = processed_str.replace(old, new)
        
#         # Handle the case where x_vals might be a single value
#         x = x_vals
        
#         # Evaluate the function with error suppression for invalid values
#         with np.errstate(all='ignore'):
#             y_vals = eval(processed_str)
        
#         # Handle scalar results
#         if np.isscalar(y_vals):
#             y_vals = np.full_like(x_vals, y_vals, dtype=float)
        
#         # Replace NaN and Inf with appropriate values for plotting
#         y_vals = np.asarray(y_vals, dtype=float)
        
#         return y_vals
    
#     except Exception as e:
#         print(f"⚠️  Error evaluating function '{func_str}': {e}")
#         return np.zeros_like(x_vals)


# def add_visual_features(ax: plt.Axes, features: Dict[str, Any], 
#                        x_vals: np.ndarray, y_vals: np.ndarray) -> None:
#     """
#     Add visual features like intercepts, turning points, asymptotes, etc.
    
#     Parameters:
#     -----------
#     ax : matplotlib.axes.Axes
#         The axes object to plot on
#     features : dict
#         Dictionary containing visual feature specifications
#     x_vals : np.ndarray
#         X values of the plotted function
#     y_vals : np.ndarray
#         Y values of the plotted function
#     """
    
#     # Mark x-intercepts
#     if features.get('x_intercepts') is not None:
#         x_intercepts = features['x_intercepts']
#         if isinstance(x_intercepts, (list, tuple)):
#             for x_int in x_intercepts:
#                 ax.plot(x_int, 0, 'ro', markersize=8, zorder=5)
#                 ax.axvline(x=x_int, color='red', linestyle='--', alpha=0.5, linewidth=1)
    
#     # Mark y-intercept
#     if features.get('y_intercept') is not None:
#         y_int = features['y_intercept']
#         ax.plot(0, y_int, 'go', markersize=8, zorder=5)
#         ax.axhline(y=y_int, color='green', linestyle='--', alpha=0.5, linewidth=1)
    
#     # Mark turning points (critical points, extrema)
#     if features.get('turning_points'):
#         for tp in features['turning_points']:
#             x_tp, y_tp = tp['x'], tp['y']
#             ax.plot(x_tp, y_tp, 'bs', markersize=10, zorder=5)
#             ax.annotate(f'Min/Max\n({x_tp:.1f}, {y_tp:.1f})', 
#                        xy=(x_tp, y_tp), xytext=(10, 10),
#                        textcoords='offset points', fontsize=9,
#                        bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.3),
#                        arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'))
    
#     # Mark asymptotes
#     if features.get('vertical_asymptotes'):
#         for va in features['vertical_asymptotes']:
#             ax.axvline(x=va, color='purple', linestyle=':', alpha=0.7, linewidth=1.5)
    
#     if features.get('horizontal_asymptote') is not None:
#         ha = features['horizontal_asymptote']
#         ax.axhline(y=ha, color='purple', linestyle=':', alpha=0.7, linewidth=1.5)


# def plot_labeled_point(ax: plt.Axes, point: Dict[str, Any]) -> None:
#     """
#     Plot a labeled point with annotation.
    
#     Parameters:
#     -----------
#     ax : matplotlib.axes.Axes
#         The axes object to plot on
#     point : dict
#         Point configuration with 'label', 'x', 'y'
#     """
    
#     x, y = point['x'], point['y']
#     label = point.get('label', '')
#     color = point.get('color', 'black')
#     marker_size = point.get('marker_size', 8)
    
#     # Plot the point
#     ax.plot(x, y, 'o', color=color, markersize=marker_size, zorder=5)
    
#     # Add label annotation
#     offset = point.get('offset', (12, 12))
#     ax.annotate(label, 
#                xy=(x, y), 
#                xytext=offset,
#                textcoords='offset points',
#                fontsize=11, 
#                fontweight='bold',
#                bbox=dict(boxstyle='round,pad=0.4', facecolor='white', 
#                         edgecolor='black', alpha=0.8),
#                arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0.3'))


# def plot_shaded_region(ax: plt.Axes, region: Dict[str, Any], 
#                       function_registry: Dict[str, Callable]) -> None:
#     """
#     Plot a shaded region between two curves or between a curve and a constant.
    
#     Parameters:
#     -----------
#     ax : matplotlib.axes.Axes
#         The axes object to plot on
#     region : dict
#         Region configuration with upper_bound_id, lower_bound_id, x_start, x_end
#     function_registry : dict
#         Registry of stored functions
#     """
    
#     upper_bound_id = region['upper_bound_id']
#     lower_bound_id = region['lower_bound_id']
#     x_start = region['x_start']
#     x_end = region['x_end']
#     color = region.get('color', 'lightblue')
#     alpha = region.get('alpha', 0.3)
#     label = region.get('label', None)
    
#     # Create x values for the region
#     x_region = np.linspace(x_start, x_end, 300)
    
#     # Get upper bound values
#     y_upper = get_bound_values(upper_bound_id, x_region, function_registry)
    
#     # Get lower bound values
#     y_lower = get_bound_values(lower_bound_id, x_region, function_registry)
    
#     # Fill the region
#     ax.fill_between(x_region, y_lower, y_upper, alpha=alpha, color=color, label=label)


# def get_bound_values(bound_id: str, x_vals: np.ndarray, 
#                     function_registry: Dict[str, Callable]) -> np.ndarray:
#     """
#     Get y values for a bound (either from function registry or constant).
    
#     Handles both function references and constant values like "y=0" or "y=5".
    
#     Parameters:
#     -----------
#     bound_id : str
#         Either a graph ID or constant specification (e.g., "y=0")
#     x_vals : np.ndarray
#         X values at which to evaluate the bound
#     function_registry : dict
#         Registry of available functions
    
#     Returns:
#     --------
#     np.ndarray
#         Y values for the bound
#     """
    
#     if bound_id in function_registry:
#         func = function_registry[bound_id]
#         if func is not None:
#             return func(x_vals)
#         else:
#             return np.zeros_like(x_vals)
    
#     elif bound_id.startswith('y='):
#         # Handle constant functions like y=0, y=5
#         try:
#             const_val = float(bound_id.split('=')[1])
#             return np.full_like(x_vals, const_val)
#         except (ValueError, IndexError):
#             print(f"⚠️  Could not parse constant bound: {bound_id}")
#             return np.zeros_like(x_vals)
    
#     else:
#         print(f"⚠️  Bound '{bound_id}' not found in function registry")
#         return np.zeros_like(x_vals)


# def setup_plot_appearance(ax: plt.Axes, config: Dict[str, Any]) -> None:
#     """
#     Set up the overall appearance and styling of the plot.
    
#     Handles titles, labels, grid, axis ranges, legend, and other visual settings.
    
#     Parameters:
#     -----------
#     ax : matplotlib.axes.Axes
#         The axes object to format
#     config : dict
#         Configuration dictionary with optional styling parameters
#     """
    
#     # Set labels
#     x_label = config.get('x_label', 'x')
#     y_label = config.get('y_label', 'y')
#     ax.set_xlabel(x_label, fontsize=13, fontweight='bold')
#     ax.set_ylabel(y_label, fontsize=13, fontweight='bold')
    
#     # Set title
#     if 'title' in config:
#         ax.set_title(config['title'], fontsize=15, fontweight='bold', pad=20)
    
#     # Set grid
#     grid_enabled = config.get('grid', True)
#     grid_style = config.get('grid_style', 'major')
#     if grid_enabled:
#         ax.grid(True, alpha=0.3, which=grid_style)
    
#     # Set axis ranges
#     if 'global_axes_range' in config:
#         range_config = config['global_axes_range']
#         x_min = range_config.get('x_min', -10)
#         x_max = range_config.get('x_max', 10)
#         y_min = range_config.get('y_min', -10)
#         y_max = range_config.get('y_max', 10)
#         ax.set_xlim(x_min, x_max)
#         ax.set_ylim(y_min, y_max)
    
#     # Add legend if there are labeled items
#     handles, labels = ax.get_legend_handles_labels()
#     if handles:
#         legend_loc = config.get('legend_location', 'best')
#         ax.legend(loc=legend_loc, fontsize=11, framealpha=0.9)
    
#     # Set equal aspect ratio if specified
#     if config.get('equal_aspect', False):
#         ax.set_aspect('equal', adjustable='box')
    
#     # Add axis through origin if requested
#     if config.get('axes_through_origin', False):
#         ax.axhline(y=0, color='k', linewidth=0.8, alpha=0.3)
#         ax.axvline(x=0, color='k', linewidth=0.8, alpha=0.3)
    
#     # Tight layout
#     plt.tight_layout()


# def get_color_cycle(graph_id: str) -> str:
#     """
#     Get a color from matplotlib's color cycle based on graph ID.
    
#     Parameters:
#     -----------
#     graph_id : str
#         Unique identifier for the graph
    
#     Returns:
#     --------
#     str
#         Color specification
#     """
    
#     colors = ['tab:blue', 'tab:orange', 'tab:green', 'tab:red', 
#               'tab:purple', 'tab:brown', 'tab:pink', 'tab:gray']
    
#     # Use hash of graph_id to select color
#     hash_val = hash(graph_id) % len(colors)
#     return colors[hash_val]


# # ============================================================================
# # VALIDATION FUNCTION
# # ============================================================================

# def validate_config(config: Dict[str, Any]) -> List[str]:
#     """
#     Validate the configuration and return any issues found.
    
#     Parameters:
#     -----------
#     config : dict
#         Configuration to validate
    
#     Returns:
#     --------
#     List[str]
#         List of validation warnings/errors
#     """
    
#     issues = []
    
#     # Check for required structure
#     if not isinstance(config, dict):
#         issues.append("Configuration must be a dictionary")
#         return issues
    
#     # Validate graphs
#     if 'graphs' in config:
#         if not isinstance(config['graphs'], list):
#             issues.append("'graphs' must be a list")
#         else:
#             for i, graph in enumerate(config['graphs']):
#                 if not isinstance(graph, dict):
#                     issues.append(f"Graph {i} must be a dictionary")
#                     continue
                
#                 if 'id' not in graph:
#                     issues.append(f"Graph {i} missing required 'id' field")
                
#                 # Check for exactly one function type
#                 function_count = sum([
#                     'explicit_function' in graph,
#                     'parametric_function' in graph,
#                     'data_points' in graph,
#                     'bins' in graph
#                 ])
                
#                 if function_count == 0:
#                     issues.append(
#                         f"Graph '{graph.get('id', i)}' must have one of: "
#                         "explicit_function, parametric_function, or data_points"
#                     )
#                 elif function_count > 1:
#                     issues.append(
#                         f"Graph '{graph.get('id', i)}' can only have one function type"
#                     )
    
#     # Validate labeled points
#     if 'labeled_points' in config:
#         if not isinstance(config['labeled_points'], list):
#             issues.append("'labeled_points' must be a list")
#         else:
#             for i, point in enumerate(config['labeled_points']):
#                 required_fields = ['label', 'x', 'y']
#                 for field in required_fields:
#                     if field not in point:
#                         issues.append(f"Labeled point {i} missing required field: '{field}'")
    
#     # Validate shaded regions
#     if 'shaded_regions' in config:
#         if not isinstance(config['shaded_regions'], list):
#             issues.append("'shaded_regions' must be a list")
#         else:
#             for i, region in enumerate(config['shaded_regions']):
#                 required_fields = ['upper_bound_id', 'lower_bound_id', 'x_start', 'x_end']
#                 for field in required_fields:
#                     if field not in region:
#                         issues.append(f"Shaded region {i} missing required field: '{field}'")
    
#     return issues

