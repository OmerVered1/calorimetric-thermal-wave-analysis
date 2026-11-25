"""Chart specs of the Statistics tab: plain dataclasses that say WHAT to draw (series, colours, hover text, ids,
reference lines); the widgets only render them. Literal ports of the page's chart blocks (page.tsx)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ctwa.analysis.jsmath import js_number_to_string, js_round, js_to_fixed
from ctwa.analysis.references import LITERATURE, LITERATURE_COLORS
from ctwa.stats.aggregate import (bin_by_period, corr_matrix, distinct_dr, linear_fit, log_grid, mean, pair_segments,
                                  std_pop, theory_curve)
from ctwa.stats.model import (Y_BY_KEY, color_for, extract_x, extract_y, fmt_g, get_period, group_value, round10,
                              run_label_text)
from ctwa.stats.view_state import ALPHA_SERIES, ViewState

__all__ = ["Series", "RefLine", "Group", "HeatSpec", "ChartSpec", "TheoryInfo", "JS_COLORS", "build_builder_spec",
           "theory_info", "lit_ref_lines", "preset_ref_lines", "ALPHA_LABELS", "build_alpha_period_spec",
           "build_heat_loss_specs", "build_phase_specs", "build_temp_specs", "build_corr_spec",
           "corr_pair_to_builder"]

# The page's COLORS list (theory curves and preset lines).
JS_COLORS = ['#3498db', '#e74c3c', '#2ecc71', '#f39c12', '#9b59b6', '#1abc9c', '#e67e22', '#34495e', '#c0392b',
             '#16a085']
NAN = float("nan")


@dataclass
class Series:
    name: str
    color: str
    x: List[float]
    y: List[float]
    ids: List[Optional[int]]
    hover: List[str]
    mode: str                       # "markers" | "lines" | "lines+markers"
    symbol: str = "o"               # pyqtgraph symbol: o s d + x t
    filled: bool = True
    size: float = 7
    width: float = 1.0
    dash: str = "solid"             # solid | dash | dot | dashdot
    opacity: float = 1.0
    legend: bool = True
    legendgroup: Optional[str] = None
    yerr: Optional[List[float]] = None
    segments: bool = False          # x/y hold point pairs separated by NaN (raw <-> calibrated connectors)


@dataclass
class RefLine:
    y: float
    label: str
    color: str
    dash: str
    width: float


@dataclass
class Group:
    name: str
    color: str
    values: List[float]
    ids: List[Optional[int]]


@dataclass
class HeatSpec:
    labels: List[str]
    matrix: List[List[float]]
    text: List[List[str]]


@dataclass
class ChartSpec:
    kind: str                       # "xy" | "box" | "violin" | "bar" | "heatmap"
    title: str
    xlabel: str = ""
    ylabel: str = ""
    xlog: bool = False
    ylog: bool = False
    series: List[Series] = field(default_factory=list)
    ref_lines: List[RefLine] = field(default_factory=list)
    categories: List[Tuple[str, str]] = field(default_factory=list)   # (name, tick text "{name}\nn = {n}")
    groups: List[Group] = field(default_factory=list)
    heat: Optional[HeatSpec] = None
    height: int = 500


@dataclass
class TheoryInfo:
    defined: bool
    dr: Optional[float]
    mixed: List[float]              # all distinct dr (ascending) when the rows mix several, else []


def _js_text(v: Any) -> str:
    """A value as a JS template literal prints it (null stays "null")."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return js_number_to_string(float(v))
    return str(v)


def _distinct(values: Sequence[Any]) -> List[Any]:
    seen: List[Any] = []
    for v in values:
        if v not in seen:
            seen.append(v)
    return seen


# ------------------------------------------------------------------ reference lines

def lit_ref_lines(names: Sequence[str]) -> List[RefLine]:
    """Literature alphas the user ticked, in the table's order (flat dashed lines)."""
    return [RefLine(alpha, name, LITERATURE_COLORS[name], "dash", 1.5)
            for name, alpha in LITERATURE.items() if name in names]


def _selected_presets(presets: Sequence[Dict[str, Any]], ids: Sequence[int]) -> List[Dict[str, Any]]:
    return [p for p in presets if p.get("id") in ids]


def preset_ref_lines(presets: Sequence[Dict[str, Any]], ids: Sequence[int]) -> List[RefLine]:
    return [RefLine(p["alpha_mm2s"], "%s %s°C" % (p["material_name"], _js_text(p["temperature_c"])),
                    JS_COLORS[(i + 5) % len(JS_COLORS)], "dot", 2)
            for i, p in enumerate(_selected_presets(presets, ids))]


# ------------------------------------------------------------------ theory

_THEORY_Y = {"raw_phase_phi": "phase", "raw_lag_dt": "lag"}
_THEORY_X = ("Period (s)", "Frequency (Hz)")


def theory_info(rows: Sequence[Dict[str, Any]], view: ViewState) -> TheoryInfo:
    defined = view.y_metric in _THEORY_Y and view.x_axis in _THEORY_X
    drs = distinct_dr(rows)                      # most common first (a curve needs ONE dr)
    return TheoryInfo(defined, drs[0] if drs else None, sorted(drs) if len(drs) > 1 else [])


def _theory_series(rows: Sequence[Dict[str, Any]], view: ViewState, presets: Sequence[Dict[str, Any]]) -> List[Series]:
    info = theory_info(rows, view)
    selected = _selected_presets(presets, view.theory_ids)
    if not info.defined or not selected or info.dr is None:
        return []
    xs = [x for x in (extract_x(a, view.x_axis, view.period_source) for a in rows) if x is not None and x > 0]
    if not xs:
        return []
    xmin, xmax = min(xs), max(xs)
    if not xmax > xmin:
        return []
    grid = log_grid(xmin, xmax, 160)
    out: List[Series] = []
    for i, p in enumerate(selected):
        ys = theory_curve(p["alpha_mm2s"], info.dr, grid, view.x_axis, _THEORY_Y[view.y_metric])
        cx = [x for x, y in zip(grid, ys) if y is not None]
        cy = [y for y in ys if y is not None]
        alpha = _js_text(p["alpha_mm2s"])
        out.append(Series(
            name="%s %s°C (α=%s)" % (p["material_name"], _js_text(p["temperature_c"]), alpha),
            color=JS_COLORS[(i + 5) % len(JS_COLORS)], x=cx, y=cy, ids=[None] * len(cx),
            hover=["theory · α=%s mm²/s\nx: %s\ny: %s" % (alpha, fmt_g(x, 4), fmt_g(y, 4)) for x, y in zip(cx, cy)],
            mode="lines", width=2, dash="dash"))
    return out


# ------------------------------------------------------------------ the chart builder

def build_builder_spec(rows: Sequence[Dict[str, Any]], view: ViewState,
                       presets: Sequence[Dict[str, Any]]) -> Optional[ChartSpec]:
    if not rows:
        return None
    src = view.period_source
    meta = Y_BY_KEY[view.y_metric]
    ref_lines: List[RefLine] = []
    if meta.is_alpha:                                # theory curves are never drawn for alpha Y
        ref_lines = lit_ref_lines(view.lit_builder) + preset_ref_lines(presets, view.theory_ids)

    def ey(a: Dict[str, Any]) -> Optional[float]:
        return extract_y(a, view.y_metric, src)

    if view.chart_type in ("scatter", "line"):
        names = (_distinct([g for g in (group_value(a, view.color_by, src) for a in rows) if g is not None])
                 if view.color_by else ["All"])
        series: List[Series] = []
        for grp in names:
            subset = [a for a in rows if group_value(a, view.color_by, src) == grp] if view.color_by else list(rows)
            pts: List[Tuple[float, float, str, int]] = []
            for a in subset:
                xv, yv = extract_x(a, view.x_axis, src), ey(a)
                if xv is None or yv is None:
                    continue
                p = get_period(a, src)
                plabel = "%ds" % round10(p) if p is not None else "—"
                text = "%s | %s | %s | #%s" % (_js_text(a.get("model_name")), plabel, _js_text(a.get("test_date")),
                                               _js_text(a.get("id")))
                pts.append((xv, yv, text, a.get("id")))
            if view.chart_type == "line":
                pts.sort(key=lambda p: p[0])
            line = view.chart_type == "line"
            series.append(Series(
                name=grp, color=color_for(grp), x=[p[0] for p in pts], y=[p[1] for p in pts], ids=[p[3] for p in pts],
                hover=["%s\n%s: %s\n%s: %s" % (p[2], view.x_axis, fmt_g(p[0], 5), meta.label, fmt_g(p[1], 5))
                       for p in pts],
                mode="lines+markers" if line else "markers", size=6 if line else 8, width=2.0 if line else 1.0))
        trends: List[Series] = []
        if view.chart_type == "scatter":
            for s in series:
                fit = linear_fit(s.x, s.y)
                if fit:
                    xs = sorted(s.x)
                    trends.append(Series(
                        name="Trend (%s)" % s.name, color=s.color, x=[xs[0], xs[-1]],
                        y=[fit[0] * xs[0] + fit[1], fit[0] * xs[-1] + fit[1]], ids=[None, None], hover=["", ""],
                        mode="lines", width=1.5, dash="dot", legend=False))
        return ChartSpec(
            kind="xy", title="%s vs %s" % (meta.label, view.x_axis), xlabel=view.x_axis, ylabel=meta.label,
            xlog=view.log_x, ylog=view.log_y, series=series + trends + _theory_series(rows, view, presets),
            ref_lines=ref_lines, height=500)

    # box / violin / bar
    names = _distinct([g for g in (group_value(a, view.group_by, src) for a in rows) if g is not None])
    groups: List[Group] = []
    for grp in names:
        vals: List[float] = []
        ids: List[Optional[int]] = []
        for a in rows:
            if group_value(a, view.group_by, src) != grp:
                continue
            v = ey(a)
            if v is not None:
                vals.append(v)
                ids.append(a.get("id"))
        groups.append(Group(grp, color_for(grp), vals, ids))
    series = []
    if view.chart_type == "bar":
        for i, g in enumerate(groups):
            m = mean(g.values) if g.values else 0
            err = std_pop(g.values) if len(g.values) > 1 else 0
            series.append(Series(name=g.name, color=g.color, x=[float(i)], y=[m], ids=[None],
                                 hover=["%s\n%s: %s" % (g.name, meta.label, fmt_g(m, 5))], mode="markers", yerr=[err]))
    return ChartSpec(
        kind=view.chart_type, title="%s by %s" % (meta.label, view.group_by), xlabel=view.group_by, ylabel=meta.label,
        xlog=view.log_x, ylog=view.log_y, series=series, ref_lines=ref_lines,
        categories=[(g.name, "%s\nn = %d" % (g.name, len(g.values))) for g in groups], groups=groups, height=500)
