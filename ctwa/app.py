"""
Calorimetric Thermal Wave Analysis Program — main window.

One window for every supported Keithley SMU. The model is chosen when you
connect; everything model-specific — channels, ranges, optional hardware such as
guard mode or a front/rear terminal switch — comes from the model's declared
capabilities (ctwa/instruments/registry.py), never from branching on its name.

This window began as the 2602B window, the most complete of the four original
per-instrument apps (it alone had the calorimeter, Real Time and setup work).
The 2450, 6430 and 2611A windows it replaces differed from it mainly by being
older; the instrument-specific parts of them now live in the drivers and the
capability table instead.
"""

import sys
import os
import time
import threading
import csv
import json
import copy
import numpy as np
from typing import Optional, List, Dict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QTabWidget, QGroupBox, QLabel, QPushButton,
    QComboBox, QLineEdit, QCheckBox, QSpinBox, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QSplitter,
    QFrame, QMessageBox, QFileDialog, QDialog, QListWidget,
    QProgressBar, QStatusBar, QTextEdit, QSizePolicy, QMenuBar,
    QMenu, QFormLayout, QScrollArea, QAbstractSpinBox,
    QInputDialog, QToolButton
)
from PySide6.QtCore import Qt, QTimer, Signal, QThread, QSettings
from PySide6.QtGui import QFont, QColor, QPalette, QIcon, QKeySequence, QAction, QShortcut

import pyqtgraph as pg

from ctwa import theme
from ctwa.connect_panel import ChoiceCard, SMUConnectPanel
from ctwa.instruments import registry
from ctwa.instruments.smu import SMU, NotSupported

from calorimeter_reader import (
    CALORIMETERS, CalorimeterReader, discover_calorimeter_ip, probe_port_free,
    SniffingCalorimeterReader, sniff_available, sniff_capture_readiness, sniff_interface_for,
    sniff_list_interfaces,
)
from calorimeter_setups import SetupStore
from calorimeter_wizard import CalorimeterSetupDialog

theme.configure_pyqtgraph()

# Version info
from _version import __version__, __author__, __app_name__
__organization__ = "Omer Vered MSc Research"
__copyright__ = "Copyright 2026 Omer Vered"


def apply_source_limits(value_box, compliance_box, function: str, reset_compliance: bool):
    """Range the source value / compliance fields for the connected model."""
    vmin, vmax, vdec, cmin, cmax, cdec = registry.active().source_limits(function)
    if value_box is not None:
        value_box.setDecimals(vdec)
        value_box.setRange(vmin, vmax)
        value_box.setSuffix(" V" if function == "Voltage" else " A")
    compliance_box.setDecimals(cdec)
    compliance_box.setRange(cmin, cmax)
    compliance_box.setSuffix(" A" if function == "Voltage" else " V")
    if reset_compliance:
        caps = registry.active()
        default = (caps.default_current_compliance if function == "Voltage"
                   else caps.default_voltage_compliance)
        compliance_box.setValue(min(max(default, cmin), cmax))


def source_range_labels(function: str):
    caps = registry.active()
    opts = caps.voltage_ranges if function == "Voltage" else caps.current_ranges
    return ["Auto"] + [o.label for o in opts]


@dataclass

class MeasurementPoint:
    """Single measurement data point"""
    index: int
    timestamp: float
    source_value: float
    channel: str = "a"
    computer_time: str = ""
    voltage: Optional[float] = None
    current: Optional[float] = None
    resistance: Optional[float] = None
    power: Optional[float] = None
    # Latest calorimeter reading at the moment this sweep sample was taken —
    # populated by _run_sweep only when a calorimeter is connected. Keys are
    # the calorimeter channel names ("hf", "t", "ext_t"); values are the
    # float32 samples in their base units. Empty dict when no calorimeter.
    cal_readings: dict = field(default_factory=dict)


# Column layout shared by the live-streaming CSV write and the batch
# _write_csv path so both files have identical header/row shape.

_CAL_COLUMN_LABELS = {"hf": "HF(mW)", "t": "T(C)", "ext_t": "ExtT(C)"}

# Filled in on connect from the reader's declared signals, so a column derived
# from a user-edited profile is still labelled with its name and unit rather
# than a bare dictionary key. Cleared on disconnect.
_CAL_COLUMN_LABELS_DYNAMIC: dict = {}


def set_cal_column_labels(signals) -> None:
    """Label the calorimeter CSV columns from what the reader says it emits."""
    _CAL_COLUMN_LABELS_DYNAMIC.clear()
    for sig in signals or ():
        _CAL_COLUMN_LABELS_DYNAMIC[sig.key] = (
            f"{sig.label}({sig.unit})" if sig.unit else sig.label
        )


def _cal_column_label(key: str) -> str:
    if key in _CAL_COLUMN_LABELS_DYNAMIC:
        return _CAL_COLUMN_LABELS_DYNAMIC[key]
    return _CAL_COLUMN_LABELS.get(key, key)


def _sweep_csv_header(cal_channels) -> list:
    header = ['Index', 'Channel', 'Computer_Time', 'Elapsed(s)',
              'Voltage(V)', 'Current(A)', 'Resistance(Ohm)', 'Power(mW)']
    for key in cal_channels:
        header.append(_cal_column_label(key))
    return header


def _sweep_csv_row(point, cal_channels) -> list:
    row = [
        point.index,
        point.channel.upper(),
        point.computer_time,
        f"{point.timestamp:.6f}",
        f"{point.voltage:.9e}" if point.voltage else "",
        f"{point.current:.9e}" if point.current else "",
        f"{point.resistance:.9e}" if point.resistance else "",
        f"{point.power*1000:.9e}" if point.power else "",
    ]
    for key in cal_channels:
        v = point.cal_readings.get(key) if point.cal_readings else None
        row.append(f"{v:.6g}" if v is not None else "")
    return row


# === Experiments ===

EXPERIMENTS_FILE = os.path.join(os.path.expanduser("~"), "Documents",
                                "K2602B_Experiments", "experiments.json")


class ExperimentStore:
    """JSON-backed store of named experiments (settings + sweep list + wave config + notes)."""

    def __init__(self, path: str = EXPERIMENTS_FILE):
        self.path = path
        self._experiments: Dict[str, dict] = {}
        self.load()

    def load(self):
        self._experiments = {}
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r") as f:
                data = json.load(f)
            for exp in data.get("experiments", []):
                name = exp.get("name")
                if name:
                    self._experiments[name] = exp
        except Exception as e:
            print(f"ExperimentStore load error: {e}")

    def _persist(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump({"experiments": list(self._experiments.values())}, f, indent=2)

    def names(self) -> List[str]:
        return sorted(self._experiments.keys(), key=str.lower)

    def get(self, name: str) -> Optional[dict]:
        return self._experiments.get(name)

    def save(self, name: str, payload: dict):
        now = datetime.now().isoformat(timespec="seconds")
        existing = self._experiments.get(name, {})
        record = dict(payload)
        record["name"] = name
        record["created_at"] = existing.get("created_at", now)
        record["modified_at"] = now
        self._experiments[name] = record
        self._persist()

    def delete(self, name: str):
        if name in self._experiments:
            del self._experiments[name]
            self._persist()

    def rename(self, old: str, new: str):
        if old not in self._experiments or new == old:
            return
        record = self._experiments.pop(old)
        record["name"] = new
        record["modified_at"] = datetime.now().isoformat(timespec="seconds")
        self._experiments[new] = record
        self._persist()


class ToggleButton(QPushButton):
    """A chip that shows which of a small set of choices is active.

    Selection is expressed through Qt's own checked state, which the theme
    styles; the old version swapped whole inline stylesheets on every change.
    """

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)
        theme.set_role(self, "segment")
        self._selected = False
        # Checked state follows set_selected, not the click itself; otherwise a
        # second click on the active choice would visibly deselect it.
        self.clicked.connect(lambda: self.setChecked(self._selected))

    def set_selected(self, selected: bool):
        self._selected = bool(selected)
        self.setChecked(self._selected)

    def is_selected(self) -> bool:
        return self._selected


class DigitalDisplay(QLabel):
    """Large digital display for multimeter readings"""

    EMPTY = "\u2014"

    def __init__(self, unit: str = "", decimals: int = 6):
        super().__init__(self.EMPTY)
        self.unit = unit
        self.decimals = decimals
        theme.set_role(self, "readout")
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def set_value(self, value: float):
        if value is None:
            self.setText(self.EMPTY)
            return

        abs_val = abs(value)
        if abs_val >= 1e6:
            text = f"{value/1e6:.{self.decimals}f} M{self.unit}"
        elif abs_val >= 1e3:
            text = f"{value/1e3:.{self.decimals}f} k{self.unit}"
        elif abs_val >= 1:
            text = f"{value:.{self.decimals}f} {self.unit}"
        elif abs_val >= 1e-3:
            text = f"{value*1e3:.{self.decimals}f} m{self.unit}"
        elif abs_val >= 1e-6:
            text = f"{value*1e6:.{self.decimals}f} \u00b5{self.unit}"
        elif abs_val >= 1e-9:
            text = f"{value*1e9:.{self.decimals}f} n{self.unit}"
        elif abs_val >= 1e-12:
            text = f"{value*1e12:.{self.decimals}f} p{self.unit}"
        elif abs_val >= 1e-15:
            text = f"{value*1e15:.{self.decimals}f} f{self.unit}"
        elif abs_val == 0:
            text = f"0.{'0'*self.decimals} {self.unit}"
        else:
            text = f"{value:.{self.decimals}e} {self.unit}"
        self.setText(text)


class ReadoutCard(QFrame):
    """One multimeter quantity: a coloured dot tying it to its trace, the name,
    and the value. Digits stay near-black — coloured digits read less crisply."""

    def __init__(self, title: str, color: str, display: DigitalDisplay, parent=None):
        super().__init__(parent)
        theme.set_role(self, "readout-card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 6)
        lay.setSpacing(0)
        head = QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(theme.swatch(color))
        head.addWidget(theme.set_role(QLabel(title), "readout-label"))
        head.addStretch()
        lay.addLayout(head)
        lay.addWidget(display)


class LiveReader(QThread):
    """Reads the instrument for the live multimeter, off the UI thread.

    The original windows read inside a QTimer slot, i.e. on the UI thread, so the
    whole window froze for the length of every reading. Over USB that is a
    stutter; on the 6430's 9600-baud serial link it is most of each cycle. The
    readings, their order and their rate are unchanged — only where they wait.
    """

    reading = Signal(object, object)   # voltage, current (either may be None)
    failed = Signal(str)

    def __init__(self, smu, channel: str, measure: str, period_ms: int):
        super().__init__()
        self._smu = smu
        self._channel = channel
        self._measure = measure
        self._period = period_ms / 1000.0
        self._stop = threading.Event()

    def set_period_ms(self, period_ms: int):
        self._period = period_ms / 1000.0

    def set_measure(self, measure: str):
        self._measure = measure

    def set_channel(self, channel: str):
        self._channel = channel

    def stop(self):
        self._stop.set()

    def run(self):
        # First reading one period after start, as the timer did.
        next_at = time.monotonic() + self._period
        while not self._stop.wait(max(0.0, next_at - time.monotonic())):
            next_at += self._period
            try:
                voltage = current = None
                if self._measure in ("Voltage", "Resistance", "All"):
                    voltage = self._smu.measure_voltage(self._channel)
                if self._measure in ("Current", "Resistance", "All"):
                    current = self._smu.measure_current(self._channel)
            except Exception as exc:
                self.failed.emit(str(exc))
                continue
            if self._stop.is_set():
                return
            self.reading.emit(voltage, current)
            # If a reading took longer than the period, carry on from now rather
            # than firing a burst to catch up.
            if next_at < time.monotonic():
                next_at = time.monotonic()



class MultimeterPanel(QWidget):
    """Live multimeter mode panel with channel support"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.app = parent
        self.running = False
        self.recording = False
        self._reader: Optional[LiveReader] = None
        self.reading_count = 0
        self.record_start_time = None
        self.recorded_data = []
        self.last_resistance: Optional[float] = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        def field(row, label, widget, gap=True):
            if gap and row.count():
                row.addSpacing(10)
            row.addWidget(theme.set_role(QLabel(label), "muted"))
            row.addWidget(widget)

        # Source: what to measure, what to apply, and the ranges
        settings = QHBoxLayout()
        settings.setSpacing(6)

        self.measure_type = QComboBox()
        self.measure_type.currentTextChanged.connect(
            lambda m: self._reader.set_measure(m) if self._reader else None)
        self.measure_type.addItems(["Voltage", "Current", "Resistance", "All"])
        self.measure_type.setCurrentText("All")
        field(settings, "Measure", self.measure_type)

        self.source_type = QComboBox()
        self.source_type.addItems(["Voltage", "Current"])
        self.source_type.currentTextChanged.connect(self._update_source_units)
        field(settings, "Source", self.source_type)

        self.source_value = QDoubleSpinBox()
        self.source_value.setValue(0)
        self.source_value.setMinimumWidth(96)
        field(settings, "Value", self.source_value)

        self.compliance = QDoubleSpinBox()
        self.compliance.setMinimumWidth(96)
        apply_source_limits(self.source_value, self.compliance, "Voltage", reset_compliance=True)
        field(settings, "Limit", self.compliance)

        self.voltage_range = QComboBox()
        field(settings, "V range", self.voltage_range)

        self.current_range = QComboBox()
        # Filled from the connected model's capability table; see set_capabilities.
        self.set_capabilities(registry.get(registry.MODEL_ORDER[0]))
        field(settings, "I range", self.current_range)

        settings.addStretch()
        layout.addLayout(settings)

        # Wiring, then how fast, then run
        inst_row = QHBoxLayout()
        inst_row.setSpacing(6)

        # Terminals (2450 only). The multimeter keeps its own choice, separate
        # from Instrument Settings, exactly as the 2450 window did.
        self.terminal_box = QWidget()
        term = QHBoxLayout(self.terminal_box)
        term.setContentsMargins(0, 0, 10, 0)
        term.setSpacing(6)
        term.addWidget(theme.set_role(QLabel("Terminals"), "muted"))
        self.front_btn = ToggleButton("Front")
        self.front_btn.clicked.connect(lambda: self._set_terminal("Front"))
        self.rear_btn = ToggleButton("Rear")
        self.rear_btn.clicked.connect(lambda: self._set_terminal("Rear"))
        term.addWidget(theme.segmented(self.front_btn, self.rear_btn))
        inst_row.addWidget(self.terminal_box)
        self._set_terminal("Rear")
        self.terminal_box.setVisible(registry.active().terminal_select)

        inst_row.addWidget(theme.set_role(QLabel("Sense"), "muted"))
        self.sense_2w = ToggleButton("2-wire")
        self.sense_2w.set_selected(True)
        self.sense_2w.clicked.connect(lambda: self._set_sense("2-Wire"))
        self.sense_4w = ToggleButton("4-wire")
        self.sense_4w.clicked.connect(lambda: self._set_sense("4-Wire"))
        inst_row.addWidget(theme.segmented(self.sense_2w, self.sense_4w))
        self.sense = "2-Wire"

        inst_row.addStretch()

        inst_row.addWidget(theme.set_role(QLabel("Rate"), "muted"))
        self.update_rate = QComboBox()
        self.update_rate.addItems(["Slow (1 Hz)", "Medium (5 Hz)", "Fast (10 Hz)", "Max (20 Hz)"])
        self.update_rate.setCurrentIndex(1)
        self.update_rate.currentIndexChanged.connect(self._update_rate_changed)
        inst_row.addWidget(self.update_rate)

        self.readings_label = theme.set_role(QLabel("0 readings"), "muted")
        self.readings_label.setMinimumWidth(84)
        self.readings_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        inst_row.addWidget(self.readings_label)
        inst_row.addSpacing(4)

        # One button that is Start while idle and Stop while running: a pair
        # always had one of them greyed out, which read as broken.
        self.run_btn = QPushButton()
        self.run_btn.setMinimumWidth(72)
        self.run_btn.clicked.connect(lambda: self.stop_live() if self.running else self.start_live())
        inst_row.addWidget(self.run_btn)
        self._show_running(False)

        layout.addLayout(inst_row)

        # Readouts, one row
        displays = QHBoxLayout()
        displays.setSpacing(8)
        self.voltage_display = DigitalDisplay("V", 6)
        self.current_display = DigitalDisplay("A", 6)
        self.resistance_display = DigitalDisplay("\u03a9", 4)
        self.power_display = DigitalDisplay("W", 6)
        for title, name, display in (("Voltage", "Voltage", self.voltage_display),
                                     ("Current", "Current", self.current_display),
                                     ("Resistance", "Resistance", self.resistance_display),
                                     ("Power", "Power", self.power_display)):
            displays.addWidget(ReadoutCard(title, theme.series_color(name), display), stretch=1)
        layout.addLayout(displays)

        # Recording
        record_layout = QHBoxLayout()
        record_layout.setSpacing(6)
        record_layout.addWidget(theme.set_role(QLabel("Recording"), "section"))
        record_layout.addSpacing(4)

        self.record_btn = QPushButton("Record")
        self.record_btn.clicked.connect(self._start_recording)
        self.record_btn.setEnabled(False)
        record_layout.addWidget(self.record_btn)

        self.pause_record_btn = QPushButton("Pause")
        self.pause_record_btn.clicked.connect(self._pause_recording)
        self.pause_record_btn.setEnabled(False)
        record_layout.addWidget(self.pause_record_btn)

        self.save_record_btn = QPushButton("Save CSV\u2026")
        self.save_record_btn.clicked.connect(self._save_recording)
        self.save_record_btn.setEnabled(False)
        record_layout.addWidget(self.save_record_btn)

        record_layout.addSpacing(4)
        self.record_status = QLabel("Not recording")
        theme.set_role(self.record_status, "faint")
        record_layout.addWidget(self.record_status)
        record_layout.addStretch()

        layout.addLayout(record_layout)

        # Recording graph: takes whatever height is left
        self.record_graph = pg.PlotWidget()
        theme.style_plot(self.record_graph)
        self.record_graph.setLabel('bottom', 'Time (s)', color=theme.P.text_muted)
        self.record_graph.addLegend(offset=(8, 8))
        self.record_graph.setMinimumHeight(160)

        self.voltage_plot = self.record_graph.plot([], [], pen=theme.pen(theme.series_color("Voltage")), name='Voltage (V)')
        self.current_plot = self.record_graph.plot([], [], pen=theme.pen(theme.series_color("Current")), name='Current (A)')
        self.power_plot = self.record_graph.plot([], [], pen=theme.pen(theme.series_color("Power")), name='Power (W)')
        for curve in (self.voltage_plot, self.current_plot, self.power_plot):
            theme.fast_curve(curve)

        layout.addWidget(self.record_graph, stretch=1)

    def _show_running(self, running: bool):
        self.run_btn.setText("Stop" if running else "Start")
        theme.set_role(self.run_btn, "danger" if running else "primary")

    def set_capabilities(self, caps):
        """Offer exactly the ranges the connected model has. Item data is the
        SI value sent to the instrument; "Auto" carries None."""
        for combo, options in ((self.voltage_range, caps.voltage_ranges),
                               (self.current_range, caps.current_ranges)):
            previous = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Auto", None)
            for opt in options:
                combo.addItem(opt.label, opt.value)
            found = combo.findText(previous)
            combo.setCurrentIndex(found if found >= 0 else 0)
            combo.blockSignals(False)
        if hasattr(self, "source_value"):
            apply_source_limits(self.source_value, self.compliance,
                                self.source_type.currentText(), reset_compliance=False)

    def _update_source_units(self, source_type):
        apply_source_limits(self.source_value, self.compliance, source_type, reset_compliance=True)

    def _update_rate_changed(self):
        rates = [1000, 200, 100, 50]
        if self.running and self._reader is not None:
            self._reader.set_period_ms(rates[self.update_rate.currentIndex()])

    def _set_terminal(self, term):
        self.terminal = term
        self.front_btn.set_selected(term == "Front")
        self.rear_btn.set_selected(term == "Rear")

    def _set_sense(self, sense):
        self.sense = sense
        self.sense_2w.set_selected(sense == "2-Wire")
        self.sense_4w.set_selected(sense == "4-Wire")

    def start_live(self):
        if not self.app.smu or not self.app.smu.connected:
            QMessageBox.warning(self, "Not Connected", "Please connect to instrument first")
            return

        try:
            source_val = self.source_value.value()
            compliance = self.compliance.value()
            ch = self.app.current_channel

            # 2450: terminals first, as its window did.
            if self.app.smu.caps.terminal_select:
                self.app.smu.set_terminal(self.terminal)

            if self.source_type.currentText() == "Voltage":
                self.app.smu.set_source_voltage(source_val, compliance_current=compliance, channel=ch)
            else:
                self.app.smu.set_source_current(source_val, compliance_voltage=compliance, channel=ch)

            # Apply sense mode so the multimeter's UI toggle actually takes effect.
            # Without this, the SMU keeps whatever sense mode the sweep (or a prior
            # session) left it in, and 4-Wire wiring read as 2-Wire produces wildly
            # wrong I/R readings.
            if self.sense == "4-Wire":
                self.app.smu.set_remote_sense(True, ch)
            else:
                self.app.smu.set_remote_sense(False, ch)

            # Apply measurement ranges
            # Ranges come from the connected model's capability table; "Auto" is None.
            self.app.smu.configure_measure_range("v", self.voltage_range.currentData(), ch)
            self.app.smu.configure_measure_range("i", self.current_range.currentData(), ch)

            self.app.smu.output_on(ch)
            self.app._update_output_buttons()

            self.running = True
            self.reading_count = 0
            self._show_running(True)
            self.record_btn.setEnabled(True)

            rates = [1000, 200, 100, 50]
            self._reader = LiveReader(self.app.smu, ch, self.measure_type.currentText(),
                                      rates[self.update_rate.currentIndex()])
            self._reader.reading.connect(self._on_reading)
            self._reader.failed.connect(lambda msg: print(f"Measurement error: {msg}"))
            self._reader.start()

        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def stop_live(self):
        reader, self._reader = self._reader, None
        if reader is not None:
            reader.stop()
            reader.wait(3000)   # a reading already in flight finishes first
        self.running = False

        if self.app.smu:
            try:
                self.app.smu.output_off(self.app.current_channel)
            except:
                pass
            self.app._update_output_buttons()

        self._show_running(False)

        if self.recording:
            self._pause_recording()
        self.record_btn.setEnabled(False)
        self.save_record_btn.setEnabled(len(self.recorded_data) > 0)

    def _on_reading(self, voltage, current):
        """A reading arrived from the LiveReader (runs on the UI thread)."""
        if not self.app.smu or not self.running:
            return

        try:
            if voltage is not None:
                self.voltage_display.set_value(voltage)
            if current is not None:
                self.current_display.set_value(current)

            resistance = 0
            power = 0
            # Same noise-floor guard as _run_sweep: R is undefined when V or
            # I are at measurement noise level (nV / pA). Power is always
            # fine at V=0 (P=0) so it doesn't need the extra V guard.
            floor = self.app.smu.caps.current_noise_floor if self.app.smu else 1e-9
            if voltage is not None and current is not None and abs(current) > floor and abs(voltage) > 1e-6:
                resistance = voltage / current
                power = abs(voltage * current)
                self.resistance_display.set_value(resistance)
                self.power_display.set_value(power)
                self.last_resistance = resistance

            self.reading_count += 1
            self.readings_label.setText(f"{self.reading_count} readings")

            if self.recording and self.record_start_time is not None:
                elapsed = time.time() - self.record_start_time
                v = voltage if voltage is not None else 0
                i = current if current is not None else 0
                self.recorded_data.append((elapsed, v, i, resistance, power))
                self._update_record_graph()
                self.record_status.setText(f"Recording, {len(self.recorded_data)} points")

        except Exception as e:
            print(f"Measurement error: {e}")

    def _start_recording(self):
        self.recording = True
        self.record_start_time = time.time()
        self.recorded_data = []
        self.record_btn.setEnabled(False)
        self.pause_record_btn.setEnabled(True)
        self.save_record_btn.setEnabled(False)
        self.record_status.setText("Recording, 0 points")
        theme.set_role(self.record_status, "pill", tone="accent")
        self.voltage_plot.setData([], [])
        self.current_plot.setData([], [])
        self.power_plot.setData([], [])

    def _pause_recording(self):
        self.recording = False
        self.record_btn.setEnabled(True)
        self.pause_record_btn.setEnabled(False)
        self.save_record_btn.setEnabled(len(self.recorded_data) > 0)
        self.record_status.setText(f"Paused, {len(self.recorded_data)} points")
        theme.set_role(self.record_status, "pill", tone="warn")

    def _save_recording(self):
        if not self.recorded_data:
            QMessageBox.warning(self, "No Data", "No recorded data to save")
            return

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        default_name = f"MultimeterRecording_{timestamp}.csv"

        file, _ = QFileDialog.getSaveFileName(
            self, "Save Recording", default_name, "CSV Files (*.csv)"
        )
        if file:
            try:
                with open(file, 'w', newline='', encoding='cp1252', errors='replace') as f:
                    writer = csv.writer(f)
                    writer.writerow(["Time(s)", "Voltage(V)", "Current(A)", "Resistance(\u03a9)", "Power(mW)"])
                    for t, v, i, r, p in self.recorded_data:
                        writer.writerow([t, v, i, r, p * 1000.0])
                QMessageBox.information(self, "Success", f"Saved {len(self.recorded_data)} points to CSV")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def _update_record_graph(self):
        if not self.recorded_data:
            return
        times = [d[0] for d in self.recorded_data]
        voltages = [d[1] for d in self.recorded_data]
        currents = [d[2] for d in self.recorded_data]
        powers = [d[4] for d in self.recorded_data]
        self.voltage_plot.setData(times, voltages)
        self.current_plot.setData(times, currents)
        self.power_plot.setData(times, powers)


def make_form() -> QFormLayout:
    """A settings form: one label column, fields at their natural width."""
    form = QFormLayout()
    form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
    form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
    form.setRowWrapPolicy(QFormLayout.DontWrapRows)
    form.setHorizontalSpacing(12)
    form.setVerticalSpacing(6)
    return form


class FormRow:
    """A label and its field in a QFormLayout, shown or hidden together.

    Qt 5's QFormLayout has no per-row visibility; hiding only the field left
    its label behind, and wrapping rows in their own widgets knocked them out
    of the form's label column (the 6430's Auto Zero sat indented).
    """

    def __init__(self, form: QFormLayout, label: str, field: QWidget):
        self.label = theme.set_role(QLabel(label), "muted")
        self.field = field
        form.addRow(self.label, field)

    def setVisible(self, visible: bool):
        self.label.setVisible(visible)
        self.field.setVisible(visible)

    def isVisible(self) -> bool:
        return not self.field.isHidden()


def _hbox_widget(*widgets, spacing: int = 8) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for x in widgets:
        lay.addWidget(x)
    lay.addStretch()
    return w


FIELD_WIDTH = 130


class SourceSettingsWidget(QGroupBox):
    """Source settings panel — no DC/Pulse for 2602B"""

    def __init__(self, parent=None):
        super().__init__("Source", parent)
        self._setup_ui()

    def _setup_ui(self):
        form = make_form()
        self.setLayout(form)

        self.volt_btn = ToggleButton("Voltage")
        self.volt_btn.set_selected(True)
        self.volt_btn.clicked.connect(lambda: self._set_function("Voltage"))
        self.curr_btn = ToggleButton("Current")
        self.curr_btn.clicked.connect(lambda: self._set_function("Current"))
        FormRow(form, "Function", theme.segmented(self.volt_btn, self.curr_btn))

        self.mode = QComboBox()
        self.mode.addItems(["Linear Sweep", "List Sweep", "Log Sweep"])
        self.mode.setMinimumWidth(FIELD_WIDTH)
        FormRow(form, "Mode", self.mode)

        self.range = QComboBox()
        self.range.addItems(["Auto", "100 mV", "1 V", "6 V", "40 V"])
        self.range.setMinimumWidth(FIELD_WIDTH)
        FormRow(form, "Range", self.range)

        self.compliance = QDoubleSpinBox()
        self.compliance.setMinimumWidth(FIELD_WIDTH)
        apply_source_limits(None, self.compliance, "Voltage", reset_compliance=True)
        FormRow(form, "Limit", self.compliance)

        self.function = "Voltage"

    def _set_function(self, func_name):
        self.function = func_name
        self.volt_btn.set_selected(func_name == "Voltage")
        self.curr_btn.set_selected(func_name == "Current")

        apply_source_limits(None, self.compliance, func_name, reset_compliance=True)
        self.range.clear()
        self.range.addItems(source_range_labels(func_name))

    def set_capabilities(self, caps):
        """Re-range for a newly connected model, keeping the chosen function."""
        apply_source_limits(None, self.compliance, self.function, reset_compliance=False)
        current = self.range.currentText()
        self.range.clear()
        self.range.addItems(source_range_labels(self.function))
        i = self.range.findText(current)
        self.range.setCurrentIndex(i if i >= 0 else 0)


class InstrumentSettingsWidget(QGroupBox):
    """Instrument settings. Rows for hardware a model lacks are hidden, so the
    same panel serves every supported SMU."""

    def __init__(self, parent=None):
        super().__init__("Instrument", parent)
        self._setup_ui()

    def _pair_row(self, form, label, a_text, b_text, on_pick):
        a, b = ToggleButton(a_text.lower() if "Wire" in a_text else a_text), \
               ToggleButton(b_text.lower() if "Wire" in b_text else b_text)
        a.clicked.connect(lambda: on_pick(a_text))
        b.clicked.connect(lambda: on_pick(b_text))
        return FormRow(form, label, theme.segmented(a, b)), a, b

    def _setup_ui(self):
        form = make_form()
        self.setLayout(form)

        # Terminals: Front / Rear (2450)
        self.terminal_row, self.front_btn, self.rear_btn = self._pair_row(
            form, "Terminals", "Front", "Rear", self._set_terminal)

        # Sense: 2-Wire / 4-Wire
        self.sense_row, self.sense_2w, self.sense_4w = self._pair_row(
            form, "Sense", "2-Wire", "4-Wire", self._set_sense)

        # High capacitance (2450)
        self.high_cap = QCheckBox("High-capacitance mode")
        self._high_cap_row = FormRow(form, "", self.high_cap)

        # Guard (6430)
        self.guard_mode = QCheckBox("Guard mode (triax)")
        self._guard_row = FormRow(form, "", self.guard_mode)

        # Output off state (6430)
        self.output_off_mode = QComboBox()
        self.output_off_mode.addItems(["Normal", "Zero", "High-Z"])
        self.output_off_mode.setMinimumWidth(FIELD_WIDTH)
        self.off_row = FormRow(form, "Output off", self.output_off_mode)

        self._model = None
        self._set_terminal("Rear")
        self._set_sense("2-Wire")
        self.set_capabilities(registry.active())

    def set_capabilities(self, caps):
        self.terminal_row.setVisible(caps.terminal_select)
        self._high_cap_row.setVisible(caps.high_capacitance)
        self._guard_row.setVisible(caps.guard_mode)
        self.off_row.setVisible(caps.output_off_mode)
        if caps.output_off_modes:
            current = self.output_off_mode.currentText()
            self.output_off_mode.clear()
            self.output_off_mode.addItems(caps.output_off_modes)
            i = self.output_off_mode.findText(current)
            self.output_off_mode.setCurrentIndex(i if i >= 0 else 0)
        # Each model starts in the sense mode its own window defaulted to —
        # only when the model changes, never over a choice made this session.
        if caps.model != self._model:
            self._model = caps.model
            self._set_sense("4-Wire" if caps.default_four_wire else "2-Wire")

    def _set_terminal(self, term):
        self.terminal = term
        self.front_btn.set_selected(term == "Front")
        self.rear_btn.set_selected(term == "Rear")

    def _set_sense(self, sense):
        self.sense = sense
        self.sense_2w.set_selected(sense == "2-Wire")
        self.sense_4w.set_selected(sense == "4-Wire")


class MeasureSettingsWidget(QGroupBox):
    """Measurement settings"""

    def __init__(self, parent=None):
        super().__init__("Measure", parent)
        self._setup_ui()

    def _setup_ui(self):
        form = make_form()
        self.setLayout(form)

        self.measure_v = QCheckBox("Voltage")
        self.measure_v.setChecked(True)
        self.measure_i = QCheckBox("Current")
        self.measure_i.setChecked(True)
        self.measure_r = QCheckBox("Resistance")
        self.measure_p = QCheckBox("Power")
        FormRow(form, "Quantities", _hbox_widget(self.measure_v, self.measure_i,
                                             self.measure_r, self.measure_p, spacing=12))

        self.measure_range = QComboBox()
        self.measure_range.addItems(["Auto", "100 nA", "1 \u00b5A", "10 \u00b5A", "100 \u00b5A", "1 mA", "10 mA", "100 mA", "1 A", "3 A"])
        self.measure_range.setMinimumWidth(FIELD_WIDTH)
        FormRow(form, "Range", self.measure_range)

        self.auto_zero = QComboBox()
        self.auto_zero.addItems(["On", "Off", "Once"])
        self.auto_zero.setMinimumWidth(FIELD_WIDTH)
        self.auto_zero_row = FormRow(form, "Auto zero", self.auto_zero)
        self.auto_zero_row.setVisible(registry.active().auto_zero)


class TimingSettingsWidget(QGroupBox):
    """Timing settings: NPLC, delay, points, repeat"""

    def __init__(self, parent=None):
        super().__init__("Timing", parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = make_form()
        self.setLayout(layout)

        self.points = QSpinBox()
        self.points.setRange(1, 10000000)
        self.points.setValue(51)
        self.points.setMinimumWidth(FIELD_WIDTH)
        FormRow(layout, "Points", self.points)

        self.repeat = QSpinBox()
        self.repeat.setRange(1, 1000)
        self.repeat.setValue(1)
        self.repeat.setMinimumWidth(FIELD_WIDTH)
        FormRow(layout, "Repeat", self.repeat)

        self.delay = QDoubleSpinBox()
        self.delay.setRange(0, 10)
        self.delay.setDecimals(4)
        self.delay.setValue(0.05)
        self.delay.setSuffix(" s")
        self.delay.setMinimumWidth(FIELD_WIDTH)
        self.auto_delay_check = QCheckBox("Match step size")
        self.auto_delay_check.setToolTip("When ticked, delay is computed so each point takes Step Size seconds")
        self.auto_delay_check.toggled.connect(self._on_auto_delay_toggled)
        FormRow(layout, "Delay", _hbox_widget(self.delay, self.auto_delay_check, spacing=10))

        self.step_size = QDoubleSpinBox()
        self.step_size.setRange(0.001, 60)
        self.step_size.setDecimals(4)
        self.step_size.setValue(1.0)
        self.step_size.setSuffix(" s")
        self.step_size.setMinimumWidth(FIELD_WIDTH)
        self.step_size.setToolTip("Desired time between consecutive sweep points (window + delay)")
        self.step_size.valueChanged.connect(self._recompute_auto_delay)
        FormRow(layout, "Step (dt)", self.step_size)

        self.nplc = QDoubleSpinBox()
        self.nplc.setRange(0.001, 25)
        self.nplc.setDecimals(3)
        self.nplc.setValue(1.0)
        self.nplc.setMinimumWidth(FIELD_WIDTH)
        self.nplc.valueChanged.connect(self._update_window)
        FormRow(layout, "NPLC", self.nplc)

        self.window_label = theme.set_role(QLabel("20 ms"), "mono")
        FormRow(layout, "Window", self.window_label)

    def _update_window(self):
        nplc = self.nplc.value()
        window_ms = nplc * 20
        self.window_label.setText(f"{window_ms:.1f} ms")
        self._recompute_auto_delay()

    def _on_auto_delay_toggled(self, checked: bool):
        self.delay.setReadOnly(checked)
        self.delay.setButtonSymbols(QAbstractSpinBox.NoButtons if checked else QAbstractSpinBox.UpDownArrows)
        if checked:
            self._recompute_auto_delay()

    # Headroom subtracted from the auto-computed delay to account for
    # the bus overhead of issuing measure_voltage() + measure_current()
    # over USB-TSP plus general Python/Qt overhead. Without this, each
    # sweep iteration overshoots step_size by ~30 ms and the absolute
    # tick alignment can never catch up, so the run drifts seconds per
    # thousand points.
    _AUTO_DELAY_OVERHEAD_S = 0.050

    def _recompute_auto_delay(self):
        if not getattr(self, "auto_delay_check", None) or not self.auto_delay_check.isChecked():
            return
        window_s = self.nplc.value() * 20e-3
        new_delay = max(0.0,
                        self.step_size.value() - window_s - self._AUTO_DELAY_OVERHEAD_S)
        if new_delay > self.delay.maximum():
            new_delay = self.delay.maximum()
        self.delay.blockSignals(True)
        self.delay.setValue(new_delay)
        self.delay.blockSignals(False)


UNTITLED = "Untitled experiment"


class ExperimentsSidebar(QGroupBox):
    """Sidebar listing saved experiments with action buttons + notes."""

    experiment_selected = Signal(str)   # emitted when user picks one from the list
    save_requested = Signal(str)        # emitted when user wants to save current state under a name
    rename_requested = Signal(str, str) # (old_name, new_name)
    delete_requested = Signal(str)
    new_requested = Signal(str)         # new experiment with this name (saved immediately)
    clone_requested = Signal(str, str)  # (source_name, new_name)
    notes_changed = Signal(str)

    def __init__(self, store: ExperimentStore, parent=None):
        super().__init__(parent)
        theme.set_role(self, "plain")
        self.store = store
        self._current_name: Optional[str] = None
        self._dirty = False
        self._suppress_select = False
        self._setup_ui()
        self.refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 0, 8, 8)
        layout.setSpacing(6)

        # Title with the actions beside it, then what is loaded now
        head = QHBoxLayout()
        head.setSpacing(4)
        head.addWidget(theme.set_role(QLabel("Saved"), "section"))
        head.addStretch()

        new_btn = QPushButton("New")
        new_btn.setToolTip("Create a new experiment in the list (prompts for a name)")
        new_btn.clicked.connect(self._on_new_clicked)
        head.addWidget(new_btn)

        self.more_btn = theme.set_role(QToolButton(), "quiet")
        self.more_btn.setText("\u22ef")
        self.more_btn.setToolTip("More actions")
        self.more_btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.more_btn)
        self._act_load = menu.addAction("Load selected", self._on_load_clicked)
        menu.addSeparator()
        self._act_save = menu.addAction("Save", self._on_save_clicked)
        self._act_save.setShortcut(QKeySequence.Save)
        menu.addAction("Save as\u2026", self._on_save_as_clicked)
        menu.addAction("Rename\u2026", self._on_rename_clicked)
        menu.addAction("Clone\u2026", self._on_clone_clicked)
        menu.addSeparator()
        menu.addAction("Delete\u2026", self._on_delete_clicked)
        self.more_btn.setMenu(menu)
        head.addWidget(self.more_btn)
        layout.addLayout(head)

        self.current_label = QLabel(UNTITLED)
        theme.set_role(self.current_label, "card-title")
        self.current_label.setWordWrap(True)
        layout.addWidget(self.current_label)

        # Save works from anywhere in the window, not only from the menu
        save_shortcut = QShortcut(QKeySequence.Save, self)
        save_shortcut.setContext(Qt.WindowShortcut)
        save_shortcut.activated.connect(self._on_save_clicked)

        self.list_widget = QListWidget()
        theme.set_role(self.list_widget, "flat")
        self.list_widget.setFrameShape(QFrame.NoFrame)
        self.list_widget.setToolTip("Double-click to load. Right-click for more.")
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._on_list_menu)
        layout.addWidget(self.list_widget, stretch=1)

        layout.addWidget(theme.set_role(QLabel("Notes"), "section"))
        self.notes = QTextEdit()
        self.notes.setMaximumHeight(110)
        self.notes.setPlaceholderText("Free-text notes for this experiment\u2026")
        self.notes.textChanged.connect(lambda: self.notes_changed.emit(self.notes.toPlainText()))
        layout.addWidget(self.notes)

    def _on_list_menu(self, pos):
        item = self.list_widget.itemAt(pos)
        if item is None:
            return
        self.list_widget.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction("Load", self._on_load_clicked)
        if item.text() == self._current_name:
            menu.addAction("Rename\u2026", self._on_rename_clicked)
        menu.addAction("Clone\u2026", self._on_clone_clicked)
        menu.addSeparator()
        menu.addAction("Delete\u2026", self._on_delete_clicked)
        menu.exec(self.list_widget.viewport().mapToGlobal(pos))

    # --- public API used by main window ---

    def refresh(self):
        self._suppress_select = True
        self.list_widget.clear()
        for name in self.store.names():
            self.list_widget.addItem(name)
            if name == self._current_name:
                self.list_widget.setCurrentRow(self.list_widget.count() - 1)
        self._suppress_select = False
        self._update_label()

    def set_current(self, name: Optional[str], notes: str = ""):
        """Set the currently-loaded experiment (without firing experiment_selected)."""
        self._current_name = name
        self._dirty = False
        self._suppress_select = True
        self.list_widget.clearSelection()
        if name:
            for i in range(self.list_widget.count()):
                if self.list_widget.item(i).text() == name:
                    self.list_widget.setCurrentRow(i)
                    break
        self._suppress_select = False
        self.notes.blockSignals(True)
        self.notes.setPlainText(notes or "")
        self.notes.blockSignals(False)
        self._update_label()

    def mark_dirty(self, dirty: bool = True):
        if self._dirty == dirty:
            return
        self._dirty = dirty
        self._update_label()

    def current_name(self) -> Optional[str]:
        return self._current_name

    def is_dirty(self) -> bool:
        return self._dirty

    # --- internal handlers ---

    def _update_label(self):
        name = self._current_name or UNTITLED
        self.current_label.setText(f"{name} \u2022" if self._dirty else name)
        self.current_label.setToolTip("Unsaved changes" if self._dirty else "")

    def _selected_name(self) -> Optional[str]:
        items = self.list_widget.selectedItems()
        return items[0].text() if items else None

    def _on_new_clicked(self):
        existing = set(self.store.names())
        i = 1
        while f"Experiment {i}" in existing:
            i += 1
        default = f"Experiment {i}"
        name, ok = QInputDialog.getText(self, "New Experiment",
                                         "Name:", QLineEdit.Normal, default)
        name = (name or "").strip()
        if not ok or not name:
            return
        if name in existing:
            QMessageBox.warning(self, "New", f"'{name}' is already taken.")
            return
        self.new_requested.emit(name)

    def _on_load_clicked(self):
        name = self._selected_name()
        if not name:
            QMessageBox.information(self, "Load", "Select an experiment from the list first.")
            return
        if name == self._current_name and not self._dirty:
            return  # nothing to do
        self.experiment_selected.emit(name)

    def _on_item_double_clicked(self, item):
        if item is None:
            return
        name = item.text()
        if name == self._current_name and not self._dirty:
            return
        self.experiment_selected.emit(name)

    def _on_save_clicked(self):
        if self._current_name:
            self.save_requested.emit(self._current_name)
        else:
            self._on_save_as_clicked()

    def _on_save_as_clicked(self):
        name, ok = QInputDialog.getText(self, "Save Experiment As",
                                         "Experiment name:", QLineEdit.Normal,
                                         self._current_name or "")
        name = (name or "").strip()
        if not ok or not name:
            return
        if name in self.store.names() and name != self._current_name:
            reply = QMessageBox.question(self, "Overwrite?",
                                          f"An experiment named '{name}' already exists. Overwrite?",
                                          QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        self.save_requested.emit(name)

    def _on_rename_clicked(self):
        # If nothing loaded, treat as Save As (name the current state).
        if not self._current_name:
            self._on_save_as_clicked()
            return
        new_name, ok = QInputDialog.getText(self, "Rename Experiment",
                                             "New name:", QLineEdit.Normal,
                                             self._current_name)
        new_name = (new_name or "").strip()
        if not ok or not new_name or new_name == self._current_name:
            return
        if new_name in self.store.names():
            QMessageBox.warning(self, "Rename", f"'{new_name}' is already taken.")
            return
        self.rename_requested.emit(self._current_name, new_name)

    def _on_clone_clicked(self):
        # Clone whatever is selected in the list (falls back to currently loaded).
        items = self.list_widget.selectedItems()
        source = items[0].text() if items else self._current_name
        if not source:
            QMessageBox.information(self, "Clone",
                                     "Select an experiment to clone, or save the current state first.")
            return
        default = f"{source} (copy)"
        # Avoid colliding with existing names
        existing = set(self.store.names())
        if default in existing:
            i = 2
            while f"{source} (copy {i})" in existing:
                i += 1
            default = f"{source} (copy {i})"
        new_name, ok = QInputDialog.getText(self, "Clone Experiment",
                                             "Name for the copy:", QLineEdit.Normal,
                                             default)
        new_name = (new_name or "").strip()
        if not ok or not new_name:
            return
        if new_name in existing:
            QMessageBox.warning(self, "Clone", f"'{new_name}' is already taken.")
            return
        self.clone_requested.emit(source, new_name)

    def _on_delete_clicked(self):
        name = self._selected_name() or self._current_name
        if not name:
            QMessageBox.information(self, "Delete", "Select an experiment to delete.")
            return
        reply = QMessageBox.question(self, "Delete experiment?",
                                      f"Delete '{name}'?\n(CSV data is kept.)",
                                      QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.delete_requested.emit(name)


class SweepListWidget(QWidget):
    """Sweep list management with table"""

    list_changed = Signal(int)
    wave_generator_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sweep_values = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Range to generate from
        gen_row = QHBoxLayout()
        gen_row.setSpacing(6)
        _v = registry.active().max_voltage
        self.start_val = QDoubleSpinBox()
        self.start_val.setRange(-_v, _v)
        self.start_val.setDecimals(4)
        self.start_val.setValue(0)
        self.stop_val = QDoubleSpinBox()
        self.stop_val.setRange(-_v, _v)
        self.stop_val.setDecimals(4)
        self.stop_val.setValue(5)
        self.num_points = QSpinBox()
        self.num_points.setRange(2, 10000)
        self.num_points.setValue(51)
        for label, box in (("Start", self.start_val), ("Stop", self.stop_val), ("Points", self.num_points)):
            if gen_row.count():
                gen_row.addSpacing(8)
            gen_row.addWidget(theme.set_role(QLabel(label), "muted"))
            box.setMinimumWidth(96)
            gen_row.addWidget(box)
        gen_row.addSpacing(8)
        gen_btn = QPushButton("Fill linear")
        gen_btn.setToolTip("Fill the list with evenly spaced values from Start to Stop")
        gen_btn.clicked.connect(self._generate_linear)
        gen_row.addWidget(gen_btn)
        log_btn = QPushButton("Fill log")
        log_btn.setToolTip("Fill the list with log-spaced values (Start and Stop must be positive)")
        log_btn.clicked.connect(self._generate_log)
        gen_row.addWidget(log_btn)
        gen_row.addStretch()
        layout.addLayout(gen_row)

        # The list itself
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["#", "Value"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(22)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setFont(theme.numeric_font(12))
        layout.addWidget(self.table, stretch=1)

        self.empty_hint = theme.set_role(QLabel(
            "Empty. Linear and log sweeps use Start, Stop and Points above; this list is "
            "only used when Mode is List Sweep. Fill it, import a CSV, or design a waveform."), "faint")
        self.empty_hint.setWordWrap(True)
        layout.addWidget(self.empty_hint)

        # List actions
        act_row = QHBoxLayout()
        act_row.setSpacing(6)
        import_btn = QPushButton("Import\u2026")
        import_btn.clicked.connect(self._import_csv)
        act_row.addWidget(import_btn)
        export_btn = QPushButton("Export\u2026")
        export_btn.clicked.connect(self._export_csv)
        act_row.addWidget(export_btn)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear)
        act_row.addWidget(clear_btn)
        act_row.addStretch()
        wave_btn = QPushButton("Design waveform\u2026")
        wave_btn.setToolTip("Build a sine, square or custom multi-segment heater waveform")
        wave_btn.clicked.connect(self.wave_generator_requested.emit)
        act_row.addWidget(wave_btn)
        layout.addLayout(act_row)

    def _generate_linear(self):
        start = self.start_val.value()
        stop = self.stop_val.value()
        points = self.num_points.value()
        self.sweep_values = list(np.linspace(start, stop, points))
        self._update_table()

    def _generate_log(self):
        start = self.start_val.value()
        stop = self.stop_val.value()
        points = self.num_points.value()
        if start <= 0 or stop <= 0:
            QMessageBox.warning(self, "Error", "Log sweep requires positive start and stop values")
            return
        self.sweep_values = list(np.logspace(np.log10(start), np.log10(stop), points))
        self._update_table()

    def _import_csv(self):
        file, _ = QFileDialog.getOpenFileName(self, "Import CSV", "", "CSV Files (*.csv);;All Files (*)")
        if file:
            try:
                values = []
                with open(file, 'r') as f:
                    for line in f:
                        for val in line.strip().split(','):
                            try:
                                values.append(float(val.strip()))
                            except:
                                pass
                self.sweep_values = values
                self._update_table()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to import: {e}")

    def _export_csv(self):
        if not self.sweep_values:
            QMessageBox.warning(self, "No Data", "No values to export")
            return
        file, _ = QFileDialog.getSaveFileName(self, "Export CSV", "", "CSV Files (*.csv)")
        if file:
            with open(file, 'w') as f:
                for v in self.sweep_values:
                    f.write(f"{v}\n")

    def _clear(self):
        self.sweep_values = []
        self._update_table()

    def _update_table(self):
        self.table.setRowCount(len(self.sweep_values))
        right = Qt.AlignRight | Qt.AlignVCenter
        for i, val in enumerate(self.sweep_values):
            idx = QTableWidgetItem(str(i + 1))
            idx.setTextAlignment(right)
            self.table.setItem(i, 0, idx)
            cell = QTableWidgetItem(f"{val:.6f}")
            cell.setTextAlignment(right)
            self.table.setItem(i, 1, cell)
        self.empty_hint.setVisible(not self.sweep_values)
        self.list_changed.emit(len(self.sweep_values))

    def get_values(self) -> List[float]:
        return self.sweep_values


# Display-unit options per axis variable. Maps unit name -> factor to
# multiply by when converting from base SI (V/A/Ω/W/s) to the chosen
# display unit. Used by the Experiments tab graph axis-unit dropdowns; table
# and CSV remain in fixed units (Power in mW, everything else in base).
GRAPH_AXIS_UNITS = {
    "Voltage":    [("V", 1.0), ("mV", 1e3)],
    "Current":    [("A", 1.0), ("mA", 1e3), ("µA", 1e6), ("nA", 1e9)],
    "Resistance": [("Ω", 1.0), ("kΩ", 1e-3), ("MΩ", 1e-6)],
    "Power":      [("mW", 1e3), ("W", 1.0), ("µW", 1e6)],
    "Time":       [("s", 1.0), ("min", 1.0/60.0), ("hour", 1.0/3600.0), ("ms", 1e3)],
    "Index":      [("", 1.0)],
    "None":       [("", 1.0)],
}


def _axis_unit_factor(variable: str, unit: str) -> float:
    for u, f in GRAPH_AXIS_UNITS.get(variable, [("", 1.0)]):
        if u == unit:
            return f
    return 1.0


class DualAxisGraph(pg.PlotWidget):
    """Graph widget with dual Y-axis support"""

    COLORS = {name: theme.series_color(name) for name in ("Voltage", "Current", "Resistance", "Power")}

    def __init__(self, parent=None):
        super().__init__(parent)

        theme.style_plot(self)

        self.data_points: List[MeasurementPoint] = []

        self.setLabel('left', 'Current', units='A', color=self.COLORS["Current"])
        self.setLabel('bottom', 'Voltage', units='V', color=theme.P.text_muted)

        self.view_box2 = pg.ViewBox()
        self.plotItem.scene().addItem(self.view_box2)
        self.plotItem.getAxis('right').linkToView(self.view_box2)
        self.view_box2.setXLink(self.plotItem)
        self.plotItem.hideAxis('right')   # Y2 starts as "None"
        theme.style_axis(self.plotItem.getAxis('right'))

        self.curve1 = self.plot([], [], pen=theme.pen(self.COLORS["Current"]), name='Y1')
        self.curve2 = pg.PlotDataItem([], [], pen=theme.pen(self.COLORS["Resistance"]), name='Y2')
        theme.fast_curve(self.curve1)
        theme.fast_curve(self.curve2)
        self.view_box2.addItem(self.curve2)

        self.plotItem.vb.sigResized.connect(self._update_views)

        self.x_axis = "Voltage"
        self.y1_axis = "Current"
        self.y2_axis = "None"
        self.x_unit = "V"
        self.y1_unit = "A"
        self.y2_unit = ""

        self.addLegend()

    def _update_views(self):
        self.view_box2.setGeometry(self.plotItem.vb.sceneBoundingRect())
        self.view_box2.linkedViewChanged(self.plotItem.vb, self.view_box2.XAxis)

    def set_axes(self, x: str, y1: str, y2: str,
                 x_unit: str = "", y1_unit: str = "", y2_unit: str = ""):
        self.x_axis = x
        self.y1_axis = y1
        self.y2_axis = y2
        self.x_unit = x_unit
        self.y1_unit = y1_unit
        self.y2_unit = y2_unit

        self.setLabel('bottom', x, units=x_unit)
        if y1 != "None":
            self.setLabel('left', y1, units=y1_unit, color=self.COLORS.get(y1, theme.P.text))
            self.curve1.setPen(theme.pen(self.COLORS.get(y1, theme.P.text)))
        if y2 != "None":
            self.plotItem.getAxis('right').setLabel(y2, units=y2_unit, color=self.COLORS.get(y2, theme.P.text))
            self.curve2.setPen(theme.pen(self.COLORS.get(y2, theme.P.text)))
            self.plotItem.showAxis('right')
        else:
            self.plotItem.hideAxis('right')
            self.curve2.setData([], [])

        self._update_plot()

    def add_point(self, point: MeasurementPoint):
        self.data_points.append(point)

    def clear_data(self):
        self.data_points = []
        self.curve1.setData([], [])
        self.curve2.setData([], [])

    def _get_data(self, axis: str, unit: str = "") -> List[float]:
        data = []
        for p in self.data_points:
            if axis == "Index":
                data.append(p.index)
            elif axis == "Time":
                data.append(p.timestamp)
            elif axis == "Voltage":
                data.append(p.voltage if p.voltage is not None else 0)
            elif axis == "Current":
                data.append(p.current if p.current is not None else 0)
            elif axis == "Resistance":
                if p.resistance and abs(p.resistance) < 1e12:
                    data.append(p.resistance)
                else:
                    data.append(float('nan'))
            elif axis == "Power":
                data.append(p.power if p.power is not None else 0)
        factor = _axis_unit_factor(axis, unit)
        if factor != 1.0:
            data = [v * factor for v in data]
        return data

    def _update_plot(self):
        if not self.data_points:
            return
        x_data = self._get_data(self.x_axis, self.x_unit)
        if self.y1_axis != "None":
            y1_data = self._get_data(self.y1_axis, self.y1_unit)
            self.curve1.setData(x_data, y1_data)
        if self.y2_axis != "None":
            y2_data = self._get_data(self.y2_axis, self.y2_unit)
            self.curve2.setData(x_data, y2_data)

    def update_live(self):
        self._update_plot()
        self.enableAutoRange()
        self.view_box2.enableAutoRange()


def si_format(value: Optional[float], unit: str, digits: int = 6) -> str:
    """Engineering notation with an SI prefix: 0.0150064 A -> '15.0064 mA'."""
    if value is None:
        return ""
    if value == 0:
        return f"0 {unit}"
    prefixes = ((1e9, "G"), (1e6, "M"), (1e3, "k"), (1, ""), (1e-3, "m"),
                (1e-6, "\u00b5"), (1e-9, "n"), (1e-12, "p"), (1e-15, "f"))
    mag = abs(value)
    for scale, prefix in prefixes:
        if mag >= scale:
            break
    scaled = value / scale
    int_digits = len(str(int(abs(scaled))))
    return f"{scaled:.{max(0, digits - int_digits)}f} {prefix}{unit}"


class DataTableWidget(QTableWidget):
    """Sweep results as they arrive. Display only — the CSV is written from the
    measurement data at full precision, never from these cells."""

    COLUMNS = ['#', 'Channel', 'Time', 'Elapsed (s)', 'Voltage', 'Current', 'Resistance', 'Power']
    _R_COL, _P_COL = 6, 7

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setColumnCount(len(self.COLUMNS))
        self.setHorizontalHeaderLabels(self.COLUMNS)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(22)
        self.setFont(theme.numeric_font(12))

        header = self.horizontalHeader()
        for i in range(len(self.COLUMNS)):
            header.setSectionResizeMode(
                i, QHeaderView.ResizeToContents if i < 4 else QHeaderView.Stretch)
        for i in (self._R_COL, self._P_COL):
            self.setColumnHidden(i, True)   # shown once a value arrives

        self.setAlternatingRowColors(True)
        self.setEditTriggers(QTableWidget.NoEditTriggers)

    def add_point(self, point: MeasurementPoint):
        row = self.rowCount()
        self.insertRow(row)

        r = point.resistance if point.resistance and abs(point.resistance) < 1e12 else None
        clock = point.computer_time.split(" ")[-1] if point.computer_time else ""
        cells = [str(point.index), point.channel.upper(), clock, f"{point.timestamp:.3f}",
                 si_format(point.voltage or None, "V"), si_format(point.current or None, "A"),
                 si_format(r, "\u03a9"), si_format(point.power or None, "W")]
        right = Qt.AlignRight | Qt.AlignVCenter
        for col, text in enumerate(cells):
            item = QTableWidgetItem(text)
            if col != 1:
                item.setTextAlignment(right)
            self.setItem(row, col, item)
        if r is not None:
            self.setColumnHidden(self._R_COL, False)
        if point.power:
            self.setColumnHidden(self._P_COL, False)

        self.scrollToBottom()

    def clear_data(self):
        self.setRowCount(0)
        for i in (self._R_COL, self._P_COL):
            self.setColumnHidden(i, True)


class ConnectionDialog(QDialog):
    """Connect the source meter and, optionally, the calorimeter.

    Two tabs rather than one tall column: the source meter is what you connect
    every session; the calorimeter is optional and has its own depth (setups,
    sniff mode, capture interface).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.app = parent
        self.setWindowTitle("Connect")
        self.setMinimumSize(600, 560)
        self._setup_ui()
        self._refresh_calorimeter_status()

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(6)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, stretch=1)

        # ---- Source meter tab ---------------------------------------------
        smu_page = QWidget()
        smu_layout = QVBoxLayout(smu_page)
        smu_layout.setContentsMargins(0, 10, 0, 0)
        settings = getattr(self.app, "settings", None)
        self.smu_panel = SMUConnectPanel(settings=settings)
        self.smu_panel.connect_requested.connect(self._on_smu_connect)
        smu_layout.addWidget(self.smu_panel)
        self.tabs.addTab(smu_page, "Source meter")

        # ---- Calorimeter tab ----------------------------------------------
        cal_page = QWidget()
        cal_layout = QVBoxLayout(cal_page)
        cal_layout.setContentsMargins(0, 10, 0, 0)
        cal_layout.setSpacing(8)
        self.tabs.addTab(cal_page, "Calorimeter")

        # Instrument: cards drive a hidden combo, which the handlers read
        cal_layout.addWidget(theme.set_role(QLabel("Instrument"), "section"))
        self.cal_combo = QComboBox()
        self.cal_combo.hide()
        cards_row = QHBoxLayout()
        cards_row.setSpacing(6)
        self._cal_cards = {}
        signal_names = {"hf": "heat flow", "t": "sample T", "ext_t": "external T"}
        for name, spec in CALORIMETERS.items():
            self.cal_combo.addItem(name)
            summary = ", ".join(signal_names.get(k, k) for k in spec["channels"])
            summary = summary[:1].upper() + summary[1:]
            card = ChoiceCard(name, summary)
            card.clicked.connect(lambda n=name: self.cal_combo.setCurrentText(n))
            self._cal_cards[name] = card
            cards_row.addWidget(card)
        self.cal_combo.currentTextChanged.connect(self._sync_cal_cards)
        cal_layout.addLayout(cards_row)
        self._sync_cal_cards(self.cal_combo.currentText())

        # How: connect directly, or watch Calisto's traffic
        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 4, 0, 0)
        mode_row.addWidget(theme.set_role(QLabel("Mode"), "section"))
        mode_row.addStretch()
        self.cal_direct_btn = ToggleButton("Direct")
        self.cal_direct_btn.setToolTip(
            "Connects to the instrument itself. Exclusive: close Calisto first.")
        self.cal_sniff_btn = ToggleButton("Sniff")
        self.cal_sniff_btn.setToolTip(
            "Never connects; watches the traffic Calisto's own polling generates, so\n"
            "Calisto stays connected. Needs Npcap and this program run as Administrator.")
        mode_row.addWidget(theme.segmented(self.cal_direct_btn, self.cal_sniff_btn))
        cal_layout.addLayout(mode_row)
        # The checkbox stays the source of truth the handlers read; the
        # segmented switch is how it is shown and set.
        self.cal_sniff_check = QCheckBox()
        self.cal_sniff_check.hide()
        self.cal_sniff_check.toggled.connect(self._on_cal_sniff_toggled)
        self.cal_direct_btn.clicked.connect(lambda: self.cal_sniff_check.setChecked(False))
        self.cal_sniff_btn.clicked.connect(lambda: self.cal_sniff_check.setChecked(True))

        details = QGroupBox("Connection")
        form = make_form()
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        details.setLayout(form)

        self.cal_setup_combo = QComboBox()
        self.cal_setup_combo.setToolTip(
            "A saved setup remembers this instrument's IP, the capture adapter,\n"
            "and the signal profile that says what its replies mean.\n"
            "Build one with New\u2026 \u2014 it watches the traffic and shows you what it finds."
        )
        self.cal_setup_combo.currentIndexChanged.connect(self._on_cal_setup_selected)
        self.cal_setup_new_btn = QPushButton("New\u2026")
        self.cal_setup_new_btn.clicked.connect(lambda: self._on_cal_setup_edit(True))
        self.cal_setup_edit_btn = QPushButton("Edit\u2026")
        self.cal_setup_edit_btn.clicked.connect(lambda: self._on_cal_setup_edit(False))
        self.cal_setup_del_btn = QPushButton("Delete")
        self.cal_setup_del_btn.clicked.connect(self._on_cal_setup_delete)
        setup_field = QWidget()
        sl = QHBoxLayout(setup_field)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(6)
        sl.addWidget(self.cal_setup_combo, stretch=1)
        for b in (self.cal_setup_new_btn, self.cal_setup_edit_btn, self.cal_setup_del_btn):
            sl.addWidget(b)
        FormRow(form, "Saved setup", setup_field)

        self.cal_host = QLineEdit()
        self.cal_host.setPlaceholderText("169.254.x.x \u2014 or use Find")
        self.cal_discover_btn = QPushButton("Find")
        self.cal_discover_btn.setToolTip(
            "Look up the selected calorimeter's IP in the OS ARP cache using its\n"
            "fixed MAC. Requires that Calisto has recently talked to the instrument."
        )
        self.cal_discover_btn.clicked.connect(self._on_calorimeter_discover)
        host_field = QWidget()
        hl = QHBoxLayout(host_field)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        hl.addWidget(self.cal_host, stretch=1)
        hl.addWidget(self.cal_discover_btn)
        FormRow(form, "Address", host_field)

        self.cal_iface_combo = QComboBox()
        self.cal_iface_combo.addItem("Auto-detect (may guess wrong)", None)
        self.cal_iface_combo.setToolTip(
            "Which network adapter to capture on. Auto-detect matches by subnet and can\n"
            "pick the wrong one (e.g. a Bluetooth adapter) \u2014 pick the real NIC by hand if so."
        )
        self.cal_iface_refresh_btn = QPushButton("Refresh")
        self.cal_iface_refresh_btn.clicked.connect(self._refresh_cal_interfaces)
        iface_field = QWidget()
        il = QHBoxLayout(iface_field)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(6)
        il.addWidget(self.cal_iface_combo, stretch=1)
        il.addWidget(self.cal_iface_refresh_btn)
        self._cal_iface_row = FormRow(form, "Capture on", iface_field)
        self.cal_iface_combo.setEnabled(False)
        self.cal_iface_refresh_btn.setEnabled(False)
        self._refresh_cal_setups()

        self.cal_interval = QDoubleSpinBox()
        self.cal_interval.setRange(0.5, 60.0)
        self.cal_interval.setValue(1.0)
        self.cal_interval.setSingleStep(0.5)
        self.cal_interval.setDecimals(1)
        self.cal_interval.setSuffix(" s")
        self.cal_interval.setMinimumWidth(FIELD_WIDTH)
        self._cal_poll_row = FormRow(form, "Poll every", self.cal_interval)
        cal_layout.addWidget(details)

        cal_layout.addStretch()

        # Footer: status on the left, the action on the right
        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.cal_status_label = QLabel("Not connected")
        theme.set_role(self.cal_status_label, "muted")
        self.cal_status_label.setWordWrap(True)
        foot.addWidget(self.cal_status_label, stretch=1)
        self.cal_connect_btn = theme.set_role(QPushButton("Connect calorimeter"), "primary")
        self.cal_connect_btn.setToolTip(
            "The C80/Drop accepts only one TCP client at a time \u2014 close Calisto\n"
            "before connecting. Reopen it afterwards to save data via Calisto.\n"
            "(Choose Sniff above to record while Calisto stays connected instead.)"
        )
        self.cal_connect_btn.clicked.connect(self._on_calorimeter_connect_toggle)
        foot.addWidget(self.cal_connect_btn)
        cal_layout.addLayout(foot)

        cal_note = QLabel("Read-only monitor. Configure and start experiments in Calisto first.")
        theme.set_role(cal_note, "faint")
        cal_layout.addWidget(cal_note)

        self._on_cal_sniff_toggled(False)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = theme.set_role(QPushButton("Close"), "quiet")
        close_btn.clicked.connect(self.reject)
        close_row.addWidget(close_btn)
        outer.addLayout(close_row)

    def _sync_cal_cards(self, name: str):
        for key, card in self._cal_cards.items():
            card.set_selected(key == name)

    # ---- Calorimeter handlers ----

    def _on_calorimeter_discover(self):
        name = self.cal_combo.currentText()
        mac = CALORIMETERS[name]["mac"]
        ip, diag = discover_calorimeter_ip(mac)
        if ip:
            self.cal_host.setText(ip)
            self.cal_status_label.setText(f"Found {name} at {ip}")
            theme.set_role(self.cal_status_label, "ok")
        else:
            self.cal_status_label.setText(f"Discover failed: {diag}")
            theme.set_role(self.cal_status_label, "danger")

    # ---- Saved setups ---------------------------------------------------

    def _setup_store(self):
        if getattr(self, "_cal_setup_store", None) is None:
            self._cal_setup_store = SetupStore()
        return self._cal_setup_store

    def _refresh_cal_setups(self):
        """Reload the setup list, keeping the current selection if it survived."""
        current = self.cal_setup_combo.currentData()
        self.cal_setup_combo.blockSignals(True)
        self.cal_setup_combo.clear()
        self.cal_setup_combo.addItem("None \u2014 fill in below", None)
        for name in self._setup_store().names():
            self.cal_setup_combo.addItem(name, name)
        if current:
            found = self.cal_setup_combo.findData(current)
            if found >= 0:
                self.cal_setup_combo.setCurrentIndex(found)
        self.cal_setup_combo.blockSignals(False)
        self._sync_setup_buttons()

    def _sync_setup_buttons(self):
        has = self.cal_setup_combo.currentData() is not None
        self.cal_setup_edit_btn.setEnabled(has)
        self.cal_setup_del_btn.setEnabled(has)

    def _selected_setup(self):
        name = self.cal_setup_combo.currentData()
        return self._setup_store().get(name) if name else None

    def _on_cal_setup_selected(self, _index=None):
        """Apply a saved setup to the fields below it.

        The fields stay editable afterwards: a setup is a starting point, not a
        lock, and the IP in particular is DHCP-assigned and does move.
        """
        self._sync_setup_buttons()
        setup = self._selected_setup()
        if setup is None:
            return
        idx = self.cal_combo.findText(setup.calorimeter)
        if idx >= 0:
            self.cal_combo.setCurrentIndex(idx)
        if setup.host:
            self.cal_host.setText(setup.host)
        # A setup exists to describe passive watching, so selecting one turns
        # sniff mode on; the interface list only populates while it is on.
        self.cal_sniff_check.setChecked(True)
        self._refresh_cal_interfaces()
        if setup.interface:
            found = self.cal_iface_combo.findData(setup.interface)
            if found >= 0:
                self.cal_iface_combo.setCurrentIndex(found)

    def _on_cal_setup_edit(self, new: bool):
        setup = None if new else self._selected_setup()
        dlg = CalorimeterSetupDialog(self, store=self._setup_store(), setup=setup)
        if dlg.exec() and dlg.saved_setup is not None:
            self._refresh_cal_setups()
            found = self.cal_setup_combo.findData(dlg.saved_setup.name)
            if found >= 0:
                self.cal_setup_combo.setCurrentIndex(found)

    def _on_cal_setup_delete(self):
        setup = self._selected_setup()
        if setup is None:
            return
        reply = QMessageBox.question(
            self, "Delete setup",
            f"Delete the setup {setup.name!r}?\n\n"
            "Its signal profile is kept — only the saved IP, adapter and "
            "profile choice go away.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._setup_store().delete(setup.name)
            self._refresh_cal_setups()

    def _on_cal_sniff_toggled(self, checked: bool):
        self.cal_direct_btn.set_selected(not checked)
        self.cal_sniff_btn.set_selected(checked)
        # Only the rows that apply to the chosen mode are shown.
        self._cal_poll_row.setVisible(not checked)
        self._cal_iface_row.setVisible(checked)
        self.cal_interval.setEnabled(not checked)
        self.cal_connect_btn.setText(
            "Start sniffing" if checked else "Connect calorimeter"
        )
        self.cal_iface_combo.setEnabled(checked)
        self.cal_iface_refresh_btn.setEnabled(checked)
        if checked and self.cal_iface_combo.count() <= 1:
            self._refresh_cal_interfaces()

    def _refresh_cal_interfaces(self):
        self.cal_iface_combo.clear()
        self.cal_iface_combo.addItem("Auto-detect (may guess wrong)", None)
        for iface in sniff_list_interfaces():
            self.cal_iface_combo.addItem(iface.label(), iface.name)

    def _on_calorimeter_connect_toggle(self):
        if self.app.calorimeter_reader is not None:
            self.app.disconnect_calorimeter()
            self._refresh_calorimeter_status()
            return

        host = self.cal_host.text().strip()
        if not host:
            self._on_calorimeter_discover()
            host = self.cal_host.text().strip()
            if not host:
                return

        sniff = self.cal_sniff_check.isChecked()
        name = self.cal_combo.currentText()

        if sniff:
            setup_for_profile = self._selected_setup()
            if setup_for_profile is None and not sniff_available(name):
                QMessageBox.warning(self, "No sniff profile",
                    f"No traffic-decoding profile is bundled for {name}.\n\n"
                    "Use New\u2026 beside Saved setup to build one by watching the traffic.")
                return
            readiness = sniff_capture_readiness()
            if not readiness.ok:
                detail = readiness.detail
                if readiness.remedy:
                    detail += f"\n\n{readiness.remedy}"
                QMessageBox.warning(self, "Capture Not Available", detail)
                return
            if readiness.warning:
                reply = QMessageBox.question(
                    self, "Capture May Fail", f"{readiness.warning}\n\nTry anyway?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if reply != QMessageBox.Yes:
                    return
            chosen_interface = self.cal_iface_combo.currentData()
            setup = self._selected_setup()
            self.app.connect_calorimeter(name, host, float(self.cal_interval.value()),
                                          sniff=True, interface=chosen_interface,
                                          profile_name=setup.profile_name if setup else None)
            self._refresh_calorimeter_status()
            return

        available, reason = probe_port_free(host)
        if not available:
            self.cal_status_label.setText(f"Cannot connect: {reason}")
            theme.set_role(self.cal_status_label, "danger")
            return

        self.app.connect_calorimeter(name, host, float(self.cal_interval.value()))
        self._refresh_calorimeter_status()

    def _refresh_calorimeter_status(self):
        """Sync the calorimeter section's status and button labels with app state."""
        if self.app.calorimeter_reader is not None:
            name = self.app.calorimeter_name or "?"
            host = self.app.calorimeter_host or "?"
            mode = "sniffing" if self.app.calorimeter_sniffing else "connected"
            self.cal_status_label.setText(f"{mode.capitalize()}: {name} @ {host}")
            theme.set_role(self.cal_status_label, "ok")
            self.cal_connect_btn.setText(
                "Stop sniffing" if self.app.calorimeter_sniffing else "Disconnect calorimeter"
            )
            theme.set_role(self.cal_connect_btn, "danger")
            self.cal_sniff_check.setEnabled(False)
            self.cal_direct_btn.setEnabled(False)
            self.cal_sniff_btn.setEnabled(False)
            self.cal_iface_combo.setEnabled(False)
            self.cal_iface_refresh_btn.setEnabled(False)
        else:
            self.cal_sniff_check.setEnabled(True)
            self.cal_direct_btn.setEnabled(True)
            self.cal_sniff_btn.setEnabled(True)
            theme.set_role(self.cal_connect_btn, "primary")
            self._on_cal_sniff_toggled(self.cal_sniff_check.isChecked())
            # leave the last status message visible

    def _on_smu_connect(self, model, address, simulate, resistance, baud):
        """The source-meter panel asked to connect."""
        try:
            self.app.connect_instrument(model, address, simulate=simulate,
                                        simulation_resistance=resistance, baud_rate=baud)
        except Exception as e:
            self.smu_panel.show_error(f"Could not connect: {e}")
            return
        self.accept()

class SafetyDialog(QDialog):
    """Safety limits configuration dialog"""

    def __init__(self, parent=None, limits=None, model: str = "2602B"):
        super().__init__(parent)
        # Limits are always a specific model's SafetyLimits; the spin-box
        # ranges are that model's hardware maxima, not the 2602B's.
        self.model = model
        self.caps = registry.get(model)
        self.limits = limits if limits is not None else SMU.default_limits(model)
        self.setWindowTitle("Safety limits")
        self.setMinimumWidth(380)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        note = theme.set_role(QLabel(
            f"For the {self.caps.display_name}. Every source command is checked "
            f"against these before it reaches the instrument."), "muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        form = make_form()

        self.max_voltage = QDoubleSpinBox()
        v_max = self.caps.max_voltage
        i_max = self.caps.max_current
        p_max = SMU.default_limits(self.model).power_limit
        self.max_voltage.setRange(0.1, v_max)
        self.max_voltage.setValue(self.limits.max_voltage)
        self.max_voltage.setSuffix(" V")
        FormRow(form, "Max voltage", self.max_voltage)

        self.min_voltage = QDoubleSpinBox()
        self.min_voltage.setRange(-v_max, 0)
        self.min_voltage.setValue(self.limits.min_voltage)
        self.min_voltage.setSuffix(" V")
        FormRow(form, "Min voltage", self.min_voltage)

        self.max_current = QDoubleSpinBox()
        self.max_current.setRange(1e-6, i_max)
        self.max_current.setDecimals(6)
        self.max_current.setValue(self.limits.max_current)
        self.max_current.setSuffix(" A")
        FormRow(form, "Max current", self.max_current)

        self.min_current = QDoubleSpinBox()
        self.min_current.setRange(-i_max, 0)
        self.min_current.setDecimals(6)
        self.min_current.setValue(self.limits.min_current)
        self.min_current.setSuffix(" A")
        FormRow(form, "Min current", self.min_current)

        self.power_limit = QDoubleSpinBox()
        self.power_limit.setRange(0.01, p_max)
        self.power_limit.setValue(self.limits.power_limit)
        self.power_limit.setSuffix(" W")
        FormRow(form, "Max power", self.power_limit)

        for box in (self.max_voltage, self.min_voltage, self.max_current,
                    self.min_current, self.power_limit):
            box.setMinimumWidth(FIELD_WIDTH)
        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)
        btn_layout.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        ok_btn = theme.set_role(QPushButton("Apply"), "primary")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)

        layout.addLayout(btn_layout)

    def get_limits(self):
        limits = SMU.default_limits(self.model)
        limits.max_voltage = self.max_voltage.value()
        limits.min_voltage = self.min_voltage.value()
        limits.max_current = self.max_current.value()
        limits.min_current = self.min_current.value()
        limits.power_limit = self.power_limit.value()
        return limits


class LicenseDialog(QDialog):
    """License agreement dialog shown on first run"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{__app_name__} \u2013 license agreement")
        self.setMinimumSize(600, 500)
        self.setModal(True)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        layout.addWidget(theme.set_role(QLabel("Read and accept the license to continue."), "muted"))

        license_text = QTextEdit()
        license_text.setReadOnly(True)
        license_text.setFont(theme.numeric_font(11))
        license_text.setPlainText(self._get_license_text())
        layout.addWidget(license_text)

        self.accept_check = QCheckBox("I have read and agree to the license terms")
        layout.addWidget(self.accept_check)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)
        btn_layout.addStretch()
        decline_btn = QPushButton("Decline")
        decline_btn.clicked.connect(self.reject)
        btn_layout.addWidget(decline_btn)

        self.accept_btn = theme.set_role(QPushButton("Accept"), "primary")
        self.accept_btn.setEnabled(False)
        self.accept_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.accept_btn)

        layout.addLayout(btn_layout)

        self.accept_check.toggled.connect(self.accept_btn.setEnabled)

    def _get_license_text(self):
        return f"""{__app_name__}
SOFTWARE LICENSE AGREEMENT

Copyright (c) 2026 {__author__}, {__organization__}
All Rights Reserved.

IMPORTANT - READ CAREFULLY: This End-User License Agreement ("EULA") is a legal
agreement between you ("User") and {__author__} / {__organization__} ("Author") for the use of
{__app_name__} software ("Software").

By installing, copying, or otherwise using this Software, you agree to be bound
by the terms of this Agreement. If you do not agree to the terms of this Agreement,
do not install or use the Software.

1. GRANT OF LICENSE
The Author grants you a non-exclusive, non-transferable license to use this Software
for personal, educational, and research purposes.

2. RESTRICTIONS
You may NOT:
- Distribute, sell, lease, or rent the Software without written permission
- Modify, reverse engineer, decompile, or disassemble the Software
- Remove any proprietary notices or labels on the Software
- Use the Software for commercial purposes without a commercial license

3. INTELLECTUAL PROPERTY
The Software is protected by copyright laws. The Author retains all intellectual
property rights in the Software.

4. DISCLAIMER OF WARRANTIES
THE SOFTWARE IS PROVIDED "AS IS" WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED.

5. LIMITATION OF LIABILITY
IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY.

6. SAFETY WARNING
This software controls laboratory equipment capable of generating hazardous voltages
and currents. Users must have proper training in electrical safety.

By using {__app_name__}, you acknowledge that you have read this Agreement,
understand it, and agree to be bound by its terms and conditions."""


_WAVE_UNIT_MULT = {
    "sec": 1.0, "min": 60.0, "hour": 3600.0, "ms": 1e-3, "μs": 1e-6,
    "Ω": 1.0, "kΩ": 1e3, "MΩ": 1e6, "GΩ": 1e9,
    "W": 1.0, "mW": 1e-3, "µW": 1e-6,
    "V": 1.0, "mV": 1e-3,
    "A": 1.0, "mA": 1e-3, "µA": 1e-6, "nA": 1e-9,
}


class WaveToolDialog(QDialog):
    """Custom Signal Design Tool - Creates multi-segment waveforms for I-V sweeps"""

    def __init__(self, parent=None, get_resistance_fn=None):
        super().__init__(parent)
        self.setWindowTitle("Design waveform")
        self.setMinimumSize(900, 640)
        self.resize(1080, 800)
        self.waveform_values = []
        self.time_values = []
        self.segments = []
        self._current_segment_index = -1
        self._get_resistance_fn = get_resistance_fn
        self._live_r_timer = QTimer(self)
        self._live_r_timer.setInterval(500)
        self._live_r_timer.timeout.connect(self._pull_live_resistance)
        # The preview follows every edit, after a short pause so typing a
        # number does not recompute on each keystroke.
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(150)
        self._preview_timer.timeout.connect(lambda: self._preview(quiet=True))
        self._setup_ui()

    def _default_segment(self):
        return {
            "wave_type": "Sine", "avg_value": 20.0, "avg_unit": "W",
            "max_value": 30.0, "max_unit": "W", "period": 240.0,
            "period_unit": "sec", "cycles": 5, "step_size": 1.0, "step_unit": "sec",
        }

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # --- Heater and output ---
        global_group = QGroupBox("Heater and output")
        global_form = make_form()
        global_group.setLayout(global_form)

        self.resistance = QDoubleSpinBox()
        self.resistance.setRange(0.1, 1e9)
        self.resistance.setValue(10)
        self.resistance.setDecimals(2)
        self.resistance.setMinimumWidth(FIELD_WIDTH)
        self.res_unit = QComboBox()
        self.res_unit.addItems(["\u03a9", "k\u03a9"])
        self.measure_r_btn = QPushButton("Measure R")
        self.measure_r_btn.setToolTip("Read current R from the multimeter and fill the field")
        self.measure_r_btn.clicked.connect(self._measure_resistance_once)
        self.live_r_check = QCheckBox("Live R")
        self.live_r_check.setToolTip("Continuously update R from the multimeter (must be running)")
        self.live_r_check.toggled.connect(self._toggle_live_resistance)
        FormRow(global_form, "Heater R", _hbox_widget(
            self.resistance, self.res_unit, self.measure_r_btn, self.live_r_check, spacing=6))

        self.design_mode = QComboBox()
        self.design_mode.addItems(["Power (W)", "Voltage (V)", "Current (A)"])
        self.design_mode.setMinimumWidth(FIELD_WIDTH)
        FormRow(global_form, "Design by", self.design_mode)

        self.export_mode = QComboBox()
        self.export_mode.addItems(["Voltage (V)", "Current (A)"])
        self.export_mode.setMinimumWidth(FIELD_WIDTH)
        FormRow(global_form, "Output as", self.export_mode)

        # --- Segments: list on the left at a fixed width, editor on the right ---
        self._segments_splitter = QSplitter(Qt.Horizontal)
        self._segments_splitter.setChildrenCollapsible(False)

        seg_list_panel = QGroupBox("Segments")
        seg_list_panel.setMaximumWidth(340)
        seg_list_layout = QVBoxLayout(seg_list_panel)
        seg_list_layout.setSpacing(6)
        self.segment_list = QListWidget()
        self.segment_list.currentRowChanged.connect(self._on_segment_selected)
        seg_list_layout.addWidget(self.segment_list)

        seg_btn_layout = QHBoxLayout()
        seg_btn_layout.setSpacing(4)
        for text, tooltip, handler in [
            ("Add", "Append a new segment after the current one", self._add_segment),
            ("Copy", "Copy the current segment and insert it after", self._duplicate_segment),
            ("Remove", "Delete the current segment", self._remove_segment),
            ("\u2191", "Move the current segment up", self._move_segment_up),
            ("\u2193", "Move the current segment down", self._move_segment_down),
        ]:
            btn = QPushButton(text)
            btn.setToolTip(tooltip)
            btn.clicked.connect(handler)
            if len(text) == 1:
                btn.setFixedWidth(30)
            seg_btn_layout.addWidget(btn)
        seg_btn_layout.addStretch()
        seg_list_layout.addLayout(seg_btn_layout)
        self._segments_splitter.addWidget(seg_list_panel)

        self.seg_editor_group = QGroupBox("Segment 1")
        seg_form = make_form()

        self.wave_type = QComboBox()
        self.wave_type.addItems(["Sine", "Square", "Triangle", "Sawtooth", "Square-Sine", "Sine-Square"])
        self.wave_type.setMinimumWidth(FIELD_WIDTH)
        self.wave_type.currentTextChanged.connect(self._update_current_segment_label)
        FormRow(seg_form, "Shape", self.wave_type)

        def value_with_unit(box, unit_combo, lo, hi, value, decimals, units):
            box.setRange(lo, hi)
            box.setValue(value)
            box.setDecimals(decimals)
            box.setMinimumWidth(FIELD_WIDTH)
            unit_combo.addItems(units)
            return _hbox_widget(box, unit_combo, spacing=6)

        self.avg_value, self.avg_unit = QDoubleSpinBox(), QComboBox()
        FormRow(seg_form, "Average", value_with_unit(
            self.avg_value, self.avg_unit, -1000, 1000, 20, 4, ["W", "mW", "V", "mV", "A", "mA"]))

        self.max_value, self.max_unit = QDoubleSpinBox(), QComboBox()
        FormRow(seg_form, "Maximum", value_with_unit(
            self.max_value, self.max_unit, -1000, 1000, 30, 4, ["W", "mW", "V", "mV", "A", "mA"]))

        self.period, self.period_unit = QDoubleSpinBox(), QComboBox()
        FormRow(seg_form, "Period", value_with_unit(
            self.period, self.period_unit, 0.001, 100000, 240, 3, ["sec", "min", "hour", "ms"]))

        self.cycles = QSpinBox()
        self.cycles.setRange(1, 1000)
        self.cycles.setValue(5)
        self.cycles.setMinimumWidth(FIELD_WIDTH)
        FormRow(seg_form, "Cycles", self.cycles)

        self.step_size, self.step_unit = QDoubleSpinBox(), QComboBox()
        FormRow(seg_form, "Step (dt)", value_with_unit(
            self.step_size, self.step_unit, 0.0001, 1000, 1, 4, ["sec", "ms", "\u03bcs"]))

        self.seg_editor_group.setLayout(seg_form)
        self._segments_splitter.addWidget(self.seg_editor_group)
        self._segments_splitter.setSizes([260, 700])
        self._segments_splitter.setStretchFactor(0, 0)
        self._segments_splitter.setStretchFactor(1, 1)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(global_group, stretch=0)
        top.addWidget(self._segments_splitter, stretch=1)
        layout.addLayout(top)

        # --- Live preview and what it adds up to ---
        self.preview_graph = pg.PlotWidget()
        theme.style_plot(self.preview_graph)
        self.preview_graph.setLabel('left', 'Output', color=theme.P.text_muted)
        self.preview_graph.setLabel('bottom', 'Time (s)', color=theme.P.text_muted)
        self.preview_graph.setMinimumHeight(200)
        layout.addWidget(self.preview_graph, stretch=1)

        stats = QGridLayout()
        stats.setHorizontalSpacing(22)
        stats.setVerticalSpacing(1)
        self._stat_values = {}
        for col, (key, label) in enumerate([
                ("amplitude", "Amplitude"), ("frequency", "Frequency"), ("duration", "Duration"),
                ("points", "Points"), ("v_peak", "Peak voltage"), ("i_peak", "Peak current"),
                ("p_peak", "Peak power")]):
            stats.addWidget(theme.set_role(QLabel(label), "stat-label"), 0, col)
            value = theme.set_role(QLabel("\u2014"), "stat-value", tone="")
            stats.addWidget(value, 1, col)
            self._stat_values[key] = value
        stats.setColumnStretch(7, 1)
        layout.addLayout(stats)

        self.info_label = theme.set_role(QLabel(""), "danger")
        self.info_label.setWordWrap(True)
        self.info_label.hide()
        layout.addWidget(self.info_label)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)
        export_btn = QPushButton("Export CSV\u2026")
        export_btn.clicked.connect(self._export_csv)
        btn_layout.addWidget(export_btn)
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        generate_btn = QPushButton("Add to sweep list")
        theme.set_role(generate_btn, "primary")
        generate_btn.setDefault(True)
        generate_btn.clicked.connect(self._generate_and_accept)
        btn_layout.addWidget(generate_btn)

        layout.addLayout(btn_layout)

        self._add_segment()

        for signal in (self.resistance.valueChanged, self.res_unit.currentIndexChanged,
                       self.design_mode.currentIndexChanged, self.export_mode.currentIndexChanged,
                       self.wave_type.currentIndexChanged, self.avg_value.valueChanged,
                       self.avg_unit.currentIndexChanged, self.max_value.valueChanged,
                       self.max_unit.currentIndexChanged, self.period.valueChanged,
                       self.period_unit.currentIndexChanged, self.cycles.valueChanged,
                       self.step_size.valueChanged, self.step_unit.currentIndexChanged):
            signal.connect(lambda *_: self._preview_timer.start())
        self._preview(quiet=True)

    # --- Segment management ---

    def _save_current_segment(self):
        if self._current_segment_index < 0 or self._current_segment_index >= len(self.segments):
            return
        seg = self.segments[self._current_segment_index]
        seg["wave_type"] = self.wave_type.currentText()
        seg["avg_value"] = self.avg_value.value()
        seg["avg_unit"] = self.avg_unit.currentText()
        seg["max_value"] = self.max_value.value()
        seg["max_unit"] = self.max_unit.currentText()
        seg["period"] = self.period.value()
        seg["period_unit"] = self.period_unit.currentText()
        seg["cycles"] = self.cycles.value()
        seg["step_size"] = self.step_size.value()
        seg["step_unit"] = self.step_unit.currentText()

    def _load_segment(self, index):
        seg = self.segments[index]
        self.wave_type.setCurrentText(seg["wave_type"])
        self.avg_value.setValue(seg["avg_value"])
        self.avg_unit.setCurrentText(seg["avg_unit"])
        self.max_value.setValue(seg["max_value"])
        self.max_unit.setCurrentText(seg["max_unit"])
        self.period.setValue(seg["period"])
        self.period_unit.setCurrentText(seg["period_unit"])
        self.cycles.setValue(seg["cycles"])
        self.step_size.setValue(seg["step_size"])
        self.step_unit.setCurrentText(seg["step_unit"])
        self.seg_editor_group.setTitle(f"Segment {index + 1}")

    def _on_segment_selected(self, row):
        if row < 0:
            return
        if self._current_segment_index >= 0:
            self._save_current_segment()
        self._current_segment_index = row
        self._load_segment(row)

    def _update_segment_list(self):
        self.segment_list.blockSignals(True)
        self.segment_list.clear()
        for i, seg in enumerate(self.segments):
            self.segment_list.addItem(f"{i+1}. {seg['wave_type']}")
        self.segment_list.blockSignals(False)
        if hasattr(self, "_preview_timer"):
            self._preview_timer.start()

    def _update_current_segment_label(self, text):
        if self._current_segment_index >= 0:
            item = self.segment_list.item(self._current_segment_index)
            if item:
                item.setText(f"{self._current_segment_index + 1}. {text}")

    def _add_segment(self):
        if self._current_segment_index >= 0:
            self._save_current_segment()
        self.segments.append(self._default_segment())
        self._update_segment_list()
        self.segment_list.setCurrentRow(len(self.segments) - 1)

    def _remove_segment(self):
        if len(self.segments) <= 1:
            QMessageBox.warning(self, "Warning", "Must have at least one segment.")
            return
        idx = self._current_segment_index
        self._current_segment_index = -1
        self.segments.pop(idx)
        self._update_segment_list()
        new_idx = min(idx, len(self.segments) - 1)
        self.segment_list.setCurrentRow(new_idx)

    def _move_segment_up(self):
        idx = self._current_segment_index
        if idx <= 0:
            return
        self._save_current_segment()
        self.segments[idx], self.segments[idx-1] = self.segments[idx-1], self.segments[idx]
        self._update_segment_list()
        self._current_segment_index = -1
        self.segment_list.setCurrentRow(idx - 1)

    def _move_segment_down(self):
        idx = self._current_segment_index
        if idx >= len(self.segments) - 1:
            return
        self._save_current_segment()
        self.segments[idx], self.segments[idx+1] = self.segments[idx+1], self.segments[idx]
        self._update_segment_list()
        self._current_segment_index = -1
        self.segment_list.setCurrentRow(idx + 1)

    def _apply_measured_resistance(self, r_ohms: float):
        if self.res_unit.currentText() == "kΩ":
            self.resistance.setValue(r_ohms / 1000.0)
        else:
            self.resistance.setValue(r_ohms)

    def _measure_resistance_once(self):
        if not self._get_resistance_fn:
            QMessageBox.information(self, "Measure R", "No SMU is connected.")
            return
        r = self._get_resistance_fn()
        if r is None or not (1e-6 < abs(r) < 1e12):
            QMessageBox.warning(self, "Measure R",
                                "No valid resistance reading available.\n"
                                "Turn the SMU output ON so current is flowing through the DUT, "
                                "or run the Multimeter tab, then try again.")
            return
        self._apply_measured_resistance(r)

    def _toggle_live_resistance(self, checked: bool):
        self.resistance.setReadOnly(checked)
        if checked:
            if not self._get_resistance_fn:
                QMessageBox.information(self, "Live R", "No SMU is connected.")
                self.live_r_check.setChecked(False)
                return
            self._pull_live_resistance()
            self._live_r_timer.start()
        else:
            self._live_r_timer.stop()

    def _pull_live_resistance(self):
        if not self._get_resistance_fn:
            return
        r = self._get_resistance_fn()
        if r is not None and 1e-6 < abs(r) < 1e12:
            self._apply_measured_resistance(r)

    def _duplicate_segment(self):
        import copy
        self._save_current_segment()
        new_seg = copy.deepcopy(self.segments[self._current_segment_index])
        self.segments.insert(self._current_segment_index + 1, new_seg)
        self._update_segment_list()
        self.segment_list.setCurrentRow(self._current_segment_index + 1)

    # --- Waveform calculation ---

    def _get_unit_multiplier(self, unit: str) -> float:
        return _WAVE_UNIT_MULT.get(unit, 1.0)

    def _calculate_segment_waveform(self, seg, R, mode, export_target):
        period_sec = seg["period"] * self._get_unit_multiplier(seg["period_unit"])
        dt = seg["step_size"] * self._get_unit_multiplier(seg["step_unit"])
        cycles = seg["cycles"]

        avg = seg["avg_value"] * self._get_unit_multiplier(seg["avg_unit"])
        max_val = seg["max_value"] * self._get_unit_multiplier(seg["max_unit"])
        amplitude = max_val - avg

        t = np.arange(0, cycles * period_sec, dt)
        f = 1.0 / period_sec

        wave_type = seg["wave_type"]
        if wave_type == "Sine":
            wave = avg + amplitude * np.sin(2 * np.pi * f * t)
        elif wave_type == "Square":
            wave = avg + amplitude * np.sign(np.sin(2 * np.pi * f * t))
        elif wave_type == "Triangle":
            wave = avg + amplitude * (2 * np.abs(2 * (t * f - np.floor(t * f + 0.5))) - 1)
        elif wave_type == "Sawtooth":
            wave = avg + amplitude * (2 * (t * f - np.floor(t * f + 0.5)))
        elif wave_type == "Square-Sine":
            phase = (t * f) % 1.0
            wave = np.where(phase < 0.5,
                avg + amplitude,
                avg + amplitude * np.cos(np.pi * (phase - 0.5) / 0.5))
        elif wave_type == "Sine-Square":
            phase = (t * f) % 1.0
            wave = np.where(phase < 0.5,
                avg - amplitude * np.cos(np.pi * phase / 0.5),
                avg + amplitude)

        if mode == "Power":
            if export_target == "Voltage":
                final_values = np.sqrt(np.maximum(wave * R, 0))
            else:
                final_values = np.sqrt(np.maximum(wave / R, 0))
        elif mode == "Voltage":
            if export_target == "Voltage":
                final_values = wave
            else:
                final_values = wave / R
        elif mode == "Current":
            if export_target == "Voltage":
                final_values = wave * R
            else:
                final_values = wave

        return t, final_values

    def _calculate_all_segments(self, quiet: bool = False):
        try:
            self._save_current_segment()

            R = self.resistance.value() * self._get_unit_multiplier(self.res_unit.currentText())
            mode = self.design_mode.currentText().split(" ")[0]
            export_target = self.export_mode.currentText().split(" ")[0]

            all_t = []
            all_values = []
            time_offset = 0.0

            for seg in self.segments:
                t, values = self._calculate_segment_waveform(seg, R, mode, export_target)
                all_t.append(t + time_offset)
                all_values.append(values)
                if len(t) > 0:
                    dt = t[1] - t[0] if len(t) > 1 else seg["step_size"] * self._get_unit_multiplier(seg["step_unit"])
                    time_offset = all_t[-1][-1] + dt

            combined_t = np.concatenate(all_t)
            combined_values = np.concatenate(all_values)

            return combined_t, combined_values
        except Exception as e:
            if quiet:
                self.info_label.setText(f"Can't compute this waveform: {e}")
                self.info_label.show()
            else:
                QMessageBox.warning(self, "Error", str(e))
            return None

    def _preview(self, quiet: bool = False):
        result = self._calculate_all_segments(quiet=quiet)
        if not result:
            return
        combined_t, combined_values = result
        self.info_label.hide()
        self.waveform_values = list(combined_values)
        self.time_values = list(combined_t)
        export_unit = "V" if "Voltage" in self.export_mode.currentText() else "A"

        self.preview_graph.clear()
        self.preview_graph.plot(self.time_values, self.waveform_values, pen=theme.pen(theme.P.accent_strong, 1.8))
        self.preview_graph.setLabel('left', f'Output ({export_unit})')

        n_segs = len(self.segments)
        if n_segs > 1:
            time_offset = 0.0
            for i, seg in enumerate(self.segments[:-1]):
                period_sec = seg["period"] * self._get_unit_multiplier(seg["period_unit"])
                seg_duration = seg["cycles"] * period_sec
                time_offset += seg_duration
                boundary_line = pg.InfiniteLine(pos=time_offset, angle=90,
                    pen=theme.pen(theme.P.text_faint, 1, dashed=True))
                self.preview_graph.addItem(boundary_line)

        self._update_stats(np.asarray(combined_t), np.asarray(combined_values), export_unit)

    def _update_stats(self, t, values, export_unit):
        """The figures you check before running: the selected segment's
        amplitude and frequency, the whole waveform's length, and the peak
        voltage, current and power it asks of the heater at this R."""
        idx = max(self._current_segment_index, 0)
        seg = self.segments[idx] if self.segments else self._default_segment()
        m = self._get_unit_multiplier
        design_unit = self.design_mode.currentText().split("(")[-1].rstrip(")")
        amplitude = seg["max_value"] * m(seg["max_unit"]) - seg["avg_value"] * m(seg["avg_unit"])
        period_s = seg["period"] * m(seg["period_unit"])
        R = self.resistance.value() * m(self.res_unit.currentText())

        if len(values):
            if export_unit == "V":
                v, i = values, values / R
            else:
                v, i = values * R, values
            p = np.abs(v * i)
            v_pk, i_pk, p_pk = float(np.max(np.abs(v))), float(np.max(np.abs(i))), float(np.max(p))
            v_max, v_min, i_max, i_min = float(np.max(v)), float(np.min(v)), float(np.max(i)), float(np.min(i))
        else:
            v_pk = i_pk = p_pk = v_max = v_min = i_max = i_min = 0.0
        duration = sum(s["cycles"] * s["period"] * m(s["period_unit"]) for s in self.segments)

        out = self._stat_values
        out["amplitude"].setText(si_format(amplitude, design_unit, 4))
        out["frequency"].setText(si_format(1.0 / period_s, "Hz", 4) if period_s > 0 else "\u2014")
        out["duration"].setText(MainWindow._fmt_duration(duration) if duration >= 1 else f"{duration:.3f} s")
        out["points"].setText(f"{len(values):,}")
        out["v_peak"].setText(si_format(v_pk, "V", 4))
        out["i_peak"].setText(si_format(i_pk, "A", 4))
        out["p_peak"].setText(si_format(p_pk, "W", 4))

        # Against the safety limits the sweep will be checked with anyway —
        # better to see it here than as a refusal at run time.
        limits = getattr(self.parent(), "safety_limits", None)
        problems = {}
        if limits is not None and len(values):
            if v_max > limits.max_voltage or v_min < limits.min_voltage:
                bad = v_max if v_max > limits.max_voltage else v_min
                lim = limits.max_voltage if v_max > limits.max_voltage else limits.min_voltage
                problems["v_peak"] = f"voltage reaches {si_format(bad, 'V', 4)} (limit {si_format(lim, 'V', 4)})"
            if i_max > limits.max_current or i_min < limits.min_current:
                bad = i_max if i_max > limits.max_current else i_min
                lim = limits.max_current if i_max > limits.max_current else limits.min_current
                problems["i_peak"] = f"current reaches {si_format(bad, 'A', 4)} (limit {si_format(lim, 'A', 4)})"
            if p_pk > limits.power_limit:
                problems["p_peak"] = f"power reaches {si_format(p_pk, 'W', 4)} (limit {si_format(limits.power_limit, 'W', 4)})"
        for key in ("v_peak", "i_peak", "p_peak"):
            theme.set_prop(out[key], tone="danger" if key in problems else "")
        if problems:
            self.info_label.setText("Over the safety limits: " + "; ".join(problems.values())
                                    + ". The sweep would stop at the first such point.")
            self.info_label.show()

    def _generate_and_accept(self):
        self._preview()
        if self.waveform_values:
            self.accept()

    def _export_csv(self):
        self._preview()
        if not self.waveform_values:
            return
        file, _ = QFileDialog.getSaveFileName(self, "Export Waveform", "", "CSV Files (*.csv)")
        if file:
            try:
                with open(file, 'w', newline='', encoding='cp1252', errors='replace') as f:
                    writer = csv.writer(f)
                    for v in self.waveform_values:
                        writer.writerow([v])
                QMessageBox.information(self, "Success", f"Exported {len(self.waveform_values)} values to CSV")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def get_waveform_values(self) -> List[float]:
        return self.waveform_values

    def dump_state(self) -> dict:
        """Serialize the dialog's current global settings + segments for persistence."""
        # Make sure the in-flight segment edits are flushed
        if self._current_segment_index >= 0:
            self._save_current_segment()
        return {
            "resistance": self.resistance.value(),
            "res_unit": self.res_unit.currentText(),
            "design_mode": self.design_mode.currentText(),
            "export_mode": self.export_mode.currentText(),
            "segments": [dict(s) for s in self.segments],
            "current_segment_index": self._current_segment_index,
            # If Live R was active when the dialog closed, the sweep should
            # re-derive the value list against the live R reading at run time
            # rather than using the snapshot taken at Generate time.
            "live_r_linked": self.live_r_check.isChecked(),
        }

    def load_state(self, state: dict):
        """Restore a previously-dumped state."""
        if not state:
            return
        if "resistance" in state:
            self.resistance.setValue(state["resistance"])
        if state.get("res_unit"):
            self.res_unit.setCurrentText(state["res_unit"])
        if state.get("design_mode"):
            self.design_mode.setCurrentText(state["design_mode"])
        if state.get("export_mode"):
            self.export_mode.setCurrentText(state["export_mode"])
        segs = state.get("segments")
        if segs:
            self.segments = [dict(s) for s in segs]
            self._current_segment_index = -1
            self._update_segment_list()
            target_idx = state.get("current_segment_index", 0)
            if 0 <= target_idx < len(self.segments):
                self.segment_list.setCurrentRow(target_idx)
            else:
                self.segment_list.setCurrentRow(0)
        if state.get("live_r_linked"):
            # Trigger toggle so the timer also restarts
            self.live_r_check.setChecked(True)

    @staticmethod
    def compute_values_from_config(config: dict, R_override: Optional[float] = None) -> List[float]:
        """Recompute the full value list from a saved dump_state config.

        Used by the main window to re-derive the sweep waveform at sweep-start
        when Live R was linked: the snapshot in sweep_list is stale, so this
        rebuilds it using the current (live) resistance.

        If R_override is None, uses the resistance stored in the config.
        """
        segments = config.get("segments", [])
        if not segments:
            return []
        if R_override is not None:
            R = float(R_override)
        else:
            R = (config.get("resistance", 10.0)
                 * _WAVE_UNIT_MULT.get(config.get("res_unit", "Ω"), 1.0))
        mode = config.get("design_mode", "Power (W)").split(" ")[0]
        export_target = config.get("export_mode", "Voltage (V)").split(" ")[0]

        out: List[float] = []
        for seg in segments:
            period_sec = seg["period"] * _WAVE_UNIT_MULT.get(seg["period_unit"], 1.0)
            dt = seg["step_size"] * _WAVE_UNIT_MULT.get(seg["step_unit"], 1.0)
            cycles = seg["cycles"]
            avg = seg["avg_value"] * _WAVE_UNIT_MULT.get(seg["avg_unit"], 1.0)
            max_val = seg["max_value"] * _WAVE_UNIT_MULT.get(seg["max_unit"], 1.0)
            amplitude = max_val - avg

            t = np.arange(0, cycles * period_sec, dt)
            f = 1.0 / period_sec if period_sec > 0 else 0.0
            wave_type = seg.get("wave_type", "Sine")

            if wave_type == "Sine":
                wave = avg + amplitude * np.sin(2 * np.pi * f * t)
            elif wave_type == "Square":
                wave = avg + amplitude * np.sign(np.sin(2 * np.pi * f * t))
            elif wave_type == "Triangle":
                wave = avg + amplitude * (2 * np.abs(2 * (t * f - np.floor(t * f + 0.5))) - 1)
            elif wave_type == "Sawtooth":
                wave = avg + amplitude * (2 * (t * f - np.floor(t * f + 0.5)))
            elif wave_type == "Square-Sine":
                phase = (t * f) % 1.0
                wave = np.where(phase < 0.5,
                                avg + amplitude,
                                avg + amplitude * np.cos(np.pi * (phase - 0.5) / 0.5))
            elif wave_type == "Sine-Square":
                phase = (t * f) % 1.0
                wave = np.where(phase < 0.5,
                                avg - amplitude * np.cos(np.pi * phase / 0.5),
                                avg + amplitude)
            else:
                wave = np.full_like(t, avg)

            if mode == "Power":
                if export_target == "Voltage":
                    final = np.sqrt(np.maximum(wave * R, 0))
                else:
                    final = np.sqrt(np.maximum(wave / R, 0))
            elif mode == "Voltage":
                final = wave if export_target == "Voltage" else wave / R
            elif mode == "Current":
                final = wave * R if export_target == "Voltage" else wave
            else:
                final = wave

            out.extend(final.tolist())
        return out

    def closeEvent(self, event):
        self._live_r_timer.stop()
        self._preview_timer.stop()
        super().closeEvent(event)


MIN_WINDOW_W, MIN_WINDOW_H = 1100, 680

# Side panels keep their width as the window grows; the workspace takes the rest.
SIDEBAR_MIN_W, SIDEBAR_MAX_W = 210, 280


class MainWindow(QMainWindow):
    """Main application window — Dual-channel 2602B control"""

    measurement_update = Signal(object)

    def __init__(self):
        super().__init__()

        self.smu: Optional[SMU] = None
        # One set of limits per model — see SMU.default_limits. Until something
        # connects, the window shows the first model's defaults.
        self._limits_by_model: Dict[str, object] = {}
        self.model = registry.MODEL_ORDER[0]
        self.safety_limits = SMU.default_limits(self.model)
        self.measurement_data: List[MeasurementPoint] = []
        self.current_channel = "a"
        self.running = False
        self.abort_flag = False

        self.run_number = 0
        self.run_start_datetime = None
        self.auto_save_enabled = True
        self.auto_save_path = os.path.join(os.path.expanduser("~"), "Documents", "K2602B_Data")

        # Experiments: named bundles of settings + sweep list + wave config + notes
        self.experiment_store = ExperimentStore()
        self._current_experiment_name: Optional[str] = None
        self._current_experiment_notes: str = ""
        self._current_wave_config: Optional[dict] = None
        self._suppress_dirty = False

        # Live CSV streaming
        self._live_csv_file = None
        self._live_csv_writer = None
        self._live_csv_path = None

        # Calorimeter LAN reader (Setaram C80 / Drop). Read-only monitor.
        self.calorimeter_reader: Optional[CalorimeterReader] = None
        self.calorimeter_name: Optional[str] = None
        self.calorimeter_host: Optional[str] = None
        self.calorimeter_sniffing: bool = False
        # Latest calorimeter sample, kept fresh by _on_calorimeter_sample.
        # Snapshotted into each MeasurementPoint during a sweep so both live
        # streaming and batch export can include cal columns in the same CSV
        # row as the Keithley reading.
        self._latest_cal_readings: dict = {}
        # Locked at sweep start to the channel keys the connected calorimeter
        # was exposing, so the CSV header layout stays consistent for the
        # whole run even if the calorimeter is disconnected mid-sweep.
        self._sweep_cal_channels: list = []

        self.settings = QSettings(__organization__, __app_name__)

        self.setWindowTitle(__app_name__)
        # A desktop layout: fixed-width side panels, the workspace takes the
        # rest. Below this size things would have to wrap, so they can't get there.
        self.setMinimumSize(MIN_WINDOW_W, MIN_WINDOW_H)
        self.resize(1360, 860)

        if not self._check_license_agreement():
            sys.exit(0)

        self._create_menu()
        self._setup_ui()
        self._setup_signals()

        # Initial toolbar label (Keithley: Disconnected  |  Calorimeter: —)
        self._update_connection_label()

    def _set_channel(self, channel: str):
        """Switch the active channel"""
        self.current_channel = channel
        reader = getattr(self.multimeter_panel, "_reader", None)
        if reader is not None:
            reader.set_channel(channel)
        self.channel_a_btn.set_selected(channel == "a")
        self.channel_b_btn.set_selected(channel == "b")
        self.status.showMessage(f"Active channel: {channel.upper()}")

    def _toggle_output(self, channel: str):
        """Toggle output on/off for a specific channel"""
        if not self.smu or not self.smu.connected:
            QMessageBox.warning(self, "Not Connected", "Please connect to instrument first")
            return

        try:
            if self.smu.output_enabled(channel):
                self.smu.output_off(channel)
                self._update_output_buttons()
            else:
                self.smu.output_on(channel)
                self._update_output_buttons()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _update_output_buttons(self):
        """Output switches reflect the instrument, one per channel it has."""
        channels = self.smu.caps.channels if self.smu else ("a",)
        for ch, btn in (("a", self.output_a_btn), ("b", self.output_b_btn)):
            present = ch in channels
            btn.setVisible(present)
            if not present:
                continue
            live = False
            if self.smu:
                try:
                    live = self.smu.output_enabled(ch)
                except Exception:
                    live = False
            label = f"Output {ch.upper()}" if len(channels) > 1 else "Output"
            btn.setText(f"{label} {'on' if live else 'off'}")
            btn.setEnabled(self.smu is not None)
            theme.set_prop(btn, live="true" if live else "false")

    def _create_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("File")

        export_action = QAction("Export data\u2026", self)
        export_action.triggered.connect(self.export_csv)
        file_menu.addAction(export_action)

        import_action = QAction("Import sweep list\u2026", self)
        import_action.triggered.connect(self._import_sweep_list)
        file_menu.addAction(import_action)

        file_menu.addSeparator()

        save_config = QAction("Save configuration\u2026", self)
        save_config.triggered.connect(self._save_config)
        file_menu.addAction(save_config)

        load_config = QAction("Load configuration\u2026", self)
        load_config.triggered.connect(self._load_config)
        file_menu.addAction(load_config)

        file_menu.addSeparator()

        self.auto_save_action = QAction("Auto-save", self)
        self.auto_save_action.setCheckable(True)
        self.auto_save_action.setChecked(self.auto_save_enabled)
        self.auto_save_action.toggled.connect(self._toggle_auto_save)
        file_menu.addAction(self.auto_save_action)

        auto_save_path_action = QAction("Set auto-save folder\u2026", self)
        auto_save_path_action.triggered.connect(self._set_auto_save_path)
        file_menu.addAction(auto_save_path_action)

        open_save_folder = QAction("Open auto-save folder", self)
        open_save_folder.triggered.connect(self._open_auto_save_folder)
        file_menu.addAction(open_save_folder)

        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        tools_menu = menubar.addMenu("Tools")
        wave_tool_action = QAction("Design waveform\u2026", self)
        wave_tool_action.triggered.connect(self._show_wave_tool)
        tools_menu.addAction(wave_tool_action)

        inst_menu = menubar.addMenu("Instrument")
        connect_action = QAction("Connect\u2026", self)
        connect_action.triggered.connect(self._show_connection_dialog)
        inst_menu.addAction(connect_action)

        disconnect_action = QAction("Disconnect", self)
        disconnect_action.triggered.connect(self._disconnect)
        inst_menu.addAction(disconnect_action)

        inst_menu.addSeparator()

        reset_action = QAction("Reset", self)
        reset_action.triggered.connect(self._reset_instrument)
        inst_menu.addAction(reset_action)

        safety_action = QAction("Safety limits\u2026", self)
        safety_action.triggered.connect(self._show_safety_dialog)
        inst_menu.addAction(safety_action)

        help_menu = menubar.addMenu("Help")
        update_action = QAction("Check for updates\u2026", self)
        update_action.triggered.connect(self._check_for_updates)
        help_menu.addAction(update_action)
        help_menu.addSeparator()
        about_action = QAction("About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar: what is connected on the left, the outputs on the right.
        # The window's own title bar already names the program.
        toolbar_frame = theme.set_role(QFrame(), "toolbar")
        toolbar = QHBoxLayout(toolbar_frame)
        toolbar.setContentsMargins(10, 6, 10, 6)
        toolbar.setSpacing(6)

        connect_btn = QPushButton("Connect\u2026")
        connect_btn.setToolTip("Choose and connect the source meter, and optionally the calorimeter")
        connect_btn.clicked.connect(self._show_connection_dialog)
        toolbar.addWidget(connect_btn)

        # Status as two chips: source meter, calorimeter.
        self.model_label = theme.set_role(QLabel(""), "muted")
        self.smu_pill = theme.set_role(QLabel("No source meter"), "pill")
        self.cal_pill = theme.set_role(QLabel("No calorimeter"), "pill")
        toolbar.addWidget(self.smu_pill)
        toolbar.addWidget(self.cal_pill)
        # Older code paths still set this label; the pills are what is shown.
        self.connection_label = QLabel()
        self.connection_label.hide()

        toolbar.addStretch()

        # Channel selector — only shown on a dual-channel instrument.
        self.channel_selector = QWidget()
        ch_row = QHBoxLayout(self.channel_selector)
        ch_row.setContentsMargins(0, 0, 6, 0)
        ch_row.setSpacing(6)
        ch_row.addWidget(theme.set_role(QLabel("Channel"), "muted"))
        self.channel_a_btn = ToggleButton("A")
        self.channel_a_btn.set_selected(True)
        self.channel_a_btn.clicked.connect(lambda: self._set_channel("a"))
        self.channel_b_btn = ToggleButton("B")
        self.channel_b_btn.clicked.connect(lambda: self._set_channel("b"))
        ch_row.addWidget(theme.segmented(self.channel_a_btn, self.channel_b_btn))
        toolbar.addWidget(self.channel_selector)

        # Per-channel output switches (channel B hidden on single-channel models)
        self.output_a_btn = theme.set_role(QPushButton("Output off"), "output", live="false")
        self.output_a_btn.clicked.connect(lambda: self._toggle_output("a"))
        toolbar.addWidget(self.output_a_btn)

        self.output_b_btn = theme.set_role(QPushButton("Output B off"), "output", live="false")
        self.output_b_btn.clicked.connect(lambda: self._toggle_output("b"))
        toolbar.addWidget(self.output_b_btn)

        layout.addWidget(toolbar_frame)

        # Sweep actions sit beside the tabs, since they belong to the
        # Experiments tab and are hidden on the others.
        sweep_actions = QWidget()
        sa = QHBoxLayout(sweep_actions)
        sa.setContentsMargins(0, 0, 0, 4)
        sa.setSpacing(6)

        self.start_btn = theme.set_role(QPushButton("Start sweep"), "primary")
        self.start_btn.clicked.connect(self.start_sweep)
        sa.addWidget(self.start_btn)

        self.stop_btn = theme.set_role(QPushButton("Stop"), "danger")
        self.stop_btn.clicked.connect(self.stop_sweep)
        self.stop_btn.setEnabled(False)
        sa.addWidget(self.stop_btn)

        self.export_btn = QPushButton("Export CSV\u2026")
        self.export_btn.clicked.connect(self.export_csv)
        sa.addWidget(self.export_btn)

        # Buttons that only make sense on the Experiments tab
        self._sweep_only_widgets = [self.start_btn, self.stop_btn, self.export_btn]

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(0)

        # Main tabs
        tabs = QTabWidget()
        self.main_tabs = tabs
        self._experiments_tab = None   # set below; adding the first tab already fires currentChanged
        tabs.setCornerWidget(sweep_actions, Qt.TopRightCorner)
        tabs.currentChanged.connect(self._on_main_tab_changed)

        # Tab 1: Multimeter (wrapped in a scroll area so it never clips)
        self.multimeter_panel = MultimeterPanel(self)
        mm_scroll = QScrollArea()
        mm_scroll.setWidgetResizable(True)
        mm_scroll.setFrameShape(QFrame.NoFrame)
        mm_scroll.setWidget(self.multimeter_panel)
        tabs.addTab(mm_scroll, "Multimeter")

        # Tab 2: Experiments — saved experiments, settings, sweep values, graph
        sweep_tab = QWidget()
        sweep_outer = QVBoxLayout(sweep_tab)
        sweep_outer.setContentsMargins(8, 8, 8, 8)

        # Horizontal splitter: experiments sidebar (left) | three sub-tabs (right)
        iv_outer_splitter = QSplitter(Qt.Horizontal)

        self.experiments_sidebar = ExperimentsSidebar(self.experiment_store)
        self.experiments_sidebar.setMinimumWidth(SIDEBAR_MIN_W)
        self.experiments_sidebar.setMaximumWidth(SIDEBAR_MAX_W)
        self.experiments_sidebar.experiment_selected.connect(self._load_experiment)
        self.experiments_sidebar.save_requested.connect(self._save_experiment)
        self.experiments_sidebar.rename_requested.connect(self._rename_experiment)
        self.experiments_sidebar.delete_requested.connect(self._delete_experiment)
        self.experiments_sidebar.new_requested.connect(self._new_experiment)
        self.experiments_sidebar.clone_requested.connect(self._clone_experiment)
        self.experiments_sidebar.notes_changed.connect(self._on_notes_changed)
        iv_outer_splitter.addWidget(self.experiments_sidebar)

        # Three sub-tabs inside Experiments: Settings / Sweep values / Graph
        iv_sub_tabs = QTabWidget()

        # --- Sub-tab 1: Settings — two columns, so it fits without scrolling
        settings_panel = QWidget()
        settings_layout = QGridLayout(settings_panel)
        settings_layout.setContentsMargins(0, 8, 0, 0)
        settings_layout.setSpacing(8)

        self.source_settings = SourceSettingsWidget()
        settings_layout.addWidget(self.source_settings, 0, 0)

        self.inst_settings = InstrumentSettingsWidget()
        settings_layout.addWidget(self.inst_settings, 0, 1)

        self.measure_settings = MeasureSettingsWidget()
        settings_layout.addWidget(self.measure_settings, 1, 0)

        self.timing_settings = TimingSettingsWidget()
        settings_layout.addWidget(self.timing_settings, 1, 1)

        settings_layout.setColumnStretch(0, 1)
        settings_layout.setColumnStretch(1, 1)
        settings_layout.setRowStretch(2, 1)

        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QFrame.NoFrame)
        settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        settings_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        settings_scroll.setWidget(settings_panel)
        iv_sub_tabs.addTab(settings_scroll, "Settings")

        # --- Sub-tab 2: Sweep Values ---
        self.sweep_list = SweepListWidget()
        self.sweep_list.wave_generator_requested.connect(self._show_wave_tool)

        sweep_scroll = QScrollArea()
        sweep_scroll.setWidgetResizable(True)
        sweep_scroll.setFrameShape(QFrame.NoFrame)
        sweep_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sweep_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        sweep_scroll.setWidget(self.sweep_list)
        iv_sub_tabs.addTab(sweep_scroll, "Sweep values")

        # --- Sub-tab 3: Graph ---
        graph_tab = QWidget()
        graph_tab_layout = QVBoxLayout(graph_tab)
        graph_tab_layout.setContentsMargins(0, 0, 0, 0)

        axis_bar = QWidget()
        axis_layout = QHBoxLayout(axis_bar)
        axis_layout.setContentsMargins(0, 8, 0, 6)
        axis_layout.setSpacing(6)

        axis_layout.addWidget(theme.set_role(QLabel("X"), "muted"))
        self.x_axis = QComboBox()
        self.x_axis.addItems(["Voltage", "Current", "Time", "Index"])
        axis_layout.addWidget(self.x_axis)
        self.x_unit = QComboBox()
        axis_layout.addWidget(self.x_unit)
        self.x_axis.currentTextChanged.connect(lambda _: self._on_axis_variable_changed("x"))
        self.x_unit.currentTextChanged.connect(self._update_graph_axes)

        axis_layout.addSpacing(8)
        axis_layout.addWidget(theme.set_role(QLabel("Y1 (left)"), "muted"))
        self.y1_axis = QComboBox()
        self.y1_axis.addItems(["Current", "Voltage", "Resistance", "Power", "None"])
        axis_layout.addWidget(self.y1_axis)
        self.y1_unit = QComboBox()
        axis_layout.addWidget(self.y1_unit)
        self.y1_axis.currentTextChanged.connect(lambda _: self._on_axis_variable_changed("y1"))
        self.y1_unit.currentTextChanged.connect(self._update_graph_axes)

        axis_layout.addSpacing(8)
        axis_layout.addWidget(theme.set_role(QLabel("Y2 (right)"), "muted"))
        self.y2_axis = QComboBox()
        self.y2_axis.addItems(["None", "Voltage", "Current", "Resistance", "Power"])
        axis_layout.addWidget(self.y2_axis)
        self.y2_unit = QComboBox()
        axis_layout.addWidget(self.y2_unit)
        self.y2_axis.currentTextChanged.connect(lambda _: self._on_axis_variable_changed("y2"))
        self.y2_unit.currentTextChanged.connect(self._update_graph_axes)

        # Populate unit combos for the initial variable selections
        for which in ("x", "y1", "y2"):
            self._on_axis_variable_changed(which)

        axis_layout.addSpacing(8)
        axis_layout.addWidget(theme.set_role(QLabel("Presets"), "muted"))
        for preset, (x, y1, y2) in [("I-V", ("Voltage", "Current", "None")),
                                     ("I-t", ("Time", "Current", "None")),
                                     ("V,P-t", ("Time", "Voltage", "Power")),
                                     ("I,R-t", ("Time", "Current", "Resistance"))]:
            btn = theme.set_role(QPushButton(preset), "quiet")
            btn.clicked.connect(lambda checked, x=x, y1=y1, y2=y2: self._set_graph_preset(x, y1, y2))
            axis_layout.addWidget(btn)

        axis_layout.addStretch()

        self.live_update_cb = QCheckBox("Live update")
        self.live_update_cb.setChecked(True)
        axis_layout.addWidget(self.live_update_cb)

        graph_tab_layout.addWidget(axis_bar)

        # Graph + table share a vertical splitter so the user can decide the ratio
        graph_table_splitter = QSplitter(Qt.Vertical)

        self.graph = DualAxisGraph()
        self.graph.setMinimumSize(0, 0)
        graph_table_splitter.addWidget(self.graph)

        self.table = DataTableWidget()
        self.table.setMinimumSize(0, 0)
        graph_table_splitter.addWidget(self.table)

        graph_table_splitter.setSizes([500, 260])
        graph_table_splitter.setChildrenCollapsible(False)
        self.graph.setMinimumHeight(160)
        self.table.setMinimumHeight(90)
        graph_tab_layout.addWidget(graph_table_splitter)

        iv_sub_tabs.addTab(graph_tab, "Graph")

        iv_outer_splitter.addWidget(iv_sub_tabs)
        iv_outer_splitter.setSizes([SIDEBAR_MIN_W + 20, 1000])
        iv_outer_splitter.setStretchFactor(0, 0)
        iv_outer_splitter.setStretchFactor(1, 1)
        iv_outer_splitter.setChildrenCollapsible(False)
        sweep_outer.addWidget(iv_outer_splitter)

        self._experiments_tab = sweep_tab
        tabs.addTab(sweep_tab, "Experiments")

        # Tab 3: Real Time — unified live view of calorimeter (HF, T) and any
        # running K2602B sweep (V, I, R, P). Connection is managed from the
        # Connect dialog; this tab is display-only.
        from realtime_tab import RealTimeTab
        self.realtime_tab = RealTimeTab(self)
        tabs.addTab(self.realtime_tab, "Real Time")

        content_layout.addWidget(tabs)
        layout.addWidget(content, stretch=1)

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)

        # Real Time signal values on the LEFT side of the status bar.
        # `insertPermanentWidget(0, …)` puts it at the leftmost position
        # within the permanent-widget area, so it stays visible even when
        # showMessage() fires and lines up to the left of the progress
        # widgets that get added below.
        if hasattr(self, "realtime_tab") and self.realtime_tab is not None:
            self.status.insertPermanentWidget(
                0, self.realtime_tab.create_status_values_widget()
            )

        self.progress_label = QLabel("")
        theme.set_role(self.progress_label, "faint")
        self.status.addPermanentWidget(self.progress_label)

        self.progress = QProgressBar()
        self.progress.setFixedWidth(160)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.status.addPermanentWidget(self.progress)
        self.status.showMessage("Ready")

        self.sweep_start_time = 0
        self.total_sweep_points = 0

    def _setup_signals(self):
        self.measurement_update.connect(self._on_measurement_update)
        self.sweep_list.list_changed.connect(self._on_sweep_list_changed)
        self._wire_dirty_tracking()
        # Initialize tab-specific visibility
        self._on_main_tab_changed(self.main_tabs.currentIndex())

    def _on_main_tab_changed(self, index: int):
        # By widget, not by title: renaming the tab once broke a title check.
        is_sweep_tab = self.main_tabs.widget(index) is self._experiments_tab
        for w in self._sweep_only_widgets:
            w.setVisible(is_sweep_tab)

    def _on_sweep_list_changed(self, count: int):
        if count > 0:
            self.timing_settings.points.setValue(count)
        self._mark_dirty()

    # === Experiments ===

    def _wire_dirty_tracking(self):
        ss = self.source_settings
        ms = self.measure_settings
        ts = self.timing_settings
        slist = self.sweep_list

        def hook(widget, signal_name):
            sig = getattr(widget, signal_name, None)
            if sig is not None:
                sig.connect(self._mark_dirty)

        for cb in [ss.mode, ss.range, ms.measure_range, ms.auto_zero,
                   self.inst_settings.output_off_mode]:
            hook(cb, "currentTextChanged")
        for sb in [ss.compliance, ts.points, ts.repeat, ts.delay, ts.step_size, ts.nplc,
                   slist.start_val, slist.stop_val, slist.num_points]:
            hook(sb, "valueChanged")
        hook(ms.measure_v, "toggled")
        hook(ms.measure_i, "toggled")
        hook(ms.measure_r, "toggled")
        hook(ms.measure_p, "toggled")
        hook(ts.auto_delay_check, "toggled")

    def _mark_dirty(self, *args):
        if self._suppress_dirty:
            return
        self.experiments_sidebar.mark_dirty(True)

    def _capture_state(self) -> dict:
        ss = self.source_settings
        ms = self.measure_settings
        ts = self.timing_settings
        slist = self.sweep_list
        inst = self.inst_settings
        return {
            "source": {
                "function": ss.function,
                "mode": ss.mode.currentText(),
                "compliance": ss.compliance.value(),
            },
            "instrument": {
                "sense": inst.sense,
                "output_off": inst.output_off_mode.currentText(),
            },
            "measure": {
                "v": ms.measure_v.isChecked(),
                "i": ms.measure_i.isChecked(),
                "r": ms.measure_r.isChecked(),
                "p": ms.measure_p.isChecked(),
                "auto_zero": ms.auto_zero.currentText(),
            },
            "timing": {
                "points": ts.points.value(),
                "repeat": ts.repeat.value(),
                "delay": ts.delay.value(),
                "step_size": ts.step_size.value(),
                "auto_delay": ts.auto_delay_check.isChecked(),
                "nplc": ts.nplc.value(),
            },
            "sweep": {
                "values": list(slist.sweep_values),
                "start": slist.start_val.value(),
                "stop": slist.stop_val.value(),
                "num_points": slist.num_points.value(),
            },
            "wave_config": self._current_wave_config,
            "notes": self._current_experiment_notes,
            "channel": self.current_channel,
        }

    def _apply_state(self, exp: dict):
        self._suppress_dirty = True
        try:
            ss = self.source_settings
            ms = self.measure_settings
            ts = self.timing_settings
            slist = self.sweep_list
            inst = self.inst_settings

            src = exp.get("source", {})
            if src.get("function"):
                ss._set_function(src["function"])
            if src.get("mode"):
                ss.mode.setCurrentText(src["mode"])
            if "compliance" in src:
                ss.compliance.setValue(src["compliance"])

            instd = exp.get("instrument", {})
            if instd.get("sense"):
                inst._set_sense(instd["sense"])
                if instd["sense"] == "4-Wire":
                    inst.sense_4w.set_selected(True)
                    inst.sense_2w.set_selected(False)
                else:
                    inst.sense_2w.set_selected(True)
                    inst.sense_4w.set_selected(False)
            if instd.get("output_off"):
                inst.output_off_mode.setCurrentText(instd["output_off"])

            md = exp.get("measure", {})
            ms.measure_v.setChecked(bool(md.get("v", True)))
            ms.measure_i.setChecked(bool(md.get("i", True)))
            ms.measure_r.setChecked(bool(md.get("r", False)))
            ms.measure_p.setChecked(bool(md.get("p", False)))
            if md.get("auto_zero"):
                ms.auto_zero.setCurrentText(md["auto_zero"])

            td = exp.get("timing", {})
            if "points" in td: ts.points.setValue(td["points"])
            if "repeat" in td: ts.repeat.setValue(td["repeat"])
            if "delay" in td: ts.delay.setValue(td["delay"])
            if "step_size" in td: ts.step_size.setValue(td["step_size"])
            if "nplc" in td: ts.nplc.setValue(td["nplc"])
            if "auto_delay" in td: ts.auto_delay_check.setChecked(bool(td["auto_delay"]))

            sd = exp.get("sweep", {})
            if "start" in sd: slist.start_val.setValue(sd["start"])
            if "stop" in sd: slist.stop_val.setValue(sd["stop"])
            if "num_points" in sd: slist.num_points.setValue(sd["num_points"])
            if "values" in sd:
                slist.sweep_values = list(sd["values"])
                slist._update_table()

            self._current_wave_config = exp.get("wave_config")
            # If the dialog already exists in memory, push the config in too.
            if getattr(self, "_wave_dialog", None) is not None and self._current_wave_config:
                self._wave_dialog.load_state(self._current_wave_config)
        finally:
            self._suppress_dirty = False

    def _load_experiment(self, name: str):
        if self.experiments_sidebar.is_dirty():
            reply = QMessageBox.question(self, "Unsaved changes",
                                          "Discard unsaved changes to the current experiment?",
                                          QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                # restore selection
                self.experiments_sidebar.set_current(self._current_experiment_name,
                                                     self._current_experiment_notes)
                return
        exp = self.experiment_store.get(name)
        if not exp:
            return
        self._apply_state(exp)
        self._current_experiment_name = name
        self._current_experiment_notes = exp.get("notes", "")
        self.experiments_sidebar.set_current(name, self._current_experiment_notes)
        self.status.showMessage(f"Loaded experiment: {name}")

    def _save_experiment(self, name: str):
        payload = self._capture_state()
        payload["notes"] = self._current_experiment_notes
        self.experiment_store.save(name, payload)
        self._current_experiment_name = name
        self.experiments_sidebar.refresh()
        self.experiments_sidebar.set_current(name, self._current_experiment_notes)
        self.status.showMessage(f"Saved experiment: {name}")

    def _rename_experiment(self, old: str, new: str):
        self.experiment_store.rename(old, new)
        self._current_experiment_name = new
        self.experiments_sidebar.refresh()
        self.experiments_sidebar.set_current(new, self._current_experiment_notes)
        self.status.showMessage(f"Renamed: {old} → {new}")

    def _delete_experiment(self, name: str):
        self.experiment_store.delete(name)
        if self._current_experiment_name == name:
            self._current_experiment_name = None
            self._current_experiment_notes = ""
        self.experiments_sidebar.refresh()
        self.experiments_sidebar.set_current(self._current_experiment_name,
                                              self._current_experiment_notes)
        self.status.showMessage(f"Deleted experiment: {name}")

    def _new_experiment(self, name: str):
        # Snapshot whatever the UI currently has and save it under the new name,
        # then switch to it so the user can start editing immediately.
        self._current_experiment_notes = ""
        self._save_experiment(name)

    def _clone_experiment(self, source: str, new_name: str):
        # If the source is the currently-loaded experiment, snapshot the LIVE
        # UI — that way any unsaved edits (sweep list, settings, wave config)
        # carry over to the clone. Otherwise pull from the on-disk store and
        # deep-copy so the two records don't share nested dicts (sweep,
        # timing, wave_config all get mutated in place elsewhere).
        if source and source == self._current_experiment_name:
            record = self._capture_state()
            record["notes"] = self._current_experiment_notes
        else:
            stored = self.experiment_store.get(source)
            if stored is None:
                record = self._capture_state()
                record["notes"] = self._current_experiment_notes
            else:
                record = copy.deepcopy(stored)
        # Strip identity fields so save() treats it as a new record
        for k in ("name", "created_at", "modified_at"):
            record.pop(k, None)
        self.experiment_store.save(new_name, record)
        self.experiments_sidebar.refresh()
        # Keep the currently-loaded experiment as-is (do NOT switch to the clone)
        self.experiments_sidebar.set_current(self._current_experiment_name,
                                              self._current_experiment_notes)
        self.status.showMessage(f"Cloned '{source}' → '{new_name}'")

    def _on_notes_changed(self, text: str):
        self._current_experiment_notes = text
        self._mark_dirty()

    def _set_graph_preset(self, x, y1, y2):
        self.x_axis.setCurrentText(x)
        self.y1_axis.setCurrentText(y1)
        self.y2_axis.setCurrentText(y2)

    def _update_graph_axes(self):
        # _on_axis_variable_changed runs during _setup_ui (to populate the
        # initial unit combos), before self.graph has been created.
        if not hasattr(self, "graph"):
            return
        self.graph.set_axes(
            self.x_axis.currentText(),
            self.y1_axis.currentText(),
            self.y2_axis.currentText(),
            x_unit=self.x_unit.currentText(),
            y1_unit=self.y1_unit.currentText(),
            y2_unit=self.y2_unit.currentText(),
        )

    def _on_axis_variable_changed(self, which: str):
        """Repopulate the unit combo for the given axis whenever its
        variable selection changes (e.g., picking 'Power' shows mW/W/µW)."""
        var_combo, unit_combo = {
            "x": (self.x_axis, self.x_unit),
            "y1": (self.y1_axis, self.y1_unit),
            "y2": (self.y2_axis, self.y2_unit),
        }[which]
        variable = var_combo.currentText()
        options = GRAPH_AXIS_UNITS.get(variable, [("", 1.0)])
        unit_combo.blockSignals(True)
        unit_combo.clear()
        unit_combo.addItems([u for u, _ in options])
        unit_combo.setEnabled(len(options) > 1)
        unit_combo.blockSignals(False)
        self._update_graph_axes()

    def _show_connection_dialog(self):
        dialog = ConnectionDialog(self)
        dialog.exec()

    def _disconnect(self):
        self.disconnect_instrument()

    def _forget_instrument_readings(self):
        """The status bar's values and the last sweep's progress belong to the
        instrument that produced them; drop them when it goes."""
        if getattr(self, "realtime_tab", None) is not None:
            self.realtime_tab.clear_status_values(("v", "i", "r", "p"))
        if not self.running:
            self.progress.hide()
            self.progress_label.setText("")

    def disconnect_instrument(self, quiet: bool = False):
        if self.smu:
            try:
                self.smu.disconnect()
            except Exception:
                pass
            self.smu = None
        self._forget_instrument_readings()
        self._update_connection_label()
        self._update_output_buttons()
        if not quiet:
            self.status.showMessage("Disconnected")

    def _apply_capabilities(self, caps):
        """Show exactly the controls the connected model supports."""
        dual = caps.dual_channel
        self.channel_selector.setVisible(dual)
        if not dual and self.current_channel != "a":
            self._set_channel("a")
        self.multimeter_panel.set_capabilities(caps)
        self.multimeter_panel.terminal_box.setVisible(caps.terminal_select)
        self.source_settings.set_capabilities(caps)
        for box in (self.sweep_list.start_val, self.sweep_list.stop_val):
            box.setRange(-caps.max_voltage, caps.max_voltage)
        self.inst_settings.set_capabilities(caps)
        self.measure_settings.auto_zero_row.setVisible(caps.auto_zero)
        if getattr(self, "_caps_model", None) != caps.model:
            # A different instrument: start from what its own window started
            # with. Reconnecting the same model keeps this session's choices.
            self._caps_model = caps.model
            self.multimeter_panel._set_sense("4-Wire" if caps.default_four_wire else "2-Wire")
            mm = self.multimeter_panel
            apply_source_limits(mm.source_value, mm.compliance, mm.source_type.currentText(),
                                reset_compliance=True)
            ss = self.source_settings
            apply_source_limits(None, ss.compliance, ss.function, reset_compliance=True)
        self.model_label.setText(caps.display_name)

    def _reset_instrument(self):
        if self.smu:
            self.smu.reset()
            self._update_output_buttons()
            self.status.showMessage("Instrument reset")

    def _show_safety_dialog(self):
        dialog = SafetyDialog(self, self.safety_limits, model=self.model)
        if dialog.exec() == QDialog.Accepted:
            self.safety_limits = dialog.get_limits()
            self._limits_by_model[self.model] = self.safety_limits
            self.status.showMessage(f"Safety limits updated: \u00b1{self.safety_limits.max_voltage} V, \u00b1{self.safety_limits.max_current} A")

    def _check_license_agreement(self) -> bool:
        license_accepted = self.settings.value("license_accepted", False, type=bool)
        license_version = self.settings.value("license_version", "", type=str)
        if license_accepted and license_version == __version__:
            return True
        dialog = LicenseDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.settings.setValue("license_accepted", True)
            self.settings.setValue("license_version", __version__)
            return True
        return False

    def _check_for_updates(self):
        from updater import check_for_updates
        check_for_updates(__version__, self)

    def _show_about(self):
        about_text = f"""
        <h2>{__app_name__}</h2>
        <p><b>Version:</b> {__version__}</p>
        <p><b>Author:</b> {__author__}</p>
        <p><b>Organization:</b> {__organization__}</p>
        <p>{__copyright__}</p>
        <hr>
        <p>Professional Keithley 2602B Dual-Channel SMU Control and I-V Characterization Software</p>
        <p><b>Features:</b></p>
        <ul>
        <li>Dual independent channels (A & B)</li>
        <li>Live multimeter mode with digital displays</li>
        <li>I-V sweep characterization (Linear, List, Log)</li>
        <li>2-Wire/4-Wire sensing</li>
        <li>Dual Y-axis graphing with presets</li>
        <li>Full safety protection</li>
        <li>Configuration save/load</li>
        </ul>
        <hr>
        <p><small>Built with PySide6 + pyqtgraph | TSP command interface</small></p>
        """
        QMessageBox.about(self, f"About {__app_name__}", about_text)

    def _toggle_auto_save(self, enabled):
        self.auto_save_enabled = enabled
        self.status.showMessage(f"Auto-save {'enabled' if enabled else 'disabled'}")

    def _set_auto_save_path(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Auto-Save Folder", self.auto_save_path)
        if folder:
            self.auto_save_path = folder
            self.status.showMessage(f"Auto-save folder: {folder}")

    def _open_auto_save_folder(self):
        if not os.path.exists(self.auto_save_path):
            os.makedirs(self.auto_save_path, exist_ok=True)
        if sys.platform == 'darwin':
            os.system(f'open "{self.auto_save_path}"')
        elif sys.platform == 'win32':
            os.startfile(self.auto_save_path)
        else:
            os.system(f'xdg-open "{self.auto_save_path}"')

    def _oneshot_resistance(self) -> Optional[float]:
        if not self.smu or not getattr(self.smu, "_connected", False):
            return None
        try:
            ch = self.current_channel
            if not self.smu.output_enabled(ch):
                return None
            v = self.smu.measure_voltage(ch)
            i = self.smu.measure_current(ch)
            if v is None or i is None or abs(i) < 1e-12:
                return None
            return v / i
        except Exception:
            return None

    def _get_live_resistance(self) -> Optional[float]:
        panel = getattr(self, "multimeter_panel", None)
        if panel is not None and getattr(panel, "running", False) and panel.last_resistance is not None:
            return panel.last_resistance
        r = self._oneshot_resistance()
        if r is not None:
            return r
        return panel.last_resistance if panel is not None else None

    def _show_wave_tool(self):
        if getattr(self, "_wave_dialog", None) is None:
            self._wave_dialog = WaveToolDialog(self, get_resistance_fn=self._get_live_resistance)
            # If the loaded experiment carried a wave config, restore it on first open
            if self._current_wave_config:
                self._wave_dialog.load_state(self._current_wave_config)
        dialog = self._wave_dialog
        if dialog.exec() == QDialog.Accepted:
            wave_values = dialog.get_waveform_values()
            if wave_values:
                self.sweep_list.sweep_values = wave_values
                self.sweep_list._update_table()
                self.status.showMessage(f"Imported {len(wave_values)} points from Custom Signal Design")
        # Remember the dialog state so we can persist it with the experiment
        self._current_wave_config = dialog.dump_state()
        self._mark_dirty()

    def _import_sweep_list(self):
        self.sweep_list._import_csv()

    def _save_config(self):
        file, _ = QFileDialog.getSaveFileName(self, "Save Configuration", "", "JSON Files (*.json)")
        if file:
            config = {
                "source": {
                    "function": self.source_settings.function,
                    "mode": self.source_settings.mode.currentText(),
                    "compliance": self.source_settings.compliance.value()
                },
                "instrument": {
                    "sense": self.inst_settings.sense,
                    "output_off": self.inst_settings.output_off_mode.currentText()
                },
                "timing": {
                    "points": self.timing_settings.points.value(),
                    "repeat": self.timing_settings.repeat.value(),
                    "delay": self.timing_settings.delay.value(),
                    "nplc": self.timing_settings.nplc.value()
                },
                "safety": {
                    "max_voltage": self.safety_limits.max_voltage,
                    "min_voltage": self.safety_limits.min_voltage,
                    "max_current": self.safety_limits.max_current,
                    "min_current": self.safety_limits.min_current,
                    "power_limit": self.safety_limits.power_limit
                }
            }
            with open(file, 'w') as f:
                json.dump(config, f, indent=2)
            self.status.showMessage(f"Configuration saved to {file}")

    def _load_config(self):
        file, _ = QFileDialog.getOpenFileName(self, "Load Configuration", "", "JSON Files (*.json)")
        if file:
            with open(file, 'r') as f:
                config = json.load(f)

            if "source" in config:
                self.source_settings._set_function(config["source"].get("function", "Voltage"))
                self.source_settings.mode.setCurrentText(config["source"].get("mode", "List Sweep"))
                self.source_settings.compliance.setValue(
                    config["source"].get("compliance", registry.active().default_current_compliance))

            if "instrument" in config:
                self.inst_settings._set_sense(config["instrument"].get("sense", "2-Wire"))
                self.inst_settings.output_off_mode.setCurrentText(config["instrument"].get("output_off", "Normal"))

            if "timing" in config:
                self.timing_settings.points.setValue(config["timing"].get("points", 51))
                self.timing_settings.repeat.setValue(config["timing"].get("repeat", 1))
                self.timing_settings.delay.setValue(config["timing"].get("delay", 0.05))
                self.timing_settings.nplc.setValue(config["timing"].get("nplc", 1.0))

            if "safety" in config:
                # The file may have been saved with a different instrument
                # connected, so its limits are clamped to this model's hardware.
                loaded = SMU.default_limits(self.model)
                for key in ("max_voltage", "min_voltage", "max_current", "min_current", "power_limit"):
                    if key in config["safety"]:
                        setattr(loaded, key, config["safety"][key])
                self.safety_limits = SMU.clamp_limits(self.model, loaded)
                self._limits_by_model[self.model] = self.safety_limits

            self.status.showMessage(f"Configuration loaded from {file}")

    def connect_instrument(self, model: str, address: Optional[str] = None, *,
                           simulate: bool = False,
                           simulation_resistance: Optional[float] = None,
                           baud_rate: Optional[int] = None):
        """Connect to any supported SMU. ``address`` is a VISA resource, or a
        serial port on the 6430; ignored when simulating."""
        caps = registry.get(model)
        if self.smu is not None:
            self.disconnect_instrument(quiet=True)
        registry.set_active(caps)

        limits = self._limits_by_model.get(model) or SMU.default_limits(model)
        smu = SMU.create(model, simulate=simulate,
                         simulation_resistance=simulation_resistance,
                         safety_limits=limits)
        smu.connect(None if simulate else address, baud_rate=baud_rate)

        self.smu = smu
        self.model = model
        self._forget_instrument_readings()
        self.safety_limits = limits
        self._limits_by_model[model] = limits
        self._smu_sim_resistance = (
            simulation_resistance or caps.default_simulation_resistance
        ) if simulate else None
        self._apply_capabilities(caps)
        self._update_connection_label()
        self._update_output_buttons()
        how = "Simulating" if simulate else "Connected to"
        self.status.showMessage(f"{how} {caps.display_name}")

    # ---- Calorimeter (Setaram C80 / Drop) \u2014 read-only LAN monitor ----

    def connect_calorimeter(self, name: str, host: str, interval_s: float, sniff: bool = False,
                             interface: Optional[str] = None,
                             profile_name: Optional[str] = None):
        """Connect to (or, if sniff=True, passively watch) a Setaram calorimeter.

        Called from ConnectionDialog. Runs a background QThread poller that
        emits (wall_ts, readings_dict); samples are forwarded to the Real
        Time tab and (during a sweep) written to the sidecar calorimeter CSV.

        In sniff mode nothing connects to the instrument — traffic is
        decoded off the wire via packet capture — so Calisto (or whatever
        is actually driving the calorimeter) keeps its one allowed TCP
        client and can run at the same time. `interface` overrides the
        auto-detected capture NIC — pass None to trust the auto-guess,
        which matches by subnet and can pick the wrong adapter.
        """
        if self.calorimeter_reader is not None:
            self.disconnect_calorimeter()

        spec = CALORIMETERS.get(name)
        if spec is None:
            QMessageBox.warning(self, "Unknown calorimeter", name)
            return
        channels = spec["channels"]

        if sniff:
            reader = SniffingCalorimeterReader(
                host=host,
                calorimeter_name=name,
                interface=interface or sniff_interface_for(host),
                profile_name=profile_name,
            )
        else:
            reader = CalorimeterReader(
                host=host,
                channels=channels,
                interval_s=interval_s,
            )
        reader.sample.connect(self._on_calorimeter_sample)
        reader.error.connect(self._on_calorimeter_error)
        if hasattr(reader, "status"):
            reader.status.connect(lambda msg: self.status.showMessage(f"Calorimeter: {msg}"))
        reader.start()
        self.calorimeter_reader = reader
        self.calorimeter_name = name
        self.calorimeter_host = host
        self.calorimeter_sniffing = sniff

        # Tell the Real Time tab which calorimeter channels + Keithley
        # signals are available. Keithley signals are always available.
        if hasattr(self, "realtime_tab") and self.realtime_tab is not None:
            # The reader knows what it will emit — in sniff mode that comes
            # from a user-editable profile, so it cannot be assumed here.
            cal_signals = reader.signal_specs()
            set_cal_column_labels(cal_signals)
            self.realtime_tab.set_calorimeter_signals(cal_signals)
            available = [s.key for s in cal_signals] + ["v", "i", "r", "p"]
            self.realtime_tab.set_available_signals(available)
            if not self.running:
                self.realtime_tab.set_reference_now("connect")
        self._update_connection_label()
        self.status.showMessage(f"Calorimeter connected: {name} @ {host}")

    def disconnect_calorimeter(self):
        if self.calorimeter_reader is None:
            return
        try:
            self.calorimeter_reader.stop()
            self.calorimeter_reader.wait(2000)
        except Exception:
            pass
        self.calorimeter_reader = None
        self.calorimeter_name = None
        self.calorimeter_host = None
        self.calorimeter_sniffing = False
        set_cal_column_labels([])
        self._update_connection_label()
        self.status.showMessage("Calorimeter disconnected")

    def _on_calorimeter_sample(self, wall_ts: float, readings: dict):
        if hasattr(self, "realtime_tab") and self.realtime_tab is not None:
            self.realtime_tab.push_calorimeter_sample(wall_ts, readings)
        # Cache the latest reading; _run_sweep snapshots it into each
        # MeasurementPoint so the merged CSV can align cal + Keithley on the
        # same row without needing a sidecar file.
        self._latest_cal_readings = dict(readings)

    def _on_calorimeter_error(self, msg: str):
        self.status.showMessage(f"Calorimeter: {msg}")
        # Clean up the reader so the next connect attempt starts fresh
        self.calorimeter_reader = None
        self.calorimeter_name = None
        self.calorimeter_host = None
        self.calorimeter_sniffing = False
        self._update_connection_label()

    def _update_connection_label(self):
        """Toolbar pills: what source meter is attached, and the calorimeter."""
        if self.smu is None:
            text, tone = "No source meter", ""
        elif self.smu.simulate:
            r = getattr(self, "_smu_sim_resistance", None) or 0
            res = (f"{r:.0f} Ω" if r < 1e3 else f"{r/1e3:.0f} kΩ" if r < 1e6
                   else f"{r/1e6:.0f} MΩ" if r < 1e9 else f"{r/1e9:.0f} GΩ")
            text, tone = f"{self.smu.caps.display_name} (simulated, {res})", "warn"
        else:
            text, tone = f"{self.smu.caps.display_name} connected", "ok"
        self.smu_pill.setText(text)
        theme.set_prop(self.smu_pill, tone=tone)

        if self.calorimeter_reader is None:
            ctext, ctone = "No calorimeter", ""
        else:
            how = "watching" if getattr(self, "calorimeter_sniffing", False) else "connected"
            ctext, ctone = f"{self.calorimeter_name or 'Calorimeter'} {how}", "ok"
        self.cal_pill.setText(ctext)
        theme.set_prop(self.cal_pill, tone=ctone)

    def start_sweep(self):
        if not self.smu:
            QMessageBox.warning(self, "Not Connected", "Please connect to instrument first")
            return

        mode = self.source_settings.mode.currentText()
        ch = self.current_channel

        if mode == "List Sweep":
            # If the list came from a Custom Signal Design with Live R linked,
            # re-derive the values now using the current resistance reading so
            # the sweep reflects R as it actually is at run time (rather than
            # the snapshot taken when the dialog was generated).
            if (self._current_wave_config
                    and self._current_wave_config.get("live_r_linked")):
                r = self._get_live_resistance()
                if r is not None and 1e-6 < abs(r) < 1e12:
                    new_values = WaveToolDialog.compute_values_from_config(
                        self._current_wave_config, r
                    )
                    if new_values:
                        self.sweep_list.sweep_values = new_values
                        self.sweep_list._update_table()
                        self.status.showMessage(
                            f"Wave list re-derived with live R = {r:.2f} Ω"
                        )
                else:
                    QMessageBox.warning(
                        self,
                        "Live R unavailable",
                        "Live R was linked to the Custom Signal Design but no "
                        "valid R reading is available right now.\n\n"
                        "Turn the SMU output ON, or run the Multimeter tab, "
                        "and start the sweep again. Falling back to the "
                        "values already in the sweep list for this run."
                    )
            sweep_values = self.sweep_list.get_values()
            if not sweep_values:
                QMessageBox.warning(self, "No Values", "No sweep values defined. Generate or import a list.")
                return
        elif mode == "Linear Sweep":
            start = self.sweep_list.start_val.value()
            stop = self.sweep_list.stop_val.value()
            points = self.sweep_list.num_points.value()
            sweep_values = list(np.linspace(start, stop, points))
        elif mode == "Log Sweep":
            start = self.sweep_list.start_val.value()
            stop = self.sweep_list.stop_val.value()
            points = self.sweep_list.num_points.value()
            if start <= 0 or stop <= 0:
                QMessageBox.warning(self, "Error", "Log sweep requires positive values")
                return
            sweep_values = list(np.logspace(np.log10(start), np.log10(stop), points))
        else:
            sweep_values = [self.sweep_list.start_val.value()]

        # Safety validation
        function = self.source_settings.function
        compliance = self.source_settings.compliance.value()

        try:
            if function == "Voltage":
                for i, v in enumerate(sweep_values):
                    if not (self.safety_limits.min_voltage <= v <= self.safety_limits.max_voltage):
                        raise ValueError(f"Point {i+1}: Voltage {v}V outside safety limits")
                    if abs(v * compliance) > self.safety_limits.power_limit:
                        raise ValueError(f"Point {i+1}: Power {abs(v*compliance):.1f}W exceeds {self.safety_limits.power_limit}W limit")
            else:
                for i, c in enumerate(sweep_values):
                    if not (self.safety_limits.min_current <= c <= self.safety_limits.max_current):
                        raise ValueError(f"Point {i+1}: Current {c}A outside safety limits")
        except ValueError as e:
            QMessageBox.critical(self, "Safety Error", str(e))
            return

        # Clear previous data
        self.measurement_data.clear()
        self.graph.clear_data()
        self.table.clear_data()

        self.running = True
        self.abort_flag = False
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        total = len(sweep_values) * self.timing_settings.repeat.value()
        self.total_sweep_points = total
        self.sweep_start_time = time.time()

        # Reset Real Time tab's X axis to "seconds since experiment start"
        if hasattr(self, "realtime_tab") and self.realtime_tab is not None:
            self.realtime_tab.set_reference_now("experiment")

        # Lock in the calorimeter channel layout for this run's CSV header.
        # If a calorimeter connects mid-sweep, its samples won't get logged
        # (start with it connected). If it disconnects mid-sweep, remaining
        # rows get empty cal cells (which is fine).
        if self.calorimeter_reader is not None:
            cal_spec = CALORIMETERS.get(self.calorimeter_name, {})
            self._sweep_cal_channels = list(cal_spec.get("channels", {}).keys())
        else:
            self._sweep_cal_channels = []
        self.run_number += 1
        self.run_start_datetime = datetime.now()
        self.progress.setMaximum(total)
        self.progress.setValue(0)
        self.progress.show()
        self.progress_label.setText(f"0 / {total}")

        # Open live CSV file for streaming. Split into three stages so a
        # failure in metadata-row generation doesn't take out the header
        # row and every subsequent data row.
        try:
            save_dir = self._experiment_save_dir()
            os.makedirs(save_dir, exist_ok=True)
            filename = self._generate_filename()
            self._live_csv_path = os.path.join(save_dir, filename)
            self._live_csv_file = open(self._live_csv_path, 'w', newline='', encoding='cp1252', errors='replace')
            self._live_csv_writer = csv.writer(self._live_csv_file)
            self.status.showMessage(f"Saving to: {filename}")
        except Exception as e:
            print(f"Live CSV open error: {e}")
            self.status.showMessage(f"CSV open failed: {e}")
            self._live_csv_file = None
            self._live_csv_writer = None

        if self._live_csv_writer:
            # Metadata rows — best-effort. _build_csv_metadata_rows already
            # catches per-row exceptions internally.
            try:
                for row in self._build_csv_metadata_rows(sweep_values):
                    self._live_csv_writer.writerow(row)
            except Exception as e:
                print(f"CSV metadata write error: {e}")
                self.status.showMessage(f"CSV metadata error: {e}")
                # Emit a marker row so the user sees something happened
                try:
                    self._live_csv_writer.writerow([f"# <metadata truncated: {e}>"])
                except Exception:
                    pass

            # Column header — MUST write so data rows are aligned with columns.
            try:
                self._live_csv_writer.writerow(_sweep_csv_header(self._sweep_cal_channels))
                self._live_csv_file.flush()
            except Exception as e:
                print(f"CSV header write error: {e}")
                self.status.showMessage(f"CSV header error: {e}")
                self._live_csv_file = None
                self._live_csv_writer = None

        thread = threading.Thread(target=self._run_sweep, args=(sweep_values, ch))
        thread.daemon = True
        thread.start()

    def _run_sweep(self, sweep_values: List[float], channel: str):
        # Take exclusive control of the calorimeter socket for the duration
        # of the sweep. During the sweep we drive cal reads synchronously
        # after each Keithley measurement so both share the same timestamp.
        # Resume autonomous polling in the finally block.
        cal_reader = self.calorimeter_reader
        cal_active = cal_reader is not None
        if cal_active:
            try:
                cal_reader.pause_polling()
            except Exception as e:
                print(f"cal pause failed: {e}")

        try:
            function = self.source_settings.function
            compliance = self.source_settings.compliance.value()
            delay = self.timing_settings.delay.value()
            nplc = self.timing_settings.nplc.value()
            repeat = self.timing_settings.repeat.value()
            auto_step = self.timing_settings.auto_delay_check.isChecked()
            step_size = self.timing_settings.step_size.value()

            # Configure source
            if function == "Voltage":
                self.smu.set_source_voltage(sweep_values[0], compliance_current=compliance, channel=channel)
            else:
                self.smu.set_source_current(sweep_values[0], compliance_voltage=compliance, channel=channel)

            # Set NPLC
            self.smu.set_nplc(nplc, channel)

            caps = self.smu.caps
            # 2450: terminals were selected before sense, as its window did.
            if caps.terminal_select:
                self.smu.set_terminal(self.inst_settings.terminal)

            # Apply sense mode
            sense = self.inst_settings.sense
            if sense == "4-Wire":
                self.smu.set_remote_sense(True, channel)
            else:
                self.smu.set_remote_sense(False, channel)

            if caps.high_capacitance:
                self.smu.set_high_capacitance(self.inst_settings.high_cap.isChecked())
            if caps.guard_mode and self.inst_settings.guard_mode.isChecked():
                # Only ever switched ON, exactly as the 6430 window did:
                # unticking the box does not send guard OFF.
                self.smu.set_guard_mode(True)
            if caps.output_off_mode:
                self.smu.set_output_off_mode(self.inst_settings.output_off_mode.currentText())
            if caps.auto_zero:
                az = {"On": "ON", "Off": "OFF", "Once": "ONCE"}
                self.smu.set_auto_zero(az.get(self.measure_settings.auto_zero.currentText(), "ON"))

            self.smu.output_on(channel)
            # Update output buttons from main thread
            self.measurement_update.emit(None)  # Will be handled

            point_num = 0
            start_time = time.time()

            for rep in range(repeat):
                if self.abort_flag:
                    break

                for source_val in sweep_values:
                    if self.abort_flag:
                        break

                    point_num += 1

                    if auto_step:
                        target_offset = (point_num - 1) * step_size
                        wait = target_offset - (time.time() - start_time)
                        if wait > 0:
                            time.sleep(wait)

                    # Set source
                    if function == "Voltage":
                        self.smu.set_voltage(source_val, channel)
                    else:
                        self.smu.set_current(source_val, channel)

                    # Settle the SMU before measuring. Without this the DAC
                    # and any range/auto-zero transients leak into V/I and
                    # produce garbage values (incl. negative R at boundaries).
                    time.sleep(delay)

                    # Simulate NPLC integration time + bus overhead in sim
                    # mode. In auto_step mode the tick alignment already
                    # paces the loop, so we don't double-count it there.
                    if not auto_step and self.smu.simulate:
                        nplc_time = nplc * 0.020
                        overhead = 0.060
                        time.sleep(nplc_time + overhead)

                    elapsed = time.time() - start_time

                    # Measure
                    voltage = None
                    current = None
                    resistance = None
                    power = None

                    # Use the SMU's atomic smua.measure.iv() so V and I come
                    # from a single bus round-trip. Two separate measure
                    # queries occasionally race on the TSP bus and the V
                    # response is re-attributed to the I read, producing
                    # V == I exactly (and bogus R = 1, P = V^2).
                    want_v = self.measure_settings.measure_v.isChecked()
                    want_i = self.measure_settings.measure_i.isChecked()
                    if want_v or want_i:
                        try:
                            result = self.smu.measure_all(channel)
                            if want_v:
                                voltage = result.voltage
                            if want_i:
                                current = result.current
                        except Exception as e:
                            print(f"Measurement error: {e}")

                    if self.measure_settings.measure_r.isChecked() and voltage is not None and current is not None:
                        # Skip R when V or I is at noise-floor level. V/I of
                        # two near-zero-noise values produces garbage spikes
                        # at zero-crossings of sinusoidal sweeps (real bug
                        # observed on both sim and real hardware, e.g. rows
                        # at every waveform trough). Leave R = None → empty
                        # cell in CSV, cleaner for downstream analysis.
                        if abs(current) > self.smu.caps.current_noise_floor and abs(voltage) > 1e-6:
                            resistance = voltage / current

                    if self.measure_settings.measure_p.isChecked() and voltage is not None and current is not None:
                        power = abs(voltage * current)

                    # Drive one calorimeter read right after the Keithley
                    # measurement so both land under the same computer_time
                    # and Elapsed(s). If it fails once we stop trying for the
                    # rest of the run — a broken cal shouldn't kill the sweep.
                    cal_readings: dict = {}
                    if cal_active:
                        try:
                            cal_readings = cal_reader.poll_once()
                        except Exception as e:
                            cal_active = False
                            print(f"cal read failed: {e}")

                    computer_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

                    point = MeasurementPoint(
                        index=point_num,
                        timestamp=elapsed,
                        source_value=source_val,
                        channel=channel,
                        computer_time=computer_time,
                        voltage=voltage,
                        current=current,
                        resistance=resistance,
                        power=power,
                        cal_readings=cal_readings,
                    )
                    self.measurement_data.append(point)

                    self.measurement_update.emit(point)

        except Exception as e:
            print(f"Sweep error: {e}")

        finally:
            self.running = False
            if self.smu:
                self.smu.output_off(channel)
            # Return the socket to the autonomous polling loop so the Real
            # Time tab keeps updating between experiments.
            if cal_reader is not None:
                try:
                    cal_reader.resume_polling()
                except Exception as e:
                    print(f"cal resume failed: {e}")

    def _on_measurement_update(self, point):
        if point is None:
            # Output state update request
            self._update_output_buttons()
            return

        # Feed the Real Time tab. `point.timestamp` is seconds since sweep
        # start; the tab uses wall-clock time, so add self.sweep_start_time.
        # Push cal readings with the SAME wall_ts so both signal families
        # land on identical X positions in the live plot.
        if hasattr(self, "realtime_tab") and self.realtime_tab is not None:
            wall_ts = (self.sweep_start_time or time.time()) + point.timestamp
            self.realtime_tab.push_keithley_sample(
                wall_ts, point.voltage, point.current, point.resistance, point.power
            )
            if point.cal_readings:
                self.realtime_tab.push_calorimeter_sample(wall_ts, point.cal_readings)

        self.table.add_point(point)
        self.graph.add_point(point)

        if self.live_update_cb.isChecked():
            self.graph.update_live()

        self.progress.setValue(point.index)

        elapsed = time.time() - self.sweep_start_time
        elapsed_str = self._fmt_duration(elapsed)
        if point.index > 0 and self.total_sweep_points > point.index:
            time_per_point = elapsed / point.index
            remaining_points = self.total_sweep_points - point.index
            remaining_sec = remaining_points * time_per_point
            eta_str = self._fmt_duration(remaining_sec)
            finish_str = (datetime.now() + timedelta(seconds=remaining_sec)).strftime("%H:%M:%S")
            self.progress_label.setText(
                f"{point.index} / {self.total_sweep_points}  ·  {elapsed_str} elapsed  ·  "
                f"{eta_str} left  ·  finish {finish_str}"
            )
        else:
            self.progress_label.setText(
                f"{point.index} / {self.total_sweep_points}  ·  {elapsed_str} elapsed"
            )

        v_str = f"{point.voltage:.6f}V" if point.voltage else ""
        i_str = f"{point.current:.4e}A" if point.current else ""
        self.status.showMessage(f"Ch {point.channel.upper()} | Point {point.index}: {point.source_value:.4f} \u2192 {v_str} {i_str}")

        # Write row to live CSV (Keithley columns + calorimeter columns
        # snapshotted at sample time — see MeasurementPoint.cal_readings).
        if self._live_csv_writer:
            try:
                self._live_csv_writer.writerow(
                    _sweep_csv_row(point, self._sweep_cal_channels)
                )
                self._live_csv_file.flush()
            except Exception as e:
                print(f"Live CSV write error: {e}")

        if not self.running:
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.graph.update_live()
            self._update_output_buttons()
            total_time = time.time() - self.sweep_start_time
            self.progress.hide()
            self.progress_label.setText(
                f"Done: {self.total_sweep_points} points in {self._fmt_duration(total_time)}"
            )
            self.status.showMessage("Sweep completed")

            # Close live CSV file
            if self._live_csv_file:
                try:
                    self._live_csv_file.close()
                except Exception:
                    pass
                filename = os.path.basename(self._live_csv_path) if self._live_csv_path else "unknown"
                self.status.showMessage(f"Saved: {filename} ({len(self.measurement_data)} points)")
                self._live_csv_file = None
                self._live_csv_writer = None
                self._live_csv_path = None
            elif self.auto_save_enabled and self.measurement_data:
                self._auto_save_csv()

    def stop_sweep(self):
        self.abort_flag = True
        if self.smu:
            self.smu.output_off(self.current_channel)
        self._update_output_buttons()
        self.status.showMessage("Stopping...")

    @staticmethod
    def _fmt_duration(seconds: float) -> str:
        s = max(0, int(seconds))
        h, rem = divmod(s, 3600)
        m, s = divmod(rem, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _build_csv_metadata_rows(self, sweep_values=None) -> List[List[str]]:
        """Build the metadata header rows written at the top of every saved sweep CSV."""
        ss = self.source_settings
        inst = self.inst_settings
        ms = self.measure_settings
        ts = self.timing_settings
        slist = self.sweep_list
        rows: List[List[str]] = []
        rows.append([f"# Run {self.run_number}"])
        if self.run_start_datetime:
            rows.append([f"# Started: {self.run_start_datetime.strftime('%Y-%m-%d %H:%M:%S')}"])
        rows.append([f"# Experiment: {self._current_experiment_name or '(Untitled)'}"])
        # Each optional row goes through _safe(). If a single row's builder
        # throws (missing widget attr, driver query returns junk, etc.), we
        # append an error marker and keep going instead of dropping every
        # row after the failure. Root cause of the "CSV has only 3 metadata
        # rows" bug seen in v3.2.0/v3.3.0.
        def _safe(desc, builder):
            try:
                rows.append([builder()])
            except Exception as e:
                rows.append([f"# {desc}: <ERROR {type(e).__name__}: {e}>"])

        if self._current_experiment_notes:
            _safe("Notes", lambda: f"# Notes: {self._current_experiment_notes.strip().replace(chr(10), ' | ')}")
        try:
            ident = self.smu.get_identification() if self.smu else ""
        except Exception:
            ident = ""
        if ident:
            _safe("Instrument", lambda: f"# Instrument: {ident.strip()}")
        _safe("Mode", lambda: f"# Mode: {'SIMULATION' if (self.smu and getattr(self.smu, 'simulate', False)) else 'HARDWARE'}")
        _safe("Channel", lambda: f"# Channel: {self.current_channel.upper()}")
        _safe("Source", lambda: f"# Source: function={ss.function} mode={ss.mode.currentText()} range={ss.range.currentText()} compliance={ss.compliance.value()}")
        _safe("Sense", lambda: f"# Sense: {inst.sense}  OutputOff: {inst.output_off_mode.currentText()}")
        _safe(
            "Measure",
            lambda: (
                "# Measure: "
                + (",".join(name for name, cb in [("V", ms.measure_v), ("I", ms.measure_i), ("R", ms.measure_r), ("P", ms.measure_p)] if cb.isChecked()) or "-")
                + f"  range={ms.measure_range.currentText()}  auto_zero={ms.auto_zero.currentText()}"
            ),
        )
        _safe("Timing", lambda: f"# Timing: points={ts.points.value()} repeat={ts.repeat.value()} delay={ts.delay.value()}s nplc={ts.nplc.value()} step_size={ts.step_size.value()}s auto_delay={ts.auto_delay_check.isChecked()}")
        if sweep_values is not None and len(sweep_values) > 0:
            _safe(
                "Sweep",
                lambda: f"# Sweep: n={len(sweep_values)} range=[{min(sweep_values):.6g}, {max(sweep_values):.6g}] total_points={self.total_sweep_points}",
            )
        if self.calorimeter_name or self._sweep_cal_channels:
            _safe(
                "Calorimeter",
                lambda: f"# Calorimeter: {self.calorimeter_name or '?'} @ {self.calorimeter_host or '?'}  channels={','.join(self._sweep_cal_channels) if self._sweep_cal_channels else '-'}",
            )
        rows.append([])
        return rows

    def _safe_experiment_token(self) -> str:
        name = self._current_experiment_name or "Untitled"
        # Strip filesystem-hostile chars
        return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)

    def _experiment_save_dir(self) -> str:
        return os.path.join(self.auto_save_path, self._safe_experiment_token())

    def _generate_filename(self) -> str:
        if self.run_start_datetime:
            date_str = self.run_start_datetime.strftime("%Y-%m-%d")
            time_str = self.run_start_datetime.strftime("%H-%M-%S")
        else:
            date_str = datetime.now().strftime("%Y-%m-%d")
            time_str = datetime.now().strftime("%H-%M-%S")
        token = self._safe_experiment_token()
        if self._current_experiment_name:
            return f"{token}_{date_str}_{time_str}.csv"
        return f"Run{self.run_number}_{date_str}_{time_str}.csv"

    def _auto_save_csv(self):
        try:
            save_dir = self._experiment_save_dir()
            os.makedirs(save_dir, exist_ok=True)
            filename = self._generate_filename()
            filepath = os.path.join(save_dir, filename)
            self._write_csv(filepath)
            self.status.showMessage(f"Auto-saved: {filename}")
        except Exception as e:
            print(f"Auto-save error: {e}")
            self.status.showMessage(f"Auto-save failed: {e}")

    def _write_csv(self, filepath: str):
        with open(filepath, 'w', newline='', encoding='cp1252', errors='replace') as f:
            writer = csv.writer(f)
            sweep_values = [p.source_value for p in self.measurement_data] if self.measurement_data else None
            for row in self._build_csv_metadata_rows(sweep_values):
                writer.writerow(row)
            # Cal channels for this file: prefer the layout locked at sweep
            # start; else infer from the first point that has any readings.
            cal_channels = list(self._sweep_cal_channels)
            if not cal_channels:
                for p in self.measurement_data:
                    if p.cal_readings:
                        cal_channels = list(p.cal_readings.keys())
                        break
            writer.writerow(_sweep_csv_header(cal_channels))
            for p in self.measurement_data:
                writer.writerow(_sweep_csv_row(p, cal_channels))

    def export_csv(self):
        if not self.measurement_data:
            QMessageBox.warning(self, "No Data", "No data to export")
            return
        suggested_name = self._generate_filename()
        file, _ = QFileDialog.getSaveFileName(
            self, "Export CSV",
            os.path.join(self.auto_save_path, suggested_name),
            "CSV Files (*.csv)"
        )
        if file:
            try:
                self._write_csv(file)
                self.status.showMessage(f"Exported to {file}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", str(e))

    def closeEvent(self, event):
        self.multimeter_panel.stop_live()
        if self.calorimeter_reader is not None:
            try:
                self.disconnect_calorimeter()
            except Exception:
                pass
        if self.smu:
            try:
                self.smu.all_outputs_off()
            except:
                pass
            self.smu.disconnect()
        event.accept()


# Global stylesheet for dark theme with green/amber accents

def main():
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    theme.apply(app)

    window = MainWindow()
    window.show()

    code = app.exec()
    from ctwa.connect_panel import wait_for_background
    wait_for_background()
    sys.exit(code)


if __name__ == "__main__":
    main()
