"""The Auto, Manual, AutoHybrid, AutoFFT and AutoFit analysis modes.

Literal port of runAutoAnalysis and runManualAnalysis of lib/analysis.ts of the
webapp, with the private helpers they use. The public entry points are
run_auto_analysis, run_manual_analysis, run_auto_hybrid_analysis,
run_auto_fft_analysis and run_auto_fit_analysis. The mean helpers mean_diff,
mean_of_indices and mean_trough_between_peaks are public here; linear_detrend and
estimate_fundamental_period live in ctwa.analysis.smoothing and are imported from there.
"""

from __future__ import annotations

import math
from functools import cmp_to_key
from typing import List, Optional, Tuple

from ctwa.analysis.diffusivity import calculate_thermal_diffusivity
from ctwa.analysis.jsmath import (
    array_max, array_min, js_ceil, js_cos, js_div, js_floor, js_max, js_min, js_round, js_sin,
)
from ctwa.analysis.peaks import compute_cycle_amplitude, find_peaks, snap_to_peak
from ctwa.analysis.sine_fit import (
    choose_lag_cycle,
    lag_into_period,
    refine_period,
    refine_peak,
    remove_period_mean,
    sine_lag,
)
from ctwa.analysis.smoothing import estimate_fundamental_period, linear_detrend
from ctwa.analysis.square import extract_fourier_fundamental, filter_to_range
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
        sx += js_cos(w * lag)
        sy += js_sin(w * lag)
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


# ---------------------------------------------------------------------------
# Helpers of the FFT-based modes
# ---------------------------------------------------------------------------


def _sine_levels(values: List[float], amplitude: float) -> Tuple[float, float]:
    """Peak and trough levels of a fitted sine (mean +- A), for the result chart."""
    mean = 0.0
    for v in values:
        mean += v
    mean /= len(values) or 1
    return mean + amplitude, mean - amplitude


def _mean_dt(time: List[float]) -> float:
    if len(time) < 2:
        return 1.0
    return (time[-1] - time[0]) / (len(time) - 1)


def _trim_to_integer_cycles(
    time: List[float], value: List[float], T: float
) -> Tuple[List[float], List[float]]:
    """Trim to a whole number of periods T from time[0] (no spectral leakage)."""
    if len(time) < 2 or T <= 0:
        return list(time), list(value)
    t_start = time[0]
    total_span = time[-1] - t_start
    n_cycles = js_floor(js_div(total_span, T))
    if n_cycles < 2:
        return list(time), list(value)
    t_end_trim = t_start + n_cycles * T
    t: List[float] = []
    v: List[float] = []
    for i in range(len(time)):
        if time[i] <= t_end_trim:
            t.append(time[i])
            v.append(value[i])
    return t, v


def _phase_lag_via_fft(
    t_src: List[float], v_src: List[float], t_cal: List[float], v_cal: List[float], T: float
) -> Tuple[float, float, float]:
    """(dt, ampSrc, ampCal): source phase minus response phase as a time, in (-T/2, T/2]."""
    f = 1 / T
    w = 2 * math.pi * f

    v_src_d = linear_detrend(t_src, v_src)
    v_cal_d = linear_detrend(t_cal, v_cal)
    s_t, s_v = _trim_to_integer_cycles(t_src, v_src_d, T)
    c_t, c_v = _trim_to_integer_cycles(t_cal, v_cal_d, T)

    src_fft = extract_fourier_fundamental(s_t, s_v, f)
    cal_fft = extract_fourier_fundamental(c_t, c_v, f)

    phase_diff = src_fft.phase - cal_fft.phase
    while phase_diff > math.pi:
        phase_diff -= 2 * math.pi
    while phase_diff < -math.pi:
        phase_diff += 2 * math.pi

    return js_div(phase_diff, w), src_fft.amplitude, cal_fft.amplitude


def _period_override(params: AnalysisParams) -> Optional[float]:
    ov = params.fft_period_override
    return ov if ov and ov > 0 else None


def _valid_period(x: Optional[float]) -> bool:
    return bool(x) and math.isfinite(x) and x > 0


# ---------------------------------------------------------------------------
# Auto (Peaks + FFT)
# ---------------------------------------------------------------------------


def run_auto_hybrid_analysis(
    t_cal: List[float],
    v_cal: List[float],
    t_src: List[float],
    v_src: List[float],
    params: AnalysisParams,
    t_min: float,
    t_max: float,
) -> AnalysisResults:
    src_t, src_v = filter_to_range(t_src, v_src, t_min, t_max)
    cal_t, cal_v = filter_to_range(t_cal, v_cal, t_min, t_max)
    if len(src_t) < 20 or len(cal_t) < 20:
        raise ValueError("Selected region has too few samples for hybrid analysis.")

    v_src_d = linear_detrend(src_t, src_v)
    v_cal_d = linear_detrend(cal_t, cal_v)

    t_est = estimate_fundamental_period(src_t, v_src_d)
    if not _valid_period(t_est):
        raise ValueError("Could not estimate fundamental period via FFT. Try a wider region.")
    dt_src = _mean_dt(src_t)
    dt_cal = _mean_dt(cal_t)
    min_dist_src = js_max(js_floor(js_div(0.7 * t_est, dt_src)), 3)
    min_dist_cal = js_max(js_floor(js_div(0.7 * t_est, dt_cal)), 3)

    peaks_src = find_peaks(v_src_d, min_dist_src)
    peaks_cal = find_peaks(v_cal_d, min_dist_cal)

    s_min = array_min(v_src_d)
    s_max = array_max(v_src_d)
    c_min = array_min(v_cal_d)
    c_max = array_max(v_cal_d)
    src_thr = s_min + (s_max - s_min) * 0.6
    cal_thr = c_min + (c_max - c_min) * 0.6
    strong_src = [i for i in peaks_src if v_src_d[i] >= src_thr]
    strong_cal = [i for i in peaks_cal if v_cal_d[i] >= cal_thr]

    if len(strong_src) < 2 or len(strong_cal) < 1:
        raise ValueError("Not enough strong peaks after detrend. Widen the region or check the data.")

    T = t_est
    w = (2 * math.pi) / T

    lag_dt, _amp_src, _amp_cal = _phase_lag_via_fft(src_t, src_v, cal_t, cal_v, T)
    choice = choose_lag_cycle(-lag_dt, T, _cycle_shift(params))
    dt = choice.dt

    amps = _fitted_amplitudes(src_t, src_v, cal_t, cal_v, T)
    a1 = amps[0] if amps is not None else compute_cycle_amplitude(v_src_d, strong_src)
    a2 = amps[1] if amps is not None else compute_cycle_amplitude(v_cal_d, strong_cal)

    # Response period (diagnostic): median of the response peak intervals
    t_resp: Optional[float] = None
    if len(strong_cal) >= 2:
        cal_times = [cal_t[i] for i in strong_cal]
        cal_diffs = [cal_times[i] - cal_times[i - 1] for i in range(1, len(cal_times))]
        cal_diffs.sort(key=cmp_to_key(lambda a, b: a - b))
        if len(cal_diffs) % 2 == 0:
            t_resp = (cal_diffs[len(cal_diffs) // 2 - 1] + cal_diffs[len(cal_diffs) // 2]) / 2
        else:
            t_resp = cal_diffs[len(cal_diffs) // 2]

    ts_first = src_t[strong_src[0]]
    ts_second = src_t[strong_src[1]]
    tc_marker = ts_first + dt

    result = calculate_thermal_diffusivity(
        a1, a2, T, w, dt, params, t_min, t_max, ts_first, ts_second, tc_marker
    )
    _note_lag_choice(result, choice)
    result.period_t_resp = _positive_period(t_resp)
    result.frequency_f_resp = 1 / result.period_t_resp if result.period_t_resp else None

    # Sums over the sample order, as reduce() does (a peak index counts once).
    src_set = set(strong_src)
    cal_set = set(strong_cal)
    if compute_cycle_amplitude(src_v, strong_src) > 0:
        s = 0.0
        for i, v in enumerate(src_v):
            if i in src_set:
                s += v
        result.mean_peak_src = s / len(strong_src)
    else:
        result.mean_peak_src = 0.0
    if len(strong_cal) > 0:
        s = 0.0
        for i, v in enumerate(cal_v):
            if i in cal_set:
                s += v
        result.mean_peak_cal = s / len(strong_cal)
    else:
        result.mean_peak_cal = 0.0
    result.mean_trough_src = mean_trough_between_peaks(src_v, strong_src)
    result.mean_trough_cal = mean_trough_between_peaks(cal_v, strong_cal)
    return result


# ---------------------------------------------------------------------------
# Auto (FFT): pure Fourier fundamental, no peak detection
# ---------------------------------------------------------------------------


def run_auto_fft_analysis(
    t_cal: List[float],
    v_cal: List[float],
    t_src: List[float],
    v_src: List[float],
    params: AnalysisParams,
    t_min: float,
    t_max: float,
) -> AnalysisResults:
    src_t, src_v = filter_to_range(t_src, v_src, t_min, t_max)
    cal_t, cal_v = filter_to_range(t_cal, v_cal, t_min, t_max)
    if len(src_t) < 20 or len(cal_t) < 20:
        raise ValueError("Selected region has too few samples for FFT analysis.")

    v_src_d0 = linear_detrend(src_t, src_v)
    override = _period_override(params)
    T = override if override is not None else estimate_fundamental_period(src_t, v_src_d0)
    if not _valid_period(T):
        raise ValueError("Could not determine fundamental period via FFT. Enter it manually.")
    w = (2 * math.pi) / T

    lag_dt, amp_src, amp_cal = _phase_lag_via_fft(src_t, src_v, cal_t, cal_v, T)
    if amp_src <= 0 or amp_cal <= 0:
        raise ValueError("Fourier amplitude is zero in source or response — check the data.")
    choice = choose_lag_cycle(-lag_dt, T, _cycle_shift(params))
    dt = choice.dt
    amps = _fitted_amplitudes(src_t, src_v, cal_t, cal_v, T)

    v_cal_d0 = linear_detrend(cal_t, cal_v)
    t_resp_fft = estimate_fundamental_period(cal_t, v_cal_d0)
    t_resp = t_resp_fft if _valid_period(t_resp_fft) else None

    speaks = _strong_peaks(src_t, src_v, T)
    ts_first = src_t[0]
    if speaks:
        ts_first = src_t[speaks[0]]
    else:
        bi = 0
        for i in range(1, len(src_v)):
            if src_v[i] > src_v[bi]:
                bi = i
        ts_first = src_t[bi]

    result = calculate_thermal_diffusivity(
        amps[0] if amps is not None else amp_src,
        amps[1] if amps is not None else amp_cal,
        T, w, dt, params, t_min, t_max,
        ts_first, ts_first + T, ts_first + dt,
    )
    _note_lag_choice(result, choice)
    result.period_t_resp = t_resp
    result.frequency_f_resp = 1 / t_resp if t_resp else None
    result.mean_peak_src, result.mean_trough_src = _sine_levels(src_v, result.amplitude_a1)
    result.mean_peak_cal, result.mean_trough_cal = _sine_levels(cal_v, result.amplitude_a2)
    return result


# ---------------------------------------------------------------------------
# Auto (sine fit): baseline and sine fitted together, with an uncertainty
# ---------------------------------------------------------------------------


def run_auto_fit_analysis(
    t_cal: List[float],
    v_cal: List[float],
    t_src: List[float],
    v_src: List[float],
    params: AnalysisParams,
    t_min: float,
    t_max: float,
) -> AnalysisResults:
    src_t, src_v = filter_to_range(t_src, v_src, t_min, t_max)
    cal_t, cal_v = filter_to_range(t_cal, v_cal, t_min, t_max)
    if len(src_t) < 20 or len(cal_t) < 20:
        raise ValueError("Selected region has too few samples for a sine fit.")

    T = _period_override(params)
    if not T:
        est = estimate_fundamental_period(src_t, linear_detrend(src_t, src_v))
        if not _valid_period(est):
            raise ValueError("Could not determine the period from the source. Enter it manually.")
        T = refine_period(src_t, src_v, est)
    w = (2 * math.pi) / T

    fit = sine_lag(src_t, src_v, cal_t, cal_v, T)
    if fit is None:
        raise ValueError("Could not fit a sine to the signals. Widen the region or check the data.")
    choice = choose_lag_cycle(fit.lag, T, _cycle_shift(params))

    # Markers on the fitted source sine: its first peak inside the region.
    k = js_ceil((src_t[0] * w - fit.phase_src) / (2 * math.pi))
    ts_first = (fit.phase_src + 2 * math.pi * k) / w

    # Response period (diagnostic), with the one-period mean taken off first.
    flat_t, flat_v = remove_period_mean(cal_t, cal_v, T)
    if len(flat_t) >= 20:
        resp_t, resp_v = flat_t, flat_v
    else:
        resp_t, resp_v = cal_t, linear_detrend(cal_t, cal_v)
    resp_est = estimate_fundamental_period(resp_t, resp_v)
    t_resp = refine_period(resp_t, resp_v, resp_est) if _valid_period(resp_est) else None

    result = calculate_thermal_diffusivity(
        fit.amplitude_src, fit.amplitude_cal, T, w, choice.dt, params, t_min, t_max,
        ts_first, ts_first + T, ts_first + choice.dt,
    )
    _note_lag_choice(result, choice)
    result.lag_se = fit.lag_se
    result.lag_se_source = fit.se_source
    result.lag_blocks = fit.blocks
    result.period_t_resp = t_resp
    result.frequency_f_resp = 1 / t_resp if t_resp else None
    result.mean_peak_src, result.mean_trough_src = _sine_levels(src_v, fit.amplitude_src)
    result.mean_peak_cal, result.mean_trough_cal = _sine_levels(cal_v, fit.amplitude_cal)
    return result
