"""Statistics filters; expected id lists pinned from the page's own filter block (node, page.tsx verbatim)."""
from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import date

from ctwa.stats import filters as F

FIX = os.path.join(os.path.dirname(__file__), "data", "stats_rows.json")
with open(FIX, encoding="utf-8") as _f:
    ROWS = json.load(_f)

PIN_COMBOS = [{'f': {}, 'ids': [18, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]},
 {'f': {'rowKind': 'calibratedCopies'}, 'ids': [17]},
 {'f': {'rowKind': 'all'}, 'ids': [18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]},
 {'f': {'rowKind': 'all', 'xm': ['Abs', 'unk foam'], 'xp': ['260 s', '1200 s'], 'cal': 'Uncalibrated'},
  'ids': [16, 7, 5, 2, 1]},
 {'f': {'p': [250, 260], 'rowKind': 'all'}, 'ids': [17, 16, 15]},
 {'f': {'a1': [10, 21],
        'from': '2026-08-31',
        'to': '2026-09-05',
        'xg': ['Air'],
        'xs': ['Keithley 2450'],
        'xmode': ['sine']},
  'ids': [14, 13, 7]},
 {'f': {'from': '2026-09-01'}, 'ids': [18, 16, 14, 13, 12, 11, 10, 8, 7, 6, 4, 3, 2]},
 {'f': {'to': '2026-09-30'}, 'ids': [18, 16, 15, 14, 13, 12, 11, 10, 9, 7, 6, 5, 4, 3, 2, 1]},
 {'f': {'hidden': [18, 16], 'cal': 'Calibrated', 'rowKind': 'all'}, 'ids': [17, 10]},
 {'f': {'xs': ['Keithley 2602B'], 'xr': ['C80'], 'rowKind': 'all'}, 'ids': []}]
PIN_FROM = [18, 16, 14, 13, 12, 11, 10, 8, 7, 6, 4, 3, 2]
PIN_TO = [18, 16, 15, 14, 13, 12, 11, 10, 9, 7, 6, 5, 4, 3, 2, 1]
PIN_NAN = {'from': [901], 'to': [901, 902]}
PIN_PERIOD_DOMAIN = [80, 2400]
PIN_A1_DOMAIN = [5, 30]
PIN_ALL_PERIODS = ['80 s', '200 s', '250 s', '260 s', '300 s', '400 s', '520 s', '600 s', '700 s', '1200 s', '2400 s']


def _state(spec):
    """The webapp's filter variables (spec keys of the pin script) as a FilterState."""
    f = F.FilterState()
    f.exclude_models = set(spec.get("xm", []))
    f.exclude_periods = {int(p.split()[0]) for p in spec.get("xp", [])}
    f.exclude_source_devices = set(spec.get("xs", []))
    f.exclude_response_devices = set(spec.get("xr", []))
    f.exclude_gas = set(spec.get("xg", []))
    f.exclude_modes = set(spec.get("xmode", []))
    f.row_kind = {"calibratedCopies": "copies"}.get(spec.get("rowKind", "originals"), spec.get("rowKind", "originals"))
    f.cal = spec.get("cal", "All")
    f.period_range = tuple(spec["p"]) if "p" in spec else None
    f.a1_range = tuple(spec["a1"]) if "a1" in spec else None
    f.date_from = date.fromisoformat(spec["from"]) if "from" in spec else None
    f.date_to = date.fromisoformat(spec["to"]) if "to" in spec else None
    f.hidden_ids = set(spec.get("hidden", []))
    return f


def _ids(rows):
    return [r["id"] for r in rows]


def test_ten_pinned_combos():
    for c in PIN_COMBOS:
        assert _ids(F.apply_filters(ROWS, _state(c["f"]))) == c["ids"], c["f"]


def test_defaults_show_originals_only_and_kinds():
    """Review focus 1: calibrated copies are not double-counted by default."""
    f = F.FilterState()
    assert f.row_kind == "originals" and f.cal == "All"
    assert 17 not in _ids(F.apply_filters(ROWS, f))
    assert _ids(F.apply_filters(ROWS, replace(f, row_kind="copies"))) == [17]
    assert len(F.apply_filters(ROWS, replace(f, row_kind="all"))) == 18


def test_null_field_never_excluded_by_that_field():
    f = F.FilterState(row_kind="all", exclude_gas={"Ar", "Air"}, exclude_source_devices={"Keithley 2602B", "Keithley 2450"},
                      exclude_response_devices={"C80"}, exclude_modes={"peak", "sine"})
    ids = _ids(F.apply_filters(ROWS, f))
    # row 14 has no gas and no source device but a C80 response device; row 12 has no response device
    assert 14 not in ids            # (excluded through its response device / mode, not through the null fields)
    g = F.FilterState(row_kind="all", exclude_gas={"Ar", "Air"})
    assert 14 in _ids(F.apply_filters(ROWS, g))       # gas None survives a gas exclusion
    h = F.FilterState(row_kind="all", exclude_source_devices={"Keithley 2602B"})
    assert 14 in _ids(F.apply_filters(ROWS, h))       # source None survives
    k = F.FilterState(row_kind="all", exclude_response_devices={"C80"})
    assert 12 in _ids(F.apply_filters(ROWS, k))       # response None survives
    m = F.FilterState(row_kind="all", exclude_modes={"peak", "sine"})
    assert F.apply_filters([dict(ROWS[0], analysis_mode=None)], m)   # mode None survives


def test_period_range_uses_round10_of_source_period_inclusive():
    f = F.FilterState(row_kind="all", period_range=(250, 260))
    assert set(_ids(F.apply_filters(ROWS, f))) == {15, 16, 17}      # 254.99 -> 250, 255 -> 260
    assert 14 not in set(_ids(F.apply_filters(ROWS, f)))            # 199.9 -> 200
    # the view's period source is irrelevant here: even with period_t_resp null the source period decides
    assert 7 in _ids(F.apply_filters(ROWS, F.FilterState(period_range=(600, 600))))
    # null period_t counts as 0 (JS Math.round(null/10)*10)
    nul = dict(ROWS[0], id=900, period_t=None)
    assert F.apply_filters([nul], F.FilterState(period_range=(10, 100))) == []
    assert F.apply_filters([nul], F.FilterState(period_range=(0, 100))) == [nul]
    assert F.apply_filters([nul], F.FilterState(exclude_periods={0})) == []
    # excluded periods compare the same round10 value
    assert 15 not in _ids(F.apply_filters(ROWS, F.FilterState(exclude_periods={260})))
    assert 16 in _ids(F.apply_filters(ROWS, F.FilterState(exclude_periods={260})))


def test_dates_whole_end_day_and_epoch():
    assert _ids(F.apply_filters(ROWS, F.FilterState(date_from=date(2026, 9, 1)))) == PIN_FROM
    assert _ids(F.apply_filters(ROWS, F.FilterState(date_to=date(2026, 9, 30)))) == PIN_TO
    day = F.FilterState(date_from=date(2026, 9, 1), date_to=date(2026, 9, 1))
    assert set(_ids(F.apply_filters(ROWS, day))) >= {18, 16, 14, 12, 11, 10, 7, 6, 4, 3}
    assert 13 not in _ids(F.apply_filters(ROWS, day))              # 05/09/2026
    # the "garbage" date is the 1970 epoch: dropped by any date_from, kept by date_to only
    assert 5 not in _ids(F.apply_filters(ROWS, F.FilterState(date_from=date(1971, 1, 1))))
    assert 5 in _ids(F.apply_filters(ROWS, F.FilterState(date_to=date(1971, 1, 1))))
    assert _ids(F.apply_filters(ROWS, F.FilterState(date_to=date(1971, 1, 1)))) == [5]


def test_three_non_numeric_date_parts_are_invalid_date_that_passes():
    """'x/y/z' is an Invalid Date in JS: NaN comparisons are false, so neither bound excludes it."""
    rows = [dict(ROWS[0], id=901, test_date="x/y/z"), dict(ROWS[0], id=902, test_date="garbage")]
    assert _ids(F.apply_filters(rows, F.FilterState(date_from=date(2026, 1, 1)))) == PIN_NAN["from"]
    assert _ids(F.apply_filters(rows, F.FilterState(date_to=date(2026, 1, 1)))) == PIN_NAN["to"]


def test_a1_range_null_passes_and_inclusive():
    nul = dict(ROWS[0], id=903, amplitude_a1=None)
    assert F.apply_filters([nul], F.FilterState(a1_range=(1000, 2000))) == [nul]
    assert _ids(F.apply_filters(ROWS, F.FilterState(a1_range=(20, 20.5)))) == [18, 16]
    assert F.apply_filters([dict(ROWS[0], amplitude_a1=20.0)], F.FilterState(a1_range=(20, 20)))


def test_hidden_ids_removed_and_order_kept():
    f = F.FilterState(hidden_ids={18, 14, 999})
    ids = _ids(F.apply_filters(ROWS, f))
    assert 18 not in ids and 14 not in ids
    assert ids == [i for i in [18, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1] if i not in (18, 14)]


def test_domains_steps_options():
    assert F.period_domain(ROWS) == tuple(PIN_PERIOD_DOMAIN)
    assert F.a1_domain(ROWS) == tuple(PIN_A1_DOMAIN)
    assert F.period_domain([]) is None and F.a1_domain([]) is None
    assert F.a1_step(0, 100) == 1 and F.a1_step(0, 300) == 5 and F.a1_step(0, 20) == 0.5 and F.a1_step(0, 2) == 0.1
    assert F.a1_step(0, 200) == 1 and F.a1_step(0, 50) == 0.5 and F.a1_step(0, 5) == 0.1   # strict ">"
    assert [str(p) + " s" for p in F.period_options(ROWS, F.FilterState())] == PIN_ALL_PERIODS
    assert F.period_options(ROWS, F.FilterState(period_range=(250, 600))) == [250, 260, 300, 400, 520, 600]
    assert F.distinct_values(ROWS, "gas_atmosphere") == ["Air", "Ar"]
    assert F.distinct_values(ROWS, "power_source_device") == ["Keithley 2602B"]
    assert F.distinct_values(ROWS, "analysis_mode") == ["peak", "sine"]


def test_active_filters_and_clear():
    f = F.FilterState(exclude_models={"Abs", "unk foam"}, period_range=(100, 1000))
    assert F.active_filters(f, ROWS) == [("Models −2", "models"), ("100–1000 s", "period")]
    g = F.clear_filter(f, "models")
    assert F.active_filters(g, ROWS) == [("100–1000 s", "period")]
    assert f.exclude_models == {"Abs", "unk foam"}                   # input untouched
    assert F.clear_filter(f, "period").period_range is None
    full = F.FilterState(period_range=F.period_domain(ROWS), a1_range=F.a1_domain(ROWS))
    assert F.active_filters(full, ROWS) == []                         # the whole domain is not a filter
    many = F.FilterState(exclude_periods={80}, a1_range=(6, 25), row_kind="copies", cal="Calibrated",
                         date_from=date(2026, 1, 2))
    assert F.active_filters(many, ROWS) == [("Periods −1", "periods"), ("A₁ 6–25 mW", "a1"),
                                            ("Calibrated copies only", "row_kind"), ("Calibrated", "cal"),
                                            ("2026-01-02 → …", "dates")]
    assert F.active_filters(F.FilterState(row_kind="all", cal="Uncalibrated"), ROWS) == [("Both", "row_kind"), ("Uncalibrated", "cal")]


def test_reset_keep_hidden_and_copy_independent():
    f = F.FilterState(exclude_models={"Abs"}, hidden_ids={3, 4}, row_kind="all", period_range=(1, 2))
    r = f.reset_keep_hidden()
    assert r.hidden_ids == {3, 4} and r.exclude_models == set() and r.row_kind == "originals" and r.period_range is None
    c = f.copy()
    c.exclude_models.add("X"); c.hidden_ids.add(9)
    assert f.exclude_models == {"Abs"} and f.hidden_ids == {3, 4}
