"""Qt side of the upload queue: owns the UploadQueue and the client, flushes off the GUI thread.

A flush runs on start(), after request_flush() (SavePanel asks after each successful
save) and every `interval_ms` (5 min). It runs in a QThreadPool worker, so the GUI never
waits on the network; UploadQueue.flush already refuses a second concurrent flush.

Signals: count_changed(int) - rows waiting; needs_login() - a flush met a missing or
expired login (the rows stay queued). No password or token passes through here."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal

from ctwa.cloud.client import NotLoggedIn
from ctwa.cloud.queue import UploadQueue

FLUSH_INTERVAL_MS = 5 * 60 * 1000


class _Spy:
    """Passes insert() through and remembers that the server wanted a login."""

    def __init__(self, client) -> None:
        self._client = client
        self.unauthorised = False

    def insert(self, table, row):
        try:
            return self._client.insert(table, row)
        except NotLoggedIn:
            self.unauthorised = True
            raise


class _Signals(QObject):
    done = Signal(int, bool)  # rows still waiting, login needed


class _FlushJob(QRunnable):
    def __init__(self, queue: UploadQueue, client, signals: _Signals) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._queue, self._client, self._signals = queue, client, signals

    def run(self) -> None:
        spy = _Spy(self._client)
        try:
            self._queue.flush(spy)
        except Exception:  # keep the thread alive; the rows stay queued
            pass
        try:
            waiting = len(self._queue.pending())
        except Exception:
            waiting = -1
        try:
            self._signals.done.emit(waiting, spy.unauthorised)
        except RuntimeError:  # the manager was deleted meanwhile
            pass


class UploadManager(QObject):
    count_changed = Signal(int)
    needs_login = Signal()

    def __init__(self, client, queue: UploadQueue, interval_ms: int = FLUSH_INTERVAL_MS,
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.client = client
        self.queue = queue
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._signals = _Signals(self)
        self._signals.done.connect(self._on_done, Qt.QueuedConnection)
        self._count = len(queue.pending())
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.request_flush)
        self._closed = False
        self._login_asked = False

    def count(self) -> int:
        return self._count

    def start(self) -> None:
        self.count_changed.emit(self._count)
        self.request_flush()
        self._timer.start()

    def request_flush(self) -> None:
        if not self._closed:
            self._pool.start(_FlushJob(self.queue, self.client, self._signals))

    def enqueue(self, row: dict) -> str:
        rid = self.queue.enqueue(row)
        self._set_count(len(self.queue.pending()))
        return rid

    def shutdown(self, timeout_ms: int = 5000) -> None:
        self._closed = True
        self._timer.stop()
        self._pool.waitForDone(timeout_ms)

    def _set_count(self, n: int) -> None:
        if n != self._count:
            self._count = n
        self.count_changed.emit(n)

    def _on_done(self, waiting: int, unauthorised: bool) -> None:
        if waiting >= 0:
            self._set_count(waiting)
        if unauthorised and not self._login_asked:
            self._login_asked = True  # once per logged-out period
            self.needs_login.emit()

    def login_succeeded(self) -> None:
        """Call after a successful login (or when the user saves again): needs_login may fire again."""
        self._login_asked = False
