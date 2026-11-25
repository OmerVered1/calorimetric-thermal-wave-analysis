"""Statistics tab in the main window, packaging and the one delimited app.py block."""
from __future__ import annotations

import logging
import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEW_MODULES = ["ctwa.stats", "ctwa.stats.model", "ctwa.stats.filters", "ctwa.stats.aggregate", "ctwa.stats.dist",
               "ctwa.stats.specs", "ctwa.stats.view_state", "ctwa.ui.statistics", "ctwa.ui.statistics.chart_view",
               "ctwa.ui.statistics.legend_bar", "ctwa.ui.statistics.dist_items", "ctwa.ui.statistics.xy_items",
               "ctwa.ui.statistics.heatmap", "ctwa.ui.statistics.filter_panel", "ctwa.ui.statistics.controls",
               "ctwa.ui.statistics.summary_table", "ctwa.ui.statistics.tab", "pyqtgraph.exporters"]


@pytest.fixture(scope="module")
def app():
    logging.disable(logging.CRITICAL)
    for n in ("warning", "critical", "information"):
        setattr(QMessageBox, n, staticmethod(lambda *a, **k: None))
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    from ctwa import app as appmod
    appmod.MainWindow._check_license_agreement = lambda self: True
    w = appmod.MainWindow()
    w.auto_save_enabled = False
    w.auto_save_path = str(tmp_path)
    yield w
    w.close()


def names(w):
    return [w.tabs.tabText(i) for i in range(w.tabs.count())]


def test_statistics_tab_follows_analysis(window):
    n = names(window)
    # final order: Runs, Analysis, Calibration, Results, Statistics — Statistics comes after the others
    assert n.index("Statistics") > n.index("Analysis")
    if "Calibration" in n:
        assert n.index("Statistics") > n.index("Calibration")
    assert window.tabs.widget(n.index("Statistics")) is window.statistics_tab


def test_open_analysis_opens_that_analysis_in_history(window):
    # after the Plan 3 merge: clicking a point in Statistics shows that id in Results > History
    seen = []
    window.results_tab.show_history = lambda i: seen.append(i)   # instance attr; the signal is bound at build
    window.statistics_tab.open_analysis.emit(5)
    assert window.tabs.currentWidget() is window.results_tab
    assert window.results_tab.current_page() == "history" or seen == [5]


def test_open_analysis_brings_the_results_tab_forward(window):
    # after the Plan 3 merge the window has a Results tab: clicking a point opens it
    assert window.results_tab is not None
    window.statistics_tab.open_analysis.emit(5)
    assert window.tabs.currentWidget() is window.results_tab


def test_hiddenimports_list_every_new_module():
    text = open(os.path.join(ROOT, "keithley_suite.spec"), encoding="utf-8").read()
    assert "# Statistics tab (Plan 5)" in text
    for m in NEW_MODULES:
        assert "'%s'" % m in text, m


def test_app_block_markers_appear_once_and_enclose_the_wiring():
    text = open(os.path.join(ROOT, "ctwa", "app.py"), encoding="utf-8").read()
    start, end = "# --- Statistics tab (Plan 5) ---", "# --- end Statistics tab ---"
    assert text.count(start) == 1 and text.count(end) == 1
    block = text[text.index(start):text.index(end)]
    assert "StatisticsTab" in block and "tabs.addTab(self.statistics_tab" in block
    assert text.count("StatisticsTab") == block.count("StatisticsTab")
    assert text.index('tabs.addTab(self.analysis_tab, "Analysis")') < text.index(start)
