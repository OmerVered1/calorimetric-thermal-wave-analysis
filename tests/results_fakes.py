"""A stand-in ResultsLoader for the Results tab tests: the Foundation's signals and methods, no network."""
from __future__ import annotations

from typing import Any, Dict, List

from PySide6.QtCore import QObject, Signal


class FakeLoader(QObject):
    rows_changed = Signal(list)
    presets_changed = Signal(list)
    failed = Signal(str, str)
    graph_loaded = Signal(int, object)
    write_done = Signal(str, int, object)
    write_failed = Signal(str, int, str, str)

    def __init__(self, rows: List[dict] = None) -> None:
        super().__init__()
        self._rows: List[dict] = list(rows or [])
        self.calls: List[tuple] = []
        self._token = 0

    def rows(self) -> List[dict]:
        return list(self._rows)

    def set_rows(self, rows: List[dict]) -> None:
        self._rows = list(rows)
        self.rows_changed.emit(self.rows())

    def refresh(self) -> None:
        self.calls.append(("refresh",))

    def request_graph(self, id: int) -> None:
        self.calls.append(("request_graph", id))

    def apply_update(self, id: int, changes: Dict[str, Any]) -> int:
        self._token += 1
        self.calls.append(("update", id, dict(changes)))
        return self._token

    def apply_delete(self, id: int) -> int:
        self._token += 1
        self.calls.append(("delete", id))
        return self._token

    def updates(self) -> List[tuple]:
        return [c for c in self.calls if c[0] == "update"]
