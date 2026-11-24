"""Display helpers that match JavaScript, for the Results tab.

Number formatting (toFixed, toPrecision, String(number), Number(string)) lives in
ctwa.analysis.jsmath and is re-exported here; this module adds the webapp's sort comparator
(compareCells, nextSort), run labels and the History search.
"""
from __future__ import annotations

import math
import re
import unicodedata
from typing import Any, Dict, Optional, Tuple

from ctwa.analysis.jsmath import (JS_WHITESPACE, js_number, js_number_to_string, js_round,
                                  js_to_fixed, js_to_precision)
from ctwa.results.helpers import run_label, sort_key_test_date

__all__ = ["js_to_fixed", "js_to_precision", "js_number", "compare_cells", "next_sort", "run_label_text",
           "label_of", "matches_fields", "HISTORY_SEARCH_FIELDS", "js_str"]

HISTORY_SEARCH_FIELDS = ("id", "model_name", "test_date", "analysis_mode", "temperature_c")

_DAY_MS = 86400000.0


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def js_str(v: Any) -> str:
    """String(v ?? '')"""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if _is_number(v):
        return js_number_to_string(float(v))
    return str(v)


def _to_number(v: Any) -> float:
    """Number(v) for the values a table cell can hold."""
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if _is_number(v):
        return float(v)
    return js_number(str(v))


def _locale_key(s: str) -> Tuple[str, str, str]:
    """Approximates String.prototype.localeCompare (ICU root): letters compared ignoring case and
    accents first, then accents, then case with lower case first."""
    folded = s.casefold()
    nfd = unicodedata.normalize("NFD", folded)
    base = "".join(c for c in nfd if not unicodedata.combining(c))
    return (base, nfd, s.swapcase())


def compare_cells(a: Any, b: Any, key: str) -> float:
    """compareCells of app/summary/page.tsx: dates by time (unparsable = 1970), two numbers by
    difference (null counts as 0, blank as 0), anything else as locale-ordered text."""
    if key == "test_date":
        da = sort_key_test_date(js_str(a)).toordinal()
        db = sort_key_test_date(js_str(b)).toordinal()
        return (da - db) * _DAY_MS
    na, nb = _to_number(a), _to_number(b)
    if not math.isnan(na) and not math.isnan(nb):
        return na - nb
    ka, kb = _locale_key(js_str(a)), _locale_key(js_str(b))
    return (ka > kb) - (ka < kb)


def next_sort(state: tuple, key: str) -> tuple:
    """nextSort of components/ui/Table.tsx: asc, then desc, then unsorted; a new column starts asc."""
    cur_key, cur_dir = state
    if cur_key != key:
        return (key, "asc")
    if cur_dir == "asc":
        return (key, "desc")
    return (None, None)


def run_label_text(row: Dict[str, Any]) -> str:
    """runLabelText: "Stainless Steel · 766 °C · 601 s · #254"."""
    return run_label(row)


def label_of(row: Dict[str, Any]) -> str:
    """labelOf of the Compare page: "model | date | 766°C | Ar | mode | A₁=12.3mW | T=600s #id"."""
    parts = [js_str(row.get("model_name")), js_str(row.get("test_date"))]
    t = row.get("temperature_c")
    if t is not None:
        parts.append("%s°C" % js_str(t))
    if row.get("gas_atmosphere"):
        parts.append(js_str(row.get("gas_atmosphere")))
    parts.append(js_str(row.get("analysis_mode")))
    a1 = row.get("amplitude_a1")
    if _is_number(a1) and math.isfinite(a1):
        parts.append("A₁=%smW" % js_to_fixed(a1, 1))
    p = row.get("period_t")
    if _is_number(p) and math.isfinite(p):
        parts.append("T=%ss" % js_to_fixed(p, 0))
    return "%s #%s" % (" | ".join(parts), js_str(row.get("id")))


_WS_SPLIT = re.compile("[" + re.escape(JS_WHITESPACE) + "]+")


def matches_fields(row: Dict[str, Any], query: str, fields: tuple) -> bool:
    """Search of the History/Summary pages: '#' is ignored, every word must be a lower-case
    substring of some field."""
    terms = [t for t in _WS_SPLIT.split(query.lower().replace("#", "")) if t]
    if not terms:
        return True
    hay = [js_str(row.get(k)).lower() for k in fields]
    return all(any(term in h for h in hay) for term in terms)
