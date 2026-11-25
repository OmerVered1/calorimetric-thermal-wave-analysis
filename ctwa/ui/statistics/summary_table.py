"""Section 7: per-model summary of the four alpha series (mean / std / min / max), first column frozen."""
from __future__ import annotations

from typing import List, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView, QTableWidget, QTableWidgetItem

from ctwa.stats.aggregate import STAT_KEYS, SummaryRow, fmt_stat
from ctwa.stats.model import color_for

__all__ = ["StatisticsSummary", "SERIES_HEADS", "STAT_HEADS"]

SERIES_HEADS = ("α comb raw", "α phase raw", "α comb cal", "α phase cal")
STAT_HEADS = ("Mean", "Std", "Min", "Max")
_DIGITS = (4, 3, 4, 4)           # the page's toPrecision digits for mean, std, min, max


def _dot(color: str) -> QIcon:
    pm = QPixmap(10, 10)
    pm.fill(Qt.transparent)
    from PySide6.QtGui import QPainter
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen)
    p.drawEllipse(1, 1, 8, 8)
    p.end()
    return QIcon(pm)


class StatisticsSummary(QTableWidget):
    """Model | N | 4 x (Mean, Std, Min, Max). The first column stays put while the rest scrolls sideways."""

    def __init__(self, parent=None):
        super().__init__(parent)
        heads = ["Model", "N"] + ["%s (mm²/s)\n%s" % (s, h) for s in SERIES_HEADS for h in STAT_HEADS]
        self.setColumnCount(len(heads))
        self.setHorizontalHeaderLabels(heads)
        self.verticalHeader().hide()
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.horizontalHeader().setMinimumSectionSize(60)
        self.setWordWrap(False)
        self._frozen = QTableView(self)
        self._frozen.setModel(self.model())
        self._frozen.setFocusPolicy(Qt.NoFocus)
        self._frozen.verticalHeader().hide()
        self._frozen.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self._frozen.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._frozen.setSelectionMode(QAbstractItemView.NoSelection)
        self._frozen.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._frozen.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._frozen.setStyleSheet("QTableView{border:none;border-right:1px solid #C3C6CA;}")
        self.viewport().stackUnder(self._frozen)
        for c in range(1, len(heads)):
            self._frozen.setColumnHidden(c, True)
        self.verticalScrollBar().valueChanged.connect(self._frozen.verticalScrollBar().setValue)
        self._frozen.verticalScrollBar().valueChanged.connect(self.verticalScrollBar().setValue)
        self.horizontalHeader().sectionResized.connect(self._section_resized)
        self.setMinimumHeight(96)

    # ------------------------------------------------------------------ frozen column plumbing
    def _section_resized(self, col: int, _old: int, new: int) -> None:
        if col == 0:
            self._frozen.setColumnWidth(0, new)
            self._fit_frozen()

    def _fit_frozen(self) -> None:
        h = self.horizontalHeader().height()
        self._frozen.setGeometry(self.frameWidth(), self.frameWidth(), self.columnWidth(0),
                                 self.viewport().height() + h)
        self._frozen.horizontalHeader().setFixedHeight(h)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit_frozen()

    def scrollTo(self, index, hint=QAbstractItemView.EnsureVisible):
        if index.column() > 0:
            super().scrollTo(index, hint)

    # ------------------------------------------------------------------ data
    def set_summary(self, rows: Sequence[SummaryRow]) -> None:
        self.setRowCount(len(rows))
        for r, s in enumerate(rows):
            name = QTableWidgetItem(str(s.model))
            name.setIcon(_dot(color_for(s.model)))
            name.setFont(self._bold(name.font()))
            self.setItem(r, 0, name)
            n = QTableWidgetItem(str(s.n))
            n.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.setItem(r, 1, n)
            col = 2
            for key in STAT_KEYS:
                st = s.stats[key]
                for i, digits in enumerate(_DIGITS):
                    it = QTableWidgetItem(fmt_stat(st[i + 1] if st else None, digits))
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self.setItem(r, col, it)
                    col += 1
        self.resizeColumnsToContents()
        self._frozen.setColumnWidth(0, self.columnWidth(0))
        self._fit_frozen()

    @staticmethod
    def _bold(f):
        f.setBold(True)
        return f

    def texts(self) -> List[List[str]]:
        return [[self.item(r, c).text() for c in range(self.columnCount())] for r in range(self.rowCount())]
