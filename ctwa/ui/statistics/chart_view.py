"""ChartView: draws any ChartSpec with pyqtgraph, with hover, click, lasso/box selection, legend bar and export."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QCursor, QPen, QPolygonF
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QGraphicsPolygonItem, QHBoxLayout, QPushButton, QToolTip,
                               QVBoxLayout, QWidget)

from ctwa import theme
from ctwa.stats.specs import ChartSpec, RefLine, Series
from ctwa.ui.statistics.geometry import (log_ticks, mask_for_log, points_in_polygon, qt_dash, slugify, to_view, view_value)
from ctwa.ui.statistics.legend_bar import LegendBar

__all__ = ["ChartView", "mask_for_log", "points_in_polygon", "slugify"]

GRID = "#eceff3"
AXIS_LINE = "#cfd5dd"
TITLE_PX = 15


class _Marker:
    """One drawn scatter item with what selection needs: view coordinates, ids and its series."""

    def __init__(self, item, series: str, group: Optional[str], xs: np.ndarray, ys: np.ndarray, ids: List[Optional[int]]):
        self.item, self.series, self.group, self.xs, self.ys, self.ids = item, series, group, xs, ys, ids
        self.visible = True


class _SelectViewBox(pg.ViewBox):
    """ViewBox whose left drag draws a lasso / box in the lasso and box tools and pans otherwise."""

    def __init__(self, owner: "ChartView"):
        super().__init__()
        self._owner = owner
        self._pts: List[Tuple[float, float]] = []
        self._poly: Optional[QGraphicsPolygonItem] = None

    def _show_poly(self, pts: List[Tuple[float, float]]) -> None:
        if self._poly is None:
            self._poly = QGraphicsPolygonItem()
            self._poly.setPen(pg.mkPen(theme.P.accent_strong, width=1.5, style=Qt.DashLine))
            c = QColor(theme.P.accent)
            c.setAlpha(60)
            self._poly.setBrush(QBrush(c))
            self.addItem(self._poly, ignoreBounds=True)
        self._poly.setPolygon(QPolygonF([QPointF(x, y) for x, y in pts]))

    def _drop_poly(self) -> None:
        if self._poly is not None:
            self.removeItem(self._poly)
            self._poly = None

    def mouseDragEvent(self, ev, axis=None):
        tool = self._owner._tool
        if tool in ("lasso", "box") and ev.button() == Qt.LeftButton:
            ev.accept()
            cur = self.mapSceneToView(ev.scenePos())
            if ev.isStart():
                p0 = self.mapSceneToView(ev.buttonDownScenePos())
                self._pts = [(p0.x(), p0.y())]
            if tool == "lasso":
                self._pts.append((cur.x(), cur.y()))
                shape = list(self._pts)
            else:
                x0, y0 = self._pts[0]
                shape = [(x0, y0), (cur.x(), y0), (cur.x(), cur.y()), (x0, cur.y())]
            self._show_poly(shape)
            if ev.isFinish():
                self._drop_poly()
                self._pts = []
                self._owner.select_polygon(shape)
        else:
            super().mouseDragEvent(ev, axis)

    def mouseClickEvent(self, ev):
        if self._owner._tool in ("lasso", "box") and ev.button() == Qt.LeftButton:
            ev.accept()
            self._owner.clear_selection()
        else:
            super().mouseClickEvent(ev)


class ChartView(QWidget):
    point_clicked = Signal(int)
    selection_made = Signal(list)
    selection_cleared = Signal()
    cell_clicked = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._spec: Optional[ChartSpec] = None
        self._tool = "pan"
        self._markers: List[_Marker] = []
        self._tracked: List[Tuple[Any, str, Optional[str]]] = []      # (item, series name, legendgroup)
        self._added: List[Any] = []
        self._selected: List[int] = []
        self._ref: List[Tuple[pg.InfiniteLine, pg.TextItem]] = []
        self._home: Optional[Tuple[List[float], List[float]]] = None
        self._extra_cleanup: List[Any] = []
        self._ring: Optional[pg.ScatterPlotItem] = None

        self._buttons: Dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        seg = []
        for key, text in (("pan", "Pan"), ("lasso", "Lasso"), ("box", "Box select")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setChecked(key == "pan")
            group.addButton(b)
            b.clicked.connect(lambda _=False, k=key: self.set_tool(k))
            self._buttons[key] = b
            seg.append(b)
        reset = QPushButton("Reset view")
        reset.clicked.connect(self.reset_view)
        png = QPushButton("PNG")
        png.clicked.connect(lambda: self._export_dialog("png"))
        svg = QPushButton("SVG")
        svg.clicked.connect(lambda: self._export_dialog("svg"))
        for b in (reset, png, svg):
            theme.set_role(b, "quiet")
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.addWidget(theme.segmented(*seg))
        bar.addWidget(reset)
        bar.addStretch(1)
        bar.addWidget(png)
        bar.addWidget(svg)

        self._vb = _SelectViewBox(self)
        self._pw = pg.PlotWidget(viewBox=self._vb)
        self._pw.setBackground(theme.P.raised)
        self._plot: pg.PlotItem = self._pw.getPlotItem()
        self._plot.hideButtons()
        self._style_frame()
        self._legend = LegendBar()
        self._legend.toggled.connect(lambda *_: self._apply_visibility())
        self._legend.isolated.connect(lambda *_: self._apply_visibility())

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addLayout(bar)
        lay.addWidget(self._pw, 1)
        lay.addWidget(self._legend)
        self._pw.scene().sigMouseClicked.connect(self._on_scene_click)
        self._pw.scene().sigMouseMoved.connect(self._on_scene_move)
        self._plot.getViewBox().sigRangeChanged.connect(self._on_range_changed)

    # ------------------------------------------------------------------ accessors
    def plot_item(self) -> pg.PlotItem:
        return self._plot

    def plot_widget(self) -> pg.PlotWidget:
        return self._pw

    def legend_bar(self) -> LegendBar:
        return self._legend

    def spec(self) -> Optional[ChartSpec]:
        return self._spec

    def scatter_items(self) -> List[pg.ScatterPlotItem]:
        return [m.item for m in self._markers]

    def ref_line_items(self) -> List[Tuple[pg.InfiniteLine, pg.TextItem]]:
        return list(self._ref)

    def selected_ids(self) -> List[int]:
        return list(self._selected)

    def tool(self) -> str:
        return self._tool

    def series_visible(self, name: str) -> bool:
        hidden = self._hidden_sets()
        for _, n, g in self._tracked:
            if n == name:
                return not self._is_hidden(n, g, *hidden)
        return True

    # ------------------------------------------------------------------ frame and axes
    def _style_frame(self) -> None:
        p = self._plot
        for name in ("left", "bottom", "right", "top"):
            ax = p.getAxis(name)
            theme.style_axis(ax)
            ax.setPen(pg.mkPen(AXIS_LINE))
            ax.setZValue(1)
        for name in ("top", "right"):
            p.showAxis(name)
            p.getAxis(name).setStyle(showValues=False)
            p.getAxis(name).setLabel(None)
        p.showGrid(x=True, y=True, alpha=0.4)
        for name in ("left", "bottom"):
            p.getAxis(name).setGrid(102)

    def _reset_axes(self) -> None:
        p = self._plot
        for name in ("left", "bottom", "right", "top"):
            ax = p.getAxis(name)
            ax.setLogMode(False)
            ax.setTicks(None)
        b = p.getAxis("bottom")
        b.setStyle(showValues=True)
        b.setHeight(None)
        b.setStyle(tickLength=-5)
        p.getViewBox().invertY(False)
        p.getViewBox().setMouseEnabled(True, True)
        p.getViewBox().enableAutoRange()
        for name in ("left", "bottom"):
            p.getAxis(name).setGrid(102)

    def _label(self, axis: str, text: str) -> None:
        self._plot.setLabel(axis, text, color=theme.P.text_muted, **{"font-size": "%dpx" % theme.TEXT_AXIS})

    def set_categories(self, ticks: List[Tuple[str, str]]) -> None:
        """Bottom ticks at 0..n-1 with the spec's two-line texts."""
        self._plot.getAxis("bottom").setTicks([[(i, t[1]) for i, t in enumerate(ticks)]])
        self._plot.getAxis("bottom").setGrid(0)          # no vertical grid between categories

    def add_ref_lines(self, ref_lines: List[RefLine], ylog: bool = False) -> None:
        for r in ref_lines:
            if ylog and not r.y > 0:
                continue
            pos = view_value(r.y, ylog)
            pen = pg.mkPen(r.color, width=r.width, style=qt_dash(r.dash))
            line = pg.InfiniteLine(pos=pos, angle=0, pen=pen)
            text = pg.TextItem(r.label, color=r.color, anchor=(1, 1))
            text.setFont(theme.ui_font(theme.TEXT_SMALL))
            self._plot.addItem(line, ignoreBounds=True)
            self._plot.addItem(text, ignoreBounds=True)
            self._added += [line, text]
            self._ref.append((line, text))
        self._place_ref_labels()

    def _place_ref_labels(self) -> None:
        (x0, x1), _ = self._plot.getViewBox().viewRange()
        for line, text in self._ref:
            text.setPos(x1, line.value())

    def _on_range_changed(self, *_):
        self._place_ref_labels()
        for fn in list(self._extra_cleanup_range()):
            fn()

    def _extra_cleanup_range(self):
        return getattr(self, "_range_hooks", [])

    def add_range_hook(self, fn) -> None:
        if not hasattr(self, "_range_hooks"):
            self._range_hooks = []
        self._range_hooks.append(fn)

    # ------------------------------------------------------------------ spec -> items
    def clear(self) -> None:
        self._plot.clear()
        for fn in self._extra_cleanup:
            try:
                fn()
            except Exception:
                pass
        self._extra_cleanup = []
        self._range_hooks = []
        self._markers, self._tracked, self._added, self._ref = [], [], [], []
        self._ring = None
        self._home = None

    def set_spec(self, spec: Optional[ChartSpec]) -> None:
        had = bool(self._selected)
        self._selected = []
        self.clear()
        self._spec = spec
        self._legend.set_entries([])
        self._reset_axes()
        if had:
            self.selection_cleared.emit()
        if spec is None:
            self._plot.setTitle(None)
            return
        self._plot.setTitle(spec.title, color=theme.P.text, size="%dpx" % TITLE_PX, bold=True)
        is_heat = spec.kind == "heatmap"
        self._label("bottom", "" if is_heat else spec.xlabel)
        self._label("left", "" if is_heat else spec.ylabel)
        ax = self._plot.getAxis
        ax("bottom").setLogMode(x=spec.xlog and spec.kind == "xy", y=False)
        ax("left").setLogMode(x=False, y=spec.ylog)
        ax("top").setLogMode(x=spec.xlog and spec.kind == "xy", y=False)
        ax("right").setLogMode(x=False, y=spec.ylog)
        if spec.kind == "xy":
            self._draw_xy(spec)
        elif spec.kind in ("box", "violin", "bar"):
            if spec.categories:
                self.set_categories(spec.categories)
            from ctwa.ui.statistics import dist_items
            fn = {"box": dist_items.draw_box, "violin": dist_items.draw_violin, "bar": dist_items.draw_bar}[spec.kind]
            self._adopt(fn(self._plot, spec))
        elif spec.kind == "heatmap":
            from ctwa.ui.statistics.heatmap import draw_heatmap
            draw_heatmap(self, spec)
        self.add_ref_lines(spec.ref_lines, spec.ylog)
        self._legend.set_entries([(s.name, s.color, s.legendgroup) for s in spec.series if s.legend])
        self._apply_visibility()
        if spec.kind == "xy":
            self._plot.getViewBox().autoRange()
        self._install_log_ticks(spec)
        self._home = None if spec.kind == "xy" else self._plot.getViewBox().viewRange()
        self._place_ref_labels()

    def _install_log_ticks(self, spec: ChartSpec) -> None:
        """Decade labels (and 1-2-5 when there is room) instead of pyqtgraph's label at every digit."""
        vb = self._plot.getViewBox()
        axes = []
        if spec.xlog and spec.kind == "xy":
            axes.append((("bottom", "top"), 0))
        if spec.ylog:
            axes.append((("left", "right"), 1))
        if not axes:
            return

        def update(*_):
            for names, dim in axes:
                lo, hi = vb.viewRange()[dim]
                px = vb.width() if dim == 0 else vb.height()
                major, minor = log_ticks(lo, hi, px)
                levels = [major, minor] if minor else [major]
                for n in names:
                    self._plot.getAxis(n).setTicks(levels)

        self.add_range_hook(update)
        update()

    def _draw_xy(self, spec: ChartSpec) -> None:
        try:
            from ctwa.ui.statistics.xy_items import draw_xy
        except ImportError:
            for s in spec.series:
                if "markers" in s.mode:
                    self.add_markers(s, spec)
            return
        draw_xy(self, spec)

    def _adopt(self, items: List[Any]) -> None:
        """Track items a draw function added (hover scatters, series-bound items)."""
        for it in items:
            name = getattr(it, "series_name", "")
            group = getattr(it, "series_group", None)
            self._tracked.append((it, name, group))
            hover = getattr(it, "hover_texts", None)
            if hover is not None and isinstance(it, pg.ScatterPlotItem):
                self._wire_hover(it, hover)

    def track(self, item, series: str, group: Optional[str]) -> None:
        self._tracked.append((item, series, group))

    def add_item(self, item, series: Optional[Series] = None) -> None:
        self._plot.addItem(item)
        self._added.append(item)
        if series is not None:
            self._tracked.append((item, series.name, series.legendgroup))

    def add_markers(self, s: Series, spec: ChartSpec):
        """Scatter item for one series: non-positive values on log axes are skipped; data = analysis id."""
        xs, ys, kept = mask_for_log(s.x, s.y, spec.xlog, spec.ylog)
        vx, vy = to_view(xs, spec.xlog), to_view(ys, spec.ylog)
        ids = [s.ids[i] for i in kept]
        hover = [s.hover[i] for i in kept]
        color = QColor(s.color)
        pen = pg.mkPen(color, width=1.2)
        brush = pg.mkBrush(color) if s.filled else None
        item = pg.ScatterPlotItem(x=vx, y=vy, data=ids, symbol=s.symbol, size=s.size, pen=pen, brush=brush,
                                  hoverable=True, hoverSymbol=s.symbol, hoverSize=s.size + 2, hoverPen=pen,
                                  hoverBrush=brush, tip=None)
        item.setOpacity(s.opacity)
        item.setZValue(5)
        self._plot.addItem(item)
        self._added.append(item)
        self._tracked.append((item, s.name, s.legendgroup))
        self._markers.append(_Marker(item, s.name, s.legendgroup, vx, vy, ids))
        item.sigClicked.connect(self._on_marker_clicked)
        self._wire_hover(item, hover)
        return item

    def _wire_hover(self, item: pg.ScatterPlotItem, hover: List[str]) -> None:
        item.sigHovered.connect(lambda it, pts, ev, h=hover: self._on_hover(h, pts))

    def _on_hover(self, hover: List[str], pts) -> None:
        if len(pts):
            i = pts[0].index()
            if 0 <= i < len(hover) and hover[i]:
                QToolTip.showText(QCursor.pos(), hover[i], self)
                return
        QToolTip.hideText()

    def _on_marker_clicked(self, item, pts, ev=None) -> None:
        if self._tool != "pan" or not len(pts):
            return
        pid = pts[0].data()
        if pid is None:
            return
        if ev is not None and hasattr(ev, "accept"):
            ev.accept()
        self.point_clicked.emit(int(pid))

    # ------------------------------------------------------------------ legend visibility
    def _hidden_sets(self):
        return set(self._legend.hidden_names()), set(self._legend.hidden_groups())

    @staticmethod
    def _is_hidden(name: str, group: Optional[str], names: set, groups: set) -> bool:
        return name in names or (group is not None and group in groups)

    def _apply_visibility(self) -> None:
        names, groups = self._hidden_sets()
        for item, name, group in self._tracked:
            item.setVisible(not self._is_hidden(name, group, names, groups))
        for m in self._markers:
            m.visible = not self._is_hidden(m.series, m.group, names, groups)
        # a hidden series cannot stay selected
        if self._selected:
            visible = {i for m in self._markers if m.visible for i in m.ids if i is not None}
            keep = [i for i in self._selected if i in visible]
            if keep != self._selected:
                self._selected = keep
                if not keep:
                    self.selection_cleared.emit()
            self._draw_ring()

    # ------------------------------------------------------------------ tools and selection
    def set_tool(self, tool: str) -> None:
        if tool not in ("pan", "lasso", "box"):
            raise ValueError(tool)
        self._tool = tool
        if tool in self._buttons:
            self._buttons[tool].setChecked(True)
        self._plot.getViewBox().setMouseMode(pg.ViewBox.PanMode)

    def reset_view(self) -> None:
        vb = self._plot.getViewBox()
        if self._home is None:
            vb.enableAutoRange()
            vb.autoRange()
        else:
            vb.setRange(xRange=self._home[0], yRange=self._home[1], padding=0)

    def select_polygon(self, poly: List[Tuple[float, float]]) -> None:
        """Select the visible markers inside ``poly`` (view coordinates: log10 on a log axis)."""
        ids: List[int] = []
        for m in self._markers:
            if not m.visible or not len(m.xs):
                continue
            inside = points_in_polygon(poly, m.xs, m.ys)
            for k in np.nonzero(inside)[0]:
                pid = m.ids[int(k)]
                if pid is not None and pid not in ids:
                    ids.append(pid)
        self._selected = ids
        self._draw_ring()
        if ids:
            self.selection_made.emit(list(ids))
        else:
            self.selection_cleared.emit()

    def clear_selection(self) -> None:
        had = bool(self._selected)
        self._selected = []
        self._draw_ring()
        if had:
            self.selection_cleared.emit()

    def _draw_ring(self) -> None:
        if self._ring is not None:
            self._plot.removeItem(self._ring)
            self._ring = None
        if not self._selected:
            return
        sel = set(self._selected)
        xs: List[float] = []
        ys: List[float] = []
        sizes: List[float] = []
        for m in self._markers:
            if not m.visible:
                continue
            size = m.item.opts.get("size", 8)
            for k, pid in enumerate(m.ids):
                if pid in sel:
                    xs.append(m.xs[k])
                    ys.append(m.ys[k])
                    sizes.append(size + 6)
        ring = pg.ScatterPlotItem(x=xs, y=ys, size=sizes, symbol="o", brush=None,
                                  pen=pg.mkPen(theme.P.accent_strong, width=2.2))
        ring.setZValue(10)
        self._plot.addItem(ring, ignoreBounds=True)
        self._ring = ring

    # ------------------------------------------------------------------ scene events (heatmap hover/click)
    def _on_scene_click(self, ev) -> None:
        h = getattr(self, "_heat_hit", None)
        if h is not None and ev.button() == Qt.LeftButton:
            cell = h(ev.scenePos())
            if cell is not None:
                self.cell_clicked.emit(*cell)

    def dist_hover_text(self, x: float, y: float) -> Optional[str]:
        """Hover stats of the box / violin under view coordinates (x, y), if any (Plotly's box hover)."""
        if self._spec is None or self._spec.kind not in ("box", "violin"):
            return None
        for item, _, _ in self._tracked:
            fn = getattr(item, "hover_at", None)
            if fn is not None and item.isVisible():
                text = fn(x, y)
                if text:
                    return text
        return None

    def _on_scene_move(self, pos) -> None:
        if self._spec is not None and self._spec.kind in ("box", "violin"):
            p = self._vb.mapSceneToView(pos)
            text = self.dist_hover_text(p.x(), p.y())
            if text:
                QToolTip.showText(QCursor.pos(), text, self)
                self._dist_tip = True
            elif getattr(self, "_dist_tip", False):
                QToolTip.hideText()
                self._dist_tip = False
            return
        h = getattr(self, "_heat_hover", None)
        if h is not None:
            text = h(pos)
            if text:
                QToolTip.showText(QCursor.pos(), text, self)
            else:
                QToolTip.hideText()

    # ------------------------------------------------------------------ export
    def _legend_for_export(self):
        entries = [(n, c) for n, c, _ in self._legend._entries if self._legend.is_visible(n)]
        if not entries:
            return None
        leg = pg.LegendItem(labelTextSize="%dpx" % theme.TEXT_SMALL)
        leg.setParentItem(self._plot.getViewBox())
        leg.anchor(itemPos=(1, 0), parentPos=(1, 0), offset=(-10, 10))
        for n, c in entries:
            leg.addItem(pg.PlotDataItem(pen=pg.mkPen(c, width=3)), n)
        return leg

    def _export(self, exporter_cls, path: str, **params) -> None:
        leg = self._legend_for_export()
        try:
            exp = exporter_cls(self._plot)
            for k, v in params.items():
                exp.parameters()[k] = v
            exp.export(path)
        finally:
            if leg is not None:
                leg.setParentItem(None)
                if leg.scene() is not None:
                    leg.scene().removeItem(leg)

    def export_png(self, path: str) -> None:
        from pyqtgraph.exporters import ImageExporter
        self._export(ImageExporter, path, width=3 * self._pw.width(), background=QColor("#ffffff"))

    def export_svg(self, path: str) -> None:
        from pyqtgraph.exporters import SVGExporter
        self._export(SVGExporter, path)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if text.startswith("<?xml"):                      # plain "<svg ..." start (the prolog is optional)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text.split("?>", 1)[1].lstrip())

    def _export_dialog(self, kind: str) -> None:
        title = self._spec.title if self._spec is not None else "chart"
        path, _ = QFileDialog.getSaveFileName(self, "Export chart", "%s.%s" % (slugify(title), kind),
                                              "%s (*.%s)" % (kind.upper(), kind))
        if path:
            (self.export_png if kind == "png" else self.export_svg)(path)
