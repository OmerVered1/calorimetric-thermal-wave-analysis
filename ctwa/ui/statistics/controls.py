"""Chart controls of the Statistics tab: chart type, metric, grouping, axes, chips, theory curves, period source.

The widgets are split into boxes the tab places where the page does: ``source_box`` (above the filters),
``builder_box`` (section 1), ``alpha_box`` (section 2) and ``phase_actions`` (section 4's log-period chip).
``set_view`` shows a ViewState without emitting; ``apply_to`` returns a copy of a ViewState with the controls'
values; ``changed`` fires only for the user's own edits.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List, Optional, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget)

from ctwa import theme
from ctwa.analysis.jsmath import js_number_to_string
from ctwa.analysis.references import LIT_MATERIALS, LITERATURE_COLORS
from ctwa.stats.model import GROUP_OPTIONS, X_AXES, Y_METRICS
from ctwa.stats.specs import ALPHA_LABELS, JS_COLORS, TheoryInfo
from ctwa.stats.view_state import ALPHA_SERIES, CHART_TYPES, ViewState

__all__ = ["ChartControls", "Chip", "FlowRow"]

CHART_LABELS = {"box": "Box", "violin": "Violin", "bar": "Bar (mean ± std)", "scatter": "Scatter", "line": "Line"}
MEAN_STD_HINT = ("Squares are the mean of the runs at each period (periods within 4 % count as one); bars are the "
                 "sample standard deviation, shown where there are at least two runs.")
RAW_CAL_HINT = "Hollow markers are raw, filled are calibrated; the line joins the two values of the same run."
SOURCE_HINT = "Applies to Period / Frequency axes and Period-based groupings"
THEORY_NOT_DEFINED = ("No theoretical curve is defined for this Y metric — a known α fixes φ(P) and Δt(P), but says "
                      "nothing about the ln term or the amplitude ratio.")
THEORY_MIXED = ("the filtered runs use more than one Δr, so a single curve cannot be right for all of them — "
                "filter to one geometry")


def _dot(color: str, on: bool) -> QIcon:
    pm = QPixmap(10, 10)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(color)
    c.setAlphaF(1.0 if on else 0.35)
    p.setBrush(c)
    p.setPen(Qt.NoPen)
    p.drawEllipse(1, 1, 8, 8)
    p.end()
    return QIcon(pm)


class Chip(QPushButton):
    """A toggle drawn as a pill, optionally with the colour of the line it switches on."""

    def __init__(self, text: str, color: Optional[str] = None, parent=None):
        super().__init__(text, parent)
        self._color = color
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        p = theme.P
        self.setStyleSheet(
            "QPushButton{border:1px solid %s;border-radius:11px;padding:2px 10px;background:transparent;"
            "color:%s;}QPushButton:hover{background:%s;}QPushButton:checked{background:%s;border-color:%s;"
            "color:%s;}" % (p.border, p.text_muted, p.hover, p.accent_soft, p.accent, p.text))
        self.toggled.connect(self._icon)
        self._icon(False)

    def _icon(self, on: bool) -> None:
        if self._color:
            self.setIcon(_dot(self._color, on))


class FlowRow(QWidget):
    """Chips in a wrapping row (a plain HBox is wide enough for this tab; the row wraps through nested rows)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from ctwa.ui.statistics.legend_bar import _Flow
        self._flow = _Flow(self, hspace=6, vspace=4)
        self._flow.setContentsMargins(0, 0, 0, 0)

    def add(self, w: QWidget) -> QWidget:
        self._flow.addWidget(w)
        return w


def _muted(text: str = "", role: str = "faint") -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    theme.set_role(lab, role)
    return lab


def _field(title: str, w: QWidget) -> QWidget:
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    lay.addWidget(_muted(title))
    lay.addWidget(w)
    return box


class ChartControls(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._series: List[str] = ["combined_raw"]
        self._lit_builder: List[str] = []
        self._lit_alpha: List[str] = list(LIT_MATERIALS)
        self._theory_ids: List[int] = []
        self._theory: Optional[TheoryInfo] = None
        self.theory_chips: Dict[int, Chip] = {}

        # ---- period source (sits above the filters on the page)
        self.src_button = QPushButton("Source")
        self.resp_button = QPushButton("Response")
        for b, key in ((self.src_button, "src"), (self.resp_button, "resp")):
            b.setCheckable(True)
            b.setProperty("periodSource", key)
            b.clicked.connect(lambda _=False, k=key: self._set_source(k))
        self.src_button.setChecked(True)
        self.source_hint = _muted(SOURCE_HINT)
        self.source_box = QWidget()
        sl = QVBoxLayout(self.source_box)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(3)
        title = _muted("Period source", "section")
        sl.addWidget(title)
        seg = theme.segmented(self.src_button, self.resp_button)
        sl.addWidget(seg, 0, Qt.AlignLeft)
        sl.addWidget(self.source_hint)

        # ---- builder
        self.y_combo = QComboBox()
        for m in Y_METRICS:
            self.y_combo.addItem(m.label, m.key)
        self.chart_combo = QComboBox()
        for k in CHART_TYPES:
            self.chart_combo.addItem(CHART_LABELS[k], k)
        self.x_combo = QComboBox()
        self.x_combo.addItems(list(X_AXES))
        self.color_combo = QComboBox()
        self.color_combo.addItem("None", None)
        for g in GROUP_OPTIONS:
            self.color_combo.addItem(g, g)
        self.group_combo = QComboBox()
        self.group_combo.addItems(list(GROUP_OPTIONS))
        self._x_field = _field("X-Axis", self.x_combo)
        self._color_field = _field("Color by", self.color_combo)
        self._group_field = _field("Group by", self.group_combo)
        row = QHBoxLayout()
        row.setSpacing(10)
        for w in (_field("Y-Axis Metric", self.y_combo), _field("Chart Type", self.chart_combo), self._x_field,
                  self._color_field, self._group_field):
            row.addWidget(w, 1)

        self.lit_builder_chips: Dict[str, Chip] = {}
        self.log_x_chip = Chip("Log X")
        self.log_y_chip = Chip("Log Y")
        lit = FlowRow()
        lit.add(_muted("Show literature reference lines:", "muted"))
        for name in LIT_MATERIALS:
            c = lit.add(Chip(name, LITERATURE_COLORS[name]))
            c.clicked.connect(lambda _=False, n=name: self._toggle(self._lit_builder, n))
            self.lit_builder_chips[name] = c
        lit.add(self.log_x_chip)
        lit.add(self.log_y_chip)
        self.theory_row = FlowRow()
        self.theory_row.add(_muted("Theory curves (presets):", "muted"))
        self.theory_label = _muted()
        self.theory_mixed_label = _muted("", "warn")
        self.theory_box = QWidget()
        tl = QVBoxLayout(self.theory_box)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(3)
        tl.addWidget(self.theory_row)
        tl.addWidget(self.theory_label)
        tl.addWidget(self.theory_mixed_label)
        self.theory_box.hide()

        self.builder_box = QWidget()
        bl = QVBoxLayout(self.builder_box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(8)
        bl.addLayout(row)
        bl.addWidget(lit)
        bl.addWidget(self.theory_box)

        # ---- alpha chart
        self.mean_chip = Chip("Mean ± std")
        self.pairs_chip = Chip("Raw → calibrated")
        self.period_log_chip = Chip("Log period axis")
        self.phase_period_log_chip = Chip("Log period axis")
        self.series_chips: Dict[str, Chip] = {}
        self.lit_alpha_chips: Dict[str, Chip] = {}
        self.alpha_actions = QWidget()
        al = QHBoxLayout(self.alpha_actions)
        al.setContentsMargins(0, 0, 0, 0)
        al.addWidget(self.mean_chip)
        al.addWidget(self.pairs_chip)
        al.addWidget(self.period_log_chip)
        self.phase_actions = QWidget()
        pl = QHBoxLayout(self.phase_actions)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(self.phase_period_log_chip)
        sr = FlowRow()
        sr.add(_muted("Series:", "muted"))
        for key in ALPHA_SERIES:
            c = sr.add(Chip(ALPHA_LABELS[key]))
            c.clicked.connect(lambda _=False, k=key: self._toggle(self._series, k))
            self.series_chips[key] = c
        sr.add(_muted("Literature reference lines", "muted"))
        for name in LIT_MATERIALS:
            c = sr.add(Chip(name, LITERATURE_COLORS[name]))
            c.clicked.connect(lambda _=False, n=name: self._toggle(self._lit_alpha, n))
            self.lit_alpha_chips[name] = c
        self.alpha_hint = _muted()
        self.alpha_hint.hide()
        self.alpha_box = QWidget()
        xl = QVBoxLayout(self.alpha_box)
        xl.setContentsMargins(0, 0, 0, 0)
        xl.setSpacing(6)
        xl.addWidget(sr)
        self.alpha_hint_holder = self.alpha_hint     # the tab places it under the chart

        # all boxes live here until the tab re-parents them
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        for w in (self.source_box, self.builder_box, self.alpha_box, self.alpha_actions, self.phase_actions,
                  self.alpha_hint):
            lay.addWidget(w)

        for cb in (self.y_combo, self.chart_combo, self.x_combo, self.color_combo, self.group_combo):
            cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(10)
            cb.currentIndexChanged.connect(self._on_edit)
        for chip in (self.log_x_chip, self.log_y_chip, self.mean_chip):
            chip.clicked.connect(self._on_edit)
        self.period_log_chip.clicked.connect(lambda _=False: self._sync_period_log(self.period_log_chip))
        self.phase_period_log_chip.clicked.connect(lambda _=False: self._sync_period_log(self.phase_period_log_chip))
        self.pairs_chip.clicked.connect(self._on_pairs)       # first: it adds the series the change reports
        self.pairs_chip.clicked.connect(self._on_edit)
        for chips in (self.series_chips, self.lit_builder_chips, self.lit_alpha_chips):
            for c in chips.values():
                c.clicked.connect(self._on_edit)
        self.set_view(ViewState())

    # ------------------------------------------------------------------ handlers
    def _emit(self) -> None:
        if not self._loading:
            self.changed.emit()

    def _on_edit(self, *_) -> None:
        if self._loading:
            return
        self._update_visibility()
        self._refresh_text()
        self.changed.emit()

    @staticmethod
    def _toggle(lst: List[Any], v: Any) -> None:
        if v in lst:
            lst.remove(v)
        else:
            lst.append(v)

    def _toggle_theory(self, pid: int) -> None:
        self._toggle(self._theory_ids, pid)

    def _on_pairs(self, *_) -> None:
        """Pairs need both ends on the chart: switching them on turns α phase raw and calibrated on."""
        if self._loading or not self.pairs_chip.isChecked():
            return
        for k in ("phase_raw", "phase_cal"):
            if k not in self._series:
                self._series.append(k)
        self._show_series()

    def _sync_period_log(self, src: Chip) -> None:
        on = src.isChecked()
        for c in (self.period_log_chip, self.phase_period_log_chip):
            c.setChecked(on)
        self._on_edit()

    def _set_source(self, key: str) -> None:
        self.src_button.setChecked(key == "src")
        self.resp_button.setChecked(key == "resp")
        self._on_edit()

    def _show_series(self) -> None:
        for k, c in self.series_chips.items():
            c.setChecked(k in self._series)

    def _update_visibility(self) -> None:
        kind = self.chart_combo.currentData()
        xy = kind in ("scatter", "line")
        self._x_field.setVisible(xy)
        self._color_field.setVisible(xy)
        self._group_field.setVisible(not xy)

    def _refresh_text(self) -> None:
        parts = []
        if self.mean_chip.isChecked():
            parts.append(MEAN_STD_HINT)
        if self.pairs_chip.isChecked():
            parts.append(RAW_CAL_HINT)
        self.alpha_hint.setText(" ".join(parts))
        self.alpha_hint.setVisible(bool(parts))
        self._refresh_theory()

    # ------------------------------------------------------------------ presets and theory
    def set_presets(self, presets: Sequence[Dict[str, Any]]) -> None:
        for c in self.theory_chips.values():
            c.setParent(None)
            c.deleteLater()
        self.theory_chips = {}
        for i, p in enumerate(presets):
            label = "%s %s°C (α=%s)" % (p["material_name"], js_number_to_string(float(p["temperature_c"])),
                                        js_number_to_string(float(p["alpha_mm2s"])))
            c = Chip(label, JS_COLORS[(i + 5) % len(JS_COLORS)])
            pid = p["id"]
            c.setChecked(pid in self._theory_ids)
            c.clicked.connect(lambda _=False, i=pid: self._toggle_theory(i))
            c.clicked.connect(self._on_edit)
            self.theory_row.add(c)
            self.theory_chips[pid] = c
        self.theory_box.setVisible(bool(presets))

    def set_theory_info(self, info: Optional[TheoryInfo]) -> None:
        self._theory = info
        self._refresh_theory()

    def _refresh_theory(self) -> None:
        info = self._theory
        is_alpha = (self.y_combo.currentData() or "").startswith("alpha_")
        want = bool(self._theory_ids) and info is not None
        txt = mixed = ""
        if want and not info.defined and not is_alpha:
            txt = THEORY_NOT_DEFINED
        elif want and info.defined and info.dr is not None:
            txt = "Curves drawn with Δr = %s mm" % js_number_to_string(float(info.dr))
            if info.mixed:
                mixed = "%s (%s mm)" % (THEORY_MIXED, ", ".join(js_number_to_string(float(d)) for d in info.mixed))
        self.theory_label.setText(txt)
        self.theory_label.setVisible(bool(txt))
        self.theory_mixed_label.setText(mixed)
        self.theory_mixed_label.setVisible(bool(mixed))

    def period_source_texts(self) -> List[str]:
        return [self.src_button.text(), self.resp_button.text()]

    # ------------------------------------------------------------------ view <-> widgets
    def set_view(self, v: ViewState) -> None:
        self._loading = True
        try:
            self.y_combo.setCurrentIndex(max(0, self.y_combo.findData(v.y_metric)))
            self.chart_combo.setCurrentIndex(max(0, self.chart_combo.findData(v.chart_type)))
            self.x_combo.setCurrentIndex(max(0, self.x_combo.findText(v.x_axis)))
            self.color_combo.setCurrentIndex(max(0, self.color_combo.findData(v.color_by)))
            self.group_combo.setCurrentIndex(max(0, self.group_combo.findText(v.group_by)))
            self.log_x_chip.setChecked(v.log_x)
            self.log_y_chip.setChecked(v.log_y)
            self.mean_chip.setChecked(v.show_mean)
            self.pairs_chip.setChecked(v.show_pairs)
            for c in (self.period_log_chip, self.phase_period_log_chip):
                c.setChecked(v.period_log)
            self.src_button.setChecked(v.period_source == "src")
            self.resp_button.setChecked(v.period_source == "resp")
            self._series = list(v.alpha_series)
            self._lit_builder = list(v.lit_builder)
            self._lit_alpha = list(v.lit_alpha)
            self._theory_ids = list(v.theory_ids)
            self._show_series()
            for n, c in self.lit_builder_chips.items():
                c.setChecked(n in self._lit_builder)
            for n, c in self.lit_alpha_chips.items():
                c.setChecked(n in self._lit_alpha)
            for pid, c in self.theory_chips.items():
                c.setChecked(pid in self._theory_ids)
            self._update_visibility()
            self._refresh_text()
        finally:
            self._loading = False

    def apply_to(self, v: ViewState) -> ViewState:
        return replace(
            v, chart_type=self.chart_combo.currentData(), y_metric=self.y_combo.currentData(),
            group_by=self.group_combo.currentText(), x_axis=self.x_combo.currentText(),
            color_by=self.color_combo.currentData(), log_x=self.log_x_chip.isChecked(),
            log_y=self.log_y_chip.isChecked(), period_log=self.period_log_chip.isChecked(),
            show_mean=self.mean_chip.isChecked(), show_pairs=self.pairs_chip.isChecked(),
            period_source="resp" if self.resp_button.isChecked() else "src", alpha_series=list(self._series),
            lit_builder=list(self._lit_builder), lit_alpha=list(self._lit_alpha), theory_ids=list(self._theory_ids))
