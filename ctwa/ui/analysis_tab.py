"""The Analysis tab: one run, its region and peaks on a plot, settings, Analyze, results.

Loading and analysis both go through AnalysisWorker (a separate process), so the
GUI thread only draws. Results are shown here and announced through
`result_ready`; saving is somebody else's job."""
from __future__ import annotations

import os
from typing import List, Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QSplitter, QVBoxLayout, QWidget)

from ctwa import theme
from ctwa.analysis.runner import LoadedRun, RegionInfo
from ctwa.analysis.jsmath import js_round
from ctwa.analysis.sine_fit import refine_peak
from ctwa.analysis.types import PipelineOptions
from ctwa.ui.analysis_results import ResultsPanel
from ctwa.ui.analysis_settings import SettingsPanel
from ctwa.ui.analysis_worker import AnalysisWorker

MARKER_NAMES = ("S1", "S2", "R1", "R2")  # source peak 1, 2; response peak 1, 2


def _round2(x: float) -> float:
    return round(x, 2)


class AnalysisTab(QWidget):
    result_ready = Signal(object)  # (LoadedRun, PipelineOptions, AnalysisResults, plot or None)
    result_cleared = Signal()      # the result announced last no longer stands (new run / Analyze / failure / settings or region changed)
    run_loaded = Signal(object)    # LoadedRun, once the plot shows it

    def __init__(self, parent: Optional[QWidget] = None, settings=None) -> None:
        super().__init__(parent)
        self._app_settings = settings   # the app's QSettings (splitter state), or None
        self.run: Optional[LoadedRun] = None
        self.worker = AnalysisWorker(self)
        self._path: Optional[str] = None
        self._loading = False
        self._running = False
        self._options: Optional[PipelineOptions] = None
        self._placed_for = None  # (sel_min, sel_max) the markers were last placed for
        self._has_results = False
        self._info = {}        # (path, sel_min, sel_max, smooth, wave) -> runner.RegionInfo
        self._pending = {}     # marker index -> dropped time, waiting for the smoothed series
        self._pending_key = None
        self._place_pending = False

        root = QVBoxLayout(self)
        self.title = theme.set_role(QLabel("Open a run from the Runs tab"), "heading")
        root.addWidget(self.title)
        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self._build_plot())
        root.addWidget(self.splitter, stretch=1)

        bottom_area = QWidget()
        bottom = QHBoxLayout(bottom_area)
        bottom.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()   # a short bottom half scrolls instead of refusing to shrink
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(bottom_area)
        self.splitter.addWidget(scroll)
        self.splitter.setStretchFactor(0, 45)
        self.splitter.setStretchFactor(1, 55)
        self.splitter.setSizes([450, 550])
        self._restore_splitter()
        self.splitter.splitterMoved.connect(self._save_splitter)
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
        self._right = QVBoxLayout()   # the results column; set_save_panel adds below
        self._right.addWidget(self.results_panel, stretch=1)
        bottom.addLayout(self._right, stretch=1)

        self.analyze_btn.clicked.connect(self._on_analyze)
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.worker.loaded.connect(self._on_loaded)
        self.worker.region_ready.connect(self._on_region_ready)
        self.worker.region_failed.connect(self._on_region_failed)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.settings.changed.connect(self._on_settings_changed)
        self.settings.mode_changed.connect(lambda _m: self._on_settings_changed())
        self._update_controls()

    def _restore_splitter(self) -> None:
        if self._app_settings is None:
            return
        try:
            state = self._app_settings.value("analysis/splitter")
            if state:
                self.splitter.restoreState(state)
        except Exception:
            pass

    def _save_splitter(self, *_args) -> None:
        if self._app_settings is not None:
            self._app_settings.setValue("analysis/splitter", self.splitter.saveState())

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

    def set_save_panel(self, panel: QWidget) -> None:
        """Put the save panel under the results and feed it each finished analysis."""
        self._right.addWidget(panel)
        self.result_ready.connect(panel.set_result)
        self.result_cleared.connect(panel.clear_result)

    # ---- opening ----
    def open_run(self, path: str) -> None:
        self._path = path
        self.run = None
        self._loading = True
        self._running = False
        self._has_results = False
        self._placed_for = None
        self._info = {}
        self._pending = {}
        self._pending_key = None
        self._place_pending = False
        self.result_cleared.emit()
        self.src_curve.clear()
        self.resp_curve.clear()
        self.region.setBounds((None, None))
        self.region.setRegion((0, 1))
        self.title.setText(os.path.basename(path) + "  —  Loading...")
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

    def _smooth_wanted(self) -> bool:
        return self.settings.smooth_check.isChecked() and self.settings.wave() == "sine"

    def _info_key(self):
        lo, hi = self._region()
        return (self.run.path, lo, hi, self._smooth_wanted(), self.settings.wave())

    def _snap(self, which: str, x: float, info: RegionInfo) -> float:
        """x moved onto the peak it points at (page.tsx toPeak), on the series the worker
        prepared (smoothed, or raw with its slow baseline taken off). Where no peak is
        found the time stays, rounded."""
        if not info.period or info.snap is None:
            return _round2(x)
        ts, vs, tc, vc = info.snap
        t, v = (ts, vs) if which == "src" else (tc, vc)
        peak = refine_peak(t, v, x, info.period) if len(t) else None
        return _round2(peak[0] if peak else x)

    def _request_region(self, key) -> None:
        """Ask the worker for a region's period (and smoothed series). Whatever was queued
        for another region is stale and goes."""
        if self._pending_key != key:
            self._pending = {}
            self._place_pending = False
        self._pending_key = key
        self.worker.region_info(*key)
        self._update_controls()

    def _snap_markers(self, items) -> None:
        """Move markers {index: time} onto their peaks. The region's period (and the smoothed
        series) come from the worker; until they arrive the markers stay where they are."""
        if not items or self.run is None or self._running:
            return
        key = self._info_key()
        if key not in self._info:
            self._request_region(key)
            self._pending.update(items)
            return
        info = self._info[key]
        for i, x in items.items():
            self.markers[i].setValue(self._snap("src" if i < 2 else "resp", x, info))

    def _on_region_ready(self, info) -> None:
        key, self._pending_key = self._pending_key, None
        if key is None or self.run is None:
            return
        self._info[key] = info
        items, self._pending = self._pending, {}
        place, self._place_pending = self._place_pending, False
        if key == self._info_key():
            if place:
                self._place_with(info)
            self._snap_markers(items)
        self._update_controls()

    def _on_marker_dropped(self, line) -> None:
        if self.run is not None:
            self._snap_markers({self.markers.index(line): line.value()})

    def _place_markers(self) -> None:
        """Put the markers on detected peaks, as the webapp does when the peaks step opens."""
        self._placed_for = self._region()
        key = self._info_key()
        if key not in self._info:
            self._request_region(key)
            self._place_pending = True
            return
        self._place_with(self._info[key])

    def _place_with(self, info: RegionInfo) -> None:
        if info.placement is None:
            return
        self._snap_markers(dict(enumerate(info.placement)))

    def _ensure_markers_placed(self) -> None:
        if self.run is not None and self.settings.manual() and self._placed_for != self._region():
            self._place_markers()

    # ---- running ----
    def is_running(self) -> bool:
        return self._running

    def is_snapping(self) -> bool:
        """Markers are waiting for the region's period (and smoothed series) from the worker."""
        return self._pending_key is not None

    def _options_now(self) -> PipelineOptions:
        lo, hi = self._region()
        manual = self.settings.manual()
        return PipelineOptions(
            wave_type=self.settings.wave(),
            smooth_to_sine=self.settings.smooth_check.isChecked() and self.settings.wave() == "sine",
            sel_min=lo, sel_max=hi,
            params=self.settings.build_params(),
            square_period=self.settings.square_period(),
            clicks=[(m.value(), 0.0) for m in self.markers] if manual else None,
        )

    def _on_analyze(self) -> None:
        if self._running or self.run is None or self._loading:
            return
        self._options = self._options_now()
        self._pending = {}
        self._pending_key = None
        self._place_pending = False
        self._running = True
        self._has_results = False
        self.result_cleared.emit()
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

    def _on_finished(self, outcome) -> None:
        if not self._running or self.run is None:
            return
        res, plot = outcome   # the worker built the plot too: no maths here
        self._running = False
        self._has_results = True
        self.results_panel.show_results(res)
        self._update_controls()
        self.result_ready.emit((self.run, self._options, res, plot))

    def _on_failed(self, kind: str, message: str) -> None:
        """A load or an analysis failed."""
        was_loading = self._loading
        self._running = False
        self._loading = False
        self._has_results = False
        self.result_cleared.emit()
        if was_loading and self._path:
            self.title.setText(os.path.basename(self._path))
        self.results_panel.show_error(kind, message, during_load=was_loading)
        self._update_controls()

    def _on_region_failed(self, _kind: str, _message: str) -> None:
        """The region's period / smoothed series could not be had: markers stay where
        they are and Analyze is free again."""
        self._pending_key = None
        self._pending = {}
        self._place_pending = False
        self._has_results = False
        self.results_panel.show_note("Couldn't snap the markers; they stay where you dropped them.")
        self._update_controls()

    # ---- changes ----
    def _on_region_changed(self) -> None:
        """A finished drag: whole seconds, as the webapp's overview (Math.round)."""
        lo, hi = self.region.getRegion()
        if (js_round(lo), js_round(hi)) != (lo, hi):
            self.region.setRegion((js_round(lo), js_round(hi)))
        self._on_settings_changed()

    def _on_settings_changed(self) -> None:
        if self._has_results:
            self._has_results = False
            self.results_panel.show_stale()
            self.result_cleared.emit()   # Save waits for the next analysis
        self._ensure_markers_placed()
        self._update_controls()

    def _update_controls(self) -> None:
        manual = self.settings.manual() and self.run is not None
        for m in self.markers:
            m.setVisible(manual)
        ready = self.run is not None and not self._running and not self._loading and not self.is_snapping() \
            and self.settings.radii_ok()
        self.analyze_btn.setEnabled(ready)
        self.cancel_btn.setVisible(self._running)
        self.region.setMovable(not self._running)
        for m in self.markers:
            m.setMovable(not self._running)
        self.settings.setEnabled(not self._running)
