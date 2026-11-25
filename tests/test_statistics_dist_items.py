"""Box, violin and bar rendering (offscreen)."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import pyqtgraph as pg  # noqa: E402  (after PySide6, so it picks the same binding)

from ctwa.stats.dist import HALF_WIDTH, box_stats, jitter_x, violin_shape  # noqa: E402
from ctwa.stats.specs import ChartSpec, Group, Series  # noqa: E402
from ctwa.ui.statistics.chart_view import ChartView  # noqa: E402
from ctwa.ui.statistics.dist_items import BoxItem, ViolinItem, draw_bar, draw_box, draw_violin  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _spec(kind, groups, **kw):
    return ChartSpec(kind=kind, title="t", groups=groups, categories=[(g.name, g.name) for g in groups], **kw)


def _g(name, vals):
    return Group(name, "#3498db", list(vals), [None] * len(vals))


def _plot(qapp):
    return pg.PlotItem()


def test_box_geometry_matches_plotly_maths(qapp):
    spec = _spec("box", [_g("a", [1, 2, 3, 4, 5]), _g("b", [1, 2, 3, 4, 100])])
    boxes = [i for i in draw_box(_plot(qapp), spec) if isinstance(i, BoxItem)]
    assert len(boxes) == 2
    a, b = boxes
    assert (a.q1, a.med, a.q3) == pytest.approx((1.75, 3, 4.25))
    assert (b.q1, b.med, b.q3) == pytest.approx((1.75, 3, 28))
    exp = box_stats([1, 2, 3, 4, 100])
    assert (b.lo, b.hi) == (exp.lo_whisker, exp.hi_whisker)
    assert (a.lo, a.hi) == (1, 5)
    assert a.x == 0 and b.x == 1


def test_empty_group_draws_nothing(qapp):
    spec = _spec("box", [_g("a", []), _g("b", [1, 2, 3])])
    items = draw_box(_plot(qapp), spec)
    assert len([i for i in items if isinstance(i, BoxItem)]) == 1
    draw_violin(_plot(qapp), _spec("violin", [_g("a", [])]))


def test_points_one_per_value_in_jitter_band(qapp):
    spec = _spec("box", [_g("a", [1, 2, 3]), _g("b", [4, 5, 6, 7])])
    items = draw_box(_plot(qapp), spec)
    scat = [i for i in items if isinstance(i, pg.ScatterPlotItem)]
    assert [len(s.points()) for s in scat] == [3, 4]
    for idx, s in enumerate(scat):
        for p in s.points():
            assert abs(p.pos().x() - (idx + HALF_WIDTH * -1.5)) <= HALF_WIDTH * 0.3 + 1e-9


def test_violin_polygon(qapp):
    vals = [1, 2, 2.5, 3, 7]
    items = draw_violin(_plot(qapp), _spec("violin", [_g("a", vals), _g("b", [4.0])]))
    vio = [i for i in items if isinstance(i, ViolinItem)]
    shape = violin_shape(vals)
    xs = [p[0] for p in vio[0].polygon_points()]
    assert max(xs) - 0 == pytest.approx(HALF_WIDTH) and min(xs) == pytest.approx(-HALF_WIDTH)
    assert max(abs(x) for x in xs) <= HALF_WIDTH + 1e-9
    assert len(vio[0].polygon_points()) == 2 * len(shape.ts)
    ones = [p[0] - 1 for p in vio[1].polygon_points()]
    assert all(abs(x) < 1e-12 for x in ones)


def test_bar_heights_and_error_bars(qapp):
    series = [Series("a", "#111111", [0.0], [5.0], [None], ["ha"], "markers", yerr=[1.5]),
              Series("b", "#222222", [1.0], [3.0], [None], ["hb"], "markers", yerr=[0.0])]
    spec = ChartSpec(kind="bar", title="t", series=series, categories=[("a", "a"), ("b", "b")])
    items = draw_bar(_plot(qapp), spec)
    bars = [i for i in items if isinstance(i, pg.BarGraphItem)]
    errs = [i for i in items if isinstance(i, pg.ErrorBarItem)]
    assert [float(b.opts["height"][0]) for b in bars] == [5.0, 3.0]
    assert len(errs) == 1                                   # zero error (n <= 1) draws nothing
    assert list(errs[0].opts["top"]) == [1.5] and list(errs[0].opts["bottom"]) == [1.5]
    assert errs[0].opts["beam"] == pytest.approx(0.12)
    assert bars[0].opts["width"] == pytest.approx(0.7)


def test_log_y_box_positions_median_at_log10(qapp):
    spec = _spec("box", [_g("a", [10, 100, 1000])], ylog=True)
    box = [i for i in draw_box(_plot(qapp), spec) if isinstance(i, BoxItem)][0]
    assert box.med == pytest.approx(math.log10(100))
    # non-positive values are skipped on a log axis, never an exception
    spec = _spec("box", [_g("a", [-1, 0, 10, 100, 1000])], ylog=True)
    box = [i for i in draw_box(_plot(qapp), spec) if isinstance(i, BoxItem)][0]
    assert box.med == pytest.approx(math.log10(100))


def test_chart_view_dispatches_and_ranges(qapp):
    v = ChartView()
    v.resize(500, 400)
    v.set_spec(_spec("box", [_g("a", [1, 2, 3, 4, 5]), _g("b", [2, 3, 4])]))
    (x0, x1), (y0, y1) = v.plot_item().viewRange()
    assert (x0, x1) == pytest.approx((-0.5, 1.5))
    assert y0 < 1 and y1 > 5
    v.set_spec(_spec("violin", [_g("a", [1, 2, 3, 4, 5])]))
    assert v.plot_item().viewRange()[0] == pytest.approx([-0.5, 0.5])
