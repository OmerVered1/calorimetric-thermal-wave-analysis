"""Correlation heatmap: Plotly's RdBu on [-1, 1], white 2 px gaps, a text per cell, rotated x labels, colour bar."""
from __future__ import annotations

import math
from typing import List, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QGraphicsTextItem

from ctwa import theme
from ctwa.stats.specs import ChartSpec

__all__ = ["RDBU_STOPS", "heat_colormap", "heat_lut", "draw_heatmap", "TICK_ANGLE"]

RDBU_STOPS = [(0.0, (5, 10, 172)), (0.35, (106, 137, 247)), (0.5, (190, 190, 190)), (0.6, (220, 170, 132)),
              (0.7, (230, 145, 90)), (1.0, (178, 10, 28))]
TICK_ANGLE = -40
GAP_PX = 2
NAN_FILL = "#f3f4f6"


def heat_colormap() -> pg.ColorMap:
    return pg.ColorMap([p for p, _ in RDBU_STOPS], [c for _, c in RDBU_STOPS])


def heat_lut(n: int = 513) -> np.ndarray:
    """RdBu over z in [-1, 1]; an odd ``n`` puts z = 0 exactly on the grey middle entry."""
    return heat_colormap().getLookupTable(0.0, 1.0, n, alpha=False)


def _text_color(v: float) -> str:
    return "#ffffff" if abs(v) > 0.6 else theme.P.text


def draw_heatmap(view, spec: ChartSpec) -> None:
    heat = spec.heat
    plot: pg.PlotItem = view.plot_item()
    vb = plot.getViewBox()
    if heat is None:
        return
    labels = heat.labels
    n = len(labels)
    m = np.array(heat.matrix, dtype=float).reshape(n, n)
    nan = ~np.isfinite(m)
    img = pg.ImageItem(np.where(nan, 0.0, m).T, levels=(-1, 1))
    img.setLookupTable(heat_lut())
    img.setZValue(0)
    view.add_item(img)
    view._heat_image = img

    # cells: NaN ones get a flat fill; white gaps between all
    for r, c in zip(*np.nonzero(nan)):
        rect = pg.QtWidgets.QGraphicsRectItem(float(c), float(r), 1.0, 1.0)
        rect.setBrush(pg.mkBrush(NAN_FILL))
        rect.setPen(pg.mkPen(None))
        rect.setZValue(1)
        plot.addItem(rect, ignoreBounds=True)
        view._added.append(rect)
    gap = pg.mkPen("#ffffff", width=GAP_PX)
    for k in range(n + 1):
        for angle in (0, 90):
            ln = pg.InfiniteLine(pos=k, angle=angle, pen=gap)
            ln.setZValue(2)
            plot.addItem(ln, ignoreBounds=True)
            view._added.append(ln)
    for r in range(n):
        for c in range(n):
            t = pg.TextItem(heat.text[r][c], color=_text_color(m[r, c] if not nan[r, c] else 0.0), anchor=(0.5, 0.5))
            t.setFont(theme.numeric_font(theme.TEXT_SMALL))
            t.setPos(c + 0.5, r + 0.5)
            t.setZValue(3)
            plot.addItem(t, ignoreBounds=True)
            view._added.append(t)

    # axes: rows downwards, no zoom, tick text at the cell centres
    vb.invertY(True)
    vb.setMouseEnabled(False, False)
    vb.setXRange(0, n, padding=0)
    vb.setYRange(0, n, padding=0)
    left, bottom = plot.getAxis("left"), plot.getAxis("bottom")
    left.setTicks([[(i + 0.5, lab) for i, lab in enumerate(labels)]])
    bottom.setTicks([[(i + 0.5, lab) for i, lab in enumerate(labels)]])
    for ax in (left, bottom, plot.getAxis("top"), plot.getAxis("right")):
        ax.setGrid(0)
    bottom.setStyle(showValues=False)
    bottom.setHeight(76)
    _rotated_labels(view, bottom, vb, labels)

    # colour bar (Plotly's "r" bar)
    bar = pg.ColorBarItem(values=(-1, 1), colorMap=heat_colormap(), interactive=False, label="r", width=14)
    bar.setImageItem(img, insert_in=plot)
    img.setLookupTable(heat_lut())

    def cleanup() -> None:
        plot.layout.removeItem(bar)
        bar.setParentItem(None)
        if bar.scene() is not None:
            bar.scene().removeItem(bar)
        plot.layout.setColumnFixedWidth(4, 0)
        view._heat_hit = view._heat_hover = None

    view._extra_cleanup.append(cleanup)

    def cell_at(scene_pos) -> Optional[Tuple[int, int]]:
        p = vb.mapSceneToView(scene_pos)
        c, r = math.floor(p.x()), math.floor(p.y())
        return (r, c) if 0 <= r < n and 0 <= c < n else None

    def hit(scene_pos) -> Optional[Tuple[str, str]]:
        rc = cell_at(scene_pos)
        return (labels[rc[0]], labels[rc[1]]) if rc else None

    def hover(scene_pos) -> Optional[str]:
        rc = cell_at(scene_pos)
        if not rc or not vb.sceneBoundingRect().contains(scene_pos):
            return None
        return "%s × %s\nr = %s" % (labels[rc[0]], labels[rc[1]], heat.text[rc[0]][rc[1]])

    view._heat_hit, view._heat_hover = hit, hover


def _rotated_labels(view, axis, vb, labels: List[str]) -> None:
    items = []
    font = theme.ui_font(theme.TEXT_SMALL)
    for lab in labels:
        it = QGraphicsTextItem(lab, axis)
        it.setFont(font)
        it.setDefaultTextColor(pg.mkColor(theme.P.text_muted))
        w, h = it.boundingRect().width(), it.boundingRect().height()
        it.setTransformOriginPoint(w, h / 2)
        it.setRotation(TICK_ANGLE)
        items.append((it, w, h))

    def place(*_):
        n = len(items)
        for i, (it, w, h) in enumerate(items):
            pt = axis.mapFromScene(vb.mapViewToScene(QPointF(i + 0.5, n)))
            it.setPos(pt.x() - w, pt.y() + 10 - h / 2)

    view.add_range_hook(place)
    vb.sigResized.connect(place)
    scene_ref = {"s": None}

    def drop() -> None:
        try:
            vb.sigResized.disconnect(place)
        except (TypeError, RuntimeError):
            pass
        for it, _, _ in items:
            it.setParentItem(None)
            if it.scene() is not None:
                it.scene().removeItem(it)

    view._extra_cleanup.append(drop)
    place()
