"""Qt bridge to the analysis process.

AnalysisWorker lives in the GUI thread. Jobs go to a one-process pool (spawn,
so the child never imports PySide6); the pool's own result-handling thread
calls our done-callback, which only emits a signal. The signal is connected to
a slot of this QObject, so Qt queues it into the GUI thread."""

from __future__ import annotations

import itertools
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from multiprocessing import get_context
from typing import Optional

from PySide6.QtCore import QCoreApplication, QObject, Signal, Slot

from ctwa.analysis import runner
from ctwa.analysis.types import PipelineError

__all__ = ["AnalysisWorker"]


class AnalysisWorker(QObject):
    loaded = Signal(object)    # LoadedRun
    finished = Signal(object)  # AnalysisResults
    region_ready = Signal(object)  # runner.region_info's (period, smoothed) for the last request
    region_failed = Signal(str, str)  # a region_info request failed (same kinds as `failed`)
    failed = Signal(str, str)  # kind ("pipeline" | "analysis" | "crash"), message

    # request id, "loaded"/"finished"/"failed", payload or (kind, message)
    _delivered = Signal(int, str, object)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._executor: Optional[ProcessPoolExecutor] = None
        self._ids = itertools.count(1)
        self._current = 0  # the only request whose result is still wanted
        self._busy = False  # a request is in flight in the process
        self._delivered.connect(self._on_delivered)
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    # ---- public API (GUI thread) ----
    def load(self, path: str) -> None:
        self._submit("loaded", runner.load_run, path)

    def analyze(self, path: str, opts) -> None:
        self._submit("finished", runner.analyze_run, path, opts)

    def region_info(self, path: str, sel_min: float, sel_max: float, smooth: bool,
                    wave: str = "sine") -> None:
        self._submit("region", runner.region_info, path, sel_min, sel_max, smooth, wave)

    def cancel(self) -> None:
        """Drop the running request (its result is ignored). The process is only
        replaced if it is busy; an idle one keeps its warm start and parse cache."""
        self._current = next(self._ids)
        if self._busy:
            self._busy = False
            self._discard_pool()

    def shutdown(self) -> None:
        self._current = next(self._ids)
        self._busy = False
        self._discard_pool()

    # ---- internals ----
    def _ensure_pool(self) -> ProcessPoolExecutor:
        if self._executor is None:
            self._executor = ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn"))
        return self._executor

    def _discard_pool(self) -> None:
        ex, self._executor = self._executor, None
        if ex is None:
            return
        try:
            for p in list((getattr(ex, "_processes", None) or {}).values()):
                try:
                    p.terminate()
                    p.join(2)  # no zombie left behind
                except Exception:
                    pass
        finally:
            ex.shutdown(wait=False, cancel_futures=True)

    def _submit(self, ok_kind: str, fn, *args) -> None:
        # a newer request supersedes the older one (that job still finishes
        # in the process first; its result is dropped by id)
        req = next(self._ids)
        self._current = req
        if self._busy:
            self._discard_pool()  # never queue behind a slow old job
        self._busy = True
        try:
            fut = self._ensure_pool().submit(fn, *args)
        except Exception as e:  # pool already broken
            self._discard_pool()
            try:
                fut = self._ensure_pool().submit(fn, *args)
            except Exception as e2:
                self._delivered.emit(req, self._fail_kind(ok_kind),
                                     ("crash", "could not start the analysis process: %s" % e2))
                return
        fut.add_done_callback(lambda f, req=req, k=ok_kind: self._on_future(req, k, f))

    @staticmethod
    def _fail_kind(ok_kind: str) -> str:
        # region requests have their own failure signal, so a failed snap is never
        # taken for a failed load or analysis
        return "region_failed" if ok_kind == "region" else "failed"

    def _on_future(self, req: int, ok_kind: str, fut: Future) -> None:
        # runs in the pool's thread: only turn the outcome into a signal
        if fut.cancelled():
            return
        exc = fut.exception()
        fail = self._fail_kind(ok_kind)
        if exc is None:
            self._delivered.emit(req, ok_kind, fut.result())
        elif isinstance(exc, PipelineError):
            self._delivered.emit(req, fail, ("pipeline", exc.code))
        elif isinstance(exc, ValueError):
            self._delivered.emit(req, fail, ("analysis", str(exc)))
        elif isinstance(exc, BrokenProcessPool):
            self._delivered.emit(req, fail, ("crash", "the analysis process stopped unexpectedly"))
        else:
            self._delivered.emit(req, fail, ("crash", "%s: %s" % (type(exc).__name__, exc)))

    @Slot(int, str, object)
    def _on_delivered(self, req: int, kind: str, payload: object) -> None:
        if req != self._current:
            return  # superseded or cancelled
        self._busy = False
        if kind in ("failed", "region_failed"):
            fail_kind, message = payload
            if fail_kind == "crash":
                self._discard_pool()  # next request gets a fresh process
            (self.region_failed if kind == "region_failed" else self.failed).emit(fail_kind, message)
        elif kind == "loaded":
            self.loaded.emit(payload)
        elif kind == "region":
            self.region_ready.emit(payload)
        else:
            self.finished.emit(payload)
