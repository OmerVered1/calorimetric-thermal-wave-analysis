"""Wiring checks for the main window module.

These check the parts the setup feature and the merge actually changed: that
the module imports, that the connect signature carries a profile through, and
that the CSV labels follow the reader's declared signals.
"""

import importlib
import inspect
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication  # noqa: E402

from calorimeter_reader import CalorimeterSignal  # noqa: E402


MODULES = ["ctwa.app"]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(params=MODULES)
def gui(request, app):
    return importlib.import_module(request.param)


def test_module_imports(gui):
    assert gui is not None


def test_connect_calorimeter_accepts_a_profile_name(gui):
    cls = next(
        obj for _n, obj in inspect.getmembers(gui, inspect.isclass)
        if hasattr(obj, "connect_calorimeter")
    )
    params = inspect.signature(cls.connect_calorimeter).parameters
    assert "profile_name" in params
    assert "interface" in params
    assert params["profile_name"].default is None


def test_setup_dialog_and_store_are_wired_in(gui):
    assert hasattr(gui, "CalorimeterSetupDialog")
    assert hasattr(gui, "SetupStore")


def test_connect_panel_exposes_the_setup_handlers(gui):
    cls = next(
        obj for _n, obj in inspect.getmembers(gui, inspect.isclass)
        if hasattr(obj, "_on_cal_sniff_toggled")
    )
    for name in ("_refresh_cal_setups", "_on_cal_setup_selected",
                 "_on_cal_setup_edit", "_on_cal_setup_delete", "_selected_setup"):
        assert hasattr(cls, name), f"{name} missing"


# ----- CSV columns -----------------------------------------------------------

def test_csv_labels_default_to_the_legacy_names(gui):
    gui.set_cal_column_labels([])
    header = gui._sweep_csv_header(["hf", "t", "ext_t"])
    assert header[-3:] == ["HF(mW)", "T(C)", "ExtT(C)"]


def test_csv_labels_follow_profile_signals(gui):
    gui.set_cal_column_labels([
        CalorimeterSignal("heat_flow", "Heat Flow", "mW"),
        CalorimeterSignal("qdos", "QDOS", "°C"),
    ])
    header = gui._sweep_csv_header(["heat_flow", "qdos"])
    assert header[-2:] == ["Heat Flow(mW)", "QDOS(°C)"]
    gui.set_cal_column_labels([])


def test_csv_label_for_a_unitless_signal_omits_the_brackets(gui):
    gui.set_cal_column_labels([CalorimeterSignal("count", "Count", "")])
    assert gui._sweep_csv_header(["count"])[-1] == "Count"
    gui.set_cal_column_labels([])


def test_csv_row_follows_the_same_channel_order(gui):
    class P:
        index, channel, computer_time, timestamp = 1, "a", "t", 0.0
        voltage = current = resistance = power = None
        cal_readings = {"heat_flow": 1.5, "qdos": 2.5}

    row = gui._sweep_csv_row(P(), ["qdos", "heat_flow"])
    assert row[-2:] == ["2.5", "1.5"]


def test_unknown_channel_key_falls_back_to_the_key_itself(gui):
    gui.set_cal_column_labels([])
    assert gui._sweep_csv_header(["mystery"])[-1] == "mystery"
