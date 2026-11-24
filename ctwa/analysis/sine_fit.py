"""Least-squares sine fitting for the thermal-wave signals.

Literal port of lib/sineFit.ts of the webapp: a slow polynomial baseline plus
one sine at a known angular frequency, solved with the TypeScript's own normal
equations and Gaussian elimination (no numpy solver).
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from ctwa.analysis.types import LagChoice, SineFit, SineLag


def _div(a: float, b: float) -> float:
    """JS division: x/0 gives +-Infinity or NaN instead of raising."""
    try:
        return a / b
    except ZeroDivisionError:
        if a != a or a == 0:
            return math.nan
        neg = (a < 0) != (math.copysign(1.0, b) < 0)
        return -math.inf if neg else math.inf


def _js_round(x: float) -> float:
    """Math.round: floor(x + 0.5) (non-finite values pass through)."""
    if x != x or x in (math.inf, -math.inf):
        return x
    return math.floor(x + 0.5)


def _js_min(a: float, b: float) -> float:
    """Math.min of two numbers (NaN propagates)."""
    if a != a or b != b:
        return math.nan
    return a if a < b else b


def _js_max(a: float, b: float) -> float:
    if a != a or b != b:
        return math.nan
    return a if a > b else b


def _least_squares(rows: List[List[float]], y: List[float]) -> Optional[List[float]]:
    """Solve the normal equations of rows.x = y (Gaussian elimination, partial pivoting)."""
    n = len(rows[0])
    g = [[0.0] * (n + 1) for _ in range(n)]
    for r in range(len(rows)):
        row = rows[r]
        for i in range(n):
            gi = g[i]
            ri = row[i]
            for j in range(n):
                gi[j] += ri * row[j]
            gi[n] += ri * y[r]
    for i in range(n):
        p = i
        for k in range(i + 1, n):
            if abs(g[k][i]) > abs(g[p][i]):
                p = k
        if abs(g[p][i]) < 1e-12:
            return None
        g[i], g[p] = g[p], g[i]
        for k in range(i + 1, n):
            f = g[k][i] / g[i][i]
            for j in range(i, n + 1):
                g[k][j] -= f * g[i][j]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = g[i][n]
        for j in range(i + 1, n):
            s -= g[i][j] * x[j]
        x[i] = s / g[i][i]
    return x


def baseline_degree(cycles: float) -> int:
    return int(_js_min(6, _js_max(2, _js_round(cycles / 3))))


def fit_sine(
    time: List[float], value: List[float], omega: float, degree: int = 2
) -> Optional[SineFit]:
    n = len(time)
    terms = degree + 3
    if n != len(value) or n < terms + 3 or not (omega > 0):
        return None
    mid = (time[0] + time[n - 1]) / 2
    half = (time[n - 1] - time[0]) / 2
    if not (half > 0):
        return None

    rows: List[List[float]] = []
    for i in range(n):
        u = (time[i] - mid) / half
        row = [0.0] * terms
        p = 1.0
        for d in range(degree + 1):
            row[d] = p
            p *= u
        row[degree + 1] = math.cos(omega * time[i])
        row[degree + 2] = math.sin(omega * time[i])
        rows.append(row)
    x = _least_squares(rows, value)
    if x is None:
        return None

    ss = 0.0
    for i in range(n):
        fit = 0.0
        for j in range(terms):
            fit += rows[i][j] * x[j]
        ss += (value[i] - fit) ** 2
    amplitude = math.hypot(x[degree + 1], x[degree + 2])
    if not (amplitude > 0) or not math.isfinite(amplitude):
        return None
    sigma = math.sqrt(ss / (n - terms))
    return SineFit(
        amplitude=amplitude,
        phase=math.atan2(x[degree + 2], x[degree + 1]),
        sigma=sigma,
        se_phase=(sigma / amplitude) * math.sqrt(2 / n),
        n=n,
    )


def remove_period_mean(
    time: List[float], value: List[float], period: float
) -> Tuple[List[float], List[float]]:
    n = len(time)
    t: List[float] = []
    v: List[float] = []
    if n < 4 or not (period > 0):
        return t, v
    integral = [0.0] * n
    for i in range(1, n):
        integral[i] = integral[i - 1] + 0.5 * (value[i] + value[i - 1]) * (time[i] - time[i - 1])

    def up_to(x: float, j: int) -> Tuple[float, int]:
        while j < n - 2 and time[j + 1] < x:
            j += 1
        f = _div(x - time[j], time[j + 1] - time[j])
        vx = value[j] + f * (value[j + 1] - value[j])
        return integral[j] + 0.5 * (value[j] + vx) * (x - time[j]), j

    ja = 0
    jb = 0
    for i in range(n):
        a = time[i] - period / 2
        b = time[i] + period / 2
        if a < time[0] or b > time[n - 1]:
            continue
        lower = up_to(a, ja)
        ja = lower[1]
        upper = up_to(b, jb)
        jb = upper[1]
        t.append(time[i])
        v.append(value[i] - (upper[0] - lower[0]) / period)
    return t, v


def refine_period(time: List[float], value: List[float], period: float) -> float:
    n = len(time)
    if n < 12 or not (period > 0):
        return period
    cycles = (time[n - 1] - time[0]) / period
    if not (cycles >= 4):
        return period
    degree = baseline_degree(cycles)
    span = _js_min(0.04, 0.4 / cycles)

    def amp(f: float) -> float:
        r = fit_sine(time, value, 2 * math.pi * f, degree)
        return r.amplitude if r is not None else 0.0

    f0 = 1 / period
    a = f0 * (1 - span)
    b = f0 * (1 + span)
    g = (math.sqrt(5) - 1) / 2
    c = b - g * (b - a)
    d = a + g * (b - a)
    fc = amp(c)
    fd = amp(d)
    for _ in range(24):
        if fc > fd:
            b = d
            d = c
            fd = fc
            c = b - g * (b - a)
            fc = amp(c)
        else:
            a = c
            c = d
            fc = fd
            d = a + g * (b - a)
            fd = amp(d)
    best = (a + b) / 2
    return 1 / best if amp(best) >= amp(f0) else period


def lag_into_period(lag: float, period: float) -> float:
    """Bring a lag into [0, T); `%` follows JS (sign of the dividend)."""
    try:
        m = math.fmod(lag, period)
    except ValueError:
        return math.nan
    return m + period if m < 0 else m


def choose_lag_cycle(lag: float, period: float, shift: float = 0) -> LagChoice:
    lag0 = lag_into_period(lag, period)
    cycles = int(_js_max(0, _js_round(shift)))
    frac = lag0 / period
    return LagChoice(
        dt=lag0 + cycles * period,
        cycles=cycles,
        near_edge=cycles == 0 and (frac < 0.02 or frac > 0.9),
    )


def _slice(time: List[float], value: List[float], lo: float, hi: float) -> Tuple[List[float], List[float]]:
    t: List[float] = []
    v: List[float] = []
    for i in range(len(time)):
        if time[i] >= lo and time[i] < hi:
            t.append(time[i])
            v.append(value[i])
    return t, v


def sine_lag(
    t_src: List[float],
    v_src: List[float],
    t_cal: List[float],
    v_cal: List[float],
    period: float,
) -> Optional[SineLag]:
    if len(t_src) < 8 or len(t_cal) < 8 or not (period > 0):
        return None
    omega = (2 * math.pi) / period

    span = _js_min(t_src[-1], t_cal[-1]) - _js_max(t_src[0], t_cal[0])
    if span / period >= 3:
        s_t, s_v = remove_period_mean(t_src, v_src, period)
        c_t, c_v = remove_period_mean(t_cal, v_cal, period)
        if len(s_t) >= 8 and len(c_t) >= 8:
            t_src, v_src, t_cal, v_cal = s_t, s_v, c_t, c_v
    start = _js_max(t_src[0], t_cal[0])
    end = _js_min(t_src[-1], t_cal[-1])
    cycles = (end - start) / period

    src = fit_sine(t_src, v_src, omega, 2)
    cal = fit_sine(t_cal, v_cal, omega, 2)
    if src is None or cal is None:
        return None
    lag = lag_into_period((cal.phase - src.phase) / omega, period)

    per = 2 if cycles >= 6 else 1
    count = math.floor(cycles / per)
    block_lags: List[float] = []
    if count >= 3:
        for k in range(count):
            a = start + k * per * period
            s_t, s_v = _slice(t_src, v_src, a, a + per * period)
            c_t, c_v = _slice(t_cal, v_cal, a, a + per * period)
            fs = fit_sine(s_t, s_v, omega, 1)
            fc = fit_sine(c_t, c_v, omega, 1)
            if fs is None or fc is None:
                continue
            d = lag_into_period((fc.phase - fs.phase) / omega, period) - lag
            if d > period / 2:
                d -= period
            if d < -period / 2:
                d += period
            block_lags.append(lag + d)

    lag_se: Optional[float]
    se_source = "formal"
    if len(block_lags) >= 3:
        m = 0.0
        for x in block_lags:
            m += x
        m = m / len(block_lags)
        acc = 0.0
        for x in block_lags:
            acc += (x - m) ** 2
        sd = math.sqrt(acc / (len(block_lags) - 1))
        lag_se = sd / math.sqrt(len(block_lags))
        se_source = "blocks"
    else:
        se = math.hypot(src.se_phase, cal.se_phase) / omega
        lag_se = se if math.isfinite(se) else None

    if lag_se is not None:
        lo = 0.0
        hi = 0.0
        for degree in (1, 3):
            s = fit_sine(t_src, v_src, omega, degree)
            c = fit_sine(t_cal, v_cal, omega, degree)
            if s is None or c is None:
                continue
            d = lag_into_period((c.phase - s.phase) / omega, period) - lag
            if d > period / 2:
                d -= period
            if d < -period / 2:
                d += period
            lo = _js_min(lo, d)
            hi = _js_max(hi, d)
        lag_se = math.hypot(lag_se, (hi - lo) / 2)

    return SineLag(
        lag=lag,
        se_source=se_source,
        blocks=len(block_lags),
        amplitude_src=src.amplitude,
        amplitude_cal=cal.amplitude,
        phase_src=src.phase,
        lag_se=lag_se,
    )


def refine_peak(
    time: List[float], value: List[float], around: float, period: float
) -> Optional[Tuple[float, float]]:
    """Returns (time, value) of the refined peak, or None."""
    n = len(time)
    if n < 5 or not (period > 0):
        return None
    reach = period / 4
    lo = 0
    while lo < n - 1 and time[lo] < around - reach:
        lo += 1
    hi = n - 1
    while hi > 0 and time[hi] > around + reach:
        hi -= 1
    if hi - lo < 4:
        return None

    step = (time[hi] - time[lo]) / (hi - lo)
    w = int(_js_max(1, _js_round(_div(period / 20, step))))
    best = lo
    best_val = -math.inf
    for i in range(lo, hi + 1):
        s = 0.0
        c = 0
        for j in range(max(lo, i - w), min(hi, i + w) + 1):
            s += value[j]
            c += 1
        if s / c > best_val:
            best_val = s / c
            best = i

    centre = time[best]
    peak: Optional[Tuple[float, float]] = None
    for _ in range(2):
        rows: List[List[float]] = []
        y: List[float] = []
        for i in range(lo, hi + 1):
            d = time[i] - centre
            if abs(d) <= period / 8:
                rows.append([1.0, d, d * d])
                y.append(value[i])
        if len(rows) < 4:
            break
        c = _least_squares(rows, y)
        if c is None or not (c[2] < 0):
            break
        shift = _js_max(-period / 8, _js_min(period / 8, -c[1] / (2 * c[2])))
        at = _js_max(around - reach, _js_min(around + reach, centre + shift))
        d = at - centre
        peak = (at, c[0] + c[1] * d + c[2] * d * d)
        centre = at
    return peak if peak is not None else (time[best], value[best])
