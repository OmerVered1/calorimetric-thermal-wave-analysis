"""New / Edit details / panel / persistence of an experiment's run details (offscreen MainWindow)."""

import os
import pathlib
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from ctwa.ui.experiment_details_dialog import ExperimentDetailsDialog  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _scratch_experiments_file(tmp_path, monkeypatch):
    """ExperimentStore binds EXPERIMENTS_FILE as a default argument, so patching the constant is
    too late: patch the default. The user's real experiments file is never written."""
    import ctwa.app
    path = str(tmp_path / "experiments.json")
    monkeypatch.setattr(ctwa.app.ExperimentStore.__init__, "__defaults__", (path,))
    monkeypatch.setattr(ctwa.app, "EXPERIMENTS_FILE", path)
    return path


def _window(model="2602B"):
    from test_equivalence_with_original_windows import _window as make
    return make(model)


def _answer(monkeypatch, name=None, **fields):
    """The next details dialog is answered with these values instead of being shown."""
    def fake_exec(self):
        if name is not None:
            self.name_edit.setText(name)
        for k, v in fields.items():
            w = self.edits[k]
            w.setCurrentText(v) if hasattr(w, "setCurrentText") else w.setText(v)
        self._on_ok()
        return QDialog.Accepted if self.result() == QDialog.Accepted else QDialog.Rejected
    monkeypatch.setattr(ExperimentDetailsDialog, "exec", fake_exec)


def test_dialog_refuses_empty_and_taken_names(app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    d = ExperimentDetailsDialog(None, "", {}, {"Taken"})
    d._on_ok()
    assert d.result() != QDialog.Accepted
    d.name_edit.setText("Taken")
    d._on_ok()
    assert d.result() != QDialog.Accepted
    d.name_edit.setText("Fresh")
    d._on_ok()
    assert d.result() == QDialog.Accepted and d.values()[0] == "Fresh"


def test_edit_dialog_has_no_name(app):
    d = ExperimentDetailsDialog(None, None, {"sample": "X", "gas": "Air"})
    name, vals = d.values()
    assert name is None and vals["sample"] == "X" and vals["gas"] == "Air"


def test_new_with_details_is_stored_and_shown(app, monkeypatch):
    w = _window()
    try:
        _answer(monkeypatch, name="E1", sample="Al2O3", temperature_c="25")
        w.experiments_sidebar._on_new_clicked()
        rec = w.experiment_store.get("E1")
        # defaults came from the connected simulated 2602B; no calorimeter connected
        assert rec["details"]["sample"] == "Al2O3"
        assert rec["details"]["power_source"] == "Keithley 2602B"
        assert rec["details"]["response_device"] == ""
        assert (rec["details"]["gas"], rec["details"]["r1_mm"], rec["details"]["r2_mm"]) == ("Ar", "6.72", "14.86")
        assert w._current_experiment_details == rec["details"]
        sb = w.experiments_sidebar
        assert "Sample: Al2O3" in sb.details_label.text()
        assert not sb.details_box.isHidden()
    finally:
        w.close()


def test_new_without_instrument_has_blank_device_defaults(app):
    from ctwa import app as merged
    merged.MainWindow._check_license_agreement = lambda self: True
    w = merged.MainWindow()
    try:
        d = w._connected_details_defaults()
        assert d["power_source"] == "" and d["response_device"] == ""
    finally:
        w.close()


def test_save_after_changing_a_sweep_keeps_the_details(app, monkeypatch):
    w = _window()
    try:
        _answer(monkeypatch, name="E1", sample="Al2O3")
        w.experiments_sidebar._on_new_clicked()
        w.sweep_list.stop_val.setValue(0.5)
        w._save_experiment("E1")
        assert w.experiment_store.get("E1")["details"]["sample"] == "Al2O3"
    finally:
        w.close()


def test_old_record_without_details_loads_saves_and_clones(app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    w = _window()
    try:
        w.experiment_store.save("Old", w._capture_state())  # no details key, as before this feature
        w.experiment_store.get("Old").pop("details", None)
        w._load_experiment("Old")
        sb = w.experiments_sidebar
        assert w._current_experiment_details == {}
        assert sb.details_label.text() == "" and sb.details_label.isHidden()
        from ctwa.experiment_details import header_lines
        assert header_lines(w._current_experiment_details) == []
        w._save_experiment("Old")
        w._clone_experiment("Old", "Old copy")
        assert w.experiment_store.get("Old copy").get("details") == {}
    finally:
        w.close()


def test_clone_copies_details_independently(app, monkeypatch):
    w = _window()
    try:
        _answer(monkeypatch, name="E1", sample="Al2O3")
        w.experiments_sidebar._on_new_clicked()
        w._clone_experiment("E1", "E2")
        w._clone_experiment("E1", "E3")
        e2 = w.experiment_store.get("E2")["details"]
        assert e2["sample"] == "Al2O3"
        e2["sample"] = "changed"
        assert w.experiment_store.get("E1")["details"]["sample"] == "Al2O3"
        assert w.experiment_store.get("E3")["details"]["sample"] == "Al2O3"
        # a stored (not loaded) source is copied too
        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        w._load_experiment("E2")
        w._clone_experiment("E3", "E4")
        assert w.experiment_store.get("E4")["details"]["sample"] == "Al2O3"
    finally:
        w.close()


def test_edit_details_saves_to_the_store_and_leaves_dirty_alone(app, monkeypatch):
    w = _window()
    try:
        _answer(monkeypatch, name="E1", sample="Al2O3")
        w.experiments_sidebar._on_new_clicked()
        sb = w.experiments_sidebar
        keep = dict(w.experiment_store.get("E1"))
        assert not sb.is_dirty()
        _answer(monkeypatch, sample="SiC", gas="Air")
        sb._on_edit_details_clicked()
        rec = w.experiment_store.get("E1")
        assert rec["details"]["sample"] == "SiC" and rec["details"]["gas"] == "Air"
        assert rec["sweep"] == keep["sweep"] and rec["notes"] == keep["notes"]
        assert not sb.is_dirty()
        assert "Sample: SiC" in sb.details_label.text()
        # and it is on disk
        from ctwa.app import ExperimentStore
        assert ExperimentStore().get("E1")["details"]["sample"] == "SiC"
        # a dirty experiment stays dirty
        sb.mark_dirty(True)
        _answer(monkeypatch, sample="SiO2")
        sb._on_edit_details_clicked()
        assert sb.is_dirty()
    finally:
        w.close()


def test_panel_is_hidden_with_no_experiment_and_never_touches_the_real_file(app, _scratch_experiments_file):
    w = _window()
    try:
        assert w.experiments_sidebar.details_box.isHidden()
        assert w.experiment_store.path == _scratch_experiments_file
    finally:
        w.close()
