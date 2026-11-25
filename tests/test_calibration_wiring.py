"""The Calibration tab inside the main window."""

import logging
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QMessageBox  # noqa: E402


@pytest.fixture(scope="module")
def app():
    logging.disable(logging.CRITICAL)
    for n in ("warning", "critical", "information"):
        setattr(QMessageBox, n, staticmethod(lambda *a, **k: None))
    return QApplication.instance() or QApplication([])


def _make(app, tmp_path):
    from ctwa import app as appmod
    appmod.MainWindow._check_license_agreement = lambda self: True
    w = appmod.MainWindow()
    w.auto_save_enabled = False
    w.auto_save_path = str(tmp_path)
    w.connect_instrument("2602B", simulate=True, simulation_resistance=100.0)
    return w


@pytest.fixture
def window(app, tmp_path):
    w = _make(app, tmp_path)
    yield w
    w.stop_sweep()
    end = time.monotonic() + 0.3
    while time.monotonic() < end:
        app.processEvents()
    w.close()


def names(w):
    return [w.tabs.tabText(i) for i in range(w.tabs.count())]


def test_calibration_tab_follows_analysis(window):
    n = names(window)
    assert n[n.index("Analysis") + 1] == "Calibration"


def test_it_is_a_calibration_tab_and_shown_once(window, monkeypatch):
    from ctwa.ui.calibration.calibration_tab import CalibrationTab
    tab = window.calibration_tab
    assert isinstance(tab, CalibrationTab)
    assert window.tabs.widget(names(window).index("Calibration")) is tab
    calls = []
    monkeypatch.setattr(tab, "on_shown", lambda: calls.append(1))
    window.tabs.setCurrentWidget(tab)
    assert calls == [1]
    window.tabs.setCurrentWidget(window.analysis_tab)
    window.tabs.setCurrentWidget(tab)
    assert len(calls) == 2  # the tab itself ignores repeats


def test_without_the_cloud_the_tab_says_so(app, tmp_path, monkeypatch):
    from ctwa import app as appmod

    def broken():
        raise RuntimeError("no keyring")
    monkeypatch.setattr(appmod, "_make_cloud_services", broken)
    w = _make(app, tmp_path)
    try:
        assert w.results_loader is None
        page = w.tabs.widget(names(w).index("Calibration"))
        assert isinstance(page, QLabel) and page.text() == "Results are not available."
        w.tabs.setCurrentWidget(page)
    finally:
        w.close()
