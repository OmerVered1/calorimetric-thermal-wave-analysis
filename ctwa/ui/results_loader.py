"""Qt bridge to the saved results: every fetch and write runs off the GUI thread.

One shared instance (MainWindow.results_loader). Reads: ``refresh()`` fetches the rows and the
presets and emits ``rows_changed(list)`` / ``presets_changed(list)``; ``rows()`` / ``presets()`` are
the cached copies; ``request_graph(id)`` emits ``graph_loaded(id, str_or_None)``.

Writes (``apply_*``) each return an int token and run one at a time, in call order. After each one
the loader emits ``write_done(op, token, result)`` (or ``write_failed(op, token, kind, message)``),
then refreshes. ``op`` is "insert" | "update" | "delete" | "preset_insert" | "preset_delete".

``failed(kind, message)``: kind is "login" (NotLoggedIn), "offline", "server" (ServerError) or
"error" (anything else). Results come back by queued signals, and emits are guarded against a
loader deleted while a job ran (the same pattern as SavePanel and UploadManager).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal

from ctwa.cloud.client import NotLoggedIn, Offline, ServerError
from ctwa.results.store import ResultsStore

__all__ = ["ResultsLoader"]


def _classify(e: BaseException) -> Tuple[str, str]:
    if isinstance(e, NotLoggedIn):
        return "login", str(e) or "Not logged in"
    if isinstance(e, Offline):
        return "offline", str(e) or "Offline"
    if isinstance(e, ServerError):
        return "server", str(e)
    return "error", "%s: %s" % (type(e).__name__, e)


class _Signals(QObject):
    finished = Signal(object)   # dict: what, ok, kind/message or result


class _Job(QRunnable):
    def __init__(self, signals: _Signals, what: str, fn, meta: Optional[dict] = None) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._signals, self._what, self._fn, self._meta = signals, what, fn, meta or {}

    def run(self) -> None:
        out: Dict[str, Any] = dict(self._meta, what=self._what)
        try:
            out["result"] = self._fn()
            out["ok"] = True
        except BaseException as e:   # a bug must not leave a flag set forever
            out["ok"] = False
            out["kind"], out["message"] = _classify(e)
        try:
            self._signals.finished.emit(out)
        except RuntimeError:   # the loader was deleted while the call ran
            pass


class ResultsLoader(QObject):
    rows_changed = Signal(list)
    presets_changed = Signal(list)
    failed = Signal(str, str)
    graph_loaded = Signal(int, object)
    write_done = Signal(str, int, object)
    write_failed = Signal(str, int, str, str)

    def __init__(self, client, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._store = ResultsStore(client)
        self._closed = False
        # one thread: writes and the refreshes after them keep their order
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._graph_pool = QThreadPool(self)   # plots are big; they never hold up a write
        self._graph_pool.setMaxThreadCount(2)
        self._signals = _Signals(self)
        self._signals.finished.connect(self._on_finished, Qt.QueuedConnection)
        self._rows: List[dict] = []
        self._presets: List[dict] = []
        self._graphs: Dict[int, Optional[str]] = {}
        self._graphs_pending = set()
        self._busy = {"rows": False, "presets": False}
        self._dirty = {"rows": False, "presets": False}
        self._next_token = 0

    # ---- read access ----
    @property
    def store(self) -> ResultsStore:
        """For read-only use off the GUI thread (a blocking call here would freeze the window)."""
        return self._store

    def rows(self) -> List[dict]:
        return list(self._rows)

    def presets(self) -> List[dict]:
        return list(self._presets)

    # ---- fetches ----
    def refresh(self) -> None:
        self._refresh("rows")
        self._refresh("presets")

    def _refresh(self, which: str) -> None:
        if self._closed:
            return
        if self._busy[which]:
            self._dirty[which] = True   # fetch again once this one is back: it may predate a write
            return
        self._busy[which] = True
        fn = self._store.fetch_rows if which == "rows" else self._store.fetch_presets
        self._pool.start(_Job(self._signals, which, fn))

    def request_graph(self, id: int) -> None:
        if self._closed:
            return
        id = int(id)
        if id in self._graphs:
            img = self._graphs[id]
            QTimer.singleShot(0, lambda: None if self._closed else self.graph_loaded.emit(id, img))
            return
        if id in self._graphs_pending:
            return
        self._graphs_pending.add(id)
        self._graph_pool.start(_Job(
            self._signals, "graph", lambda: self._store.fetch_graph_images([id]).get(id), {"id": id}))

    # ---- writes ----
    def _write(self, op: str, fn, row_id: Optional[int] = None) -> int:
        self._next_token += 1
        token = self._next_token
        if self._closed:
            self.write_failed.emit(op, token, "error", "The results loader is closed")
            return token
        self._pool.start(_Job(self._signals, "write", fn, {"op": op, "token": token, "id": row_id}))
        return token

    def apply_update(self, id: int, changes: dict) -> int:
        changes = dict(changes)
        return self._write("update", lambda: self._store.update_fields(id, changes), id)

    def apply_delete(self, id: int) -> int:
        return self._write("delete", lambda: self._store.delete(id), id)

    def apply_insert(self, row: dict) -> int:
        row = dict(row)
        return self._write("insert", lambda: self._store.insert("analyses", row))

    def apply_preset_insert(self, row: dict) -> int:
        row = dict(row)
        return self._write("preset_insert", lambda: self._store.insert_preset(row))

    def apply_preset_delete(self, id: int) -> int:
        return self._write("preset_delete", lambda: self._store.delete_preset(id))

    # ---- results (GUI thread) ----
    def _on_finished(self, out: dict) -> None:
        if self._closed:
            return
        what = out["what"]
        if what in ("rows", "presets"):
            self._busy[what] = False
            if out["ok"]:
                if what == "rows":
                    self._rows = list(out["result"])
                    self.rows_changed.emit(self.rows())
                else:
                    self._presets = list(out["result"])
                    self.presets_changed.emit(self.presets())
            else:
                self.failed.emit(out["kind"], out["message"])
            if self._dirty[what]:
                self._dirty[what] = False
                if out["ok"]:
                    self._refresh(what)
        elif what == "graph":
            self._graphs_pending.discard(out["id"])
            if out["ok"]:
                self._graphs[out["id"]] = out["result"]
                self.graph_loaded.emit(out["id"], out["result"])
            else:
                self.failed.emit(out["kind"], out["message"])
        else:
            self._on_write(out)

    def _on_write(self, out: dict) -> None:
        op, token = out["op"], out["token"]
        if not out["ok"]:
            self.write_failed.emit(op, token, out["kind"], out["message"])
            if out["kind"] == "login":
                self.failed.emit("login", out["message"])
            return
        if out.get("id") is not None and op in ("update", "delete"):
            self._graphs.pop(int(out["id"]), None)   # the plot may have changed
        self.write_done.emit(op, token, out["result"])
        self._refresh("presets" if op.startswith("preset") else "rows")

    def shutdown(self, timeout_ms: int = 500) -> None:
        """Stop accepting work and wait a moment for what is running."""
        self._closed = True
        self._pool.waitForDone(timeout_ms)
        self._graph_pool.waitForDone(timeout_ms)
