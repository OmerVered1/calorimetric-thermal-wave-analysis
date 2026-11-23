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

# Deliberate differences from the original windows, all in sweeps, all sent
# just before the output turns on:
#
# 1. The 2602B and 2611A windows showed "Output Off" and "Auto Zero" but never
#    sent them. The merged window sends both, as the 6430 window always did.
# 2. No window sent the Source or Measure "Range" choice. The merged window
#    sends both, Auto included: the source range for the sourced quantity, the
#    measure range for the measured one (current, when sourcing voltage), so a
#    sweep no longer inherits a fixed range left by the Multimeter tab.
#
# Every model resets on connect (smua.reset() / *RST), which leaves Output off
# Normal, auto-zero on and auto-range on. At their defaults these commands
# repeat that, so a run at default settings is taken exactly as the old ones were.
OUTPUT_ON = {"2450": "OUTP ON", "6430": ":OUTP ON",
             "2602B": "smua.source.output = smua.OUTPUT_ON",
             "2611A": "smua.source.output = smua.OUTPUT_ON"}
TSP_OFF_AND_ZERO = [
    "smua.source.offmode = smua.OUTPUT_NORMAL",
    "smua.measure.autozero = smua.AUTOZERO_AUTO",
]
AUTO_CURRENT_RANGE = {"2450": "SENS:CURR:RANG:AUTO ON", "6430": ":SENS:CURR:RANG:AUTO ON",
                      "2602B": "smua.measure.autorangei = smua.AUTORANGE_ON",
                      "2611A": "smua.measure.autorangei = smua.AUTORANGE_ON"}
AUTO_SOURCE_VOLTAGE_RANGE = {"2450": "SOUR:VOLT:RANG:AUTO ON", "6430": ":SOUR:VOLT:RANG:AUTO ON",
                             "2602B": "smua.source.autorangev = smua.AUTORANGE_ON",
                             "2611A": "smua.source.autorangev = smua.AUTORANGE_ON"}


def expected(model, scenario):
    sent = list(GOLDEN[model][scenario])
    if scenario.startswith("sweep"):
        added = TSP_OFF_AND_ZERO if model in ("2602B", "2611A") else []
        i = sent.index(OUTPUT_ON[model])
        sent[i:i] = added + [AUTO_SOURCE_VOLTAGE_RANGE[model], AUTO_CURRENT_RANGE[model]]
    return sent


def _window(model):
    from ctwa import app as merged
    merged.MainWindow._check_license_agreement = lambda self: True
    w = merged.MainWindow()
    w.auto_save_enabled = False
    w.connect_instrument(model, simulate=True, simulation_resistance=1000.0)
    return w


def _sweep(app, w, stop=1.0):
    sent = S._record(w.smu.driver)
    w.source_settings.mode.setCurrentText("Linear Sweep")
    w.sweep_list.start_val.setValue(0.0)
    w.sweep_list.stop_val.setValue(stop)
    w.sweep_list.num_points.setValue(3)
    w.timing_settings.delay.setValue(0.0)
    w.start_sweep()
    S._wait(app, w)
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
    w = _window(model)
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
        sent = _sweep(app, w)
        smu = f"smu{channel}"
        on = sent.index(f"{smu}.source.output = {smu}.OUTPUT_ON")
        assert sent[on - 4:on] == [
            f"{smu}.source.offmode = {smu}.OUTPUT_HIGH_Z",
            f"{smu}.measure.autozero = {smu}.AUTOZERO_ONCE",
            f"{smu}.source.autorangev = {smu}.AUTORANGE_ON",
            f"{smu}.measure.autorangei = {smu}.AUTORANGE_ON",
        ]
    finally:
        w.close()
        app.processEvents()


def _ranges(w):
    box = w.measure_settings.measure_range
    return [box.itemText(i) for i in range(box.count())]


def test_measure_range_lists_the_measured_quantity_of_the_connected_model(app):
    w = _window("2602B")
    try:
        # Sourcing voltage measures current; sourcing current measures voltage.
        assert _ranges(w) == ["Auto", "100 nA", "1 \u00b5A", "10 \u00b5A", "100 \u00b5A",
                              "1 mA", "10 mA", "100 mA", "1 A", "3 A"]
        w.source_settings._set_function("Current")
        assert _ranges(w) == ["Auto", "200 mV", "2 V", "20 V", "40 V"]
        w.source_settings._set_function("Voltage")
        w.connect_instrument("6430", simulate=True, simulation_resistance=1000.0)
        assert _ranges(w)[:3] == ["Auto", "100 fA", "1 pA"]
        assert "3 A" not in _ranges(w)
    finally:
        w.close()
        app.processEvents()


@pytest.mark.parametrize("function,label,commands", [
    ("Voltage", "1 mA", ["smub.measure.rangei = 0.001",
                         "smub.measure.autorangei = smub.AUTORANGE_OFF"]),
    ("Current", "2 V", ["smub.measure.rangev = 2",
                        "smub.measure.autorangev = smub.AUTORANGE_OFF"]),
])
def test_fixed_measure_range_reaches_the_instrument(app, function, label, commands):
    w = _window("2602B")
    try:
        w._set_channel("b")
        w.source_settings._set_function(function)
        if function == "Current":
            w.source_settings.compliance.setValue(10.0)
        w.measure_settings.measure_range.setCurrentText(label)
        # 1 mA through the simulated 1 kΩ stays well inside 10 V compliance
        sent = _sweep(app, w, stop=1.0 if function == "Voltage" else 0.001)
        on = sent.index("smub.source.output = smub.OUTPUT_ON")
        assert sent[on - 2:on] == commands
    finally:
        w.close()
        app.processEvents()


def test_measure_range_is_saved_with_the_experiment(app):
    w = _window("2602B")
    try:
        w.measure_settings.measure_range.setCurrentText("10 mA")
        state = w._capture_state()
        assert state["measure"]["range"] == "10 mA"
        w.measure_settings.measure_range.setCurrentText("Auto")
        w._apply_state(state)
        assert w.measure_settings.measure_range.currentText() == "10 mA"
    finally:
        w.close()
        app.processEvents()


def _source_ranges(w):
    box = w.source_settings.range
    return [box.itemText(i) for i in range(box.count())]


def test_source_range_lists_the_sourced_quantity_of_the_connected_model(app):
    w = _window("2602B")
    try:
        assert _source_ranges(w) == ["Auto", "200 mV", "2 V", "20 V", "40 V"]
        w.source_settings._set_function("Current")
        assert _source_ranges(w)[:3] == ["Auto", "100 nA", "1 \u00b5A"]
        assert _source_ranges(w)[-1] == "3 A"
        w.source_settings._set_function("Voltage")
        w.connect_instrument("2450", simulate=True, simulation_resistance=1000.0)
        assert _source_ranges(w) == ["Auto", "200 mV", "2 V", "20 V", "200 V"]
    finally:
        w.close()
        app.processEvents()


def test_fixed_source_range_reaches_the_instrument(app):
    w = _window("2602B")
    try:
        w._set_channel("b")
        w.source_settings.range.setCurrentText("2 V")
        sent = _sweep(app, w)
        on = sent.index("smub.source.output = smub.OUTPUT_ON")
        assert sent[on - 3:on] == [
            "smub.source.rangev = 2",
            "smub.source.autorangev = smub.AUTORANGE_OFF",
            "smub.measure.autorangei = smub.AUTORANGE_ON",
        ]
    finally:
        w.close()
        app.processEvents()


def test_sweep_beyond_a_fixed_source_range_does_not_start(app):
    w = _window("2602B")
    try:
        w.source_settings.range.setCurrentText("2 V")
        sent = _sweep(app, w, stop=5.0)
        assert not w.running
        assert not any("OUTPUT_ON" in c for c in sent)
    finally:
        w.close()
        app.processEvents()


def test_source_range_is_saved_with_the_experiment(app):
    w = _window("2602B")
    try:
        w.source_settings.range.setCurrentText("20 V")
        state = w._capture_state()
        assert state["source"]["range"] == "20 V"
        w.source_settings.range.setCurrentText("Auto")
        w._apply_state(state)
        assert w.source_settings.range.currentText() == "20 V"
    finally:
        w.close()
        app.processEvents()
