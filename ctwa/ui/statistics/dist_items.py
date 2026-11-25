"""Box, violin and bar drawing. Statistics are Plotly's (ctwa.stats.dist); on a log Y axis they are computed on
log10 of the positive values, exactly as Plotly does (it calculates on the axis' own scale)."""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen

from ctwa.stats.dist import HALF_WIDTH, BoxStats, box_stats, jitter_x, violin_shape
from ctwa.stats.specs import ChartSpec, Group
from ctwa.ui.statistics.geometry import mask_for_log, to_view

__all__ = ["BoxItem", "ViolinItem", "draw_box", "draw_violin", "draw_bar"]

FILL_ALPHA = 0.5
POINT_ALPHA = 0.8
LINE_PX = 2.0
BAR_WIDTH = 0.7
BAR_CAP = 0.12
PAD = 0.05


def _fill(color: str) -> QColor:
    c = QColor(color)
    c.setAlphaF(FILL_ALPHA)
    return c


def _pen(color: str, width: float = LINE_PX) -> QPen:
    p = pg.mkPen(color, width=width)
    p.setCosmetic(True)
    return p


class BoxItem(pg.GraphicsObject):
    """Box q1..q3 with median line and whiskers lo..hi (Plotly's whiskerwidth is 0, so no caps by default)."""

    def __init__(self, x: float, stats: BoxStats, color: str, cap: float = 0.0):
        super().__init__()
        self.x, self.stats, self.color, self.cap = x, stats, color, cap
        self.q1, self.med, self.q3 = stats.q1, stats.med, stats.q3
        self.lo, self.hi = stats.lo_whisker, stats.hi_whisker

    def boundingRect(self):
        return QRectF(self.x - HALF_WIDTH, self.lo, 2 * HALF_WIDTH, max(self.hi - self.lo, 1e-12)).adjusted(
            -0.02, 0, 0.02, 0)

    def paint(self, p, *args):
        p.setPen(_pen(self.color))
        p.setBrush(_fill(self.color))
        h = HALF_WIDTH
        p.drawRect(QRectF(self.x - h, self.q1, 2 * h, self.q3 - self.q1))
        p.drawLine(QPointF(self.x - h, self.med), QPointF(self.x + h, self.med))
        p.drawLine(QPointF(self.x, self.q1), QPointF(self.x, self.lo))
        p.drawLine(QPointF(self.x, self.q3), QPointF(self.x, self.hi))
        if self.cap > 0:
            c = h * self.cap
            p.drawLine(QPointF(self.x - c, self.lo), QPointF(self.x + c, self.lo))
            p.drawLine(QPointF(self.x - c, self.hi), QPointF(self.x + c, self.hi))


class ViolinItem(pg.GraphicsObject):
    """Closed outline of the KDE shape: right side bottom-to-top, left side back down."""

    def __init__(self, x: float, ts: List[float], half_widths: List[float], color: str):
        super().__init__()
        self.x, self.color = x, color
        right = [(x + w, t) for t, w in zip(ts, half_widths)]
        left = [(x - w, t) for t, w in zip(reversed(ts), reversed(half_widths))]
        self._pts = right + left
        self._ymin, self._ymax = min(ts), max(ts)

    def polygon_points(self) -> List[Tuple[float, float]]:
        return list(self._pts)

    def boundingRect(self):
        return QRectF(self.x - HALF_WIDTH, self._ymin, 2 * HALF_WIDTH, max(self._ymax - self._ymin, 1e-12)).adjusted(
            -0.02, 0, 0.02, 0)

    def paint(self, p, *args):
        path = QPainterPath()
        path.moveTo(*self._pts[0])
        for x, y in self._pts[1:]:
            path.lineTo(x, y)
        path.closeSubpath()
        p.setPen(_pen(self.color))
        p.setBrush(_fill(self.color))
        p.drawPath(path)


def _view_values(g: Group, ylog: bool) -> Tuple[np.ndarray, List[int]]:
    """Values of a group in view coordinates, plus their indices (non-positive ones dropped on a log axis)."""
    xs = np.zeros(len(g.values))
    _, ys, kept = mask_for_log(xs, g.values, False, ylog)
    return to_view(ys, ylog), kept


def _points(i: int, g: Group, vals: np.ndarray, kept: List[int], n_total: int, name: str) -> pg.ScatterPlotItem:
    jit = jitter_x(i, n_total)
    c = QColor(g.color)
    c.setAlphaF(POINT_ALPHA)
    item = pg.ScatterPlotItem(x=[jit[k] for k in kept], y=list(vals), size=6, symbol="o", pen=pg.mkPen(c),
                              brush=pg.mkBrush(c))
    item.setZValue(3)
    item.series_name = ""
    return item


def _finish(plot: pg.PlotItem, n: int, lo: Optional[float], hi: Optional[float]) -> None:
    vb = plot.getViewBox()
    vb.setXRange(-0.5, n - 0.5, padding=0)
    if lo is None or hi is None:
        vb.enableAutoRange(axis="y")
        return
    span = (hi - lo) or max(abs(hi), 1.0) * 0.1
    vb.setYRange(lo - PAD * span, hi + PAD * span, padding=0)


def _count(spec: ChartSpec) -> int:
    return len(spec.categories) or len(spec.groups) or len(spec.series)


def _draw_dist(plot: pg.PlotItem, spec: ChartSpec, violin: bool) -> List[pg.GraphicsObject]:
    items: List[pg.GraphicsObject] = []
    lo = hi = None
    for i, g in enumerate(spec.groups):
        vals, kept = _view_values(g, spec.ylog)
        if not len(vals):
            continue
        ext = [float(vals.min()), float(vals.max())]
        if violin:
            shape = violin_shape(list(vals))
            body = ViolinItem(i, shape.ts, shape.half_widths, g.color)
            ext += [shape.ts[0], shape.ts[-1]]
        else:
            stats = box_stats(list(vals))
            body = BoxItem(i, stats, g.color)
            ext += [stats.lo_whisker, stats.hi_whisker]
        plot.addItem(body)
        pts = _points(i, g, vals, kept, len(g.values), g.name)
        plot.addItem(pts)
        items += [body, pts]
        lo = min(ext + ([lo] if lo is not None else []))
        hi = max(ext + ([hi] if hi is not None else []))
    _finish(plot, _count(spec), lo, hi)
    return items


def draw_box(plot: pg.PlotItem, spec: ChartSpec) -> List[pg.GraphicsObject]:
    return _draw_dist(plot, spec, False)


def draw_violin(plot: pg.PlotItem, spec: ChartSpec) -> List[pg.GraphicsObject]:
    return _draw_dist(plot, spec, True)


def draw_bar(plot: pg.PlotItem, spec: ChartSpec) -> List[pg.GraphicsObject]:
    items: List[pg.GraphicsObject] = []
    ylog = spec.ylog
    pos = [s for s in spec.series if s.y and (not ylog or s.y[0] > 0)]
    base = 0.0
    if ylog and pos:
        base = float(np.floor(min(np.log10(s.y[0]) for s in pos)))
    lo, hi = base, base
    for s in spec.series:
        y = s.y[0]
        if ylog and not y > 0:
            continue
        x = s.x[0]
        top = float(np.log10(y)) if ylog else y
        err = (s.yerr[0] if s.yerr else 0.0) or 0.0
        bar = pg.BarGraphItem(x=[x], height=[top - base] if ylog else [top], y0=base if ylog else None,
                              width=BAR_WIDTH, brush=_fill(s.color), pen=_pen(s.color))
        bar.series_name, bar.series_group = s.name, s.legendgroup
        plot.addItem(bar)
        items.append(bar)
        hi = max(hi, top)
        lo = min(lo, top)
        if err > 0:
            if ylog:
                up = float(np.log10(y + err)) - top
                dn = top - (float(np.log10(y - err)) if y - err > 0 else base)
            else:
                up = dn = err
            eb = pg.ErrorBarItem(x=np.array([x]), y=np.array([top]), top=np.array([up]), bottom=np.array([dn]),
                                 beam=BAR_CAP, pen=_pen("#444444", 1.5))
            eb.series_name, eb.series_group = s.name, s.legendgroup
            plot.addItem(eb)
            items.append(eb)
            hi = max(hi, top + up)
            lo = min(lo, top - dn)
        tip = pg.ScatterPlotItem(x=[x], y=[top], size=14, symbol="s", pen=pg.mkPen(None), brush=pg.mkBrush(None),
                                 hoverable=True)
        tip.hover_texts = list(s.hover)
        tip.series_name, tip.series_group = s.name, s.legendgroup
        plot.addItem(tip)
        items.append(tip)
    _finish(plot, _count(spec), lo if items else None, hi if items else None)
    return items
