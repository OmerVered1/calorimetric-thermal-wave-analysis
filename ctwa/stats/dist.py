"""Box and violin maths, exactly Plotly's (3.x): linear quartiles, fence whiskers, Silverman KDE.

Sources: plotly.js lib/stats.js (interp), lib/search.js (findBin), traces/box/calc.js (fences),
traces/violin/calc.js (bandwidth, soft span, sampling) and traces/violin/helpers.js (makeKDE).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import List, Optional, Sequence

__all__ = ["interp", "BoxStats", "box_stats", "silverman_bandwidth", "ViolinShape", "violin_shape", "jitter_x",
           "HALF_WIDTH"]

HALF_WIDTH = 0.35          # box and violin half-width (category spacing 1, gap 0.3)
_POINTPOS = -1.5
_JITTER = 0.3
_ROUNDING = 1e-9


def interp(arr: Sequence[float], q: float) -> float:
    """Plotly's Lib.interp: position q*N - 0.5, clamped to the ends, linear between neighbours."""
    n = q * len(arr) - 0.5
    if n < 0:
        return arr[0]
    if n > len(arr) - 1:
        return arr[-1]
    frac = n % 1
    return frac * arr[int(math.ceil(n))] + (1 - frac) * arr[int(math.floor(n))]


def _find_bin(val: float, bins: Sequence[float], linelow: bool = False) -> int:
    """Lib.findBin for an array of bin edges (binary search; a value on an edge goes up, or down with linelow)."""
    n1, n2 = 0, len(bins)
    bin_size = (bins[n2 - 1] - bins[0]) / (n2 - 1) if n2 > 1 else 1
    val += bin_size * _ROUNDING * (-1 if linelow else 1)     # bins are ascending here
    while n1 < n2:
        n = (n1 + n2) // 2
        less = bins[n] < val if linelow else bins[n] <= val
        if less:
            n1 = n + 1
        else:
            n2 = n
    return n1 - 1


@dataclass(frozen=True)
class BoxStats:
    n: int
    q1: float
    med: float
    q3: float
    lo_whisker: float      # Plotly's lower fence ``lf``
    hi_whisker: float      # Plotly's upper fence ``uf``
    mean: float


def _sum_mean(v: Sequence[float]) -> float:
    s = 0.0
    for x in v:
        s += x
    return s / len(v)


def box_stats(vals: Sequence[float]) -> Optional[BoxStats]:
    """Quartiles (linear method), median, mean and the fence whiskers of one box; None for no values.

    As Plotly: lf = min(q1, lowest point >= q1 - 1.5 IQR) and uf = max(q3, highest point <= q3 + 1.5 IQR),
    so a whisker is never shorter than the box edge (with a far outlier the upper whisker can be 0 long)."""
    v = sorted(float(x) for x in vals)
    n = len(v)
    if n == 0:
        return None
    q1, q3 = interp(v, 0.25), interp(v, 0.75)
    lf = min(q1, v[min(_find_bin(2.5 * q1 - 1.5 * q3, v, True) + 1, n - 1)])
    uf = max(q3, v[max(_find_bin(2.5 * q3 - 1.5 * q1, v), 0)])
    return BoxStats(n, q1, interp(v, 0.5), q3, lf, uf, _sum_mean(v))


def _bandwidth(v: List[float], q1: float, q3: float, mean: float) -> float:
    span = v[-1] - v[0]
    if not span:
        return 0.0
    n = len(v)
    s = 0.0
    for x in v:
        s += (x - mean) ** 2
    ssd = math.sqrt(s / (n - 1))                           # Lib.stdev(vals, len - 1, mean)
    silverman = 1.059 * min(ssd, (q3 - q1) / 1.349) * n ** -0.2
    return max(silverman, span / 100)


def silverman_bandwidth(vals: Sequence[float]) -> float:
    """Plotly's violin bandwidth: Silverman's rule floored at span/100; 0 for a zero span (or no values)."""
    v = sorted(float(x) for x in vals)
    if not v:
        return 0.0
    return _bandwidth(v, interp(v, 0.25), interp(v, 0.75), _sum_mean(v))


@dataclass(frozen=True)
class ViolinShape:
    ts: List[float]
    half_widths: List[float]       # density scaled so its maximum is the full half-width
    bandwidth: float


_SQRT_2PI_INV = 1 / math.sqrt(2 * math.pi)


def violin_shape(vals: Sequence[float], half_width: float = HALF_WIDTH) -> Optional[ViolinShape]:
    """The violin outline: Gaussian KDE over the soft span [min - 2 bw, max + 2 bw], sampled every ~bw/3."""
    v = sorted(float(x) for x in vals)
    if not v:
        return None
    bw = _bandwidth(v, interp(v, 0.25), interp(v, 0.75), _sum_mean(v))
    if v[0] == v[-1] and bw == 0:
        return ViolinShape([v[0], v[0]], [0.0, 0.0], 0.0)      # zero span: a zero-width violin
    lo, hi = v[0] - 2 * bw, v[-1] + 2 * bw
    dist = hi - lo
    n = int(math.ceil(dist / (bw / 3)))
    step = dist / n
    factor = 1 / (len(v) * bw)
    ts: List[float] = []
    dens: List[float] = []
    for k in range(n + 1):
        t = lo + k * step
        s = 0.0
        for x in v:
            u = (t - x) / bw
            s += _SQRT_2PI_INV * math.exp(-0.5 * u * u)
        ts.append(t)
        dens.append(factor * s)
    top = max(dens)
    return ViolinShape(ts, [d / top * half_width for d in dens], bw)


def jitter_x(index: int, n: int, half_width: float = HALF_WIDTH) -> List[float]:
    """x of the n points of category ``index``: pointpos -1.5, jitter 0.3, seeded by the index (stable)."""
    rng = random.Random(index)
    return [index + half_width * (_POINTPOS + _JITTER * (2 * rng.random() - 1)) for _ in range(n)]
