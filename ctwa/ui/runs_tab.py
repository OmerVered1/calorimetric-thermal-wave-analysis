"""The Runs tab: recorded run files, and a way into the analysis of one."""
from __future__ import annotations

import os
import threading
from typing import Dict, List, Optional

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QObject, QRunnable,
                            QSettings, QThreadPool, Qt, Signal)
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView,
                               QInputDialog, QLabel, QPushButton, QTableView,
                               QVBoxLayout, QWidget)

from ctwa import theme
from ctwa.ui import run_index
from ctwa.ui.mean_worker import MeanTempWorker
from ctwa.ui.run_index import MeanTempCache, RunInfo, SavedInfo

try:  # the app's own names, so the tab shares its settings
    from _version import __app_name__
except Exception:  # pragma: no cover
    __app_name__ = "CTWA"
_ORGANIZATION = "Omer Vered MSc Research"   # same as ctwa.app.__organization__

COLUMNS = ["Name", "Started", "Length", "Saved analyses", "Sample", "Temperature"]
_NAME, _STARTED, _LENGTH, _SAVED, _SAMPLE, _TEMP = range(6)
SAME_DAY_TIP = "same day; older results don't record their file"
NOT_CAPTURE_TIP = "Not a CTWA/C80 one-file capture"
RECORDING_TIP = "This run is being recorded"
FOLDERS_KEY = "runs/folders"


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(p)))


def _fmt_length(s: Optional[float]) -> str:
    if s is None:
        return ""
    s = int(round(s))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}"


class RunsModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.runs: List[RunInfo] = []
        self.saved: Dict[str, SavedInfo] = {}
        self.means: Dict[str, Optional[float]] = {}
        self.cloud_state: str = "loading"   # "loading" | "ok" | an error reason
        self.recording: Optional[str] = None
        self._row_of: Dict[str, int] = {}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.runs)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]
        return None

    def is_recording(self, run: RunInfo) -> bool:
        return self.recording is not None and _norm(run.path) == self.recording

    def set_runs(self, runs: List[RunInfo], means: Dict[str, Optional[float]]) -> None:
        self.beginResetModel()
        self.runs = runs
        self._row_of = {r.path: i for i, r in enumerate(runs)}
        self.means = dict(means)
        self.saved = {}
        self.cloud_state = "loading"
        self.endResetModel()

    def _touch(self, columns) -> None:
        if self.runs:
            self.dataChanged.emit(self.index(0, min(columns)),
                                  self.index(len(self.runs) - 1, max(columns)))

    def set_saved(self, saved: Dict[str, SavedInfo]) -> None:
        self.saved, self.cloud_state = dict(saved), "ok"
        self._touch([_SAVED, _SAMPLE])

    def set_cloud_error(self, reason: str) -> None:
        self.saved, self.cloud_state = {}, reason
        self._touch([_SAVED, _SAMPLE])

    def set_mean(self, path: str, mean: Optional[float]) -> None:
        r = self._row_of.get(path)
        if r is None or (self.recording is not None and _norm(path) == self.recording):
            return   # unknown file, or the recording one (its mean would be stale)
        self.means[path] = mean
        i = self.index(r, _TEMP)
        self.dataChanged.emit(i, i)

    def set_recording(self, path: Optional[str]) -> None:
        self.recording = _norm(path) if path else None
        self._touch([0, len(COLUMNS) - 1])

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        run, c = self.runs[index.row()], index.column()
        if role == Qt.UserRole:
            return run
        if c == _NAME:
            if role == Qt.DisplayRole:
                return run.name
            if role == Qt.ToolTipRole:
                return run.path if run.is_capture else f"{run.path}\n{NOT_CAPTURE_TIP}"
            if role == Qt.ForegroundRole and not run.is_capture:
                return QBrush(QColor(theme.P.text_disabled))   # can't be opened: reads as off
        elif c == _STARTED:
            if role == Qt.DisplayRole and run.started:
                return run.started.strftime("%Y-%m-%d %H:%M")
        elif c == _LENGTH:
            if role == Qt.DisplayRole:
                return "recording" if self.is_recording(run) else _fmt_length(run.length_s)
        elif c in (_SAVED, _SAMPLE):
            return self._cloud_data(run, c, role)
        elif c == _TEMP:
            m = None if self.is_recording(run) else self.means.get(run.path)
            if role == Qt.DisplayRole and m is not None:
                return f"{m:.1f} °C"
            if role == Qt.TextAlignmentRole:
                return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def _cloud_data(self, run: RunInfo, c: int, role):
        if self.cloud_state != "ok":
            if self.cloud_state == "loading":
                if role == Qt.DisplayRole:
                    return "…"
                return None
            if role == Qt.DisplayRole:
                return "—"
            if role == Qt.ToolTipRole:
                return self.cloud_state
            return None
        info = self.saved.get(run.path)
        if info is None:
            return None
        if c == _SAVED:
            if role == Qt.DisplayRole:
                return str(info.count)
            if role == Qt.ForegroundRole and not info.exact:
                return QBrush(QColor(theme.P.text_faint))
            if role == Qt.ToolTipRole:
                return (f"{info.count} saved with this file's name" if info.exact
                        else SAME_DAY_TIP)
            if role == Qt.TextAlignmentRole:
                return int(Qt.AlignRight | Qt.AlignVCenter)
        elif role == Qt.DisplayRole:
            return info.sample
        return None


class _Signals(QObject):
    scanned = Signal(int, object, bool, object)   # generation, runs, truncated, means
    saved = Signal(int, object)       # generation, {path: SavedInfo}
    cloud_error = Signal(int, str)
    scan_failed = Signal(int, str)


class _ScanWorker(QRunnable):
    """Walks the folders, reads headers/tails, looks up the cached means."""

    def __init__(self, gen: int, folders: List[str], get_cache, signals: _Signals):
        super().__init__()
        self.gen, self.folders, self.get_cache, self.signals = gen, folders, get_cache, signals

    def run(self):
        try:
            runs, truncated = run_index.scan_limited(self.folders)
            cache = self.get_cache()
            means = {}
            for r in runs:
                if r.is_capture:
                    known, mean = cache.lookup(r)
                    if known:
                        means[r.path] = mean
        except Exception as e:
            self.signals.scan_failed.emit(self.gen, f"Could not scan the folders: {e}")
            return
        self.signals.scanned.emit(self.gen, runs, truncated, means)


class _CloudWorker(QRunnable):
    def __init__(self, gen: int, runs: List[RunInfo], client, signals: _Signals):
        super().__init__()
        self.gen, self.runs, self.client, self.signals = gen, runs, client, signals

    def run(self):
        from ctwa.cloud.client import NotLoggedIn, Offline, ServerError
        try:
            out = run_index.query_saved_rows(self.client, self.runs)
        except Offline:
            self.signals.cloud_error.emit(self.gen, "Offline: could not reach the cloud")
        except (NotLoggedIn, ServerError) as e:
            self.signals.cloud_error.emit(self.gen, f"Cloud error: {e}")
        except Exception as e:  # never let a worker die silently
            self.signals.cloud_error.emit(self.gen, f"Cloud error: {e}")
        else:
            self.signals.saved.emit(self.gen, out)


class RunsTab(QWidget):
    open_run = Signal(str)

    def __init__(self, auto_save_dir: str, client=None,
                 settings: Optional[QSettings] = None,
                 cache_path: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.auto_save_dir = auto_save_dir
        self.client = client
        self.settings = settings if settings is not None else QSettings(_ORGANIZATION, __app_name__)
        self._cache_path = cache_path
        self._cache: Optional[MeanTempCache] = None
        self._pool = QThreadPool(self)
        self._gen = 0
        self._recording: Optional[str] = None
        self._truncated = False
        self._cache_lock = threading.Lock()
        self._todo: Dict[str, RunInfo] = {}   # files whose mean the process is still working out
        self._means = MeanTempWorker(self)   # parsing happens in a separate process
        self._means.mean.connect(self._on_mean)
        self._means.idle.connect(self._on_means_idle)
        self._signals = _Signals(self)
        self._signals.scanned.connect(self._on_scanned, Qt.QueuedConnection)
        self._signals.saved.connect(self._on_saved, Qt.QueuedConnection)
        self._signals.cloud_error.connect(self._on_cloud_error, Qt.QueuedConnection)
        self._signals.scan_failed.connect(self._on_scan_failed, Qt.QueuedConnection)

        self.model = RunsModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(theme.ROW_HEIGHT)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(_NAME, QHeaderView.Stretch)
        self.table.doubleClicked.connect(lambda _i: self.analyze_selected())
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._update_buttons())

        self.analyze_btn = QPushButton("Analyze")
        self.open_btn = QPushButton("Open…")
        self.add_btn = QPushButton("Add folder…")
        self.remove_btn = QPushButton("Remove folder")
        self.refresh_btn = QPushButton("Refresh")
        self.analyze_btn.clicked.connect(self.analyze_selected)
        self.open_btn.clicked.connect(self._choose_file)
        self.add_btn.clicked.connect(self._choose_folder)
        self.remove_btn.clicked.connect(self._choose_folder_to_remove)
        self.refresh_btn.clicked.connect(self.refresh)
        bar = QHBoxLayout()
        for b in (self.analyze_btn, self.open_btn, self.add_btn, self.remove_btn):
            bar.addWidget(b)
        bar.addStretch(1)
        bar.addWidget(self.refresh_btn)

        self.status = QLabel("")
        theme.set_role(self.status, "muted")
        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.status)
        self._update_buttons()

    # -- folders ------------------------------------------------------------
    def added_folders(self) -> List[str]:
        v = self.settings.value(FOLDERS_KEY, [])
        if v is None:
            v = []
        if isinstance(v, str):
            v = [v]
        return [str(p) for p in v if p]

    def folders(self) -> List[str]:
        return [self.auto_save_dir] + [p for p in self.added_folders()
                                       if _norm(p) != _norm(self.auto_save_dir)]

    def add_folder(self, path: str) -> bool:
        if not path or _norm(path) == _norm(self.auto_save_dir):
            return False
        cur = self.added_folders()
        if any(_norm(p) == _norm(path) for p in cur):
            return False
        self.settings.setValue(FOLDERS_KEY, cur + [os.path.normpath(path)])
        self.settings.sync()
        self.refresh()
        return True

    def remove_folder(self, path: str) -> bool:
        """The auto-save folder cannot be removed."""
        if _norm(path) == _norm(self.auto_save_dir):
            return False
        cur = self.added_folders()
        keep = [p for p in cur if _norm(p) != _norm(path)]
        if len(keep) == len(cur):
            return False
        self.settings.setValue(FOLDERS_KEY, keep)
        self.settings.sync()
        self.refresh()
        return True

    def set_auto_save_dir(self, path: str) -> None:
        self.auto_save_dir = path
        self.refresh()

    def set_client(self, client) -> None:
        self.client = client
        self.refresh()

    def set_recording_path(self, path: Optional[str]) -> None:
        self._recording = path
        if path is not None:   # a sweep is running: no parsing at all until it ends
            self._means.cancel()
            self._todo = {}
        self.model.set_recording(path)
        self._update_buttons()

    # -- refresh --------------------------------------------------------------
    def _get_cache(self) -> MeanTempCache:
        with self._cache_lock:
            if self._cache is None:
                self._cache = MeanTempCache(self._cache_path or run_index.default_cache_path())
            return self._cache

    def refresh(self) -> None:
        """Returns at once: the scan runs in the worker pool."""
        self._gen += 1
        self._means.cancel()
        self._todo = {}
        self.status.setText("Scanning\u2026")
        self._pool.start(_ScanWorker(self._gen, self.folders(), self._get_cache, self._signals))

    def _on_scanned(self, gen: int, runs, truncated: bool, means) -> None:
        if gen != self._gen:
            return
        self._truncated = truncated
        rec = _norm(self._recording) if self._recording else None
        means = {p: m for p, m in means.items() if rec is None or _norm(p) != rec}
        todo = [r for r in runs if r.is_capture and r.path not in means
                and (rec is None or _norm(r.path) != rec)]   # a growing file: skip
        self.model.set_runs(runs, means)
        self.model.set_recording(self._recording)
        self._update_status(len(runs))
        self._update_buttons()
        if todo and rec is None:   # nothing is parsed while a run is being recorded
            self._todo = {r.path: r for r in todo}
            self._means.submit(gen, [r.path for r in todo])
        cap = [r for r in runs if r.is_capture]
        if self.client is None:
            self.model.set_cloud_error("Not connected to the cloud")
        elif cap:
            self._pool.start(_CloudWorker(gen, cap, self.client, self._signals))
        else:
            self.model.set_saved({})

    def _on_scan_failed(self, gen: int, reason: str) -> None:
        if gen == self._gen:
            self.status.setText(reason)

    def _update_status(self, n: int) -> None:
        msg = f"{n} run file{'s' if n != 1 else ''}"
        if self._truncated:
            msg += f" (stopped at {run_index.MAX_FILES}; remove a folder to see the rest)"
        self.status.setText(msg)

    def wait_for_workers(self, msecs: int = 30000) -> bool:
        """Block until the workers and the results they queued are all done (tests)."""
        import time
        from PySide6.QtCore import QCoreApplication
        end = time.monotonic() + msecs / 1000.0
        for _ in range(10):   # a finished scan starts the next workers
            if not self._pool.waitForDone(max(1, int((end - time.monotonic()) * 1000))):
                return False
            QCoreApplication.processEvents()
            while self._means.pending() and time.monotonic() < end:
                QCoreApplication.processEvents()
                time.sleep(0.005)
            QCoreApplication.processEvents()
            if self._pool.activeThreadCount() == 0 and not self._means.pending():
                return True
        return True

    def shutdown(self) -> None:
        """Stop the mean-temperature process and forget what is queued (window closing)."""
        self._gen += 1   # whatever is still running is stale
        self._means.shutdown()
        try:
            if self._cache is not None:
                self._cache.save()
        except Exception:
            pass

    def _on_mean(self, gen: int, path: str, mean) -> None:
        if gen != self._gen or self._recording is not None:
            return
        run = self._todo.pop(path, None)
        if run is not None:
            self._get_cache().put(run, mean)
        self.model.set_mean(path, mean)   # ignores the recording file

    def _on_means_idle(self, gen: int) -> None:
        if gen == self._gen:
            self._get_cache().save()

    def _on_saved(self, gen: int, saved) -> None:
        if gen == self._gen:
            self.model.set_saved(saved)

    def _on_cloud_error(self, gen: int, reason: str) -> None:
        if gen == self._gen:
            self.model.set_cloud_error(reason)

    # -- actions ----------------------------------------------------------------
    def _selected_run(self) -> Optional[RunInfo]:
        rows = self.table.selectionModel().selectedRows()
        return self.model.runs[rows[0].row()] if rows else None

    def _can_analyze(self, run: Optional[RunInfo]) -> bool:
        return run is not None and run.is_capture and not self.model.is_recording(run)

    def _update_buttons(self) -> None:
        run = self._selected_run()
        self.analyze_btn.setEnabled(self._can_analyze(run))
        if run is None:
            tip = "Select a run first"
        elif self.model.is_recording(run):
            tip = RECORDING_TIP
        elif not run.is_capture:
            tip = NOT_CAPTURE_TIP
        else:
            tip = ""
        self.analyze_btn.setToolTip(tip)
        self.remove_btn.setEnabled(bool(self.added_folders()))

    def analyze_selected(self) -> None:
        run = self._selected_run()
        if self._can_analyze(run):
            self.open_run.emit(run.path)

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open a run file", self.auto_save_dir,
                                              "Run files (*.csv *.txt);;All files (*)")
        if not path:
            return
        if self._recording and _norm(path) == _norm(self._recording):
            self.status.setText(RECORDING_TIP)   # same refusal as the list's Analyze
            return
        self.open_run.emit(path)

    def _choose_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Add a folder of runs", self.auto_save_dir)
        if path:
            self.add_folder(path)

    def _choose_folder_to_remove(self) -> None:
        added = self.added_folders()
        if not added:
            return
        path, ok = QInputDialog.getItem(self, "Remove folder", "Folder to stop listing:",
                                        added, 0, False)
        if ok and path:
            self.remove_folder(path)
