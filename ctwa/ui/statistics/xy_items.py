"""XY series: lines, markers, error bars, raw-to-calibrated connector pairs."""
from __future__ import annotations

from typing import List, Optional

import numpy as np
import pyqtgraph as pg

from ctwa.stats.specs import ChartSpec, Series
from ctwa.ui.statistics.geometry import mask_for_log, qt_dash, to_view

__all__ = ["draw_xy"]

CAP_PX = 5


def _line_pen(s: Series):
    return pg.mkPen(s.color, width=s.width, style=qt_dash(s.dash))


def _valid(vals: np.ndarray, log: bool) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        return np.isfinite(vals) & (vals > 0 if log else True)


def _draw_line(view, s: Series, spec: ChartSpec) -> None:
    x = np.asarray(s.x, dtype=float)
    y = np.asarray(s.y, dtype=float)
    ok = _valid(x, spec.xlog) & _valid(y, spec.ylog)
    if s.segments:
        # triples (a, b, NaN): keep the pairs whose two ends can both be drawn, joined with connect="pairs"
        xs: List[float] = []
        ys: List[float] = []
        i = 0
        while i + 1 < len(x):
            if ok[i] and ok[i + 1]:
                xs += [x[i], x[i + 1]]
                ys += [y[i], y[i + 1]]
            i += 3
        vx, vy = to_view(xs, spec.xlog), to_view(ys, spec.ylog)
        connect = "pairs"
    else:
        vx = to_view(np.where(ok, x, np.nan), spec.xlog)
        vy = to_view(np.where(ok, y, np.nan), spec.ylog)
        connect = "finite"
    item = pg.PlotDataItem(x=vx, y=vy, pen=_line_pen(s), connect=connect)
    item.setOpacity(s.opacity)
    item.setZValue(2)
    view.add_item(item, s)


def _draw_error_bars(view, s: Series, spec: ChartSpec) -> None:
    xs, ys, kept = mask_for_log(s.x, s.y, spec.xlog, spec.ylog)
    err = np.asarray([s.yerr[i] for i in kept], dtype=float)
    pos = err > 0
    if not pos.any():
        return
    xs, ys, err = xs[pos], ys[pos], err[pos]
    vx, vy = to_view(xs, spec.xlog), to_view(ys, spec.ylog)
    if spec.ylog:
        top = to_view(ys + err, True) - vy
        low = ys - err
        bottom = np.where(low > 0, vy - to_view(np.where(low > 0, low, 1.0), True), 0.0)
    else:
        top = bottom = err
    eb = pg.ErrorBarItem(x=vx, y=vy, top=top, bottom=bottom, beam=0, pen=pg.mkPen(s.color, width=1.2))
    eb.setOpacity(s.opacity)
    eb.setZValue(1)
    view.add_item(eb, s)

    def rescale(*_):
        vb = view.plot_item().getViewBox()
        w = vb.width()
        if w > 0:
            x0, x1 = vb.viewRange()[0]
            eb.setData(beam=CAP_PX * (x1 - x0) / w)

    view.add_range_hook(rescale)
    vb = view.plot_item().getViewBox()
    vb.sigResized.connect(rescale)
    view._extra_cleanup.append(lambda: _disconnect(vb, rescale))
    rescale()


def _disconnect(vb, fn) -> None:
    try:
        vb.sigResized.disconnect(fn)
    except (TypeError, RuntimeError):
        pass


def draw_xy(view, spec: ChartSpec) -> None:
    for s in spec.series:
        if "lines" in s.mode or s.segments:
            _draw_line(view, s, spec)
        if "markers" in s.mode and not s.segments:
            view.add_markers(s, spec)
        if s.yerr and not s.segments:
            _draw_error_bars(view, s, spec)
