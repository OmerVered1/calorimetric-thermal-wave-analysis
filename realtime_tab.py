"""
Real Time tab
=============
Unified live view of the connected calorimeter (Heat Flow, Sample T, and
External T if present) and any running K2602B sweep (Voltage, Current,
Resistance, Power) in one time-locked plot.

Controls (one row per signal):
    [ show ✓ ] [ Name ]   value + unit   [ Unit ▾ ] [ auto-range ✓ ]

Layout of Y axes as signals are toggled on/off:
    1 visible → left
    2 visible → left + right
    3 visible → left + right + right-outer
    4 visible → left-outer + left + right + right-outer
    5 visible → left-outer + left + right + right-outer + right-farther
    6+ visible → alternate further outward, always keeping visible signals
                 distributed on both sides of the plot area.

Time axis semantics:
    - Default: X = seconds since calorimeter was connected.
    - On experiment (sweep) start: X = seconds since experiment start;
      plot buffers are cleared so the new run starts at t=0.
    - On experiment end: X keeps the experiment-start reference so the
      completed run stays visible; next Connect or next experiment resets.
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

import pyqtgraph as pg

from calorimeter_reader import CalorimeterSignal


def _series_color(name):
    from ctwa import theme
    return theme.series_color(name)
from signal_units import color_for_index, unit_options


# ---- Signal catalog --------------------------------------------------------

# Each signal has a unique key, display name, list of unit options, and color.
# Unit options: (display_label, transform_from_base_fn). The base unit is the
# first entry — any raw sample coming into the tab is assumed to be in that
# unit; the transform converts to whatever the user picked in the dropdown.

def _mul(factor: float):
    return lambda x: x * factor

def _c_to_k(x: float) -> float: return x + 273.15
def _c_to_f(x: float) -> float: return x * 9.0 / 5.0 + 32.0


@dataclass
class SignalSpec:
    key: str
    name: str
    color: str
    units: list[tuple[str, callable]]   # (label, base→display fn)


# The SMU's own signals. Fixed in code because they come from the instrument
# driver, not off the wire — no profile can rename or re-unit them.
KEITHLEY_SPECS: list[SignalSpec] = [
    SignalSpec("v",     "Voltage", _series_color("Voltage"),
               [("V", _mul(1)), ("mV", _mul(1000)), ("µV", _mul(1e6)), ("kV", _mul(1e-3))]),
    SignalSpec("i",     "Current", _series_color("Current"),
               [("A", _mul(1)), ("mA", _mul(1000)), ("µA", _mul(1e6)), ("nA", _mul(1e9))]),
    SignalSpec("r",     "Resistance", _series_color("Resistance"),
               [("Ω", _mul(1)), ("kΩ", _mul(1e-3)), ("MΩ", _mul(1e-6)), ("mΩ", _mul(1000))]),
    SignalSpec("p",     "Power", _series_color("Power"),
               [("W", _mul(1)), ("mW", _mul(1000)), ("µW", _mul(1e6)), ("kW", _mul(1e-3))]),
]

KEITHLEY_KEYS = tuple(s.key for s in KEITHLEY_SPECS)


def specs_from_signals(signals) -> list[SignalSpec]:
    """Turn reader-declared CalorimeterSignals into plot specs.

    Colors come from the palette by position, so the same profile paints the
    same way every session; unit menus come from the unit string, which for an
    unrecognised unit means no conversions rather than a wrong guess.
    """
    return [
        SignalSpec(
            key=sig.key,
            name=sig.label or sig.key,
            color=color_for_index(i),
            units=unit_options(sig.unit),
        )
        for i, sig in enumerate(signals)
    ]


# Shown before any calorimeter connects, and by the direct-connect reader.
# Same keys, colors and units the tab has always had, so the default view is
# unchanged.
DEFAULT_CAL_SPECS: list[SignalSpec] = specs_from_signals([
    CalorimeterSignal("hf", "Heat Flow", "mW"),
    CalorimeterSignal("t", "Sample Temperature", "°C"),
    CalorimeterSignal("ext_t", "External Temperature", "°C"),
])

def _theme():
    from ctwa import theme
    return theme


# Side panel width: fixed range, the plot takes the rest.
CONTROLS_MIN_W, CONTROLS_MAX_W = _theme().scaled(320), _theme().scaled(380)

EMPTY_NOTHING = ("Nothing to plot yet.\n"
                 "Connect a calorimeter or start a sweep, and signals appear here as they arrive.")
EMPTY_HIDDEN = "Every signal with data is hidden. Tick one on the left to plot it."


@dataclass
class Series:
    spec: SignalSpec
    xs: list[float] = field(default_factory=list)
    ys_base: list[float] = field(default_factory=list)   # values in base unit
    curve: pg.PlotDataItem = None
    axis: pg.AxisItem = None
    view_box: pg.ViewBox = None
    available: bool = True    # instrument exposes it
    visible: bool = True      # user has it toggled on
    unit_index: int = 0
    auto_range: bool = True

    def display_ys(self) -> list[float]:
        transform = self.spec.units[self.unit_index][1]
        return [transform(y) for y in self.ys_base]

    def current_unit_label(self) -> str:
        return self.spec.units[self.unit_index][0]


class RealTimeTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._t_ref: float | None = None
        self._t_ref_source: str = "connect"

        # Calorimeter signals are whatever the connected reader declares; the
        # SMU's four are fixed. Both live in one ordered list so axis slots,
        # control rows and CSV columns all follow the same order.
        self._cal_specs: list[SignalSpec] = list(DEFAULT_CAL_SPECS)
        self._specs: list[SignalSpec] = self._cal_specs + KEITHLEY_SPECS
        self._series: dict[str, Series] = {
            spec.key: Series(spec=spec) for spec in self._specs
        }
        # Start with only calorimeter defaults visible (V/I/R/P off) — Keithley
        # signals only make sense during a sweep. Set before the controls are
        # built, so their tick boxes say the same thing; set after, as it
        # was, the boxes showed ticked while those four were never plotted.
        # The app calls set_calorimeter_signals() when a calorimeter connects.
        for key in KEITHLEY_KEYS:
            self._series[key].visible = False

        # Row-widgets we need to refer to later, keyed by signal key
        self._control_rows: dict[str, dict] = {}
        self._status_labels: dict[str, QLabel] = {}
        self._status_layout: QHBoxLayout | None = None
        self._status_widget: QWidget | None = None

        self._setup_ui()

    # ---- Signal set --------------------------------------------------------

    def set_calorimeter_signals(self, signals) -> None:
        """Replace the calorimeter signals with the ones a reader declares.

        Called on connect, before any sample arrives. A no-op when the set is
        unchanged, so reconnecting to the same instrument does not tear the
        plot down and lose the axis arrangement the user set up.
        """
        new_specs = specs_from_signals(signals) if signals else list(DEFAULT_CAL_SPECS)
        same = [(s.key, s.name, [u for u, _ in s.units]) for s in self._cal_specs] == \
               [(s.key, s.name, [u for u, _ in s.units]) for s in new_specs]
        if same:
            for spec in new_specs:
                self._series[spec.key].available = True
            return

        self._teardown_plot_items()

        keithley_series = {k: self._series[k] for k in KEITHLEY_KEYS}
        self._cal_specs = new_specs
        self._specs = self._cal_specs + KEITHLEY_SPECS
        self._series = {spec.key: Series(spec=spec) for spec in self._cal_specs}
        self._series.update(keithley_series)

        self._populate_controls()
        self._populate_status_labels()
        self._build_plot_items()
        self._rebuild_axes()

    def _teardown_plot_items(self) -> None:
        """Detach the current curves, ViewBoxes and axes from the plot.

        Everything added in _build_plot_items has to come back off, or the
        scene keeps painting orphaned curves from the previous profile.
        """
        plot_item = self._plot.plotItem
        for s in self._series.values():
            if s.axis is not None:
                try:
                    plot_item.layout.removeItem(s.axis)
                except Exception:
                    pass
                s.axis.hide()
                s.axis.unlinkFromView()
            if s.view_box is not None:
                if s.curve is not None:
                    s.view_box.removeItem(s.curve)
                try:
                    plot_item.scene().removeItem(s.view_box)
                except Exception:
                    pass
            s.curve = None
            s.axis = None
            s.view_box = None

    # ---- UI construction ---------------------------------------------------

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # Controls on the left at a fixed width range, plot on the right
        # taking the rest. Neither collapses: a desktop layout, not a page.
        splitter = QSplitter(Qt.Horizontal)
        controls = self._build_controls_panel()
        controls.setMinimumWidth(CONTROLS_MIN_W)
        controls.setMaximumWidth(CONTROLS_MAX_W)
        splitter.addWidget(controls)
        splitter.addWidget(self._build_plot_area())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([CONTROLS_MIN_W + 20, 900])
        outer.addWidget(splitter, stretch=1)

        outer.addLayout(self._build_action_row())

    def _build_controls_panel(self) -> QGroupBox:
        group = QGroupBox("Signals")
        grid = QGridLayout(group)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(5)
        self._controls_grid = grid
        self._populate_controls()
        return group

    def _populate_controls(self) -> None:
        """(Re)build one control row per signal in the current signal set."""
        grid = self._controls_grid
        while grid.count():
            item = grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._control_rows = {}

        theme = _theme()
        # Header row
        headers = ["", "", "Signal", "Unit", "Auto-scale"]
        for col, text in enumerate(headers):
            grid.addWidget(theme.set_role(QLabel(text), "faint"), 0, col)

        row = 1
        for spec in self._specs:
            s = self._series[spec.key]

            show_cb = QCheckBox()
            show_cb.setChecked(s.visible)
            show_cb.toggled.connect(
                lambda checked, k=spec.key: self._on_show_toggled(k, checked)
            )
            show_cb.setToolTip(f"Plot {spec.name}")
            grid.addWidget(show_cb, row, 0)

            dot = theme.swatch(spec.color)
            grid.addWidget(dot, row, 1)

            name_lbl = QLabel(spec.name)
            grid.addWidget(name_lbl, row, 2)

            unit_combo = QComboBox()
            for unit_label, _ in spec.units:
                unit_combo.addItem(unit_label)
            unit_combo.setCurrentIndex(min(s.unit_index, len(spec.units) - 1))
            unit_combo.currentIndexChanged.connect(
                lambda idx, k=spec.key: self._on_unit_changed(k, idx)
            )
            grid.addWidget(unit_combo, row, 3)

            auto_cb = QCheckBox()
            auto_cb.setToolTip(f"Rescale the {spec.name} axis to fit its data")
            auto_cb.setChecked(True)
            auto_cb.toggled.connect(
                lambda checked, k=spec.key: self._on_auto_range_toggled(k, checked)
            )
            grid.addWidget(auto_cb, row, 4, alignment=Qt.AlignHCenter)

            self._control_rows[spec.key] = {
                "show": show_cb,
                "dot": dot,
                "name": name_lbl,
                "unit": unit_combo,
                "auto": auto_cb,
            }
            row += 1

        grid.setColumnStretch(2, 1)
        grid.setRowStretch(row, 1)

    def create_status_values_widget(self) -> QWidget:
        """Compact per-signal value strip meant to sit in the app status bar.

        Text (signal name) is black; the numeric value + unit are colored.
        Only signals currently `available` are shown. The widget itself is
        created once and handed to the status bar; changing the signal set
        repopulates it in place rather than replacing it.
        """
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        # Hold the widget, not just its layout: the caller reparents it into
        # the status bar, but if it ever does not, Python would collect the
        # QWidget and take the layout we repopulate through with it.
        self._status_widget = w
        self._status_layout = layout
        self._populate_status_labels()
        return w

    def _populate_status_labels(self) -> None:
        layout = self._status_layout
        if layout is None:
            return
        try:
            layout.count()
        except RuntimeError:
            # Host destroyed the strip; nothing to repopulate.
            self._status_layout = None
            self._status_labels = {}
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._status_labels = {}
        for spec in self._specs:
            lbl = QLabel()
            lbl.setTextFormat(Qt.RichText)
            layout.addWidget(lbl)
            self._status_labels[spec.key] = lbl
            lbl.setVisible(self._series[spec.key].available)

    def _build_plot_area(self) -> QWidget:
        """The plot, with a message laid over it while there is nothing to show."""
        area = QWidget()
        grid = QGridLayout(area)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.addWidget(self._build_plot(), 0, 0)
        self._empty_label = _theme().set_role(QLabel(EMPTY_NOTHING), "muted")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._empty_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        grid.addWidget(self._empty_label, 0, 0, alignment=Qt.AlignCenter)
        self._update_empty_state()
        return area

    def _build_plot(self) -> pg.PlotWidget:
        self._plot = pg.PlotWidget()
        from ctwa import theme
        theme.style_plot(self._plot)
        plot_item = self._plot.plotItem
        plot_item.setLabel("bottom", "Time since connect (s)")

        # Hide both built-in Y axes; _rebuild_axes decides which to show and
        # what stacked right-axes to add.
        plot_item.hideAxis("left")
        plot_item.hideAxis("right")

        # One ViewBox per signal. The one signal that occupies the "left"
        # slot at any time uses the plot's own vb (linked to the built-in
        # left axis when shown). All other signals get their own extra
        # ViewBox + AxisItem stacked on the right.
        self._build_plot_items()

        # Keep aux ViewBoxes' geometry synced with the main plot area
        plot_item.vb.sigResized.connect(self._sync_viewboxes)
        # Manual pan/zoom on X disables Follow so the user can navigate
        # earlier data without the plot snapping back on the next sample.
        plot_item.vb.sigRangeChangedManually.connect(self._on_manual_range_change)

        self._rebuild_axes()
        return self._plot

    def _build_plot_items(self) -> None:
        """Create one ViewBox + curve + right-hand axis per signal.

        The signal that occupies the "left" slot at any time uses the plot's
        own vb; every other signal gets its own ViewBox stacked on the right.
        """
        plot_item = self._plot.plotItem
        for spec in self._specs:
            s = self._series[spec.key]
            s.view_box = pg.ViewBox()
            s.view_box.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
            plot_item.scene().addItem(s.view_box)
            s.view_box.setXLink(plot_item.vb)
            from ctwa import theme
            s.curve = pg.PlotDataItem(pen=theme.pen(spec.color, 1.4))
            # Real Time runs for hours; without these every sample redraws them all.
            theme.fast_curve(s.curve)
            s.view_box.addItem(s.curve)
            if s.ys_base:
                s.curve.setData(s.xs, s.display_ys())
            # Right-side axis for this signal, created once, reused.
            # Axis line = black, tick numbers = colored, label = mixed
            # (name black + unit colored) via HTML in setLabel.
            s.axis = pg.AxisItem("right")
            theme.style_axis(s.axis)
            s.axis.setLabel(_axis_label_html(spec.name, s.current_unit_label(), spec.color))
            s.axis.setTextPen(spec.color)
            s.axis.linkToView(s.view_box)

    def _on_manual_range_change(self, _mask=None) -> None:
        if getattr(self, "follow_cb", None) is not None and self.follow_cb.isChecked():
            self.follow_cb.setChecked(False)

    def _build_action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()

        self.follow_cb = QCheckBox("Follow")
        self.follow_cb.setChecked(True)
        self.follow_cb.setToolTip(
            "Auto-scroll X so the latest sample stays at the right edge.\n"
            "Preserves the current X window width; disables when you pan/zoom X."
        )
        row.addWidget(self.follow_cb)

        self.reset_btn = QPushButton("Reset view")
        self.reset_btn.setToolTip(
            "Re-enable auto-range on X and every visible signal's Y axis.\n"
            "Use when scrolling or zooming has left the plot in a weird state."
        )
        self.reset_btn.clicked.connect(self._on_reset_view)
        row.addWidget(self.reset_btn)

        row.addStretch()

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self._on_clear)
        row.addWidget(self.clear_btn)
        self.save_btn = QPushButton("Save CSV…")
        self.save_btn.clicked.connect(self._on_save_csv)
        row.addWidget(self.save_btn)
        return row

    def _on_reset_view(self) -> None:
        primary = self._plot.plotItem.vb
        primary.enableAutoRange(axis=pg.ViewBox.XAxis, enable=True)
        for s in self._series.values():
            if s.view_box is not None and s.available and s.visible:
                s.view_box.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
                # Also re-sync the per-signal auto-range checkbox
                row = self._control_rows.get(s.spec.key)
                if row is not None:
                    row["auto"].setChecked(True)

    # ---- Axis layout -------------------------------------------------------

    def _rebuild_axes(self) -> None:
        """Assign visible signals to axis slots.

        Rule: at most one axis on the left (the plot's built-in left axis,
        linked to the first-visible signal's ViewBox). All other visible
        signals get their own AxisItem stacked outward on the right, in
        signal-set order. Matches Omer's stated examples:
            n=1  → left
            n=2  → left + right
            n=3  → left + 2 right (innermost + outer)
            n=4+ → left + more right
        """
        plot_item = self._plot.plotItem
        layout = plot_item.layout

        # Detach all right-side axes from the layout
        for s in self._series.values():
            try:
                layout.removeItem(s.axis)
            except Exception:
                pass
            s.axis.hide()

        # An axis only for a signal that is shown *and* has data: empty axes
        # for signals that have not reported yet cost a fifth of the plot width.
        visible = [self._series[spec.key] for spec in self._specs
                   if self._series[spec.key].available and self._series[spec.key].visible
                   and self._series[spec.key].xs]

        self._update_empty_state()
        left_axis = plot_item.getAxis("left")
        if not visible:
            plot_item.hideAxis("left")
            layout.invalidate()
            self._sync_viewboxes()
            return

        # First visible signal owns the built-in left axis. Axis line black,
        # tick numbers in the signal's color, label uses HTML so the signal
        # name is black and the unit is colored.
        first = visible[0]
        left_axis.linkToView(first.view_box)
        left_axis.setLabel(_axis_label_html(first.spec.name, first.current_unit_label(), first.spec.color))
        _theme().style_axis(left_axis)
        left_axis.setTextPen(first.spec.color)
        plot_item.showAxis("left")

        # Remaining visible signals: right-side stacked axes (innermost first)
        for i, s in enumerate(visible[1:]):
            s.axis.setLabel(_axis_label_html(s.spec.name, s.current_unit_label(), s.spec.color))
            layout.addItem(s.axis, 2, 2 + i)
            s.axis.show()

        layout.invalidate()
        self._sync_viewboxes()

    def _update_empty_state(self) -> None:
        label = getattr(self, "_empty_label", None)
        if label is None:
            return
        has_data = [s for s in self._series.values() if s.available and s.xs]
        shown = [s for s in has_data if s.visible]
        if shown:
            label.hide()
        else:
            label.setText(EMPTY_HIDDEN if has_data else EMPTY_NOTHING)
            label.show()

    def _sync_viewboxes(self) -> None:
        primary = self._plot.plotItem.vb
        rect = primary.sceneBoundingRect()
        for s in self._series.values():
            if s.view_box is not None and s.view_box is not primary:
                s.view_box.setGeometry(rect)
                s.view_box.linkedViewChanged(primary, s.view_box.XAxis)

    # ---- Signal control handlers ------------------------------------------

    def _on_show_toggled(self, key: str, checked: bool) -> None:
        s = self._series[key]
        s.visible = checked
        if s.curve is not None:
            if checked:
                s.curve.setData(s.xs, s.display_ys())
            else:
                s.curve.setData([], [])
        self._rebuild_axes()

    def _on_unit_changed(self, key: str, idx: int) -> None:
        s = self._series[key]
        s.unit_index = idx
        # Redraw any axis showing this signal (its own right-axis or the
        # built-in left-axis if it's the first-visible).
        new_label = _axis_label_html(s.spec.name, s.current_unit_label(), s.spec.color)
        if s.axis is not None:
            s.axis.setLabel(new_label)
        left_axis = self._plot.plotItem.getAxis("left")
        visible = [self._series[spec.key] for spec in self._specs
                   if self._series[spec.key].available and self._series[spec.key].visible
                   and self._series[spec.key].xs]
        if visible and visible[0] is s:
            left_axis.setLabel(new_label)
        if s.curve is not None and s.visible:
            s.curve.setData(s.xs, s.display_ys())
        if s.ys_base:
            self._update_value_label(s)

    def _on_auto_range_toggled(self, key: str, checked: bool) -> None:
        s = self._series[key]
        s.auto_range = checked
        if s.view_box is not None:
            s.view_box.enableAutoRange(axis=pg.ViewBox.YAxis, enable=checked)

    # ---- Public API called by Keithley2602BApp -----------------------------

    def set_available_signals(self, keys: list[str]) -> None:
        """Hide control rows for signals not exposed by the current
        instrument. `keys` is a list of signal keys ("hf", "t", "ext_t", …).
        Signals not in `keys` become both `available=False` and hidden in
        the control panel + status-bar strip; they cannot be toggled on.
        """
        available_set = set(keys)
        for spec in self._specs:
            s = self._series[spec.key]
            avail = spec.key in available_set
            s.available = avail
            row = self._control_rows.get(spec.key)
            if row is not None:
                for w in (row["show"], row["dot"], row["name"], row["unit"], row["auto"]):
                    w.setVisible(avail)
            labels = getattr(self, "_status_labels", None)
            if labels is not None and spec.key in labels:
                labels[spec.key].setVisible(avail)
            if not avail:
                s.visible = False
        self._rebuild_axes()

    def set_reference_now(self, source: str) -> None:
        """Reset the X-axis reference to now. `source` in {"connect", "experiment"}."""
        self._t_ref = time.time()
        self._t_ref_source = source
        label = "connect" if source == "connect" else "experiment"
        self._plot.plotItem.setLabel("bottom", f"Time since {label} (s)")
        for s in self._series.values():
            s.xs.clear()
            s.ys_base.clear()
            if s.curve is not None:
                s.curve.setData([], [])
            # Clear the status-bar readout too. _update_value_label bails on an
            # empty series, so a value left here would sit there looking live
            # while the plot is empty — which is exactly how a silently-failing
            # sniff session managed to look like a working one.
            lbl = self._status_labels.get(s.spec.key)
            if lbl is not None:
                lbl.setText("")
        self._rebuild_axes()

    def clear_status_values(self, keys) -> None:
        """Blank the status-bar values for these signals, leaving the plot.

        Used when the source meter changes: its last sweep stays on the plot,
        but a value in the status bar reads as current, and it no longer is.
        """
        for key in keys:
            lbl = self._status_labels.get(key)
            if lbl is not None:
                lbl.setText("")

    def push_calorimeter_sample(self, wall_ts: float, readings: dict) -> None:
        """`readings` is keyed by whatever the connected reader declares —
        the built-in "hf"/"t"/"ext_t" for a direct connection, or the profile's
        own signal names when sniffing. Keys the tab does not know about are
        dropped rather than plotted against the wrong axis."""
        for spec in self._cal_specs:
            if spec.key in readings:
                self._append(spec.key, wall_ts, float(readings[spec.key]))

    def push_keithley_sample(self, wall_ts: float, v, i, r, p) -> None:
        for key, value in (("v", v), ("i", i), ("r", r), ("p", p)):
            if value is None:
                continue
            self._append(key, wall_ts, float(value))

    def _append(self, key: str, wall_ts: float, value_base: float) -> None:
        s = self._series.get(key)
        if s is None or not s.available:
            return
        if self._t_ref is None:
            self._t_ref = wall_ts
            self._t_ref_source = "connect"
            self._plot.plotItem.setLabel("bottom", "Time since connect (s)")
        rel_t = wall_ts - self._t_ref
        s.xs.append(rel_t)
        s.ys_base.append(value_base)
        if len(s.xs) == 1:
            self._rebuild_axes()   # its first sample: it gets an axis now
        if s.visible and s.curve is not None:
            s.curve.setData(s.xs, s.display_ys())
        self._update_value_label(s)
        # Follow mode: X ranges from 0 to the latest sample time — t=0 pinned
        # to the left, right edge auto-expands as new data arrives.
        if getattr(self, "follow_cb", None) is not None and self.follow_cb.isChecked():
            max_t = max(
                (series.xs[-1] for series in self._series.values() if series.xs),
                default=rel_t,
            )
            if max_t <= 0:
                max_t = 0.01
            self._plot.plotItem.vb.setXRange(0.0, max_t, padding=0.02)

    def _update_value_label(self, s: Series) -> None:
        if not s.ys_base:
            return
        labels = getattr(self, "_status_labels", None)
        if labels is None:
            return
        lbl = labels.get(s.spec.key)
        if lbl is None:
            return
        transform = s.spec.units[s.unit_index][1]
        display_val = transform(s.ys_base[-1])
        # 9 significant digits preserves the full float32 wire precision
        # without cluttering the display with FP-noise trailing digits.
        val_str = f"{display_val:.9g}"
        unit = s.current_unit_label()
        theme = _theme()
        lbl.setText(
            f"<span style='color:{s.spec.color};'>\u25cf</span> "
            f"<span style='color:{theme.P.text_muted};'>{s.spec.name}</span> "
            f"<span style='color:{theme.P.text};font-family:\"{theme.fonts()[1]}\";'>{val_str} {unit}</span>"
        )

    # ---- Actions -----------------------------------------------------------

    def _on_clear(self) -> None:
        for s in self._series.values():
            s.xs.clear()
            s.ys_base.clear()
            if s.curve is not None:
                s.curve.setData([], [])
            labels = getattr(self, "_status_labels", None)
            if labels is not None and s.spec.key in labels:
                labels[s.spec.key].setText("")
        self._rebuild_axes()

    def _on_save_csv(self) -> None:
        n = sum(len(s.xs) for s in self._series.values() if s.available)
        if n == 0:
            QMessageBox.information(self, "Nothing to save", "No samples recorded yet.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Real-Time log as CSV", "realtime_log.csv", "CSV files (*.csv)"
        )
        if not path:
            return

        timeline: dict[float, dict[str, float]] = {}
        for s in self._series.values():
            if not s.available:
                continue
            for x, y in zip(s.xs, s.ys_base):
                timeline.setdefault(x, {})[s.spec.key] = y

        try:
            with open(path, "w", newline="", encoding="cp1252", errors="replace") as f:
                w = csv.writer(f)
                header = ["time_s"]
                cols: list[Series] = [s for s in self._series.values() if s.available]
                for s in cols:
                    # Base unit for the CSV (unambiguous, unit-agnostic)
                    base_unit = s.spec.units[0][0]
                    header.append(f"{s.spec.name} ({base_unit})")
                w.writerow(header)
                for t_rel in sorted(timeline.keys()):
                    row_vals = [t_rel]
                    for s in cols:
                        row_vals.append(timeline[t_rel].get(s.spec.key, ""))
                    w.writerow(row_vals)
        except OSError as e:
            QMessageBox.warning(self, "Save failed", str(e))
            return
        QMessageBox.information(
            self, "Saved", f"Wrote {len(timeline)} rows to\n{path}"
        )


def _axis_label_html(name: str, unit: str, color: str) -> str:
    """Axis label with the signal name muted and the unit in the signal's
    color. pyqtgraph AxisItem.setLabel accepts HTML."""
    return (
        f"<span style='color:{_theme().P.text_muted};'>{name} </span>"
        f"<span style='color:{color};'>({unit})</span>"
    )


