"""Batch calibration: one calibrated copy per picked run of one material (Plan 4, Task 9).

State used: batch_material / batch_temp / batch_picked (None = follow the default pick: every
calibratable run without a copy). The lag comes from the shared source / fit above. Save all asks
once, fetches the graphs once, then inserts sequentially through the tab's WriteQueue; a failure
never stops the rest, a login failure does. The section holds its own `saving` state from the click
until the batch has finished, so a double click cannot start a second batch."""
from __future__ import annotations

from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ctwa import theme
from ctwa.analysis.calibration_batch import (batch_calibratable, batch_default_ids, batch_ok, batch_report,
                                             build_calibrated_row, calibration_model_string, pick_clear,
                                             pick_default, pick_in_range, pick_recalibrate, toggle_pick)
from ctwa.analysis.calibration_logic import all_materials, num, temps_for
from ctwa.results.helpers import format_alpha
from ctwa.ui.calibration.common import StepCard, link_button, note_label
from ctwa.ui.calibration.state import CalibrationState
from ctwa.ui.calibration.texts import TEXT
from ctwa.ui.calibration.writes import WriteOp, WriteQueue

HEADERS = ["", "run", "period", "α raw", "appliedLag", "correctedLag", "α cal", ""]
STATUS_TEXT = {"ok": "✓ %s" % TEXT["statusOk"], "outOfRange": "⚠️ %s" % TEXT["statusOutOfRange"],
               "notCalibratable": "✕ %s" % TEXT["statusNotCalibratable"]}
STATUS_COLOR = {"ok": "#2e7d32", "outOfRange": "#b26a00", "notCalibratable": "#c62828"}
DIM = QColor(130, 130, 130)


def _heading() -> str:
    h = TEXT["batchHeading"]
    return h if h[:1].isdigit() else "3. " + h


class BatchSection(StepCard):
    def __init__(self, state: CalibrationState, queue: WriteQueue, on_message: Callable[[str, str], None],
                 confirm: Callable[[str, str, str], bool], parent: Optional[QWidget] = None) -> None:
        super().__init__(_heading(), parent)
        self._state, self._queue, self._on_message, self._confirm = state, queue, on_message, confirm
        self._mine = False
        self._running = False
        self._table_key = None
        body = self.body
        body.addWidget(note_label(TEXT["batchNote"], "muted"))
        self.needs_fit_label = note_label(TEXT["batchNeedsFit"], "muted")
        body.addWidget(self.needs_fit_label)

        self.content = QWidget()
        cl = QVBoxLayout(self.content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(6)
        row = QHBoxLayout()
        self.material = QComboBox()
        self.temp = QComboBox()
        for label, w in ((TEXT["batchMaterial"], self.material), (TEXT["temperature"], self.temp)):
            c = QVBoxLayout()
            c.setSpacing(2)
            c.addWidget(theme.set_role(QLabel(label), "faint"))
            c.addWidget(w)
            row.addLayout(c)
        row.addStretch(1)
        cl.addLayout(row)

        self.shortcuts = QWidget()
        sl = QHBoxLayout(self.shortcuts)
        sl.setContentsMargins(0, 0, 0, 0)
        self.default_link = link_button(TEXT["selectAllVisible"])
        self.recal_link = link_button(TEXT["includeRecalibrate"])
        self.clear_link = link_button(TEXT["clearSelection"])
        self.range_link = link_button(TEXT["selectInRangeOnly"])
        self.counter = theme.set_role(QLabel(""), "faint")
        for w in (self.default_link, self.recal_link, self.clear_link, self.range_link):
            sl.addWidget(w)
        sl.addStretch(1)
        sl.addWidget(self.counter)
        cl.addWidget(self.shortcuts)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(
            ["", TEXT["run"], "%s (s)" % TEXT["period"], "α raw", "%s (s)" % TEXT["appliedLag"],
             "%s (s)" % TEXT["correctedLag"], "α cal", ""])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setMinimumHeight(140)
        self.table.setMaximumHeight(420)
        cl.addWidget(self.table)

        act = QHBoxLayout()
        self.save_button = QPushButton("")
        theme.set_role(self.save_button, "primary")
        self.progress_label = theme.set_role(QLabel(""), "faint")
        act.addWidget(self.save_button)
        act.addWidget(self.progress_label)
        act.addStretch(1)
        cl.addLayout(act)
        body.addWidget(self.content)

        self.material.currentIndexChanged.connect(
            lambda _i: setattr(state, "batch_material", self.material.currentData() or ""))
        self.temp.currentIndexChanged.connect(
            lambda _i: setattr(state, "batch_temp", self.temp.currentData() or ""))
        self.default_link.clicked.connect(lambda: setattr(state, "batch_picked", pick_default()))
        self.recal_link.clicked.connect(lambda: setattr(state, "batch_picked", pick_recalibrate(state.batch_rows)))
        self.clear_link.clicked.connect(lambda: setattr(state, "batch_picked", pick_clear()))
        self.range_link.clicked.connect(lambda: setattr(state, "batch_picked", pick_in_range(state.batch_rows)))
        self.table.itemChanged.connect(self._on_item)
        self.save_button.clicked.connect(self.save)
        state.changed.connect(self.refresh)
        queue.busy_changed.connect(lambda _b: self._sync_save())
        queue.reserved_changed.connect(lambda _b: self._sync_save())
        queue.progress.connect(self._on_progress)
        self.refresh()

    @property
    def saving(self) -> bool:
        """This section's save is in progress (graph wait, writes, or waiting for the refreshed rows)."""
        return self._mine and self._queue.reserved

    def has_lag(self) -> bool:
        s = self._state
        return (s.fit is not None) if s.source == "curve" else (s.direct_lag is not None)

    def picked_ids(self) -> List[int]:
        """Ids ticked in the table, in table order."""
        return [r.a["id"] for r in batch_ok(self._state.batch_rows, self._state.batch_picked)]

    # ---- showing ----
    def refresh(self) -> None:
        s = self._state
        has = self.has_lag()
        self.needs_fit_label.setVisible(not has)
        self.content.setVisible(has)
        rows = s.batch_rows
        ok = batch_ok(rows, s.batch_picked)
        cal = batch_calibratable(rows)
        if s.batch_material:
            self.set_status("%d / %d %s" % (len(ok), len(rows), TEXT["statusReady"]), len(ok) > 0)
        else:
            self.set_status("", False)
        if not has:
            self._sync_save()
            return
        mats = all_materials(s.non_references)
        self._fill(self.material, [("", "— %s —" % TEXT["none"])] + [(m, m) for m in mats], s.batch_material)
        self._fill(self.temp, [("", TEXT["all"])] + [(t, "%s °C" % t) for t in
                                                    temps_for(s.non_references, s.batch_material)], s.batch_temp)
        self.temp.setEnabled(bool(s.batch_material))
        self.shortcuts.setVisible(bool(rows))
        self.table.setVisible(bool(rows))
        self.recal_link.setVisible(any(r.existing for r in cal))
        self.counter.setText("%d / %d %s" % (len(ok), len(cal), TEXT["selectedForSave"]))
        self._fill_table(rows, s.batch_picked)
        self._sync_save()

    @staticmethod
    def _fill(combo: QComboBox, items, current) -> None:
        have = [(combo.itemData(i), combo.itemText(i)) for i in range(combo.count())]
        combo.blockSignals(True)
        if have != items:
            combo.clear()
            for data, text in items:
                combo.addItem(text, data)
        combo.setCurrentIndex(max(0, combo.findData(current)))
        combo.blockSignals(False)

    def _fill_table(self, rows, picked) -> None:
        default_ids = set(batch_default_ids(rows))
        picked_set = default_ids if picked is None else set(picked)
        key = [(r.a["id"], r.a.get("model_name"), r.a.get("period_t"), r.a.get("alpha_phase_raw"), r.lag,
                None if r.result is None else (r.result.net_lag_dt, r.result.alpha_phase_cal), r.status,
                tuple(r.existing), r.a["id"] in picked_set) for r in rows]
        if key == self._table_key:
            return
        self._table_key = key
        t = self.table
        t.blockSignals(True)
        t.setRowCount(len(rows))
        right = Qt.AlignRight | Qt.AlignVCenter
        for n, r in enumerate(rows):
            a = r.a
            on = r.result is not None and a["id"] in picked_set
            dim = r.status == "notCalibratable" or not on
            box = QTableWidgetItem("")
            box.setData(Qt.UserRole, a["id"])
            if r.result is None:
                box.setFlags(Qt.ItemIsSelectable)
            else:
                box.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            box.setCheckState(Qt.Checked if on else Qt.Unchecked)
            t.setItem(n, 0, box)
            status = STATUS_TEXT[r.status]
            if r.existing:
                status += "\n⚠️ %s (%s)" % (TEXT["alreadyCalibrated"], ", ".join("#%s" % c for c in r.existing))
            cells = ["#%s %s" % (a["id"], a.get("model_name")), num(a.get("period_t"), 0),
                     format_alpha(a.get("alpha_phase_raw")), num(r.lag),
                     num(r.result.net_lag_dt) if r.result else num(None),
                     format_alpha(r.result.alpha_phase_cal) if r.result else "—", status]
            for c, text in enumerate(cells, start=1):
                it = QTableWidgetItem(text)
                it.setTextAlignment(((Qt.AlignLeft if c in (1, 7) else right)) | Qt.AlignVCenter)
                if c == 6 and r.result:
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                if dim:
                    it.setForeground(QBrush(DIM))
                elif c == 7:
                    it.setForeground(QBrush(QColor(STATUS_COLOR[r.status])))
                t.setItem(n, c, it)
        t.resizeColumnsToContents()
        t.resizeRowsToContents()
        t.blockSignals(False)

    # ---- user actions ----
    def _on_item(self, item: QTableWidgetItem) -> None:
        if item.column() != 0 or item.flags() & Qt.ItemIsUserCheckable == 0:
            return
        rows = self._state.batch_rows
        self._state.batch_picked = toggle_pick(self._state.batch_picked, batch_default_ids(rows),
                                               item.data(Qt.UserRole), item.checkState() == Qt.Checked)

    def _sync_save(self) -> None:
        n = len(self.picked_ids()) if self.has_lag() else 0
        self.save_button.setText("%s (%d)" % (TEXT["saveAll"], n))
        self.save_button.setEnabled(n > 0 and not self._queue.reserved and not self._queue.busy)

    def _on_progress(self, done: int, total: int) -> None:
        if self._running and done < total:
            self.progress_label.setText("%d / %d" % (done + 1, total))

    # ---- save ----
    def save(self) -> None:
        s = self._state
        if self._queue.busy or not self.has_lag() or not self.picked_ids():
            return
        if not self._queue.reserve():
            return
        self._mine = True
        rows0 = batch_ok(s.batch_rows, s.batch_picked)
        n0 = len(rows0)
        confirmed = self._confirm(TEXT["confirmBatchTitle"].format(n=n0, name=s.batch_material),
                                  TEXT["confirmBatchMessage"], "%s (%d)" % (TEXT["saveAll"], n0))
        if not confirmed:
            self._abort()
            return
        try:
            # one snapshot, taken after the dialog returned: the rows, the report numbers, the
            # reference ids and the model all describe the same state
            rows = batch_ok(s.batch_rows, s.batch_picked)
            all_rows = list(s.batch_rows)
            n = len(rows)
            n_rows, n_cal = len(all_rows), len(batch_calibratable(all_rows))
            saved_ids = {r.a["id"] for r in rows}
            # had_copies: rows that already had a copy AND are not saved now (the webapp's hadCopies)
            had_copies = sum(1 for r in all_rows if r.existing and r.a["id"] not in saved_ids)
            ref_ids = [x.ref["id"] for x in s.selected]
            model = calibration_model_string(s.source, s.fit, s.direct_lag)
            if n == 0:
                self._abort()
                return

            def with_graphs(graphs) -> None:
                self._no_plot = sum(1 for r in rows if graphs.get(r.a["id"]) is None)
                try:
                    ops = [WriteOp("insert", None, build_calibrated_row(
                        r.a, r.lag, r.result, graphs.get(r.a["id"]), ref_ids, model), "#%s" % r.a["id"])
                        for r in rows]
                    self._running = True
                    self.progress_label.setText("1 / %d" % n)
                    started = self._queue.run(
                        ops, lambda summary: self._done(summary, n, n_rows, n_cal, had_copies))
                except Exception as e:
                    self._abort("%s: %s" % (TEXT["saveFailed"], e))
                    return
                if not started:
                    self._abort(TEXT["saveInProgress"])

            self._queue.with_graphs([r.a["id"] for r in rows], with_graphs)
        except Exception as e:
            self._abort("%s: %s" % (TEXT["saveFailed"], e))

    def _abort(self, text: str = "") -> None:
        self._running = False
        self._mine = False
        self.progress_label.setText("")
        self._queue.release()
        if text:
            self._on_message(text, "error")

    def _done(self, summary, n: int, n_rows: int, n_cal: int, had_copies: int) -> None:
        self._running = False
        self.progress_label.setText("")
        try:
            text = batch_report(summary.done, n, n_rows, n_cal, had_copies, summary.failures)
            if summary.aborted:
                text += " · %s · %s" % (TEXT["loginNeeded"], TEXT["writtenOf"].format(n=summary.done, m=summary.total))
            no_plot = getattr(self, "_no_plot", 0)
            if no_plot and summary.done:
                text += " · " + TEXT["noPlotSaved"].format(n=min(no_plot, summary.done))
            self._on_message(text, "ok" if not (summary.failures or summary.aborted or (no_plot and summary.done))
                             else "warn")
        finally:
            # stay reserved until the refreshed rows (with the new copies) have reached the tab
            self._queue.release(after_refresh=summary.done > 0)
