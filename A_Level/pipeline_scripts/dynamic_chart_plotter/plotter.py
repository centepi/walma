"""
plotter.py — Chart Plotter entry point (controller/orchestrator)

This file contains ONLY:
- dynamic_chart_plotter (main entry point)
- create_composite_layout (layout helper)
- plot_chart (dispatcher)

All chart-specific plotting functions live in `charts.py`.
All helpers (appearance, evaluation, etc.) live in `utils.py`.
"""

import matplotlib.pyplot as plt
from typing import Dict, List, Any, Optional, Callable

# Local imports (kept light to avoid circular imports)
from .charts import (
    plot_explicit_function,
    plot_parametric_curve,
    plot_scatter,
    plot_bar_chart,
    plot_histogram,
    plot_box_plot,
    plot_cumulative_frequency,
    plot_table,
    plot_labeled_point,
    plot_shaded_region,
)
from .utils import setup_plot_appearance, _coerce_bin_pair


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
    tables = [
        c for c in charts
        if isinstance(c, dict) and str(c.get('type', '')).strip().lower() == 'table'
    ]
    non_tables = [
        c for c in charts
        if isinstance(c, dict) and str(c.get('type', '')).strip().lower() != 'table'
    ]

    # ------------------------------------------------------------------------
    # USABILITY DEFAULTS (so visuals actually help)
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

    # ------------------------------------------------------------------------
    # HISTOGRAM NORMALISATION (FIX EMPTY HISTOGRAMS)
    #
    # Some pipeline outputs provide bins + frequencies but omit "heights".
    # Our histogram renderer expects "heights" to plot the bars.
    #
    # We convert frequency -> frequency density height by dividing by class width.
    # ------------------------------------------------------------------------
    try:
        for c in non_tables:
            if not isinstance(c, dict):
                continue
            if str(c.get("type", "")).strip().lower() != "histogram":
                continue

            vf = c.get("visual_features")
            if not isinstance(vf, dict):
                vf = {}
                c["visual_features"] = vf

            # If heights are already provided, leave them alone.
            if vf.get("heights") is not None:
                continue

            raw_bins = vf.get("bins", [])
            freqs = vf.get("frequencies", [])

            if not raw_bins or not freqs:
                continue
            if len(raw_bins) != len(freqs):
                continue

            # Parse bins (supports lists/tuples or strings like "[0, 10]")
            parsed_bins = []
            ok = True
            for b in raw_bins:
                pair = _coerce_bin_pair(b)
                if pair is None:
                    ok = False
                    break
                lo, hi = pair
                width = float(hi) - float(lo)
                if width <= 0:
                    ok = False
                    break
                parsed_bins.append((float(lo), float(hi), width))

            if not ok:
                continue

            # Compute frequency densities
            heights = []
            for (_, _, width), f in zip(parsed_bins, freqs):
                try:
                    heights.append(float(f) / float(width))
                except Exception:
                    ok = False
                    break

            if not ok:
                continue

            vf["heights"] = heights
    except Exception:
        # Never crash plotting due to normalization logic.
        pass

    # Determine subplot configuration
    if layout_mode == 'composite' or tables:
        fig, axes = create_composite_layout(config, tables, non_tables)
    else:
        # Standard single-chart layout
        fig, ax = plt.subplots(figsize=(12, 8))
        axes = {'main': ax}

    # Store function objects for later reference
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

        # Set up the plot appearance for main chart (axis-level only; no tight_layout here)
        setup_plot_appearance(axes['main'], config)

    # Process tables
    if 'table' in axes:
        for table in tables:
            plot_table(axes['table'], table)

    # Global title if specified (composite only)
    if 'title' in config and layout_mode == 'composite':
        fig.suptitle(config['title'], fontsize=16, fontweight='bold', y=0.98)

    # IMPORTANT: apply figure-level layout once, at the very end.
    # This prevents clipped table titles / overlapping when multiple panels exist.
    try:
        fig.tight_layout()
    except Exception:
        # Never crash plotting due to layout.
        pass

    return fig


def create_composite_layout(
    config: Dict[str, Any],
    tables: List[Dict[str, Any]],
    charts: List[Dict[str, Any]]
) -> tuple:
    """
    Create figure with composite layout for charts and tables.
    """
    axes: Dict[str, plt.Axes] = {}

    # Determine positioning
    if not tables:
        fig, ax = plt.subplots(figsize=(12, 8))
        axes['main'] = ax
        return fig, axes

    if not charts:
        fig, ax = plt.subplots(figsize=(12, 6))
        axes['table'] = ax
        return fig, axes

    position = tables[0].get('visual_features', {}).get('position', 'below_chart')

    if position == 'above_chart':
        fig, (ax_table, ax_chart) = plt.subplots(
            2, 1, figsize=(12, 10),
            gridspec_kw={'height_ratios': [1, 3]}
        )
        axes['table'] = ax_table
        axes['main'] = ax_chart

    elif position == 'below_chart':
        fig, (ax_chart, ax_table) = plt.subplots(
            2, 1, figsize=(12, 10),
            gridspec_kw={'height_ratios': [3, 1]}
        )
        axes['main'] = ax_chart
        axes['table'] = ax_table

    elif position == 'beside_chart':
        fig, (ax_chart, ax_table) = plt.subplots(
            1, 2, figsize=(16, 8),
            gridspec_kw={'width_ratios': [2, 1]}
        )
        axes['main'] = ax_chart
        axes['table'] = ax_table

    else:  # 'standalone'
        fig, ax = plt.subplots(figsize=(12, 6))
        axes['table'] = ax

    return fig, axes


# ============================================================================
# MAIN CHART PLOTTING DISPATCHER
# ============================================================================

def plot_chart(
    ax: plt.Axes,
    chart: Dict[str, Any],
    function_registry: Dict[str, Optional[Callable]]
) -> None:
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
        return
    else:
        raise ValueError(f"Unsupported chart type: {chart_type}")