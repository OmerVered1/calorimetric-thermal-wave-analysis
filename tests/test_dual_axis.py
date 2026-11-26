"""ResponseViewBox and link_y_zoom: wheel inside the plot moves both signals, an axis moves one."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import pyqtgraph as pg  # noqa: E402  (after PySide6, so it binds to it)

from ctwa.ui.dual_axis import ResponseViewBox, link_y_zoom  # noqa: E402


class FakeWheel:
    def __init__(self, scene_pos, local_pos=None, delta=120):
        self._sp, self._lp, self._d = scene_pos, local_pos or scene_pos, delta
        self.accepted = None

    def delta(self):
        return self._d

    def pos(self):
        return self._lp

    def scenePos(self):
        return self._sp

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.accepted = False


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def plot(qapp):
    w = pg.PlotWidget()
    w.resize(600, 400)
    w.show()
    item = w.getPlotItem()
    item.showAxis("right")
    vb2 = ResponseViewBox()
    item.scene().addItem(vb2)
    item.getAxis("right").linkToView(vb2)
    vb2.setXLink(item)
    item.vb.sigResized.connect(lambda: (vb2.setGeometry(item.vb.sceneBoundingRect()),
                                        vb2.linkedViewChanged(item.vb, vb2.XAxis)))
    item.plot(list(range(100)), [float(i) for i in range(100)])
    vb2.addItem(pg.PlotDataItem(list(range(100)), [float(i) * 50 + 1000 for i in range(100)]))
    qapp.processEvents()
    item.vb.setRange(xRange=(0, 100), yRange=(0, 100), padding=0)
    vb2.setYRange(1000, 6000, padding=0)
    link = link_y_zoom(item.vb, vb2)
    yield w, item, vb2, link
    w.close()


def _center(vb):
    return vb.sceneBoundingRect().center()


def test_wheel_inside_plot_zooms_time_and_both_signals(plot):
    _w, item, vb2, _l = plot
    x0 = item.vb.viewRange()[0]
    y0 = item.vb.viewRange()[1]
    r0 = vb2.viewRange()[1]
    item.vb.wheelEvent(FakeWheel(_center(item.vb), item.vb.mapFromScene(_center(item.vb))))
    x1, y1, r1 = item.vb.viewRange()[0], item.vb.viewRange()[1], vb2.viewRange()[1]
    assert (x1[1] - x1[0]) != pytest.approx(x0[1] - x0[0])
    fx = (y1[1] - y1[0]) / (y0[1] - y0[0])
    assert fx != pytest.approx(1.0)
    assert (r1[1] - r1[0]) / (r0[1] - r0[0]) == pytest.approx(fx)
    # the map is kept: the same point of the sources lines up as before
    a = (r0[1] - r0[0]) / (y0[1] - y0[0])
    b = r0[0] - a * y0[0]
    assert r1[0] == pytest.approx(a * y1[0] + b) and r1[1] == pytest.approx(a * y1[1] + b)


def test_wheel_on_the_right_axis_changes_only_the_response(plot):
    _w, item, vb2, _l = plot
    main_before = (item.vb.viewRange()[0][:], item.vb.viewRange()[1][:])
    r0 = vb2.viewRange()[1][:]
    ax = item.getAxis("right")
    pos = ax.sceneBoundingRect().center()
    ax.wheelEvent(FakeWheel(pos, QPointF(2, 2)))
    assert vb2.viewRange()[1] != r0
    assert (item.vb.viewRange()[0], item.vb.viewRange()[1]) == main_before


def test_wheel_on_the_left_axis_changes_only_the_source(plot):
    _w, item, vb2, _l = plot
    r0 = vb2.viewRange()[1][:]
    x0 = item.vb.viewRange()[0][:]
    y0 = item.vb.viewRange()[1][:]
    ax = item.getAxis("left")
    ax.wheelEvent(FakeWheel(ax.sceneBoundingRect().center(), QPointF(2, 2)))
    assert item.vb.viewRange()[1] != y0
    assert item.vb.viewRange()[0] == x0
    assert vb2.viewRange()[1] == r0


def test_axis_zoom_relearns_the_map(plot):
    _w, item, vb2, _l = plot
    ax = item.getAxis("right")
    ax.wheelEvent(FakeWheel(ax.sceneBoundingRect().center(), QPointF(2, 2)))
    y0, r0 = item.vb.viewRange()[1][:], vb2.viewRange()[1][:]
    item.vb.wheelEvent(FakeWheel(_center(item.vb), item.vb.mapFromScene(_center(item.vb))))
    y1, r1 = item.vb.viewRange()[1], vb2.viewRange()[1]
    a = (r0[1] - r0[0]) / (y0[1] - y0[0])
    assert (r1[1] - r1[0]) / (y1[1] - y1[0]) == pytest.approx(a)
    assert r1[0] == pytest.approx(r0[0] + a * (y1[0] - y0[0]))


def test_programmatic_fit_relearns_the_map(plot):
    _w, item, vb2, _l = plot
    item.vb.setYRange(10, 20, padding=0)
    vb2.setYRange(0, 1, padding=0)
    item.vb.wheelEvent(FakeWheel(_center(item.vb), item.vb.mapFromScene(_center(item.vb))))
    y1, r1 = item.vb.viewRange()[1], vb2.viewRange()[1]
    assert (r1[1] - r1[0]) / (y1[1] - y1[0]) == pytest.approx(0.1)


def test_response_box_ignores_events_from_inside_the_plot(plot):
    _w, _item, vb2, _l = plot
    r0 = vb2.viewRange()[1][:]
    ev = FakeWheel(_center(vb2))
    vb2.wheelEvent(ev)
    assert vb2.viewRange()[1] == r0 and ev.accepted is False


def test_real_wheel_over_the_plot_reaches_the_main_view_box(plot, qapp):
    """Through the scene, the response box on top must not swallow the wheel."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QWheelEvent
    w, item, vb2, _l = plot
    qapp.processEvents()
    x0, r0 = item.vb.viewRange()[0][:], vb2.viewRange()[1][:]
    c = w.mapFromScene(_center(item.vb))
    ev = QWheelEvent(QPointF(c), QPointF(w.viewport().mapToGlobal(c)), QPoint(0, 0), QPoint(0, 120),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    qapp.sendEvent(w.viewport(), ev)
    assert item.vb.viewRange()[0] != x0
    assert vb2.viewRange()[1] != r0


def test_figure_view_zoom_inside_moves_both_axes(qapp):
    import json
    from ctwa.ui.results.figure_view import FigureView
    fig = {"data": [{"x": [0, 1, 2], "y": [0, 1, 2], "type": "scatter"},
                    {"x": [0, 1, 2], "y": [100, 300, 200], "type": "scatter", "yaxis": "y2"}],
           "layout": {"yaxis2": {"overlaying": "y", "side": "right"}}}
    v = FigureView()
    v.resize(600, 400)
    v.show()
    v.show_graph(json.dumps(fig), {})
    assert v.mode() == "figure"
    vb, vb2 = v._pi.vb, v._view2
    y0, r0 = vb.viewRange()[1][:], vb2.viewRange()[1][:]
    vb.wheelEvent(FakeWheel(_center(vb), vb.mapFromScene(_center(vb))))
    y1, r1 = vb.viewRange()[1], vb2.viewRange()[1]
    assert (r1[1] - r1[0]) / (r0[1] - r0[0]) == pytest.approx((y1[1] - y1[0]) / (y0[1] - y0[0]))
    assert not vb2.mouseEnabled()[0] and vb2.mouseEnabled()[1]
