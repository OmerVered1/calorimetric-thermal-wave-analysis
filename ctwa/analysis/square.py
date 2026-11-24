"""Square-wave analysis path.

Literal port of lib/squareAnalysis.ts of the webapp: amplitude and phase at the
fundamental frequency from both signals by a single-frequency trapezoidal DFT,
fed into the same Angstrom formula as the sine path.
"""

from __future__ import annotations

import math
from typing import List, NamedTuple, Optional, Tuple

import numpy as np

from ctwa.analysis.diffusivity import calculate_thermal_diffusivity
from ctwa.analysis.jsmath import array_max, array_min, js_div
from ctwa.analysis.sine_fit import choose_lag_cycle
from ctwa.analysis.types import AnalysisParams, AnalysisResults


class Fourier(NamedTuple):
    amplitude: float
    phase: float


def detect_square_period(time: List[float], value: List[float]) -> float:
    """Mean spacing of the rising edges (upward crossings of the mid-level); NaN below 2 edges."""
    if len(value) < 4:
        return math.nan
    v_min = array_min(value)
    v_max = array_max(value)
    mid = (v_min + v_max) / 2
    edge_times: List[float] = []
    for i in range(1, len(value)):
        if value[i - 1] < mid and value[i] >= mid:
            # Linear interpolation for sub-sample precision
            frac = js_div(mid - value[i - 1], value[i] - value[i - 1])
            edge_times.append(time[i - 1] + frac * (time[i] - time[i - 1]))
    if len(edge_times) < 2:
        return math.nan
    total = 0.0
    for i in range(1, len(edge_times)):
        total += edge_times[i] - edge_times[i - 1]
    return total / (len(edge_times) - 1)


def extract_fourier_fundamental(time: List[float], value: List[float], freq: float) -> Fourier:
    """Amplitude (half peak-to-peak of the fundamental) and phase at `freq` (Hz).

    The trapezoid terms are computed with numpy and added in index order
    (cumsum is sequential), so the sums are the TypeScript's own.
    """
    n = len(time)
    if n < 2 or n != len(value):
        return Fourier(0.0, 0.0)
    omega = 2 * math.pi * freq
    t = np.asarray(time, dtype=np.float64)
    v = np.asarray(value, dtype=np.float64)
    with np.errstate(all="ignore"):
        mean = float(np.cumsum(v)[-1]) / n  # sequential, like `for (v of value) mean += v`
        t_start = time[0]
        t_end = time[n - 1]
        length = t_end - t_start
        if length <= 0:
            return Fourier(0.0, 0.0)

        d = v - mean
        angle = omega * t
        cs = np.cos(angle)
        sn = np.sin(angle)
        dt = t[1:] - t[:-1]
        c_terms = 0.5 * (d[:-1] * cs[:-1] + d[1:] * cs[1:]) * dt
        s_terms = 0.5 * (d[:-1] * sn[:-1] + d[1:] * sn[1:]) * dt
        c_sum = float(np.cumsum(c_terms)[-1])
        s_sum = float(np.cumsum(s_terms)[-1])
    c = (2 / length) * c_sum
    s = (2 / length) * s_sum
    return Fourier(math.sqrt(c * c + s * s), math.atan2(s, c))


def filter_to_range(
    time: List[float], value: List[float], t_min: float, t_max: float
) -> Tuple[List[float], List[float]]:
    """The samples with t_min <= time <= t_max, as (t, v)."""
    t: List[float] = []
    v: List[float] = []
    for i in range(len(time)):
        if time[i] >= t_min and time[i] <= t_max:
            t.append(time[i])
            v.append(value[i])
    return t, v


def run_square_analysis(
    t_cal: List[float],
    v_cal: List[float],
    t_src: List[float],
    v_src: List[float],
    params: AnalysisParams,
    t_min: float,
    t_max: float,
    period_override: Optional[float] = None,
) -> AnalysisResults:
    src_t, src_v = filter_to_range(t_src, v_src, t_min, t_max)
    cal_t, cal_v = filter_to_range(t_cal, v_cal, t_min, t_max)

    if len(src_t) < 4 or len(cal_t) < 4:
        raise ValueError("Not enough samples in the selected range for Fourier analysis.")

    # Period: explicit override wins, otherwise auto-detect from source edges
    if period_override is not None and period_override > 0:
        period = period_override
    else:
        period = detect_square_period(src_t, src_v)
    if not math.isfinite(period) or period <= 0:
        raise ValueError("Could not determine the fundamental period — enter it manually.")

    freq = 1 / period
    omega = 2 * math.pi * freq

    src_fft = extract_fourier_fundamental(src_t, src_v, freq)
    cal_fft = extract_fourier_fundamental(cal_t, cal_v, freq)

    if src_fft.amplitude <= 0 or cal_fft.amplitude <= 0:
        raise ValueError("Fourier amplitude is zero in source or response — check the data.")

    # Phase lag: response lags source. Normalise the difference to (-pi, pi].
    phase_diff = src_fft.phase - cal_fft.phase
    while phase_diff > math.pi:
        phase_diff -= 2 * math.pi
    while phase_diff < -math.pi:
        phase_diff += 2 * math.pi
    # A response lagging by tau gives -tau here, up to whole periods; read it in [0, T).
    cycle_shift = 0 if params.cycle_shift is None else params.cycle_shift
    choice = choose_lag_cycle(-phase_diff / omega, period, cycle_shift)
    lag_dt = choice.dt

    # Plot markers: first rising edge of the source, one period later, and edge + lag.
    src_min = array_min(src_v)
    src_max = array_max(src_v)
    src_mid = (src_min + src_max) / 2
    first_src_edge = src_t[0]
    for i in range(1, len(src_v)):
        if src_v[i - 1] < src_mid and src_v[i] >= src_mid:
            first_src_edge = src_t[i]
            break
    second_src_edge = first_src_edge + period
    resp_marker = first_src_edge + lag_dt

    # Response period (diagnostic): rising edges of the response signal
    resp_period_raw = detect_square_period(cal_t, cal_v)
    resp_period = resp_period_raw if math.isfinite(resp_period_raw) and resp_period_raw > 0 else None

    result = calculate_thermal_diffusivity(
        src_fft.amplitude,
        cal_fft.amplitude,
        period,
        omega,
        lag_dt,
        params,
        t_min,
        t_max,
        first_src_edge,
        second_src_edge,
        resp_marker,
    )
    result.lag_cycles = choice.cycles
    result.lag_near_edge = choice.near_edge
    result.period_t_resp = resp_period
    result.frequency_f_resp = 1 / resp_period if resp_period else None
    return result
