"""Mark reference runs: filters, a checkable candidate list and one known alpha for the lot (Task 6).

State used: mark_filter_material / mark_filter_temp / mark_alpha / mark_ids. The write is one UPDATE
per ticked run through the tab's WriteQueue, one at a time, a failure never stops the rest."""
from __future__ import annotations

import math
from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout, QWidget)

from ctwa import theme
from ctwa.analysis.calibration_batch import mark_report
from ctwa.analysis.calibration_logic import all_materials, label_of, mark_warnings, num, temp_key, temps_for
from ctwa.ui.calibration.common import link_button, note_label, parse_number
from ctwa.ui.calibration.state import CalibrationState
from ctwa.ui.calibration.texts import TEXT
from ctwa.ui.calibration.writes import WriteOp, WriteQueue


def _fill_combo(combo: QComboBox, keys: List[str], current: str) -> None:
    """Items "All" + keys (+ the current choice when it is not among them), current selected."""
    wanted = [""] + list(keys) + ([current] if current and current not in keys else [])
    have = [combo.itemData(i) for i in range(combo.count())]
    combo.blockSignals(True)
    if have != wanted:
        combo.clear()
        for k in wanted:
            combo.addItem(TEXT["all"] if k == "" else k, k)
    combo.setCurrentIndex(max(0, combo.findData(current)))
    combo.blockSignals(False)


class MarkSection(QWidget):
    def __init__(self, state: CalibrationState, queue: WriteQueue,
                 on_message: Callable[[str, str], None], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._state, self._queue, self._on_message = state, queue, on_message
        self._marking = False
        self._list_key = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(theme.set_role(QLabel(TEXT["markHeading"]), "section"))

        row = QHBoxLayout()
        row.setSpacing(8)
        self.material = QComboBox()
        self.temp = QComboBox()
        self.alpha = QLineEdit()
        self.alpha.setPlaceholderText("5.829")
        self.alpha.setToolTip(TEXT["knownAlphaHint"])
        for label, w in ((TEXT["batchMaterial"], self.material), (TEXT["temperature"], self.temp),
                         (TEXT["knownAlpha"], self.alpha)):
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(theme.set_role(QLabel(label), "faint"))
            col.addWidget(w)
            row.addLayout(col, 1)
        lay.addLayout(row)

        self.list = QListWidget()
        self.list.setMinimumHeight(120)
        self.list.setMaximumHeight(220)
        lay.addWidget(self.list)
        self.empty_label = note_label(TEXT["noCandidates"], "muted")
        lay.addWidget(self.empty_label)

        links = QHBoxLayout()
        self.select_all = link_button(TEXT["selectAllVisible"])
        self.clear = link_button(TEXT["clearSelection"])
        self.shown_label = theme.set_role(QLabel(""), "faint")
        links.addWidget(self.select_all)
        links.addWidget(self.clear)
        links.addStretch(1)
        links.addWidget(self.shown_label)
        lay.addLayout(links)

        self.mixed_label = theme.set_role(QLabel(""), "pill", tone="warn")
        self.spread_label = theme.set_role(QLabel(""), "pill", tone="warn")
        for w in (self.mixed_label, self.spread_label):
            w.setWordWrap(True)
            w.hide()
            lay.addWidget(w)

        act = QHBoxLayout()
        self.mark_button = QPushButton("")
        theme.set_role(self.mark_button, "primary")
        self.progress_label = theme.set_role(QLabel(""), "faint")
        act.addWidget(self.mark_button)
        act.addWidget(self.progress_label)
        act.addStretch(1)
        lay.addLayout(act)

        self.material.currentIndexChanged.connect(
            lambda _i: setattr(state, "mark_filter_material", self.material.currentData() or ""))
        self.temp.currentIndexChanged.connect(
            lambda _i: setattr(state, "mark_filter_temp", self.temp.currentData() or ""))
        self.alpha.textChanged.connect(lambda t: setattr(state, "mark_alpha", t))
        self.list.itemChanged.connect(self._on_item)
        self.select_all.clicked.connect(self._select_all)
        self.clear.clicked.connect(lambda: setattr(state, "mark_ids", []))
        self.mark_button.clicked.connect(self.mark)
        state.changed.connect(self.refresh)
        queue.busy_changed.connect(lambda _b: self._sync_buttons())
        queue.progress.connect(self._on_progress)
        self.refresh()

    # ---- candidates ----
    def candidates(self) -> List[dict]:
        s = self._state
        m, t = s.mark_filter_material, s.mark_filter_temp
        return [a for a in s.non_references
                if (m == "" or a.get("model_name") == m)
                and (t == "" or temp_key(a.get("temperature_c")) == t)]

    def ticked_rows(self) -> List[dict]:
        by_id = {a["id"]: a for a in self._state.non_references}
        return [by_id[i] for i in self._state.mark_ids if i in by_id]

    # ---- showing ----
    def refresh(self) -> None:
        s = self._state
        _fill_combo(self.material, all_materials(s.non_references), s.mark_filter_material)
        _fill_combo(self.temp, temps_for(s.non_references, s.mark_filter_material), s.mark_filter_temp)
        if self.alpha.text() != s.mark_alpha:
            self.alpha.setText(s.mark_alpha)
        cands = self.candidates()
        key = [(a["id"], label_of(a)) for a in cands]
        ticked = set(s.mark_ids)
        self.list.blockSignals(True)
        if key != self._list_key:
            self._list_key = key
            self.list.clear()
            for a in cands:
                it = QListWidgetItem(label_of(a))
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setData(Qt.UserRole, a["id"])
                it.setCheckState(Qt.Checked if a["id"] in ticked else Qt.Unchecked)
                self.list.addItem(it)
        else:
            for i in range(self.list.count()):
                it = self.list.item(i)
                it.setCheckState(Qt.Checked if it.data(Qt.UserRole) in ticked else Qt.Unchecked)
        self.list.blockSignals(False)
        self.empty_label.setVisible(not cands)
        self.list.setVisible(bool(cands))
        self.shown_label.setText(TEXT["shownCount"].format(n=len(cands)))
        warn = mark_warnings(self.ticked_rows())
        if warn["mixed_materials"]:
            self.mixed_label.setText("%s — %s" % (TEXT["mixedMaterialsWarn"], ", ".join(
                str(m) for m in warn["mixed_materials"])))
        self.mixed_label.setVisible(bool(warn["mixed_materials"]))
        if warn["temp_spread"] is not None:
            self.spread_label.setText("%s — %s %s °C" % (
                TEXT["markTempSpreadWarn"], TEXT["spread"], num(warn["temp_spread"], 1)))
        self.spread_label.setVisible(warn["temp_spread"] is not None)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        n = len(self.ticked_rows())
        self.mark_button.setText(TEXT["markButton"].format(n=n))
        self.mark_button.setEnabled(n > 0 and not self._queue.busy)
        self.select_all.setDisabled(self._queue.busy)
        self.clear.setDisabled(self._queue.busy)

    # ---- user actions ----
    def _on_item(self, item: QListWidgetItem) -> None:
        ids = list(self._state.mark_ids)
        i = item.data(Qt.UserRole)
        if item.checkState() == Qt.Checked:
            if i not in ids:
                ids.append(i)
        else:
            ids = [x for x in ids if x != i]
        self._state.mark_ids = ids

    def _select_all(self) -> None:
        ids = list(self._state.mark_ids)
        ids += [a["id"] for a in self.candidates() if a["id"] not in ids]
        self._state.mark_ids = ids

    def mark(self) -> None:
        if self._queue.busy:
            return
        rows = self.ticked_rows()
        if not rows:
            return
        alpha = parse_number(self.alpha.text())
        if not alpha > 0 or not math.isfinite(alpha):
            self._on_message(TEXT["errAlphaRequired"], "error")
            return
        ops = [WriteOp("update", a["id"], {"is_reference": True, "reference_alpha_mm2s": alpha},
                       "#%s" % a["id"]) for a in rows]
        self._marking = True
        self.progress_label.setText("1 / %d" % len(ops))
        if not self._queue.run(ops, self._marked):
            self._marking = False
            self.progress_label.setText("")

    def _on_progress(self, done: int, total: int) -> None:
        if self._marking and done < total:
            self.progress_label.setText("%d / %d" % (done + 1, total))

    def _marked(self, summary) -> None:
        self._marking = False
        self.progress_label.setText("")
        text = mark_report(summary.done, summary.total, summary.failures)
        if summary.aborted:
            text += " · " + TEXT["writtenOf"].format(n=summary.done, m=summary.total)
        self._on_message(text, "ok" if not summary.failures and not summary.aborted else "warn")
        # only the runs that were written leave the selection; failed and unsent ones stay ticked
        self._state.mark_ids = [i for i in self._state.mark_ids if "#%s" % i not in summary.succeeded]
