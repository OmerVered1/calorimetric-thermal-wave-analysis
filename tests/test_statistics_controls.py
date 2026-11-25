"""Statistics filter panel and chart controls (offscreen)."""
from __future__ import annotations

import json
import os
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ctwa.stats.filters import FilterState, active_filters, period_domain  # noqa: E402
from ctwa.stats.model import prepare_rows  # noqa: E402
from ctwa.stats.specs import TheoryInfo  # noqa: E402
from ctwa.stats.view_state import ViewState  # noqa: E402
from ctwa.ui.statistics.controls import ChartControls  # noqa: E402
from ctwa.ui.statistics.filter_panel import FilterPanel  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "data", "stats_rows.json")
with open(FIX, encoding="utf-8") as _f:
    ROWS = prepare_rows(json.load(_f))
PRESETS = [{"id": 1, "material_name": "Al", "temperature_c": 25, "alpha_mm2s": 64.0},
           {"id": 2, "material_name": "Abs", "temperature_c": 150, "alpha_mm2s": 0.08}]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(qapp):
    p = FilterPanel()
    p.resize(320, 900)
    p.set_rows(ROWS)
    p.show()
    yield p
    p.close()
    p.deleteLater()
    qapp.processEvents()


def _spy(sig):
    hits = []
    sig.connect(lambda *a: hits.append(a))
    return hits


def _item(lst, text):
    for i in range(lst.count()):
        if lst.item(i).text() == text:
            return lst.item(i)
    raise KeyError(text)


# ------------------------------------------------------------------ FilterPanel

def test_defaults_include_everything(panel):
    assert panel.state() == FilterState()
    assert [panel.model_list.item(i).text() for i in range(panel.model_list.count())] == [
        "Abs", "Al₂O₃", "Stainless Steel", "unk foam"]
    assert all(panel.model_list.item(i).checkState().value == 2 for i in range(panel.model_list.count()))


def test_unchecking_a_model_and_a_period_updates_state_and_emits_once_each(panel):
    from PySide6.QtCore import Qt
    hits = _spy(panel.changed)
    _item(panel.model_list, "Abs").setCheckState(Qt.Unchecked)
    assert len(hits) == 1
    _item(panel.period_list, "1200 s").setCheckState(Qt.Unchecked)
    assert len(hits) == 2
    assert panel.state() == FilterState(exclude_models={"Abs"}, exclude_periods={1200})


def test_set_state_round_trips_without_emitting(panel):
    hits = _spy(panel.changed)
    st = FilterState(exclude_models={"unk foam"}, exclude_periods={75}, exclude_gas={"Air"}, exclude_modes={"sine"},
                     exclude_source_devices={"Keithley 2602B"}, exclude_response_devices={"C80"},
                     row_kind="copies", cal="Calibrated", period_range=(100, 1200), a1_range=(5.0, 20.0),
                     date_from=date(2026, 1, 2), date_to=date(2026, 9, 30), hidden_ids={3, 4})
    panel.set_state(st)
    assert panel.state() == st
    assert hits == []
    assert panel.rows_combo.currentText() == "Calibrated copies only"
    assert panel.cal_combo.currentText() == "Calibrated"
    assert panel.date_from.date().toPython() == date(2026, 1, 2)


def test_row_kind_warning_only_for_both(panel):
    assert panel.row_warning.isHidden()
    assert not panel.row_hint.isHidden()
    panel.rows_combo.setCurrentIndex(panel.rows_combo.findData("all"))
    assert not panel.row_warning.isHidden()
    assert "counted twice" in panel.row_warning.text()
    panel.rows_combo.setCurrentIndex(panel.rows_combo.findData("copies"))
    assert panel.row_warning.isHidden()
    assert panel.state().row_kind == "copies"
    assert panel.row_hint.text().startswith("A calibrated run is saved as a copy")


def test_period_list_follows_the_slider_range(panel):
    panel.period_lo.setValue(300)
    panel.period_hi.setValue(1200)
    texts = [panel.period_list.item(i).text() for i in range(panel.period_list.count())]
    assert texts == ["300 s", "400 s", "520 s", "600 s", "700 s", "1200 s"]
    assert panel.state().period_range == (300, 1200)
    panel.set_state(FilterState(period_range=(2500, 2600)))
    assert panel.period_list.count() == 0
    assert not panel.period_empty.isHidden() and panel.period_empty.text() == "No periods in range"


def test_range_chip_and_its_clear_button(panel):
    hits = _spy(panel.changed)
    panel.period_lo.setValue(300)
    labels = [c[0] for c in panel.chips()]
    assert labels == ["300–2400 s"]
    panel.chips()[0][2].click()
    assert panel.chips() == []
    assert panel.state().period_range is None
    assert panel.period_lo.value() == period_domain(ROWS)[0]
    assert len(hits) == 2


def test_range_equal_to_domain_is_stored_as_none(panel):
    panel.period_lo.setValue(500)
    panel.period_lo.setValue(period_domain(ROWS)[0])
    assert panel.state().period_range is None


def test_reset_all_keeps_hidden_ids(panel):
    panel.set_state(FilterState(exclude_models={"Abs"}, row_kind="all", cal="Uncalibrated", hidden_ids={5, 6}))
    hits = _spy(panel.changed)
    assert panel.reset_button.isEnabled()
    panel.reset_button.click()
    assert panel.state() == FilterState(hidden_ids={5, 6})
    assert len(hits) == 1
    assert not panel.reset_button.isEnabled()


def test_chips_match_active_filters(panel):
    st = FilterState(exclude_models={"Abs"}, row_kind="all", cal="Calibrated", date_from=date(2026, 1, 1))
    panel.set_state(st)
    assert [c[0] for c in panel.chips()] == [a[0] for a in active_filters(st, ROWS)]
    assert panel.chip_count_label.text() == "4"


def test_date_limit_checkboxes(panel):
    assert panel.state().date_from is None and panel.state().date_to is None
    panel.date_from_free.setChecked(False)
    panel.date_from.setDate(panel.date_from.date().fromString("2026-03-04", "yyyy-MM-dd"))
    assert panel.state().date_from == date(2026, 3, 4)
    panel.date_from_free.setChecked(True)
    assert panel.state().date_from is None


def test_set_rows_rebuilds_options_and_keeps_state(panel):
    panel.set_state(FilterState(exclude_models={"Abs"}))
    hits = _spy(panel.changed)
    panel.set_rows([r for r in ROWS if r["model_name"] != "Al₂O₃"])
    assert [panel.model_list.item(i).text() for i in range(panel.model_list.count())] == [
        "Abs", "Stainless Steel", "unk foam"]
    assert panel.state().exclude_models == {"Abs"}
    assert hits == []


def test_a1_range_step_from_data(panel):
    # fixture A1 spans 5..30: a1_step -> 0.5 (span 25 > 5)
    assert panel.a1_lo.singleStep() == 0.5
    panel.a1_lo.setValue(10.0)
    assert panel.state().a1_range == (10.0, 30)


# ------------------------------------------------------------------ ChartControls

@pytest.fixture
def controls(qapp):
    c = ChartControls()
    c.set_presets(PRESETS)
    c.show()
    yield c
    c.close()
    c.deleteLater()
    qapp.processEvents()


def _shown(controls, *ws):
    return [w.isVisibleTo(controls) for w in ws]


def test_group_by_only_for_distribution_charts(controls):
    for kind in ("box", "violin", "bar"):
        controls.set_view(ViewState(chart_type=kind))
        assert _shown(controls, controls.group_combo, controls.x_combo, controls.color_combo) == [True, False, False]
    for kind in ("scatter", "line"):
        controls.set_view(ViewState(chart_type=kind))
        assert _shown(controls, controls.group_combo, controls.x_combo, controls.color_combo) == [False, True, True]


def test_changing_the_chart_type_combo_switches_the_visible_controls(controls):
    hits = _spy(controls.changed)
    controls.chart_combo.setCurrentIndex(controls.chart_combo.findData("scatter"))
    assert _shown(controls, controls.group_combo, controls.x_combo) == [False, True]
    assert len(hits) == 1


def test_option_texts(controls):
    assert [controls.chart_combo.itemText(i) for i in range(controls.chart_combo.count())] == [
        "Box", "Violin", "Bar (mean ± std)", "Scatter", "Line"]
    assert controls.color_combo.itemText(0) == "None"
    assert controls.y_combo.itemText(0) == "α Combined (raw) mm²/s"
    assert controls.period_source_texts() == ["Source", "Response"]


def test_raw_cal_pairs_on_adds_both_phase_series(controls):
    controls.set_view(ViewState(alpha_series=["combined_raw"]))
    controls.pairs_chip.click()
    v = controls.apply_to(ViewState())
    assert v.show_pairs is True
    assert v.alpha_series == ["combined_raw", "phase_raw", "phase_cal"]
    assert controls.series_chips["phase_raw"].isChecked() and controls.series_chips["phase_cal"].isChecked()


def test_apply_to_after_set_view_round_trips(controls):
    v = ViewState(chart_type="scatter", y_metric="raw_phase_phi", group_by="Period Band", x_axis="Frequency (Hz)",
                  color_by="Model", log_x=True, log_y=True, period_log=False, show_mean=True, show_pairs=True,
                  period_source="resp", alpha_series=["phase_raw", "phase_cal", "combined_cal"],
                  lit_builder=["Copper"], lit_alpha=[], theory_ids=[2])
    controls.set_view(v)
    assert controls.apply_to(ViewState()) == v
    other = ViewState(filters=FilterState(exclude_models={"x"}), filters_collapsed=True, splitter=[1, 2])
    out = controls.apply_to(other)
    assert out.filters == other.filters and out.filters_collapsed and out.splitter == [1, 2]


def test_set_view_does_not_emit(controls):
    hits = _spy(controls.changed)
    controls.set_view(ViewState(chart_type="line", log_x=True, theory_ids=[1]))
    assert hits == []


def test_chips_emit_and_update_view(controls):
    hits = _spy(controls.changed)
    controls.log_x_chip.click()
    controls.mean_chip.click()
    controls.period_log_chip.click()
    assert len(hits) == 3
    v = controls.apply_to(ViewState())
    assert v.log_x and v.show_mean and v.period_log is False
    assert controls.phase_period_log_chip.isChecked() is False         # the section-4 chip mirrors it


def test_hints_follow_the_chips(controls):
    assert controls.alpha_hint.isHidden()
    controls.mean_chip.click()
    assert "periods within 4 %" in controls.alpha_hint.text()
    controls.pairs_chip.click()
    assert "Hollow markers are raw" in controls.alpha_hint.text()


def test_literature_and_theory_chips(controls):
    assert sorted(controls.theory_chips) == [1, 2]
    assert controls.theory_chips[1].text() == "Al 25°C (α=64)"
    assert controls.theory_chips[2].text() == "Abs 150°C (α=0.08)"
    controls.theory_chips[2].click()
    controls.lit_builder_chips[next(iter(controls.lit_builder_chips))].click()
    v = controls.apply_to(ViewState())
    assert v.theory_ids == [2] and len(v.lit_builder) == 1


def test_theory_messages(controls):
    controls.set_view(ViewState(y_metric="ln_term", theory_ids=[1]))
    controls.set_theory_info(TheoryInfo(False, 8.14, []))
    assert controls.theory_label.text().startswith("No theoretical curve is defined for this Y metric")
    controls.set_view(ViewState(y_metric="raw_phase_phi", theory_ids=[1]))
    controls.set_theory_info(TheoryInfo(True, 8.14, []))
    assert controls.theory_label.text() == "Curves drawn with Δr = 8.14 mm"
    assert controls.theory_mixed_label.isHidden()
    controls.set_theory_info(TheoryInfo(True, 8.14, [6.0, 8.14]))
    assert not controls.theory_mixed_label.isHidden()
    assert controls.theory_mixed_label.text().startswith("the filtered runs use more than one Δr")
    assert controls.theory_mixed_label.text().endswith("(6, 8.14 mm)")
    controls.set_view(ViewState(y_metric="raw_phase_phi", theory_ids=[]))
    assert controls.theory_label.isHidden()


def test_period_source_segmented_control(controls):
    hits = _spy(controls.changed)
    controls.resp_button.click()
    assert controls.apply_to(ViewState()).period_source == "resp"
    assert len(hits) == 1
    assert "Applies to Period / Frequency axes" in controls.source_hint.text()
