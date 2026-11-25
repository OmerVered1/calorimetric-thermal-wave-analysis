"""Filter panel of the Statistics tab: everything is included by default; unchecking cuts (the page's sidebar).

The stored form stays the excluded set (``FilterState``). ``set_rows`` rebuilds the option lists, ``set_state`` /
``state`` move the whole filter in and out without emitting, and ``changed`` fires once per user edit.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QDate, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
                               QToolButton, QVBoxLayout, QWidget)

from ctwa import theme
from ctwa.stats.filters import (FilterState, a1_domain, a1_step, active_filters, clear_filter, distinct_values,
                                period_domain, period_options)

__all__ = ["FilterPanel", "RangeSlider"]

ROW_KIND_TEXT = (("originals", "Originals only"), ("copies", "Calibrated copies only"), ("all", "Both"))
ROW_KIND_HINT = "A calibrated run is saved as a copy of the original, so the two are kept apart here."
ROW_KIND_WARN = ("A calibrated copy repeats its original’s raw values, so every raw quantity is counted twice. Use "
                 "this only to compare a run against its own calibration.")


class RangeSlider(QWidget):
    """Two-handle slider over [lo, hi] with a fixed step; ``changed(lo, hi)`` follows the user's drags."""
    changed = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._min, self._max, self._step = 0.0, 1.0, 1.0
        self._lo, self._hi = 0.0, 1.0
        self._drag: Optional[str] = None
        self.setMinimumHeight(22)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_domain(self, lo: float, hi: float, step: float) -> None:
        self._min, self._max, self._step = lo, hi, step
        self._lo, self._hi = max(self._lo, lo), min(self._hi, hi)
        self.update()

    def set_values(self, lo: float, hi: float) -> None:
        self._lo, self._hi = lo, hi
        self.update()

    def values(self) -> Tuple[float, float]:
        return self._lo, self._hi

    def _x(self, v: float) -> float:
        span = (self._max - self._min) or 1.0
        return 8 + (self.width() - 16) * (v - self._min) / span

    def _v(self, x: float) -> float:
        span = self._max - self._min
        raw = self._min + span * (x - 8) / max(1, self.width() - 16)
        steps = round((raw - self._min) / self._step)
        return min(self._max, max(self._min, self._min + steps * self._step))

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        y = self.height() / 2
        p.setPen(QPen(QColor(theme.P.border), 3, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(8, y), QPointF(self.width() - 8, y))
        p.setPen(QPen(QColor(theme.P.accent), 3, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(self._x(self._lo), y), QPointF(self._x(self._hi), y))
        for v in (self._lo, self._hi):
            p.setPen(QPen(QColor(theme.P.accent_strong), 1.5))
            p.setBrush(QColor(theme.P.raised))
            p.drawEllipse(QPointF(self._x(v), y), 6, 6)

    def mousePressEvent(self, ev):
        x = ev.position().x()
        self._drag = "lo" if abs(x - self._x(self._lo)) <= abs(x - self._x(self._hi)) else "hi"
        self.mouseMoveEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._drag is None:
            return
        v = self._v(ev.position().x())
        lo, hi = (min(v, self._hi), self._hi) if self._drag == "lo" else (self._lo, max(v, self._lo))
        if (lo, hi) != (self._lo, self._hi):
            self._lo, self._hi = lo, hi
            self.update()
            self.changed.emit(lo, hi)

    def mouseReleaseEvent(self, ev):
        self._drag = None


class _Group(QFrame):
    """A collapsible filter group: title, count badge, clear (×) and a content area."""

    def __init__(self, title: str, on_reset: Optional[Callable[[], None]] = None, closed: bool = False):
        super().__init__()
        self._title = title
        self._closed = closed
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.head = QToolButton()
        self.head.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.head.setCheckable(True)
        self.head.setChecked(not closed)
        self.head.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.head.setStyleSheet("QToolButton{border:none;text-align:left;font-weight:600;padding:6px 10px;}")
        self.head.toggled.connect(self._toggle)
        self.reset = QToolButton()
        self.reset.setText("×")
        theme.set_role(self.reset, "quiet")
        self.reset.hide()
        if on_reset:
            self.reset.clicked.connect(lambda: on_reset())
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 4, 0)
        top.addWidget(self.head, 1)
        top.addWidget(self.reset)
        lay.addLayout(top)
        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(10, 0, 10, 8)
        self.body_lay.setSpacing(4)
        lay.addWidget(self.body)
        self.body.setVisible(not closed)
        self.set_count(0)

    def _toggle(self, on: bool) -> None:
        self.body.setVisible(on)
        self._refresh_head()

    def _refresh_head(self) -> None:
        arrow = "▾" if self.head.isChecked() else "▸"
        badge = "  (%d)" % self._count if self._count else ""
        self.head.setText("%s %s%s" % (arrow, self._title, badge))

    def set_count(self, n: int) -> None:
        self._count = n
        self.reset.setVisible(n > 0)
        if n > 0 and not self.head.isChecked():      # a closed group with an active filter opens (the page's rule)
            self.head.setChecked(True)
        self._refresh_head()

    def add(self, w) -> None:
        self.body_lay.addWidget(w)


def _check_list(max_h: int = 120) -> QListWidget:
    lst = QListWidget()
    lst.setMaximumHeight(max_h)
    lst.setSelectionMode(QListWidget.NoSelection)
    return lst


def _hint(text: str = "", role: str = "faint") -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    theme.set_role(lab, role)
    return lab


class FilterPanel(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: List[Dict[str, Any]] = []
        self._state = FilterState()
        self._loading = False
        self._period_dom: Optional[Tuple[int, int]] = None
        self._a1_dom: Optional[Tuple[int, int]] = None

        # ---- header
        self.chip_count_label = QLabel("")
        theme.set_role(self.chip_count_label, "pill", tone="accent")
        self.chip_count_label.hide()
        title = QLabel("Filters")
        theme.set_role(title, "heading")
        self.reset_button = QPushButton("Reset all filters")
        theme.set_role(self.reset_button, "quiet")
        self.reset_button.clicked.connect(self._reset_all)
        head = QHBoxLayout()
        head.addWidget(title)
        head.addWidget(self.chip_count_label)
        head.addStretch(1)
        head.addWidget(self.reset_button)
        self._chip_host = QWidget()
        self._chip_lay = QVBoxLayout(self._chip_host)
        self._chip_lay.setContentsMargins(0, 0, 0, 0)
        self._chip_lay.setSpacing(3)
        self._chips: List[Tuple[str, str, QToolButton]] = []

        # ---- groups
        self.model_list = _check_list()
        self.g_models = _Group("Models", lambda: self._clear("models"))
        self.g_models.add(self.model_list)

        self.period_lo = QSpinBox()
        self.period_hi = QSpinBox()
        for sp in (self.period_lo, self.period_hi):
            sp.setSingleStep(10)
            sp.setSuffix(" s")
            sp.setKeyboardTracking(False)
        self.period_slider = RangeSlider()
        self.period_list = _check_list(150)
        self.period_empty = _hint("No periods in range", "muted")
        self.period_empty.hide()
        self.g_periods = _Group("Periods", self._reset_periods)
        self.period_range_box = QWidget()
        pr = QVBoxLayout(self.period_range_box)
        pr.setContentsMargins(0, 0, 0, 0)
        pr.addWidget(self.period_slider)
        spins = QHBoxLayout()
        spins.addWidget(self.period_lo)
        spins.addWidget(QLabel("–"))
        spins.addWidget(self.period_hi)
        pr.addLayout(spins)
        self.g_periods.add(self.period_range_box)
        self.g_periods.add(self.period_list)
        self.g_periods.add(self.period_empty)

        self.a1_lo = QDoubleSpinBox()
        self.a1_hi = QDoubleSpinBox()
        for sp in (self.a1_lo, self.a1_hi):
            sp.setDecimals(1)
            sp.setSuffix(" mW")
            sp.setRange(-1e9, 1e9)
            sp.setKeyboardTracking(False)
        self.a1_slider = RangeSlider()
        self.a1_none = _hint("—", "muted")
        self.g_a1 = _Group("A₁ (mW)", lambda: self._clear("a1"))
        self.a1_range_box = QWidget()
        ar = QVBoxLayout(self.a1_range_box)
        ar.setContentsMargins(0, 0, 0, 0)
        ar.addWidget(self.a1_slider)
        s2 = QHBoxLayout()
        s2.addWidget(self.a1_lo)
        s2.addWidget(QLabel("–"))
        s2.addWidget(self.a1_hi)
        ar.addLayout(s2)
        self.g_a1.add(self.a1_range_box)
        self.g_a1.add(self.a1_none)

        self.rows_combo = QComboBox()
        for k, t in ROW_KIND_TEXT:
            self.rows_combo.addItem(t, k)
        self.row_hint = _hint(ROW_KIND_HINT)
        self.row_warning = _hint(ROW_KIND_WARN, "warn")
        self.row_warning.hide()
        self.g_rows = _Group("Rows", lambda: self._clear("row_kind"))
        for w in (self.rows_combo, self.row_hint, self.row_warning):
            self.g_rows.add(w)

        self.cal_combo = QComboBox()
        self.cal_combo.addItems(["All", "Calibrated", "Uncalibrated"])
        self.g_cal = _Group("Calibration", lambda: self._clear("cal"))
        self.g_cal.add(self.cal_combo)

        self.gas_list, self.mode_list = _check_list(), _check_list()
        self.source_list, self.response_list = _check_list(), _check_list()
        self.g_gas = _Group("Gas Atmosphere", lambda: self._clear("gas"), closed=True)
        self.g_gas.add(self.gas_list)
        self.g_modes = _Group("Analysis Mode", lambda: self._clear("modes"), closed=True)
        self.g_modes.add(self.mode_list)
        self.g_source = _Group("Power Source Device", lambda: self._clear("source"), closed=True)
        self.g_source.add(self.source_list)
        self.g_response = _Group("Power Response Device", lambda: self._clear("response"), closed=True)
        self.g_response.add(self.response_list)

        self.date_from, self.date_to = QDateEdit(), QDateEdit()
        self.date_from_free, self.date_to_free = QCheckBox("no limit"), QCheckBox("no limit")
        self.g_dates = _Group("Date Range", lambda: self._clear("dates"), closed=True)
        for lab, de, free in (("From", self.date_from, self.date_from_free), ("To", self.date_to, self.date_to_free)):
            de.setCalendarPopup(True)
            de.setDisplayFormat("yyyy-MM-dd")
            de.setDate(QDate.currentDate())
            free.setChecked(True)
            de.setEnabled(False)
            r = QHBoxLayout()
            r.addWidget(QLabel(lab))
            r.addWidget(de, 1)
            r.addWidget(free)
            w = QWidget()
            w.setLayout(r)
            r.setContentsMargins(0, 0, 0, 0)
            self.g_dates.add(w)

        self._groups = [self.g_models, self.g_periods, self.g_a1, self.g_rows, self.g_cal, self.g_gas, self.g_modes,
                        self.g_source, self.g_response, self.g_dates]

        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(0)
        il.addWidget(self._chip_host)
        for g in self._groups:
            il.addWidget(g)
            line = QFrame()
            line.setFrameShape(QFrame.HLine)
            line.setStyleSheet("color:%s" % theme.P.hairline)
            il.addWidget(line)
        il.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setFrameShape(QFrame.NoFrame)
        self.scroll = scroll
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addLayout(head)
        lay.addWidget(scroll, 1)

        # ---- wiring
        for lst, getter in ((self.model_list, lambda s: s.exclude_models), (self.gas_list, lambda s: s.exclude_gas),
                            (self.mode_list, lambda s: s.exclude_modes),
                            (self.source_list, lambda s: s.exclude_source_devices),
                            (self.response_list, lambda s: s.exclude_response_devices),
                            (self.period_list, lambda s: s.exclude_periods)):
            lst.itemChanged.connect(lambda item, lst=lst, g=getter: self._on_item(lst, g, item))
        self.rows_combo.currentIndexChanged.connect(self._on_rows)
        self.cal_combo.currentIndexChanged.connect(self._on_cal)
        self.period_lo.valueChanged.connect(self._on_period_spin)
        self.period_hi.valueChanged.connect(self._on_period_spin)
        self.period_slider.changed.connect(lambda lo, hi: self._set_period_widgets(int(lo), int(hi), True))
        self.a1_lo.valueChanged.connect(self._on_a1_spin)
        self.a1_hi.valueChanged.connect(self._on_a1_spin)
        self.a1_slider.changed.connect(lambda lo, hi: self._set_a1_widgets(lo, hi, True))
        for de, free in ((self.date_from, self.date_from_free), (self.date_to, self.date_to_free)):
            de.dateChanged.connect(self._on_dates)
            free.toggled.connect(lambda on, de=de: (de.setEnabled(not on), self._on_dates()))
        self._rebuild(initial=True)

    # ------------------------------------------------------------------ public
    def chips(self) -> List[Tuple[str, str, QToolButton]]:
        return list(self._chips)

    def state(self) -> FilterState:
        return self._state.copy()

    def set_rows(self, rows) -> None:
        self._rows = list(rows)
        self._rebuild()

    def set_state(self, st: FilterState) -> None:
        self._state = st.copy()
        self._rebuild()

    # ------------------------------------------------------------------ rebuild from rows + state (silent)
    def _fill(self, lst: QListWidget, items: List[Tuple[str, Any]], excluded: Set[Any]) -> None:
        lst.clear()
        for text, value in items:
            it = QListWidgetItem(text)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setData(Qt.UserRole, value)
            it.setCheckState(Qt.Unchecked if value in excluded else Qt.Checked)
            lst.addItem(it)

    def _rebuild(self, initial: bool = False) -> None:
        self._loading = True
        try:
            st, rows = self._state, self._rows
            self._fill(self.model_list, [(v, v) for v in distinct_values(rows, "model_name")], st.exclude_models)
            self._fill(self.gas_list, [(v, v) for v in distinct_values(rows, "gas_atmosphere")], st.exclude_gas)
            self._fill(self.mode_list, [(v, v) for v in distinct_values(rows, "analysis_mode")], st.exclude_modes)
            self._fill(self.source_list, [(v, v) for v in distinct_values(rows, "power_source_device")],
                       st.exclude_source_devices)
            self._fill(self.response_list, [(v, v) for v in distinct_values(rows, "power_response_device")],
                       st.exclude_response_devices)
            self._period_dom = period_domain(rows)
            self._a1_dom = a1_domain(rows)
            pd = self._period_dom
            show = pd is not None and pd[0] < pd[1]
            self.period_range_box.setVisible(show)
            if pd is not None:
                for sp in (self.period_lo, self.period_hi):
                    sp.setRange(pd[0], pd[1])
                self.period_slider.set_domain(pd[0], pd[1], 10)
                lo, hi = st.period_range or pd
                self._set_period_widgets(lo, hi, False)
            self._fill_periods()
            ad = self._a1_dom
            show = ad is not None and ad[0] < ad[1]
            self.a1_range_box.setVisible(show)
            self.a1_none.setVisible(not show)
            if ad is not None:
                step = a1_step(ad[0], ad[1])
                for sp in (self.a1_lo, self.a1_hi):
                    sp.setRange(ad[0], ad[1])
                    sp.setSingleStep(step)
                self.a1_slider.set_domain(ad[0], ad[1], step)
                lo, hi = st.a1_range or ad
                self._set_a1_widgets(lo, hi, False)
            self.rows_combo.setCurrentIndex(max(0, self.rows_combo.findData(st.row_kind)))
            self.cal_combo.setCurrentIndex(max(0, self.cal_combo.findText(st.cal)))
            for de, free, d in ((self.date_from, self.date_from_free, st.date_from),
                                (self.date_to, self.date_to_free, st.date_to)):
                free.setChecked(d is None)
                de.setEnabled(d is not None)
                if d is not None:
                    de.setDate(QDate(d.year, d.month, d.day))
            self._refresh_derived()
        finally:
            self._loading = False

    def _fill_periods(self) -> None:
        opts = period_options(self._rows, self._state)
        self._fill(self.period_list, [("%d s" % p, p) for p in opts], self._state.exclude_periods)
        self.period_list.setVisible(bool(opts))
        self.period_empty.setVisible(not opts)

    def _refresh_derived(self) -> None:
        st = self._state
        self.row_warning.setVisible(st.row_kind == "all")
        self.row_hint.setVisible(st.row_kind != "all")
        pr = st.period_range is not None and self._period_dom is not None and tuple(st.period_range) != self._period_dom
        self.g_models.set_count(len(st.exclude_models))
        self.g_periods.set_count(len(st.exclude_periods) + (1 if pr else 0))
        ar = st.a1_range is not None and self._a1_dom is not None and tuple(st.a1_range) != tuple(self._a1_dom)
        self.g_a1.set_count(1 if ar else 0)
        self.g_rows.set_count(1 if st.row_kind != "originals" else 0)
        self.g_cal.set_count(1 if st.cal != "All" else 0)
        self.g_gas.set_count(len(st.exclude_gas))
        self.g_modes.set_count(len(st.exclude_modes))
        self.g_source.set_count(len(st.exclude_source_devices))
        self.g_response.set_count(len(st.exclude_response_devices))
        self.g_dates.set_count(1 if (st.date_from or st.date_to) else 0)
        active = active_filters(st, self._rows)
        for _, _, b in self._chips:
            b.parent().deleteLater()
        self._chips = []
        while self._chip_lay.count():
            self._chip_lay.takeAt(0)
        for label, key in active:
            row = QFrame()
            row.setFrameShape(QFrame.NoFrame)
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            lab = QLabel(label)
            theme.set_role(lab, "pill", tone="accent")
            x = QToolButton()
            x.setText("×")
            theme.set_role(x, "quiet")
            x.clicked.connect(lambda _=False, k=key: self._clear(k))
            h.addWidget(lab)
            h.addWidget(x)
            h.addStretch(1)
            self._chip_lay.addWidget(row)
            self._chips.append((label, key, x))
        self.chip_count_label.setText(str(len(active)))
        self.chip_count_label.setVisible(bool(active))
        self.reset_button.setEnabled(bool(active))

    # ------------------------------------------------------------------ user edits
    def _commit(self) -> None:
        self._refresh_derived()
        self.changed.emit()

    def _on_item(self, lst: QListWidget, getter, item: QListWidgetItem) -> None:
        if self._loading:
            return
        excluded = getter(self._state)
        value = item.data(Qt.UserRole)
        if item.checkState() == Qt.Checked:
            excluded.discard(value)
        else:
            excluded.add(value)
        self._commit()

    def _on_rows(self, *_) -> None:
        if self._loading:
            return
        self._state.row_kind = self.rows_combo.currentData()
        self._commit()

    def _on_cal(self, *_) -> None:
        if self._loading:
            return
        self._state.cal = self.cal_combo.currentText()
        self._commit()

    def _set_period_widgets(self, lo: int, hi: int, user: bool) -> None:
        was = self._loading
        self._loading = True
        try:
            self.period_lo.setValue(lo)
            self.period_hi.setValue(hi)
            self.period_slider.set_values(lo, hi)
        finally:
            self._loading = was
        if user:
            self._apply_period_range()

    def _on_period_spin(self, *_) -> None:
        if self._loading:
            return
        lo, hi = self.period_lo.value(), self.period_hi.value()
        if lo > hi:                                      # the handle being moved pushes the other
            if self.sender() is self.period_lo:
                hi = lo
            else:
                lo = hi
        self._set_period_widgets(lo, hi, True)

    def _apply_period_range(self) -> None:
        rng = (self.period_lo.value(), self.period_hi.value())
        self._state.period_range = None if rng == self._period_dom else rng
        self._fill_periods_silent()
        self._commit()

    def _fill_periods_silent(self) -> None:
        was = self._loading
        self._loading = True
        try:
            self._fill_periods()
        finally:
            self._loading = was

    def _set_a1_widgets(self, lo: float, hi: float, user: bool) -> None:
        was = self._loading
        self._loading = True
        try:
            self.a1_lo.setValue(lo)
            self.a1_hi.setValue(hi)
            self.a1_slider.set_values(lo, hi)
        finally:
            self._loading = was
        if user:
            rng = (float(self.a1_lo.value()), float(self.a1_hi.value()))
            dom = tuple(float(v) for v in self._a1_dom) if self._a1_dom else None
            self._state.a1_range = None if rng == dom else rng
            self._commit()

    def _on_a1_spin(self, *_) -> None:
        if self._loading:
            return
        lo, hi = self.a1_lo.value(), self.a1_hi.value()
        if lo > hi:
            if self.sender() is self.a1_lo:
                hi = lo
            else:
                lo = hi
        self._set_a1_widgets(lo, hi, True)

    def _on_dates(self, *_) -> None:
        if self._loading:
            return

        def pick(de: QDateEdit, free: QCheckBox) -> Optional[date]:
            d = de.date()
            return None if free.isChecked() else date(d.year(), d.month(), d.day())

        self._state.date_from = pick(self.date_from, self.date_from_free)
        self._state.date_to = pick(self.date_to, self.date_to_free)
        self._commit()

    def _reset_periods(self) -> None:
        self._state = self._state.copy()
        self._state.exclude_periods = set()
        self._state.period_range = None
        self._apply_state_and_emit()

    def _clear(self, key: str) -> None:
        self._state = clear_filter(self._state, key)
        self._apply_state_and_emit()

    def _reset_all(self) -> None:
        self._state = self._state.reset_keep_hidden()
        self._apply_state_and_emit()

    def _apply_state_and_emit(self) -> None:
        self._rebuild()
        self.changed.emit()
