"""The Calibration tab's write queue: every write of the tab goes through here, one at a time.

The queue never touches the network itself: each op is handed to the shared ResultsLoader
(`apply_*`, which runs it off the GUI thread and refreshes afterwards) and the next op starts when
the loader reports that op's token done (`write_done`) or failed (`write_failed`). A "login"
failure stops the rest; any other failure is recorded and the queue goes on. `busy` is true from
`run` until `on_done` has returned, so a double click cannot write anything twice.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from ctwa.ui.calibration.texts import TEXT

WATCHDOG_MS = 60_000        # one op that never reports back is counted as failed after this
GRAPH_TIMEOUT_MS = 20_000   # graph_image fetches are given this long, then missing means None

KINDS = ("update", "insert", "delete", "preset_insert", "preset_delete")


@dataclass
class WriteOp:
    kind: str                 # one of KINDS
    id: Optional[int] = None  # update / delete / preset_delete
    data: Optional[dict] = None   # update changes, insert row, preset_insert row
    label: str = ""           # how a failure is named, e.g. "#11"


@dataclass
class WriteSummary:
    done: int
    total: int
    failures: List[str] = field(default_factory=list)
    aborted: Optional[str] = None


class WriteQueue(QObject):
    progress = Signal(int, int)   # ops finished (written or failed), total

    def __init__(self, loader, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._loader = loader
        self._busy = False
        self._ops: List[WriteOp] = []
        self._index = 0
        self._token: Optional[int] = None
        self._done = 0
        self._failures: List[str] = []
        self._on_done: Optional[Callable[[WriteSummary], None]] = None
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(self._on_timeout)
        loader.write_done.connect(self._on_write_done)
        loader.write_failed.connect(self._on_write_failed)
        self._graph_jobs: List[dict] = []
        loader.graph_loaded.connect(self._on_graph)

    @property
    def busy(self) -> bool:
        return self._busy

    # ---- writes ----
    def run(self, ops: List[WriteOp], on_done: Callable[[WriteSummary], None]) -> bool:
        """Start the ops in order. False (and nothing happens) while a run is in progress."""
        if self._busy:
            return False
        self._busy = True
        self._ops = list(ops)
        self._index = 0
        self._done = 0
        self._failures = []
        self._on_done = on_done
        self._start_next()
        return True

    def _start_next(self) -> None:
        if self._index >= len(self._ops):
            self._finish(None)
            return
        op = self._ops[self._index]
        loader = self._loader
        if op.kind == "update":
            token = loader.apply_update(op.id, op.data)
        elif op.kind == "insert":
            token = loader.apply_insert(op.data)
        elif op.kind == "delete":
            token = loader.apply_delete(op.id)
        elif op.kind == "preset_insert":
            token = loader.apply_preset_insert(op.data)
        elif op.kind == "preset_delete":
            token = loader.apply_preset_delete(op.id)
        else:
            raise ValueError("unknown write kind %r" % op.kind)
        self._token = token
        self._watchdog.start(WATCHDOG_MS)

    def _advance(self) -> None:
        self._watchdog.stop()
        self._token = None
        self._index += 1
        self.progress.emit(self._index, len(self._ops))
        self._start_next()

    def _on_write_done(self, op: str, token: int, result) -> None:
        if not self._busy or token != self._token:
            return
        self._done += 1
        self._advance()

    def _on_write_failed(self, op: str, token: int, kind: str, message: str) -> None:
        if not self._busy or token != self._token:
            return
        self._failures.append("%s: %s" % (self._ops[self._index].label, message))
        if kind == "login":
            self._watchdog.stop()
            self._token = None
            self._index += 1
            self.progress.emit(self._index, len(self._ops))
            self._finish(message or TEXT["loginNeeded"])
            return
        self._advance()

    def _on_timeout(self) -> None:
        if not self._busy or self._token is None:
            return
        self._failures.append("%s: %s" % (self._ops[self._index].label, TEXT["timedOut"]))
        self._advance()

    def _finish(self, aborted: Optional[str]) -> None:
        summary = WriteSummary(self._done, len(self._ops), list(self._failures), aborted)
        cb = self._on_done
        try:
            if cb is not None:
                cb(summary)
        finally:
            self._busy = False
            self._on_done = None
            self._ops = []

    # ---- graphs ----
    def with_graphs(self, ids: List[int], callback: Callable[[Dict[int, Optional[str]]], None]) -> None:
        """callback({id: base64 or None}) once every graph is back, or after GRAPH_TIMEOUT_MS."""
        wanted = list(dict.fromkeys(int(i) for i in ids))
        job = {"wanted": set(wanted), "got": {}, "callback": callback, "timer": QTimer(self)}
        if not wanted:
            callback({})
            return
        job["timer"].setSingleShot(True)
        job["timer"].timeout.connect(lambda j=job: self._finish_graphs(j))
        self._graph_jobs.append(job)
        job["timer"].start(GRAPH_TIMEOUT_MS)
        for i in wanted:
            self._loader.request_graph(i)

    def _on_graph(self, id_: int, image) -> None:
        for job in list(self._graph_jobs):
            if id_ in job["wanted"] and id_ not in job["got"]:
                job["got"][id_] = image
                if len(job["got"]) == len(job["wanted"]):
                    self._finish_graphs(job)

    def _finish_graphs(self, job: dict) -> None:
        if job not in self._graph_jobs:
            return
        self._graph_jobs.remove(job)
        job["timer"].stop()
        job["callback"]({i: job["got"].get(i) for i in sorted(job["wanted"])})
