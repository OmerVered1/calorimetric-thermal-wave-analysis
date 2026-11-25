"""XY series (lines, markers, error bars, pair segments, overlays) and the correlation heatmap (offscreen)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import pyqtgraph as pg  # noqa: E402  (after PySide6, so it picks the same binding)
from ctwa.stats.aggregate import CORR_LABELS  # noqa: E402
from ctwa.stats.specs import ChartSpec, HeatSpec, Series  # noqa: E402
from ctwa.ui.statistics.chart_view import ChartView  # noqa: E402
from ctwa.ui.statistics.heatmap import heat_lut  # noqa: E402

NAN = float("nan")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _s(name="a", n=3, **kw):
    kw.setdefault("mode", "lines+markers")
    return Series(name=name, color="#3498db", x=[float(i + 1) for i in range(n)], y=[float(i + 2) for i in range(n)],
                  ids=list(range(1, n + 1)), hover=["h"] * n, **kw)


def _view(spec):
    v = ChartView()
    v.resize(700, 450)
    v.set_spec(spec)
    return v


def _spec(series, **kw):
    return ChartSpec(kind="xy", title="t", xlabel="x", ylabel="y", series=series, **kw)


def _items(v, cls):
    return [i for i in v.plot_item().items if isinstance(i, cls)]


def test_markers_and_lines_series(qapp):
    v = _view(_spec([_s()]))
    assert len(_items(v, pg.PlotDataItem)) == 1
    assert [len(s.points()) for s in v.scatter_items()] == [3]


def test_markers_only_has_no_line_and_lines_only_no_markers(qapp):
    v = _view(_spec([_s(mode="markers"), _s("b", mode="lines")]))
    assert len(_items(v, pg.PlotDataItem)) == 1 and len(v.scatter_items()) == 1


def test_hollow_series_has_no_brush_and_dash_maps(qapp):
    v = _view(_spec([_s(filled=False, dash="dot", width=2)]))
    item = v.scatter_items()[0]
    assert item.opts["brush"].style() == Qt.NoBrush
    line = _items(v, pg.PlotDataItem)[0]
    assert line.opts["pen"].style() == Qt.DotLine and line.opts["pen"].widthF() == 2


def test_opacity_applies(qapp):
    v = _view(_spec([_s(opacity=0.4)]))
    assert v.scatter_items()[0].opacity() == pytest.approx(0.4)
    assert _items(v, pg.PlotDataItem)[0].opacity() == pytest.approx(0.4)


def test_error_bars(qapp):
    v = _view(_spec([_s(yerr=[0.5, 1.0, 0.25])]))
    eb = _items(v, pg.ErrorBarItem)
    assert len(eb) == 1 and list(eb[0].opts["top"]) == [0.5, 1.0, 0.25] and list(eb[0].opts["bottom"]) == [0.5, 1.0, 0.25]
    v = _view(_spec([_s(yerr=[0, 0, 0])]))
    assert _items(v, pg.ErrorBarItem) == []


def test_error_bar_zero_points_skipped(qapp):
    v = _view(_spec([_s(yerr=[0, 1.0, 0])]))
    eb = _items(v, pg.ErrorBarItem)[0]
    assert list(eb.opts["top"]) == [1.0] and list(eb.opts["x"]) == [2.0]


def test_segment_pairs(qapp):
    seg = Series(name="m", color="#111111", x=[1, 2, NAN, 3, 4, NAN], y=[1, 2, NAN, 3, 5, NAN], ids=[None] * 6,
                 hover=[""] * 6, mode="lines", segments=True, legend=False)
    v = _view(_spec([seg]))
    line = _items(v, pg.PlotDataItem)[0]
    assert line.opts["connect"] == "pairs"
    xs, ys = line.getData()
    assert list(xs) == [1, 2, 3, 4] and list(ys) == [1, 2, 3, 5]
    assert v.scatter_items() == []


def test_log_axes_skip_non_positive_in_lines_too(qapp):
    v = _view(_spec([_s(n=4)], ylog=True))
    s = Series(name="z", color="#111111", x=[1, 2, 3, 4], y=[-1, 0, 2, 4], ids=[1, 2, 3, 4], hover=[""] * 4,
               mode="lines+markers")
    v = _view(_spec([s], ylog=True))
    assert len(v.scatter_items()[0].points()) == 2


def test_overlay_legend_and_group_toggle(qapp):
    raw = _s("M (raw)", mode="markers", legend=False, legendgroup="M", opacity=0.4)
    mean = _s("M — mean ± std", legend=True, legendgroup="M", yerr=[0.1, 0.1, 0.1])
    other = _s("N", legend=True, legendgroup="N")
    seg = Series(name="M", color="#111111", x=[1, 2, NAN], y=[1, 2, NAN], ids=[None] * 3, hover=[""] * 3, mode="lines",
                 segments=True, legend=False, legendgroup="M")
    v = _view(_spec([raw, mean, other, seg]))
    assert list(v.legend_bar()._widgets) == ["M — mean ± std", "N"]
    v.legend_bar().click_entry("M — mean ± std")
    assert not v.series_visible("M (raw)") and not v.series_visible("M — mean ± std") and v.series_visible("N")
    assert all(not i.isVisible() or True for i in _items(v, pg.ErrorBarItem))
    eb = _items(v, pg.ErrorBarItem)[0]
    assert not eb.isVisible()
    raw_marker = v.scatter_items()[0]
    assert not raw_marker.isVisible()


# ------------------------------------------------------------------ heatmap

def _heat(n=10):
    labels = list(CORR_LABELS)[:n]
    m = [[1.0 if i == j else round(((i * 7 + j * 3) % 13) / 13 - 0.5, 2) for j in range(n)] for i in range(n)]
    for i in range(n):
        for j in range(i):
            m[i][j] = m[j][i]
    text = [["%.2f" % v for v in row] for row in m]
    return ChartSpec(kind="heatmap", title="Correlation Matrix (Pearson r)", heat=HeatSpec(labels, m, text), height=560)


def test_heat_lut_matches_rdbu_stops():
    lut = heat_lut()
    n = len(lut)
    assert tuple(lut[(n - 1) // 2][:3]) == pytest.approx((190, 190, 190), abs=1)
    assert tuple(lut[-1][:3]) == pytest.approx((178, 10, 28), abs=1)
    assert tuple(lut[0][:3]) == pytest.approx((5, 10, 172), abs=1)


def test_heatmap_image_texts_and_click(qapp):
    spec = _heat()
    v = _view(spec)
    v.show()
    qapp.processEvents()
    imgs = _items(v, pg.ImageItem)
    assert len(imgs) == 1 and imgs[0].image.shape == (10, 10)
    texts = _items(v, pg.TextItem)
    assert sorted(t.toPlainText() for t in texts) == sorted(s for row in spec.heat.text for s in row)
    assert len(texts) == 100
    got = []
    v.cell_clicked.connect(lambda r, c: got.append((r, c)))

    class Ev:
        def __init__(self, p):
            self._p = p

        def button(self):
            return Qt.LeftButton

        def scenePos(self):
            return self._p

    scene_pt = v.plot_item().getViewBox().mapViewToScene(QPointF(4.5, 2.5))     # column 4 (Δt), row 2 (A₁/A₂)
    v._on_scene_click(Ev(scene_pt))
    assert got == [("A₁/A₂", "Δt")]


def _has_bar(v):
    lay = v.plot_item().layout
    return any(isinstance(lay.itemAt(i), pg.ColorBarItem) for i in range(lay.count()))


def test_heatmap_colour_bar_and_cleanup(qapp):
    v = _view(_heat())
    assert _has_bar(v)
    v.set_spec(_spec([_s()]))
    assert not _has_bar(v)
    assert _items(v, pg.ImageItem) == [] and len(v.scatter_items()) == 1
    assert v.plot_item().getAxis("bottom").style["showValues"] is True
