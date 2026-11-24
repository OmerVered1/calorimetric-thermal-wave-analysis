"""Device-lag curve fitting (literal port of lib/lagFit.ts).

Given the device lags derived from a set of reference runs, fit lag(P) so the
lag can be evaluated at any period inside the fitted range. Every model is
fitted (sqrt, linear, power, physical second-order) and the caller chooses,
guided by the reported RMS.
"""

from __future__ import annotations

import math
from typing import Callable, List, Optional, Tuple

from ctwa.analysis.jsmath import (
    js_div, js_log, js_number_to_string, js_sqrt, js_to_fixed, js_to_precision,
)
from ctwa.analysis.types import LagFit, LagPoint

# Minimum points before a two-parameter fit means anything.
MIN_POINTS = 3


def _pow(x: float, y: float) -> float:
    """Math.pow for the finite positive bases used here (overflow gives Infinity)."""
    try:
        return math.pow(x, y)
    except OverflowError:
        return math.inf


def _exp(x: float) -> float:
    try:
        return math.exp(x)
    except OverflowError:
        return math.inf


def _rms_of(points: List[LagPoint], predict: Callable[[float], float]) -> float:
    sse = 0.0
    for p in points:
        d = p.lag - predict(p.period)
        sse += d * d
    return js_sqrt(js_div(sse, len(points)))


def _r2_of(points: List[LagPoint], predict: Callable[[float], float]) -> float:
    total = 0.0
    for p in points:
        total += p.lag
    mean = total / len(points)
    ss_res = 0.0
    ss_tot = 0.0
    for p in points:
        d = p.lag - predict(p.period)
        ss_res += d * d
        e = p.lag - mean
        ss_tot += e * e
    if ss_tot == 0:
        return 0
    return 1 - js_div(ss_res, ss_tot)


def _linear_least_squares(
    points: List[LagPoint],
    x: Callable[[LagPoint], float],
    y: Optional[Callable[[LagPoint], float]] = None,
) -> Optional[Tuple[float, float]]:
    """Closed-form least squares for y = a + b*x. None if degenerate."""
    if y is None:
        y = lambda p: p.lag  # noqa: E731
    n = len(points)
    sx = sy = sxx = sxy = 0.0
    for p in points:
        xi = x(p)
        yi = y(p)
        if not (math.isfinite(xi) and math.isfinite(yi)):
            return None
        sx += xi
        sy += yi
        sxx += xi * xi
        sxy += xi * yi
    denom = n * sxx - sx * sx
    if denom == 0 or not math.isfinite(denom):
        return None
    b = (n * sxy - sx * sy) / denom
    a = (sy - b * sx) / n
    if not math.isfinite(a) or not math.isfinite(b):
        return None
    return a, b


def _physical_predict(tau1: float, tau2: float) -> Callable[[float], float]:
    """dt(w) = [atan(w*tau1) + atan(w*tau2)] / w,  w = 2*pi/P."""
    def predict(period_s: float) -> float:
        w = js_div(2 * math.pi, period_s)
        return js_div(math.atan(w * tau1) + math.atan(w * tau2), w)
    return predict


def _fit_physical(points: List[LagPoint]) -> Optional[Tuple[float, float]]:
    tau_min, tau_max = 1, 5000
    best: List[Optional[Tuple[float, float, float]]] = [None]  # (tau1, tau2, err)

    def consider(tau1: float, tau2: float) -> None:
        if tau2 < tau1:
            return
        if not (tau1 > 0) or not (tau2 > 0):
            return
        err = _rms_of(points, _physical_predict(tau1, tau2))
        cur = best[0]
        if math.isfinite(err) and (cur is None or err < cur[2]):
            best[0] = (tau1, tau2, err)

    # Coarse logarithmic scan.
    grid = 70
    for i in range(grid):
        tau1 = tau_min * _pow(tau_max / tau_min, i / (grid - 1))
        for j in range(grid):
            tau2 = tau_min * _pow(tau_max / tau_min, j / (grid - 1))
            consider(tau1, tau2)
    if best[0] is None:
        return None

    # Local refinement, shrinking the step each pass.
    for pass_ in range(3):
        step = _pow(1.15, _pow(0.6, pass_))
        anchor = best[0]
        for i in range(-12, 13):
            for j in range(-12, 13):
                consider(anchor[0] * _pow(step, i), anchor[1] * _pow(step, j))
    return best[0][0], best[0][1]


def _fmt(v: float) -> str:
    if not math.isfinite(v):
        return "—"
    a = abs(v)
    if a >= 100:
        return js_to_fixed(v, 1)
    if a >= 1:
        return js_to_fixed(v, 3)
    return js_to_precision(v, 4)


def fit_lag_models(points: List[LagPoint]) -> List[LagFit]:
    """Fit every applicable model, sorted best (lowest RMS) first.

    Returns [] when there are too few usable points.
    """
    usable = [p for p in points
              if math.isfinite(p.period) and math.isfinite(p.lag) and p.period > 0]
    if len(usable) < MIN_POINTS:
        return []

    periods = [p.period for p in usable]
    p_min = min(periods)
    p_max = max(periods)
    # A fit needs at least two distinct periods.
    if p_min == p_max:
        return []

    fits: List[LagFit] = []

    def push(kind: str, params: List[float], label: str,
             predict: Callable[[float], float]) -> None:
        rms = _rms_of(usable, predict)
        if not math.isfinite(rms):
            return
        fits.append(LagFit(kind=kind, params=params, label=label, predict=predict,
                           rms=rms, r2=_r2_of(usable, predict),
                           n=len(usable), p_min=p_min, p_max=p_max))

    # lag = a + b*sqrt(P)
    sq = _linear_least_squares(usable, lambda p: js_sqrt(p.period))
    if sq:
        sa, sb = sq
        push("sqrt", [sa, sb], f"{_fmt(sa)} + {_fmt(sb)}·√P",
             lambda P, sa=sa, sb=sb: sa + sb * js_sqrt(P))

    # lag = a + b*P
    li = _linear_least_squares(usable, lambda p: p.period)
    if li:
        la, lb = li
        push("linear", [la, lb], f"{_fmt(la)} + {_fmt(lb)}·P",
             lambda P, la=la, lb=lb: la + lb * P)

    # lag = a*P^b, needs strictly positive lags for the log transform.
    if all(p.lag > 0 for p in usable):
        lg = _linear_least_squares(usable, lambda p: js_log(p.period),
                                   lambda p: js_log(p.lag))
        if lg:
            a = _exp(lg[0])
            b = lg[1]
            if math.isfinite(a):
                push("power", [a, b], f"{_fmt(a)}·P^{_fmt(b)}",
                     lambda P, a=a, b=b: a * _pow(P, b))

    # Physical second-order instrument model.
    ph = _fit_physical(usable)
    if ph:
        t1, t2 = ph
        push("physical", [t1, t2],
             f"τ₁={_fmt(t1)}s, τ₂={_fmt(t2)}s (plateau {_fmt(t1 + t2)}s)",
             _physical_predict(t1, t2))

    return sorted(fits, key=lambda f: f.rms)


def serialize_fit(fit: LagFit) -> str:
    """Compact, re-derivable description of a fit, stored on a calibrated row."""
    names = ["t1", "t2"] if fit.kind == "physical" else ["a", "b"]
    body = ",".join(f"{names[i]}={js_to_precision(v, 6)}" for i, v in enumerate(fit.params))
    return f"{fit.kind}:{body}"


def serialize_direct(lag_s: float) -> str:
    """Serialization for a lag taken directly from the references, with no curve."""
    return f"direct:lag={js_to_precision(lag_s, 6)}"


_MODEL_LABELS = {
    "sqrt": "√P",
    "linear": "linear",
    "power": "P^b",
    "physical": "τ₁/τ₂",
    "direct": "direct",
}


def describe_lag_model(serialized: Optional[str]) -> str:
    """Short display label for a stored calibration_model (contains NO COMMA)."""
    if not serialized:
        return "—"
    kind = serialized.split(":")[0]
    return _MODEL_LABELS.get(kind, kind)
