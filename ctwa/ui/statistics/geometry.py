"""Pure helpers shared by the chart renderers: log masking, polygon hit-testing, dash styles."""
from __future__ import annotations

import math
from typing import List, Sequence, Tuple

import numpy as np
from PySide6.QtCore import Qt

__all__ = ["log_ticks", "mask_for_log", "to_view", "view_value", "points_in_polygon", "qt_dash", "slugify"]

_DASH = {"solid": Qt.SolidLine, "dash": Qt.DashLine, "dot": Qt.DotLine, "dashdot": Qt.DashDotLine}


def qt_dash(name: str):
    return _DASH.get(name, Qt.SolidLine)


def mask_for_log(xs: Sequence[float], ys: Sequence[float], xlog: bool, ylog: bool
                 ) -> Tuple[np.ndarray, np.ndarray, List[int]]:
    """Keep the points that can be drawn: finite, and > 0 on every log axis (Plotly skips the others too).

    Returns (xs, ys, kept_idx): the kept values (original units) and their indices in the input."""
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    keep = np.isfinite(x) & np.isfinite(y)
    with np.errstate(invalid="ignore"):
        if xlog:
            keep &= x > 0
        if ylog:
            keep &= y > 0
    idx = np.nonzero(keep)[0]
    return x[idx], y[idx], [int(i) for i in idx]


def to_view(vals, log: bool) -> np.ndarray:
    """Values in view coordinates (log10 on a log axis; the caller has masked non-positive values)."""
    a = np.asarray(vals, dtype=float)
    if not log:
        return a
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.log10(a)


def view_value(v: float, log: bool) -> float:
    import math
    return math.log10(v) if log else v


def points_in_polygon(poly: Sequence[Tuple[float, float]], xs, ys) -> np.ndarray:
    """Even-odd rule for many points at once; ``poly`` and the points share one coordinate system."""
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    inside = np.zeros(x.shape, dtype=bool)
    n = len(poly)
    if n < 3 or x.size == 0:
        return inside
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if yi != yj:
            cross = (yi > y) != (yj > y)
            with np.errstate(invalid="ignore", divide="ignore"):
                xcut = (xj - xi) * (y - yi) / (yj - yi) + xi
            inside ^= cross & (x < xcut)
        j = i
    return inside


def slugify(text: str) -> str:
    """File-name suggestion: lowercase, runs of non-alphanumerics become one '-'."""
    import re
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "chart"


Tick = Tuple[float, str]
_WIDE_PX_PER_DECADE = 160       # room to label 1, 2 and 5
_DENSE_PX_PER_DECADE = 50       # below this even the decades are thinned and no subticks are drawn
_LABEL_PX = 40


def _log_label(mant: int, exp: int) -> str:
    if -4 <= exp <= 5:
        return "%g" % (mant * 10.0 ** exp)
    return "%de%d" % (mant, exp) if mant != 1 else "1e%d" % exp


def log_ticks(lo: float, hi: float, px: float) -> Tuple[List[Tick], List[Tick]]:
    """(major, minor) ticks for a log axis shown from 10**lo to 10**hi over ``px`` pixels (positions are log10).

    Roomy axis: 1, 2 and 5 of every decade are labelled and the other digits are unlabelled subticks. Medium:
    decades are labelled, 2 and 5 are unlabelled subticks. Crowded: only decades, and only every n-th of them
    carries a label (no subticks)."""
    span = hi - lo
    if not span > 0 or px <= 0:
        return [], []
    ppd = px / span
    eps = 1e-9
    major: List[Tick] = []
    minor: List[Tick] = []
    first, last = int(math.floor(lo - eps)), int(math.ceil(hi + eps))
    every = 1 if ppd >= _DENSE_PX_PER_DECADE else int(math.ceil(_LABEL_PX / ppd))
    for e in range(first, last + 1):
        for m in range(1, 10):
            pos = e + math.log10(m)
            if pos < lo - eps or pos > hi + eps:
                continue
            if ppd >= _WIDE_PX_PER_DECADE:
                (major if m in (1, 2, 5) else minor).append((pos, _log_label(m, e) if m in (1, 2, 5) else ""))
            elif m == 1:
                major.append((float(e), _log_label(1, e) if e % every == 0 else ""))
            elif m in (2, 5) and ppd >= _DENSE_PX_PER_DECADE:
                minor.append((pos, ""))
    return major, minor
