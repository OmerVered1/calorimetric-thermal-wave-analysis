"""Process side of the analysis: loading a run file and analysing it (no Qt).

These functions run inside the long-lived worker process started by
ctwa.ui.analysis_worker.AnalysisWorker, so that the heavy maths never shares
the GUI process's GIL with the sweep thread."""

from __future__ import annotations

import math
import os
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, List, NamedTuple, Optional, Tuple

from ctwa.analysis.parser import decode_bytes, parse_combined_file
from ctwa.analysis.pipeline import default_selection, load_one_file, run_one_file_pipeline
from ctwa.analysis.run_header import parse_run_header
from ctwa.analysis.modes import run_auto_fit_analysis
from ctwa.analysis.row import build_analysis_plot
from ctwa.analysis.sine_fit import remove_period_mean, sine_lag
from ctwa.analysis.smoothing import smooth_to_shared_sine
from ctwa.analysis.square import detect_square_period
from ctwa.analysis.types import AnalysisParams, AnalysisResults, CombinedParsed, PipelineOptions, SyncedData

__all__ = ["LoadedRun", "RegionInfo", "load_run", "analyze_run", "smoothed_region", "region_info",
           "file_mean_temperature"]

_CACHE_MAX = 3
# (path, mtime_ns, size) -> LoadedRun, least recently used first
_CACHE: "OrderedDict[Tuple[str, int, int], LoadedRun]" = OrderedDict()


@dataclass
class LoadedRun:
    path: str
    synced: SyncedData
    parsed: CombinedParsed
    header: Dict[str, object]  # started, experiment, instrument, calorimeter
    default: Tuple[float, float, List[Tuple[float, float]]]  # sel_min, sel_max, clicks
    mean_temperature: Optional[float]  # mean of the finite temperatures, whole file


def _mean_finite(values) -> Optional[float]:
    total = 0.0
    n = 0
    for v in values:
        if math.isfinite(v):
            total += v
            n += 1
    return total / n if n else None


def load_run(path: str) -> LoadedRun:
    st = os.stat(path)
    key = (path, st.st_mtime_ns, st.st_size)
    hit = _CACHE.get(key)
    if hit is not None:
        _CACHE.move_to_end(key)
        return hit
    with open(path, "rb") as f:
        data = f.read()
    synced, parsed = load_one_file(data)
    run = LoadedRun(
        path=path,
        synced=synced,
        parsed=parsed,
        header=parse_run_header(decode_bytes(data[:8192]).splitlines()),
        default=default_selection(synced),
        mean_temperature=_mean_finite(parsed.temperature),
    )
    for k in [k for k in _CACHE if k[0] == path]:
        del _CACHE[k]  # an older version of the same file
    _CACHE[key] = run
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return run


def analyze_run(path: str, opts: PipelineOptions):
    """(results, plot): the plot saved as graph_image is built here, in the process, because
    its sine smoothing takes seconds. plot is None if it could not be built (the row is then
    saved without a graph)."""
    synced = load_run(path).synced
    results = run_one_file_pipeline(synced, opts)
    try:
        plot = build_analysis_plot(synced, results, opts)
    except Exception:
        plot = None
    return results, plot


def file_mean_temperature(path: str) -> Optional[float]:
    """Mean of the finite temperatures of a run file (None: no temperature or not a capture).
    For the Runs tab's mean-temperature process; never raises."""
    try:
        with open(path, "rb") as f:
            parsed = parse_combined_file(f.read())
        if parsed is None:
            return None
        return _mean_finite(parsed.temperature)
    except Exception:
        return None


_SMOOTH_MAX = 4
_SMOOTH_CACHE: "OrderedDict[Tuple[str, int, int, float, float], object]" = OrderedDict()


def smoothed_region(path: str, sel_min: float, sel_max: float):
    """The webapp's smoothedRegion: (t_src, v_src_smoothed, t_cal, v_cal_smoothed) over the
    region, each signal replaced by a sine at the source's frequency; None when the region
    has under 10 points on either signal or no sine can be fitted. Cached per file and region."""
    st = os.stat(path)
    key = (path, st.st_mtime_ns, st.st_size, sel_min, sel_max)
    if key in _SMOOTH_CACHE:
        _SMOOTH_CACHE.move_to_end(key)
        return _SMOOTH_CACHE[key]
    s = load_run(path).synced
    ts = [t for t in s.t_src if sel_min <= t <= sel_max]
    vs = [v for t, v in zip(s.t_src, s.v_src) if sel_min <= t <= sel_max]
    tc = [t for t in s.t_cal if sel_min <= t <= sel_max]
    vc = [v for t, v in zip(s.t_cal, s.v_cal) if sel_min <= t <= sel_max]
    result = None
    if len(ts) >= 10 and len(tc) >= 10:
        sm = smooth_to_shared_sine(ts, vs, tc, vc)
        if sm is not None:
            result = (ts, sm[0], tc, sm[1])
    _SMOOTH_CACHE[key] = result
    while len(_SMOOTH_CACHE) > _SMOOTH_MAX:
        _SMOOTH_CACHE.popitem(last=False)
    return result


_PERIOD_CACHE: "OrderedDict[Tuple[str, int, int, float, float, str], Optional[float]]" = OrderedDict()


def _region_slices(path: str, sel_min: float, sel_max: float):
    s = load_run(path).synced
    ts = [t for t in s.t_src if sel_min <= t <= sel_max]
    vs = [v for t, v in zip(s.t_src, s.v_src) if sel_min <= t <= sel_max]
    tc = [t for t in s.t_cal if sel_min <= t <= sel_max]
    vc = [v for t, v in zip(s.t_cal, s.v_cal) if sel_min <= t <= sel_max]
    return ts, vs, tc, vc


def region_period(path: str, sel_min: float, sel_max: float, wave: str = "sine") -> Optional[float]:
    """The webapp's `preview.T` (page.tsx ~L460): the period the Auto (sine fit) analysis finds
    in the region (for a square wave, detectSquarePeriod of the source, L470-474);
    None when the region is too short or has no clear period."""
    st = os.stat(path)
    key = (path, st.st_mtime_ns, st.st_size, sel_min, sel_max, wave)
    if key in _PERIOD_CACHE:
        _PERIOD_CACHE.move_to_end(key)
        return _PERIOD_CACHE[key]
    ts, vs, tc, vc = _region_slices(path, sel_min, sel_max)
    period = None
    if len(ts) >= 10 and len(tc) >= 10 and wave == "square":
        t = detect_square_period(ts, vs)
        period = t if math.isfinite(t) and t > 0 else None
    elif len(ts) >= 10 and len(tc) >= 10:
        params = AnalysisParams(
            model_name="", test_date="", test_time="", t_cal="00:00:00", t_src="00:00:00",
            r1_mm=6.72, r2_mm=14.86, c80_time_unit="Seconds", c80_pwr_unit="mW",
            src_time_unit="Seconds", src_pwr_unit="Watts", use_calibration=False, system_lag=0.0,
            analysis_mode="AutoFit")
        try:
            t = run_auto_fit_analysis(tc, vc, ts, vs, params, sel_min, sel_max).period_t
            period = t if t is not None and math.isfinite(t) and t > 0 else None
        except Exception:
            period = None
    _PERIOD_CACHE[key] = period
    while len(_PERIOD_CACHE) > _SMOOTH_MAX:
        _PERIOD_CACHE.popitem(last=False)
    return period


class RegionInfo(NamedTuple):
    """Everything the Analysis tab needs to place and snap Manual markers in a region,
    so the GUI process only does cheap lookups."""
    period: Optional[float]
    # (t_src, v_src, t_cal, v_cal) the markers snap on: the smoothed series when smoothing is
    # on and a sine could be fitted, else the raw region with its slow baseline taken off when
    # the region is three periods or more. None when there is no period.
    snap: Optional[tuple]
    # the four marker times (S1, S2, R1, R2) before snapping, as the webapp places them when
    # the peaks step opens; None when no sine could be fitted.
    placement: Optional[Tuple[float, float, float, float]]


def _snap_series(path: str, sel_min: float, sel_max: float, smooth: bool, wave: str, period):
    if not period:
        return None
    if smooth and wave != "square":
        sm = smoothed_region(path, sel_min, sel_max)
        if sm is not None:
            return sm
    ts, vs, tc, vc = _region_slices(path, sel_min, sel_max)
    if (sel_max - sel_min) / period >= 3:
        ft, fv = remove_period_mean(ts, vs, period)
        if len(ft) > 10:
            ts, vs = ft, fv
        ft, fv = remove_period_mean(tc, vc, period)
        if len(ft) > 10:
            tc, vc = ft, fv
    return ts, vs, tc, vc


def _placement(path: str, sel_min: float, sel_max: float, T):
    """page.tsx's marker placement: source peaks at the first and last full cycles of the
    region's sine fit, response peaks one fitted lag later."""
    if not T:
        return None
    ts, vs, tc, vc = _region_slices(path, sel_min, sel_max)
    fit = sine_lag(ts, vs, tc, vc, T)
    if fit is None:
        return None
    w = 2 * math.pi / T
    lo_t, hi_t = max(ts[0], tc[0]) + T / 4, min(ts[-1], tc[-1]) - T / 4
    peaks = []
    k = math.ceil((lo_t * w - fit.phase_src) / (2 * math.pi))
    while True:
        at = (fit.phase_src + 2 * math.pi * k) / w
        if at + fit.lag > hi_t:
            break
        peaks.append(at)
        k += 1
    if not peaks:
        return None
    first = peaks[0]
    last = peaks[-1] if len(peaks) > 1 else first + T
    return (first, last, first + fit.lag, last + fit.lag)


_INFO_CACHE: "OrderedDict[Tuple[str, int, int, float, float, bool, str], RegionInfo]" = OrderedDict()


def region_info(path: str, sel_min: float, sel_max: float, smooth: bool, wave: str = "sine") -> RegionInfo:
    """Period, snapping series and initial marker times of a region (see RegionInfo)."""
    st = os.stat(path)
    key = (path, st.st_mtime_ns, st.st_size, sel_min, sel_max, smooth, wave)
    hit = _INFO_CACHE.get(key)
    if hit is not None:
        _INFO_CACHE.move_to_end(key)
        return hit
    period = region_period(path, sel_min, sel_max, wave)
    info = RegionInfo(period, _snap_series(path, sel_min, sel_max, smooth, wave, period),
                      _placement(path, sel_min, sel_max, period))
    _INFO_CACHE[key] = info
    while len(_INFO_CACHE) > _SMOOTH_MAX:
        _INFO_CACHE.popitem(last=False)
    return info
