"""The save logic of the analysis page: literal port of lib/analysisRow.ts of the webapp.

The result row for Supabase, the step-3 plot saved as graph_image, and the
duplicate match. Python names follow the snake_case rule of the webapp's
camelCase (sourceFileName -> source_file_name).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ctwa.analysis.jsmath import js_ceil, js_div, js_max, js_min, js_to_fixed, js_trim
from ctwa.analysis.smoothing import smooth_to_shared_sine

__all__ = ["RowMeta", "build_analysis_plot", "build_analysis_row", "find_duplicate", "clean_for_json"]

# lib/materialColors.ts
SIGNAL_COLORS = {"source": "#1F5BB0", "response": "#E4572E"}

# Duplicate-analysis match tolerances (period & A1 "super close").
PERIOD_TOL_FRAC, PERIOD_TOL_FLOOR = 0.02, 1  # s
A1_TOL_FRAC, A1_TOL_FLOOR = 0.02, 0.5  # mW


@dataclass
class RowMeta:  # lib/analysisRow.ts
    model_name: str
    test_date: str
    test_time: str
    temperature: Optional[float]
    gas_atmosphere: str
    power_source_device: str
    power_response_device: str
    wave_type: str  # 'sine' | 'square'
    analysis_mode: str
    r1: float
    r2: float
    use_calibration: bool
    system_lag: float
    input_mode: str  # 'one' | 'two'
    day_offset: Optional[float] = None
    clock_ahead: Optional[float] = None
    source_file_name: Optional[str] = None  # one-file mode; left out of the row when None


def clean_for_json(obj: Any) -> Any:
    """Non-finite floats -> None (as JSON.stringify writes null), recursively through dicts, lists, tuples."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: clean_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_for_json(v) for v in obj]
    return obj


def _fmt_level(v: float, span: float) -> str:
    """A peak or trough level with enough decimals to tell it from the other."""
    if span > 0:
        d = js_min(4, js_max(1, js_ceil(-math.log10(span)) + 2))
    else:
        d = 1
    return js_to_fixed(v, int(d))


def _in_region(t: List[float], v: List[float], sel_min: float, sel_max: float):
    tf: List[float] = []
    vf: List[float] = []
    for i in range(len(t)):
        if t[i] >= sel_min and t[i] <= sel_max:
            tf.append(t[i])
            vf.append(v[i])
    return tf, vf


def _mean(v: List[float]) -> float:
    s = 0.0
    for x in v:
        s += x
    return js_div(s, len(v))


def _line(color: str, dash: str, width: float) -> Dict[str, Any]:
    return {"color": color, "dash": dash, "width": width}


def build_analysis_plot(synced, results, opts) -> Dict[str, Any]:
    """The step-3 "Stable Zone Analysis" figure (Plotly data + layout)."""
    wave_type, smooth_to_sine = opts.wave_type, opts.smooth_to_sine
    sel_min, sel_max = opts.sel_min, opts.sel_max

    # Single-sine fits over the selected region (when smoothing is enabled).
    smoothed_region = None
    if smooth_to_sine and wave_type != "square":
        t_src_s, v_src_s = _in_region(synced.t_src, synced.v_src, sel_min, sel_max)
        t_cal_s, v_cal_s = _in_region(synced.t_cal, synced.v_cal, sel_min, sel_max)
        if len(t_src_s) >= 10 and len(t_cal_s) >= 10:
            sm = smooth_to_shared_sine(t_src_s, v_src_s, t_cal_s, v_cal_s)
            if sm:
                smoothed_region = (t_src_s, sm[0], t_cal_s, sm[1])

    t_src_f, v_src_f = _in_region(synced.t_src, synced.v_src, sel_min, sel_max)
    t_cal_f, v_cal_f = _in_region(synced.t_cal, synced.v_cal, sel_min, sel_max)
    # When smoothing is on, show the fitted single sines instead of the raw signals.
    if smoothed_region:
        t_src_f, v_src_f, t_cal_f, v_cal_f = smoothed_region

    src_mean = _mean(v_src_f)
    cal_mean = _mean(v_cal_f)

    def levels_ok(peak: float, trough: float) -> bool:
        return math.isfinite(peak) and math.isfinite(trough) and peak > trough and not (peak == 0 and trough == 0)

    src_levels = levels_ok(results.mean_peak_src, results.mean_trough_src)
    cal_levels = levels_ok(results.mean_peak_cal, results.mean_trough_cal)
    src_c, resp_c = SIGNAL_COLORS["source"], SIGNAL_COLORS["response"]

    shapes: List[Dict[str, Any]] = [
        {"type": "line", "x0": sel_min, "x1": sel_max, "y0": src_mean, "y1": src_mean,
         "line": _line(src_c, "dash", 1)},
        {"type": "line", "x0": sel_min, "x1": sel_max, "y0": cal_mean, "y1": cal_mean, "yref": "y2",
         "line": _line(resp_c, "dash", 1)},
    ]
    # Mean peak/trough levels, when the mode reports them.
    if src_levels:
        for lv in (results.mean_peak_src, results.mean_trough_src):
            shapes.append({"type": "line", "x0": sel_min, "x1": sel_max, "y0": lv, "y1": lv,
                           "line": _line("#27ae60", "dot", 2)})
    if cal_levels:
        for lv in (results.mean_peak_cal, results.mean_trough_cal):
            shapes.append({"type": "line", "x0": sel_min, "x1": sel_max, "yref": "y2", "y0": lv, "y1": lv,
                           "line": _line("#f39c12", "dot", 2)})
    for tm, color in ((results.marker_src_time, src_c), (results.marker_src2_time, src_c),
                      (results.marker_cal_time, resp_c)):
        shapes.append({"type": "line", "x0": tm, "x1": tm, "y0": 0, "y1": 1, "yref": "paper",
                       "line": _line(color, "dashdot", 1.5)})

    annotations: List[Dict[str, Any]] = [
        {"x": results.marker_src_time, "y": 1.05, "yref": "paper", "text": "Src Peak 1",
         "showarrow": False, "font": {"color": src_c, "size": 11}},
        {"x": results.marker_src2_time, "y": 1.05, "yref": "paper", "text": "Src Peak 2",
         "showarrow": False, "font": {"color": src_c, "size": 11}},
        {"x": results.marker_cal_time, "y": 1.05, "yref": "paper", "text": "Resp Peak",
         "showarrow": False, "font": {"color": resp_c, "size": 11}},
    ]
    bg = "rgba(255,255,255,0.8)"
    if src_levels:
        span = results.mean_peak_src - results.mean_trough_src
        annotations.append({
            "x": sel_min, "y": results.mean_peak_src, "xanchor": "left",
            "text": f"  Src peak: {_fmt_level(results.mean_peak_src, span)}",
            "showarrow": False, "font": {"color": "#27ae60", "size": 10, "family": "monospace"}, "bgcolor": bg})
        annotations.append({
            "x": sel_min, "y": results.mean_trough_src, "xanchor": "left",
            "text": f"  Src trough: {_fmt_level(results.mean_trough_src, span)}",
            "showarrow": False, "font": {"color": "#27ae60", "size": 10, "family": "monospace"}, "bgcolor": bg})
    if cal_levels:
        span = results.mean_peak_cal - results.mean_trough_cal
        annotations.append({
            "x": sel_max, "y": results.mean_peak_cal, "xanchor": "right", "yref": "y2",
            "text": f"Resp peak: {_fmt_level(results.mean_peak_cal, span)}  ",
            "showarrow": False, "font": {"color": "#f39c12", "size": 10, "family": "monospace"}, "bgcolor": bg})
        annotations.append({
            "x": sel_max, "y": results.mean_trough_cal, "xanchor": "right", "yref": "y2",
            "text": f"Resp trough: {_fmt_level(results.mean_trough_cal, span)}  ",
            "showarrow": False, "font": {"color": "#f39c12", "size": 10, "family": "monospace"}, "bgcolor": bg})

    return {
        "data": [
            {"x": t_src_f, "y": v_src_f, "name": "Source", "type": "scatter", "mode": "lines",
             "line": {"color": src_c, "width": 2}},
            {"x": t_cal_f, "y": v_cal_f, "name": "Response", "type": "scatter", "mode": "lines",
             "line": {"color": resp_c, "width": 2}, "yaxis": "y2"},
        ],
        "layout": {
            "title": {"text": f"Stable Zone Analysis — Δt = {js_to_fixed(results.raw_lag_dt, 2)}s"},
            "height": 500,
            "xaxis": {"title": {"text": "Time (s)"}},
            "yaxis": {"title": {"text": "Source Power (mW)", "font": {"color": src_c}}, "side": "left"},
            "yaxis2": {"title": {"text": "Response Power (mW)", "font": {"color": resp_c}},
                       "side": "right", "overlaying": "y"},
            "legend": {"orientation": "h", "y": 1.12},
            "hovermode": "x unified",
            "shapes": shapes,
            "annotations": annotations,
            "margin": {"t": 60, "b": 50},
        },
    }


def _dumps(obj: Any) -> str:
    """JSON.stringify: no spaces, non-finite numbers as null."""
    return json.dumps(clean_for_json(obj), separators=(",", ":"), allow_nan=False, ensure_ascii=False)


def build_analysis_row(results, meta: RowMeta, plot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The row the page inserts into `analyses` (free text trimmed; extra_data only when non-empty)."""
    cal = meta.use_calibration
    row: Dict[str, Any] = {
        # Free text is trimmed: a trailing space once split "unk foam" into two groups.
        "model_name": js_trim(meta.model_name),
        "test_date": js_trim(meta.test_date),
        "test_time": js_trim(meta.test_time),
        "temperature_c": meta.temperature,
        "power_source_device": js_trim(meta.power_source_device),
        "power_response_device": js_trim(meta.power_response_device),
        "gas_atmosphere": js_trim(meta.gas_atmosphere),
        "wave_type": meta.wave_type,
        "analysis_mode": "Fourier" if meta.wave_type == "square" else meta.analysis_mode,
        "r1_mm": meta.r1,
        "r2_mm": meta.r2,
        "amplitude_a1": results.amplitude_a1,
        "amplitude_a2": results.amplitude_a2,
        "period_t": results.period_t,
        "frequency_f": results.frequency_f,
        "period_t_resp": results.period_t_resp,
        "frequency_f_resp": results.frequency_f_resp,
        "angular_freq_w": results.angular_freq_w,
        "raw_lag_dt": results.raw_lag_dt,
        "raw_phase_phi": results.raw_phase_phi,
        "ln_term": results.ln_term,
        "alpha_combined_raw": results.alpha_combined_raw,
        "alpha_phase_raw": results.alpha_phase_raw,
        "use_calibration": cal,
        "system_lag": meta.system_lag if cal else None,
        "net_lag_dt": results.net_lag_dt if cal else None,
        "net_phase_phi": results.net_phase_phi if cal else None,
        "alpha_combined_cal": results.alpha_combined_cal if cal else None,
        "alpha_phase_cal": results.alpha_phase_cal if cal else None,
    }
    # An optional result the mode did not report is undefined in the webapp, which
    # the insert drops: leave the key out rather than writing null.
    for key in ("period_t_resp", "frequency_f_resp", "alpha_combined_raw"):
        if row[key] is None:
            del row[key]
    if cal and row["alpha_combined_cal"] is None:
        del row["alpha_combined_cal"]
    if meta.source_file_name is not None:
        row["c80_filename"] = meta.source_file_name
    # What the table has no column for: the lag's uncertainty and how the two clocks were aligned.
    extra: Dict[str, Any] = {}
    if results.lag_se is not None:
        extra["lag_se_s"] = results.lag_se
        if results.lag_se_source is not None:  # undefined is dropped by JSON.stringify
            extra["lag_se_source"] = results.lag_se_source
    if results.lag_cycles:
        extra["lag_cycles"] = results.lag_cycles
    if meta.input_mode == "two" and meta.day_offset:
        extra["day_offset"] = meta.day_offset
    if meta.input_mode == "two" and meta.clock_ahead:
        extra["clock_ahead_s"] = meta.clock_ahead
    if extra:
        row["extra_data"] = _dumps(extra)
    row = clean_for_json(row)
    # Save the analysis plot as Plotly JSON so the History page can display it.
    if plot:
        try:
            row["graph_image"] = _dumps({"data": plot["data"], "layout": plot["layout"]})
        except (TypeError, ValueError):
            pass  # ignore serialization errors
    return row


def find_duplicate(candidates: List[Dict[str, Any]], row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Same sample + method with very close period & A1 (candidates: rows of the same test date)."""
    saved_mode = row["analysis_mode"]
    pv, a1 = row["period_t"], row["amplitude_a1"]
    model_name = row["model_name"]

    def num(x):
        return 0 if x is None else x  # JS: null counts as 0 in arithmetic

    for c in candidates:
        name = c.get("model_name")
        if (name is not None
                and js_trim(name).lower() == js_trim(model_name).lower()
                and c.get("analysis_mode") == saved_mode
                and abs(num(c.get("period_t")) - pv) <= js_max(PERIOD_TOL_FLOOR, PERIOD_TOL_FRAC * pv)
                and abs(num(c.get("amplitude_a1")) - a1) <= js_max(A1_TOL_FLOOR, A1_TOL_FRAC * a1)):
            return c
    return None
