"""The two charts of the Compare page, drawn with pyqtgraph: the waveform overlay (OverlayChart) and the
one-dot-per-run metric chart (MetricChart)."""
from __future__ import annotations

import math
from typing import Any, List, Optional, Tuple

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ctwa import theme
from ctwa.ui.results.compare_logic import OverlayLine, OverlayOptions, OverlayRun, metric_text, run_colors

__all__ = ["OverlayChart", "MetricChart"]

_WHITE75 = QColor(255, 255, 255, 191)
_DASH = {"dot": Qt.DotLine, "dashdot": Qt.DashDotLine, "dash": Qt.DashLine, "solid": Qt.SolidLine}


def _pen(color: str, width: float, dash: str):
    p = pg.mkPen(color, width=width)
    p.setStyle(_DASH.get(dash, Qt.SolidLine))
    p.setCosmetic(True)
    return p


def _text(text: str, color: str, anchor: Tuple[float, float], fill=_WHITE75, px: int = 0):
    t = pg.TextItem(text, color=color, anchor=anchor, fill=fill)
    t.setFont(theme.ui_font(px or theme.TEXT_SMALL))
    return t


class OverlayChart(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._plot = pg.PlotWidget()
        theme.style_plot(self._plot)
        self._pi = self._plot.getPlotItem()
        self._vb = self._pi.vb
        self._legend = QLabel()
        self._legend.setWordWrap(True)
        self._legend.setTextFormat(Qt.RichText)
        theme.set_role(self._legend, "muted")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._plot, 1)
        lay.addWidget(self._legend)
        self._items: List[Any] = []
        self._curves: List[Tuple[str, str, str, List[float], List[float]]] = []
        self._lines: List[Tuple[OverlayLine, Any]] = []
        self._labels: List[Tuple[str, Any, float, float, Any]] = []   # (text, anchor-kind, x, y, item)
        self._boxes: List[Tuple[str, Any]] = []
        self._titles = ("", "")
        self._fixing = False
        self._vb.sigRangeChanged.connect(self._reposition)
        self.setMinimumHeight(420)

    # ---- inspection ----
    def curve_names(self) -> List[str]:
        return [c[0] for c in self._curves]

    def curve_styles(self) -> List[tuple]:
        return [(c[0], c[1], c[2]) for c in self._curves]

    def curve_data(self) -> List[Tuple[List[float], List[float]]]:
        return [(c[3], c[4]) for c in self._curves]

    def line_count(self) -> int:
        return len(self._lines)

    def label_texts(self) -> List[str]:
        return [t for t, _, _, _, _ in self._labels]

    def box_texts(self) -> List[str]:
        return [t for t, _ in self._boxes]

    def x_title(self) -> str:
        return self._titles[0]

    def y_title(self) -> str:
        return self._titles[1]

    # ---- drawing ----
    def _clear(self) -> None:
        for it in self._items:
            try:
                self._vb.removeItem(it)
            except (RuntimeError, ValueError):
                pass
        self._items, self._curves, self._lines, self._labels, self._boxes = [], [], [], [], []

    def set_runs(self, runs: List[Optional[OverlayRun]], opts: OverlayOptions,
                 boxes: Optional[List[Optional[str]]] = None) -> None:
        """Draw the runs (None: no stored waveform). `boxes[i]` is the value box of a run without one."""
        self._clear()
        x_title = ("Normalized time (0–1)" if opts.norm_time else
                   "Time from start (s)" if opts.align else "Time (s)")
        y_title = "Normalized power" if opts.norm_amp else "Power (mW)"
        self._titles = (x_title, y_title)
        self._pi.setLabel("bottom", x_title)
        self._pi.setLabel("left", y_title)
        legend = []
        for i, run in enumerate(runs):
            if run is None:
                continue
            for tr in run.traces:
                item = pg.PlotDataItem(tr.x, tr.y, pen=_pen(tr.color, 2.0, tr.dash), name=tr.name)
                self._pi.addItem(item)
                theme.fast_curve(item)   # after addItem: it needs the ViewBox
                self._items.append(item)
                self._curves.append((tr.name, tr.color, tr.dash, list(tr.x), list(tr.y)))
                mark = "━━" if tr.dash == "solid" else "╌╌"
                legend.append('<span style="color:%s">%s</span> %s' % (tr.color, mark, _esc(tr.name)))
            for ln in run.lines:
                self._add_line(ln)
        for i, run in enumerate(runs):
            text = run.box_text if run is not None else (boxes[i] if boxes and i < len(boxes) else None)
            if text:
                t = _text(text, run_colors(i)[0], (0, 0))
                self._vb.addItem(t, ignoreBounds=True)
                self._items.append(t)
                self._boxes.append((text, (i, t)))
        self._legend.setText("&nbsp;&nbsp;&nbsp;".join(legend))
        self._vb.autoRange()
        self._reposition()

    def _add_line(self, ln: OverlayLine) -> None:
        curve = pg.PlotCurveItem(pen=_pen(ln.color, 1.5, ln.dash))
        curve.setData([ln.x0, ln.x1], [ln.y0, ln.y1])
        self._vb.addItem(curve, ignoreBounds=True)
        self._items.append(curve)
        self._lines.append((ln, curve))
        if ln.label:
            paper = ln.yref == "paper"
            t = _text(ln.label, ln.color, (0.5, 1.0) if paper else (0, 0.5))
            self._vb.addItem(t, ignoreBounds=True)
            self._items.append(t)
            self._labels.append((ln.label, "paper" if paper else "data", ln.x1, 1.02 if paper else ln.y1, t))

    def _reposition(self, *_a) -> None:
        if self._fixing:
            return
        self._fixing = True
        try:
            (x_lo, x_hi), (y_lo, y_hi) = self._vb.viewRange()
            for ln, curve in self._lines:
                if ln.yref == "paper":
                    curve.setData([ln.x0, ln.x1], [y_lo + ln.y0 * (y_hi - y_lo), y_lo + ln.y1 * (y_hi - y_lo)])
            for _text_, kind, x, y, item in self._labels:
                item.setPos(x, y_lo + y * (y_hi - y_lo) if kind == "paper" else y)
            for _t, (i, item) in self._boxes:
                item.setPos(x_lo + 0.01 * (x_hi - x_lo), y_lo + (0.98 - i * 0.06) * (y_hi - y_lo))
        finally:
            self._fixing = False


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class MetricChart(QWidget):
    """One dot per run on a value axis; the value above the dot, the run label on the left, first run on top."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._plot = pg.PlotWidget()
        theme.style_plot(self._plot)
        self._pi = self._plot.getPlotItem()
        self._pi.invertY(True)
        self._pi.showGrid(x=True, y=False, alpha=0.15)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._plot)
        self._items: List[Any] = []
        self._values: List[Optional[float]] = []
        self._labels: List[str] = []
        self._texts: List[str] = []
        self._colors: List[str] = []
        self._title = ""
        self._height = 0
        self.set_values([], [], [], "")

    def dot_values(self) -> List[Optional[float]]:
        return list(self._values)

    def dot_labels(self) -> List[str]:
        return list(self._labels)

    def dot_colors(self) -> List[str]:
        return list(self._colors)

    def text_labels(self) -> List[str]:
        return list(self._texts)

    def chart_height(self) -> int:
        return self._height

    def title_text(self) -> str:
        return self._title

    def set_values(self, labels: List[str], values: List[Optional[float]], colors: List[str],
                   metric_label: str) -> None:
        for it in self._items:
            self._pi.removeItem(it)
        self._items = []
        n = len(labels)
        fin = lambda v: v is not None and isinstance(v, (int, float)) and math.isfinite(v)   # noqa: E731
        self._values = [v if fin(v) else None for v in values]
        self._labels, self._colors = list(labels), list(colors)
        self._texts = [metric_text(v) for v in values]
        self._title = "%s — comparison across analyses" % metric_label if metric_label else ""
        self._height = 120 + 70 * n
        self.setFixedHeight(self._height)
        self._pi.setTitle(self._title or None, color=theme.P.text_muted, size="%dpx" % theme.TEXT_SMALL)
        self._pi.setLabel("bottom", metric_label)
        self._pi.getAxis("left").setTicks([list(enumerate(labels))])
        pts = [(v, i) for i, v in enumerate(self._values) if v is not None]
        if pts:
            sc = pg.ScatterPlotItem(x=[p[0] for p in pts], y=[p[1] for p in pts], size=16,
                                    brush=[pg.mkBrush(colors[p[1]]) for p in pts],
                                    pen=pg.mkPen("#ffffff", width=1.5))
            self._pi.addItem(sc)
            self._items.append(sc)
        lo = min([p[0] for p in pts], default=0.0)
        hi = max([p[0] for p in pts], default=1.0)
        pad = (hi - lo) * 0.15 or abs(hi) * 0.1 or 1.0
        for i, v in enumerate(self._values):
            t = pg.TextItem(self._texts[i], color=theme.P.text, anchor=(0.5, 1.5))
            t.setFont(theme.ui_font(theme.TEXT_SMALL))
            self._pi.addItem(t, ignoreBounds=True)
            t.setPos(v if v is not None else (lo + hi) / 2, i)
            self._items.append(t)
        self._pi.setXRange(lo - pad, hi + pad, padding=0)
        self._pi.setYRange(-0.6, max(n - 1, 0) + 0.6, padding=0)
