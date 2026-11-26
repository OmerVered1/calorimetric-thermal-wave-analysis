"""The Analysis tab: one run, in steps like the webapp: 1 Setup, 2 Region, 3 Peaks (Manual
mode only), 4 Results. A step bar on top, the plot (hidden on Setup) above a stacked panel with
one page per step.

Loading and analysis both go through AnalysisWorker (a separate process), so the
GUI thread only draws. Results are shown here and announced through
`result_ready`; saving is somebody else's job."""
from __future__ import annotations

import os
from typing import List, Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QSplitter, QStackedWidget, QVBoxLayout, QWidget)

from ctwa import theme
from ctwa.analysis.runner import LoadedRun, RegionInfo
from ctwa.analysis.jsmath import js_round
from ctwa.analysis.sine_fit import refine_peak
from ctwa.analysis.types import PipelineOptions
from ctwa.ui.analysis_results import ResultsPanel
from ctwa.ui.analysis_settings import SettingsPanel
from ctwa.ui.analysis_worker import AnalysisWorker
from ctwa.ui.dual_axis import ResponseViewBox, link_y_zoom

MARKER_NAMES = ("S1", "S2", "R1", "R2")  # source peak 1, 2; response peak 1, 2
STEPS = (("setup", "1 Setup"), ("region", "2 Region"), ("peaks", "3 Peaks"), ("results", "4 Results"))
PEAKS_HINT = ("Drag S1 and S2 onto two neighbouring source peaks, R1 and R2 onto the response "
              "peaks that follow them.")
ZOOM_MARGIN = 0.05  # the Peaks and Results views show the region plus this share of its width each side


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

        self._step = "setup"
        self._save_panel = None
        root = QVBoxLayout(self)
        root.addLayout(self._build_step_bar())
        self.title = theme.set_role(QLabel("Open a run from the Runs tab"), "heading")
        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self._build_plot())
        root.addWidget(self.splitter, stretch=1)

        self.stack = QStackedWidget()
        scroll = QScrollArea()   # a short bottom half scrolls instead of refusing to shrink
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self.stack)
        self.splitter.addWidget(scroll)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)   # extra height goes to the plot
        self._restored = self._restore_splitter()
        self._moved = self._restored
        self.splitter.splitterMoved.connect(self._save_splitter)

        self.settings = SettingsPanel()
        self.results_panel = ResultsPanel()
        self.analyze_btn = theme.set_role(QPushButton("Analyze"), "primary")
        self.analyze_btn.setEnabled(False)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.hide()
        self._analyze_box = QWidget()   # Analyze + Cancel; moved onto the Region or the Peaks page
        box = QHBoxLayout(self._analyze_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.analyze_btn)
        box.addWidget(self.cancel_btn)

        # 1 Setup: run line, the save form (set_save_panel), settings, Next
        setup = QWidget()
        self._setup_lay = QVBoxLayout(setup)
        self._setup_lay.addWidget(self.title)
        self._setup_lay.addWidget(self.settings, stretch=1)
        self.next_region_btn = theme.set_role(QPushButton("Next: Region \u2192"), "primary")
        self.next_region_btn.clicked.connect(lambda: self.go("region"))
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.next_region_btn)
        self._setup_lay.addLayout(row)
        # 2 Region: readout, Back, Next: Peaks / Analyze
        region_page = QWidget()
        lay = QVBoxLayout(region_page)
        self.region_readout = theme.set_role(QLabel(""), "readout")
        lay.addWidget(self.region_readout)
        lay.addStretch(1)
        self._region_row = QHBoxLayout()
        self.region_back_btn = theme.set_role(QPushButton("\u2190 Back"), "quiet")
        self.region_back_btn.clicked.connect(lambda: self.go("setup"))
        self.next_peaks_btn = theme.set_role(QPushButton("Next: Peaks \u2192"), "primary")
        self.next_peaks_btn.clicked.connect(lambda: self.go("peaks"))
        self._region_row.addWidget(self.region_back_btn)
        self._region_row.addStretch(1)
        self._region_row.addWidget(self.next_peaks_btn)
        lay.addLayout(self._region_row)
        # 3 Peaks: hint, Back, Analyze
        peaks_page = QWidget()
        lay = QVBoxLayout(peaks_page)
        hint = QLabel(PEAKS_HINT)
        # one line: a wrapped label under-reports its height, the divider then sized
        # this page too short and pushed Analyze out of view
        hint.setWordWrap(False)
        # ...and it may clip on a narrow window rather than force a sideways scrollbar
        hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        hint.setToolTip(PEAKS_HINT)
        lay.addWidget(hint)
        lay.addStretch(1)
        self._peaks_row = QHBoxLayout()
        self.peaks_back_btn = theme.set_role(QPushButton("\u2190 Region"), "quiet")
        self.peaks_back_btn.clicked.connect(lambda: self.go("region"))
        self._peaks_row.addWidget(self.peaks_back_btn)
        self._peaks_row.addStretch(1)
        lay.addLayout(self._peaks_row)
        # 4 Results: results, the save part (set_save_panel), Back
        results_page = QWidget()
        self._results_lay = QVBoxLayout(results_page)
        self._results_lay.addWidget(self.results_panel, stretch=1)
        self.results_back_btn = theme.set_role(QPushButton("\u2190 Back"), "quiet")
        self.results_back_btn.clicked.connect(lambda: self.go(self._back_from_results()))
        row = QHBoxLayout()
        row.addWidget(self.results_back_btn)
        row.addStretch(1)
        self._results_lay.addLayout(row)
        self._pages = {"setup": setup, "region": region_page, "peaks": peaks_page, "results": results_page}
        for name, _label in STEPS:
            self.stack.addWidget(self._pages[name])
        self._analyze_host = None

        self.analyze_btn.clicked.connect(self._on_analyze)
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.worker.loaded.connect(self._on_loaded)
        self.worker.region_ready.connect(self._on_region_ready)
        self.worker.region_failed.connect(self._on_region_failed)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.settings.changed.connect(self._on_settings_changed)
        self.settings.mode_changed.connect(lambda _m: self._on_settings_changed())
        self.region.sigRegionChanged.connect(self._update_readout)
        self.result_cleared.connect(self._on_result_cleared)
        self._update_readout()
        self.go("setup")
        self._update_controls()

    # ---- steps ----
    def _build_step_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        frame = theme.set_role(QFrame(), "segmented")
        inner = QHBoxLayout(frame)
        inner.setContentsMargins(2, 2, 2, 2)
        inner.setSpacing(2)
        self._step_group = QButtonGroup(self)
        self._step_group.setExclusive(True)
        self.step_buttons = {}
        for name, label in STEPS:
            b = theme.set_role(QPushButton(label), "segment")
            b.setCheckable(True)
            b.clicked.connect(lambda _c=False, n=name: self.go(n))
            self._step_group.addButton(b)
            inner.addWidget(b)
            self.step_buttons[name] = b
        bar.addWidget(frame)
        bar.addStretch(1)
        return bar

    def step(self) -> str:
        return self._step

    def _step_reachable(self, name: str) -> bool:
        loaded = self.run is not None
        return {"setup": True, "region": loaded, "peaks": loaded and self.settings.manual(),
                "results": self._has_results}[name]

    def _peaks_or_region(self) -> str:
        return "peaks" if self.settings.manual() else "region"

    def _back_from_results(self) -> str:
        return self._peaks_or_region()

    def go(self, step: str) -> None:
        """Show a step. An unreachable step is refused (the bar greys it out too)."""
        if step not in self._pages or not self._step_reachable(step):
            return
        self._step = step
        for name, page in self._pages.items():   # the panel is as tall as the page shown, not the tallest page
            pol = page.sizePolicy()
            pol.setVerticalPolicy(QSizePolicy.Preferred if name == step else QSizePolicy.Ignored)
            page.setSizePolicy(pol)
        self.stack.setCurrentWidget(self._pages[step])
        self.step_buttons[step].setChecked(True)
        item = self.plot.getPlotItem()
        self.plot.setVisible(step != "setup")
        if step == "region":
            item.vb.autoRange()
            self._vb2.autoRange()
        elif step == "peaks":
            self._ensure_markers_placed()
        if step in ("peaks", "results"):
            self._zoom_to_region()
        self._update_controls()
        if not self._moved:
            QTimer.singleShot(0, self._size_divider)

    def _place_analyze(self) -> None:
        """Analyze (with Cancel) lives on the Peaks page in Manual mode, else on the Region page."""
        row = self._peaks_row if self.settings.manual() else self._region_row
        if self._analyze_host is row:
            return
        if self._analyze_host is not None:
            self._analyze_host.removeWidget(self._analyze_box)
        row.addWidget(self._analyze_box)
        self._analyze_host = row

    def _zoom_to_region(self) -> None:
        lo, hi = self._region()
        pad = (hi - lo) * ZOOM_MARGIN
        x0, x1 = lo - pad, hi + pad
        item = self.plot.getPlotItem()
        item.setXRange(x0, x1, padding=0)
        # each axis fits what is inside the zoom, so the waves fill the height
        # instead of keeping the whole run's span (a step or a drift elsewhere
        # would leave them flat)
        self._fit_y(item.vb, self.src_curve, x0, x1)
        self._fit_y(self._vb2, self.resp_curve, x0, x1)

    @staticmethod
    def _fit_y(vb, curve, x0: float, x1: float) -> None:
        x, y = curve.getData()
        if x is None or y is None or len(x) == 0:
            return
        x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
        inside = (x >= x0) & (x <= x1) & np.isfinite(y)
        if not inside.any():
            return
        lo, hi = float(y[inside].min()), float(y[inside].max())
        if hi <= lo:
            hi, lo = lo + 1e-12, lo - 1e-12
        vb.setYRange(lo, hi, padding=0.08)

    def _update_readout(self, *_a) -> None:
        lo, hi = self.region.getRegion()
        self.region_readout.setText("Region %.0f \u2013 %.0f s" % (lo, hi))

    def _on_result_cleared(self) -> None:
        if self._step == "results":
            self.go(self._peaks_or_region())

    def _restore_splitter(self) -> bool:
        if self._app_settings is None:
            return False
        try:
            state = self._app_settings.value("analysis/splitter2")
            return bool(state) and self.splitter.restoreState(state)
        except Exception:
            return False

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._moved:
            # no saved divider: the lower half gets what the step's page needs, the plot the rest
            QTimer.singleShot(0, self._size_divider)

    def _size_divider(self) -> None:
        if self._moved or self._step == "setup":
            return
        need = self._pages[self._step].sizeHint().height() + 4
        total = self.splitter.height()
        self.splitter.setSizes([max(total - need, 1), need])

    def _save_splitter(self, *_args) -> None:
        self._moved = True   # the user chose a layout: it is no longer sized to fit the page
        if self._app_settings is not None:
            self._app_settings.setValue("analysis/splitter2", self.splitter.saveState())

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
        # (clicks reach the region and the markers; wheel/drag inside the plot reach the main view box)
        self._vb2 = ResponseViewBox()
        item.scene().addItem(self._vb2)
        item.getAxis("right").linkToView(self._vb2)
        self._vb2.setXLink(item)
        self._yzoom = link_y_zoom(item.vb, self._vb2)
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

    def set_save_panel(self, panel) -> None:
        """Place the save form on Setup and the save part on Results, and feed the panel the
        run and each finished analysis. Without a save panel those places stay empty."""
        self._save_panel = panel
        self._setup_lay.insertWidget(1, panel.form_widget)
        self._results_lay.insertWidget(1, panel.action_widget)
        self.run_loaded.connect(panel.set_run)
        self.result_ready.connect(panel.set_result)
        self.result_cleared.connect(panel.clear_result)
        panel.edit_requested.connect(lambda: self.go("setup"))
        if self.run is not None:
            panel.set_run(self.run)

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
        self.go("setup")
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
        # radii the experiment's details wrote into the run: the first Analyze uses them
        # (r2 <= r1 is left to the usual radii check, which keeps Analyze disabled)
        for key, spin in (("r1_mm", self.settings.r1_spin), ("r2_mm", self.settings.r2_spin)):
            value = run.header.get(key)
            if isinstance(value, (int, float)):
                spin.setValue(float(value))
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
        if self._step in ("setup", "results"):   # show the progress where Analyze lives
            self.go(self._peaks_or_region())
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
        self.go("results")

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
        if self._step == "peaks" and not self.settings.manual():
            self.go("region")   # there is no Peaks step outside Manual
        self._ensure_markers_placed()
        self._update_controls()

    def _update_controls(self) -> None:
        manual = self.settings.manual() and self.run is not None
        self._place_analyze()
        for name, b in self.step_buttons.items():
            b.setEnabled(self._step_reachable(name))
        self.step_buttons["peaks"].setVisible(self.settings.manual())
        self.next_region_btn.setEnabled(self.run is not None)
        self.next_peaks_btn.setVisible(self.settings.manual())
        self.next_peaks_btn.setEnabled(self.run is not None and not self._running)
        peaks_view = self._step in ("peaks", "results")
        for m in self.markers:
            m.setVisible(manual and peaks_view)
        ready = self.run is not None and not self._running and not self._loading and not self.is_snapping() \
            and self.settings.radii_ok()
        self.analyze_btn.setEnabled(ready)
        self.cancel_btn.setVisible(self._running)
        self.region.setMovable(not self._running and not peaks_view)
        for m in self.markers:
            m.setMovable(not self._running and self._step != "results")
        self.settings.setEnabled(not self._running)
