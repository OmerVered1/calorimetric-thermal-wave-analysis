"""Compare charts and tab (Results tab, Task 12), offscreen with a FakeLoader."""
from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from results_fakes import FakeLoader  # noqa: E402
from ctwa.ui.results import compare_logic as cl  # noqa: E402
from ctwa.ui.results.compare_charts import MetricChart, OverlayChart  # noqa: E402
from ctwa.ui.results.compare_tab import CompareTab  # noqa: E402
from ctwa.ui.results.fmt import label_of, run_label_text  # noqa: E402

FIXTURE = (Path(__file__).parent / "data" / "results" / "overlay_fixture.json").read_text(encoding="utf-8")
PNG = "iVBORw0KGgo" + "A" * 40


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def row(i, **kw):
    r = {"id": i, "model_name": "Stainless Steel", "test_date": "%02d/11/2026" % (i + 10), "test_time": "10:30",
         "temperature_c": 700 + i, "gas_atmosphere": "Ar", "analysis_mode": "Auto", "r1_mm": 6.72, "r2_mm": 14.86,
         "amplitude_a1": 12.34, "amplitude_a2": 5.67, "period_t": 600.4, "raw_lag_dt": 105.2,
         "alpha_combined_raw": 8e-6, "alpha_phase_raw": 8.5e-6, "use_calibration": False, "ln_term": 0.5}
    r.update(kw)
    return r


ROWS = [row(1), row(2, alpha_phase_raw=0), row(3, alpha_phase_raw=9e-6), row(4), row(5), row(6)]


@pytest.fixture
def make(qapp):
    made = []

    def _make(rows=ROWS):
        loader = FakeLoader(rows)
        tab = CompareTab(loader)
        tab.resize(1100, 1400)
        tab.show()
        made.append(tab)
        return tab, loader
    yield _make
    for t in made:
        t.close()


def by_id(i):
    return next(r for r in ROWS if r["id"] == i)


def requests(loader):
    return [c[1] for c in loader.calls if c[0] == "request_graph"]


def test_picker_limits_and_empty_prompt(make):
    tab, _ = make()
    assert tab.prompt_text() == "Select one or more analyses above to view and compare them."
    assert tab.charts_visible() is False
    tab.set_ids([1, 2, 3, 4, 5])
    assert tab.ids() == [1, 2, 3, 4]
    tab.set_ids([4242, 3])
    assert tab.ids() == [3]
    assert tab.charts_visible() is True and tab.prompt_text() == ""
    tab.set_ids([])
    assert tab.charts_visible() is False


def test_graphs_requested_once_per_run_until_rows_change(make):
    tab, loader = make()
    tab.set_ids([1, 2])
    tab.set_ids([1, 2, 3])
    assert requests(loader) == [1, 2, 3]
    tab.set_ids([3, 1])
    assert requests(loader) == [1, 2, 3]
    loader.set_rows(ROWS)
    assert sorted(requests(loader)[3:]) == [1, 3]


def test_overlay_curves_styles_and_footnote(make):
    tab, loader = make()
    tab.set_ids([1, 3, 4])
    loader.graph_loaded.emit(1, FIXTURE)
    loader.graph_loaded.emit(3, FIXTURE)
    loader.graph_loaded.emit(4, PNG)                       # an image: no waveform
    ov = tab.overlay
    l1, l3 = label_of(by_id(1)), label_of(by_id(3))
    assert ov.curve_names() == [l1 + " — Source", l1 + " — Response", l3 + " — Source", l3 + " — Response"]
    styles = ov.curve_styles()
    assert styles[0][1:] == (cl.run_colors(0)[0], "solid") and styles[1][1:] == (cl.run_colors(0)[1], "dash")
    assert styles[2][1:] == (cl.run_colors(1)[0], "solid") and styles[3][1:] == (cl.run_colors(1)[1], "dash")
    assert tab.no_waveform() == [label_of(by_id(4))]
    assert "No stored waveform (shown in table only): " + label_of(by_id(4)) in tab.footnote_text()
    assert tab.overlay_message() == ""


def test_broken_graphs_are_listed_not_raised(make):               # Review Focus 5
    tab, loader = make()
    tab.set_ids([1, 2, 3, 4])
    loader.graph_loaded.emit(1, FIXTURE)
    loader.graph_loaded.emit(2, "<broken json")
    loader.graph_loaded.emit(3, "{}")
    loader.graph_loaded.emit(4, "")                        # no stored graph (None now means a failed fetch)
    assert tab.no_waveform() == [label_of(by_id(i)) for i in (2, 3, 4)]
    assert len(tab.overlay.curve_names()) == 2


def test_no_run_with_waveform(make):
    tab, loader = make()
    tab.set_ids([1, 2])
    assert tab.overlay_message() == "Loading…"
    loader.graph_loaded.emit(1, "")
    loader.graph_loaded.emit(2, "<x")
    assert tab.overlay_message() == "None of the selected analyses has a stored waveform to overlay."
    assert tab.overlay.curve_names() == [] and not tab.overlay_visible()


def test_toggles_change_the_data(make):
    tab, loader = make()
    tab.set_ids([1, 3])
    loader.graph_loaded.emit(1, FIXTURE)
    loader.graph_loaded.emit(3, FIXTURE)
    ov = tab.overlay
    assert ov.x_title() == "Time from start (s)" and ov.y_title() == "Power (mW)"
    assert tab.options() == cl.OverlayOptions(signal="both", align=True, norm_amp=False, norm_time=False,
                                              guides=True)

    def expected(**kw):
        opts = cl.OverlayOptions(**kw)
        runs = [cl.overlay_run(by_id(i), FIXTURE, k, opts) for k, i in enumerate((1, 3))]
        return runs
    runs = expected()
    assert ov.line_count() == sum(len(r.lines) for r in runs)
    assert ov.box_texts() == [cl.box_text(by_id(1)), cl.box_text(by_id(3))]
    tab.align_button.click()
    assert ov.x_title() == "Time (s)"
    assert ov.curve_data()[0][0][0] == 1000                # the stored x
    tab.align_button.click()
    tab.norm_amp_button.click()
    assert ov.y_title() == "Normalized power" and ov.line_count() == 0
    ys = [v for xs, ys in ov.curve_data() for v in ys]
    assert min(ys) >= 0 and max(ys) <= 1
    assert ov.box_texts() == [cl.box_text(by_id(1)), cl.box_text(by_id(3))]
    tab.norm_amp_button.click()
    tab.norm_time_button.click()
    assert ov.x_title() == "Normalized time (0–1)"
    xs = [v for xs, _ in ov.curve_data() for v in xs]
    assert min(xs) == 0 and max(xs) == 1
    tab.norm_time_button.click()
    tab.signal_buttons["source"].click()
    assert len(ov.curve_names()) == 2
    assert ov.line_count() == sum(len(r.lines) for r in expected(signal="source"))
    tab.guides_button.click()
    assert ov.line_count() == 0 and ov.box_texts() == []


def test_late_graph_of_removed_run_is_ignored(make):
    tab, loader = make()
    tab.set_ids([1])
    tab.set_ids([3])
    loader.graph_loaded.emit(1, FIXTURE)
    assert tab.overlay.curve_names() == [] and tab.no_waveform() == []
    assert requests(loader).count(1) == 1
    loader.graph_loaded.emit(3, FIXTURE)
    assert len(tab.overlay.curve_names()) == 2
    tab.set_ids([1, 3])                                # added again: asked for again
    assert requests(loader).count(1) == 2


def test_metric_chart(make):
    tab, _ = make()
    tab.set_ids([1, 2, 3])
    tab.select_metric("alpha_phase_raw")
    m = tab.metric_chart
    assert m.dot_values() == [8.5, None, 9.0]
    assert m.text_labels() == ["8.500", "—", "9.000"]
    assert m.dot_labels() == [run_label_text(by_id(i)) for i in (1, 2, 3)]
    assert m.chart_height() == 120 + 70 * 3
    assert m.title_text() == "α Phase (raw) (mm²/s) — comparison across analyses"
    assert tab.metric_label() == "α Phase (raw) (mm²/s)"
    assert m.dot_colors() == [cl.run_colors(i)[0] for i in range(3)]


def test_metric_text_from_1000(qapp):
    m = MetricChart()
    m.set_values(["a", "b"], [1234.5, 0.5], ["#1F5BB0", "#E4572E"], "x")
    assert m.text_labels() == ["1235", "0.5000"] and m.chart_height() == 260


def test_parameter_table_and_differing(make):
    r1, r2 = row(1), row(1, temperature_c=800, alpha_phase_raw=9e-6, id=9)
    tab, loader = make([r1, r2])
    tab.set_ids([1, 9])
    texts = tab.table_texts()
    assert len(texts) == len(cl.PARAM_ROWS)
    for t, (label, _) in zip(texts, cl.PARAM_ROWS):
        assert t == [label, cl.param_value(label, r1), cl.param_value(label, r2)]
    want = {"Temperature (°C)", "α Phase raw (mm²/s)"}
    assert tab.differing() == want
    assert tab.diff_check.text() == "Only rows that differ (2)"
    tab.diff_check.setChecked(True)
    assert {t[0] for t in tab.table_texts()} == want
    assert tab.view_mode() == "table"


def test_diff_checkbox_hidden_with_one_run_and_cards(make):
    tab, _ = make()
    tab.set_ids([1])
    assert tab.diff_check.isHidden()
    assert tab.differing() == set()
    tab.set_ids([1, 3, 4])
    assert not tab.diff_check.isHidden()
    tab.cards_button.click()
    assert tab.view_mode() == "cards"
    assert tab.card_row_counts() == [28, 28, 28]
    tab.table_button.click()
    assert tab.view_mode() == "table"


def test_deleted_run_leaves_the_selection(make):
    tab, loader = make()
    tab.set_ids([1, 2, 3])
    loader.set_rows([r for r in ROWS if r["id"] != 2])
    assert tab.ids() == [1, 3]


def test_overlay_chart_alone(qapp):
    c = OverlayChart()
    opts = cl.OverlayOptions()
    run = cl.overlay_run(by_id(1), FIXTURE, 0, opts)
    c.set_runs([run, None], opts, [None, "box two"])
    assert c.box_texts() == [run.box_text, "box two"]
    c.set_runs([], opts)
    assert c.curve_names() == [] and c.line_count() == 0 and c.box_texts() == []


def test_painting_the_whole_tab_does_not_crash(make, qapp):
    # a public attribute named like a QWidget/QPaintDevice method (metric, scroll) crashed the first paint
    from PySide6.QtCore import Signal
    from PySide6.QtWidgets import QWidget
    tab, loader = make()
    tab.set_ids([1, 2, 3])
    for i in (1, 2, 3):
        loader.graph_loaded.emit(i, FIXTURE)
    qapp.processEvents()
    tab.grab()
    assert [n for n in vars(tab) if hasattr(QWidget, n) and not isinstance(getattr(QWidget, n), Signal)] == []      # no attribute hides a QWidget member


def test_redraws_do_not_leak_plot_items(make):
    tab, loader = make()
    tab.set_ids([1, 3])
    loader.graph_loaded.emit(1, FIXTURE)
    loader.graph_loaded.emit(3, FIXTURE)
    pi = tab.overlay._pi
    base = (len(pi.items), len(pi.dataItems), len(pi.vb.addedItems))
    for _ in range(5):
        tab.norm_amp_button.click()
    assert (len(pi.items), len(pi.dataItems), len(pi.vb.addedItems)) == base


def test_overlay_curves_connect_finite(make):
    tab, loader = make()
    tab.set_ids([1])
    loader.graph_loaded.emit(1, FIXTURE)
    item = tab.overlay._items[0]
    assert item.opts.get("connect") == "finite"


def test_toggles_do_not_reparse_graph_json(make, monkeypatch):
    tab, loader = make()
    tab.set_ids([1, 3])
    loader.graph_loaded.emit(1, FIXTURE)
    loader.graph_loaded.emit(3, FIXTURE)
    calls = []
    real = cl.parse_graph
    monkeypatch.setattr(cl, "parse_graph", lambda raw: (calls.append(1), real(raw))[1])
    for _ in range(3):
        tab.norm_amp_button.click()
    assert calls == []
    loader.graph_loaded.emit(1, FIXTURE + " ")          # changed text: parsed again
    assert len(calls) == 1


def test_known_graphs_not_requested_again_on_rows(make):
    tab, loader = make()
    tab.set_ids([1, 3])
    loader.graph_loaded.emit(1, FIXTURE)
    n = len(requests(loader))
    loader.set_rows(ROWS)
    assert requests(loader)[n:] == [3]


def test_failed_graph_shows_note_and_retries(make):
    tab, loader = make()
    tab.set_ids([1, 3])
    loader.graph_loaded.emit(1, FIXTURE)
    loader.graph_loaded.emit(3, None)
    assert tab.overlay_message() != "Loading…"
    assert "Could not load the graph" in tab.footnote_text()
    n = len(requests(loader))
    loader.set_rows(ROWS)
    assert requests(loader)[n:] == [3]          # retried; the good one is not


def test_read_error_banner_when_rows_are_shown(make):
    tab, loader = make()
    tab.set_ids([1])
    loader.failed.emit("net", "no route")
    assert tab.banner.isVisible()
    assert tab.banner_label.text() == "Can't reach the database: no route"
    loader.set_rows(ROWS)
    assert not tab.banner.isVisible()
