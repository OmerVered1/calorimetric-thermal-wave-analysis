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

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QTabWidget, QGroupBox, QLabel, QPushButton,
    QComboBox, QLineEdit, QCheckBox, QSpinBox, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QSplitter,
    QFrame, QMessageBox, QFileDialog, QDialog, QListWidget,
    QProgressBar, QStatusBar, QTextEdit, QSizePolicy, QMenuBar,
    QMenu, QAction, QFormLayout, QScrollArea, QAbstractSpinBox,
    QInputDialog
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread, QSettings
from PyQt5.QtGui import QFont, QColor, QPalette, QIcon

import pyqtgraph as pg

from ctwa import theme
from ctwa.connect_panel import SMUConnectPanel
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


class LightPalette(QPalette):
    """Light theme: black text on white surfaces with subtle grays for borders."""
    def __init__(self):
        super().__init__()
        self.setColor(QPalette.Window, QColor(255, 255, 255))          # #ffffff
        self.setColor(QPalette.WindowText, QColor(26, 26, 46))         # #1a1a2e (near-black)
        self.setColor(QPalette.Base, QColor(255, 255, 255))            # #ffffff
        self.setColor(QPalette.AlternateBase, QColor(243, 244, 246))   # #f3f4f6
        self.setColor(QPalette.ToolTipBase, QColor(255, 255, 255))     # #ffffff
        self.setColor(QPalette.ToolTipText, QColor(26, 26, 46))        # #1a1a2e
        self.setColor(QPalette.Text, QColor(26, 26, 46))               # #1a1a2e
        self.setColor(QPalette.Button, QColor(243, 244, 246))          # #f3f4f6
        self.setColor(QPalette.ButtonText, QColor(26, 26, 46))         # #1a1a2e
        self.setColor(QPalette.BrightText, QColor(220, 38, 38))        # #dc2626
        self.setColor(QPalette.Link, QColor(37, 99, 235))              # #2563eb
        self.setColor(QPalette.Highlight, QColor(59, 130, 246))        # #3b82f6
        self.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
        self.setColor(QPalette.Disabled, QPalette.WindowText, QColor(156, 163, 175))  # #9ca3af
        self.setColor(QPalette.Disabled, QPalette.Text, QColor(156, 163, 175))
        self.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(156, 163, 175))


class ToggleButton(QPushButton):
    """Toggle button with selected/unselected state - green accent"""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self._selected = False
        self._update_style()

    def set_selected(self, selected: bool):
        self._selected = selected
        self._update_style()

    def is_selected(self) -> bool:
        return self._selected

    def _update_style(self):
        if self._selected:
            self.setStyleSheet("""
                QPushButton {
                    background-color: #1a1a2e;
                    color: #ffffff;
                    border: none;
                    padding: 6px 16px;
                    font-weight: bold;
                    font-size: 14px;
                    border-radius: 5px;
                }
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background-color: #ffffff;
                    color: #6b7280;
                    border: 1px solid #d1d5db;
                    padding: 6px 16px;
                    font-weight: 500;
                    font-size: 14px;
                    border-radius: 5px;
                }
                QPushButton:hover { background-color: #f3f4f6; color: #1a1a2e; }
            """)


class DigitalDisplay(QLabel):
    """Large digital display for multimeter readings"""

    def __init__(self, unit: str = "", decimals: int = 6):
        super().__init__("----")
        self.unit = unit
        self.decimals = decimals
        self.color = "#22c55e"
        self.setStyleSheet("""
            QLabel {
                background-color: transparent;
                color: #22c55e;
                font-family: 'Inter', sans-serif;
                font-size: 28px;
                font-weight: bold;
                padding: 10px 15px;
                border: none;
                qproperty-alignment: AlignRight;
            }
        """)
        self.setMinimumHeight(50)

    def set_value(self, value: float):
        if value is None:
            self.setText("----")
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
        elif abs_val == 0:
            text = f"0.{'0'*self.decimals} {self.unit}"
        else:
            text = f"{value:.{self.decimals}e} {self.unit}"
        self.setText(text)

    def set_color(self, color: str):
        self.color = color
        self.setStyleSheet(f"""
            QLabel {{
                background-color: transparent;
                color: {color};
                font-family: 'Inter', sans-serif;
                font-size: 28px;
                font-weight: bold;
                padding: 10px 15px;
                border: none;
                qproperty-alignment: AlignRight;
            }}
        """)


class MultimeterPanel(QWidget):
    """Live multimeter mode panel with channel support"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.app = parent
        self.running = False
        self.recording = False
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_reading)
        self.reading_count = 0
        self.record_start_time = None
        self.recorded_data = []
        self.last_resistance: Optional[float] = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(20)

        # Title
        title = QLabel("Live Multimeter")
        title.setFont(QFont("Google Sans", 28, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # Channel indicator
        ch_layout = QHBoxLayout()
        ch_layout.addStretch()
        self.channel_indicator = QLabel("Channel A")
        self.channel_indicator.setStyleSheet("color: #1a1a2e; font-size: 18px; font-weight: bold;")
        ch_layout.addWidget(self.channel_indicator)
        ch_layout.addStretch()
        layout.addLayout(ch_layout)

        # Settings row
        settings = QHBoxLayout()

        settings.addWidget(QLabel("Measure:"))
        self.measure_type = QComboBox()
        self.measure_type.addItems(["Voltage", "Current", "Resistance", "All"])
        self.measure_type.setCurrentText("All")
        settings.addWidget(self.measure_type)

        settings.addWidget(QLabel("Source:"))
        self.source_type = QComboBox()
        self.source_type.addItems(["Voltage", "Current"])
        self.source_type.currentTextChanged.connect(self._update_source_units)
        settings.addWidget(self.source_type)

        settings.addWidget(QLabel("Value:"))
        self.source_value = QDoubleSpinBox()
        self.source_value.setRange(-40, 40)
        self.source_value.setDecimals(4)
        self.source_value.setValue(0)
        self.source_value.setSuffix(" V")
        settings.addWidget(self.source_value)

        settings.addWidget(QLabel("Limit:"))
        self.compliance = QDoubleSpinBox()
        self.compliance.setRange(0.001, 3.0)
        self.compliance.setDecimals(4)
        self.compliance.setValue(0.1)
        self.compliance.setSuffix(" A")
        settings.addWidget(self.compliance)

        settings.addWidget(QLabel("V Range:"))
        self.voltage_range = QComboBox()
        settings.addWidget(self.voltage_range)

        settings.addWidget(QLabel("I Range:"))
        self.current_range = QComboBox()
        # Filled from the connected model's capability table; see set_capabilities.
        self.set_capabilities(registry.get(registry.MODEL_ORDER[0]))
        settings.addWidget(self.current_range)

        settings.addStretch()
        layout.addLayout(settings)

        # Instrument settings row
        inst_row = QHBoxLayout()

        inst_row.addWidget(QLabel("Sense:"))
        self.sense_2w = ToggleButton("2-Wire")
        self.sense_2w.set_selected(True)
        self.sense_2w.clicked.connect(lambda: self._set_sense("2-Wire"))
        inst_row.addWidget(self.sense_2w)

        self.sense_4w = ToggleButton("4-Wire")
        self.sense_4w.clicked.connect(lambda: self._set_sense("4-Wire"))
        inst_row.addWidget(self.sense_4w)
        self.sense = "2-Wire"

        inst_row.addStretch()
        layout.addLayout(inst_row)

        # Digital displays
        displays = QGridLayout()

        v_group = QGroupBox("Voltage")
        v_layout = QVBoxLayout(v_group)
        self.voltage_display = DigitalDisplay("V", 6)
        self.voltage_display.set_color("#22c55e")
        v_layout.addWidget(self.voltage_display)
        displays.addWidget(v_group, 0, 0)

        i_group = QGroupBox("Current")
        i_layout = QVBoxLayout(i_group)
        self.current_display = DigitalDisplay("A", 6)
        self.current_display.set_color("#d97706")
        i_layout.addWidget(self.current_display)
        displays.addWidget(i_group, 0, 1)

        r_group = QGroupBox("Resistance")
        r_layout = QVBoxLayout(r_group)
        self.resistance_display = DigitalDisplay("\u03a9", 4)
        self.resistance_display.set_color("#0891b2")
        r_layout.addWidget(self.resistance_display)
        displays.addWidget(r_group, 1, 0)

        p_group = QGroupBox("Power")
        p_layout = QVBoxLayout(p_group)
        self.power_display = DigitalDisplay("W", 6)
        self.power_display.set_color("#c026d3")
        p_layout.addWidget(self.power_display)
        displays.addWidget(p_group, 1, 1)

        layout.addLayout(displays)

        # Rate and stats
        rate_layout = QHBoxLayout()
        rate_layout.addWidget(QLabel("Update Rate:"))
        self.update_rate = QComboBox()
        self.update_rate.addItems(["Slow (1 Hz)", "Medium (5 Hz)", "Fast (10 Hz)", "Max (20 Hz)"])
        self.update_rate.setCurrentIndex(1)
        self.update_rate.currentIndexChanged.connect(self._update_rate_changed)
        rate_layout.addWidget(self.update_rate)

        self.readings_label = QLabel("Readings: 0")
        rate_layout.addWidget(self.readings_label)
        rate_layout.addStretch()
        layout.addLayout(rate_layout)

        # Buttons
        btn_layout = QHBoxLayout()

        self.start_btn = QPushButton("START")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #1a1a2e; color: #ffffff;
                font-family: 'Inter'; font-size: 14px; font-weight: bold;
                padding: 8px 20px; border-radius: 6px; border: none;
            }
            QPushButton:hover { background-color: #374151; }
            QPushButton:disabled { background-color: #e5e7eb; color: #9ca3af; }
        """)
        self.start_btn.clicked.connect(self.start_live)
        btn_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("STOP")
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc2626; color: #ffffff;
                font-family: 'Inter'; font-size: 14px; font-weight: bold;
                padding: 8px 20px; border-radius: 6px; border: none;
            }
            QPushButton:hover { background-color: #b91c1c; }
            QPushButton:disabled { background-color: #e5e7eb; color: #9ca3af; }
        """)
        self.stop_btn.clicked.connect(self.stop_live)
        self.stop_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_btn)

        layout.addLayout(btn_layout)

        # Recording buttons
        record_layout = QHBoxLayout()

        self.record_btn = QPushButton("RECORD")
        self.record_btn.setStyleSheet("""
            QPushButton {
                background-color: #f3f4f6; color: #1a1a2e;
                font-family: 'Inter'; font-size: 14px; font-weight: bold;
                padding: 8px 20px; border-radius: 6px; border: 1px solid #d1d5db;
            }
            QPushButton:hover { background-color: #e5e7eb; }
            QPushButton:disabled { background-color: #f9fafb; color: #9ca3af; border-color: #e5e7eb; }
        """)
        self.record_btn.clicked.connect(self._start_recording)
        self.record_btn.setEnabled(False)
        record_layout.addWidget(self.record_btn)

        self.pause_record_btn = QPushButton("PAUSE")
        self.pause_record_btn.setStyleSheet("""
            QPushButton {
                background-color: #f3f4f6; color: #1a1a2e;
                font-family: 'Inter'; font-size: 14px; font-weight: bold;
                padding: 8px 20px; border-radius: 6px; border: 1px solid #d1d5db;
            }
            QPushButton:hover { background-color: #e5e7eb; }
            QPushButton:disabled { background-color: #f9fafb; color: #9ca3af; border-color: #e5e7eb; }
        """)
        self.pause_record_btn.clicked.connect(self._pause_recording)
        self.pause_record_btn.setEnabled(False)
        record_layout.addWidget(self.pause_record_btn)

        self.save_record_btn = QPushButton("SAVE CSV")
        self.save_record_btn.setStyleSheet("""
            QPushButton {
                background-color: #f3f4f6; color: #1a1a2e;
                font-family: 'Inter'; font-size: 14px; font-weight: bold;
                padding: 8px 20px; border-radius: 6px; border: 1px solid #d1d5db;
            }
            QPushButton:hover { background-color: #e5e7eb; }
            QPushButton:disabled { background-color: #f9fafb; color: #9ca3af; border-color: #e5e7eb; }
        """)
        self.save_record_btn.clicked.connect(self._save_recording)
        self.save_record_btn.setEnabled(False)
        record_layout.addWidget(self.save_record_btn)

        self.record_status = QLabel("Recording: Stopped | Points: 0")
        self.record_status.setStyleSheet("color: #9ca3af;")
        record_layout.addWidget(self.record_status)
        record_layout.addStretch()

        layout.addLayout(record_layout)

        # Recording Graph
        self.record_graph = pg.PlotWidget()
        self.record_graph.setBackground('#ffffff')
        self.record_graph.setLabel('left', 'Value', color='#1a1a2e')
        self.record_graph.setLabel('bottom', 'Time (s)', color='#1a1a2e')
        self.record_graph.setTitle("Recording Graph", color='#1a1a2e', size='14pt')
        self.record_graph.addLegend()
        self.record_graph.showGrid(x=True, y=True, alpha=0.2)
        self.record_graph.setMinimumHeight(200)

        self.voltage_plot = self.record_graph.plot([], [], pen=pg.mkPen('#16a34a', width=2), name='Voltage (V)')
        self.current_plot = self.record_graph.plot([], [], pen=pg.mkPen('#d97706', width=2), name='Current (A)')
        self.power_plot = self.record_graph.plot([], [], pen=pg.mkPen('#c026d3', width=2), name='Power (W)')

        layout.addWidget(self.record_graph)

        layout.addStretch()

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

    def _update_source_units(self, source_type):
        if source_type == "Voltage":
            self.source_value.setSuffix(" V")
            self.source_value.setRange(-40, 40)
            self.compliance.setSuffix(" A")
            self.compliance.setRange(0.001, 3.0)
            self.compliance.setValue(0.1)
        else:
            self.source_value.setSuffix(" A")
            self.source_value.setRange(-3, 3)
            self.compliance.setSuffix(" V")
            self.compliance.setRange(0.1, 40)
            self.compliance.setValue(20)

    def _update_rate_changed(self):
        rates = [1000, 200, 100, 50]
        if self.running:
            self.timer.setInterval(rates[self.update_rate.currentIndex()])

    def _set_sense(self, sense):
        self.sense = sense
        self.sense_2w.set_selected(sense == "2-Wire")
        self.sense_4w.set_selected(sense == "4-Wire")

    def update_channel_display(self):
        """Update channel indicator based on app's current channel"""
        ch = self.app.current_channel.upper()
        self.channel_indicator.setText(f"Channel {ch}")

    def start_live(self):
        if not self.app.smu or not self.app.smu.connected:
            QMessageBox.warning(self, "Not Connected", "Please connect to instrument first")
            return

        try:
            source_val = self.source_value.value()
            compliance = self.compliance.value()
            ch = self.app.current_channel

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

            self.running = True
            self.reading_count = 0
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.record_btn.setEnabled(True)

            rates = [1000, 200, 100, 50]
            self.timer.start(rates[self.update_rate.currentIndex()])

        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def stop_live(self):
        self.timer.stop()
        self.running = False

        if self.app.smu:
            try:
                self.app.smu.output_off(self.app.current_channel)
            except:
                pass

        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

        if self.recording:
            self._pause_recording()
        self.record_btn.setEnabled(False)
        self.save_record_btn.setEnabled(len(self.recorded_data) > 0)

    def _update_reading(self):
        if not self.app.smu:
            return

        try:
            voltage = None
            current = None
            ch = self.app.current_channel
            smu = self.app.smu

            measure = self.measure_type.currentText()

            if measure in ["Voltage", "Resistance", "All"]:
                voltage = smu.measure_voltage(ch)

            if measure in ["Current", "Resistance", "All"]:
                current = smu.measure_current(ch)

            if voltage is not None:
                self.voltage_display.set_value(voltage)
            if current is not None:
                self.current_display.set_value(current)

            resistance = 0
            power = 0
            # Same noise-floor guard as _run_sweep: R is undefined when V or
            # I are at measurement noise level (nV / pA). Power is always
            # fine at V=0 (P=0) so it doesn't need the extra V guard.
            if voltage is not None and current is not None and abs(current) > 1e-9 and abs(voltage) > 1e-6:
                resistance = voltage / current
                power = abs(voltage * current)
                self.resistance_display.set_value(resistance)
                self.power_display.set_value(power)
                self.last_resistance = resistance

            self.reading_count += 1
            self.readings_label.setText(f"Readings: {self.reading_count}")

            if self.recording and self.record_start_time is not None:
                elapsed = time.time() - self.record_start_time
                v = voltage if voltage is not None else 0
                i = current if current is not None else 0
                self.recorded_data.append((elapsed, v, i, resistance, power))
                self._update_record_graph()
                self.record_status.setText(f"Recording: Active | Points: {len(self.recorded_data)}")

        except Exception as e:
            print(f"Measurement error: {e}")

    def _start_recording(self):
        self.recording = True
        self.record_start_time = time.time()
        self.recorded_data = []
        self.record_btn.setEnabled(False)
        self.pause_record_btn.setEnabled(True)
        self.save_record_btn.setEnabled(False)
        self.record_status.setText("Recording: Active | Points: 0")
        self.record_status.setStyleSheet("color: #e83e8c; font-weight: bold;")
        self.voltage_plot.setData([], [])
        self.current_plot.setData([], [])
        self.power_plot.setData([], [])

    def _pause_recording(self):
        self.recording = False
        self.record_btn.setEnabled(True)
        self.pause_record_btn.setEnabled(False)
        self.save_record_btn.setEnabled(len(self.recorded_data) > 0)
        self.record_status.setText(f"Recording: Paused | Points: {len(self.recorded_data)}")
        self.record_status.setStyleSheet("color: #fd7e14;")

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


class SourceSettingsWidget(QGroupBox):
    """Source settings panel — no DC/Pulse for 2602B"""

    def __init__(self, parent=None):
        super().__init__("Source Settings", parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Function: Voltage / Current
        func_layout = QHBoxLayout()
        func_layout.addWidget(QLabel("Function:"))

        self.volt_btn = ToggleButton("Voltage")
        self.volt_btn.set_selected(True)
        self.volt_btn.clicked.connect(lambda: self._set_function("Voltage"))
        func_layout.addWidget(self.volt_btn)

        self.curr_btn = ToggleButton("Current")
        self.curr_btn.clicked.connect(lambda: self._set_function("Current"))
        func_layout.addWidget(self.curr_btn)

        func_layout.addStretch()
        layout.addLayout(func_layout)

        # Mode
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Mode:"))
        self.mode = QComboBox()
        self.mode.addItems(["Linear Sweep", "List Sweep", "Log Sweep"])
        mode_layout.addWidget(self.mode)
        mode_layout.addStretch()
        layout.addLayout(mode_layout)

        # Range
        range_layout = QHBoxLayout()
        range_layout.addWidget(QLabel("Range:"))
        self.range = QComboBox()
        self.range.addItems(["Auto", "100 mV", "1 V", "6 V", "40 V"])
        range_layout.addWidget(self.range)
        range_layout.addStretch()
        layout.addLayout(range_layout)

        # Limit (Compliance)
        limit_layout = QHBoxLayout()
        limit_layout.addWidget(QLabel("Limit:"))
        self.compliance = QDoubleSpinBox()
        self.compliance.setRange(0.001, 3.0)
        self.compliance.setDecimals(4)
        self.compliance.setValue(0.1)
        self.compliance.setSuffix(" A")
        limit_layout.addWidget(self.compliance)
        limit_layout.addStretch()
        layout.addLayout(limit_layout)

        self.function = "Voltage"

    def _set_function(self, func_name):
        self.function = func_name
        self.volt_btn.set_selected(func_name == "Voltage")
        self.curr_btn.set_selected(func_name == "Current")

        if func_name == "Voltage":
            self.compliance.setSuffix(" A")
            self.compliance.setRange(0.001, 3.0)
            self.compliance.setValue(0.1)
            self.range.clear()
            self.range.addItems(["Auto", "100 mV", "1 V", "6 V", "40 V"])
        else:
            self.compliance.setSuffix(" V")
            self.compliance.setRange(0.1, 40)
            self.compliance.setValue(20)
            self.range.clear()
            self.range.addItems(["Auto", "100 nA", "1 \u00b5A", "10 \u00b5A", "100 \u00b5A", "1 mA", "10 mA", "100 mA", "1 A", "3 A"])


class InstrumentSettingsWidget(QGroupBox):
    """Instrument settings: Sense mode (no terminal for 2602B)"""

    def __init__(self, parent=None):
        super().__init__("Instrument Settings", parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Sense: 2-Wire / 4-Wire
        sense_layout = QHBoxLayout()
        sense_layout.addWidget(QLabel("Sense:"))

        self.sense_2w = ToggleButton("2-Wire")
        self.sense_2w.set_selected(True)
        self.sense_2w.clicked.connect(lambda: self._set_sense("2-Wire"))
        sense_layout.addWidget(self.sense_2w)

        self.sense_4w = ToggleButton("4-Wire")
        self.sense_4w.clicked.connect(lambda: self._set_sense("4-Wire"))
        sense_layout.addWidget(self.sense_4w)

        sense_layout.addStretch()
        layout.addLayout(sense_layout)

        # Output Off State
        off_layout = QHBoxLayout()
        off_layout.addWidget(QLabel("Output Off:"))
        self.output_off_mode = QComboBox()
        self.output_off_mode.addItems(["Normal", "Zero", "High-Z"])
        off_layout.addWidget(self.output_off_mode)
        off_layout.addStretch()
        layout.addLayout(off_layout)

        self.sense = "2-Wire"

    def _set_sense(self, sense):
        self.sense = sense
        self.sense_2w.set_selected(sense == "2-Wire")
        self.sense_4w.set_selected(sense == "4-Wire")


class MeasureSettingsWidget(QGroupBox):
    """Measurement settings"""

    def __init__(self, parent=None):
        super().__init__("Measure Settings", parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # What to measure - row 1
        meas_layout1 = QHBoxLayout()
        self.measure_v = QCheckBox("Voltage")
        self.measure_v.setChecked(True)
        meas_layout1.addWidget(self.measure_v)

        self.measure_i = QCheckBox("Current")
        self.measure_i.setChecked(True)
        meas_layout1.addWidget(self.measure_i)

        self.measure_r = QCheckBox("Resistance")
        meas_layout1.addWidget(self.measure_r)

        meas_layout1.addStretch()
        layout.addLayout(meas_layout1)

        # What to measure - row 2
        meas_layout2 = QHBoxLayout()
        self.measure_p = QCheckBox("Power")
        meas_layout2.addWidget(self.measure_p)

        meas_layout2.addStretch()
        layout.addLayout(meas_layout2)

        # Range
        range_layout = QHBoxLayout()
        range_layout.addWidget(QLabel("Range:"))
        self.measure_range = QComboBox()
        self.measure_range.addItems(["Auto", "100 nA", "1 \u00b5A", "10 \u00b5A", "100 \u00b5A", "1 mA", "10 mA", "100 mA", "1 A", "3 A"])
        range_layout.addWidget(self.measure_range)
        range_layout.addStretch()
        layout.addLayout(range_layout)

        # Auto Zero
        az_layout = QHBoxLayout()
        az_layout.addWidget(QLabel("Auto Zero:"))
        self.auto_zero = QComboBox()
        self.auto_zero.addItems(["On", "Off", "Once"])
        az_layout.addWidget(self.auto_zero)
        az_layout.addStretch()
        layout.addLayout(az_layout)


class TimingSettingsWidget(QGroupBox):
    """Timing settings: NPLC, delay, points, repeat"""

    def __init__(self, parent=None):
        super().__init__("Timing Settings", parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QFormLayout(self)

        self.points = QSpinBox()
        self.points.setRange(1, 10000000)
        self.points.setValue(51)
        layout.addRow("Points:", self.points)

        self.repeat = QSpinBox()
        self.repeat.setRange(1, 1000)
        self.repeat.setValue(1)
        layout.addRow("Repeat:", self.repeat)

        delay_row = QHBoxLayout()
        self.delay = QDoubleSpinBox()
        self.delay.setRange(0, 10)
        self.delay.setDecimals(4)
        self.delay.setValue(0.05)
        self.delay.setSuffix(" s")
        delay_row.addWidget(self.delay)
        self.auto_delay_check = QCheckBox("Auto-adjust to step size")
        self.auto_delay_check.setToolTip("When ticked, delay is computed so each point takes Step Size seconds")
        self.auto_delay_check.toggled.connect(self._on_auto_delay_toggled)
        delay_row.addWidget(self.auto_delay_check)
        layout.addRow("Delay:", delay_row)

        self.step_size = QDoubleSpinBox()
        self.step_size.setRange(0.001, 60)
        self.step_size.setDecimals(4)
        self.step_size.setValue(1.0)
        self.step_size.setSuffix(" s")
        self.step_size.setToolTip("Desired time between consecutive sweep points (window + delay)")
        self.step_size.valueChanged.connect(self._recompute_auto_delay)
        layout.addRow("Step Size (dt):", self.step_size)

        self.nplc = QDoubleSpinBox()
        self.nplc.setRange(0.001, 25)
        self.nplc.setDecimals(3)
        self.nplc.setValue(1.0)
        self.nplc.valueChanged.connect(self._update_window)
        layout.addRow("NPLC:", self.nplc)

        self.window_label = QLabel("20 ms")
        layout.addRow("Window:", self.window_label)

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


class ExperimentsSidebar(QGroupBox):
    """Sidebar listing saved experiments with action buttons + notes."""

    experiment_selected = pyqtSignal(str)   # emitted when user picks one from the list
    save_requested = pyqtSignal(str)        # emitted when user wants to save current state under a name
    rename_requested = pyqtSignal(str, str) # (old_name, new_name)
    delete_requested = pyqtSignal(str)
    new_requested = pyqtSignal(str)         # new experiment with this name (saved immediately)
    clone_requested = pyqtSignal(str, str)  # (source_name, new_name)
    notes_changed = pyqtSignal(str)

    def __init__(self, store: ExperimentStore, parent=None):
        super().__init__("Experiments", parent)
        self.store = store
        self._current_name: Optional[str] = None
        self._dirty = False
        self._suppress_select = False
        self._setup_ui()
        self.refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self.current_label = QLabel("(Untitled)")
        self.current_label.setStyleSheet("font-weight: bold; color: #1a1a2e;")
        layout.addWidget(self.current_label)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.list_widget, stretch=1)

        # Action buttons
        btn_grid = QGridLayout()
        btn_grid.setSpacing(4)

        load_btn = QPushButton("Load")
        load_btn.setToolTip("Load the selected experiment (also: double-click an item in the list)")
        load_btn.clicked.connect(self._on_load_clicked)
        btn_grid.addWidget(load_btn, 0, 0)

        new_btn = QPushButton("New")
        new_btn.setToolTip("Create a new experiment in the list (prompts for a name)")
        new_btn.clicked.connect(self._on_new_clicked)
        btn_grid.addWidget(new_btn, 0, 1)

        save_btn = QPushButton("Save")
        save_btn.setToolTip("Save current state to the loaded experiment (or prompt for a name if none)")
        save_btn.clicked.connect(self._on_save_clicked)
        btn_grid.addWidget(save_btn, 1, 0)

        save_as_btn = QPushButton("Save As…")
        save_as_btn.setToolTip("Save current state as a new experiment")
        save_as_btn.clicked.connect(self._on_save_as_clicked)
        btn_grid.addWidget(save_as_btn, 1, 1)

        rename_btn = QPushButton("Rename")
        rename_btn.setToolTip("Rename the loaded experiment (or name an untitled one)")
        rename_btn.clicked.connect(self._on_rename_clicked)
        btn_grid.addWidget(rename_btn, 2, 0)

        clone_btn = QPushButton("Clone")
        clone_btn.setToolTip("Duplicate the selected experiment under a new name")
        clone_btn.clicked.connect(self._on_clone_clicked)
        btn_grid.addWidget(clone_btn, 2, 1)

        delete_btn = QPushButton("Delete")
        delete_btn.setToolTip("Delete the selected experiment (data CSVs are kept)")
        delete_btn.clicked.connect(self._on_delete_clicked)
        btn_grid.addWidget(delete_btn, 3, 0, 1, 2)

        layout.addLayout(btn_grid)

        layout.addWidget(QLabel("Notes:"))
        self.notes = QTextEdit()
        self.notes.setMaximumHeight(120)
        self.notes.setPlaceholderText("Free-text notes for this experiment…")
        self.notes.textChanged.connect(lambda: self.notes_changed.emit(self.notes.toPlainText()))
        layout.addWidget(self.notes)

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
        name = self._current_name or "(Untitled)"
        dot = "● " if self._dirty else ""
        self.current_label.setText(f"{dot}{name}")

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


class SweepListWidget(QGroupBox):
    """Sweep list management with table"""

    list_changed = pyqtSignal(int)
    wave_generator_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Sweep Values", parent)
        self._setup_ui()
        self.sweep_values = []

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["#", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setMaximumHeight(200)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #ffffff;
                color: #1a1a2e;
                gridline-color: #d1d5db;
                font-size: 13px;
                alternate-background-color: #f9fafb;
            }
            QTableWidget::item { color: #1a1a2e; }
            QHeaderView::section {
                background-color: #f3f4f6;
                color: #1a1a2e;
                font-weight: bold;
                font-size: 13px;
                padding: 6px;
                border: 1px solid #d1d5db;
            }
        """)
        layout.addWidget(self.table)

        # Linear sweep settings (form layout so labels stack above values when narrow)
        linear_form = QFormLayout()
        linear_form.setLabelAlignment(Qt.AlignLeft)
        linear_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.start_val = QDoubleSpinBox()
        self.start_val.setRange(-40, 40)
        self.start_val.setDecimals(4)
        self.start_val.setValue(0)
        linear_form.addRow("Start:", self.start_val)

        self.stop_val = QDoubleSpinBox()
        self.stop_val.setRange(-40, 40)
        self.stop_val.setDecimals(4)
        self.stop_val.setValue(5)
        linear_form.addRow("Stop:", self.stop_val)

        self.num_points = QSpinBox()
        self.num_points.setRange(2, 10000)
        self.num_points.setValue(51)
        linear_form.addRow("Points:", self.num_points)

        layout.addLayout(linear_form)

        # Buttons - Row 1: Generate
        btn_layout1 = QHBoxLayout()
        gen_btn = QPushButton("Linear")
        gen_btn.clicked.connect(self._generate_linear)
        btn_layout1.addWidget(gen_btn)

        log_btn = QPushButton("Log")
        log_btn.clicked.connect(self._generate_log)
        btn_layout1.addWidget(log_btn)

        layout.addLayout(btn_layout1)

        # Buttons - Row 2: Import/Export/Clear
        btn_layout2 = QHBoxLayout()
        import_btn = QPushButton("Import")
        import_btn.clicked.connect(self._import_csv)
        btn_layout2.addWidget(import_btn)

        export_btn = QPushButton("Export")
        export_btn.clicked.connect(self._export_csv)
        btn_layout2.addWidget(export_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear)
        btn_layout2.addWidget(clear_btn)

        layout.addLayout(btn_layout2)

        # Custom Signal Design button (fills the column so it never overflows)
        wave_btn = QPushButton("Custom Signal Design")
        wave_btn.setMinimumWidth(0)
        wave_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        wave_btn.setStyleSheet("""
            QPushButton {
                background-color: #17a2b8; color: white;
                font-family: 'Inter'; font-size: 14px;
                font-weight: bold; padding: 8px 10px;
            }
            QPushButton:hover { background-color: #138496; }
        """)
        wave_btn.clicked.connect(self.wave_generator_requested.emit)
        layout.addWidget(wave_btn)

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
        for i, val in enumerate(self.sweep_values):
            self.table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.table.setItem(i, 1, QTableWidgetItem(f"{val:.6f}"))
        self.list_changed.emit(len(self.sweep_values))

    def get_values(self) -> List[float]:
        return self.sweep_values


# Display-unit options per axis variable. Maps unit name -> factor to
# multiply by when converting from base SI (V/A/Ω/W/s) to the chosen
# display unit. Used by the I-V Sweep graph axis-unit dropdowns; table
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

    COLORS = {
        "Voltage": "#16a34a",
        "Current": "#d97706",
        "Resistance": "#0891b2",
        "Power": "#c026d3"
    }

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setBackground('#ffffff')
        self.showGrid(x=True, y=True, alpha=0.3)

        self.data_points: List[MeasurementPoint] = []

        self.setLabel('left', 'Current', units='A', color='#d97706')
        self.setLabel('bottom', 'Voltage', units='V', color='#1a1a2e')

        self.view_box2 = pg.ViewBox()
        self.plotItem.scene().addItem(self.view_box2)
        self.plotItem.getAxis('right').linkToView(self.view_box2)
        self.view_box2.setXLink(self.plotItem)
        self.plotItem.showAxis('right')

        self.curve1 = self.plot([], [], pen=pg.mkPen('#d97706', width=2), name='Y1')
        self.curve2 = pg.PlotDataItem([], [], pen=pg.mkPen('#0891b2', width=2), name='Y2')
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
            self.setLabel('left', y1, units=y1_unit, color=self.COLORS.get(y1, "#fff"))
            self.curve1.setPen(pg.mkPen(self.COLORS.get(y1, "#fff"), width=2))
        if y2 != "None":
            self.plotItem.getAxis('right').setLabel(y2, units=y2_unit, color=self.COLORS.get(y2, "#fff"))
            self.curve2.setPen(pg.mkPen(self.COLORS.get(y2, "#fff"), width=2))
            self.plotItem.showAxis('right')
        else:
            self.plotItem.hideAxis('right')

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


class DataTableWidget(QTableWidget):
    """Data table with Channel column and export capability"""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setColumnCount(8)
        self.setHorizontalHeaderLabels(['#', 'Channel', 'Computer Time', 'Elapsed (s)', 'Voltage (V)', 'Current (A)', 'Resistance (\u03a9)', 'Power (mW)'])

        header = self.horizontalHeader()
        for i in range(8):
            header.setSectionResizeMode(i, QHeaderView.Stretch)

        self.setAlternatingRowColors(True)
        self.setStyleSheet("""
            QTableWidget {
                background-color: #ffffff;
                alternate-background-color: #f9fafb;
                color: #1a1a2e;
                gridline-color: #d1d5db;
                font-size: 13px;
            }
            QTableWidget::item { color: #1a1a2e; padding: 4px; }
            QHeaderView::section {
                background-color: #f3f4f6;
                color: #1a1a2e;
                font-weight: bold;
                font-size: 13px;
                padding: 8px 5px;
                border: 1px solid #d1d5db;
            }
        """)

    def add_point(self, point: MeasurementPoint):
        row = self.rowCount()
        self.insertRow(row)

        self.setItem(row, 0, QTableWidgetItem(str(point.index)))
        self.setItem(row, 1, QTableWidgetItem(point.channel.upper()))
        self.setItem(row, 2, QTableWidgetItem(point.computer_time))
        self.setItem(row, 3, QTableWidgetItem(f"{point.timestamp:.3f}"))
        self.setItem(row, 4, QTableWidgetItem(f"{point.voltage:.9e}" if point.voltage else ""))
        self.setItem(row, 5, QTableWidgetItem(f"{point.current:.9e}" if point.current else ""))
        self.setItem(row, 6, QTableWidgetItem(f"{point.resistance:.4e}" if point.resistance and abs(point.resistance) < 1e12 else ""))
        self.setItem(row, 7, QTableWidgetItem(f"{point.power*1000:.6e}" if point.power else ""))

        self.scrollToBottom()

    def clear_data(self):
        self.setRowCount(0)


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
        self.setMinimumSize(640, 600)
        self._setup_ui()
        self._refresh_calorimeter_status()

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 18)
        outer.setSpacing(4)
        outer.addWidget(theme.set_role(QLabel("Connect"), "title"))
        outer.addWidget(theme.set_role(QLabel(
            "Choose your source meter and how it is attached. The calorimeter is optional."),
            "muted"))

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, stretch=1)

        # ---- Source meter tab ---------------------------------------------
        smu_page = QWidget()
        smu_layout = QVBoxLayout(smu_page)
        smu_layout.setContentsMargins(2, 12, 2, 2)
        settings = getattr(self.app, "settings", None)
        self.smu_panel = SMUConnectPanel(settings=settings)
        self.smu_panel.connect_requested.connect(self._on_smu_connect)
        smu_layout.addWidget(self.smu_panel)
        self.tabs.addTab(smu_page, "Source meter")

        # ---- Calorimeter tab ----------------------------------------------
        cal_page = QWidget()
        layout = QVBoxLayout(cal_page)   # the calorimeter code below adds to `layout`
        layout.setContentsMargins(2, 12, 2, 2)
        self.tabs.addTab(cal_page, "Calorimeter")

        cal_group = QGroupBox("Calorimeter (read-only monitor)")
        cal_layout = QVBoxLayout(cal_group)

        cal_setup_row = QHBoxLayout()
        cal_setup_row.addWidget(QLabel("Setup:"))
        self.cal_setup_combo = QComboBox()
        self.cal_setup_combo.setToolTip(
            "A saved setup remembers this instrument's IP, the capture adapter,\n"
            "and the signal profile that says what its replies mean.\n"
            "Build one with New… — it watches the traffic and shows you what it finds."
        )
        self.cal_setup_combo.currentIndexChanged.connect(self._on_cal_setup_selected)
        cal_setup_row.addWidget(self.cal_setup_combo, stretch=1)
        self.cal_setup_new_btn = QPushButton("New…")
        self.cal_setup_new_btn.clicked.connect(lambda: self._on_cal_setup_edit(True))
        cal_setup_row.addWidget(self.cal_setup_new_btn)
        self.cal_setup_edit_btn = QPushButton("Edit…")
        self.cal_setup_edit_btn.clicked.connect(lambda: self._on_cal_setup_edit(False))
        cal_setup_row.addWidget(self.cal_setup_edit_btn)
        self.cal_setup_del_btn = QPushButton("Delete")
        self.cal_setup_del_btn.clicked.connect(self._on_cal_setup_delete)
        cal_setup_row.addWidget(self.cal_setup_del_btn)
        cal_layout.addLayout(cal_setup_row)

        cal_pick_row = QHBoxLayout()
        cal_pick_row.addWidget(QLabel("Instrument:"))
        self.cal_combo = QComboBox()
        for name in CALORIMETERS.keys():
            self.cal_combo.addItem(name)
        cal_pick_row.addWidget(self.cal_combo, stretch=1)
        cal_layout.addLayout(cal_pick_row)

        cal_host_row = QHBoxLayout()
        cal_host_row.addWidget(QLabel("Host:"))
        self.cal_host = QLineEdit()
        self.cal_host.setPlaceholderText("169.254.x.x (click Discover)")
        cal_host_row.addWidget(self.cal_host, stretch=1)
        self.cal_discover_btn = QPushButton("Discover")
        self.cal_discover_btn.setToolTip(
            "Look up the selected calorimeter's IP in the OS ARP cache using its\n"
            "fixed MAC. Requires that Calisto has recently talked to the instrument."
        )
        self.cal_discover_btn.clicked.connect(self._on_calorimeter_discover)
        cal_host_row.addWidget(self.cal_discover_btn)
        cal_layout.addLayout(cal_host_row)

        cal_mode_row = QHBoxLayout()
        self.cal_sniff_check = QCheckBox("Sniff mode (watch traffic — Calisto stays connected)")
        self.cal_sniff_check.setToolTip(
            "Off: connects directly to the instrument (exclusive — Calisto must be closed).\n"
            "On: never connects, just watches the traffic Calisto's own polling generates.\n"
            "Needs Npcap installed and this app run as Administrator."
        )
        self.cal_sniff_check.toggled.connect(self._on_cal_sniff_toggled)
        cal_mode_row.addWidget(self.cal_sniff_check)
        cal_mode_row.addStretch()
        cal_layout.addLayout(cal_mode_row)

        cal_iface_row = QHBoxLayout()
        cal_iface_row.addWidget(QLabel("Capture interface:"))
        self.cal_iface_combo = QComboBox()
        self.cal_iface_combo.addItem("Auto-detect (may guess wrong)", None)
        self.cal_iface_combo.setToolTip(
            "Which network adapter to capture on. Auto-detect matches by subnet and can\n"
            "pick the wrong one (e.g. a Bluetooth adapter) — pick the real NIC by hand if so."
        )
        cal_iface_row.addWidget(self.cal_iface_combo, stretch=1)
        self.cal_iface_refresh_btn = QPushButton("Refresh")
        self.cal_iface_refresh_btn.clicked.connect(self._refresh_cal_interfaces)
        cal_iface_row.addWidget(self.cal_iface_refresh_btn)
        cal_layout.addLayout(cal_iface_row)
        self.cal_iface_combo.setEnabled(False)
        self.cal_iface_refresh_btn.setEnabled(False)
        self._refresh_cal_setups()

        cal_ctrl_row = QHBoxLayout()
        cal_ctrl_row.addWidget(QLabel("Poll (s):"))
        self.cal_interval = QDoubleSpinBox()
        self.cal_interval.setRange(0.5, 60.0)
        self.cal_interval.setValue(1.0)
        self.cal_interval.setSingleStep(0.5)
        self.cal_interval.setDecimals(1)
        cal_ctrl_row.addWidget(self.cal_interval)
        cal_ctrl_row.addSpacing(20)
        self.cal_connect_btn = QPushButton("Connect Calorimeter")
        self.cal_connect_btn.setToolTip(
            "The C80/Drop accepts only one TCP client at a time — close Calisto\n"
            "before connecting. Reopen it afterwards to save data via Calisto.\n"
            "(Tick 'Sniff mode' above to record while Calisto stays connected instead.)"
        )
        self.cal_connect_btn.clicked.connect(self._on_calorimeter_connect_toggle)
        cal_ctrl_row.addWidget(self.cal_connect_btn)
        cal_ctrl_row.addStretch()
        cal_layout.addLayout(cal_ctrl_row)

        self.cal_status_label = QLabel("Not connected")
        self.cal_status_label.setStyleSheet("color: #6b7280; font-size: 13px;")
        cal_layout.addWidget(self.cal_status_label)

        cal_note = QLabel(
            "Read-only monitor. Configure and start experiments in Calisto first."
        )
        cal_note.setStyleSheet("color: #6b7280; font-size: 12px; font-style: italic;")
        cal_layout.addWidget(cal_note)

        layout.addWidget(cal_group)
        layout.addStretch()

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = theme.set_role(QPushButton("Close"), "quiet")
        close_btn.clicked.connect(self.reject)
        close_row.addWidget(close_btn)
        outer.addLayout(close_row)

    # ---- Calorimeter handlers ----

    def _on_calorimeter_discover(self):
        name = self.cal_combo.currentText()
        mac = CALORIMETERS[name]["mac"]
        ip, diag = discover_calorimeter_ip(mac)
        if ip:
            self.cal_host.setText(ip)
            self.cal_status_label.setText(f"Found {name} at {ip}")
            self.cal_status_label.setStyleSheet("color: #16a34a; font-size: 13px;")
        else:
            self.cal_status_label.setText(f"Discover failed: {diag}")
            self.cal_status_label.setStyleSheet("color: #dc2626; font-size: 13px;")

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
        self.cal_setup_combo.addItem("(none — configure by hand below)", None)
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
        if dlg.exec_() and dlg.saved_setup is not None:
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
        self.cal_interval.setEnabled(not checked)
        self.cal_connect_btn.setText(
            "Start Sniffing" if checked else "Connect Calorimeter"
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
                QMessageBox.warning(self, "No Sniff Profile",
                    f"No traffic-decoding profile is bundled for {name}.\n\n"
                    "Use New… beside Setup to build one by watching the traffic.")
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
            self.cal_status_label.setStyleSheet("color: #dc2626; font-size: 13px;")
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
            self.cal_status_label.setStyleSheet("color: #16a34a; font-size: 13px;")
            self.cal_connect_btn.setText(
                "Stop Sniffing" if self.app.calorimeter_sniffing else "Disconnect Calorimeter"
            )
            self.cal_sniff_check.setEnabled(False)
            self.cal_iface_combo.setEnabled(False)
            self.cal_iface_refresh_btn.setEnabled(False)
        else:
            self.cal_sniff_check.setEnabled(True)
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
        self.setWindowTitle("Safety Settings")
        self.setMinimumWidth(400)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        layout.addWidget(theme.set_role(QLabel("Safety limits"), "heading"))
        note = theme.set_role(QLabel(
            f"For the {self.caps.display_name}. Every source command is checked "
            f"against these before it reaches the instrument."), "muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        form = QFormLayout()

        self.max_voltage = QDoubleSpinBox()
        v_max = self.caps.max_voltage
        i_max = self.caps.max_current
        p_max = SMU.default_limits(self.model).power_limit
        self.max_voltage.setRange(0.1, v_max)
        self.max_voltage.setValue(self.limits.max_voltage)
        self.max_voltage.setSuffix(" V")
        form.addRow("Max Voltage:", self.max_voltage)

        self.min_voltage = QDoubleSpinBox()
        self.min_voltage.setRange(-v_max, 0)
        self.min_voltage.setValue(self.limits.min_voltage)
        self.min_voltage.setSuffix(" V")
        form.addRow("Min Voltage:", self.min_voltage)

        self.max_current = QDoubleSpinBox()
        self.max_current.setRange(1e-6, i_max)
        self.max_current.setDecimals(6)
        self.max_current.setValue(self.limits.max_current)
        self.max_current.setSuffix(" A")
        form.addRow("Max Current:", self.max_current)

        self.min_current = QDoubleSpinBox()
        self.min_current.setRange(-i_max, 0)
        self.min_current.setDecimals(6)
        self.min_current.setValue(self.limits.min_current)
        self.min_current.setSuffix(" A")
        form.addRow("Min Current:", self.min_current)

        self.power_limit = QDoubleSpinBox()
        self.power_limit.setRange(0.01, p_max)
        self.power_limit.setValue(self.limits.power_limit)
        self.power_limit.setSuffix(" W")
        form.addRow("Max Power:", self.power_limit)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        ok_btn = theme.set_role(QPushButton("Apply"), "primary")
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

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
        self.setWindowTitle(f"{__app_name__} - License Agreement")
        self.setMinimumSize(600, 500)
        self.setModal(True)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel(f"<h2>{__app_name__}</h2>")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        layout.addWidget(QLabel("Please read and accept the following license agreement:"))

        license_text = QTextEdit()
        license_text.setReadOnly(True)
        license_text.setPlainText(self._get_license_text())
        layout.addWidget(license_text)

        self.accept_check = QCheckBox("I have read and agree to the license terms")
        layout.addWidget(self.accept_check)

        btn_layout = QHBoxLayout()
        self.accept_btn = QPushButton("Accept")
        self.accept_btn.setEnabled(False)
        self.accept_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.accept_btn)

        decline_btn = QPushButton("Decline")
        decline_btn.clicked.connect(self.reject)
        btn_layout.addWidget(decline_btn)

        layout.addLayout(btn_layout)

        self.accept_check.stateChanged.connect(
            lambda state: self.accept_btn.setEnabled(state == Qt.Checked)
        )

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
        self.setWindowTitle("Custom Signal Design")
        self.setMinimumSize(520, 600)
        self.resize(1050, 800)
        self.waveform_values = []
        self.time_values = []
        self.segments = []
        self._current_segment_index = -1
        self._get_resistance_fn = get_resistance_fn
        self._live_r_timer = QTimer(self)
        self._live_r_timer.setInterval(500)
        self._live_r_timer.timeout.connect(self._pull_live_resistance)
        self._setup_ui()

    def _default_segment(self):
        return {
            "wave_type": "Sine", "avg_value": 20.0, "avg_unit": "W",
            "max_value": 30.0, "max_unit": "W", "period": 240.0,
            "period_unit": "sec", "cycles": 5, "step_size": 1.0, "step_unit": "sec",
        }

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel("<h2>Custom Signal Design</h2>")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # --- Global Settings ---
        global_group = QGroupBox("Global Settings")
        global_form = QFormLayout()

        res_layout = QHBoxLayout()
        self.resistance = QDoubleSpinBox()
        self.resistance.setRange(0.1, 1e9)
        self.resistance.setValue(10)
        self.resistance.setDecimals(2)
        res_layout.addWidget(self.resistance)
        self.res_unit = QComboBox()
        self.res_unit.addItems(["\u03a9", "k\u03a9"])
        res_layout.addWidget(self.res_unit)
        self.measure_r_btn = QPushButton("Measure R")
        self.measure_r_btn.setToolTip("Read current R from the multimeter and fill the field")
        self.measure_r_btn.clicked.connect(self._measure_resistance_once)
        res_layout.addWidget(self.measure_r_btn)
        self.live_r_check = QCheckBox("Live R")
        self.live_r_check.setToolTip("Continuously update R from the multimeter (must be running)")
        self.live_r_check.toggled.connect(self._toggle_live_resistance)
        res_layout.addWidget(self.live_r_check)
        global_form.addRow("Resistance (R):", res_layout)

        self.design_mode = QComboBox()
        self.design_mode.addItems(["Power (W)", "Voltage (V)", "Current (A)"])
        global_form.addRow("Design By:", self.design_mode)

        self.export_mode = QComboBox()
        self.export_mode.addItems(["Voltage (V)", "Current (A)"])
        global_form.addRow("Export As:", self.export_mode)

        global_group.setLayout(global_form)
        layout.addWidget(global_group)

        # --- Segments Section (splitter so user can resize; reorients on narrow widths) ---
        self._segments_splitter = QSplitter(Qt.Horizontal)

        seg_list_panel = QWidget()
        seg_list_layout = QVBoxLayout(seg_list_panel)
        seg_list_layout.setContentsMargins(0, 0, 0, 0)
        seg_list_label = QLabel("<b>Segments</b>")
        seg_list_layout.addWidget(seg_list_label)
        self.segment_list = QListWidget()
        self.segment_list.currentRowChanged.connect(self._on_segment_selected)
        seg_list_layout.addWidget(self.segment_list)

        seg_btn_layout = QVBoxLayout()
        seg_btn_layout.setSpacing(4)
        for text, tooltip, handler in [
            ("Add segment", "Append a new segment after the current one", self._add_segment),
            ("Duplicate segment", "Copy the current segment and insert it after", self._duplicate_segment),
            ("Remove segment", "Delete the current segment", self._remove_segment),
            ("Move up", "Swap the current segment with the one above", self._move_segment_up),
            ("Move down", "Swap the current segment with the one below", self._move_segment_down),
        ]:
            btn = QPushButton(text)
            btn.setToolTip(tooltip)
            btn.clicked.connect(handler)
            seg_btn_layout.addWidget(btn)
        seg_list_layout.addLayout(seg_btn_layout)
        self._segments_splitter.addWidget(seg_list_panel)

        self.seg_editor_group = QGroupBox("Segment 1")
        seg_form = QFormLayout()

        self.wave_type = QComboBox()
        self.wave_type.addItems(["Sine", "Square", "Triangle", "Sawtooth", "Square-Sine", "Sine-Square"])
        self.wave_type.currentTextChanged.connect(self._update_current_segment_label)
        seg_form.addRow("Wave Type:", self.wave_type)

        avg_layout = QHBoxLayout()
        self.avg_value = QDoubleSpinBox()
        self.avg_value.setRange(-1000, 1000)
        self.avg_value.setValue(20)
        self.avg_value.setDecimals(4)
        avg_layout.addWidget(self.avg_value)
        self.avg_unit = QComboBox()
        self.avg_unit.addItems(["W", "mW", "V", "mV", "A", "mA"])
        avg_layout.addWidget(self.avg_unit)
        seg_form.addRow("Average Value:", avg_layout)

        max_layout = QHBoxLayout()
        self.max_value = QDoubleSpinBox()
        self.max_value.setRange(-1000, 1000)
        self.max_value.setValue(30)
        self.max_value.setDecimals(4)
        max_layout.addWidget(self.max_value)
        self.max_unit = QComboBox()
        self.max_unit.addItems(["W", "mW", "V", "mV", "A", "mA"])
        max_layout.addWidget(self.max_unit)
        seg_form.addRow("Max Value:", max_layout)

        period_layout = QHBoxLayout()
        self.period = QDoubleSpinBox()
        self.period.setRange(0.001, 100000)
        self.period.setValue(240)
        self.period.setDecimals(3)
        period_layout.addWidget(self.period)
        self.period_unit = QComboBox()
        self.period_unit.addItems(["sec", "min", "hour", "ms"])
        period_layout.addWidget(self.period_unit)
        seg_form.addRow("Period:", period_layout)

        self.cycles = QSpinBox()
        self.cycles.setRange(1, 1000)
        self.cycles.setValue(5)
        seg_form.addRow("Total Cycles:", self.cycles)

        step_layout = QHBoxLayout()
        self.step_size = QDoubleSpinBox()
        self.step_size.setRange(0.0001, 1000)
        self.step_size.setValue(1)
        self.step_size.setDecimals(4)
        step_layout.addWidget(self.step_size)
        self.step_unit = QComboBox()
        self.step_unit.addItems(["sec", "ms", "\u03bcs"])
        step_layout.addWidget(self.step_unit)
        seg_form.addRow("Step Size (dt):", step_layout)

        self.seg_editor_group.setLayout(seg_form)
        self._segments_splitter.addWidget(self.seg_editor_group)
        self._segments_splitter.setSizes([220, 600])
        self._segments_splitter.setStretchFactor(0, 0)
        self._segments_splitter.setStretchFactor(1, 1)
        layout.addWidget(self._segments_splitter)

        preview_btn = QPushButton("Preview Waveform")
        preview_btn.setStyleSheet("background-color: #f3f4f6; color: #1a1a2e; border: 1px solid #d1d5db; font-family: 'Inter'; font-size: 15px; padding: 12px; font-weight: bold;")
        preview_btn.clicked.connect(self._preview)
        layout.addWidget(preview_btn)

        self.info_label = QLabel("Configure parameters and click Preview")
        self.info_label.setStyleSheet("color: #6b7280; font-style: italic;")
        layout.addWidget(self.info_label)

        self.preview_graph = pg.PlotWidget()
        self.preview_graph.setBackground('#ffffff')
        self.preview_graph.setLabel('left', 'Output Value', color='#1a1a2e')
        self.preview_graph.setLabel('bottom', 'Time (s)', color='#1a1a2e')
        self.preview_graph.setTitle("Waveform Preview", color='#1a1a2e', size='14pt')
        self.preview_graph.showGrid(x=True, y=True, alpha=0.3)
        self.preview_graph.setMinimumHeight(200)
        layout.addWidget(self.preview_graph)

        btn_layout = QHBoxLayout()
        generate_btn = QPushButton("Generate && Import to Sweep List")
        generate_btn.setStyleSheet("background-color: #1a1a2e; color: #ffffff; font-family: 'Inter'; font-size: 15px; padding: 12px; font-weight: bold;")
        generate_btn.clicked.connect(self._generate_and_accept)
        btn_layout.addWidget(generate_btn)

        export_btn = QPushButton("Export CSV")
        export_btn.clicked.connect(self._export_csv)
        btn_layout.addWidget(export_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

        self._add_segment()

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
            self.segment_list.addItem(f"Seg {i+1}: {seg['wave_type']}")
        self.segment_list.blockSignals(False)

    def _update_current_segment_label(self, text):
        if self._current_segment_index >= 0:
            item = self.segment_list.item(self._current_segment_index)
            if item:
                item.setText(f"Seg {self._current_segment_index + 1}: {text}")

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

    def _calculate_all_segments(self):
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
            QMessageBox.warning(self, "Error", str(e))
            return None

    def _preview(self):
        result = self._calculate_all_segments()
        if result:
            combined_t, combined_values = result
            self.waveform_values = list(combined_values)
            self.time_values = list(combined_t)
            export_unit = "V" if "Voltage" in self.export_mode.currentText() else "A"

            n_segs = len(self.segments)
            self.info_label.setText(
                f"{n_segs} segment{'s' if n_segs > 1 else ''} | "
                f"{len(combined_values)} points | "
                f"Duration: {combined_t[-1]:.2f}s | "
                f"Output: {min(combined_values):.4f} to {max(combined_values):.4f} {export_unit}"
            )
            self.info_label.setStyleSheet("color: #1a1a2e; font-weight: bold;")

            self.preview_graph.clear()
            self.preview_graph.plot(self.time_values, self.waveform_values, pen=pg.mkPen('#16a34a', width=2))
            self.preview_graph.setLabel('left', f'Output ({export_unit})')

            if n_segs > 1:
                time_offset = 0.0
                for i, seg in enumerate(self.segments[:-1]):
                    period_sec = seg["period"] * self._get_unit_multiplier(seg["period_unit"])
                    seg_duration = seg["cycles"] * period_sec
                    time_offset += seg_duration
                    boundary_line = pg.InfiniteLine(pos=time_offset, angle=90,
                        pen=pg.mkPen('#ff6b6b', width=1, style=Qt.DashLine))
                    self.preview_graph.addItem(boundary_line)

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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        splitter = getattr(self, "_segments_splitter", None)
        if splitter is None:
            return
        target = Qt.Vertical if self.width() < 750 else Qt.Horizontal
        if splitter.orientation() != target:
            splitter.setOrientation(target)
            if target == Qt.Vertical:
                splitter.setSizes([220, 400])
            else:
                splitter.setSizes([220, max(400, self.width() - 280)])

    def closeEvent(self, event):
        self._live_r_timer.stop()
        super().closeEvent(event)


class MainWindow(QMainWindow):
    """Main application window — Dual-channel 2602B control"""

    measurement_update = pyqtSignal(object)

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

        self.setWindowTitle(f"{__app_name__} - Dual-Channel I-V Characterizer")
        self.setMinimumSize(560, 480)
        self.resize(1200, 800)

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
        self.channel_a_btn.set_selected(channel == "a")
        self.channel_b_btn.set_selected(channel == "b")
        self.multimeter_panel.update_channel_display()
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
            btn.setText(f"{label} · {'On' if live else 'Off'}")
            btn.setEnabled(self.smu is not None)
            theme.set_prop(btn, live="true" if live else "false")

    def _create_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("File")

        export_action = QAction("Export Data...", self)
        export_action.triggered.connect(self.export_csv)
        file_menu.addAction(export_action)

        import_action = QAction("Import Sweep List...", self)
        import_action.triggered.connect(self._import_sweep_list)
        file_menu.addAction(import_action)

        file_menu.addSeparator()

        save_config = QAction("Save Configuration...", self)
        save_config.triggered.connect(self._save_config)
        file_menu.addAction(save_config)

        load_config = QAction("Load Configuration...", self)
        load_config.triggered.connect(self._load_config)
        file_menu.addAction(load_config)

        file_menu.addSeparator()

        self.auto_save_action = QAction("Auto-Save Enabled", self)
        self.auto_save_action.setCheckable(True)
        self.auto_save_action.setChecked(self.auto_save_enabled)
        self.auto_save_action.toggled.connect(self._toggle_auto_save)
        file_menu.addAction(self.auto_save_action)

        auto_save_path_action = QAction("Set Auto-Save Folder...", self)
        auto_save_path_action.triggered.connect(self._set_auto_save_path)
        file_menu.addAction(auto_save_path_action)

        open_save_folder = QAction("Open Auto-Save Folder", self)
        open_save_folder.triggered.connect(self._open_auto_save_folder)
        file_menu.addAction(open_save_folder)

        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        tools_menu = menubar.addMenu("Tools")
        wave_tool_action = QAction("Custom Signal Design...", self)
        wave_tool_action.triggered.connect(self._show_wave_tool)
        tools_menu.addAction(wave_tool_action)

        inst_menu = menubar.addMenu("Instrument")
        connect_action = QAction("Connect...", self)
        connect_action.triggered.connect(self._show_connection_dialog)
        inst_menu.addAction(connect_action)

        disconnect_action = QAction("Disconnect", self)
        disconnect_action.triggered.connect(self._disconnect)
        inst_menu.addAction(disconnect_action)

        inst_menu.addSeparator()

        reset_action = QAction("Reset", self)
        reset_action.triggered.connect(self._reset_instrument)
        inst_menu.addAction(reset_action)

        safety_action = QAction("Safety Settings...", self)
        safety_action.triggered.connect(self._show_safety_dialog)
        inst_menu.addAction(safety_action)

        help_menu = menubar.addMenu("Help")
        update_action = QAction("Check for Updates…", self)
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
        layout.setContentsMargins(0, 0, 0, 10)

        # Header bar
        header = QFrame()
        header.setFixedHeight(44)
        header.setStyleSheet("""
            QFrame {
                background-color: #1a1a2e;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 5, 20, 5)

        header_title = QLabel(__app_name__)
        header_title.setStyleSheet("color: white; font-size: 18px; font-weight: bold; font-family: 'Inter'; background: transparent;")
        header_layout.addWidget(header_title)
        header_layout.addStretch()

        version_label = QLabel(f"v{__version__} Created by {__author__} with claude code")
        version_label.setStyleSheet("color: rgba(255,255,255,0.9); font-size: 11px; font-family: 'Inter'; background: transparent;")
        header_layout.addWidget(version_label)

        layout.addWidget(header)

        # Content area
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 15, 20, 10)

        # Top toolbar
        toolbar = QHBoxLayout()

        connect_btn = QPushButton("Connect")
        connect_btn.clicked.connect(self._show_connection_dialog)
        toolbar.addWidget(connect_btn)

        self.connection_label = QLabel("Disconnected")
        self.connection_label.setStyleSheet("color: #dc2626; font-family: 'Inter'; font-weight: bold; font-size: 15px;")
        toolbar.addWidget(self.connection_label)

        toolbar.addStretch()

        # Channel selector
        ch_label = QLabel("Channel:")
        ch_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        toolbar.addWidget(ch_label)

        self.channel_a_btn = ToggleButton("Ch A")
        self.channel_a_btn.set_selected(True)
        self.channel_a_btn.clicked.connect(lambda: self._set_channel("a"))
        toolbar.addWidget(self.channel_a_btn)

        self.channel_b_btn = ToggleButton("Ch B")
        self.channel_b_btn.clicked.connect(lambda: self._set_channel("b"))
        toolbar.addWidget(self.channel_b_btn)

        # Per-channel output buttons
        self.output_a_btn = QPushButton("OUT A: OFF")
        self.output_a_btn.setStyleSheet("""
            QPushButton {
                background-color: #ffffff; color: #1a1a2e;
                font-family: 'Inter'; font-size: 14px; font-weight: 600;
                padding: 8px 16px; border-radius: 6px; border: 1px solid #d1d5db;
            }
            QPushButton:hover { background-color: #f3f4f6; }
        """)
        self.output_a_btn.clicked.connect(lambda: self._toggle_output("a"))
        toolbar.addWidget(self.output_a_btn)

        self.output_b_btn = QPushButton("OUT B: OFF")
        self.output_b_btn.setStyleSheet("""
            QPushButton {
                background-color: #ffffff; color: #1a1a2e;
                font-family: 'Inter'; font-size: 14px; font-weight: 600;
                padding: 8px 16px; border-radius: 6px; border: 1px solid #d1d5db;
            }
            QPushButton:hover { background-color: #f3f4f6; }
        """)
        self.output_b_btn.clicked.connect(lambda: self._toggle_output("b"))
        toolbar.addWidget(self.output_b_btn)

        toolbar.addStretch()

        self.start_btn = QPushButton("START SWEEP")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #1a1a2e; color: #ffffff;
                font-family: 'Inter'; font-size: 14px; font-weight: bold;
                padding: 8px 20px; border-radius: 6px; border: none;
            }
            QPushButton:hover { background-color: #374151; }
            QPushButton:disabled { background-color: #e5e7eb; color: #9ca3af; }
        """)
        self.start_btn.clicked.connect(self.start_sweep)
        toolbar.addWidget(self.start_btn)

        self.stop_btn = QPushButton("STOP")
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc2626; color: #ffffff;
                font-family: 'Inter'; font-size: 14px; font-weight: bold;
                padding: 8px 20px; border-radius: 6px; border: none;
            }
            QPushButton:hover { background-color: #b91c1c; }
            QPushButton:disabled { background-color: #e5e7eb; color: #9ca3af; }
        """)
        self.stop_btn.clicked.connect(self.stop_sweep)
        self.stop_btn.setEnabled(False)
        toolbar.addWidget(self.stop_btn)

        self.export_btn = QPushButton("Export CSV")
        self.export_btn.clicked.connect(self.export_csv)
        toolbar.addWidget(self.export_btn)

        # Buttons that only make sense on the I-V Sweep tab
        self._sweep_only_widgets = [self.start_btn, self.stop_btn, self.export_btn]

        content_layout.addLayout(toolbar)

        # Main tabs
        tabs = QTabWidget()
        self.main_tabs = tabs
        tabs.currentChanged.connect(self._on_main_tab_changed)

        # Tab 1: Multimeter (wrapped in a scroll area so it never clips)
        self.multimeter_panel = MultimeterPanel(self)
        mm_scroll = QScrollArea()
        mm_scroll.setWidgetResizable(True)
        mm_scroll.setFrameShape(QFrame.NoFrame)
        mm_scroll.setWidget(self.multimeter_panel)
        tabs.addTab(mm_scroll, "Multimeter")

        # Tab 2: I-V Sweep
        sweep_tab = QWidget()
        sweep_outer = QVBoxLayout(sweep_tab)
        sweep_outer.setContentsMargins(0, 0, 0, 0)

        # Horizontal splitter: experiments sidebar (left) | three sub-tabs (right)
        iv_outer_splitter = QSplitter(Qt.Horizontal)

        self.experiments_sidebar = ExperimentsSidebar(self.experiment_store)
        self.experiments_sidebar.experiment_selected.connect(self._load_experiment)
        self.experiments_sidebar.save_requested.connect(self._save_experiment)
        self.experiments_sidebar.rename_requested.connect(self._rename_experiment)
        self.experiments_sidebar.delete_requested.connect(self._delete_experiment)
        self.experiments_sidebar.new_requested.connect(self._new_experiment)
        self.experiments_sidebar.clone_requested.connect(self._clone_experiment)
        self.experiments_sidebar.notes_changed.connect(self._on_notes_changed)
        iv_outer_splitter.addWidget(self.experiments_sidebar)

        # Three sub-tabs inside I-V Sweep: Settings / Sweep Values / Graph
        iv_sub_tabs = QTabWidget()

        # --- Sub-tab 1: Settings ---
        settings_panel = QWidget()
        settings_layout = QVBoxLayout(settings_panel)
        settings_layout.setSpacing(10)

        self.source_settings = SourceSettingsWidget()
        settings_layout.addWidget(self.source_settings)

        self.inst_settings = InstrumentSettingsWidget()
        settings_layout.addWidget(self.inst_settings)

        self.measure_settings = MeasureSettingsWidget()
        settings_layout.addWidget(self.measure_settings)

        self.timing_settings = TimingSettingsWidget()
        settings_layout.addWidget(self.timing_settings)

        settings_layout.addStretch()

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
        iv_sub_tabs.addTab(sweep_scroll, "Sweep Values")

        # --- Sub-tab 3: Graph ---
        graph_tab = QWidget()
        graph_tab_layout = QVBoxLayout(graph_tab)
        graph_tab_layout.setContentsMargins(0, 0, 0, 0)

        axis_bar = QWidget()
        axis_layout = QHBoxLayout(axis_bar)
        axis_layout.setContentsMargins(0, 0, 0, 0)

        axis_layout.addWidget(QLabel("X:"))
        self.x_axis = QComboBox()
        self.x_axis.addItems(["Voltage", "Current", "Time", "Index"])
        axis_layout.addWidget(self.x_axis)
        self.x_unit = QComboBox()
        axis_layout.addWidget(self.x_unit)
        self.x_axis.currentTextChanged.connect(lambda _: self._on_axis_variable_changed("x"))
        self.x_unit.currentTextChanged.connect(self._update_graph_axes)

        axis_layout.addWidget(QLabel("Y1 (Left):"))
        self.y1_axis = QComboBox()
        self.y1_axis.addItems(["Current", "Voltage", "Resistance", "Power", "None"])
        axis_layout.addWidget(self.y1_axis)
        self.y1_unit = QComboBox()
        axis_layout.addWidget(self.y1_unit)
        self.y1_axis.currentTextChanged.connect(lambda _: self._on_axis_variable_changed("y1"))
        self.y1_unit.currentTextChanged.connect(self._update_graph_axes)

        axis_layout.addWidget(QLabel("Y2 (Right):"))
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

        axis_layout.addWidget(QLabel("Presets:"))
        for preset, (x, y1, y2) in [("I-V", ("Voltage", "Current", "None")),
                                     ("I-t", ("Time", "Current", "None")),
                                     ("V,P-t", ("Time", "Voltage", "Power")),
                                     ("I,R-t", ("Time", "Current", "Resistance"))]:
            btn = QPushButton(preset)
            btn.setMaximumWidth(80)
            btn.clicked.connect(lambda checked, x=x, y1=y1, y2=y2: self._set_graph_preset(x, y1, y2))
            axis_layout.addWidget(btn)

        axis_layout.addStretch()

        self.live_update_cb = QCheckBox("Live Update")
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

        graph_table_splitter.setSizes([500, 300])
        graph_table_splitter.setCollapsible(0, True)
        graph_table_splitter.setCollapsible(1, True)
        graph_tab_layout.addWidget(graph_table_splitter)

        iv_sub_tabs.addTab(graph_tab, "Graph")

        iv_outer_splitter.addWidget(iv_sub_tabs)
        iv_outer_splitter.setSizes([240, 1000])
        iv_outer_splitter.setStretchFactor(0, 0)
        iv_outer_splitter.setStretchFactor(1, 1)
        iv_outer_splitter.setCollapsible(0, True)
        iv_outer_splitter.setCollapsible(1, False)
        sweep_outer.addWidget(iv_outer_splitter)

        tabs.addTab(sweep_tab, "I-V Sweep")

        # Tab 3: Real Time — unified live view of calorimeter (HF, T) and any
        # running K2602B sweep (V, I, R, P). Connection is managed from the
        # Connect dialog; this tab is display-only.
        from realtime_tab import RealTimeTab
        self.realtime_tab = RealTimeTab(self)
        tabs.addTab(self.realtime_tab, "Real Time")

        content_layout.addWidget(tabs)
        layout.addWidget(content)

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
        self.progress_label.setStyleSheet("font-family: 'Inter'; color: #9ca3af;")
        self.status.addPermanentWidget(self.progress_label)

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(200)
        self.progress.setFormat("%v / %m")
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
        is_sweep_tab = self.main_tabs.tabText(index) == "I-V Sweep"
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
        dialog.exec_()

    def _disconnect(self):
        self.disconnect_instrument()

    def disconnect_instrument(self, quiet: bool = False):
        if self.smu:
            try:
                self.smu.disconnect()
            except Exception:
                pass
            self.smu = None
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
        if hasattr(self.inst_settings, "set_capabilities"):
            self.inst_settings.set_capabilities(caps)
        self.model_label.setText(caps.display_name)

    def _reset_instrument(self):
        if self.smu:
            self.smu.reset()
            self._update_output_buttons()
            self.status.showMessage("Instrument reset")

    def _show_safety_dialog(self):
        dialog = SafetyDialog(self, self.safety_limits, model=self.model)
        if dialog.exec_() == QDialog.Accepted:
            self.safety_limits = dialog.get_limits()
            self._limits_by_model[self.model] = self.safety_limits
            self.status.showMessage(f"Safety limits updated: \u00b1{self.safety_limits.max_voltage}V, \u00b1{self.safety_limits.max_current}A")

    def _check_license_agreement(self) -> bool:
        license_accepted = self.settings.value("license_accepted", False, type=bool)
        license_version = self.settings.value("license_version", "", type=str)
        if license_accepted and license_version == __version__:
            return True
        dialog = LicenseDialog(self)
        if dialog.exec_() == QDialog.Accepted:
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
        <p><small>Built with PyQt5 + pyqtgraph | TSP command interface</small></p>
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
        if dialog.exec_() == QDialog.Accepted:
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
                self.source_settings.compliance.setValue(config["source"].get("compliance", 0.1))

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

        limits = self._limits_by_model.get(model) or SMU.default_limits(model)
        smu = SMU.create(model, simulate=simulate,
                         simulation_resistance=simulation_resistance,
                         safety_limits=limits)
        smu.connect(None if simulate else address, baud_rate=baud_rate)

        self.smu = smu
        self.model = model
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
        """Toolbar label reflects both Keithley and calorimeter status."""
        parts = []
        if self.smu is None:
            parts.append(("Keithley: Disconnected", "#dc2626"))
        elif getattr(self, "_smu_sim_resistance", None) is not None:
            r = self._smu_sim_resistance
            res_str = f"{r:.0f}\u03a9" if r < 1000 else f"{r/1000:.0f}k\u03a9"
            parts.append((f"Keithley: SIM ({res_str})", "#6b7280"))
        else:
            parts.append(("Keithley: Connected", "#16a34a"))

        if self.calorimeter_reader is None:
            parts.append(("Calorimeter: \u2014", "#6b7280"))
        else:
            name = self.calorimeter_name or "?"
            parts.append((f"Calorimeter: {name}", "#16a34a"))

        # Render as rich text with per-segment color
        html = "  |  ".join(
            f"<span style='color:{color};'>{text}</span>" for text, color in parts
        )
        self.connection_label.setText(html)
        # Keep styleSheet minimal \u2014 colors handled by inline spans
        self.connection_label.setStyleSheet(
            "font-family: 'Inter'; font-weight: bold; font-size: 14px;"
        )

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
        self.progress_label.setText(f"0 / {total} | Est: --:--")

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

            # Apply sense mode
            sense = self.inst_settings.sense
            if sense == "4-Wire":
                self.smu.set_remote_sense(True, channel)
            else:
                self.smu.set_remote_sense(False, channel)

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
                        if abs(current) > 1e-9 and abs(voltage) > 1e-6:
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
            self.progress_label.setText(
                f"Done: {self.total_sweep_points} pts in {self._fmt_duration(total_time)}"
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def _apply_responsive_layout(self):
        w = self.width()
        h = self.height()

        # Font scaling: shrinks when window is small, never grows above original sizes.
        # 1.00 at >= 1300x900, down to 0.65 at very small windows.
        ratio = min(w / 1300.0, h / 900.0)
        scale = max(0.65, min(1.00, ratio))
        # Round to nearest 0.05 to avoid thrashing the stylesheet on tiny moves
        scale = round(scale * 20) / 20
        if abs(scale - getattr(self, "_current_ui_scale", -1)) >= 0.025:
            self._current_ui_scale = scale
            app = QApplication.instance()
            if app is not None:
                app.setStyleSheet(build_global_stylesheet(scale))
                f = QFont("Inter", max(9, round(15 * scale)))
                app.setFont(f)

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
_GLOBAL_STYLESHEET_TEMPLATE = """
    QMainWindow, QWidget {
        background-color: #ffffff;
        color: #1a1a2e;
    }
    QLabel {
        color: #1a1a2e;
        font-size: __FONT_14__;
    }
    QPushButton {
        font-size: __FONT_14__;
        color: #1a1a2e;
        background-color: #f3f4f6;
        border: 1px solid #d1d5db;
        padding: 6px 14px;
        border-radius: 5px;
        font-weight: 500;
    }
    QPushButton:hover {
        background-color: #e5e7eb;
        border-color: #9ca3af;
    }
    QPushButton:disabled {
        background-color: #f3f4f6;
        color: #9ca3af;
        border-color: #e5e7eb;
    }
    QCheckBox, QRadioButton {
        font-size: __FONT_14__;
        color: #1a1a2e;
        font-weight: 500;
    }
    QCheckBox:disabled, QRadioButton:disabled {
        color: #9ca3af;
    }
    QGroupBox {
        font-size: __FONT_14__;
        font-weight: bold;
        color: #1a1a2e;
        border: 1px solid #d1d5db;
        border-radius: 8px;
        margin-top: 16px;
        padding: 16px;
        padding-top: 14px;
        background-color: transparent;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 8px;
        color: #1a1a2e;
        background-color: #ffffff;
        font-size: __FONT_14__;
        font-weight: bold;
    }
    QTableWidget, QListWidget {
        font-size: __FONT_13__;
        color: #1a1a2e;
        background-color: #ffffff;
        border: 1px solid #d1d5db;
        alternate-background-color: #f9fafb;
    }
    QTableWidget::item, QListWidget::item {
        color: #1a1a2e;
    }
    QTableWidget::item:selected, QListWidget::item:selected {
        background-color: #dbeafe;
        color: #1a1a2e;
    }
    QHeaderView::section {
        background-color: #f3f4f6;
        color: #1a1a2e;
        font-weight: bold;
        font-size: __FONT_13__;
        padding: 8px;
        border: 1px solid #d1d5db;
    }
    QToolTip {
        font-size: __FONT_13__;
        background-color: #1a1a2e;
        color: #ffffff;
        border: 1px solid #1a1a2e;
        padding: 6px;
    }
    QMenuBar {
        font-size: __FONT_14__;
        background-color: #f3f4f6;
        color: #1a1a2e;
        border-bottom: 1px solid #d1d5db;
    }
    QMenuBar::item {
        color: #1a1a2e;
    }
    QMenuBar::item:selected {
        background-color: #e5e7eb;
    }
    QMenu {
        font-size: __FONT_14__;
        background-color: #ffffff;
        color: #1a1a2e;
        border: 1px solid #d1d5db;
    }
    QMenu::item {
        color: #1a1a2e;
        padding: 6px 20px;
    }
    QMenu::item:selected {
        background-color: #dbeafe;
        color: #1a1a2e;
    }
    QTabWidget::pane {
        border: 1px solid #d1d5db;
        background-color: #ffffff;
        border-top: none;
    }
    QTabBar::tab {
        font-size: __FONT_14__;
        padding: 10px 24px;
        background-color: #f3f4f6;
        color: #6b7280;
        border: 1px solid #d1d5db;
        border-bottom: none;
        margin-right: 2px;
        font-weight: 500;
    }
    QTabBar::tab:selected {
        background-color: #ffffff;
        color: #1a1a2e;
        font-weight: bold;
        border-bottom: 2px solid #1a1a2e;
        border-color: #d1d5db;
    }
    QTabBar::tab:hover {
        background-color: #e5e7eb;
        color: #1a1a2e;
    }
    QComboBox {
        font-size: __FONT_14__;
        color: #1a1a2e;
        background-color: #ffffff;
        border: 1px solid #d1d5db;
        padding: 6px 10px;
        border-radius: 5px;
    }
    QComboBox:hover {
        border-color: #6b7280;
    }
    QComboBox:disabled {
        background-color: #f3f4f6;
        color: #9ca3af;
    }
    QComboBox QAbstractItemView {
        background-color: #ffffff;
        color: #1a1a2e;
        selection-background-color: #dbeafe;
        selection-color: #1a1a2e;
    }
    QSpinBox, QDoubleSpinBox {
        font-size: __FONT_14__;
        color: #1a1a2e;
        background-color: #ffffff;
        border: 1px solid #d1d5db;
        padding: 4px 6px;
        padding-right: 22px;
        border-radius: 5px;
    }
    QSpinBox:hover, QDoubleSpinBox:hover {
        border-color: #6b7280;
    }
    QSpinBox:disabled, QDoubleSpinBox:disabled {
        background-color: #f3f4f6;
        color: #9ca3af;
    }
    /* Spinbox up/down buttons: only style the area, let Fusion paint the arrows */
    QSpinBox::up-button, QDoubleSpinBox::up-button,
    QSpinBox::down-button, QDoubleSpinBox::down-button,
    QComboBox::drop-down {
        background-color: transparent;
        border: none;
    }
    QTextEdit, QLineEdit {
        font-size: __FONT_13__;
        color: #1a1a2e;
        background-color: #ffffff;
        border: 1px solid #d1d5db;
        border-radius: 4px;
        padding: 4px 6px;
    }
    QScrollBar:vertical {
        background-color: #f3f4f6;
        width: 12px;
        border-radius: 6px;
    }
    QScrollBar::handle:vertical {
        background-color: #d1d5db;
        border-radius: 6px;
        min-height: 30px;
    }
    QScrollBar::handle:vertical:hover {
        background-color: #9ca3af;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    QScrollBar:horizontal {
        background-color: #f3f4f6;
        height: 12px;
        border-radius: 6px;
    }
    QScrollBar::handle:horizontal {
        background-color: #d1d5db;
        border-radius: 6px;
        min-width: 30px;
    }
    QScrollBar::handle:horizontal:hover {
        background-color: #9ca3af;
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0px;
    }
    QStatusBar {
        background-color: #f3f4f6;
        color: #4b5563;
        border-top: 1px solid #d1d5db;
    }
    QProgressBar {
        border: 1px solid #d1d5db;
        border-radius: 4px;
        background-color: #ffffff;
        text-align: center;
        color: #1a1a2e;
        font-weight: bold;
    }
    QProgressBar::chunk {
        background-color: #1a1a2e;
        border-radius: 3px;
    }
    QSplitter::handle {
        background-color: #e5e7eb;
    }
    QSplitter::handle:hover {
        background-color: #d1d5db;
    }
"""


def build_global_stylesheet(scale: float = 1.0) -> str:
    """Render the global stylesheet with all font sizes scaled by `scale`."""
    def px(base: int) -> str:
        return f"{max(8, round(base * scale))}px"
    return (_GLOBAL_STYLESHEET_TEMPLATE
            .replace("__FONT_14__", px(14))
            .replace("__FONT_13__", px(13)))


# Backwards-compat alias: existing callers (launcher) import GLOBAL_STYLESHEET.
GLOBAL_STYLESHEET = build_global_stylesheet(1.0)


def main():
    app = QApplication(sys.argv)
    app.setPalette(LightPalette())
    app.setStyle('Fusion')

    app.setStyleSheet(build_global_stylesheet(1.0))

    # Set Inter font AFTER stylesheet — on macOS, setStyleSheet() resets app font
    app.setFont(QFont("Inter", 15))

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
