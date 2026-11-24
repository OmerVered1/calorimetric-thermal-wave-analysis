"""Period estimation and sine smoothing.

Literal port of linearDetrend, estimateFundamentalPeriod, reconstructSineAt,
smoothToSharedSine, detectSegments and smoothPiecewise of lib/analysis.ts of the
webapp. modes.py imports this module, never the reverse.
"""

from __future__ import annotations

import math
from functools import cmp_to_key
from typing import List, Optional, Tuple

import numpy as np

from ctwa.analysis.jsmath import js_div, js_floor, js_max, js_min
from ctwa.analysis.jstrig import cos_array
from ctwa.analysis.peaks import find_peaks
from ctwa.analysis.square import extract_fourier_fundamental


def linear_detrend(time: List[float], value: List[float]) -> List[float]:
    """Subtract a least-squares linear trend (a + b t) from `value`."""
    n = len(value)
    if n < 2:
        return list(value)
    sx = sy = sxx = sxy = 0.0
    for i in range(n):
        sx += time[i]
        sy += value[i]
        sxx += time[i] * time[i]
        sxy += time[i] * value[i]
    denom = n * sxx - sx * sx
    if denom == 0:
        return list(value)
    b = (n * sxy - sx * sy) / denom
    a = (sy - b * sx) / n
    return [value[i] - (a + b * time[i]) for i in range(n)]


def estimate_fundamental_period(
    time: List[float],
    value: List[float],
    max_cycles: Optional[float] = None,
    grid_size: Optional[float] = None,
) -> Optional[float]:
    """Period of the largest Fourier amplitude over a log-spaced frequency scan plus one finer pass."""
    if len(time) < 8 or len(value) != len(time):
        return None
    t0 = time[0]
    t_n = time[-1]
    length = t_n - t0
    if length <= 0:
        return None

    # Allow as many cycles as the sampling can resolve (~5 samples/cycle).
    dt = length / (len(time) - 1)
    resolvable_cycles = js_floor(js_div(length, 5 * dt))
    mc = js_min(400, js_max(20, resolvable_cycles)) if max_cycles is None else max_cycles
    grid = js_min(240, js_max(80, mc * 2)) if grid_size is None else grid_size
    f_min = 2 / length  # 2 cycles in window
    f_max = mc / length  # up to mc cycles in window

    best_freq = f_min
    best_amp = -1.0
    i = 0
    while i < grid:  # logarithmic scan
        frac = js_div(i, grid - 1)
        freq = f_min * math.pow(f_max / f_min, frac)
        amplitude = extract_fourier_fundamental(time, value, freq).amplitude
        if amplitude > best_amp:
            best_amp = amplitude
            best_freq = freq
        i += 1
    # One refine pass around the best (linear, finer)
    refine_range = js_div(f_max - f_min, grid)
    f0 = js_max(f_min, best_freq - refine_range)
    f1 = js_min(f_max, best_freq + refine_range)
    i = 0
    while i < grid:
        freq = f0 + (f1 - f0) * js_div(i, grid - 1)
        amplitude = extract_fourier_fundamental(time, value, freq).amplitude
        if amplitude > best_amp:
            best_amp = amplitude
            best_freq = freq
        i += 1
    return 1 / best_freq if best_freq > 0 else None


def reconstruct_sine_at(time: List[float], value: List[float], freq: float) -> List[float]:
    """mean + A cos(w t - phase) at each time, A and phase from the Fourier fundamental at freq."""
    if len(time) == 0 or len(time) != len(value) or not (freq > 0):
        return list(value)
    mean = 0.0
    for v in value:
        mean += v
    mean /= len(value)
    f = extract_fourier_fundamental(time, value, freq)
    w = 2 * math.pi * freq
    angle = w * np.asarray(time, dtype=np.float64) - f.phase
    return [mean + f.amplitude * c for c in cos_array(angle).tolist()]


def smooth_to_shared_sine(
    t_src: List[float], v_src: List[float], t_cal: List[float], v_cal: List[float]
) -> Optional[Tuple[List[float], List[float], float]]:
    """Both signals as one sine at the source's frequency: (v_src, v_cal, freq), or None."""
    period = estimate_fundamental_period(t_src, linear_detrend(t_src, v_src))
    if not period or not math.isfinite(period) or period <= 0:
        return None
    freq = 1 / period
    return reconstruct_sine_at(t_src, v_src, freq), reconstruct_sine_at(t_cal, v_cal, freq), freq


def detect_segments(time: List[float], value: List[float]) -> List[Tuple[int, int]]:
    """Index ranges (start, end) of the oscillating bursts of a capture."""
    n = len(time)
    whole = [(0, max(0, n - 1))]
    if n < 20:
        return whole

    lo = math.inf
    hi = -math.inf
    for v in value:
        if v < lo:
            lo = v
        if v > hi:
            hi = v
    if hi - lo <= 0:
        return whole
    thr = lo + (hi - lo) * 0.6

    # Strong source peaks, de-duplicated to one per ~5 s.
    peak_idx: List[int] = []
    for i in find_peaks(value, 3):
        if value[i] < thr:
            continue
        last = peak_idx[-1] if peak_idx else None
        if last is None or time[i] - time[last] > 5:
            peak_idx.append(i)
        elif value[i] > value[last]:
            peak_idx[-1] = i
    if len(peak_idx) < 3:
        return whole

    intervals = [time[peak_idx[i]] - time[peak_idx[i - 1]] for i in range(1, len(peak_idx))]
    srt = sorted(intervals, key=cmp_to_key(lambda a, b: a - b))
    median = srt[len(srt) // 2]
    if not (median > 0):
        return whole
    gap_thresh = median * 3
    half = median / 2

    runs: List[List[int]] = []
    cur: List[int] = [peak_idx[0]]
    for i in range(1, len(peak_idx)):
        if time[peak_idx[i]] - time[peak_idx[i - 1]] > gap_thresh:
            runs.append(cur)
            cur = []
        cur.append(peak_idx[i])
    if cur:
        runs.append(cur)

    segs: List[Tuple[int, int]] = []
    for r in runs:
        if len(r) < 2:
            continue
        t0 = time[r[0]] - half
        t1 = time[r[-1]] + half
        start = 0
        while start < n - 1 and time[start] < t0:
            start += 1
        end = n - 1
        while end > 0 and time[end] > t1:
            end -= 1
        if end > start:
            segs.append((start, end))
    return segs if segs else whole


def smooth_piecewise(
    t_src: List[float], v_src: List[float], t_cal: List[float], v_cal: List[float]
) -> Tuple[List[float], List[float]]:
    """Each oscillating segment replaced by its own sine fit (shared w from the source)."""
    out_src = list(v_src)
    out_cal = list(v_cal)
    for start, end in detect_segments(t_src, v_src):
        if end - start < 8:
            continue
        s_t = t_src[start:end + 1]
        s_v = v_src[start:end + 1]
        period = estimate_fundamental_period(s_t, linear_detrend(s_t, s_v))
        if not period or not math.isfinite(period) or period <= 0:
            continue
        freq = 1 / period

        r_src = reconstruct_sine_at(s_t, s_v, freq)
        for i in range(len(r_src)):
            out_src[start + i] = r_src[i]

        t0 = t_src[start]
        t1 = t_src[end]
        c_idx = [i for i in range(len(t_cal)) if t_cal[i] >= t0 and t_cal[i] <= t1]
        if len(c_idx) >= 8:
            r_resp = reconstruct_sine_at([t_cal[i] for i in c_idx], [v_cal[i] for i in c_idx], freq)
            for k in range(len(c_idx)):
                out_cal[c_idx[k]] = r_resp[k]
    return out_src, out_cal
