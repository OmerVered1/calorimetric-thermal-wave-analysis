"""Pure helpers shared by the chart renderers: log masking, polygon hit-testing, dash styles."""
from __future__ import annotations

from typing import List, Sequence, Tuple

import numpy as np
from PySide6.QtCore import Qt

__all__ = ["mask_for_log", "to_view", "view_value", "points_in_polygon", "qt_dash", "slugify"]

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
