"""Draws a saved analysis plot (Plotly JSON, a base64 image, or the alpha bar fallback) with pyqtgraph.

FigureView.show_graph never raises: a stored figure that cannot be drawn falls back to the bars."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QFont, QFontDatabase, QPixmap
from PySide6.QtWidgets import QLabel, QStackedLayout, QVBoxLayout, QWidget

from ctwa import theme
from ctwa.analysis.jsmath import js_to_precision
from ctwa.ui.results.figure_model import (Annotation, Shape, StoredFigure, StoredImage, Trace, bar_values,
                                          parse_color, parse_graph)

__all__ = ["FigureView", "FigureHandles", "draw_stored_figure"]

_DASH = {"solid": Qt.SolidLine, "dash": Qt.DashLine, "dot": Qt.DotLine, "dashdot": Qt.DashDotLine}


def _pen(color: str, width: float, dash: str):
    p = pg.mkPen(parse_color(color), width=max(0.5, float(width)))
    p.setStyle(_DASH.get(dash, Qt.SolidLine))
    p.setCosmetic(True)
    return p


@dataclass
class _PaperLine:
    shape: Shape
    curve: Any
    view: Any   # the ViewBox the curve lives in


@dataclass
class _PaperText:
    ann: Annotation
    item: Any


@dataclass
class FigureHandles:
    """Everything draw_stored_figure added, so the view can remove it again."""
    curves: List[Any] = field(default_factory=list)       # (trace, PlotDataItem)
    curves2: List[Any] = field(default_factory=list)
    shapes: List[Tuple[Shape, Any]] = field(default_factory=list)
    paper_lines: List[_PaperLine] = field(default_factory=list)
    texts: List[Tuple[Annotation, Any]] = field(default_factory=list)
    paper_texts: List[_PaperText] = field(default_factory=list)
    legend: Any = None
    view2: Any = None
    uses_y2: bool = False


def _mono_font(px: float) -> QFont:
    f = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    f.setStyleHint(QFont.Monospace)
    f.setPixelSize(max(6, int(round(px))))
    return f


def _curve(tr: Trace):
    pen = _pen(tr.color, tr.width, tr.dash) if "lines" in tr.mode else None
    kw: Dict[str, Any] = {}
    if "markers" in tr.mode:
        kw.update(symbol="o", symbolSize=6, symbolBrush=parse_color(tr.color), symbolPen=None)
    return pg.PlotDataItem(tr.x, tr.y, pen=pen, name=tr.name, connect="finite", **kw)


def draw_stored_figure(plot_item, fig: StoredFigure, view2) -> FigureHandles:
    """Add the figure's items to plot_item (and view2, the right-axis ViewBox)."""
    h = FigureHandles(view2=view2)
    vb = plot_item.vb
    for tr in fig.traces:
        c = _curve(tr)
        if tr.yaxis == "y2":
            view2.addItem(c)
            h.curves2.append(c)
            h.uses_y2 = True
        else:
            vb.addItem(c)
            h.curves.append(c)
    for sh in fig.shapes:
        target = view2 if sh.yref == "y2" else vb
        if sh.yref == "y2":
            h.uses_y2 = True
        curve = pg.PlotCurveItem([sh.x0, sh.x1], [sh.y0, sh.y1], pen=_pen(sh.color, sh.width, sh.dash))
        target.addItem(curve, ignoreBounds=True)   # Plotly does not autorange to shapes either
        h.shapes.append((sh, curve))
        if sh.yref == "paper" or sh.xref == "paper":
            h.paper_lines.append(_PaperLine(sh, curve, target))
    for an in fig.annotations:
        anchor = {"left": (0.0, 0.5), "right": (1.0, 0.5)}.get(an.xanchor, (0.5, 0.5))
        fill = pg.mkBrush(*an.bgcolor) if an.bgcolor is not None else None
        item = pg.TextItem(an.text, color=parse_color(an.color), anchor=anchor, fill=fill)
        item.setFont(_mono_font(an.size) if an.mono else theme.ui_font(int(round(an.size))))
        if an.xref == "paper" or an.yref == "paper":
            plot_item.scene().addItem(item)
            item.setZValue(100)
            h.paper_texts.append(_PaperText(an, item))
        else:
            target = view2 if an.yref == "y2" else vb
            if an.yref == "y2":
                h.uses_y2 = True
            target.addItem(item, ignoreBounds=True)
            item.setPos(an.x, an.y)
        h.texts.append((an, item))
    if fig.traces:
        n = len(fig.traces)
        legend = pg.LegendItem(offset=(10, 10), colCount=n if fig.horizontal_legend else 1,
                               labelTextSize="%dpx" % theme.TEXT_SMALL, brush=pg.mkBrush(255, 255, 255, 200))
        legend.setParentItem(vb)
        for tr, c in zip(fig.traces, _in_trace_order(fig, h)):
            legend.addItem(c, tr.name)
        h.legend = legend
    return h


def _in_trace_order(fig: StoredFigure, h: FigureHandles) -> List[Any]:
    a, b = iter(h.curves), iter(h.curves2)
    return [next(b) if t.yaxis == "y2" else next(a) for t in fig.traces]


class FigureView(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._mode = "empty"
        self._note = ""
        self._handles: Optional[FigureHandles] = None
        self._bar_items: List[Any] = []
        self._bar_labels: List[str] = []
        self._line_items: List[tuple] = []
        self._titles: tuple = ("", "", "")
        self._pixmap: Optional[QPixmap] = None
        self._fixing = False

        self._note_label = QLabel()
        self._note_label.setWordWrap(True)
        theme.set_role(self._note_label, "caption")
        self._note_label.hide()
        self._plot = pg.PlotWidget()
        theme.style_plot(self._plot)
        self._pi = self._plot.getPlotItem()
        self._view2 = pg.ViewBox()
        self._pi.showAxis("right")
        self._pi.scene().addItem(self._view2)
        self._pi.getAxis("right").linkToView(self._view2)
        self._view2.setXLink(self._pi.vb)
        self._pi.hideAxis("right")
        self._pi.vb.sigResized.connect(self._on_resized)
        self._pi.vb.sigRangeChanged.connect(self._reposition)
        self._image = QLabel()
        self._image.setAlignment(Qt.AlignCenter)
        self._image.setMinimumSize(50, 50)
        self._message = QLabel()
        self._message.setAlignment(Qt.AlignCenter)
        theme.set_role(self._message, "caption")
        self._stack = QStackedLayout()
        for w in (self._plot, self._image, self._message):
            self._stack.addWidget(w)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._note_label)
        lay.addLayout(self._stack, 1)

    # ---- inspection ----
    def mode(self) -> str:
        return self._mode

    def note(self) -> str:
        return self._note

    def curve_count(self, second_axis: bool = False) -> int:
        h = self._handles
        if h is None:
            return 0
        return len(h.curves2 if second_axis else h.curves)

    def line_items(self) -> List[tuple]:
        return list(self._line_items)

    def annotation_texts(self) -> List[str]:
        return [a.text for a, _ in self._handles.texts] if self._handles else []

    def annotation_items(self) -> List[Any]:
        return [i for _, i in self._handles.texts] if self._handles else []

    def legend_labels(self) -> List[str]:
        h = self._handles
        if h is None or h.legend is None:
            return []
        return [label.text for _, label in h.legend.items]

    def legend_item(self):
        return self._handles.legend if self._handles else None

    def paper_lines(self) -> List[_PaperLine]:
        return list(self._handles.paper_lines) if self._handles else []

    def bar_labels(self) -> List[str]:
        return list(self._bar_labels)

    def axis_titles(self) -> tuple:
        return self._titles

    def plot_item(self):
        return self._pi

    def image_label(self) -> QLabel:
        return self._image

    # ---- public ----
    def clear(self) -> None:
        self._remove_items()
        self._set_mode("empty", "")
        self._message.setText("")
        self._stack.setCurrentWidget(self._message)

    def show_loading(self) -> None:
        self._remove_items()
        self._set_mode("loading", "")
        self._message.setText("Loading…")
        self._stack.setCurrentWidget(self._message)

    def show_graph_failed(self, row: Dict[str, Any]) -> None:
        """The stored plot could not be fetched: the α bars with a note."""
        self._remove_items()
        self._show_bars(row, "Could not load the graph")

    def show_graph(self, raw: Optional[str], row: Dict[str, Any]) -> None:
        self._remove_items()
        try:
            parsed = parse_graph(raw)
            if isinstance(parsed, StoredFigure):
                self._draw_figure(parsed)
                return
            if isinstance(parsed, StoredImage):
                if self._draw_image(parsed):
                    return
        except Exception:
            self._remove_items()
            self._show_bars(row, "Could not draw the stored graph")
            return
        self._show_bars(row, "")

    # ---- drawing ----
    def _set_mode(self, mode: str, note: str) -> None:
        self._mode, self._note = mode, note
        self._note_label.setText(note)
        self._note_label.setVisible(bool(note))

    def _remove_items(self) -> None:
        h = self._handles
        if h is not None:
            if h.legend is not None:
                if h.legend.scene() is not None:
                    h.legend.scene().removeItem(h.legend)
            for pt in h.paper_texts:
                if pt.item.scene() is not None:
                    pt.item.scene().removeItem(pt.item)
        self._handles = None
        self._pi.vb.clear()
        self._view2.clear()
        for it in self._bar_items:
            if it.scene() is not None:
                it.scene().removeItem(it)
        self._bar_items = []
        self._bar_labels = []
        self._line_items = []
        self._titles = ("", "", "")
        self._pixmap = None
        self._image.clear()
        self._pi.hideAxis("right")
        self._pi.getAxis("bottom").setTicks(None)
        self._pi.setTitle(None)
        for side in ("left", "bottom", "right"):
            self._pi.setLabel(side, "")
        self._pi.enableAutoRange()

    def _draw_figure(self, fig: StoredFigure) -> None:
        h = draw_stored_figure(self._pi, fig, self._view2)
        self._handles = h
        self._line_items = [(s.x0, s.y0, s.x1, s.y1, s.dash, s.yref if s.yref in ("y2", "paper") else "y")
                            for s, _ in h.shapes]
        if h.uses_y2:
            self._pi.showAxis("right")
        self._pi.setTitle(fig.title or None, color=theme.P.text_muted, size="%dpx" % theme.TEXT_SMALL)
        self._pi.setLabel("bottom", fig.x_title)
        self._pi.setLabel("left", fig.y_title)
        if h.uses_y2:
            self._pi.getAxis("right").setLabel(fig.y2_title)
        self._titles = (fig.x_title, fig.y_title, fig.y2_title)
        note = "Not drawn: " + ", ".join(dict.fromkeys(fig.skipped)) if fig.skipped else ""
        self._set_mode("figure", note)
        self._stack.setCurrentWidget(self._plot)
        self._on_resized()
        self._pi.vb.autoRange()
        self._view2.autoRange()
        self._reposition()

    def _draw_image(self, img: StoredImage) -> bool:
        pm = QPixmap()
        if not pm.loadFromData(img.data) or pm.isNull():
            return False
        self._pixmap = pm
        self._set_mode("image", "")
        self._stack.setCurrentWidget(self._image)
        self._fit_image()
        return True

    def _fit_image(self) -> None:
        if self._pixmap is not None:
            self._image.setPixmap(self._pixmap.scaled(self._image.size(), Qt.KeepAspectRatio,
                                                      Qt.SmoothTransformation))

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if self._mode == "image":
            self._fit_image()

    def _show_bars(self, row: Dict[str, Any], note: str) -> None:
        bars = bar_values(row)
        if not bars:
            self._set_mode("empty", "No stored graph")
            self._message.setText("No stored graph")
            self._stack.setCurrentWidget(self._message)
            return
        n = len(bars)
        vals = [v for _, v, _ in bars]
        bg = pg.BarGraphItem(x=list(range(n)), height=vals, width=0.6, brushes=[parse_color(c) for _, _, c in bars])
        self._pi.vb.addItem(bg)
        self._bar_items.append(bg)
        top = max(vals)
        for i, v in enumerate(vals):
            t = pg.TextItem(js_to_precision(v, 4), color=theme.P.text, anchor=(0.5, 1.0))
            t.setFont(theme.ui_font(theme.TEXT_SMALL))
            self._pi.vb.addItem(t, ignoreBounds=True)
            t.setPos(i, v)
            self._bar_items.append(t)
        self._bar_labels = [lb for lb, _, _ in bars]
        self._pi.getAxis("bottom").setTicks([list(enumerate(self._bar_labels))])
        self._pi.setTitle("Thermal Diffusivity α", color=theme.P.text_muted, size="%dpx" % theme.TEXT_SMALL)
        self._pi.setLabel("left", "α (mm²/s)")
        self._pi.setYRange(0, top * 1.15, padding=0)
        self._pi.setXRange(-0.7, n - 0.3, padding=0)
        self._titles = ("", "α (mm²/s)", "")
        self._set_mode("bars", note)
        self._stack.setCurrentWidget(self._plot)

    # ---- layout of the second axis and paper items ----
    def _on_resized(self) -> None:
        self._view2.setGeometry(self._pi.vb.sceneBoundingRect())
        self._view2.linkedViewChanged(self._pi.vb, self._view2.XAxis)
        self._reposition()

    def _reposition(self, *_a) -> None:
        h = self._handles
        if h is None or self._fixing or (not h.paper_lines and not h.paper_texts):
            return
        self._fixing = True
        try:
            (x_lo, x_hi), (y_lo, y_hi) = self._pi.vb.viewRange()
            for pl in h.paper_lines:
                s = pl.shape
                if pl.view is self._view2:
                    (_, _), (v_lo, v_hi) = self._view2.viewRange()
                else:
                    v_lo, v_hi = y_lo, y_hi
                xs = [x_lo + v * (x_hi - x_lo) if s.xref == "paper" else v for v in (s.x0, s.x1)]
                ys = [v_lo + v * (v_hi - v_lo) if s.yref == "paper" else v for v in (s.y0, s.y1)]
                pl.curve.setData(xs, ys)
            rect = self._pi.vb.sceneBoundingRect()
            for pt in h.paper_texts:
                a = pt.ann
                x = (rect.left() + a.x * rect.width() if a.xref == "paper"
                     else self._pi.vb.mapViewToScene(QPointF(a.x, 0)).x())
                if a.yref == "paper":
                    y = rect.bottom() - a.y * rect.height()
                else:
                    vb = self._view2 if a.yref == "y2" else self._pi.vb
                    y = vb.mapViewToScene(QPointF(0, a.y)).y()
                pt.item.setPos(x, y)
        finally:
            self._fixing = False
