"""The Analysis tab: one run, its region and peaks on a plot, settings, Analyze, results.

Loading and analysis both go through AnalysisWorker (a separate process), so the
GUI thread only draws. Results are shown here and announced through
`result_ready`; saving is somebody else's job."""
from __future__ import annotations

import math
import os
from typing import List, Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from ctwa import theme
from ctwa.analysis.peaks import snap_to_peak
from ctwa.analysis.runner import LoadedRun
from ctwa.analysis.sine_fit import refine_peak, remove_period_mean, sine_lag
from ctwa.analysis.types import AnalysisResults, PipelineOptions
from ctwa.ui.analysis_results import ResultsPanel
from ctwa.ui.analysis_settings import SettingsPanel
from ctwa.ui.analysis_worker import AnalysisWorker

MARKER_NAMES = ("S1", "S2", "R1", "R2")  # source peak 1, 2; response peak 1, 2


def _round2(x: float) -> float:
    return round(x, 2)


def _fft_period(ts: List[float], vs: List[float]) -> Optional[float]:
    """Period of the strongest sine in the region, from a zero-padded FFT (milliseconds).
    Only used for the reach of marker snapping, so it does not need the pipeline's
    own (much slower) estimate."""
    t = np.asarray(ts, dtype=float)
    v = np.asarray(vs, dtype=float)
    n = len(t)
    span = t[-1] - t[0] if n else 0.0
    if n < 16 or not span > 0:
        return None
    dt = span / (n - 1)
    v = v - np.polyval(np.polyfit(t - t[0], v, 1), t - t[0])
    spec = np.abs(np.fft.rfft(v * np.hanning(n), n=8 * n))
    f = np.fft.rfftfreq(8 * n, d=dt)
    ok = f >= 2.0 / span  # at least two cycles in the region
    if not ok.any():
        return None
    k = int(np.argmax(np.where(ok, spec, 0.0)))
    return 1.0 / f[k] if f[k] > 0 else None


class AnalysisTab(QWidget):
    result_ready = Signal(object)  # (LoadedRun, PipelineOptions, AnalysisResults)
    run_loaded = Signal(object)    # LoadedRun, once the plot shows it

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.run: Optional[LoadedRun] = None
        self.worker = AnalysisWorker(self)
        self._path: Optional[str] = None
        self._loading = False
        self._running = False
        self._options: Optional[PipelineOptions] = None
        self._placed_for = None  # (sel_min, sel_max) the markers were last placed for
        self._has_results = False

        root = QVBoxLayout(self)
        self.title = theme.set_role(QLabel("Open a run from the Runs tab"), "heading")
        root.addWidget(self.title)
        root.addWidget(self._build_plot(), stretch=3)

        bottom = QHBoxLayout()
        root.addLayout(bottom, stretch=2)
        left = QVBoxLayout()
        self.settings = SettingsPanel()
        left.addWidget(self.settings, stretch=1)
        buttons = QHBoxLayout()
        self.analyze_btn = theme.set_role(QPushButton("Analyze"), "primary")
        self.analyze_btn.setEnabled(False)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.hide()
        buttons.addWidget(self.analyze_btn)
        buttons.addWidget(self.cancel_btn)
        buttons.addStretch(1)
        left.addLayout(buttons)
        bottom.addLayout(left, stretch=1)
        self.results_panel = ResultsPanel()
        bottom.addWidget(self.results_panel, stretch=1)

        self.analyze_btn.clicked.connect(self._on_analyze)
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.worker.loaded.connect(self._on_loaded)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.settings.changed.connect(self._on_settings_changed)
        self.settings.mode_changed.connect(lambda _m: self._on_settings_changed())
        self._update_controls()

    # ---- plot ----
    def _build_plot(self) -> QWidget:
        self.plot = pg.PlotWidget()
        theme.style_plot(self.plot)
        item = self.plot.getPlotItem()
        item.setLabel("bottom", "Time (s)")
        item.setLabel("left", "Source (mW)")
        item.showAxis("right")
        item.setLabel("right", "Response (mW)")
        self._src_color = theme.series_color("Power")
        self._resp_color = theme.series_color("Heat Flow")
        # the response has its own scale, on the right
        self._vb2 = pg.ViewBox()
        item.scene().addItem(self._vb2)
        item.getAxis("right").linkToView(self._vb2)
        self._vb2.setXLink(item)
        self._vb2.setAcceptedMouseButtons(Qt.NoButton)  # clicks and drags reach the region and markers
        self._vb2.setMouseEnabled(False, False)
        item.vb.sigResized.connect(self._sync_views)
        self.src_curve = pg.PlotDataItem(pen=theme.pen(self._src_color))
        self.resp_curve = pg.PlotDataItem(pen=theme.pen(self._resp_color))
        theme.fast_curve(self.src_curve)
        theme.fast_curve(self.resp_curve)
        item.addItem(self.src_curve)
        self._vb2.addItem(self.resp_curve)
        theme.style_axis(item.getAxis("right"))
        item.getAxis("left").setTextPen(pg.mkPen(self._src_color))
        item.getAxis("right").setTextPen(pg.mkPen(self._resp_color))

        accent = QColor(theme.P.accent)
        accent.setAlpha(60)
        self.region = pg.LinearRegionItem(
            (0, 1), brush=pg.mkBrush(accent), pen=pg.mkPen(theme.P.accent_strong, width=1.5))
        self.region.setZValue(-10)
        item.addItem(self.region)
        self.region.sigRegionChangeFinished.connect(self._on_region_changed)

        self.markers: List[pg.InfiniteLine] = []
        for i, name in enumerate(MARKER_NAMES):
            color = self._src_color if i < 2 else self._resp_color
            line = pg.InfiniteLine(
                pos=0, angle=90, movable=True, pen=theme.pen(color, 1.6, dashed=True),
                hoverPen=theme.pen(color, 3), label=name,
                labelOpts={"position": 0.95, "color": color, "movable": False})
            line.setZValue(10)
            line.setVisible(False)
            line.sigPositionChangeFinished.connect(self._on_marker_dropped)
            item.addItem(line)
            self.markers.append(line)
        return self.plot

    def _sync_views(self) -> None:
        vb = self.plot.getPlotItem().vb
        self._vb2.setGeometry(vb.sceneBoundingRect())
        self._vb2.linkedViewChanged(vb, self._vb2.XAxis)

    # ---- opening ----
    def open_run(self, path: str) -> None:
        self._path = path
        self.run = None
        self._loading = True
        self._running = False
        self._has_results = False
        self._placed_for = None
        self.title.setText(os.path.basename(path) + "  —  loading…")
        self.results_panel.clear()
        self.worker.load(path)
        self._update_controls()

    def _on_loaded(self, run: LoadedRun) -> None:
        if run.path != self._path:
            return
        self.run = run
        self._loading = False
        s = run.synced
        self.src_curve.setData(np.asarray(s.t_src), np.asarray(s.v_src))
        self.resp_curve.setData(np.asarray(s.t_cal), np.asarray(s.v_cal))
        lo = min(s.t_src[0], s.t_cal[0])
        hi = max(s.t_src[-1], s.t_cal[-1])
        self.region.setBounds((lo, hi))
        sel_min, sel_max, clicks = run.default
        self.region.setRegion((sel_min, sel_max))
        for line, (t, _v) in zip(self.markers, clicks):
            line.setValue(t)
        self._sync_views()
        self.plot.getPlotItem().vb.autoRange()
        self._vb2.autoRange()
        started = run.header.get("started")
        self.title.setText(os.path.basename(run.path) + (("  —  %s" % started) if started else ""))
        self._ensure_markers_placed()
        self._update_controls()
        self.run_loaded.emit(run)

    # ---- manual markers ----
    def _region(self):
        lo, hi = self.region.getRegion()
        return lo, hi

    def _slice(self, t, v):
        lo, hi = self._region()
        t = np.asarray(t)
        m = (t >= lo) & (t <= hi)
        return t[m].tolist(), np.asarray(v)[m].tolist()

    def _period(self, ts, vs) -> Optional[float]:
        override = self.settings.fft_period()
        if override and self.settings.mode() in ("AutoFFT", "AutoFit"):
            return override
        if len(ts) < 10:
            return None
        est = _fft_period(ts, vs)
        return est if est is not None and math.isfinite(est) and est > 0 else None

    def _marker_series(self, which: str):
        """Region slice a marker snaps on: the source or the response, with the
        slow baseline taken off when the region is three periods or more (as the webapp's chart)."""
        s = self.run.synced
        ts, vs = self._slice(s.t_src, s.v_src)
        tc, vc = self._slice(s.t_cal, s.v_cal)
        T = self._period(ts, vs)
        t, v = (ts, vs) if which == "src" else (tc, vc)
        if T and len(t) > 1 and (t[-1] - t[0]) / T >= 3:
            ft, fv = remove_period_mean(t, v, T)
            if len(ft) > 10:
                t, v = ft, fv
        return t, v, T, (ts, vs, tc, vc)

    def snap_time(self, which: str, x: float) -> float:
        """x moved onto the peak it points at (never further than a quarter period);
        the nearest highest sample when the period is not known."""
        t, v, T, _ = self._marker_series(which)
        if not t:
            return _round2(x)
        peak = refine_peak(t, v, x, T) if T else None
        if peak:
            return _round2(peak[0])
        return _round2(snap_to_peak(x, t, v)[0])

    def _on_marker_dropped(self, line) -> None:
        if self.run is None:
            return
        i = self.markers.index(line)
        line.setValue(self.snap_time("src" if i < 2 else "resp", line.value()))

    def _place_markers(self) -> None:
        """Put the markers on detected peaks, as the webapp does when the peaks step opens."""
        _, _, T, (ts, vs, tc, vc) = self._marker_series("src")
        self._placed_for = self._region()
        if not T:
            return
        fit = sine_lag(ts, vs, tc, vc, T)
        if fit is None:
            return
        w = 2 * math.pi / T
        lo_t, hi_t = max(ts[0], tc[0]) + T / 4, min(ts[-1], tc[-1]) - T / 4
        peaks = []
        k = math.ceil((lo_t * w - fit.phase_src) / (2 * math.pi))
        while True:
            at = (fit.phase_src + 2 * math.pi * k) / w
            if at + fit.lag > hi_t:
                break
            peaks.append(at)
            k += 1
        if not peaks:
            return
        first = peaks[0]
        last = peaks[-1] if len(peaks) > 1 else first + T
        for line, which, x in zip(self.markers, ("src", "src", "resp", "resp"),
                                  (first, last, first + fit.lag, last + fit.lag)):
            line.setValue(self.snap_time(which, x))

    def _ensure_markers_placed(self) -> None:
        if self.run is not None and self.settings.manual() and self._placed_for != self._region():
            self._place_markers()

    # ---- running ----
    def is_running(self) -> bool:
        return self._running

    def _options_now(self) -> PipelineOptions:
        lo, hi = self._region()
        manual = self.settings.manual()
        return PipelineOptions(
            wave_type=self.settings.wave(),
            smooth_to_sine=self.settings.smooth_check.isChecked() and self.settings.wave() == "sine",
            sel_min=_round2(lo), sel_max=_round2(hi),
            params=self.settings.build_params(),
            square_period=self.settings.square_period(),
            clicks=[(m.value(), 0.0) for m in self.markers] if manual else None,
        )

    def _on_analyze(self) -> None:
        if self._running or self.run is None or self._loading:
            return
        self._options = self._options_now()
        self._running = True
        self._has_results = False
        self.results_panel.show_busy()
        self._update_controls()
        self.worker.analyze(self.run.path, self._options)

    def _on_cancel(self) -> None:
        if not self._running:
            return
        self.worker.cancel()
        self._running = False
        self.results_panel.clear()
        self._update_controls()

    def _on_finished(self, res: AnalysisResults) -> None:
        if not self._running or self.run is None:
            return
        self._running = False
        self._has_results = True
        self.results_panel.show_results(res)
        self._update_controls()
        self.result_ready.emit((self.run, self._options, res))

    def _on_failed(self, kind: str, message: str) -> None:
        self._running = False
        self._loading = False
        self._has_results = False
        self.results_panel.show_error(kind, message)
        self._update_controls()

    # ---- changes ----
    def _on_region_changed(self) -> None:
        self._on_settings_changed()

    def _on_settings_changed(self) -> None:
        if self._has_results:
            self._has_results = False
            self.results_panel.show_stale()
        self._ensure_markers_placed()
        self._update_controls()

    def _update_controls(self) -> None:
        manual = self.settings.manual() and self.run is not None
        for m in self.markers:
            m.setVisible(manual)
        ready = self.run is not None and not self._running and not self._loading \
            and self.settings.radii_ok()
        self.analyze_btn.setEnabled(ready)
        self.cancel_btn.setVisible(self._running)
        self.settings.setEnabled(not self._running)
