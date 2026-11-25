"""Statistics view state: QSettings round trip, garbage tolerance, sanitising against the loaded data."""
from __future__ import annotations

import json
import os
from datetime import date

import pytest
from PySide6.QtCore import QSettings

from ctwa.stats.filters import FilterState
from ctwa.stats.view_state import ALPHA_SERIES, ViewState, load_view, sanitize, save_view

FIX = os.path.join(os.path.dirname(__file__), "data", "stats_rows.json")
with open(FIX, encoding="utf-8") as _f:
    ROWS = json.load(_f)
PRESETS = [{"id": 1, "material_name": "Al", "temperature_c": 25, "alpha_mm2s": 64.0},
           {"id": 2, "material_name": "Abs", "temperature_c": 25, "alpha_mm2s": 0.08}]


@pytest.fixture
def settings(tmp_path):
    s = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    yield s
    s.sync()


def _reopen(settings):
    settings.sync()
    return QSettings(settings.fileName(), QSettings.IniFormat)


def _non_default() -> ViewState:
    f = FilterState(exclude_models={"Abs", "Al₂O₃"}, exclude_periods={75, 1200}, exclude_source_devices={"Keithley 2602B"},
                    exclude_response_devices={"C80"}, exclude_gas={"Ar"}, exclude_modes={"sine"}, row_kind="all",
                    cal="Calibrated", period_range=(100, 1200), a1_range=(1.5, 20.5),
                    date_from=date(2026, 1, 2), date_to=date(2026, 9, 30), hidden_ids={3, 4})
    return ViewState(chart_type="scatter", y_metric="raw_phase_phi", group_by="Period Band", x_axis="Frequency (Hz)",
                     color_by=None, log_x=True, log_y=True, period_log=False, show_mean=True, show_pairs=True,
                     period_source="resp", alpha_series=["phase_raw", "phase_cal", "combined_cal"],
                     lit_builder=["Al", "Abs"], lit_alpha=["Brass"], theory_ids=[2, 1], filters=f,
                     filters_collapsed=True, splitter=[300, 900])


def test_round_trip_non_default(settings):
    v = _non_default()
    save_view(settings, v)
    got = load_view(_reopen(settings))
    expected = _non_default()
    expected.filters.hidden_ids = set()          # session-only: never stored
    assert got == expected


def test_round_trip_color_by_set_and_empty(settings):
    v = ViewState(color_by="Temp Band")
    save_view(settings, v)
    assert load_view(_reopen(settings)).color_by == "Temp Band"
    save_view(settings, ViewState(color_by=None))
    s = _reopen(settings)
    assert s.value("statistics/colorBy") in ("", None)
    assert load_view(s).color_by is None


def test_defaults_from_empty_file_and_hidden_ids_not_written(settings):
    assert load_view(settings) == ViewState()
    v = ViewState()
    v.filters.hidden_ids = {1, 2}
    save_view(settings, v)
    keys = settings.allKeys()
    assert keys and all(k.startswith("statistics/") for k in keys)
    assert not any("hidden" in k.lower() or "select" in k.lower() for k in keys)
    assert load_view(_reopen(settings)).filters.hidden_ids == set()


def test_page_defaults():
    v = ViewState()
    assert (v.chart_type, v.y_metric, v.group_by, v.x_axis, v.color_by) == ("box", "alpha_combined_raw", "Model",
                                                                          "Period (s)", None)
    assert (v.log_x, v.log_y, v.period_log, v.show_mean, v.show_pairs, v.period_source) == (False, False, True, False,
                                                                                            False, "src")
    assert v.alpha_series == ["combined_raw"] and v.lit_builder == [] and v.theory_ids == []
    assert v.lit_alpha == ["Abs", "Al", "Brass", "Stainless Steel", "Al₂O₃"]
    assert ALPHA_SERIES == ("combined_raw", "phase_raw", "combined_cal", "phase_cal")


def test_garbage_falls_back_per_key_keeping_valid_ones(settings):
    v = _non_default()
    save_view(settings, v)
    settings.setValue("statistics/logX", "banana")
    settings.setValue("statistics/filter/excludeModels", "{not json")
    settings.setValue("statistics/filter/periodRange", "5")
    settings.setValue("statistics/chartType", "pie")
    settings.setValue("statistics/ui/splitter", "[1]")
    got = load_view(_reopen(settings))
    ref = _non_default()
    ref.filters.hidden_ids = set()
    assert got.log_x is False and got.chart_type == "box" and got.splitter is None
    assert got.filters.exclude_models == set() and got.filters.period_range is None
    # everything else survived
    ref.log_x, ref.chart_type, ref.splitter = False, "box", None
    ref.filters.exclude_models, ref.filters.period_range = set(), None
    assert got == ref


@pytest.mark.parametrize("key,value", [("statistics/filter/rowKind", "bogus"), ("statistics/filter/cal", 7),
                                       ("statistics/yMetric", "nope"), ("statistics/groupBy", ""),
                                       ("statistics/periodSource", "x"), ("statistics/filter/dateFrom", "2026-13-45"),
                                       ("statistics/filter/excludePeriods", '["a"]'), ("statistics/theoryIds", '{"a":1}'),
                                       ("statistics/alphaSeries", "null"), ("statistics/filter/a1Range", "9,1")])
def test_other_garbage_never_raises(settings, key, value):
    settings.setValue(key, value)
    assert load_view(_reopen(settings)) == ViewState()


def test_sanitize_ranges_against_domain():
    v = ViewState()
    v.filters.period_range = (3000, 4000)
    assert sanitize(v, ROWS, PRESETS).filters.period_range is None
    v.filters.period_range = (100, 5000)
    assert sanitize(v, ROWS, PRESETS).filters.period_range == (100, 2400)
    v.filters.period_range = (10, 500)           # the fixture's domain is (80, 2400): the low end clamps up
    assert sanitize(v, ROWS, PRESETS).filters.period_range == (80, 500)
    v.filters.a1_range = (50.0, 60.0)
    assert sanitize(v, ROWS, PRESETS).filters.a1_range is None


def test_sanitize_range_clamps_to_narrow_domain():
    rows = [r for r in ROWS if r["period_t"] in (75, 200, 300)]
    v = ViewState()
    v.filters.period_range = (2000, 3000)
    assert sanitize(v, rows, PRESETS).filters.period_range is None
    v.filters.period_range = (100, 5000)
    assert sanitize(v, rows, PRESETS).filters.period_range == (100, 300)


def test_sanitize_drops_unknown_values():
    v = ViewState(theory_ids=[1, 99])
    v.filters.exclude_models = {"Abs", "Ghost"}
    v.filters.exclude_periods = {80, 31337}
    v.filters.exclude_gas = {"Ar", "Neon"}
    v.filters.exclude_modes = {"sine", "wavelet"}
    out = sanitize(v, ROWS, PRESETS)
    assert out.filters.exclude_models == {"Abs"}
    assert out.filters.exclude_periods == {80}
    assert out.filters.exclude_gas == {"Ar"} and out.filters.exclude_modes == {"sine"}
    assert out.theory_ids == [1]
    assert v.filters.exclude_models == {"Abs", "Ghost"}          # the input is untouched


def test_sanitize_show_pairs_adds_phase_series_and_unknown_enums_reset():
    v = ViewState(show_pairs=True, alpha_series=["combined_raw"], y_metric="zzz", x_axis="?", group_by="?",
                  chart_type="pie", color_by="?")
    out = sanitize(v, ROWS, PRESETS)
    assert out.alpha_series == ["combined_raw", "phase_raw", "phase_cal"]
    assert (out.y_metric, out.x_axis, out.group_by, out.chart_type, out.color_by) == (
        "alpha_combined_raw", "Period (s)", "Model", "box", None)


def test_sanitize_keeps_saved_filters_while_nothing_is_loaded():
    v = ViewState(theory_ids=[5])
    v.filters.exclude_models = {"Abs"}
    v.filters.period_range = (100, 200)
    out = sanitize(v, [], [])
    assert out.filters.exclude_models == {"Abs"} and out.filters.period_range == (100, 200) and out.theory_ids == [5]
