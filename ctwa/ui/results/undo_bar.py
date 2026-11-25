"""The "Deleted! #id  [Undo]" toasts of the History tab, one per pending delete, each with its own timer.

The timers belong to the entries, so deleting the bar (and the tab around it) stops them without a send."""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ctwa import theme

__all__ = ["UndoBar"]


class _Entry(QFrame):
    def __init__(self, id: int, delay_ms: int, bar: "UndoBar") -> None:
        super().__init__(bar)
        theme.set_role(self, "card")
        self.id = id
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        self.label = QLabel("Deleted! #%d" % id)
        self.button = QPushButton("Undo")
        lay.addWidget(self.label, 1)
        lay.addWidget(self.button)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(max(0, int(delay_ms)))
        self.timer.timeout.connect(lambda: bar._finish(id, expired=True))
        self.button.clicked.connect(lambda: bar._finish(id, expired=False))
        self.timer.start()


class UndoBar(QWidget):
    undone = Signal(int)
    expired = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._entries: Dict[int, _Entry] = {}
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(4)
        self.hide()

    def add(self, id: int, delay_ms: int = 6000) -> bool:
        """Start an entry; False when this id is already pending (a row is queued once)."""
        if id in self._entries:
            return False
        e = _Entry(id, delay_ms, self)
        self._entries[id] = e
        self._lay.addWidget(e)
        self.show()
        return True

    def pending_ids(self) -> List[int]:
        return list(self._entries)

    def texts(self) -> List[str]:
        return [e.label.text() for e in self._entries.values()]

    def undo(self, id: int) -> None:
        self._finish(id, expired=False)

    def flush(self) -> None:
        """Expire everything now."""
        for id in list(self._entries):
            self._finish(id, expired=True)

    def discard(self, id: int) -> None:
        """Drop an entry without a signal (its row is gone, there is nothing left to undo or send)."""
        e = self._entries.pop(id, None)
        if e is None:
            return
        e.timer.stop()
        self._lay.removeWidget(e)
        e.hide()
        e.deleteLater()
        if not self._entries:
            self.hide()

    def _finish(self, id: int, expired: bool) -> None:
        e = self._entries.pop(id, None)
        if e is None:
            return   # already settled: a late timer or a second click does nothing
        e.timer.stop()
        self._lay.removeWidget(e)
        e.hide()
        e.deleteLater()
        if not self._entries:
            self.hide()
        (self.expired if expired else self.undone).emit(id)
