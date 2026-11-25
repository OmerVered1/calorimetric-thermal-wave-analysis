"""The Results tab: Summary, History and Compare pages of the saved analyses in one container."""
from __future__ import annotations

import time
from typing import List, Optional

from PySide6.QtCore import QSettings, QTimer, Signal
from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from ctwa import theme
from ctwa.ui.results.compare_tab import CompareTab
from ctwa.ui.results.history_tab import HistoryTab
from ctwa.ui.results.summary_tab import SummaryTab

__all__ = ["ResultsTab"]

LOGIN_WINDOW_S = 5.0
STATUS_MS = 6000


class ResultsTab(QWidget):
    login_needed = Signal()

    def __init__(self, loader, settings: Optional[QSettings] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._loader = loader
        self._refreshed = False
        self._last_login = None
        self.summary = SummaryTab(loader, settings)
        self.history = HistoryTab(loader)
        self.compare = CompareTab(loader)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.summary, "Summary")
        self.tabs.addTab(self.history, "History")
        self.tabs.addTab(self.compare, "Compare")
        self.status_label = QLabel("")
        theme.set_role(self.status_label, "muted")
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(STATUS_MS)
        self._status_timer.timeout.connect(lambda: self.status_label.setText(""))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.tabs, 1)
        lay.addWidget(self.status_label)
        self.summary.compare_requested.connect(self.show_compare)
        self.history.open_in_viewer.connect(lambda i: self.show_compare([i]))
        for page in (self.summary, self.history):
            page.message.connect(self._on_message)
            page.login_needed.connect(self._on_login)

    # ---- public ----
    def current_page(self) -> str:
        return self.tabs.tabText(self.tabs.currentIndex())

    def show_compare(self, ids: List[int]) -> None:
        self.compare.set_ids(list(ids))
        self.tabs.setCurrentWidget(self.compare)

    def show_history(self, id: int) -> None:
        self.history.select_id(id)
        self.tabs.setCurrentWidget(self.history)

    def show_summary(self, ids=None, query: Optional[str] = None) -> None:
        self.summary.set_id_filter(set(ids) if ids is not None else None)
        if query is not None:
            self.summary.set_search(query)
        self.tabs.setCurrentWidget(self.summary)

    def flush_pending(self) -> None:
        self.history.flush_pending()

    def status_text(self) -> str:
        return self.status_label.text()

    # ---- internals ----
    def _on_message(self, text: str) -> None:
        self.status_label.setText(text)
        self._status_timer.start()

    def _on_login(self) -> None:
        now = time.monotonic()
        if self._last_login is not None and now - self._last_login < LOGIN_WINDOW_S:
            return
        self._last_login = now
        self.login_needed.emit()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if not self._refreshed:
            self._refreshed = True
            self._loader.refresh()
