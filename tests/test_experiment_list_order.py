"""The experiment list: newest created first, date beside each name, lookups by name not text."""

import json
import os
import pathlib
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def store_path(tmp_path, monkeypatch):
    import ctwa.app
    path = str(tmp_path / "experiments.json")
    monkeypatch.setattr(ctwa.app.ExperimentStore.__init__, "__defaults__", (path,))
    monkeypatch.setattr(ctwa.app, "EXPERIMENTS_FILE", path)
    records = [
        {"name": "mid", "created_at": "2026-05-10T09:00:00"},
        {"name": "Zed", "created_at": "2026-01-02T09:00:00"},
        {"name": "new", "created_at": "2026-11-20T23:59:59"},
        {"name": "undated b"},
        {"name": "Undated a"},
    ]
    with open(path, "w") as f:
        json.dump({"experiments": records}, f)
    return path


def _window():
    from test_equivalence_with_original_windows import _window as make
    return make("2602B")


def _texts(sb):
    return [sb.list_widget.item(i).text() for i in range(sb.list_widget.count())]


def _row(sb, name):
    for i in range(sb.list_widget.count()):
        if sb.list_widget.item(i).data(Qt.UserRole) == name:
            return i
    raise AssertionError(name)


def test_store_order_newest_first_undated_last_alphabetical(app, store_path):
    from ctwa.app import ExperimentStore
    assert ExperimentStore().names_by_created() == ["new", "mid", "Zed", "Undated a", "undated b"]


def test_items_show_name_and_date(app, store_path):
    w = _window()
    try:
        sb = w.experiments_sidebar
        assert _texts(sb) == ["new   20/11/2026", "mid   10/05/2026", "Zed   02/01/2026",
                              "Undated a", "undated b"]
        assert sb.list_widget.item(0).data(Qt.UserRole) == "new"
    finally:
        w.close()


def test_selected_name_and_highlight_follow_the_name(app, store_path):
    w = _window()
    try:
        sb = w.experiments_sidebar
        sb.list_widget.setCurrentRow(_row(sb, "mid"))
        assert sb._selected_name() == "mid"
        sb.set_current("Zed")
        assert sb.list_widget.currentRow() == _row(sb, "Zed")
        assert sb._selected_name() == "Zed"
    finally:
        w.close()


def test_load_rename_clone_delete_act_on_the_right_experiment(app, store_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    w = _window()
    try:
        sb = w.experiments_sidebar
        # double-click loads by name, not by the "name   date" text
        sb._on_item_double_clicked(sb.list_widget.item(_row(sb, "mid")))
        assert w._current_experiment_name == "mid"
        # rename keeps the date and the position; selection stays on the renamed one
        monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("mid2", True)))
        sb._on_rename_clicked()
        assert w._current_experiment_name == "mid2" and w.experiment_store.get("mid") is None
        assert _texts(sb)[:3] == ["new   20/11/2026", "mid2   10/05/2026", "Zed   02/01/2026"]
        assert sb.list_widget.currentRow() == _row(sb, "mid2")
        # clone the selected (Zed) one: the copy is the newest and named after Zed
        sb.list_widget.setCurrentRow(_row(sb, "Zed"))
        monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Zed copy", True)))
        sb._on_clone_clicked()
        assert w.experiment_store.get("Zed copy") is not None
        assert sb.list_widget.item(0).data(Qt.UserRole) == "Zed copy"
        assert w._current_experiment_name == "mid2"  # clone does not switch
        assert sb.list_widget.currentRow() == _row(sb, "mid2")
        # delete the selected one only
        sb.list_widget.setCurrentRow(_row(sb, "new"))
        sb._on_delete_clicked()
        assert w.experiment_store.get("new") is None and w.experiment_store.get("Zed") is not None
        assert "new" not in [sb.list_widget.item(i).data(Qt.UserRole) for i in range(sb.list_widget.count())]
    finally:
        w.close()
