"""The Auto, Manual, AutoHybrid, AutoFFT and AutoFit analysis modes.

Literal port of runAutoAnalysis and runManualAnalysis of lib/analysis.ts of the
webapp, with the private helpers they use (strongPeaks, fittedAmplitudes,
linearDetrend, estimateFundamentalPeriod, ...). The helpers that the later
modes share are public here: linear_detrend, estimate_fundamental_period,
mean_diff, mean_of_indices, mean_trough_between_peaks.
"""

from __future__ import annotations

import math
from functools import cmp_to_key
from typing import List, Optional, Tuple

from ctwa.analysis.diffusivity import calculate_thermal_diffusivity
from ctwa.analysis.jsmath import array_max, array_min, js_div, js_floor, js_max, js_min, js_round
from ctwa.analysis.peaks import compute_cycle_amplitude, find_peaks, snap_to_peak
from ctwa.analysis.sine_fit import (
    choose_lag_cycle,
    lag_into_period,
    refine_peak,
    sine_lag,
)
from ctwa.analysis.smoothing import estimate_fundamental_period, linear_detrend
from ctwa.analysis.types import AnalysisParams, AnalysisResults, LagChoice


def mean_diff(arr: List[float]) -> float:
    total = 0.0
    for i in range(1, len(arr)):
        total += arr[i] - arr[i - 1]
    return js_div(total, len(arr) - 1)


def mean_of_indices(values: List[float], indices: List[int]) -> float:
    if len(indices) == 0:
        return 0.0
    total = 0.0
    for i in indices:
        total += values[i]
    return total / len(indices)


def mean_trough_between_peaks(values: List[float], peak_indices: List[int]) -> float:
    """Average of the minimum values found between each pair of consecutive peaks."""
    if len(peak_indices) < 2:
        return array_min(values)
    total = 0.0
    for k in range(len(peak_indices) - 1):
        min_val = values[peak_indices[k]]
        for i in range(peak_indices[k] + 1, peak_indices[k + 1]):
            if values[i] < min_val:
                min_val = values[i]
        total += min_val
    return total / (len(peak_indices) - 1)


def _strong_peaks(time: List[float], value: List[float], period: Optional[float]) -> List[int]:
    """Peaks above 60% of the range, spaced by ~0.7 of the period (length/8 without one)."""
    dt = (time[-1] - time[0]) / (len(time) - 1) if len(time) > 1 else 1
    if period is not None and period > 0:
        dist = js_max(js_floor(js_div(0.7 * period, dt)), 3)
    else:
        dist = js_max(js_floor(len(value) / 8), 10)
    lo = array_min(value)
    hi = array_max(value)
    thr = lo + (hi - lo) * 0.6
    return [i for i in find_peaks(value, dist) if value[i] >= thr]


def _fitted_amplitudes(
    t_src: List[float], v_src: List[float], t_cal: List[float], v_cal: List[float], T: float
) -> Optional[Tuple[float, float]]:
    """A1 and A2 as the amplitudes of sines fitted at the analysis period."""
    fit = sine_lag(t_src, v_src, t_cal, v_cal, T)
    if fit is not None and fit.amplitude_src > 0 and fit.amplitude_cal > 0:
        return fit.amplitude_src, fit.amplitude_cal
    return None


def _note_lag_choice(result: AnalysisResults, choice: LagChoice) -> None:
    result.lag_cycles = choice.cycles
    result.lag_near_edge = choice.near_edge


def _positive_period(x: Optional[float]) -> Optional[float]:
    return x if x is not None and math.isfinite(x) and x > 0 else None


def _cycle_shift(params: AnalysisParams) -> float:
    return 0 if params.cycle_shift is None else params.cycle_shift


def run_auto_analysis(
    t_cal: List[float],
    v_cal: List[float],
    t_src: List[float],
    v_src: List[float],
    params: AnalysisParams,
    t_min: float,
    t_max: float,
) -> AnalysisResults:
    # Size the peak spacing from the FFT-estimated period so short periods with
    # many cycles in the window are detected correctly (not merged).
    t_est = estimate_fundamental_period(t_src, linear_detrend(t_src, v_src))
    strong_src = _strong_peaks(t_src, v_src, t_est)
    strong_cal = _strong_peaks(t_cal, v_cal, t_est)

    if len(strong_src) < 2 or len(strong_cal) < 1:
        raise ValueError("Not enough peaks detected. Try manual mode or adjust the selection range.")

    src_peak_times = [t_src[i] for i in strong_src]
    cal_peak_times = [t_cal[i] for i in strong_cal]
    T = t_est if t_est is not None and t_est > 0 else mean_diff(src_peak_times)
    w = (2 * math.pi) / T

    # Each source peak is paired with its nearest response peak and the lag is
    # read in [0, T); the median is taken around the circular mean.
    raw: List[float] = []
    for ts in src_peak_times:
        best = math.inf
        best_lag = 0.0
        for tc in cal_peak_times:
            d = tc - ts
            if abs(d) < best:
                best = abs(d)
                best_lag = d
        raw.append(lag_into_period(best_lag, T))
    sx = 0.0
    sy = 0.0
    for lag in raw:
        sx += math.cos(w * lag)
        sy += math.sin(w * lag)
    centre = lag_into_period(math.atan2(sy, sx) / w, T)
    around: List[float] = []
    for lag in raw:
        d = lag - centre
        if d > T / 2:
            d -= T
        if d < -T / 2:
            d += T
        around.append(d)
    around.sort(key=cmp_to_key(lambda a, b: a - b))
    choice = choose_lag_cycle(centre + around[len(around) // 2], T, _cycle_shift(params))
    dt = choice.dt

    ts_first = src_peak_times[0]
    ts_second = src_peak_times[1] if len(src_peak_times) > 1 else ts_first + T
    tc_marker = ts_first + dt  # response peak paired with the first source peak

    t_resp = mean_diff(cal_peak_times) if len(strong_cal) >= 2 else None
    amps = _fitted_amplitudes(t_src, v_src, t_cal, v_cal, T)
    a1 = amps[0] if amps is not None else compute_cycle_amplitude(v_src, strong_src)
    a2 = amps[1] if amps is not None else compute_cycle_amplitude(v_cal, strong_cal)

    result = calculate_thermal_diffusivity(
        a1, a2, T, w, dt, params, t_min, t_max, ts_first, ts_second, tc_marker
    )
    _note_lag_choice(result, choice)
    result.period_t_resp = _positive_period(t_resp)
    result.frequency_f_resp = 1 / result.period_t_resp if result.period_t_resp else None
    result.mean_peak_src = mean_of_indices(v_src, strong_src)
    result.mean_trough_src = mean_trough_between_peaks(v_src, strong_src)
    result.mean_peak_cal = mean_of_indices(v_cal, strong_cal)
    result.mean_trough_cal = mean_trough_between_peaks(v_cal, strong_cal)
    return result


def run_manual_analysis(
    t_cal: List[float],
    v_cal: List[float],
    t_src: List[float],
    v_src: List[float],
    params: AnalysisParams,
    t_min: float,
    t_max: float,
    clicks: List[Tuple[float, float]],
) -> AnalysisResults:
    """`clicks` = [src peak 1, src peak 2, resp peak 1, resp peak 2], each (t, v); 3 clicks also accepted."""
    if len(clicks) < 3:
        raise ValueError("Need at least 3 click coordinates for manual analysis")

    # The source's own period: cycles between two markers, and the reach of a refined marker.
    est = estimate_fundamental_period(t_src, linear_detrend(t_src, v_src))
    t_est = est if est is not None and math.isfinite(est) and est > 0 else None

    def cycles_in(gap: float) -> float:
        return js_max(1, js_round(js_div(gap, t_est))) if t_est else 1

    rough_gap = abs(clicks[1][0] - clicks[0][0])
    if rough_gap > 0:
        t_guess = js_div(rough_gap, cycles_in(rough_gap))
    else:
        t_guess = t_est if t_est is not None else 0

    # A marker is moved to the peak it points at unless told to use the time as given.
    snap = params.manual_snap is not False

    def place(x: float, time: List[float], values: List[float]) -> Tuple[float, float]:
        if snap and t_guess > 0:
            refined = refine_peak(time, values, x, t_guess)
            if refined:
                return refined
        if snap:
            t_s, v_s, _ = snap_to_peak(x, time, values)
            return t_s, v_s
        return x, 0.0

    p1 = place(clicks[0][0], t_src, v_src)
    p2 = place(clicks[1][0], t_src, v_src)
    gap = abs(p2[0] - p1[0])
    if not (gap > 0):
        raise ValueError("The two source peaks are at the same time. Place them on different peaks.")
    # The two source markers may be several cycles apart.
    T = js_div(gap, cycles_in(gap))
    w = (2 * math.pi) / T

    r1 = place(clicks[2][0], t_cal, v_cal)
    r2 = place(clicks[3][0], t_cal, v_cal) if len(clicks) >= 4 else None

    # Lag: each response peak against its own source peak, averaged.
    lag1 = r1[0] - p1[0]
    lag2 = r2[0] - p2[0] if r2 is not None else None
    if lag2 is not None and abs(lag1 - lag2) > T / 4:
        raise ValueError(
            "The two source-response pairs disagree by more than a quarter of a period. "
            "Check that each response peak belongs to its source peak."
        )
    dt = (lag1 + lag2) / 2 if lag2 is not None else lag1
    if not (dt > 0):
        raise ValueError("Each response peak must come after its source peak.")
    resp_gap = abs(r2[0] - r1[0]) if r2 is not None else 0
    t_resp_from_clicks = (
        js_div(resp_gap, js_max(1, js_round(js_div(resp_gap, T)))) if resp_gap > 0 else None
    )

    # Amplitudes: fitted sines at this period; peak-to-trough only as a fallback.
    dist_src = js_max(js_floor(len(v_src) / 8), 10)
    dist_cal = js_max(js_floor(len(v_cal) / 8), 10)
    src_peaks = find_peaks(v_src, dist_src)
    cal_peaks = find_peaks(v_cal, dist_cal)
    src_thresh = array_min(v_src) + (array_max(v_src) - array_min(v_src)) * 0.6
    cal_thresh = array_min(v_cal) + (array_max(v_cal) - array_min(v_cal)) * 0.6
    strong_src_m = [i for i in src_peaks if v_src[i] >= src_thresh]
    strong_cal_m = [i for i in cal_peaks if v_cal[i] >= cal_thresh]
    use_src_peaks = strong_src_m if len(strong_src_m) >= 2 else src_peaks
    use_cal_peaks = strong_cal_m if len(strong_cal_m) >= 1 else cal_peaks
    amps = _fitted_amplitudes(t_src, v_src, t_cal, v_cal, T)
    a1 = amps[0] if amps is not None else compute_cycle_amplitude(v_src, use_src_peaks)
    a2 = amps[1] if amps is not None else compute_cycle_amplitude(v_cal, use_cal_peaks)

    # Response period: from the two clicked response peaks if given, else auto.
    if t_resp_from_clicks is not None:
        t_resp: Optional[float] = t_resp_from_clicks
    elif len(use_cal_peaks) >= 2:
        t_resp = mean_diff([t_cal[i] for i in use_cal_peaks])
    else:
        t_resp = None

    result = calculate_thermal_diffusivity(
        a1, a2, T, w, dt, params, t_min, t_max, p1[0], p2[0], r1[0]
    )
    if lag2 is not None:
        # Two pairs give a first idea of how well the lag is pinned down.
        result.lag_se = abs(lag1 - lag2) / 2
        result.lag_se_source = "pairs"
    result.period_t_resp = _positive_period(t_resp)
    result.frequency_f_resp = 1 / result.period_t_resp if result.period_t_resp else None
    result.mean_peak_src = mean_of_indices(v_src, use_src_peaks)
    result.mean_trough_src = mean_trough_between_peaks(v_src, use_src_peaks)
    result.mean_peak_cal = mean_of_indices(v_cal, use_cal_peaks)
    result.mean_trough_cal = mean_trough_between_peaks(v_cal, use_cal_peaks)
    return result
