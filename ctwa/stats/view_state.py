"""Statistics view state: chart-builder choices and filters, persisted in QSettings (replaces the page's URL / localStorage).

No Qt import: the functions only call ``settings.value(key)`` / ``settings.setValue(key, value)``.
``hidden_ids`` and the selection are session-only and never stored.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, replace
from datetime import date
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from ctwa.analysis.references import LIT_MATERIALS
from ctwa.stats.filters import (CAL_CHOICES, ROW_KINDS, FilterState, a1_domain, distinct_values, period_domain,
                                row_period10)
from ctwa.stats.model import GROUP_OPTIONS, PERIOD_SOURCES, X_AXES, Y_BY_KEY

if TYPE_CHECKING:   # pragma: no cover
    from PySide6.QtCore import QSettings

__all__ = ["ViewState", "ALPHA_SERIES", "CHART_TYPES", "save_view", "load_view", "sanitize"]

ALPHA_SERIES = ("combined_raw", "phase_raw", "combined_cal", "phase_cal")
CHART_TYPES = ("box", "violin", "bar", "scatter", "line")
_PREFIX = "statistics/"


@dataclass
class ViewState:
    chart_type: str = "box"
    y_metric: str = "alpha_combined_raw"
    group_by: str = "Model"
    x_axis: str = "Period (s)"
    color_by: Optional[str] = None
    log_x: bool = False
    log_y: bool = False
    period_log: bool = True
    show_mean: bool = False
    show_pairs: bool = False
    period_source: str = "src"
    alpha_series: List[str] = field(default_factory=lambda: ["combined_raw"])
    lit_builder: List[str] = field(default_factory=list)
    lit_alpha: List[str] = field(default_factory=lambda: list(LIT_MATERIALS))
    theory_ids: List[int] = field(default_factory=list)
    filters: FilterState = field(default_factory=FilterState)
    # UI layout (stored with the view)
    filters_collapsed: bool = False
    splitter: Optional[List[int]] = None


# ---------------------------------------------------------------- parsing helpers (every one falls back to default)

def _bool(raw: Any, default: bool) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        s = raw.strip().lower()
        if s in ("true", "1"):
            return True
        if s in ("false", "0"):
            return False
    return default


def _choice(raw: Any, allowed: Sequence[str], default: Any) -> Any:
    return raw if isinstance(raw, str) and raw in allowed else default


def _json(raw: Any) -> Any:
    if not isinstance(raw, str):
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _str_list(raw: Any, default: List[str]) -> List[str]:
    v = _json(raw)
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        return list(v)
    return list(default)


def _int_list(raw: Any, default: List[int]) -> List[int]:
    v = _json(raw)
    if isinstance(v, list) and all(isinstance(x, int) and not isinstance(x, bool) for x in v):
        return list(v)
    return list(default)


def _range(raw: Any, as_int: bool) -> Optional[Tuple[Any, Any]]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    parts = raw.split(",")
    if len(parts) != 2:
        return None
    try:
        lo, hi = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    if not (math.isfinite(lo) and math.isfinite(hi)) or lo > hi:
        return None
    return (int(lo), int(hi)) if as_int else (lo, hi)


def _date(raw: Any) -> Optional[date]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        return None


def _splitter(raw: Any) -> Optional[List[int]]:
    v = _json(raw)
    if isinstance(v, list) and len(v) == 2 and all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in v):
        return list(v)
    return None


def _get(settings: "QSettings", key: str) -> Any:
    try:
        return settings.value(_PREFIX + key)
    except Exception:   # a broken settings backend must not stop the tab
        return None


def _put(settings: "QSettings", key: str, value: Any) -> None:
    settings.setValue(_PREFIX + key, value)


def _dump(v: Iterable[Any]) -> str:
    return json.dumps(sorted(v) if isinstance(v, (set, frozenset)) else list(v), ensure_ascii=False)


def _range_text(r: Optional[Tuple[Any, Any]]) -> str:
    return "" if r is None else "%s,%s" % (r[0], r[1])


# ---------------------------------------------------------------- save / load

def save_view(settings: "QSettings", v: ViewState) -> None:
    f = v.filters
    _put(settings, "chartType", v.chart_type)
    _put(settings, "yMetric", v.y_metric)
    _put(settings, "groupBy", v.group_by)
    _put(settings, "xAxis", v.x_axis)
    _put(settings, "colorBy", v.color_by or "")
    _put(settings, "logX", bool(v.log_x))
    _put(settings, "logY", bool(v.log_y))
    _put(settings, "periodLog", bool(v.period_log))
    _put(settings, "showMean", bool(v.show_mean))
    _put(settings, "showPairs", bool(v.show_pairs))
    _put(settings, "periodSource", v.period_source)
    _put(settings, "alphaSeries", _dump(v.alpha_series))
    _put(settings, "litBuilder", _dump(v.lit_builder))
    _put(settings, "litAlpha", _dump(v.lit_alpha))
    _put(settings, "theoryIds", _dump(v.theory_ids))
    _put(settings, "filter/excludeModels", _dump(f.exclude_models))
    _put(settings, "filter/excludePeriods", _dump(f.exclude_periods))
    _put(settings, "filter/excludeSources", _dump(f.exclude_source_devices))
    _put(settings, "filter/excludeResponses", _dump(f.exclude_response_devices))
    _put(settings, "filter/excludeGas", _dump(f.exclude_gas))
    _put(settings, "filter/excludeModes", _dump(f.exclude_modes))
    _put(settings, "filter/rowKind", f.row_kind)
    _put(settings, "filter/cal", f.cal)
    _put(settings, "filter/periodRange", _range_text(f.period_range))
    _put(settings, "filter/a1Range", _range_text(f.a1_range))
    _put(settings, "filter/dateFrom", f.date_from.isoformat() if f.date_from else "")
    _put(settings, "filter/dateTo", f.date_to.isoformat() if f.date_to else "")
    _put(settings, "ui/filtersCollapsed", bool(v.filters_collapsed))
    _put(settings, "ui/splitter", json.dumps(v.splitter) if v.splitter else "")


def load_view(settings: "QSettings") -> ViewState:
    d = ViewState()
    f = FilterState(
        exclude_models=set(_str_list(_get(settings, "filter/excludeModels"), [])),
        exclude_periods=set(_int_list(_get(settings, "filter/excludePeriods"), [])),
        exclude_source_devices=set(_str_list(_get(settings, "filter/excludeSources"), [])),
        exclude_response_devices=set(_str_list(_get(settings, "filter/excludeResponses"), [])),
        exclude_gas=set(_str_list(_get(settings, "filter/excludeGas"), [])),
        exclude_modes=set(_str_list(_get(settings, "filter/excludeModes"), [])),
        row_kind=_choice(_get(settings, "filter/rowKind"), ROW_KINDS, d.filters.row_kind),
        cal=_choice(_get(settings, "filter/cal"), CAL_CHOICES, d.filters.cal),
        period_range=_range(_get(settings, "filter/periodRange"), True),
        a1_range=_range(_get(settings, "filter/a1Range"), False),
        date_from=_date(_get(settings, "filter/dateFrom")),
        date_to=_date(_get(settings, "filter/dateTo")),
    )
    series = [s for s in _str_list(_get(settings, "alphaSeries"), d.alpha_series) if s in ALPHA_SERIES]
    return ViewState(
        chart_type=_choice(_get(settings, "chartType"), CHART_TYPES, d.chart_type),
        y_metric=_choice(_get(settings, "yMetric"), list(Y_BY_KEY), d.y_metric),
        group_by=_choice(_get(settings, "groupBy"), GROUP_OPTIONS, d.group_by),
        x_axis=_choice(_get(settings, "xAxis"), X_AXES, d.x_axis),
        color_by=_choice(_get(settings, "colorBy"), GROUP_OPTIONS, None),
        log_x=_bool(_get(settings, "logX"), d.log_x),
        log_y=_bool(_get(settings, "logY"), d.log_y),
        period_log=_bool(_get(settings, "periodLog"), d.period_log),
        show_mean=_bool(_get(settings, "showMean"), d.show_mean),
        show_pairs=_bool(_get(settings, "showPairs"), d.show_pairs),
        period_source=_choice(_get(settings, "periodSource"), PERIOD_SOURCES, d.period_source),
        alpha_series=series,
        lit_builder=[s for s in _str_list(_get(settings, "litBuilder"), d.lit_builder) if s in LIT_MATERIALS],
        lit_alpha=[s for s in _str_list(_get(settings, "litAlpha"), d.lit_alpha) if s in LIT_MATERIALS],
        theory_ids=_int_list(_get(settings, "theoryIds"), d.theory_ids),
        filters=f,
        filters_collapsed=_bool(_get(settings, "ui/filtersCollapsed"), d.filters_collapsed),
        splitter=_splitter(_get(settings, "ui/splitter")),
    )


# ---------------------------------------------------------------- sanitize against the loaded data

def _clamp(r: Optional[Tuple[Any, Any]], domain: Optional[Tuple[Any, Any]]) -> Optional[Tuple[Any, Any]]:
    if r is None or domain is None:
        return r
    lo, hi = max(r[0], domain[0]), min(r[1], domain[1])
    return (lo, hi) if lo <= hi else None


def sanitize(v: ViewState, rows: Sequence[Dict[str, Any]], presets: Sequence[Dict[str, Any]]) -> ViewState:
    """A copy of ``v`` that fits the current data (stale saved filters must not blank the charts silently).

    Row-dependent trimming is skipped while ``rows`` is empty and preset trimming while ``presets`` is empty
    (nothing loaded yet: do not throw the saved choices away)."""
    out = replace(v, filters=v.filters.copy(), alpha_series=list(v.alpha_series), lit_builder=list(v.lit_builder),
                  lit_alpha=list(v.lit_alpha), theory_ids=list(v.theory_ids))
    d = ViewState()
    out.chart_type = _choice(out.chart_type, CHART_TYPES, d.chart_type)
    out.y_metric = _choice(out.y_metric, list(Y_BY_KEY), d.y_metric)
    out.x_axis = _choice(out.x_axis, X_AXES, d.x_axis)
    out.group_by = _choice(out.group_by, GROUP_OPTIONS, d.group_by)
    out.color_by = _choice(out.color_by, GROUP_OPTIONS, None)
    out.period_source = _choice(out.period_source, PERIOD_SOURCES, d.period_source)
    out.alpha_series = [s for s in out.alpha_series if s in ALPHA_SERIES]
    if out.show_pairs:
        for s in ("phase_raw", "phase_cal"):
            if s not in out.alpha_series:
                out.alpha_series.append(s)
    f = out.filters
    if rows:
        f.exclude_models &= set(distinct_values(rows, "model_name"))
        f.exclude_source_devices &= set(distinct_values(rows, "power_source_device"))
        f.exclude_response_devices &= set(distinct_values(rows, "power_response_device"))
        f.exclude_gas &= set(distinct_values(rows, "gas_atmosphere"))
        f.exclude_modes &= set(distinct_values(rows, "analysis_mode"))
        present: Set[int] = set()
        for r in rows:
            p = row_period10(r)
            if math.isfinite(p):
                present.add(int(p))
        f.exclude_periods &= present
        f.period_range = _clamp(f.period_range, period_domain(rows))
        f.a1_range = _clamp(f.a1_range, a1_domain(rows))
    if presets:
        known = {p.get("id") for p in presets}
        out.theory_ids = [i for i in out.theory_ids if i in known]
    return out
