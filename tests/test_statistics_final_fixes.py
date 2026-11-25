"""Final-round Statistics fixes: wheel, rebuild cost, export failures and the minor items."""
from __future__ import annotations

import copy
import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from ctwa.stats.filters import distinct_values  # noqa: E402
from ctwa.ui.statistics.legend_bar import LegendBar  # noqa: E402
from tests.test_statistics_tab import PRESETS, ROWS, made, qapp, settings, StubLoader  # noqa: E402,F401


def big_rows(n=400, models=30):
    out = []
    for i in range(n):
        r = copy.deepcopy(ROWS[i % len(ROWS)])
        r["id"] = 1000 + i
        r["model_name"] = "Model %d" % (i % models)
        out.append(r)
    return out


def _wheel(widget, pos, delta, mods=Qt.NoModifier):
    ev = QWheelEvent(QPointF(pos), QPointF(widget.mapToGlobal(pos)), QPoint(0, 0), QPoint(0, delta),
                     Qt.NoButton, mods, Qt.NoScrollPhase, False)
    QApplication.sendEvent(widget, ev)
    return ev


# ------------------------------------------------------------------ 1. wheel
def test_plain_wheel_scrolls_the_page_and_ctrl_wheel_zooms(made):
    tab = made()
    tab.resize(1400, 700)
    tab.show()
    QApplication.processEvents()
    chart = tab.builder_chart
    bar = tab.scroll.verticalScrollBar()
    tab.scroll_to("builder")
    QApplication.processEvents()
    vp = chart.plot_widget().viewport()
    pos = QPoint(vp.width() // 2, vp.height() // 2)
    before = chart.plot_item().getViewBox().viewRange()
    v0 = bar.value()
    _wheel(vp, pos, -120)
    QApplication.processEvents()
    assert chart.plot_item().getViewBox().viewRange() == before
    assert bar.value() > v0
    _wheel(vp, pos, 120, Qt.ControlModifier)
    QApplication.processEvents()
    assert chart.plot_item().getViewBox().viewRange() != before


# ------------------------------------------------------------------ 2. rebuild cost
def test_rebuild_400_rows_30_models_under_budget(made):
    tab = made(rows=None)
    tab.set_rows(big_rows(), PRESETS)       # warm up (imports, fonts)
    t = time.perf_counter()
    tab._rebuild()
    dt = time.perf_counter() - t
    print("rebuild seconds:", dt)
    assert dt < 1.5


def test_split_and_filter_toggle_do_not_rebuild_or_clear_selection(made):
    tab = made()
    tab.show()
    QApplication.processEvents()
    chart = tab.alpha_chart
    ids = [i for s in chart.spec().series for i in s.ids if i is not None]
    xs = [m.xs for m in chart._markers]
    chart.select_polygon([(-1e9, -1e9), (1e9, -1e9), (1e9, 1e9), (-1e9, 1e9)])
    assert chart.selected_ids()
    n = tab.rebuild_count
    tab._on_split()
    tab._toggle_filters()
    tab.flush()
    QTest.qWait(400)
    assert tab.rebuild_count == n
    assert chart.selected_ids()
    assert tab.view().filters_collapsed is True


def test_hidden_tab_defers_rebuild_until_shown(made):
    from ctwa.stats.filters import FilterState
    tab = made()
    tab.show()
    QApplication.processEvents()
    tab.hide()
    n = tab.rebuild_count
    tab.set_filters(FilterState(row_kind="all"))
    tab.set_rows(ROWS, PRESETS)
    QTest.qWait(400)
    assert tab.rebuild_count == n
    tab.show()
    QApplication.processEvents()
    assert tab.rebuild_count == n + 1
    tab.hide()
    tab.show()
    assert tab.rebuild_count == n + 1


# ------------------------------------------------------------------ 3. export failures
@pytest.fixture
def warned(monkeypatch):
    calls = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: calls.append(a) or QMessageBox.Ok)
    return calls


def test_csv_to_unwritable_path_warns(made, warned, tmp_path):
    tab = made(save_path_provider=lambda: str(tmp_path / "no" / "such" / "dir" / "x.csv"))
    tab._download_csv()
    assert len(warned) == 1


@pytest.mark.parametrize("kind", ["png", "svg"])
def test_chart_export_to_unwritable_path_warns(made, warned, monkeypatch, tmp_path, kind):
    from PySide6.QtWidgets import QFileDialog
    bad = str(tmp_path / "no" / "such" / ("x." + kind))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (bad, ""))
    tab = made()
    tab.builder_chart._export_dialog(kind)
    assert len(warned) == 1


# ------------------------------------------------------------------ minor
def test_tools_follow_the_chart_kind(made):
    tab = made()
    tab.show()
    kinds = {}
    for c in tab._all_charts():
        s = c.spec()
        if s is not None:
            kinds.setdefault(s.kind, c)
    assert "heatmap" in kinds
    h = kinds["heatmap"]
    for k in ("pan", "lasso", "box"):
        assert h._buttons[k].isHidden()
    assert h._reset_button.isHidden()
    for kind in ("box", "violin", "bar"):
        if kind in kinds:
            c = kinds[kind]
            assert c._buttons["lasso"].isHidden() and c._buttons["box"].isHidden()
            assert not c._reset_button.isHidden()
    xy = kinds["xy"]
    assert not xy._buttons["lasso"].isHidden() and not xy._reset_button.isHidden()


def test_empty_model_name_is_labelled_and_filterable(made):
    rows = copy.deepcopy(ROWS)
    rows[0]["model_name"] = None
    rows[1]["model_name"] = ""
    tab = made(rows=rows)
    assert "(none)" in distinct_values(tab._rows, "model_name")
    assert any(r[0] == "(none)" for r in tab.summary.texts())
    names = {s.name for c in tab._all_charts() if c.spec() for s in c.spec().series}
    assert "(none)" in names or any("(none)" in n for n in names)


def test_presets_with_null_values_are_skipped(made):
    tab = made(presets=[{"id": 1, "material_name": "Al", "temperature_c": None, "alpha_mm2s": 64.0},
                        {"id": 2, "material_name": "Cu", "temperature_c": 25, "alpha_mm2s": None},
                        {"id": 3, "material_name": "Fe", "temperature_c": 25, "alpha_mm2s": 20.0}])
    assert list(tab.controls.theory_chips) == [3]


def test_legend_labels_are_plain_text(qapp):
    bar = LegendBar()
    bar.set_entries([("a<b>c", "#ff0000", None)])
    labels = [w.label for w in bar._widgets.values()]
    assert labels and all(l.textFormat() == Qt.PlainText for l in labels)


def test_category_axis_leaves_room_for_two_tick_lines_and_the_label(made):
    tab = made()
    ax = tab.builder_chart.plot_item().getAxis("bottom")
    assert (ax.fixedHeight or 0) >= 70
