"""Logic of the Compare page, ported literally from app/analyses-viewer/page.tsx (PARAM_ROWS, METRICS, the
overlay useMemo, differingRows). No Qt."""
from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from ctwa.analysis.jsmath import js_div, js_to_fixed, js_to_precision, js_truthy
from ctwa.results.helpers import format_alpha
from ctwa.ui.results.figure_model import StoredFigure, parse_graph
from ctwa.ui.results.fmt import js_str, label_of

DASH = "—"
MAX_RUNS = 4
_PARSED_MAX = 20
_parsed: "OrderedDict[str, Any]" = OrderedDict()   # raw graph text -> parsed figure (LRU)

# Two colours per run (source, response), so up to four runs stay distinct.
COMPARE_COLORS = ["#1F5BB0", "#E4572E", "#2A9D8F", "#E9A23B", "#8E44AD", "#3BA3D9", "#16A085", "#D35D9B",
                  "#A67C00", "#C0392B"]

# Which signal a guide line of a stored graph belongs to (lower case). Graphs saved since Nov 2026 use the
# CTWA colours; older ones the previous blue / red.
SRC_GUIDE_COLORS = {"#27ae60", "#3498db", "#1f5bb0"}
RESP_GUIDE_COLORS = {"#f39c12", "#e74c3c", "#e4572e"}


def run_colors(i: int) -> Tuple[str, str]:
    """(source colour, response colour) of the i-th run."""
    n = len(COMPARE_COLORS)
    return COMPARE_COLORS[(2 * i) % n], COMPARE_COLORS[(2 * i + 1) % n]


# ---- parameter table ----

def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _num_or_dash(v: Any, digits: int) -> str:
    return js_to_fixed(v, digits) if _is_num(v) and math.isfinite(v) else DASH


def _alpha_str(v: Any) -> str:
    return format_alpha(v) if _is_num(v) and v > 0 else DASH


def _or_dash(v: Any) -> str:
    """`v || '—'`"""
    return js_str(v) if js_truthy(v) else DASH


def _nullish_dash(v: Any) -> str:
    """`v ?? '—'`"""
    return DASH if v is None else js_str(v)


def _fixed_getter(key: str, digits: int) -> Callable[[Dict[str, Any]], str]:
    return lambda a: _num_or_dash(a.get(key), digits)


PARAM_ROWS: List[Tuple[str, Callable[[Dict[str, Any]], str]]] = [
    ("Model", lambda a: js_str(a.get("model_name"))),
    ("Test date", lambda a: js_str(a.get("test_date"))),
    ("Test time", lambda a: _nullish_dash(a.get("test_time"))),
    ("Temperature (°C)", lambda a: DASH if a.get("temperature_c") is None else js_str(a.get("temperature_c"))),
    ("Gas atmosphere", lambda a: _or_dash(a.get("gas_atmosphere"))),
    ("Power source device", lambda a: _or_dash(a.get("power_source_device"))),
    ("Power response device", lambda a: _or_dash(a.get("power_response_device"))),
    ("Wave type", lambda a: _nullish_dash(a.get("wave_type"))),
    ("Analysis mode", lambda a: js_str(a.get("analysis_mode"))),
    ("r₁ (mm)", _fixed_getter("r1_mm", 2)),
    ("r₂ (mm)", _fixed_getter("r2_mm", 2)),
    ("A₁ (mW)", _fixed_getter("amplitude_a1", 4)),
    ("A₂ (mW)", _fixed_getter("amplitude_a2", 4)),
    ("Src Period (s)", _fixed_getter("period_t", 2)),
    ("Resp Period (s)", _fixed_getter("period_t_resp", 2)),
    ("Src f (Hz)", _fixed_getter("frequency_f", 6)),
    ("Resp f (Hz)", _fixed_getter("frequency_f_resp", 6)),
    ("ω (rad/s)", _fixed_getter("angular_freq_w", 5)),
    ("Δt (s)", _fixed_getter("raw_lag_dt", 2)),
    ("φ (rad)", _fixed_getter("raw_phase_phi", 4)),
    ("ln term", _fixed_getter("ln_term", 4)),
    ("α Combined raw (mm²/s)", lambda a: _alpha_str(a.get("alpha_combined_raw"))),
    ("α Phase raw (mm²/s)", lambda a: _alpha_str(a.get("alpha_phase_raw"))),
    ("Calibration", lambda a: "✓" if js_truthy(a.get("use_calibration")) else "✗"),
    ("System lag (s)", _fixed_getter("system_lag", 1)),
    ("Net Δt (s)", _fixed_getter("net_lag_dt", 2)),
    ("α Combined cal (mm²/s)", lambda a: _alpha_str(a.get("alpha_combined_cal"))),
    ("α Phase cal (mm²/s)", lambda a: _alpha_str(a.get("alpha_phase_cal"))),
]
_PARAM_BY_LABEL = dict(PARAM_ROWS)


def param_value(label: str, row: Dict[str, Any]) -> str:
    return _PARAM_BY_LABEL[label](row)


def differing_rows(rows: List[Dict[str, Any]]) -> Set[str]:
    """Labels of the parameter rows whose text is not the same in every run."""
    if len(rows) < 2:
        return set()
    return {label for label, get in PARAM_ROWS if len({get(a) for a in rows}) > 1}


# ---- metrics ----

def _scaled_positive(key: str) -> Callable[[Dict[str, Any]], Optional[float]]:
    """`(a[key] ?? 0) > 0 ? a[key] * 1e6 : null`"""
    def get(a: Dict[str, Any]) -> Optional[float]:
        v = a.get(key)
        return v * 1e6 if _is_num(v) and v > 0 else None
    return get


def _raw(key: str) -> Callable[[Dict[str, Any]], Optional[float]]:
    return lambda a: a.get(key)


def _ratio(a: Dict[str, Any]) -> Optional[float]:
    a2 = a.get("amplitude_a2")
    if _is_num(a2) and a2 == 0:
        return None
    # JS: a1 / null is a1 / 0 (Infinity), null / null is NaN
    return js_div(float(a.get("amplitude_a1") or 0), float(a2 or 0))


METRICS: List[Tuple[str, str, Callable[[Dict[str, Any]], Optional[float]]]] = [
    ("alpha_comb_raw", "α Combined (raw) (mm²/s)", _scaled_positive("alpha_combined_raw")),
    ("alpha_phase_raw", "α Phase (raw) (mm²/s)", _scaled_positive("alpha_phase_raw")),
    ("alpha_comb_cal", "α Combined (cal) (mm²/s)", _scaled_positive("alpha_combined_cal")),
    ("alpha_phase_cal", "α Phase (cal) (mm²/s)", _scaled_positive("alpha_phase_cal")),
    ("raw_lag_dt", "Δt (s)", _raw("raw_lag_dt")),
    ("net_lag_dt", "Net Δt (s)", _raw("net_lag_dt")),
    ("raw_phase_phi", "φ (rad)", _raw("raw_phase_phi")),
    ("ln_term", "ln term", _raw("ln_term")),
    ("amplitude_a1", "A₁ (mW)", _raw("amplitude_a1")),
    ("amplitude_a2", "A₂ (mW)", _raw("amplitude_a2")),
    ("a1_a2", "A₁/A₂ ratio", _ratio),
    ("period_t", "Src Period (s)", _raw("period_t")),
    ("period_t_resp", "Resp Period (s)", _raw("period_t_resp")),
    ("frequency_f", "Src f (Hz)", _raw("frequency_f")),
    ("angular_freq_w", "ω (rad/s)", _raw("angular_freq_w")),
    ("temperature_c", "Temperature (°C)", _raw("temperature_c")),
    ("system_lag", "System lag (s)", _raw("system_lag")),
]
_METRIC_BY_KEY = {k: g for k, _, g in METRICS}


def metric_value(key: str, row: Dict[str, Any]) -> Optional[float]:
    return _METRIC_BY_KEY[key](row)


def metric_text(v: Optional[float]) -> str:
    """The label beside a metric dot: toFixed(0) from 1000 up, else 4 significant digits."""
    if v is None:
        return DASH
    return js_to_fixed(v, 0) if abs(v) >= 1000 else js_to_precision(v, 4)


# ---- waveform overlay ----

@dataclass
class OverlayOptions:
    signal: str = "both"         # "source" | "response" | "both"
    align: bool = True
    norm_amp: bool = False
    norm_time: bool = False
    guides: bool = True


@dataclass
class OverlayTrace:
    name: str
    x: List[float]
    y: List[float]
    color: str
    dash: str                    # "solid" | "dash"


@dataclass
class OverlayLine:
    x0: float
    x1: float
    y0: float
    y1: float
    yref: str                    # "y" | "paper"
    color: str
    dash: str                    # "dot" | "dashdot"
    label: Optional[str] = None


@dataclass
class OverlayRun:
    traces: List[OverlayTrace]
    lines: List[OverlayLine]
    box_text: Optional[str] = None   # None when guides are off (the webapp draws no value box then)


def guide_levels(fig: StoredFigure) -> Tuple[List[float], List[float], List[float], List[float]]:
    """(source levels, response levels, source markers, response markers) of the stored guide shapes, in
    stored order. Only horizontal levels in the two level colours and vertical markers in the signal
    colours count; everything else (means, other colours, non-lines) is ignored."""
    src_levels: List[float] = []
    resp_levels: List[float] = []
    src_markers: List[float] = []
    resp_markers: List[float] = []
    for sh in fig.shapes:
        c = sh.color.lower()
        vertical = sh.x0 == sh.x1
        level = sh.y0 == sh.y1 and sh.x0 != sh.x1
        if level and c == "#27ae60":
            src_levels.append(sh.y0)
        elif level and c == "#f39c12":
            resp_levels.append(sh.y0)
        elif vertical and c in SRC_GUIDE_COLORS:
            src_markers.append(sh.x0)
        elif vertical and c in RESP_GUIDE_COLORS:
            resp_markers.append(sh.x0)
    return src_levels, resp_levels, src_markers, resp_markers


def box_text(row: Dict[str, Any]) -> str:
    """The always-visible value box of a run: "Model #id:  Δt=105 s · A₁=12.3 · A₂=5.7 mW"."""
    model = "null" if row.get("model_name") is None else js_str(row.get("model_name"))
    return "%s #%s:  Δt=%s s · A₁=%s · A₂=%s mW" % (
        model, js_str(row.get("id")), _num_or_dash(row.get("raw_lag_dt"), 0),
        _num_or_dash(row.get("amplitude_a1"), 1), _num_or_dash(row.get("amplitude_a2"), 1))


def _finite_extent(vals: List[float]) -> Tuple[float, float]:
    lo, hi = math.inf, -math.inf
    for v in vals:
        if v < lo:
            lo = v
        if v > hi:
            hi = v
    return lo, hi


def _parse_cached(raw: Optional[str]):
    """parse_graph with a small LRU keyed by the raw text: toggling an option re-draws without re-parsing
    megabytes of JSON, and changed text is a different key."""
    if not isinstance(raw, str):
        return parse_graph(raw)
    hit = _parsed.get(raw)
    if hit is not None:
        _parsed.move_to_end(raw)
        return hit
    fig = parse_graph(raw)
    _parsed[raw] = fig
    while len(_parsed) > _PARSED_MAX:
        _parsed.popitem(last=False)
    return fig


def overlay_run(row: Dict[str, Any], raw_graph: Optional[str], index: int,
                opts: OverlayOptions) -> Optional[OverlayRun]:
    """One run's traces and guide lines for the overlay, or None when it has no stored Plotly figure with
    a Source or Response trace (the page lists such runs in its "no stored waveform" note)."""
    fig = _parse_cached(raw_graph)
    if not isinstance(fig, StoredFigure):
        return None
    wanted = [t for t in fig.traces if t.name in ("Source", "Response")]
    if not wanted:
        return None
    src_color, resp_color = run_colors(index)

    # Per-run time range across the kept (both) traces.
    all_x = [x for t in wanted for x in t.x if x == x]
    x0, x_max = _finite_extent(all_x)
    if not math.isfinite(x0):
        x0 = 0.0
    span = x_max - x0 if x_max > x0 else 1.0

    if opts.norm_time:
        def transform(x: float) -> float:
            return (x - x0) / span
    elif opts.align:
        def transform(x: float) -> float:
            return x - x0
    else:
        def transform(x: float) -> float:
            return x
    right_x = transform(x_max)

    label = label_of(row)
    traces: List[OverlayTrace] = []
    for tr in wanted:
        is_source = tr.name == "Source"
        if opts.signal == "source" and not is_source:
            continue
        if opts.signal == "response" and is_source:
            continue
        xs = [transform(x) for x in tr.x]
        ys = list(tr.y)
        if opts.norm_amp:
            lo, hi = _finite_extent(ys)
            rng = hi - lo
            ys = [(y - lo) / rng for y in ys] if rng > 0 else [0.0] * len(ys)
        traces.append(OverlayTrace(name="%s — %s" % (label, "Source" if is_source else "Response"), x=xs, y=ys,
                                   color=src_color if is_source else resp_color,
                                   dash="solid" if is_source else "dash"))

    lines: List[OverlayLine] = []
    if opts.guides and not opts.norm_amp:
        src_levels, resp_levels, src_markers, resp_markers = guide_levels(fig)
        show_src = opts.signal != "response"
        show_resp = opts.signal != "source"
        labelled = index == 0   # only the first run is annotated

        def draw_levels(levels: List[float], color: str, tag: str) -> None:
            for k, y in enumerate(sorted(levels, reverse=True)):     # peak first
                name = "%s peak" % tag if k == 0 else "%s trough" % tag
                text = "  %s (%s mW)" % (name, _num_or_dash(y, 1)) if labelled else None
                lines.append(OverlayLine(transform(x0), right_x, y, y, "y", color, "dot", text))

        def draw_marker(x: float, color: str, text: str) -> None:
            tx = transform(x)
            lines.append(OverlayLine(tx, tx, 0, 1, "paper", color, "dashdot", text if labelled and text else None))

        if show_src:
            draw_levels(src_levels, src_color, "A₁")
        if show_resp:
            draw_levels(resp_levels, resp_color, "A₂")
        if show_src:
            for k, x in enumerate(src_markers):
                draw_marker(x, src_color, "Src peak" if k == 0 else "")
        if show_resp:
            for x in resp_markers:
                draw_marker(x, resp_color, "Resp peak (Δt=%ss)" % _num_or_dash(row.get("raw_lag_dt"), 0))

    return OverlayRun(traces=traces, lines=lines, box_text=box_text(row) if opts.guides else None)
