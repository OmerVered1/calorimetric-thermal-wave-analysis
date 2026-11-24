"""JavaScript number semantics for the analysis port.

Python raises where JavaScript returns NaN or +-Infinity (x / 0, fmod, log of
a non-positive number, cos of Infinity, floor of Infinity). The port keeps the
TypeScript's behaviour, so every operation that can differ lives here.
"""

from __future__ import annotations

import math
from typing import Iterable

from ctwa.analysis.jstrig import cos_array, sin_array


# JS whitespace (String.prototype.trim, regex \s)
JS_WHITESPACE = (" \t\n\v\f\r\u00a0\u1680" + "".join(map(chr, range(0x2000, 0x200B)))
       + "\u2028\u2029\u202f\u205f\u3000\ufeff")


def js_trim(s: str) -> str:
    """String.prototype.trim: strips exactly the JS whitespace set."""
    return s.strip(JS_WHITESPACE)


def js_div(a: float, b: float) -> float:
    """JS division: x/0 gives +-Infinity or NaN instead of raising."""
    try:
        return a / b
    except ZeroDivisionError:
        if a != a or a == 0:
            return math.nan
        neg = (a < 0) != (math.copysign(1.0, b) < 0)
        return -math.inf if neg else math.inf


def js_floor(x: float) -> float:
    """Math.floor: NaN and +-Infinity pass through (math.floor raises on them)."""
    if x != x or x in (math.inf, -math.inf):
        return x
    return float(math.floor(x))


def js_ceil(x: float) -> float:
    """Math.ceil: NaN and +-Infinity pass through (math.ceil raises on them)."""
    if x != x or x in (math.inf, -math.inf):
        return x
    return float(math.ceil(x))


def js_round(x: float) -> float:
    """Math.round: floor(x + 0.5); NaN and +-Infinity pass through."""
    if x != x or x in (math.inf, -math.inf):
        return x
    return js_floor(x + 0.5)


def js_min(a: float, b: float) -> float:
    """Math.min of two numbers (NaN propagates)."""
    if a != a or b != b:
        return math.nan
    return a if a < b else b


def js_max(a: float, b: float) -> float:
    """Math.max of two numbers (NaN propagates)."""
    if a != a or b != b:
        return math.nan
    return a if a > b else b


def js_fmod(a: float, b: float) -> float:
    """JS `a % b`: the sign of the dividend; NaN for b == 0, a infinite or NaN."""
    try:
        return math.fmod(a, b)
    except ValueError:
        return math.nan


def js_log(x: float) -> float:
    """Math.log: -Infinity at 0, NaN below 0."""
    if x != x or x < 0:
        return math.nan
    if x == 0:
        return -math.inf
    return math.log(x)


def js_sqrt(x: float) -> float:
    """Math.sqrt: NaN below 0."""
    if x != x or x < 0:
        return math.nan
    return math.sqrt(x)


def js_cos(x: float) -> float:
    """Math.cos as V8 computes it (fdlibm, see jstrig); NaN for Infinity."""
    return float(cos_array([x])[0])


def js_sin(x: float) -> float:
    """Math.sin as V8 computes it (fdlibm, see jstrig); NaN for Infinity."""
    return float(sin_array([x])[0])


def array_max(a: Iterable[float]) -> float:
    """The webapp's arrayMax loop: starts at -Infinity, `x > v` (NaN is skipped)."""
    v = -math.inf
    for x in a:
        if x > v:
            v = x
    return v


def array_min(a: Iterable[float]) -> float:
    """The webapp's arrayMin loop: starts at Infinity, `x < v` (NaN is skipped)."""
    v = math.inf
    for x in a:
        if x < v:
            v = x
    return v
