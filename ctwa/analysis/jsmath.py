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


def js_truthy(x) -> bool:
    """JS truthiness of a number, string, bool or null: false for 0, -0, NaN, "", None."""
    if x is None:
        return False
    if isinstance(x, float) and x != x:
        return False
    return bool(x)


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


# ---------------------------------------------------------------------------
# Number -> string, exactly as JavaScript prints numbers.
# ---------------------------------------------------------------------------

def _nonfinite_text(x: float) -> str:
    if x != x:
        return "NaN"
    return "Infinity" if x > 0 else "-Infinity"


def js_number_to_string(x: float) -> str:
    """String(x) / template-literal formatting of a number (shortest round-trip)."""
    if x != x or x in (math.inf, -math.inf):
        return _nonfinite_text(x)
    if x == 0:
        return "0"  # also for -0
    sign = "-" if x < 0 else ""
    # repr() gives the shortest round-trip digits, the same digits JS uses.
    from decimal import Decimal
    t = Decimal(repr(abs(float(x)))).as_tuple()
    digits = "".join(map(str, t.digits)).rstrip("0")
    # value = 0.DIGITS * 10**n, i.e. n is the decimal point position
    n = len("".join(map(str, t.digits))) + t.exponent
    k = len(digits)
    if k <= n <= 21:
        body = digits + "0" * (n - k)
    elif 0 < n <= 21:
        body = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        exp = ("+" if e >= 0 else "-") + str(abs(e))
        body = digits[0] + ("." + digits[1:] if k > 1 else "") + "e" + exp
    return sign + body


def js_to_fixed(x: float, digits: int) -> str:
    """Number.prototype.toFixed: exact binary value, ties go to the larger n."""
    from fractions import Fraction
    if x != x or x in (math.inf, -math.inf):
        return _nonfinite_text(x)
    if abs(x) >= 1e21:
        return js_number_to_string(x)
    sign = "-" if x < 0 else ""  # -0 and 0 print without a sign
    scaled = Fraction(abs(float(x))) * 10 ** digits
    n = int(math.floor(scaled + Fraction(1, 2)))
    text = str(n)
    if digits:
        text = text.rjust(digits + 1, "0")
        text = text[:-digits] + "." + text[-digits:]
    return sign + text


def js_to_precision(x: float, precision: int) -> str:
    """Number.prototype.toPrecision (precision given, 1..100)."""
    from fractions import Fraction
    if x != x or x in (math.inf, -math.inf):
        return _nonfinite_text(x)
    sign = "-" if x < 0 else ""
    if x == 0:
        return "0" + ("." + "0" * (precision - 1) if precision > 1 else "")
    ax = Fraction(abs(float(x)))
    e = int(math.floor(math.log10(abs(float(x)))))
    for _ in range(3):  # settle the decade exactly (log10 can be off by one)
        scale = Fraction(10) ** (e - precision + 1)
        n = int(math.floor(ax / scale + Fraction(1, 2)))
        if n >= 10 ** precision:
            e += 1
        elif n < 10 ** (precision - 1):
            e -= 1
        else:
            break
    digits = str(n)
    if e < -6 or e >= precision:
        body = digits[0] + ("." + digits[1:] if precision > 1 else "")
        return sign + body + "e" + ("+" if e >= 0 else "-") + str(abs(e))
    if e == precision - 1:
        return sign + digits
    if e >= 0:
        return sign + digits[:e + 1] + "." + digits[e + 1:]
    return sign + "0." + "0" * (-(e + 1)) + digits
