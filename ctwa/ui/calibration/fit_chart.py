"""Device lag against period: the selected references, the fitted curve, the fitted range and the
target (Plan 4, Task 7). As the webapp's chart (fitPlot in app/calibration/page.tsx).

pyqtgraph's log mode converts the data of plot items itself, but not InfiniteLine or
LinearRegionItem: those two get log10(x) positions."""
from __future__ import annotations

import math
from typing import List, Optional

import pyqtgraph as pg
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ctwa import theme
from ctwa.analysis.calibration_logic import RefLag, curve_points
from ctwa.analysis.types import LagFit
from ctwa.results.helpers import material_color
from ctwa.ui.calibration.texts import TEXT

TARGET_COLOR = "#E4572E"
CURVE_COLOR = "#7f8c8d"
REGION_BRUSH = (31, 91, 176, int(round(0.07 * 255)))


class _PeriodAxis(pg.AxisItem):
    """Log-x axis in seconds: ticks at 1, 2, 3, 5, 7 x 10^k labelled as plain numbers (80, 100, 250)."""
    _MANTISSAS = (1, 2, 3, 5, 7)

    def tickValues(self, minVal, maxVal, size):
        lo, hi = 10 ** minVal, 10 ** maxVal
        vals = []
        k = math.floor(math.log10(lo)) - 1
        while 10 ** k <= hi:
            for m in self._MANTISSAS:
                v = m * 10 ** k
                if lo <= v <= hi:
                    vals.append(math.log10(v))
            k += 1
        return [(1.0, vals)]

    def tickStrings(self, values, scale, spacing):
        return ["%g" % round(10 ** v, 6) for v in values]


def _hover(x, y, _data) -> str:
    return "%d s → %.1f s" % (x, y)


class FitChart(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.plot = pg.PlotWidget(axisItems={"bottom": _PeriodAxis("bottom")})
        self.plot.setFixedHeight(340)
        theme.style_plot(self.plot, TEXT["fitChartTitle"])
        self.item = self.plot.getPlotItem()
        self.item.setLabel("bottom", TEXT["period"] + " (s)")
        self.item.setLabel("left", TEXT["deviceLag"] + " (s)")
        self.item.setLogMode(x=True, y=False)
        self.legend = theme.legend(self.item)
        lay.addWidget(self.plot)
        self.scatter_items: List[pg.PlotDataItem] = []
        self.curve_item: Optional[pg.PlotDataItem] = None
        self.region_item: Optional[pg.LinearRegionItem] = None
        self.target_line: Optional[pg.InfiniteLine] = None
        self.star_item: Optional[pg.PlotDataItem] = None
        self.hide()

    def _clear(self) -> None:
        for it in self.scatter_items + [self.curve_item, self.region_item, self.target_line, self.star_item]:
            if it is not None:
                self.item.removeItem(it)
        self.legend.clear()
        self.scatter_items = []
        self.curve_item = self.region_item = self.target_line = self.star_item = None

    def set_data(self, fit: Optional[LagFit], sel: List[RefLag], target: Optional[dict]) -> None:
        self._clear()
        if fit is None or not sel:
            self.hide()
            return
        self.show()
        # fitted range, shaded and fixed
        self.region_item = pg.LinearRegionItem(
            values=(math.log10(fit.p_min), math.log10(fit.p_max)), movable=False,
            brush=pg.mkBrush(*REGION_BRUSH), pen=pg.mkPen(None))
        self.region_item.setZValue(-10)
        self.item.addItem(self.region_item)
        # one marker trace per material
        for name in list(dict.fromkeys(x.ref.get("model_name") for x in sel)):
            pts = [x for x in sel if x.ref.get("model_name") == name]
            it = pg.PlotDataItem([x.ref["period_t"] for x in pts], [x.lag for x in pts], pen=None,
                                 symbol="o", symbolSize=9, symbolBrush=pg.mkBrush(material_color(name)),
                                 symbolPen=pg.mkPen(None), name=str(name))
            it.scatter.opts["tip"] = _hover
            self.item.addItem(it)
            self.scatter_items.append(it)
        # the fitted curve
        xs, ys = curve_points(fit)
        self.curve_item = pg.PlotDataItem(xs, ys, pen=theme.pen(CURVE_COLOR, 2, dashed=True), name=TEXT["model_" + fit.kind])
        self.item.addItem(self.curve_item)
        # the target: a vertical line, and a star on the curve at its period
        period = target.get("period_t") if target else None
        if period is not None and math.isfinite(period) and period > 0:
            pen = pg.mkPen(TARGET_COLOR, width=1.5)
            from PySide6.QtCore import Qt
            pen.setStyle(Qt.DashDotLine)
            self.target_line = pg.InfiniteLine(pos=math.log10(period), angle=90, movable=False, pen=pen)
            self.item.addItem(self.target_line)
            lag = fit.predict(period)
            if math.isfinite(lag):
                self.star_item = pg.PlotDataItem(
                    [period], [lag], pen=None, symbol="star", symbolSize=15,
                    symbolBrush=pg.mkBrush(TARGET_COLOR), symbolPen=pg.mkPen("#ffffff", width=1),
                    name="#%s" % target["id"])
                self.star_item.scatter.opts["tip"] = lambda x, y, _d, i=target["id"]: "#%s · %d s → %.1f s" % (i, x, y)
                self.item.addItem(self.star_item)
        self.item.autoRange()
