"""The merged window must send exactly what each original window sent.

tests/golden/original_windows.json holds the command streams recorded from the
four per-model programs of keithley-smu-control v3.6.0 (see
equivalence_scenarios.py). Every measurement taken so far was made through those
programs, so matching them command for command is the guarantee that a new run
is taken the same way as an old one.
"""

import json
import logging
import os
import pathlib
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import equivalence_scenarios as S  # noqa: E402

GOLDEN = json.loads((pathlib.Path(__file__).parent / "golden" / "original_windows.json").read_text())
CASES = [(m, s) for m in ("2450", "6430", "2602B", "2611A") for s in S.SCENARIOS]

# The one deliberate difference from the original windows. The 2602B and 2611A
# windows showed "Output Off" and "Auto Zero" but never sent them, so those
# instruments ran at whatever smua.reset() on connect left: Normal and auto
# (On). The merged window sends both just before the output turns on, as the
# 6430 window always did. At their defaults they repeat what the reset already
# set, so a run at default settings is still taken exactly as the old ones were.
TSP_SWEEP_ADDED = [
    "smua.source.offmode = smua.OUTPUT_NORMAL",
    "smua.measure.autozero = smua.AUTOZERO_AUTO",
]


def expected(model, scenario):
    sent = list(GOLDEN[model][scenario])
    if model in ("2602B", "2611A") and scenario.startswith("sweep"):
        i = sent.index("smua.source.output = smua.OUTPUT_ON")
        sent[i:i] = TSP_SWEEP_ADDED
    return sent


@pytest.fixture(scope="module")
def app():
    logging.disable(logging.CRITICAL)
    for n in ("warning", "critical", "information"):
        setattr(QMessageBox, n, staticmethod(lambda *a, **k: None))
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("model,scenario", CASES)
def test_merged_window_sends_what_the_original_sent(app, model, scenario):
    from ctwa import app as merged
    merged.MainWindow._check_license_agreement = lambda self: True
    w = merged.MainWindow()
    w.auto_save_enabled = False
    w.connect_instrument(model, simulate=True, simulation_resistance=1000.0)
    try:
        got = S.run(app, w, w.smu.driver, model, scenario)
    finally:
        w.close()
        app.processEvents()
    assert got == expected(model, scenario)


@pytest.mark.parametrize("model", ["2602B", "2611A"])
def test_output_off_and_auto_zero_are_shown_and_sent(app, model):
    from ctwa import app as merged
    merged.MainWindow._check_license_agreement = lambda self: True
    w = merged.MainWindow()
    w.auto_save_enabled = False
    w.connect_instrument(model, simulate=True, simulation_resistance=1000.0)
    try:
        assert w.inst_settings.off_row.isVisible()
        assert w.measure_settings.auto_zero_row.isVisible()
        offered = [w.inst_settings.output_off_mode.itemText(i)
                   for i in range(w.inst_settings.output_off_mode.count())]
        assert offered == ["Normal", "Zero", "High-Z"]

        channel = "b" if model == "2602B" else "a"
        w._set_channel(channel)
        w.inst_settings.output_off_mode.setCurrentText("High-Z")
        w.measure_settings.auto_zero.setCurrentText("Once")
        sent = S._record(w.smu.driver)
        w.sweep_list.start_val.setValue(0.0)
        w.sweep_list.stop_val.setValue(1.0)
        w.sweep_list.num_points.setValue(3)
        w.timing_settings.delay.setValue(0.0)
        w.start_sweep()
        S._wait(app, w)
        smu = f"smu{channel}"
        on = sent.index(f"{smu}.source.output = {smu}.OUTPUT_ON")
        assert sent[on - 2:on] == [
            f"{smu}.source.offmode = {smu}.OUTPUT_HIGH_Z",
            f"{smu}.measure.autozero = {smu}.AUTOZERO_ONCE",
        ]
    finally:
        w.close()
        app.processEvents()
