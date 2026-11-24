"""The Runs tab: recorded run files, and a way into the analysis of one."""
from __future__ import annotations

import os
from typing import Dict, List, Optional

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QObject, QRunnable,
                            QSettings, QThreadPool, Qt, Signal)
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView,
                               QInputDialog, QLabel, QPushButton, QTableView,
                               QVBoxLayout, QWidget)

from ctwa import theme
from ctwa.ui import run_index
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
        self.means[path] = mean
        for r, run in enumerate(self.runs):
            if run.path == path:
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
                return QBrush(QColor(theme.P.text_faint))
        elif c == _STARTED:
            if role == Qt.DisplayRole and run.started:
                return run.started.strftime("%Y-%m-%d %H:%M")
        elif c == _LENGTH:
            if role == Qt.DisplayRole:
                return "recording" if self.is_recording(run) else _fmt_length(run.length_s)
        elif c in (_SAVED, _SAMPLE):
            return self._cloud_data(run, c, role)
        elif c == _TEMP:
            m = self.means.get(run.path)
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
    mean = Signal(int, str, object)   # generation, path, mean or None
    saved = Signal(int, object)       # generation, {path: SavedInfo}
    cloud_error = Signal(int, str)
    done = Signal(int)


class _MeanWorker(QRunnable):
    def __init__(self, gen: int, runs: List[RunInfo], cache: MeanTempCache,
                 signals: _Signals, is_current):
        super().__init__()
        self.gen, self.runs, self.cache = gen, runs, cache
        self.signals, self.is_current = signals, is_current

    def run(self):
        for r in self.runs:
            if not self.is_current(self.gen):
                break
            mean = run_index.compute_mean_temperature(r)
            self.cache.put(r, mean)
            self.signals.mean.emit(self.gen, r.path, mean)
        self.cache.save()
        self.signals.done.emit(self.gen)


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
        self.model.set_recording(path)
        self._update_buttons()

    # -- refresh --------------------------------------------------------------
    def _get_cache(self) -> MeanTempCache:
        if self._cache is None:
            self._cache = MeanTempCache(self._cache_path or run_index.default_cache_path())
        return self._cache

    def refresh(self) -> None:
        self._gen += 1
        gen = self._gen
        runs, self._truncated = run_index.scan_limited(self.folders())
        cache = self._get_cache()
        means: Dict[str, Optional[float]] = {}
        todo: List[RunInfo] = []
        rec = _norm(self._recording) if self._recording else None
        for r in runs:
            if not r.is_capture:
                continue
            known, mean = cache.lookup(r)
            if known:
                means[r.path] = mean
            elif rec is None or _norm(r.path) != rec:   # a growing file: skip
                todo.append(r)
        self.model.set_runs(runs, means)
        self.model.set_recording(self._recording)
        self._update_status(len(runs))
        self._update_buttons()

        sig = _Signals(self)
        sig.mean.connect(self._on_mean, Qt.QueuedConnection)
        sig.saved.connect(self._on_saved, Qt.QueuedConnection)
        sig.cloud_error.connect(self._on_cloud_error, Qt.QueuedConnection)
        if todo:
            self._pool.start(_MeanWorker(gen, todo, cache, sig, lambda g: g == self._gen))
        cap = [r for r in runs if r.is_capture]
        if self.client is None:
            self.model.set_cloud_error("Not connected to the cloud")
        elif cap:
            self._pool.start(_CloudWorker(gen, cap, self.client, sig))
        else:
            self.model.set_saved({})

    def _update_status(self, n: int) -> None:
        msg = f"{n} run file{'s' if n != 1 else ''}"
        if self._truncated:
            msg += f" (stopped at {run_index.MAX_FILES}; remove a folder to see the rest)"
        self.status.setText(msg)

    def wait_for_workers(self, msecs: int = 30000) -> bool:
        return self._pool.waitForDone(msecs)

    def _on_mean(self, gen: int, path: str, mean) -> None:
        if gen == self._gen:
            self.model.set_mean(path, mean)

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
            tip = "This run is being recorded"
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
        if path:
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
