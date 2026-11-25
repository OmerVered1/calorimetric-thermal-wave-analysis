"""ChartView base widget: log masking, categories, clicks, lasso, legend bar, export (offscreen)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ctwa.stats.specs import ChartSpec, Group, RefLine, Series  # noqa: E402
from ctwa.ui.statistics.chart_view import ChartView, mask_for_log, points_in_polygon  # noqa: E402
from ctwa.ui.statistics.legend_bar import LegendBar  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _series(name, xs, ys, ids=None, **kw):
    ids = ids if ids is not None else list(range(1, len(xs) + 1))
    return Series(name=name, color="#3498db", x=list(xs), y=list(ys), ids=ids, hover=["h%s" % i for i in ids],
                  mode="markers", **kw)


def _xy(series, **kw):
    return ChartSpec(kind="xy", title="T vs x", xlabel="x", ylabel="y", series=series, **kw)


def _view(qapp, spec):
    v = ChartView()
    v.resize(600, 400)
    v.set_spec(spec)
    return v


def test_mask_for_log_drops_non_positive(qapp):
    xs, ys, kept = mask_for_log([1, 2, 3, 4], [-1, 0, 2, 4], False, True)
    assert list(kept) == [2, 3] and list(ys) == [2, 4] and list(xs) == [3, 4]
    xs, ys, kept = mask_for_log([0, 1, 2], [5, 6, 7], True, False)
    assert list(kept) == [1, 2]
    xs, ys, kept = mask_for_log([1, 2], [3, 4], False, False)
    assert list(kept) == [0, 1]


def test_log_axis_with_non_positive_values_renders(qapp):
    v = _view(qapp, _xy([_series("a", [1, 2, 3, 4], [-1, 0, 2, 4])], ylog=True))
    items = v.scatter_items()
    assert len(items) == 1 and len(items[0].points()) == 2


def test_log_axis_all_non_positive_shows_nothing(qapp):
    v = _view(qapp, _xy([_series("a", [1, 2], [-1, 0])], ylog=True))
    assert sum(len(i.points()) for i in v.scatter_items()) == 0


def test_categories_become_bottom_ticks(qapp):
    spec = ChartSpec(kind="box", title="b", categories=[("A", "A\nn = 3"), ("B", "B\nn = 5")],
                     groups=[Group("A", "#111111", [1, 2, 3], [None] * 3), Group("B", "#222222", [1, 2], [None] * 2)])
    v = _view(qapp, spec)
    ticks = v.plot_item().getAxis("bottom")._tickLevels
    assert [t[1] for t in ticks[0]] == ["A\nn = 3", "B\nn = 5"]


def test_point_click_emits_id_only_when_present(qapp):
    v = _view(qapp, _xy([_series("a", [1, 2, 3], [1, 2, 3], ids=[10, None, 12])]))
    got = []
    v.point_clicked.connect(got.append)
    item = v.scatter_items()[0]
    pts = item.points()
    item.sigClicked.emit(item, [pts[2]], None)
    item.sigClicked.emit(item, [pts[1]], None)
    assert got == [12]
    v.set_tool("lasso")
    item.sigClicked.emit(item, [pts[0]], None)
    assert got == [12]


def test_points_in_polygon():
    import numpy as np
    inside = points_in_polygon([(0, 0), (4, 0), (4, 4), (0, 4)], np.array([1, 5]), np.array([1, 1]))
    assert list(inside) == [True, False]


def test_lasso_selects_markers_inside(qapp):
    v = _view(qapp, _xy([_series("a", [1, 2, 3, 4], [1, 2, 3, 4], ids=[11, 12, 13, 14])]))
    sel, cleared = [], []
    v.selection_made.connect(sel.append)
    v.selection_cleared.connect(lambda: cleared.append(1))
    v.select_polygon([(1.5, 1.5), (3.5, 1.5), (3.5, 3.5), (1.5, 3.5)])
    assert sel == [[12, 13]] and v.selected_ids() == [12, 13]
    v.select_polygon([(10, 10), (10.1, 10), (10.1, 10.1)])
    assert cleared == [1] and v.selected_ids() == []


def test_lasso_on_log_axis_uses_displayed_coordinates(qapp):
    v = _view(qapp, _xy([_series("a", [1, 2, 3, 4], [1, 10, 100, 1000], ids=[1, 2, 3, 4])], ylog=True))
    sel = []
    v.selection_made.connect(sel.append)
    v.select_polygon([(0, 0.5), (5, 0.5), (5, 2.5), (0, 2.5)])        # log10 y between 0.5 and 2.5
    assert sel == [[2, 3]]


def test_empty_selection_via_none_ids(qapp):
    v = _view(qapp, _xy([_series("a", [1, 2], [1, 2], ids=[None, None])]))
    sel, cleared = [], []
    v.selection_made.connect(sel.append)
    v.selection_cleared.connect(lambda: cleared.append(1))
    v.select_polygon([(0, 0), (3, 0), (3, 3), (0, 3)])
    assert sel == [] and cleared == [1]


def test_legend_toggle_group_and_isolate(qapp):
    bar = LegendBar()
    bar.set_entries([("a", "#111111", "g"), ("b", "#222222", "g"), ("c", "#333333", None)])
    events = []
    bar.toggled.connect(lambda n, vis: events.append((n, vis)))
    QTest.mouseClick(bar.entry_widget("a"), Qt.LeftButton)
    assert events == [("a", False)]
    assert not bar.is_visible("a") and not bar.is_visible("b") and bar.is_visible("c")
    QTest.mouseClick(bar.entry_widget("a"), Qt.LeftButton)
    assert bar.is_visible("a") and bar.is_visible("b")
    QTest.mouseDClick(bar.entry_widget("c"), Qt.LeftButton)
    assert bar.is_visible("c") and not bar.is_visible("a") and not bar.is_visible("b")
    QTest.mouseDClick(bar.entry_widget("c"), Qt.LeftButton)
    assert all(bar.is_visible(n) for n in "abc")


def test_hidden_series_not_selectable_and_group_hides(qapp):
    s1 = _series("m1", [1, 2], [1, 2], ids=[1, 2], legendgroup="m")
    s2 = _series("m1 — mean", [1, 2], [1, 2], ids=[None, None], legendgroup="m", legend=False)
    s3 = _series("other", [1, 2], [1, 2], ids=[3, 4])
    v = _view(qapp, _xy([s1, s2, s3]))
    v.legend_bar().click_entry("m1")
    assert not v.series_visible("m1") and not v.series_visible("m1 — mean") and v.series_visible("other")
    sel = []
    v.selection_made.connect(sel.append)
    v.select_polygon([(0, 0), (3, 0), (3, 3), (0, 3)])
    assert sel == [[3, 4]]


def test_export_png_triple_width_and_svg(qapp, tmp_path):
    from PySide6.QtGui import QImage
    v = _view(qapp, _xy([_series("a", [1, 2, 3], [1, 2, 3])]))
    before = v.plot_item().viewRange()
    png, svg = str(tmp_path / "c.png"), str(tmp_path / "c.svg")
    v.export_png(png)
    v.export_svg(svg)
    img = QImage(png)
    assert img.width() == 3 * v.plot_widget().width()
    assert open(svg, encoding="utf-8").read(200).lstrip().startswith("<svg")
    assert v.plot_item().viewRange() == before


def test_ref_line_and_label(qapp):
    v = _view(qapp, _xy([_series("a", [1, 2], [1, 2])], ref_lines=[RefLine(1.5, "Ideal", "#888888", "dash", 1)]))
    lines = v.ref_line_items()
    assert len(lines) == 1 and lines[0][0].value() == 1.5 and lines[0][1].toPlainText() == "Ideal"


def test_ref_line_on_log_axis_is_at_log_position(qapp):
    v = _view(qapp, _xy([_series("a", [1, 2], [1, 100])], ylog=True, ref_lines=[RefLine(10, "r", "#888888", "dash", 1)]))
    assert abs(v.ref_line_items()[0][0].value() - 1.0) < 1e-9


# ---- log axis ticks: decades labelled, 2 and 5 as unlabelled subticks when dense

def test_log_ticks_wide_axis_labels_one_two_five():
    from ctwa.ui.statistics.geometry import log_ticks
    import math
    major, minor = log_ticks(math.log10(75), math.log10(2400), 800)
    assert [t[1] for t in major] == ["100", "200", "500", "1000", "2000"]
    assert all(t[1] == "" for t in minor) and minor


def test_log_ticks_dense_axis_labels_decades_only():
    from ctwa.ui.statistics.geometry import log_ticks
    major, minor = log_ticks(-1, 3, 400)               # 4 decades in 400 px
    assert [t[1] for t in major] == ["0.1", "1", "10", "100", "1000"]
    assert sorted(round(10 ** t[0], 6) for t in minor if t[0] > -1) [:4] == [0.2, 0.5, 2, 5]
    assert all(t[1] == "" for t in minor)


def test_log_ticks_very_dense_thins_labels_and_drops_subticks():
    from ctwa.ui.statistics.geometry import log_ticks
    major, minor = log_ticks(-8, 4, 360)               # 12 decades in 360 px
    labels = [t[1] for t in major if t[1]]
    assert 3 <= len(labels) <= 7
    assert minor == []
    assert all(t[0] == round(t[0]) for t in major)


def test_chart_view_installs_log_ticks_on_log_axes(qapp):
    v = _view(qapp, _xy([_series("a", [75, 200, 2400], [1, 2, 3])], xlog=True))
    levels = v.plot_item().getAxis("bottom")._tickLevels
    assert levels is not None
    labels = [t[1] for t in levels[0]]
    assert "100" in labels and "1000" in labels and "10.0" not in labels
