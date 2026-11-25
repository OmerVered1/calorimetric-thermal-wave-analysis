"""The reference runs, their known alpha (editable in place) and the lags they give (Task 6).

Like the webapp's table: every reference, a search box, Unmark per row. Writes go through the tab's
WriteQueue, one UPDATE per change, only the changed fields."""
from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ctwa import theme
from ctwa.analysis.jsmath import js_number_to_string
from ctwa.analysis.calibration_logic import label_of, num
from ctwa.results.helpers import row_matches
from ctwa.ui.calibration.common import failure_text, note_label, parse_number
from ctwa.ui.calibration.state import CalibrationState
from ctwa.ui.calibration.texts import TEXT
from ctwa.ui.calibration.writes import WriteOp, WriteQueue

SAVED_MS = 2500
HEADERS = ["run", "temperature", "period", "knownAlpha", "measuredLag", "trueLag", "deviceLag"]
DASH = "—"


class ReferenceTable(QWidget):
    def __init__(self, state: CalibrationState, queue: WriteQueue,
                 on_message: Callable[[str, str], None], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._state, self._queue, self._on_message = state, queue, on_message
        self._pending: Dict[int, float] = {}
        self._status: Dict[int, str] = {}
        self._key = None
        self.alpha_edits: Dict[int, QLineEdit] = {}
        self.status_labels: Dict[int, QLabel] = {}
        self.unmark_buttons: Dict[int, QPushButton] = {}
        self._row_of: Dict[int, int] = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        head = QHBoxLayout()
        self.heading = theme.set_role(QLabel(""), "section")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search")
        self.search.setClearButtonEnabled(True)
        head.addWidget(self.heading)
        head.addStretch(1)
        head.addWidget(self.search)
        lay.addLayout(head)
        self.empty_label = note_label(TEXT["noReferences"], "muted")
        lay.addWidget(self.empty_label)
        self.table = QTableWidget(0, len(HEADERS) + 1)
        self.table.setHorizontalHeaderLabels([TEXT[h] for h in HEADERS] + [""])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setMinimumHeight(140)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, self.table.horizontalHeader().ResizeMode.Stretch)
        lay.addWidget(self.table)

        self.search.textChanged.connect(self._apply_search)
        state.changed.connect(self.refresh)
        queue.busy_changed.connect(lambda _b: self._sync_busy())
        self.refresh()

    # ---- showing ----
    def refresh(self) -> None:
        lags = self._state.ref_lags
        key = [(x.ref["id"], label_of(x.ref), x.ref.get("temperature_c"), x.ref.get("period_t"),
                x.ref.get("reference_alpha_mm2s"), x.ref.get("raw_lag_dt"), x.lag, x.true_lag) for x in lags]
        self.heading.setText("%s (%d)" % (TEXT["referenceRuns"], len(lags)))
        self.empty_label.setVisible(not lags)
        self.table.setVisible(bool(lags))
        self.search.setVisible(bool(lags))
        if key == self._key:
            return
        self._key = key
        self._rebuild(lags)

    def _rebuild(self, lags) -> None:
        self.alpha_edits, self.status_labels, self.unmark_buttons, self._row_of = {}, {}, {}, {}
        self.table.setRowCount(len(lags))
        right = Qt.AlignRight | Qt.AlignVCenter
        for r, x in enumerate(lags):
            ref = x.ref
            i = ref["id"]
            self._row_of[i] = r
            cells = [label_of(ref), "%s °C" % num(ref.get("temperature_c"), 0), "%s s" % num(ref.get("period_t"), 0)]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                it.setData(Qt.UserRole, i)
                it.setTextAlignment((Qt.AlignLeft if c == 0 else right) | Qt.AlignVCenter)
                self.table.setItem(r, c, it)
            # known alpha: an edit and a small status
            cell = QWidget()
            h = QHBoxLayout(cell)
            h.setContentsMargins(4, 0, 4, 0)
            h.setSpacing(4)
            edit = QLineEdit(self._alpha_text(ref))
            edit.setFixedWidth(80)
            status = theme.set_role(QLabel(self._status.get(i, "")), "faint")
            h.addWidget(edit)
            h.addWidget(status)
            h.addStretch(1)
            edit.editingFinished.connect(lambda i=i: self._commit(i))
            self.table.setCellWidget(r, 3, cell)
            self.alpha_edits[i], self.status_labels[i] = edit, status
            lag = x.lag
            for c, text in ((4, "%s s" % num(ref.get("raw_lag_dt"))),
                            (5, DASH if x.true_lag is None else "%s s" % num(x.true_lag)),
                            (6, DASH if lag is None else "%s s" % num(lag))):
                it = QTableWidgetItem(text)
                it.setTextAlignment(right)
                if c == 6:
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                self.table.setItem(r, c, it)
            b = QPushButton(TEXT["unmark"])
            theme.set_role(b, "danger")
            b.clicked.connect(lambda _=False, i=i: self.unmark(i))
            self.table.setCellWidget(r, 7, b)
            self.unmark_buttons[i] = b
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(0, self.table.horizontalHeader().ResizeMode.Stretch)
        self._apply_search()
        self._sync_busy()

    @staticmethod
    def _alpha_text(ref: dict) -> str:
        a = ref.get("reference_alpha_mm2s")
        return "" if a is None else js_number_to_string(a)

    def shown_ids(self) -> List[int]:
        return [i for i, r in self._row_of.items() if not self.table.isRowHidden(r)]

    def _apply_search(self) -> None:
        q = self.search.text()
        by_id = {x.ref["id"]: x.ref for x in self._state.ref_lags}
        for i, r in self._row_of.items():
            self.table.setRowHidden(r, bool(q.strip()) and not row_matches(by_id[i], q))

    def _sync_busy(self) -> None:
        busy = self._queue.busy
        for b in self.unmark_buttons.values():
            b.setDisabled(busy)
        for e in self.alpha_edits.values():
            e.setDisabled(busy)

    def _set_status(self, i: int, text: str, restore_ms: int = 0) -> None:
        self._status[i] = text
        lab = self.status_labels.get(i)
        if lab is not None:
            lab.setText(text)
        if restore_ms:
            QTimer.singleShot(restore_ms, lambda: self._clear_status(i, text))

    def _clear_status(self, i: int, text: str) -> None:
        if self._status.get(i) == text:
            self._set_status(i, "")

    # ---- writes ----
    def _ref(self, i: int) -> Optional[dict]:
        for x in self._state.ref_lags:
            if x.ref["id"] == i:
                return x.ref
        return None

    def _commit(self, i: int) -> None:
        """The known-alpha cell lost focus (or Enter): send only a real change to a valid number."""
        edit = self.alpha_edits.get(i)
        ref = self._ref(i)
        if edit is None or ref is None or i in self._pending:
            return
        v = parse_number(edit.text())
        old = ref.get("reference_alpha_mm2s")
        if not v > 0 or not math.isfinite(v) or v == old:
            edit.setText(self._alpha_text(ref))
            return
        self._pending[i] = v
        self._set_status(i, TEXT["cellSaving"])
        started = self._queue.run(
            [WriteOp("update", i, {"reference_alpha_mm2s": v}, "#%s" % i)], lambda s, i=i: self._alpha_done(i, s))
        if not started:
            self._pending.pop(i, None)
            self._set_status(i, "")
            edit.setText(self._alpha_text(ref))

    def _alpha_done(self, i: int, summary) -> None:
        self._pending.pop(i, None)
        if summary.failures or summary.aborted:
            self._set_status(i, TEXT["cellFailed"])
            ref = self._ref(i)
            edit = self.alpha_edits.get(i)
            if edit is not None and ref is not None:
                edit.setText(self._alpha_text(ref))
            self._on_message("%s: %s" % (TEXT["saveFailed"], failure_text(summary)), "error")
        else:
            self._set_status(i, TEXT["cellSaved"], SAVED_MS)

    def unmark(self, i: int) -> None:
        if self._queue.busy:
            return
        self._queue.run([WriteOp("update", i, {"is_reference": False, "reference_alpha_mm2s": None}, "#%s" % i)],
                        lambda s, i=i: self._unmarked(i, s))

    def _unmarked(self, i: int, summary) -> None:
        if summary.failures or summary.aborted:
            self._on_message("%s: %s" % (TEXT["saveFailed"], failure_text(summary)), "error")
            return
        self._state.selected_ref_ids = [x for x in self._state.selected_ref_ids if x != i]
