"""Calibrate one run: target, reference picker, lag source, models, result and Save (Plan 4, Task 8).

State used: target_id, selected_ref_ids, model_kind, lag_source, ref_filter_*, ref_near_*, ref_sort.
Save = one INSERT of a calibrated copy through the tab's WriteQueue (the source row is never edited).
The section holds its own `saving` state from the click until the save has finished (the graph fetch
can take a while before the queue is even busy), so a double click cannot write two copies."""
from __future__ import annotations

import math
from typing import Callable, List, Optional

from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QCompleter, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QRadioButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ctwa import theme
from ctwa.analysis.calibration_batch import build_calibrated_row, calibration_model_string
from ctwa.analysis.calibration_logic import (TEMP_SPREAD_WARN_C, all_materials, label_of, num, ref_temps,
                                             temp_spread)
from ctwa.analysis.jsmath import js_number_to_string
from ctwa.results.helpers import format_alpha
from ctwa.ui.calibration.common import StepCard, failure_text, link_button, note_label, parse_number
from ctwa.ui.calibration.fit_chart import FitChart
from ctwa.ui.calibration.state import CalibrationState
from ctwa.ui.calibration.texts import TEXT
from ctwa.ui.calibration.writes import WriteOp, WriteQueue

DASH = "—"
SORTS = [("period", "sortPeriod"), ("nearPeriod", "sortNearPeriod"), ("nearTemp", "sortNearTemp")]


def _has_period(row: dict) -> bool:
    p = row.get("period_t")
    return isinstance(p, (int, float)) and math.isfinite(p) and p > 0


def _signed(v: Optional[float]) -> str:
    return "" if v is None else ("+" if v > 0 else "") + num(v, 0)


def _fill(combo: QComboBox, items: List[tuple], current) -> None:
    """items = [(data, text)]; select `current` (first item when it is not there)."""
    have = [(combo.itemData(i), combo.itemText(i)) for i in range(combo.count())]
    combo.blockSignals(True)
    if have != items:
        combo.clear()
        for data, text in items:
            combo.addItem(text, data)
    combo.setCurrentIndex(max(0, combo.findData(current)))
    combo.blockSignals(False)


class TargetSection(StepCard):
    def __init__(self, state: CalibrationState, queue: WriteQueue,
                 on_message: Callable[[str, str], None], parent: Optional[QWidget] = None) -> None:
        super().__init__(TEXT["calibrateHeading"], parent)
        self._state, self._queue, self._on_message = state, queue, on_message
        self._mine = False
        self._target_key = None
        self._list_key = None
        self._fits_key = None
        body = self.body

        # ---- target ----
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(theme.set_role(QLabel(TEXT["target"]), "faint"))
        self.target_combo = QComboBox()
        self.target_combo.setEditable(True)
        self.target_combo.setInsertPolicy(QComboBox.NoInsert)
        comp = QCompleter(self.target_combo.model(), self.target_combo)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self.target_combo.setCompleter(comp)
        col.addWidget(self.target_combo)
        body.addLayout(col)
        self.measured_label = theme.set_role(QLabel(""), "faint")
        body.addWidget(self.measured_label)

        # ---- reference picker ----
        self.no_refs_label = note_label(TEXT["noReferences"], "muted")
        body.addWidget(self.no_refs_label)
        self.picker = QWidget()
        pl = QVBoxLayout(self.picker)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(6)
        filt = QHBoxLayout()
        filt.setSpacing(8)
        self.material = QComboBox()
        self.temp = QComboBox()
        self.sort = QComboBox()
        for label, w in ((TEXT["batchMaterial"], self.material), (TEXT["temperature"], self.temp),
                         (TEXT["sortBy"], self.sort)):
            c = QVBoxLayout()
            c.setSpacing(2)
            c.addWidget(theme.set_role(QLabel(label), "faint"))
            c.addWidget(w)
            filt.addLayout(c, 1)
        for key, text in SORTS:
            self.sort.addItem(TEXT[text], key)
        self.near_box = QCheckBox(TEXT["nearTargetOnly"])
        self.near_pct = QLineEdit(js_number_to_string(state.ref_near_pct))
        self.near_pct.setFixedWidth(56)
        filt.addWidget(self.near_box)
        filt.addWidget(self.near_pct)
        filt.addWidget(QLabel("%"))
        pl.addLayout(filt)

        links = QHBoxLayout()
        self.select_all = link_button(TEXT["selectAllVisible"])
        self.clear = link_button(TEXT["clearSelection"])
        self.counter = theme.set_role(QLabel(""), "faint")
        links.addWidget(self.select_all)
        links.addWidget(self.clear)
        links.addStretch(1)
        links.addWidget(self.counter)
        pl.addLayout(links)
        self.near_hint = note_label(TEXT["nearTargetHint"])
        pl.addWidget(self.near_hint)
        self.no_match_label = note_label(TEXT["noRefsMatch"], "muted")
        pl.addWidget(self.no_match_label)
        self.list = QListWidget()
        self.list.setMinimumHeight(110)
        self.list.setMaximumHeight(260)
        pl.addWidget(self.list)
        body.addWidget(self.picker)

        self.spread_label = theme.set_role(QLabel(""), "pill", tone="warn")
        self.spread_label.setWordWrap(True)
        body.addWidget(self.spread_label)

        # ---- lag source ----
        self.source_row = QWidget()
        sl = QHBoxLayout(self.source_row)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(theme.set_role(QLabel(TEXT["lagSource"] + ":"), "section"))
        self.curve_radio = QRadioButton(TEXT["sourceCurve"])
        self.direct_radio = QRadioButton(TEXT["sourceDirect"])
        grp = QButtonGroup(self)
        grp.addButton(self.curve_radio)
        grp.addButton(self.direct_radio)
        self.source_hint = theme.set_role(QLabel(""), "faint")
        sl.addWidget(self.curve_radio)
        sl.addWidget(self.direct_radio)
        sl.addWidget(self.source_hint)
        sl.addStretch(1)
        body.addWidget(self.source_row)
        self.too_few_label = note_label(TEXT["tooFewPoints"], "muted")
        body.addWidget(self.too_few_label)
        self.direct_label = note_label("", "muted")
        body.addWidget(self.direct_label)

        # ---- models ----
        self.models = QWidget()
        ml = QVBoxLayout(self.models)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(4)
        ml.addWidget(theme.set_role(QLabel(TEXT["modelHeading"]), "section"))
        self.model_table = QTableWidget(0, 6)
        self.model_table.setHorizontalHeaderLabels(["", TEXT["model"], TEXT["formula"], "RMS (s)", "R²", "n"])
        self.model_table.verticalHeader().hide()
        self.model_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.model_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.model_table.setMaximumHeight(170)
        self.model_radios = {}
        self._model_group = QButtonGroup(self)
        ml.addWidget(self.model_table)
        self.range_label = theme.set_role(QLabel(""), "faint")
        ml.addWidget(self.range_label)
        body.addWidget(self.models)

        self.chart = FitChart()
        body.addWidget(self.chart)

        # ---- result ----
        self.result = QFrame()
        theme.set_role(self.result, "card")
        rl = QVBoxLayout(self.result)
        rl.setSpacing(6)
        self.applied_label = QLabel("")
        self.applied_label.setWordWrap(True)
        rl.addWidget(self.applied_label)
        self.no_period_label = theme.set_role(QLabel(TEXT["noPeriod"]), "danger")
        rl.addWidget(self.no_period_label)
        self.range_warn = self._warn_label(rl, "danger")
        self.copy_warn = self._warn_label(rl, "warn")
        self.mismatch_warn = self._warn_label(rl, "danger")
        self.cards = QWidget()
        grid = QGridLayout(self.cards)
        grid.setContentsMargins(0, 0, 0, 0)
        self.card_labels = {}
        for c, key in enumerate(("lag", "phi", "phase", "comb")):
            box = QFrame()
            theme.set_role(box, "card")
            bl = QVBoxLayout(box)
            bl.setSpacing(2)
            title = theme.set_role(QLabel(""), "faint")
            value = QLabel("")
            f = value.font()
            f.setBold(True)
            value.setFont(f)
            raw = theme.set_role(QLabel(""), "faint")
            for w in (title, value, raw):
                bl.addWidget(w)
            self.card_labels[key] = (title, value, raw)
            grid.addWidget(box, 0, c)
        rl.addWidget(self.cards)
        self.not_cal_label = theme.set_role(QLabel(TEXT["notCalibratable"]), "danger")
        self.not_cal_label.setWordWrap(True)
        rl.addWidget(self.not_cal_label)
        self.save_button = QPushButton(TEXT["saveCalibrated"])
        theme.set_role(self.save_button, "primary")
        brow = QHBoxLayout()
        brow.addWidget(self.save_button)
        brow.addStretch(1)
        rl.addLayout(brow)
        body.insertWidget(body.indexOf(self.models), self.result)   # the Save card stays near the top

        # ---- wiring ----
        self.target_combo.currentIndexChanged.connect(self._on_target)
        self.material.currentIndexChanged.connect(
            lambda _i: setattr(state, "ref_filter_material", self.material.currentData() or ""))
        self.temp.currentIndexChanged.connect(
            lambda _i: setattr(state, "ref_filter_temp", self.temp.currentData() or ""))
        self.sort.currentIndexChanged.connect(lambda _i: setattr(state, "ref_sort", self.sort.currentData()))
        self.near_box.toggled.connect(lambda on: setattr(state, "ref_near_only", bool(on)))
        self.near_pct.textChanged.connect(self._on_pct)
        self.select_all.clicked.connect(self._select_all)
        self.clear.clicked.connect(lambda: setattr(state, "selected_ref_ids", []))
        self.list.itemChanged.connect(self._on_item)
        self.curve_radio.clicked.connect(lambda: setattr(state, "lag_source", "curve"))
        self.direct_radio.clicked.connect(lambda: setattr(state, "lag_source", "direct"))
        self.model_table.cellClicked.connect(self._on_model_row)
        self.save_button.clicked.connect(self.save)
        state.changed.connect(self.refresh)
        queue.busy_changed.connect(lambda _b: self._sync_save())
        queue.reserved_changed.connect(lambda _b: self._sync_save())
        self.refresh()

    @staticmethod
    def _warn_label(layout, tone: str) -> QLabel:
        lab = theme.set_role(QLabel(""), "pill", tone=tone)
        lab.setWordWrap(True)
        layout.addWidget(lab)
        return lab

    # ---- user actions ----
    def _on_target(self, _i: int) -> None:
        self._state.target_id = self.target_combo.currentData()

    def _on_pct(self, text: str) -> None:
        v = parse_number(text)
        if v == v:  # a number
            self._state.ref_near_pct = v

    def _on_item(self, item: QListWidgetItem) -> None:
        i = item.data(Qt.UserRole)
        ids = list(self._state.selected_ref_ids)
        if item.checkState() == Qt.Checked:
            lag = next((x.lag for x in self._state.picker if x.ref["id"] == i and _has_period(x.ref)), None)
            if lag is None:     # a reference without a lag or period can never be ticked
                self.list.blockSignals(True)
                item.setCheckState(Qt.Unchecked)
                self.list.blockSignals(False)
                return
            if i not in ids:
                ids.append(i)
        else:
            ids = [x for x in ids if x != i]
        self._state.selected_ref_ids = ids

    def _select_all(self) -> None:
        ids = list(self._state.selected_ref_ids)
        ids += [x.ref["id"] for x in self._state.picker if x.lag is not None and _has_period(x.ref)
                and x.ref["id"] not in ids]
        self._state.selected_ref_ids = ids

    def _on_model_row(self, row: int, _col: int) -> None:
        item = self.model_table.item(row, 1)
        if item is not None:
            self._state.model_kind = item.data(Qt.UserRole)

    def _editing_target(self) -> bool:
        edit = self.target_combo.lineEdit()
        return edit is not None and edit.hasFocus()

    # ---- showing ----
    def refresh(self) -> None:
        s = self._state
        target = s.target
        refs = s.references
        # target combo
        cands = s.non_references
        key = [(a["id"], label_of(a)) for a in cands]
        editing = self._editing_target()
        typed = self.target_combo.currentText()
        self.target_combo.blockSignals(True)
        if key != self._target_key:
            self._target_key = key
            self.target_combo.clear()
            self.target_combo.addItem(TEXT["chooseTarget"], None)
            for i, text in key:
                self.target_combo.addItem(text, i)
        if editing:
            self.target_combo.setEditText(typed)      # the user is typing: never reset the editor under them
        else:
            self.target_combo.setCurrentIndex(max(0, self.target_combo.findData(s.target_id)))
        self.target_combo.blockSignals(False)
        self.measured_label.setVisible(target is not None)
        if target is not None:
            self.measured_label.setText("%s: %s s" % (TEXT["measuredLag"], num(target.get("raw_lag_dt"))))

        # picker
        self.no_refs_label.setVisible(not refs)
        self.picker.setVisible(bool(refs))
        sel_ids = set(s.selected_ref_ids)
        if refs:
            _fill(self.material, [("", TEXT["all"])] + [(m, m) for m in all_materials(refs)], s.ref_filter_material)
            _fill(self.temp, [("", TEXT["all"])] + [(t, "%s °C" % t) for t in
                                                    ref_temps(refs, s.ref_filter_material)], s.ref_filter_temp)
            self.sort.blockSignals(True)
            self.sort.setCurrentIndex(max(0, self.sort.findData(s.ref_sort)))
            model = self.sort.model()
            for r in (1, 2):
                it = model.item(r)
                if it is not None:
                    it.setEnabled(target is not None)
            self.sort.blockSignals(False)
            self.near_box.blockSignals(True)
            self.near_box.setChecked(s.ref_near_only)
            self.near_box.setEnabled(target is not None)
            self.near_box.blockSignals(False)
            self.near_pct.setEnabled(s.ref_near_only and target is not None)
            rows = s.picker
            key = [(x.ref["id"], x.lag, x.true_lag, x.d_t, x.d_p, x.ref.get("reference_alpha_mm2s"),
                    label_of(x.ref)) for x in rows]
            self.list.blockSignals(True)
            if key != self._list_key:
                self._list_key = key
                self.list.clear()
                for x in rows:
                    ref = x.ref
                    lines = ["%s\nα known = %s mm²/s · %s = %s · %s = %s" % (
                        label_of(ref), num(ref.get("reference_alpha_mm2s"), 3),
                        TEXT["trueLag"], "%s s" % num(x.true_lag) if x.true_lag is not None else DASH,
                        TEXT["deviceLag"], "%s s" % num(x.lag) if x.lag is not None else DASH)]
                    if x.d_t is not None:
                        lines[0] += " · ΔT = %s °C" % _signed(x.d_t)
                    if x.d_p is not None:
                        lines[0] += " · ΔP = %s s" % _signed(x.d_p)
                    it = QListWidgetItem(lines[0])
                    flags = it.flags() | Qt.ItemIsUserCheckable
                    if x.lag is None or not _has_period(ref):
                        flags &= ~Qt.ItemIsEnabled
                    if x.lag is not None and not _has_period(ref):
                        it.setToolTip(TEXT["refNoPeriod"])
                    it.setFlags(flags)
                    it.setData(Qt.UserRole, ref["id"])
                    self.list.addItem(it)
            for i in range(self.list.count()):
                it = self.list.item(i)
                it.setCheckState(Qt.Checked if it.data(Qt.UserRole) in sel_ids else Qt.Unchecked)
            self.list.blockSignals(False)
            self.no_match_label.setVisible(not rows)
            self.list.setVisible(bool(rows))
            self.near_hint.setVisible(s.ref_near_only)
            self.counter.setText("%d / %d %s · %d %s" % (len(rows), len(s.ref_lags), TEXT["shown"],
                                                         len(s.selected), TEXT["refsUsed"]))

        # temperature spread
        spread = temp_spread(s.selected)
        warn = spread is not None and spread > TEMP_SPREAD_WARN_C
        self.spread_label.setVisible(warn)
        if warn:
            self.spread_label.setText("%s — %s %s °C" % (TEXT["tempSpreadWarn"], TEXT["spread"], num(spread, 1)))

        # lag source
        selected = s.selected
        source = s.source
        fits = s.fits
        self.source_row.setVisible(bool(selected))
        self.curve_radio.setEnabled(bool(fits))
        for radio, on in ((self.curve_radio, source == "curve"), (self.direct_radio, source == "direct")):
            radio.blockSignals(True)
            radio.setAutoExclusive(False)
            radio.setChecked(on)
            radio.setAutoExclusive(True)
            radio.blockSignals(False)
        self.source_hint.setText(TEXT["sourceDirectHint"] if source == "direct" else TEXT["sourceCurveHint"])
        self.too_few_label.setVisible(bool(selected) and not fits)
        show_direct = source == "direct" and bool(selected)
        self.direct_label.setVisible(show_direct)
        if show_direct:
            text = TEXT["directSingle"] if len(selected) == 1 else "%s %d" % (TEXT["directMean"], len(selected))
            if s.direct_mean_period is not None:
                text += " · %s ≈ %s s" % (TEXT["period"], num(s.direct_mean_period, 0))
            self.direct_label.setText(text)

        # models
        fit = s.fit
        show_models = source == "curve" and bool(fits)
        self.models.setVisible(show_models)
        self._fill_models(fits, fit)
        if fit is not None:
            self.range_label.setText("%s: %s–%s s%s" % (
                TEXT["fitRange"], num(fit.p_min, 0), num(fit.p_max, 0),
                " · " + TEXT["bestByRms"] if s.model_kind is None else ""))
        self.chart.set_data(fit if source == "curve" else None, selected, target)

        # result
        applied = s.applied
        cal = s.calibrated
        no_period = target is not None and applied is None and not _has_period(target)
        self.result.setVisible(target is not None and (applied is not None or no_period))
        self.no_period_label.setVisible(no_period)
        if no_period:
            for w in (self.applied_label, self.range_warn, self.copy_warn, self.mismatch_warn,
                      self.cards, self.not_cal_label):
                w.hide()
        if target is not None and applied is not None:
            via = (TEXT["sourceDirect"] if source == "direct"
                   else (TEXT["model_" + fit.kind] if fit else ""))
            self.applied_label.setText("%s: %s s (%d %s%s)" % (
                TEXT["appliedLag"], num(applied.lag), len(selected), TEXT["refsUsed"], ", " + via if via else ""))
            oor = applied.out_of_range and fit is not None
            self.range_warn.setVisible(oor)
            if oor:
                self.range_warn.setText("%s — P = %s s, %s %s–%s s" % (
                    TEXT["outOfRangeWarn"], num(target.get("period_t"), 0), TEXT["fitRange"],
                    num(fit.p_min, 0), num(fit.p_max, 0)))
            copies = s.copies.get(target["id"], [])
            self.copy_warn.setVisible(bool(copies))
            if copies:
                self.copy_warn.setText("%s (%s) — %s" % (
                    TEXT["alreadyCalibrated"], ", ".join("#%s" % c for c in copies), TEXT["saveMakesAnother"]))
            self.mismatch_warn.setVisible(applied.period_mismatch)
            if applied.period_mismatch:
                ratio = " (%s×)" % num(applied.ratio, 2) if applied.ratio is not None else ""
                self.mismatch_warn.setText("%s — %s P = %s s, %s ≈ %s s%s" % (
                    TEXT["periodMismatchWarn"], TEXT["target"], num(target.get("period_t"), 0),
                    TEXT["refsUsed"], num(s.direct_mean_period, 0), ratio))
            self.cards.setVisible(cal is not None)
            self.not_cal_label.setVisible(cal is None)
            if cal is not None:
                L = self.card_labels
                L["lag"][0].setText(TEXT["correctedLag"])
                L["lag"][1].setText("%s s" % num(cal.net_lag_dt))
                L["lag"][2].setText("")
                L["phi"][0].setText("φ net")
                L["phi"][1].setText("%s rad" % num(cal.net_phase_phi, 4))
                L["phi"][2].setText("")
                L["phase"][0].setText("α phase (cal) — %s" % TEXT["primary"])
                L["phase"][1].setText("%s mm²/s" % format_alpha(cal.alpha_phase_cal))
                L["phase"][2].setText("raw %s" % format_alpha(target.get("alpha_phase_raw")))
                L["comb"][0].setText("α comb (cal) — %s" % TEXT["crossCheck"])
                L["comb"][1].setText("%s mm²/s" % format_alpha(cal.alpha_combined_cal))
                L["comb"][2].setText("raw %s" % format_alpha(target.get("alpha_combined_raw")))

        # card status
        if source == "curve":
            self.set_status("%s · RMS %s s" % (TEXT["model_" + fit.kind], num(fit.rms)) if fit
                            else TEXT["statusNoFit"], fit is not None)
        else:
            ok = s.direct_lag is not None
            self.set_status(TEXT["sourceDirect"] if ok else TEXT["statusNoFit"], ok)
        self._sync_save()

    def _fill_models(self, fits, fit) -> None:
        key = [(f.kind, f.label, f.rms, f.r2, f.n) for f in fits]
        if key != self._fits_key:
            self._fits_key = key
            for b in list(self._model_group.buttons()):
                self._model_group.removeButton(b)
            self.model_radios = {}
            t = self.model_table
            t.setRowCount(len(fits))
            for r, f in enumerate(fits):
                radio = QRadioButton()
                radio.clicked.connect(lambda _=False, k=f.kind: setattr(self._state, "model_kind", k))
                self._model_group.addButton(radio)
                self.model_radios[f.kind] = radio
                t.setCellWidget(r, 0, radio)
                cells = [TEXT["model_" + f.kind], f.label, num(f.rms), num(f.r2, 4), str(f.n)]
                for c, text in enumerate(cells, start=1):
                    it = QTableWidgetItem(text)
                    if c == 1:
                        it.setData(Qt.UserRole, f.kind)
                    if c >= 3:
                        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    t.setItem(r, c, it)
            t.resizeColumnsToContents()
            t.setFixedHeight(min(170, 32 + 28 * len(fits)))
        for kind, radio in self.model_radios.items():
            radio.blockSignals(True)
            radio.setChecked(fit is not None and fit.kind == kind)
            radio.blockSignals(False)

    # ---- save ----
    @property
    def saving(self) -> bool:
        """This section's save is in progress (graph wait, write, or waiting for the refreshed rows)."""
        return self._mine and self._queue.reserved

    def _sync_save(self) -> None:
        self.save_button.setEnabled(self._state.calibrated is not None and not self._queue.reserved
                                    and not self._queue.busy)

    def save(self) -> None:
        s = self._state
        if self._queue.busy or not self._queue.reserve():
            return
        self._mine = True
        target, applied, cal = s.target, s.applied, s.calibrated
        if target is None or applied is None or cal is None:
            self._abort()
            return
        # everything the row needs is read now: the state may change while the graph is fetched
        lag = applied.lag
        ref_ids = [x.ref["id"] for x in s.selected]
        model = calibration_model_string(s.source, s.fit, s.direct_lag)

        def with_graph(graphs) -> None:
            self._no_plot = graphs.get(target["id"]) is None
            try:
                row = build_calibrated_row(target, lag, cal, graphs.get(target["id"]), ref_ids, model)
                started = self._queue.run([WriteOp("insert", None, row, "#%s" % target["id"])], self._saved)
            except Exception as e:      # never leave the reservation held
                self._abort("%s: %s" % (TEXT["saveFailed"], e))
                return
            if not started:
                self._abort(TEXT["saveInProgress"])

        try:
            self._queue.with_graphs([target["id"]], with_graph)
        except Exception as e:
            self._abort("%s: %s" % (TEXT["saveFailed"], e))

    def _abort(self, text: str = "") -> None:
        self._mine = False
        self._queue.release()
        if text:
            self._on_message(text, "error")

    def _saved(self, summary) -> None:
        try:
            if summary.failures or summary.aborted:
                self._on_message("%s: %s" % (TEXT["saveFailed"], failure_text(summary)), "error")
            elif getattr(self, "_no_plot", False):
                self._on_message("%s · %s" % (TEXT["saved"], TEXT["noPlotSaved"].format(n=1)), "warn")
            else:
                self._on_message(TEXT["saved"], "ok")
        finally:
            # the new copy shows up in the rows only after the loader's refresh: stay reserved until then
            self._queue.release(after_refresh=summary.done > 0)
