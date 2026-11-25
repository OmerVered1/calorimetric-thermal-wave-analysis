"""Run picker of the Compare page: type to find a run (name, date, °C or #id), Enter adds it; up to four
runs show as chips (app/analyses-viewer/page.tsx AnalysisPicker)."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QToolButton, QVBoxLayout, QWidget)

from ctwa import theme
from ctwa.analysis.jsmath import JS_WHITESPACE
from ctwa.ui.results.compare_logic import MAX_RUNS, run_colors
from ctwa.ui.results.fmt import js_str, label_of, run_label_text

__all__ = ["RunPicker"]

MAX_HITS = 60
PLACEHOLDER = "Add a run: type a name, date, °C or #id"
FULL_TEXT = "Compare up to 4 at a time"
_WS = re.compile("[" + re.escape(JS_WHITESPACE) + "]+")


class RunPicker(QWidget):
    ids_changed = Signal(list)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._rows: List[Dict[str, Any]] = []
        self._by_id: Dict[Any, Dict[str, Any]] = {}
        self._ids: List[int] = []
        self._open = False
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        self.title_label = QLabel("Select analyses to compare")
        theme.set_role(self.title_label, "heading")
        self._counter = QLabel()
        theme.set_role(self._counter, "faint")
        head.addWidget(self.title_label, 1)
        head.addWidget(self._counter)
        root.addLayout(head)
        self._chips = QHBoxLayout()
        self._chips.setSpacing(6)
        row = QHBoxLayout()
        row.addLayout(self._chips)
        row.addStretch(1)
        self.remove_all_button = QPushButton("Remove all")
        theme.set_role(self.remove_all_button, "quiet")
        self.remove_all_button.clicked.connect(self.clear_all)
        row.addWidget(self.remove_all_button)
        root.addLayout(row)
        self.edit = QLineEdit()
        self.edit.setClearButtonEnabled(True)
        self.edit.textEdited.connect(self._typed)
        self.edit.installEventFilter(self)
        root.addWidget(self.edit)
        self.list = QListWidget()
        self.list.setMaximumHeight(260)
        self.list.itemClicked.connect(lambda it: self._pick(it.data(Qt.UserRole)))
        self.list.hide()
        root.addWidget(self.list)
        self._refresh()

    # ---- public ----
    def set_rows(self, rows: List[dict]) -> None:
        self._rows = list(rows)
        self._by_id = {}
        for r in self._rows:
            self._by_id.setdefault(r.get("id"), r)
        kept = [i for i in self._ids if i in self._by_id]
        changed = kept != self._ids
        self._ids = kept
        self._refresh()
        if changed:
            self.ids_changed.emit(self.ids())

    def set_ids(self, ids: List[int]) -> None:
        out: List[int] = []
        for i in ids:
            if i in self._by_id and i not in out and len(out) < MAX_RUNS:
                out.append(i)
        if out != self._ids:
            self._ids = out
            self._refresh()
            self.ids_changed.emit(self.ids())

    def ids(self) -> List[int]:
        return list(self._ids)

    def add(self, id: int) -> bool:
        if id not in self._by_id or id in self._ids or len(self._ids) >= MAX_RUNS:
            return False
        self._ids.append(id)
        self._refresh()
        self.ids_changed.emit(self.ids())
        return True

    def remove(self, id: int) -> None:
        if id in self._ids:
            self._ids.remove(id)
            self._refresh()
            self.ids_changed.emit(self.ids())

    def clear_all(self) -> None:
        if self._ids:
            self._ids = []
            self._refresh()
            self.ids_changed.emit([])

    def hits(self) -> List[int]:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]

    def chip_texts(self) -> List[str]:
        return [lab.text() for _, lab, _ in self._chip_widgets]

    def chip_colors(self) -> List[str]:
        return [c for _, _, c in self._chip_widgets]

    def counter_text(self) -> str:
        return self._counter.text()

    # ---- search ----
    def _found(self) -> List[Dict[str, Any]]:
        terms = [t for t in _WS.split(self.edit.text().lower().replace("#", "")) if t]
        out = []
        for r in self._rows:
            if r.get("id") in self._ids:
                continue
            hay = label_of(r).lower()
            if all(t in hay for t in terms):
                out.append(r)
                if len(out) >= MAX_HITS:
                    break
        return out

    def _typed(self, _text: str = "") -> None:
        self._open = True
        self._fill_list()

    def _fill_list(self) -> None:
        self.list.clear()
        show = self._open and bool(self.edit.text().strip()) or self._open and self.edit.hasFocus()
        if show and len(self._ids) < MAX_RUNS:
            for r in self._found():
                it = QListWidgetItem("%s\n%s · %s%s" % (
                    run_label_text(r), js_str(r.get("test_date")), js_str(r.get("analysis_mode")),
                    " · %s" % js_str(r.get("gas_atmosphere")) if r.get("gas_atmosphere") else ""))
                it.setData(Qt.UserRole, r.get("id"))
                self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)
        self.list.setVisible(self.list.count() > 0)

    def _pick(self, id: Any) -> None:
        if self.add(id):
            self.edit.clear()
            self._fill_list()

    # ---- keys ----
    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        if obj is self.edit:
            if ev.type() == QEvent.KeyPress:
                k = ev.key()
                n = self.list.count()
                if k == Qt.Key_Down and n:
                    self.list.setCurrentRow(min(self.list.currentRow() + 1, n - 1))
                    return True
                if k == Qt.Key_Up and n:
                    self.list.setCurrentRow(max(self.list.currentRow() - 1, 0))
                    return True
                if k in (Qt.Key_Return, Qt.Key_Enter) and n:
                    cur = self.list.currentItem()
                    if cur is not None:
                        self._pick(cur.data(Qt.UserRole))
                    return True
                if k == Qt.Key_Escape:
                    self._open = False
                    self._fill_list()
                    return True
            elif ev.type() == QEvent.FocusIn and isinstance(ev, QFocusEvent) \
                    and ev.reason() != Qt.ActiveWindowFocusReason and len(self._ids) < MAX_RUNS:
                self._open = True
                self._fill_list()
        return False

    # ---- view ----
    def _refresh(self) -> None:
        while self._chips.count():
            it = self._chips.takeAt(0)
            if it.widget() is not None:
                it.widget().deleteLater()
        self._chip_widgets: List[tuple] = []
        for i, id in enumerate(self._ids):
            r = self._by_id[id]
            color = run_colors(i)[0]
            chip = QFrame()
            theme.set_role(chip, "card")
            cl = QHBoxLayout(chip)
            cl.setContentsMargins(8, 2, 2, 2)
            cl.setSpacing(6)
            cl.addWidget(theme.swatch(color, 10))
            lab = QLabel(run_label_text(r))
            lab.setToolTip(label_of(r))
            cl.addWidget(lab)
            x = QToolButton()
            x.setText("×")
            x.setToolTip("Delete #%s" % js_str(id))
            x.clicked.connect(lambda _=False, i=id: self.remove(i))
            cl.addWidget(x)
            self._chips.addWidget(chip)
            self._chip_widgets.append((chip, lab, color))
        n = len(self._ids)
        self._counter.setText("%d / %d" % (n, MAX_RUNS))
        full = n >= MAX_RUNS
        self.edit.setEnabled(not full)
        self.edit.setPlaceholderText(FULL_TEXT if full else PLACEHOLDER)
        self.edit.setToolTip(FULL_TEXT if full else "")
        self.remove_all_button.setVisible(n > 0)
        self._fill_list()
