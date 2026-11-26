"""DetailsForm and its preset helpers (no MainWindow)."""

import os
import sys
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from ctwa import theme  # noqa: E402
from ctwa.experiment_details import FILL_IN_NEW  # noqa: E402
from ctwa.ui.details_form import (DetailsForm, PresetCombo, presets_for, remember,  # noqa: E402
                                  remembered)
from ctwa.ui.experiment_details_dialog import ExperimentDetailsDialog  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)


def _items(c):
    return [c.itemText(i) for i in range(c.count())]


def test_fill_in_new_text_is_exact():
    assert FILL_IN_NEW == "Fill in new…"


def test_combos_hold_presets_then_fill_in_new_last(app, settings):
    f = DetailsForm()
    f.set_presets("sample", ["A", "B"])
    assert _items(f.fields["sample"]) == ["A", "B", FILL_IN_NEW]
    assert _items(f.fields["power_source"])[:4] == ["Keithley 2602B", "Keithley 2611A",
                                                    "Keithley 2450", "Keithley 6430"]
    assert _items(f.fields["power_source"])[-1] == FILL_IN_NEW
    assert _items(f.fields["response_device"]) == ["C80", "Drop Calorimeter", FILL_IN_NEW]


def test_choosing_fill_in_new_clears_and_never_saves_the_literal(app):
    c = PresetCombo(["A"])
    c.setEditText("A")
    c.activated.emit(c.findText(FILL_IN_NEW))
    assert c.currentText() == "" and c.value() == ""
    c.setEditText(FILL_IN_NEW)
    assert c.value() == ""


def test_typed_value_and_unknown_value_are_kept(app):
    f = DetailsForm()
    f.set_values({"sample": "Keithley 2400", "temperature_c": "800", "gas": "N2"})
    v = f.values()
    assert v["sample"] == "Keithley 2400" and v["temperature_c"] == "800" and v["gas"] == "N2"
    f.set_presets("sample", ["X"])  # refreshing presets keeps the current value
    assert f.values()["sample"] == "Keithley 2400"
    f.fields["power_source"].setEditText("  My SMU ")
    assert f.values()["power_source"] == "My SMU"


def test_set_values_emits_nothing_but_user_edits_do(app):
    f = DetailsForm()
    hits = []
    f.changed.connect(lambda: hits.append(1))
    f.set_values({"sample": "A", "temperature_c": "5", "gas": "Air"})
    assert hits == []
    f.fields["temperature_c"].textEdited.emit("6")
    assert hits == [1]


def test_temperature_placeholder_and_colour(app):
    f = DetailsForm()
    t = f.fields["temperature_c"]
    assert t.placeholderText() == "leave blank = automatic"
    assert t.palette().color(QPalette.PlaceholderText).name().lower() == theme.P.text_disabled.lower()


def test_remember_caps_orders_and_dedupes(app, settings):
    for i in range(40):
        remember(settings, {"sample": "s%d" % i})
    r = remembered(settings, "sample")
    assert len(r) == 30 and r[0] == "s39"
    remember(settings, {"sample": " s20 "})
    r = remembered(settings, "sample")
    assert r[0] == "s20" and r.count("s20") == 1 and len(r) == 30
    remember(settings, {"sample": FILL_IN_NEW, "gas": "Ar"})
    assert FILL_IN_NEW not in remembered(settings, "sample")
    assert remembered(settings, "gas") == []


def test_presets_for_order_and_dedupe(app, settings):
    remember(settings, {"sample": "typed", "response_device": "C80"})
    assert presets_for("sample", settings, ["db1", "db1", " db2 ", "typed"]) == ["db1", "db2", "typed"]
    assert presets_for("response_device", settings) == ["C80", "Drop Calorimeter"]
    assert presets_for("power_source", None)[0] == "Keithley 2602B"


def test_dialog_still_returns_name_and_details_and_refuses_bad_names(app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    d = ExperimentDetailsDialog(None, "", {"sample": "S"}, {"Taken"})
    d._on_ok()
    assert d.result() != QDialog.Accepted
    d.name_edit.setText("Taken")
    d._on_ok()
    assert d.result() != QDialog.Accepted
    d.name_edit.setText("Fresh")
    d._on_ok()
    assert d.result() == QDialog.Accepted
    name, vals = d.values()
    assert name == "Fresh" and vals["sample"] == "S"
