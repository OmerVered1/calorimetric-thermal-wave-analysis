"""Experiment details: the Qt-free module, the run header round trip, and Start writing them."""

import os
import pathlib
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from ctwa.analysis.run_header import parse_run_header  # noqa: E402
from ctwa.experiment_details import FIELDS, default_details, header_lines, parse_number  # noqa: E402

FULL = {"sample": "Al2O3", "power_source": "Keithley 2602B", "response_device": "Drop Calorimeter",
        "temperature_c": "25", "gas": "Ar", "r1_mm": "6.72", "r2_mm": "14.86"}


def test_header_lines_exact():
    assert header_lines(FULL) == [
        "# Sample: Al2O3", "# PowerSource: Keithley 2602B", "# ResponseDevice: Drop Calorimeter",
        "# Temperature: 25", "# Gas: Ar", "# InnerRadius: 6.72", "# OuterRadius: 14.86"]


def test_blank_and_missing_fields_are_omitted():
    assert header_lines(None) == [] and header_lines({}) == []
    assert header_lines({"sample": "  ", "gas": "Air", "temperature_c": ""}) == ["# Gas: Air"]


def test_typed_temperature_is_written_only_when_it_is_a_number():
    assert header_lines({"temperature_c": "800 °C"}) == ["# Temperature: 800"]
    assert header_lines({"temperature_c": "0,5"}) == ["# Temperature: 0.5"]
    assert header_lines({"temperature_c": "abc"}) == []
    assert header_lines({"r1_mm": "x", "r2_mm": "nan"}) == []


def test_parse_number():
    assert parse_number("800,5") == 800.5
    assert parse_number("6.72 mm") == 6.72
    assert parse_number("inf") is None and parse_number("") is None and parse_number(None) is None


def test_round_trip_through_the_header_parser():
    text = "\n".join(["# Started: 2026-11-26 10:00:00", "# Experiment: E"] + header_lines(FULL)) + "\nTime,V"
    h = parse_run_header(text)
    assert (h["sample"], h["power_source"], h["response_device"], h["gas"]) == (
        "Al2O3", "Keithley 2602B", "Drop Calorimeter", "Ar")
    assert (h["temperature_c"], h["r1_mm"], h["r2_mm"]) == (25.0, 6.72, 14.86)
    assert h["experiment"] == "E"


def test_old_header_has_none_for_every_new_key():
    h = parse_run_header("# Run 1\n# Started: 2026-11-26 10:00:00\n# Experiment: E\nTime,V")
    for key in ("sample", "power_source", "response_device", "gas", "temperature_c", "r1_mm", "r2_mm"):
        assert h[key] is None


def test_defaults():
    d = default_details("Keithley Instruments Inc., Model 2602B, 123", "Drop Calorimeter @ host")
    assert d == {"sample": "", "power_source": "Keithley 2602B", "response_device": "Drop Calorimeter",
                 "temperature_c": "", "gas": "Ar", "r1_mm": "6.72", "r2_mm": "14.86"}
    blank = default_details(None, None)
    assert blank["power_source"] == "" and blank["response_device"] == ""
    assert set(d) == {k for k, _ in FIELDS}


def test_radius_defaults_match_the_analysis_settings():
    from ctwa.ui import analysis_settings as a
    assert float(default_details(None, None)["r1_mm"]) == a.DEFAULT_R1
    assert float(default_details(None, None)["r2_mm"]) == a.DEFAULT_R2


# ---- Start writes them into the live CSV ----

@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_sweep_writes_the_details_into_the_run_csv(app, tmp_path):
    from test_equivalence_with_original_windows import _sweep, _window
    w = _window("2602B")
    try:
        w.auto_save_path = str(tmp_path)
        w._current_experiment_details = dict(FULL)
        _sweep(app, w)
        csvs = list(tmp_path.rglob("*.csv"))
        assert csvs
        text = max(csvs, key=lambda p: p.stat().st_mtime).read_text()
        assert "# PowerSource: Keithley 2602B" in text and "# InnerRadius: 6.72" in text
        h = parse_run_header(text)
        assert h["sample"] == "Al2O3" and h["r2_mm"] == 14.86
    finally:
        w.close()
