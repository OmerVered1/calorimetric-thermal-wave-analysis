"""The Results tab inside the main window (Task 14)."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from results_fakes import FakeLoader  # noqa: E402
from test_results_history_tab import ROWS  # noqa: E402


@pytest.fixture(scope="module")
def app():
    for n in ("warning", "critical", "information"):
        setattr(QMessageBox, n, staticmethod(lambda *a, **k: None))
    return QApplication.instance() or QApplication([])


class ClosingLoader(FakeLoader):
    shutdowns = []
    log = []

    def __init__(self, client=None, parent=None):
        super().__init__(ROWS)

    def apply_delete(self, id):
        ClosingLoader.log.append(("delete", id))
        return super().apply_delete(id)

    def shutdown(self, timeout_ms=500):
        ClosingLoader.log.append(("shutdown", timeout_ms))


def make_window(monkeypatch):
    from ctwa import app as appmod
    appmod.MainWindow._check_license_agreement = lambda self: True
    return appmod.MainWindow()


def test_results_tab_after_analysis_and_wired(app, monkeypatch):
    from ctwa.ui.results.results_tab import ResultsTab
    w = make_window(monkeypatch)
    try:
        names = [w.tabs.tabText(i) for i in range(w.tabs.count())]
        assert names.index("Runs") < names.index("Analysis") < names.index("Results")
        assert isinstance(w.results_tab, ResultsTab) and w.tabs.widget(names.index("Results")) is w.results_tab
        assert w.results_tab.summary is not None
    finally:
        w.close()


def test_no_cloud_shows_unavailable(app, monkeypatch):
    from ctwa import app as appmod

    def broken():
        raise RuntimeError("no keyring")
    monkeypatch.setattr(appmod, "_make_cloud_services", broken)
    w = make_window(monkeypatch)
    try:
        assert w.results_loader is None
        assert w.results_tab.status_text() == "Results are not available."
        w.results_tab.flush_pending()
    finally:
        w.close()


def test_close_flushes_delete_before_loader_shutdown(app, monkeypatch):
    import ctwa.ui.results_loader as rl
    monkeypatch.setattr(rl, "ResultsLoader", ClosingLoader)
    ClosingLoader.log = []
    w = make_window(monkeypatch)
    h = w.results_tab.history
    h._confirm = lambda t, m: True
    h.select_id(1)
    h.delete_selected()
    assert ClosingLoader.log == []                 # still inside the Undo window
    w.close()
    assert ClosingLoader.log == [("delete", 1), ("shutdown", 3000)]


def test_close_with_nothing_pending_keeps_500(app, monkeypatch):
    import ctwa.ui.results_loader as rl
    monkeypatch.setattr(rl, "ResultsLoader", ClosingLoader)
    ClosingLoader.log = []
    w = make_window(monkeypatch)
    w.close()
    assert ClosingLoader.log == [("shutdown", 500)]
