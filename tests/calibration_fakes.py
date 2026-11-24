"""Test doubles for the Calibration tab: a FakeLoader with the ResultsLoader's signals and methods
(no network, no threads: completions come through QTimer.singleShot(0)), and `make_rows()`."""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QObject, QTimer, Signal


class FakeStore:
    def __init__(self) -> None:
        self.calls: List[tuple] = []

    def insert_preset(self, row: dict) -> dict:
        self.calls.append(("insert_preset", dict(row)))
        return dict(row, id=len(self.calls))

    def delete_preset(self, id) -> None:
        self.calls.append(("delete_preset", id))


class FakeLoader(QObject):
    rows_changed = Signal(list)
    presets_changed = Signal(list)
    failed = Signal(str, str)
    graph_loaded = Signal(int, object)
    write_done = Signal(str, int, object)
    write_failed = Signal(str, int, str, str)

    def __init__(self, rows: Optional[List[dict]] = None, presets: Optional[List[dict]] = None) -> None:
        super().__init__()
        self.rows_list = list(rows or [])
        self.presets_list = list(presets or [])
        self.ops: List[tuple] = []           # ("update", id, changes) / ("insert", row) / ...
        self.refreshes = 0
        self.fail_at: Dict[int, Tuple[str, str]] = {}   # op index -> (kind, message)
        self.hang_at: Set[int] = set()        # op indexes that never report back
        self.graphs: Dict[int, Optional[str]] = {}
        self.silent_graphs = False            # request_graph never answers
        self.requested_graphs: List[int] = []
        self.store = FakeStore()
        self._token = 0

    # reads
    def rows(self) -> List[dict]:
        return list(self.rows_list)

    def presets(self) -> List[dict]:
        return list(self.presets_list)

    def refresh(self) -> None:
        self.refreshes += 1
        QTimer.singleShot(0, lambda: self.rows_changed.emit(self.rows()))
        QTimer.singleShot(0, lambda: self.presets_changed.emit(self.presets()))

    def request_graph(self, id: int) -> None:
        self.requested_graphs.append(id)
        if not self.silent_graphs:
            QTimer.singleShot(0, lambda: self.graph_loaded.emit(id, self.graphs.get(id)))

    # writes
    def _write(self, op: str, entry: tuple) -> int:
        index = len(self.ops)
        self.ops.append(entry)
        self._token += 1
        token = self._token
        if index in self.hang_at:
            return token
        if index in self.fail_at:
            kind, message = self.fail_at[index]
            QTimer.singleShot(0, lambda: self.write_failed.emit(op, token, kind, message))
            if kind == "login":
                QTimer.singleShot(0, lambda: self.failed.emit("login", message))
        else:
            QTimer.singleShot(0, lambda: self.write_done.emit(op, token, {}))
            self.refresh()
        return token

    def apply_update(self, id: int, changes: dict) -> int:
        return self._write("update", ("update", id, dict(changes)))

    def apply_delete(self, id: int) -> int:
        return self._write("delete", ("delete", id))

    def apply_insert(self, row: dict) -> int:
        return self._write("insert", ("insert", dict(row)))

    def apply_preset_insert(self, row: dict) -> int:
        self.store.insert_preset(row)
        return self._write("preset_insert", ("preset_insert", dict(row)))

    def apply_preset_delete(self, id: int) -> int:
        self.store.delete_preset(id)
        return self._write("preset_delete", ("preset_delete", id))


# ---- rows ----

PERIODS = [75, 150, 300, 600, 1200]
RAW = [28.2366967506017, 40.64844825385532, 57.4733935012034, 81.29689650771064, 114.9467870024068]


def make_row(id: int, model: str = "Stainless Steel", temp: Optional[float] = 800.0, period: float = 400,
             **extra) -> dict:
    w = 2 * math.pi / period
    row = {"id": id, "model_name": model, "temperature_c": temp, "period_t": period,
           "angular_freq_w": w, "r1_mm": 6.72, "r2_mm": 14.86, "ln_term": 3,
           "amplitude_a1": 4, "amplitude_a2": 1, "raw_lag_dt": 150, "test_date": "17/11/2026",
           "analysis_mode": "AutoFit", "is_reference": False, "reference_alpha_mm2s": None,
           "calibrated_from_id": None, "graph_image": None}
    row.update(extra)
    return row


def make_rows() -> List[dict]:
    """Five stainless-steel references (ids 10-14, alpha 5.829; id 14 at 780.5 degrees), targets
    99 (the Task 2 target, period 400), 100-103 in other materials and temperatures, and a
    calibrated copy (150) of 101."""
    rows = []
    for i, (p, raw) in enumerate(zip(PERIODS, RAW)):
        rows.append(make_row(10 + i, period=p, temp=780.5 if i == 4 else 800.0, raw_lag_dt=raw,
                             is_reference=True, reference_alpha_mm2s=5.829))
    rows += [
        make_row(99, period=400, temp=800.0),
        make_row(100, period=300, temp=780.5),
        make_row(101, model="Al", period=300, temp=800.0),
        make_row(102, model="Al₂O₃", period=261, temp=150.0),
        make_row(103, period=600, temp=831.0),
        make_row(150, model="Al", period=300, temp=800.0, calibrated_from_id=101, use_calibration=True),
    ]
    return rows


# ---- Qt helpers (no pytest-qt here) ----

def get_app():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def wait_until(pred, timeout: float = 5.0) -> bool:
    import time
    from PySide6.QtCore import QCoreApplication
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if pred():
            return True
        time.sleep(0.002)
    QCoreApplication.processEvents()
    return pred()
