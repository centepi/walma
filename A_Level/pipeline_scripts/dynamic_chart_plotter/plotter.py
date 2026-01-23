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
)

from .overlays import (
    plot_labeled_point,
    plot_shaded_region,
    plot_polygon,
)

# ✅ NEW: split geometry modules
from .geometry_renderer import plot_geometry
from .geometry_bounds import compute_geometry_bounds

from .utils import setup_plot_appearance, _coerce_bin_pair


def dynamic_chart_plotter(config: Dict[str, Any]) -> plt.Figure:
    """
    Dynamic function to plot various charts and graphs based on JSON configuration.
    """
    if not isinstance(config, dict):
        raise TypeError("Config must be a dictionary")

    if (
        "charts" not in config
        and "graphs" not in config
        and isinstance(config.get("type"), str)
    ):
        config = {"charts": [config]}

    charts = config.get("charts", config.get("graphs", []))
    if charts is None:
        charts = []
    if not isinstance(charts, list):
        raise TypeError("'charts'/'graphs' must be a list of chart objects")

    layout_mode = config.get("layout", "single")

    tables = [
        c for c in charts
        if isinstance(c, dict) and str(c.get("type", "")).strip().lower() == "table"
    ]
    non_tables = [
        c for c in charts
        if isinstance(c, dict) and str(c.get("type", "")).strip().lower() != "table"
    ]

    # ------------------------------------------------------------------------
    # PER-CHART "HIDE VALUES" SUPPORT
    # ------------------------------------------------------------------------
    try:
        if "show_axis_numbers" not in config:
            wants_hide = False
            for c in non_tables:
                if not isinstance(c, dict):
                    continue
                vf = c.get("visual_features") or {}
                if isinstance(vf, dict) and bool(vf.get("hide_values", False)):
                    wants_hide = True
                    break
            if wants_hide:
                config["show_axis_numbers"] = False
    except Exception:
        pass

    # ------------------------------------------------------------------------
    # USABILITY DEFAULTS
    # ------------------------------------------------------------------------
    try:
        chart_types = [
            str(c.get("type", "")).strip().lower()
            for c in non_tables
            if isinstance(c, dict)
        ]

        data_reading_types = {"histogram", "bar", "scatter", "cumulative", "box_plot"}
        if any(t in data_reading_types for t in chart_types):
            if "show_axis_numbers" not in config:
                config["show_axis_numbers"] = True

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

                existing_label = str(c.get("label", "") or "").strip()
                if not existing_label:
                    existing_label = str(c.get("id", "") or "").strip() or f"g{i}"

                candidate = existing_label
                if candidate in used_labels:
                    candidate = f"{candidate}{i}"
                used_labels.add(candidate)
                c["label"] = candidate
    except Exception:
        pass

    # ------------------------------------------------------------------------
    # GEOMETRY AUTO-BOUNDS
    #
    # ✅ FIX: Mark auto-computed bounds so we DON'T treat them like teacher intent.
    # This lets us do robust post-plot autoscale + padding + square viewport.
    # ------------------------------------------------------------------------
    try:
        if not config.get("global_axes_range") and not config.get("axes_range"):
            has_geometry = any(
                isinstance(c, dict) and str(c.get("type", "")).strip().lower() == "geometry"
                for c in non_tables
            )
            if has_geometry:
                bounds = compute_geometry_bounds({"charts": non_tables})
                if isinstance(bounds, dict):
                    config["axes_range"] = bounds
                    config["_auto_axes_range"] = True  # ✅ NEW
                    config.setdefault("equal_aspect", True)
    except Exception:
        pass

    # ------------------------------------------------------------------------
    # HISTOGRAM NORMALISATION
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

            if vf.get("heights") is not None:
                continue

            raw_bins = vf.get("bins", [])
            freqs = vf.get("frequencies", [])

            if not raw_bins or not freqs:
                continue
            if len(raw_bins) != len(freqs):
                continue

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
        pass

    if layout_mode == "composite" or tables:
        fig, axes = create_composite_layout(config, tables, non_tables)
    else:
        fig, ax = plt.subplots(figsize=(12, 8), constrained_layout=True)
        axes = {"main": ax}

    function_registry: Dict[str, Optional[Callable]] = {}

    def _apply_preplot_viewport(ax: plt.Axes, cfg: Dict[str, Any]) -> None:
        axes_range = cfg.get("global_axes_range", cfg.get("axes_range"))
        if isinstance(axes_range, dict):
            ax.set_xlim(axes_range.get("x_min", -10), axes_range.get("x_max", 10))
            ax.set_ylim(axes_range.get("y_min", -10), axes_range.get("y_max", 10))
        if cfg.get("equal_aspect"):
            ax.set_aspect("equal", adjustable="box")

    # ✅ FIX: treat auto axes_range as NOT explicit
    def _has_explicit_axes_range(cfg: Dict[str, Any]) -> bool:
        if bool(cfg.get("_auto_axes_range", False)):
            return False
        ar = cfg.get("global_axes_range", cfg.get("axes_range"))
        return isinstance(ar, dict)

    def _autoscale_with_padding(ax: plt.Axes, pad_frac: float = 0.08) -> None:
        try:
            ax.relim(visible_only=True)
            ax.autoscale_view()

            x0, x1 = ax.get_xlim()
            y0, y1 = ax.get_ylim()

            dx = float(x1) - float(x0)
            dy = float(y1) - float(y0)

            if dx == 0:
                dx = 1.0
            if dy == 0:
                dy = 1.0

            px = dx * float(pad_frac)
            py = dy * float(pad_frac)

            ax.set_xlim(x0 - px, x1 + px)
            ax.set_ylim(y0 - py, y1 + py)
        except Exception:
            pass

    # ✅ NEW: square viewport when equal_aspect=True (prevents tall skinny circles)
    def _square_viewport_if_equal_aspect(ax: plt.Axes, pad_frac: float = 0.08) -> None:
        try:
            if ax.get_aspect() != "equal":
                return

            x0, x1 = ax.get_xlim()
            y0, y1 = ax.get_ylim()

            cx = 0.5 * (float(x0) + float(x1))
            cy = 0.5 * (float(y0) + float(y1))

            dx = float(x1) - float(x0)
            dy = float(y1) - float(y0)

            if dx == 0:
                dx = 1.0
            if dy == 0:
                dy = 1.0

            half = 0.5 * max(dx, dy)
            half = half * (1.0 + float(pad_frac))

            ax.set_xlim(cx - half, cx + half)
            ax.set_ylim(cy - half, cy + half)
        except Exception:
            pass

    def _iter_all_labeled_points(cfg: Dict[str, Any], charts_list: List[Dict[str, Any]]):
        pts = []
        lp = cfg.get("labeled_points")
        if isinstance(lp, list):
            pts.extend([p for p in lp if isinstance(p, dict)])

        for c in charts_list:
            if not isinstance(c, dict):
                continue
            lp2 = c.get("labeled_points")
            if isinstance(lp2, list):
                pts.extend([p for p in lp2 if isinstance(p, dict)])
            vf = c.get("visual_features")
            if isinstance(vf, dict):
                lp3 = vf.get("labeled_points")
                if isinstance(lp3, list):
                    pts.extend([p for p in lp3 if isinstance(p, dict)])
        return pts

    if "main" in axes:
        _apply_preplot_viewport(axes["main"], config)

        for chart in non_tables:
            plot_chart(axes["main"], chart, function_registry)

        for point in _iter_all_labeled_points(config, non_tables):
            plot_labeled_point(axes["main"], point)

        shaded_regions = config.get("shaded_regions")
        if isinstance(shaded_regions, list):
            for region in shaded_regions:
                if isinstance(region, dict):
                    plot_shaded_region(axes["main"], region, function_registry)

        # ✅ FIX: apply appearance WITHOUT re-forcing auto bounds
        style_cfg = dict(config)
        if bool(style_cfg.get("_auto_axes_range", False)):
            style_cfg.pop("axes_range", None)
            style_cfg.pop("global_axes_range", None)

        setup_plot_appearance(axes["main"], style_cfg)

        # ✅ FIX: post-plot viewport correction for auto-bounds
        if not _has_explicit_axes_range(config):
            _autoscale_with_padding(axes["main"], pad_frac=0.08)
            _square_viewport_if_equal_aspect(axes["main"], pad_frac=0.06)

    if "table" in axes:
        for table in tables:
            plot_table(axes["table"], table)

    if "title" in config and layout_mode == "composite":
        fig.suptitle(config["title"], fontsize=16, fontweight="bold", y=0.99)

    return fig


def create_composite_layout(
    config: Dict[str, Any],
    tables: List[Dict[str, Any]],
    charts: List[Dict[str, Any]],
) -> tuple:
    axes: Dict[str, plt.Axes] = {}

    if not tables:
        fig, ax = plt.subplots(figsize=(12, 8), constrained_layout=True)
        axes["main"] = ax
        return fig, axes

    if not charts:
        n_rows = 0
        try:
            vf = (tables[0] or {}).get("visual_features") or {}
            rows = vf.get("rows") or []
            n_rows = len(rows) if isinstance(rows, list) else 0
        except Exception:
            n_rows = 0

        total_rows = max(1, n_rows + 1)

        fig_h = 2.2 + 0.55 * total_rows
        fig_h = max(3.2, min(10.0, fig_h))

        fig, ax = plt.subplots(figsize=(12, fig_h), constrained_layout=True)
        axes["table"] = ax
        return fig, axes

    position = tables[0].get("visual_features", {}).get("position", "below_chart")

    if position == "above_chart":
        fig, (ax_table, ax_chart) = plt.subplots(
            2,
            1,
            figsize=(12, 10),
            gridspec_kw={"height_ratios": [1, 3]},
            constrained_layout=True,
        )
        axes["table"] = ax_table
        axes["main"] = ax_chart

    elif position == "below_chart":
        fig, (ax_chart, ax_table) = plt.subplots(
            2,
            1,
            figsize=(12, 10),
            gridspec_kw={"height_ratios": [3, 1]},
            constrained_layout=True,
        )
        axes["main"] = ax_chart
        axes["table"] = ax_table

    elif position == "beside_chart":
        fig, (ax_chart, ax_table) = plt.subplots(
            1,
            2,
            figsize=(16, 8),
            gridspec_kw={"width_ratios": [2, 1]},
            constrained_layout=True,
        )
        axes["main"] = ax_chart
        axes["table"] = ax_table

    else:
        fig, ax = plt.subplots(figsize=(12, 6), constrained_layout=True)
        axes["table"] = ax

    return fig, axes


def plot_chart(
    ax: plt.Axes,
    chart: Dict[str, Any],
    function_registry: Dict[str, Optional[Callable]],
) -> None:
    chart_type = str(chart.get("type", "function")).strip().lower()

    if chart_type == "function":
        plot_explicit_function(ax, chart, function_registry)
    elif chart_type == "parametric":
        plot_parametric_curve(ax, chart, function_registry)
    elif chart_type == "scatter":
        plot_scatter(ax, chart, function_registry)
    elif chart_type == "bar":
        plot_bar_chart(ax, chart, function_registry)
    elif chart_type == "histogram":
        plot_histogram(ax, chart, function_registry)
    elif chart_type == "box_plot":
        plot_box_plot(ax, chart, function_registry)
    elif chart_type == "cumulative":
        plot_cumulative_frequency(ax, chart, function_registry)
    elif chart_type == "polygon":
        plot_polygon(ax, chart, function_registry)
    elif chart_type == "geometry":
        plot_geometry(ax, chart, function_registry)
    elif chart_type == "table":
        return
    else:
        raise ValueError(f"Unsupported chart type: {chart_type}")