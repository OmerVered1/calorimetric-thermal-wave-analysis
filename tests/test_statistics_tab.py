"""StatisticsTab: assembly, sections, summary, CSV, hide, open run (offscreen)."""
from __future__ import annotations

import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QObject, QSettings, Signal  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ctwa.stats.aggregate import summary_csv  # noqa: E402
from ctwa.stats.filters import FilterState, apply_filters  # noqa: E402
from ctwa.stats.model import prepare_rows  # noqa: E402
from ctwa.stats.view_state import ViewState, save_view  # noqa: E402
from ctwa.ui.statistics.tab import StatisticsTab  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "data", "stats_rows.json")
with open(FIX, encoding="utf-8") as _f:
    ROWS = json.load(_f)
PRESETS = [{"id": 1, "material_name": "Al", "temperature_c": 25, "alpha_mm2s": 64.0}]


class StubLoader(QObject):
    rows_changed = Signal(list)
    presets_changed = Signal(list)
    failed = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.refreshes = 0

    def refresh(self):
        self.refreshes += 1


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)


@pytest.fixture
def made(qapp, settings):
    tabs = []

    def make(rows=ROWS, presets=PRESETS, loader=None, **kw):
        t = StatisticsTab(loader or StubLoader(), settings, **kw)
        t.resize(1400, 900)
        tabs.append(t)
        if rows is not None:
            t.set_rows(rows, presets)
        return t

    yield make
    for t in tabs:
        t.close()
        t.deleteLater()
    qapp.processEvents()


def _ids(spec):
    out = set()
    for s in spec.series:
        out |= {i for i in s.ids if i is not None}
    return out


def _alpha_ids(tab):
    return _ids(tab.alpha_chart.spec())


def _shown(tab, name):
    return tab.sections[name].isVisibleTo(tab)


# ------------------------------------------------------------------ Review Focus 1

def test_first_open_shows_originals_only_and_both_shows_the_warning(made):
    tab = made()
    assert tab.count_label.text() == "17 / 18"
    assert 17 not in _alpha_ids(tab) and 16 in _alpha_ids(tab)
    assert tab.panel.row_warning.isHidden()
    tab.set_filters(FilterState(row_kind="all"))
    tab.flush()
    assert not tab.panel.row_warning.isHidden() and "counted twice" in tab.panel.row_warning.text()
    assert 17 in _alpha_ids(tab)
    assert tab.count_label.text() == "18 / 18"


# ------------------------------------------------------------------ Review Focus 2

def test_stale_saved_range_does_not_blank_the_charts(made, settings):
    v = ViewState()
    v.filters.period_range = (2500, 2600)
    v.filters.exclude_models = {"vanished"}
    v.filters.exclude_periods = {777}
    save_view(settings, v)
    tab = made()
    assert tab.alpha_chart.spec() is not None
    assert not tab.message.isVisibleTo(tab)
    assert [c for c in tab.panel.chips() if c[1] in ("period", "models", "periods")] == []
    assert tab.view().filters.period_range is None


def test_saved_narrow_range_is_clamped_when_rows_refresh(made):
    tab = made(rows=[r for r in ROWS if r["period_t"] >= 500])
    tab.set_filters(FilterState(period_range=(600, 2400)))
    tab.flush()
    assert tab.view().filters.period_range == (600, 2400)
    tab.set_rows([r for r in ROWS if r["period_t"] <= 300], PRESETS)       # domain is now 70..300
    assert tab.alpha_chart.spec() is not None
    assert tab.view().filters.period_range is None


# ------------------------------------------------------------------ Review Focus 5

def test_hidden_points_survive_a_refresh_and_selection_clears(made):
    tab = made()
    one, two, three = sorted(_alpha_ids(tab))[:3]
    tab.builder_chart.selection_made.emit([one, two])
    assert tab.selection_label.text() == "2 points selected"
    assert tab.selection_bar.isVisibleTo(tab)
    tab.hide_button.click()
    tab.flush()
    assert not ({one, two} & _alpha_ids(tab))
    assert tab.hidden_label.text() == "2 hidden"
    assert tab.view().filters.hidden_ids == {one, two}
    assert not tab.selection_bar.isVisibleTo(tab)
    tab.set_rows([r for r in ROWS if r["id"] != one], PRESETS)           # one of the hidden points is gone
    assert tab.hidden_label.text() == "1 hidden"
    assert two not in _alpha_ids(tab) and three in _alpha_ids(tab)
    tab.builder_chart.selection_made.emit([three])
    tab.set_rows(ROWS, PRESETS)                                          # a refresh clears the selection
    assert not tab.selection_bar.isVisibleTo(tab)
    assert tab.hidden_label.text() == "1 hidden" and one in _alpha_ids(tab)
    tab.show_hidden_button.click()
    tab.flush()
    assert {one, two} <= _alpha_ids(tab) and not tab.hidden_badge.isVisibleTo(tab)


def test_point_click_emits_open_analysis_and_is_harmless_unconnected(made):
    tab = made()
    tab.builder_chart.point_clicked.emit(7)              # nothing connected: no error
    got = []
    tab.open_analysis.connect(got.append)
    tab.builder_chart.point_clicked.emit(7)
    tab.alpha_chart.point_clicked.emit(8)
    tab.phase_charts[0].point_clicked.emit(9)
    assert got == [7, 8, 9]


def test_box_points_carry_no_id_and_emit_nothing(made):
    tab = made()
    got = []
    tab.open_analysis.connect(got.append)
    assert tab.view().chart_type == "box"
    assert tab.builder_chart.scatter_items() == []
    for chart in tab.heat_charts:
        assert chart.scatter_items() == []
    assert got == []


# ------------------------------------------------------------------ sections and empty states

def test_sections_follow_the_data(made):
    tab = made()
    assert all(_shown(tab, n) for n in ("builder", "alpha", "heat", "phase", "temp", "corr", "summary"))
    one_temp = [r for r in ROWS if r["temperature_c"] == 150]
    tab.set_rows(one_temp, PRESETS)
    assert not _shown(tab, "temp") and _shown(tab, "corr")
    tab.set_rows(ROWS[:2], PRESETS)
    assert not _shown(tab, "corr")                       # fewer than 3 rows pass the filters: no correlation section
    assert tab.corr_chart.spec() is None


def test_no_rows_and_no_match_messages(made):
    tab = made(rows=[])
    assert tab.message.text() == "No analyses found. Run some analyses first."
    assert not tab.csv_button.isVisibleTo(tab)
    tab.set_rows(ROWS, PRESETS)
    tab.set_filters(FilterState(exclude_models={"Abs", "Al₂O₃", "Stainless Steel", "unk foam"}))
    tab.flush()
    assert tab.message.text() == "No analyses match these filters."
    assert tab.reset_button.isVisibleTo(tab) and not tab.alpha_chart.isVisibleTo(tab)
    tab.reset_button.click()
    tab.flush()
    assert tab.alpha_chart.spec() is not None and not tab.message.isVisibleTo(tab)


def test_no_loader_says_not_available(qapp, settings):
    tab = StatisticsTab(None, settings)
    assert tab.message.text() == "Results are not available."
    assert not tab.csv_button.isVisibleTo(tab)
    tab.set_rows(ROWS, [])                                  # ignored
    assert tab.message.text() == "Results are not available."


def test_headings_and_hints_are_the_pages(made):
    tab = made()
    assert [tab.sections[n].title() for n in ("builder", "alpha", "heat", "phase", "temp", "corr", "summary")] == [
        "1. Chart Builder", "2. α vs Period — by Model", "3. Heat-Loss Indicators", "4. Phase Lag Analysis",
        "5. Temperature Dependence", "6. Correlation Matrix", "7. Summary Statistics by Model"]
    assert tab.sections["alpha"].hint() == "Ideal: α constant across periods. Drift indicates frequency-dependent artifacts."
    assert tab.sections["corr"].hint() == "Click a cell to plot that pair as a scatter in the chart builder."
    assert [b.text() for b in tab.link_buttons()] == [
        "Chart Builder", "α vs Period", "Heat-Loss Indicators", "Phase Lag Analysis", "Temperature Dependence",
        "Correlation Matrix", "Summary Statistics by Model"]


def test_section_link_scrolls(made):
    tab = made()
    tab.show()
    tab.resize(1400, 700)
    QApplication.processEvents()
    tab.scroll_to("summary")
    assert tab.scroll.verticalScrollBar().value() > 0
    tab.scroll_to("builder")
    assert tab.scroll.verticalScrollBar().value() == 0


# ------------------------------------------------------------------ summary + CSV

def test_summary_table_one_row_per_filtered_model(made):
    tab = made()
    texts = tab.summary.texts()
    assert [r[0] for r in texts] == ["Stainless Steel", "unk foam", "Abs", "Al₂O₃"]
    rows = apply_filters(prepare_rows(ROWS), FilterState())
    n_ss = len([r for r in rows if r["model_name"] == "Stainless Steel"])
    assert texts[0][1] == str(n_ss)
    assert tab.summary.columnCount() == 18


def test_csv_button_writes_the_summary_csv(made, tmp_path):
    out = tmp_path / "summary_statistics.csv"
    tab = made(save_path_provider=lambda: str(out))
    tab.csv_button.click()
    expected = summary_csv(apply_filters(prepare_rows(ROWS), FilterState()))
    assert out.read_text(encoding="utf-8") == expected
    tab2 = made(save_path_provider=lambda: "")
    tab2.csv_button.click()                                  # cancelled dialog: nothing happens


# ------------------------------------------------------------------ interactions

def test_corr_click_sets_the_builder(made):
    tab = made()
    tab.corr_chart.cell_clicked.emit("Δt", "φ")
    tab.flush()
    v = tab.view()
    assert (v.chart_type, v.y_metric, v.x_axis) == ("scatter", "raw_phase_phi", "Raw Δt (s)")
    assert tab.builder_chart.spec().kind == "xy"
    assert tab.controls.chart_combo.currentData() == "scatter"
    assert not tab.pair_message.isVisibleTo(tab)


def test_corr_click_without_axis_shows_message(made):
    tab = made()
    before = tab.view()
    tab.corr_chart.cell_clicked.emit("φ", "α comb raw")
    assert tab.pair_message.isVisibleTo(tab)
    assert tab.pair_message.text() == "The chart builder has no X axis for either of these two."
    assert tab.view() == before


def test_lasso_selection_fills_the_selection_bar_and_clear(made):
    tab = made()
    tab.alpha_chart.selection_made.emit([1, 2, 3])
    assert tab.selection_label.text() == "3 points selected"
    tab.clear_selection_button.click()
    assert not tab.selection_bar.isVisibleTo(tab)


# ------------------------------------------------------------------ persistence

def test_chart_type_is_restored_and_hidden_ids_are_not(made, settings):
    tab = made()
    tab.controls.chart_combo.setCurrentIndex(tab.controls.chart_combo.findData("scatter"))
    tab.builder_chart.selection_made.emit([3])
    tab.hide_button.click()
    tab.flush()
    settings.sync()
    again = StatisticsTab(StubLoader(), QSettings(settings.fileName(), QSettings.IniFormat))
    again.set_rows(ROWS, PRESETS)
    assert again.view().chart_type == "scatter"
    assert again.view().filters.hidden_ids == set()
    again.close()


def test_garbage_settings_open_with_defaults(made, settings):
    settings.setValue("statistics/chartType", 42)
    settings.setValue("statistics/filter/periodRange", "x,y")
    tab = made()
    assert tab.view().chart_type == "box"


# ------------------------------------------------------------------ loader wiring

def test_loader_signals_refresh_and_failure_strip(qapp, settings):
    loader = StubLoader()
    tab = StatisticsTab(loader, settings)
    tab.resize(1200, 800)
    assert loader.refreshes == 0
    tab.show()
    qapp.processEvents()
    assert loader.refreshes == 1
    tab.hide()
    tab.show()
    assert loader.refreshes == 1                              # only the first time
    loader.rows_changed.emit(ROWS)
    loader.presets_changed.emit(PRESETS)
    assert tab.alpha_chart.spec() is not None
    assert sorted(tab.controls.theory_chips) == [1]
    loader.failed.emit("offline", "No connection")
    assert tab.refresh_failed.isVisibleTo(tab) and "No connection" in tab.refresh_failed.text()
    assert tab.alpha_chart.spec() is not None               # the charts keep the last rows
    loader.rows_changed.emit(ROWS)
    assert not tab.refresh_failed.isVisibleTo(tab)
    tab.close()


# ------------------------------------------------------------------ budget and debounce

def _synthetic(n):
    out = []
    for i in range(n):
        r = dict(ROWS[i % len(ROWS)])
        r["id"] = 1000 + i
        r["calibrated_from_id"] = None
        k = 1 + (i % 7) * 0.03
        for key in ("alpha_combined_raw", "alpha_phase_raw", "alpha_combined_cal", "alpha_phase_cal", "raw_lag_dt",
                    "amplitude_a1", "amplitude_a2"):
            if r.get(key):
                r[key] = r[key] * k
        out.append(r)
    return out


def test_600_rows_build_every_spec_within_budget(made):
    rows = _synthetic(600)
    tab = made(rows=None)
    t0 = time.perf_counter()
    tab.set_rows(rows, PRESETS)
    full = time.perf_counter() - t0
    t0 = time.perf_counter()
    specs = tab.build_specs()
    specs_only = time.perf_counter() - t0
    assert specs_only < 1.0
    print("set_rows %.3f s, specs %.3f s" % (full, specs_only))
    assert full < 3.0
    assert specs["builder"] is not None and len(specs["heat"]) == 3 and specs["corr"] is not None


def test_rapid_changes_trigger_one_rebuild(made):
    tab = made()
    tab.flush()
    assert tab._timer.interval() == 150
    tab._timer.setInterval(60000)            # deterministic on a loaded machine: the timer cannot fire mid-burst
    n = tab.rebuild_count
    for _ in range(5):
        tab.controls.log_y_chip.click()
    assert tab._timer.isActive() and tab.rebuild_count == n          # nothing built yet
    tab.flush()
    assert tab.rebuild_count == n + 1
    assert tab.view().log_y is True
