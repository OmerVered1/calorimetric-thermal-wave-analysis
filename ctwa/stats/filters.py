"""Statistics filters: a literal port of the page's ``filtered`` block and its filter summary (page.tsx).

Everything is included by default; the sets hold the EXCLUDED values. ``None`` ranges mean the whole domain.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from ctwa.analysis.jsmath import js_ceil, js_floor, js_round
from ctwa.results.helpers import parse_test_date, sort_key_test_date

__all__ = ["FilterState", "ROW_KINDS", "CAL_CHOICES", "apply_filters", "distinct_values", "period_options",
           "period_domain", "a1_domain", "a1_step", "active_filters", "clear_filter", "row_period10"]

ROW_KINDS = ("originals", "copies", "all")
CAL_CHOICES = ("All", "Calibrated", "Uncalibrated")


@dataclass
class FilterState:
    exclude_models: Set[str] = field(default_factory=set)
    exclude_periods: Set[int] = field(default_factory=set)      # round10 values
    exclude_source_devices: Set[str] = field(default_factory=set)
    exclude_response_devices: Set[str] = field(default_factory=set)
    exclude_gas: Set[str] = field(default_factory=set)
    exclude_modes: Set[str] = field(default_factory=set)
    row_kind: str = "originals"
    cal: str = "All"
    period_range: Optional[Tuple[int, int]] = None
    a1_range: Optional[Tuple[float, float]] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    hidden_ids: Set[int] = field(default_factory=set)

    def copy(self) -> "FilterState":
        return replace(self, exclude_models=set(self.exclude_models), exclude_periods=set(self.exclude_periods),
                       exclude_source_devices=set(self.exclude_source_devices),
                       exclude_response_devices=set(self.exclude_response_devices),
                       exclude_gas=set(self.exclude_gas), exclude_modes=set(self.exclude_modes),
                       hidden_ids=set(self.hidden_ids))

    def reset_keep_hidden(self) -> "FilterState":
        """resetAllFilters: everything back to "all included"; hidden points are not a filter."""
        return FilterState(hidden_ids=set(self.hidden_ids))


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def row_period10(row: Dict[str, Any]) -> float:
    """Math.round(a.period_t / 10) * 10 as JS computes it: null counts as 0; NaN stays NaN."""
    p = row.get("period_t")
    if p is None:
        p = 0
    return js_round(float(p) / 10) * 10


def _row_date(s: Any) -> Optional[date]:
    """parseTestDate(...).getTime(): the epoch for anything that is not three "/" parts, None for the
    Invalid Date of three parts that are not numbers (NaN: every comparison is false, so it passes)."""
    if isinstance(s, str) and len(s.split("/")) == 3:
        return parse_test_date(s)
    return sort_key_test_date(None)


def apply_filters(rows: Iterable[Dict[str, Any]], f: FilterState) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for a in rows:
        if a.get("id") in f.hidden_ids:
            continue
        if a.get("model_name") in f.exclude_models:
            continue
        copy_of = a.get("calibrated_from_id")
        if f.row_kind == "originals" and copy_of is not None:
            continue
        if f.row_kind == "copies" and copy_of is None:
            continue
        if f.cal == "Calibrated" and not a.get("use_calibration"):
            continue
        if f.cal == "Uncalibrated" and a.get("use_calibration"):
            continue
        pv = row_period10(a)
        if f.period_range is not None and (pv < f.period_range[0] or pv > f.period_range[1]):
            continue
        if math.isfinite(pv) and int(pv) in f.exclude_periods:
            continue
        a1 = a.get("amplitude_a1")
        if f.a1_range is not None and a1 is not None and (a1 < f.a1_range[0] or a1 > f.a1_range[1]):
            continue
        if a.get("power_source_device") and a["power_source_device"] in f.exclude_source_devices:
            continue
        if a.get("power_response_device") and a["power_response_device"] in f.exclude_response_devices:
            continue
        if a.get("gas_atmosphere") and a["gas_atmosphere"] in f.exclude_gas:
            continue
        if a.get("analysis_mode") and a["analysis_mode"] in f.exclude_modes:
            continue
        if f.date_from is not None or f.date_to is not None:
            d = _row_date(a.get("test_date"))
            if d is not None:
                if f.date_from is not None and d < f.date_from:
                    continue
                if f.date_to is not None and d > f.date_to:      # the whole "to" day is included
                    continue
        out.append(a)
    return out


def distinct_values(rows: Iterable[Dict[str, Any]], field_name: str) -> List[str]:
    return sorted({r[field_name] for r in rows if r.get(field_name)})


def _all_period10(rows: Iterable[Dict[str, Any]]) -> List[int]:
    return [int(p) for p in (row_period10(r) for r in rows) if math.isfinite(p)]


def period_options(rows: Iterable[Dict[str, Any]], f: FilterState) -> List[int]:
    """allPeriods limited to the slider range (round10 values, numeric order)."""
    vals = set(_all_period10(rows))
    if f.period_range is not None:
        vals = {v for v in vals if f.period_range[0] <= v <= f.period_range[1]}
    return sorted(vals)


def period_domain(rows: Iterable[Dict[str, Any]]) -> Optional[Tuple[int, int]]:
    ps = _all_period10(rows)
    return (min(ps), max(ps)) if ps else None


def a1_domain(rows: Iterable[Dict[str, Any]]) -> Optional[Tuple[int, int]]:
    vs = [float(r["amplitude_a1"]) for r in rows
          if _is_num(r.get("amplitude_a1")) and math.isfinite(r["amplitude_a1"])]
    if not vs:
        return None
    return (int(js_floor(min(vs))), int(js_ceil(max(vs))))


def a1_step(lo: float, hi: float) -> float:
    span = hi - lo
    return 5 if span > 200 else 1 if span > 50 else 0.5 if span > 5 else 0.1


def _num_text(x: float) -> str:
    """A number as a JS template literal prints it."""
    from ctwa.analysis.jsmath import js_number_to_string
    return js_number_to_string(float(x))


def active_filters(f: FilterState, rows: Iterable[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """(label, key) per active filter, in the page's chip order."""
    rows = list(rows)
    out: List[Tuple[str, str]] = []
    if f.exclude_models:
        out.append(("Models −%d" % len(f.exclude_models), "models"))
    if f.exclude_source_devices:
        out.append(("Power Source Device −%d" % len(f.exclude_source_devices), "source"))
    if f.exclude_response_devices:
        out.append(("Power Response Device −%d" % len(f.exclude_response_devices), "response"))
    if f.exclude_gas:
        out.append(("Gas Atmosphere −%d" % len(f.exclude_gas), "gas"))
    if f.exclude_modes:
        out.append(("Analysis Mode −%d" % len(f.exclude_modes), "modes"))
    if f.exclude_periods:
        out.append(("Periods −%d" % len(f.exclude_periods), "periods"))
    pd = period_domain(rows)
    if pd is not None and f.period_range is not None and tuple(f.period_range) != pd:
        out.append(("%s–%s s" % (_num_text(f.period_range[0]), _num_text(f.period_range[1])), "period"))
    ad = a1_domain(rows)
    if ad is not None and f.a1_range is not None and tuple(f.a1_range) != ad:
        out.append(("A₁ %s–%s mW" % (_num_text(f.a1_range[0]), _num_text(f.a1_range[1])), "a1"))
    if f.row_kind != "originals":
        out.append(("Both" if f.row_kind == "all" else "Calibrated copies only", "row_kind"))
    if f.cal != "All":
        out.append(("Calibrated" if f.cal == "Calibrated" else "Uncalibrated", "cal"))
    if f.date_from or f.date_to:
        out.append(("%s → %s" % (f.date_from.isoformat() if f.date_from else "…",
                                 f.date_to.isoformat() if f.date_to else "…"), "dates"))
    return out


def clear_filter(f: FilterState, key: str) -> FilterState:
    g = f.copy()
    if key == "models":
        g.exclude_models = set()
    elif key == "source":
        g.exclude_source_devices = set()
    elif key == "response":
        g.exclude_response_devices = set()
    elif key == "gas":
        g.exclude_gas = set()
    elif key == "modes":
        g.exclude_modes = set()
    elif key == "periods":
        g.exclude_periods = set()
    elif key == "period":
        g.period_range = None
    elif key == "a1":
        g.a1_range = None
    elif key == "row_kind":
        g.row_kind = "originals"
    elif key == "cal":
        g.cal = "All"
    elif key == "dates":
        g.date_from = g.date_to = None
    else:
        raise KeyError(key)
    return g
