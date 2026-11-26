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
        assert w.run_details_form.values() == rec["details"]
        assert not w.experiments_sidebar.is_dirty()
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
        assert all(v == "" for v in w.run_details_form.values().values())
        assert not w.experiments_sidebar.is_dirty()
        from ctwa.experiment_details import header_lines
        assert header_lines(w.run_details_form.values()) == []
        w._save_experiment("Old")
        w._clone_experiment("Old", "Old copy")
        assert w.experiment_store.get("Old copy")["details"] == w.run_details_form.values()
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


def test_run_details_box_is_in_the_settings_tab_with_seven_fields(app):
    from ctwa.experiment_details import FIELDS
    w = _window()
    try:
        assert w.run_details.title() == "Run details"
        assert set(w.run_details_form.fields) == {k for k, _ in FIELDS} and len(FIELDS) == 7
        assert w.run_details.parent() is w.source_settings.parent()  # same page as the other settings
        assert not hasattr(w.experiments_sidebar, "edit_details_btn")
        assert not hasattr(w.experiments_sidebar, "details_label")
    finally:
        w.close()


def test_editing_the_box_marks_dirty_and_save_stores_it(app, monkeypatch):
    w = _window()
    try:
        _answer(monkeypatch, name="E1", sample="Al2O3")
        w.experiments_sidebar._on_new_clicked()
        assert not w.experiments_sidebar.is_dirty()
        w.run_details_form.fields["temperature_c"].textEdited.emit("5")  # a user edit
        w.run_details_form.fields["temperature_c"].setText("800")
        assert w.experiments_sidebar.is_dirty()
        w._save_experiment("E1")
        assert w.experiment_store.get("E1")["details"]["temperature_c"] == "800"
        assert not w.experiments_sidebar.is_dirty()
        # typed values are remembered for the dropdowns
        from ctwa.ui.details_form import remembered
        assert "Al2O3" in remembered(w.settings, "sample")
    finally:
        w.close()


def test_start_before_save_writes_the_box_values_into_the_header(app, monkeypatch):
    w = _window()
    try:
        _answer(monkeypatch, name="E1", sample="Al2O3")
        w.experiments_sidebar._on_new_clicked()
        w.run_details_form.set_values({"sample": "SiC", "temperature_c": "650", "gas": "Air"})
        w.run_details_form.fields["sample"].edited.emit()
        assert w.experiments_sidebar.is_dirty()
        lines = [r[0] for r in w._build_csv_metadata_rows([]) if r]
        assert "# Sample: SiC" in lines and "# Temperature: 650" in lines and "# Gas: Air" in lines
        assert w.experiment_store.get("E1")["details"]["sample"] == "Al2O3"  # not saved yet
    finally:
        w.close()


def test_loading_another_experiment_fills_the_box_without_dirtying(app, monkeypatch):
    w = _window()
    try:
        _answer(monkeypatch, name="E1", sample="Al2O3")
        w.experiments_sidebar._on_new_clicked()
        _answer(monkeypatch, name="E2", sample="SiC", temperature_c="300")
        w.experiments_sidebar._on_new_clicked()
        assert w.run_details_form.values()["sample"] == "SiC"
        w._load_experiment("E1")
        assert w.run_details_form.values()["sample"] == "Al2O3"
        assert w.run_details_form.values()["temperature_c"] == ""
        assert not w.experiments_sidebar.is_dirty()
    finally:
        w.close()


def test_sample_presets_include_names_from_the_results_loader(app, monkeypatch):
    w = _window()
    try:
        class FakeLoader:
            def rows(self):
                return [{"model_name": "unk foam "}, {"model_name": "Alumina"}, {"model_name": None}]
        w.results_loader = FakeLoader()
        w._refresh_detail_presets()
        combo = w.run_details_form.fields["sample"]
        items = [combo.itemText(i) for i in range(combo.count())]
        assert items == ["Alumina", "unk foam", "Fill in new\u2026"]
        # and the New dialog gets them too
        captured = {}

        def fake_exec(self):
            c = self.edits["sample"]
            captured["items"] = [c.itemText(i) for i in range(c.count())]
            return QDialog.Rejected
        monkeypatch.setattr(ExperimentDetailsDialog, "exec", fake_exec)
        w.experiments_sidebar._on_new_clicked()
        assert "unk foam" in captured["items"]
        w.results_loader = None  # no cloud: no database names, no crash
        assert w._sample_names() == []
    finally:
        w.close()


def test_never_touches_the_real_file(app, _scratch_experiments_file):
    w = _window()
    try:
        assert w.experiment_store.path == _scratch_experiments_file
    finally:
        w.close()
