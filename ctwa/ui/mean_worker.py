"""Qt bridge to the mean-temperature process of the Runs tab.

Parsing a run file takes 90-210 ms of pure Python; doing it for a whole auto-save folder in
a QThreadPool thread would hold the GUI process's GIL (and so slow the instrument sweep
thread) for minutes. Here the parsing happens in a separate single-process pool (spawn: the
child never imports PySide6). The pool's result thread only emits a queued signal."""
from __future__ import annotations

from concurrent.futures import Future, ProcessPoolExecutor
from multiprocessing import get_context
from typing import Dict, List, Optional

from PySide6.QtCore import QCoreApplication, QObject, Signal, Slot

from ctwa.analysis import runner

__all__ = ["MeanTempWorker"]


class MeanTempWorker(QObject):
    mean = Signal(int, str, object)   # generation, path, mean temperature or None
    idle = Signal(int)                # generation whose last queued file has been answered

    _delivered = Signal(int, str, object, bool)  # generation, path, mean, ok

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._executor: Optional[ProcessPoolExecutor] = None
        self._futures: List[Future] = []
        self._left: Dict[int, int] = {}   # generation -> files not answered yet
        self._delivered.connect(self._on_delivered)
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    def pending(self) -> int:
        return sum(self._left.values())

    def submit(self, gen: int, paths: List[str]) -> None:
        """Queue files; they are parsed one after the other, in the child."""
        if not paths:
            return
        if self._executor is None:
            self._executor = ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn"))
        self._left[gen] = self._left.get(gen, 0) + len(paths)
        for p in paths:
            try:
                fut = self._executor.submit(runner.file_mean_temperature, p)
            except Exception:   # a broken pool: start afresh once
                self._discard()
                self._executor = ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn"))
                fut = self._executor.submit(runner.file_mean_temperature, p)
            self._futures.append(fut)
            fut.add_done_callback(lambda f, g=gen, path=p: self._on_future(g, path, f))

    def cancel(self) -> None:
        """Drop everything not started yet. The file being parsed finishes; its answer is
        ignored."""
        for f in self._futures:
            f.cancel()
        self._futures = []
        self._left = {}

    def shutdown(self) -> None:
        self._left = {}
        self._discard()

    # ---- internals ----
    def _discard(self) -> None:
        ex, self._executor = self._executor, None
        self._futures = []
        if ex is None:
            return
        try:
            for p in list((getattr(ex, "_processes", None) or {}).values()):
                try:
                    p.terminate()
                    p.join(2)
                except Exception:
                    pass
        finally:
            ex.shutdown(wait=False, cancel_futures=True)

    def _on_future(self, gen: int, path: str, fut: Future) -> None:
        # the pool's thread: only turn the outcome into a signal
        if fut.cancelled():
            return
        exc = fut.exception()
        try:
            if exc is None:
                self._delivered.emit(gen, path, fut.result(), True)
            else:   # e.g. the process died: nothing to cache for this file
                self._delivered.emit(gen, path, None, False)
        except RuntimeError:   # the worker was deleted meanwhile
            pass

    @Slot(int, str, object, bool)
    def _on_delivered(self, gen: int, path: str, mean, ok: bool) -> None:
        if gen not in self._left:
            return   # cancelled
        self._left[gen] -= 1
        if ok:
            self.mean.emit(gen, path, mean)
        if self._left[gen] <= 0:
            del self._left[gen]
            self.idle.emit(gen)
