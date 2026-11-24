"""Display helpers for saved results: literal ports of the webapp's.

format_alpha / parse_test_date: lib/utils.ts; with_ln_validity: lib/analysisColumns.ts;
run_label: components/ui/RunLabel.tsx; row_matches: the Summary page's search;
material_color: lib/materialColors.ts (ported in ctwa.analysis.references).
"""
from __future__ import annotations

import math
import re
from datetime import date, timedelta
from typing import Any, Dict, Optional

from ctwa.analysis.jsmath import (js_div, js_log, js_number_to_string, js_round, js_sqrt,
                                  js_to_precision)
from ctwa.analysis.references import material_color

__all__ = ["format_alpha", "parse_test_date", "with_ln_validity", "run_label", "row_matches",
           "material_color"]

DASH = "—"


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def format_alpha(v: Optional[float]) -> str:
    """alpha (m^2/s) as mm^2/s with 4 significant digits; "—" for None, 0 and non-finite."""
    if v is None or not _is_number(v) or v == 0 or not math.isfinite(v):
        return DASH
    return js_to_precision(v * 1e6, 4)


# ---- test dates ----

_DEC = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?\Z")
# JS WhiteSpace + LineTerminator (what trim(), \s and Number() see)
_JS_WS = "\t\n\v\f\r              " \
         "    　﻿"


def _js_number(s: str) -> float:
    """Number(string) for what a date part can look like; NaN when JS gives NaN."""
    t = s.strip(_JS_WS)
    if not t:
        return 0.0
    try:
        if _DEC.match(t):
            return float(t)
        m = re.match(r"0([xXoObB])([0-9a-fA-F]+)\Z", t)
        if m:
            return float(int(m.group(2), {"x": 16, "o": 8, "b": 2}[m.group(1).lower()]))
        if t in ("Infinity", "+Infinity"):
            return math.inf
        if t == "-Infinity":
            return -math.inf
    except (ValueError, OverflowError):
        pass
    return math.nan


def parse_test_date(s: Optional[str]) -> Optional[date]:
    """DD/MM/YYYY as the webapp reads it: split on "/", Number() each part, new Date(y, m-1, d).

    As in JS: years 0-99 mean 1900-1999 and day/month overflow rolls over (31/02 -> 3 March).
    None where the webapp gives its epoch placeholder or an Invalid Date, and for dates Python's
    date cannot hold (year outside 1..9999)."""
    if s is None:
        return None
    parts = str(s).split("/")
    if len(parts) != 3:
        return None
    day, month, year = (_js_number(p) for p in parts)
    if not all(math.isfinite(x) for x in (day, month, year)):
        return None
    day, month, year = int(day), int(month), int(year)   # ToIntegerOrInfinity truncates
    if 0 <= year <= 99:
        year += 1900
    year += (month - 1) // 12
    month0 = (month - 1) % 12
    if not 1 <= year <= 9999:
        return None
    try:
        return date(year, month0 + 1, 1) + timedelta(days=day - 1)
    except (OverflowError, ValueError):
        return None


# ---- ln validity ----

def with_ln_validity(row: Dict[str, Any]) -> Dict[str, Any]:
    """withLnValidity: a stored ln of 1 (the old "replace a bad ln with 1") or <= 0 is recomputed from
    the amplitudes and radii; if it is not positive, alpha combined (raw and cal) become None and
    ln_term the true ln. Always a new dict; for display only, never write it back."""
    out = dict(row)
    stored = row.get("ln_term")
    if stored is not None and _is_number(stored) and stored > 0 and stored != 1:
        return out
    a1, a2, r1, r2 = (row.get(k) for k in ("amplitude_a1", "amplitude_a2", "r1_mm", "r2_mm"))
    if not all(_is_number(x) and x > 0 for x in (a1, a2, r1, r2)):
        return out
    ln = js_log(js_div(a1, a2) * js_sqrt(js_div(r1, r2)))
    if ln > 0:
        return out
    out.update(ln_term=ln, alpha_combined_raw=None, alpha_combined_cal=None)
    return out


# ---- labels and search ----

def _js_str(v: Any) -> str:
    """String(v ?? '')"""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if _is_number(v):
        return js_number_to_string(float(v))
    return str(v)


def run_label(row: Dict[str, Any]) -> str:
    """"Stainless Steel · 766 °C · 600 s · #254" (runLabelText)."""
    parts = [_js_str(row.get("model_name"))]
    t = row.get("temperature_c")
    if t is not None:
        parts.append("%s °C" % _js_str(t))
    p = row.get("period_t")
    if p is not None and _is_number(p) and math.isfinite(p):
        parts.append("%s s" % js_number_to_string(js_round(float(p))))
    parts.append("#%s" % _js_str(row.get("id")))
    return " · ".join(parts)


_WS_SPLIT = re.compile("[" + _JS_WS + "]+")
_SEARCH_FIELDS = ("id", "model_name", "test_date", "analysis_mode", "gas_atmosphere", "temperature_c",
                  "power_source_device", "power_response_device")


def row_matches(row: Dict[str, Any], query: str) -> bool:
    """Summary search: every word (# ignored) must be found in some searched field, case-insensitive."""
    terms = [t for t in _WS_SPLIT.split(query.lower().replace("#", "")) if t]
    hay = [_js_str(row.get(k)).lower() for k in _SEARCH_FIELDS]
    return all(any(term in h for h in hay) for term in terms)
