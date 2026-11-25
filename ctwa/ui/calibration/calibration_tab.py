"""The Calibration tab: presets, marking, reference table, calibrate one run and batch (Plan 4, Task 10).

Everything shares one CalibrationState and one WriteQueue. The loader's rows and presets feed the
state; until the first rows arrive the page shows only "Loading..."."""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

from ctwa import theme
from ctwa.ui.calibration.batch_section import BatchSection
from ctwa.ui.calibration.common import MessageBar, StepCard, note_label
from ctwa.ui.calibration.mark_section import MarkSection
from ctwa.ui.calibration.presets_section import PresetsSection
from ctwa.ui.calibration.reference_table import ReferenceTable
from ctwa.ui.calibration.state import CalibrationState
from ctwa.ui.calibration.target_section import TargetSection
from ctwa.ui.calibration.texts import TEXT
from ctwa.ui.calibration.writes import WriteQueue

LOGIN_TEXT = "Not logged in. Use Settings → Webapp login…"
REPORT_MS = 12_000


def ask_confirm(title: str, message: str, button_label: str) -> bool:
    box = QMessageBox(QMessageBox.Question, title, message)
    yes = box.addButton(button_label, QMessageBox.AcceptRole)
    box.addButton(QMessageBox.Cancel)
    box.exec()
    return box.clickedButton() is yes


class CalibrationTab(QWidget):
    def __init__(self, loader, parent: Optional[QWidget] = None,
                 confirm: Callable[[str, str, str], bool] = ask_confirm) -> None:
        super().__init__(parent)
        self._loader = loader
        self._shown = False
        self._loaded = False
        self.state = CalibrationState(self)
        self.queue = WriteQueue(loader, self)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(theme.set_role(QLabel(TEXT["title"]), "title"))
        head.addStretch(1)
        head.addWidget(QLabel(TEXT["lagMethod"] + ":"))
        self.phase_button = QPushButton(TEXT["methodPhase"])
        self.combined_button = QPushButton(TEXT["methodCombined"])
        for b in (self.phase_button, self.combined_button):
            b.setCheckable(True)
            b.setToolTip(TEXT["lagMethod"])
        self.phase_button.setChecked(True)
        head.addWidget(theme.segmented(self.phase_button, self.combined_button))
        self.method_hint = theme.set_role(QLabel(TEXT["methodHint"]), "faint")
        head.addWidget(self.method_hint)
        self.refresh_button = QPushButton("Refresh")
        head.addWidget(self.refresh_button)
        root.addLayout(head)
        root.addWidget(note_label(TEXT["note"]))
        self.messages = MessageBar()
        root.addWidget(self.messages)
        self._message_timer = QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.timeout.connect(self.messages.clear_message)

        self.loading_label = theme.set_role(QLabel(TEXT["loading"]), "muted")
        root.addWidget(self.loading_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(12)
        msg = self._on_message
        self.presets = PresetsSection(self.state, self.queue, msg)
        self.mark = MarkSection(self.state, self.queue, msg)
        self.table = ReferenceTable(self.state, self.queue, msg)
        self.reference_card = StepCard(TEXT["referencesHeading"])
        for w in (self.presets, self.mark, self.table):
            self.reference_card.body.addWidget(w)
        self.target = TargetSection(self.state, self.queue, msg)
        self.batch = BatchSection(self.state, self.queue, msg, confirm)
        for w in (self.reference_card, self.target, self.batch):
            pl.addWidget(w)
        pl.addStretch(1)
        self.scroll.setWidget(page)
        self.scroll.hide()
        root.addWidget(self.scroll, 1)

        self.phase_button.clicked.connect(lambda: self._set_method("phase"))
        self.combined_button.clicked.connect(lambda: self._set_method("combined"))
        self.refresh_button.clicked.connect(self._on_refresh)
        loader.rows_changed.connect(self._on_rows)
        loader.presets_changed.connect(self.state.set_presets)
        loader.failed.connect(self._on_failed)
        self.queue.busy_changed.connect(self._on_busy)
        self.state.changed.connect(self._sync)
        self._sync()

    # ---- public ----
    def refresh(self) -> None:
        self._loader.refresh()

    def on_shown(self) -> None:
        if not self._shown:
            self._shown = True
            self._loader.refresh()

    def show_message(self, text: str, kind: str = "info", ms: int = 5000) -> None:
        """Errors stay until the next action; everything else fades after `ms`."""
        self._message_timer.stop()
        self.messages.show_message(text, kind)
        if kind != "error" and ms > 0 and text:
            self._message_timer.start(ms)

    # ---- internals ----
    def _on_message(self, text: str, kind: str) -> None:
        self.show_message(text, kind, 5000 if text == TEXT["saved"] else REPORT_MS)

    def _on_rows(self, rows) -> None:
        self._loaded = True
        self.state.set_rows(rows)
        self.loading_label.hide()
        self.scroll.show()

    def _on_failed(self, kind: str, message: str) -> None:
        if self.queue.busy:
            return      # the queue reports its own failures
        self.show_message(LOGIN_TEXT if kind == "login" else message, "error")

    def _on_busy(self, busy: bool) -> None:
        if busy:
            self._message_timer.stop()
            self.messages.clear_message()

    def _on_refresh(self) -> None:
        self._message_timer.stop()
        self.messages.clear_message()
        self.refresh()

    def _set_method(self, method: str) -> None:
        self.state.method = method
        self._sync()

    def _sync(self) -> None:
        m = self.state.method
        self.phase_button.setChecked(m == "phase")
        self.combined_button.setChecked(m == "combined")
        n = len(self.state.references)
        self.reference_card.set_status(TEXT["refCount"].format(n=n), n > 0)
