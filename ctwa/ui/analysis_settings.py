"""The settings column of the Analysis tab. Defaults are the webapp's
(app/analysis/page.tsx, useState block): r1 6.72, r2 14.86, calibration on
with a 105 s system lag, mode AutoFit, no cycle shift, no period override."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                               QFrame, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from ctwa import theme
from ctwa.analysis.types import AnalysisParams

MODES = [  # (value, label) as in the webapp's mode control, same order
    ("AutoFit", "Auto (sine fit)"),
    ("AutoFFT", "Auto (FFT)"),
    ("AutoHybrid", "Auto (peaks + FFT)"),
    ("Auto", "Auto (peaks)"),
    ("Manual", "Manual"),
]
DEFAULT_R1, DEFAULT_R2, DEFAULT_LAG = 6.72, 14.86, 105.0


def _spin(lo, hi, value, decimals, step, suffix) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setValue(value)
    s.setSuffix(suffix)
    return s


class SettingsPanel(QFrame):
    changed = Signal()       # any setting
    mode_changed = Signal(str)  # "Manual" shows the markers

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        theme.set_role(self, "card")
        lay = QVBoxLayout(self)
        lay.addWidget(theme.set_role(QLabel("Settings"), "section"))

        self.sine_btn = QPushButton("Sine")
        self.square_btn = QPushButton("Square")
        for b in (self.sine_btn, self.square_btn):
            b.setCheckable(True)
        self.sine_btn.setChecked(True)
        self.sine_btn.clicked.connect(lambda: self.set_wave("sine"))
        self.square_btn.clicked.connect(lambda: self.set_wave("square"))
        lay.addWidget(theme.segmented(self.sine_btn, self.square_btn))

        form = QFormLayout()
        form.setContentsMargins(0, 4, 0, 4)
        lay.addLayout(form)
        self.mode_combo = QComboBox()
        for value, label in MODES:
            self.mode_combo.addItem(label, value)
        self.period_spin = _spin(0, 1e7, 0.0, 1, 0.1, " s")
        self.period_spin.setSpecialValueText("auto")
        self.period_spin.setToolTip("Leave on auto to detect the period from the source")
        self.square_spin = _spin(0, 1e7, 0.0, 1, 0.1, " s")
        self.square_spin.setSpecialValueText("auto")
        self.square_spin.setToolTip("Auto-detected from the source edges when left on auto")
        self.shift_spin = QSpinBox()
        self.shift_spin.setRange(-20, 20)
        self.shift_spin.setToolTip("Whole periods added to the lag as read within one period "
                                   "(for a lag longer than a period)")
        self.r1_spin = _spin(0.1, 1000, DEFAULT_R1, 2, 0.01, " mm")
        self.r2_spin = _spin(0.1, 1000, DEFAULT_R2, 2, 0.01, " mm")
        self._rows = {}
        for key, label, w in (("mode", "Mode", self.mode_combo),
                              ("period", "Period override", self.period_spin),
                              ("square", "Period", self.square_spin),
                              ("shift", "Cycle shift", self.shift_spin),
                              ("r1", "Inner radius r₁", self.r1_spin),
                              ("r2", "Outer radius r₂", self.r2_spin)):
            lab = QLabel(label)
            form.addRow(lab, w)
            self._rows[key] = (lab, w)

        self.smooth_check = QCheckBox("Smooth to single sine")
        self.smooth_check.setToolTip("Fit A·sin(ωt+φ) to source and response, "
                                     "then analyze the fitted sines")
        self.calib_check = QCheckBox("Subtract system lag")
        self.calib_check.setChecked(True)
        self.lag_spin = _spin(-1e6, 1e6, DEFAULT_LAG, 1, 0.1, " s")
        lay.addWidget(self.smooth_check)
        lay.addWidget(self.calib_check)
        lay.addWidget(self.lag_spin)
        self.radii_note = theme.set_role(QLabel("r₂ should be larger than r₁"), "danger")
        self.radii_note.hide()
        lay.addWidget(self.radii_note)
        lay.addStretch(1)

        self.sine_btn.clicked.connect(self._refresh)
        self.square_btn.clicked.connect(self._refresh)
        self.mode_combo.currentIndexChanged.connect(self._on_mode)
        self.calib_check.toggled.connect(self._refresh)
        for w in (self.period_spin, self.square_spin, self.r1_spin, self.r2_spin, self.lag_spin):
            w.valueChanged.connect(self._refresh)
        self.shift_spin.valueChanged.connect(self._refresh)
        self.smooth_check.toggled.connect(self._refresh)
        self._refresh()

    # ---- state ----
    def wave(self) -> str:
        return "square" if self.square_btn.isChecked() else "sine"

    def set_wave(self, wave: str) -> None:
        self.square_btn.setChecked(wave == "square")
        self.sine_btn.setChecked(wave != "square")
        self._refresh()

    def mode(self) -> str:
        return self.mode_combo.currentData()

    def set_mode(self, mode: str) -> None:
        self.mode_combo.setCurrentIndex(self.mode_combo.findData(mode))

    def radii_ok(self) -> bool:
        return self.r2_spin.value() > self.r1_spin.value()

    def manual(self) -> bool:
        return self.wave() == "sine" and self.mode() == "Manual"

    def square_period(self) -> Optional[float]:
        return self.square_spin.value() or None if self.wave() == "square" else None

    def build_params(self) -> AnalysisParams:
        """As the webapp builds it at page.tsx ~L676: units Seconds/mW, no clocks for one file,
        manual_snap False (the markers are used as placed), override only for AutoFFT/AutoFit."""
        use_override = self.wave() == "sine" and self.mode() in ("AutoFFT", "AutoFit") \
            and self.period_spin.value() > 0
        return AnalysisParams(
            model_name="", test_date="", test_time="",
            t_cal="00:00:00", t_src="00:00:00",
            r1_mm=self.r1_spin.value(), r2_mm=self.r2_spin.value(),
            c80_time_unit="Seconds", c80_pwr_unit="mW",
            src_time_unit="Seconds", src_pwr_unit="Watts",  # the page's defaults; unused for one file
            use_calibration=self.calib_check.isChecked(),
            system_lag=self.lag_spin.value(),
            analysis_mode=self.mode(),
            fft_period_override=self.period_spin.value() if use_override else None,
            cycle_shift=float(self.shift_spin.value()),
            manual_snap=False,
        )

    # ---- visibility ----
    def _on_mode(self) -> None:
        self._refresh()
        self.mode_changed.emit(self.mode())

    def _refresh(self) -> None:
        sine = self.wave() == "sine"
        show = {"mode": sine,
                "period": sine and self.mode() in ("AutoFFT", "AutoFit"),
                "square": not sine}
        for key, visible in show.items():
            for w in self._rows[key]:
                w.setVisible(visible)
        self.smooth_check.setVisible(sine)
        self.lag_spin.setEnabled(self.calib_check.isChecked())
        self.radii_note.setVisible(not self.radii_ok())
        self.changed.emit()
