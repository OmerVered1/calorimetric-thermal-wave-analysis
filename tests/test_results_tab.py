"""The Results tab container (Task 13)."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from results_fakes import FakeLoader  # noqa: E402
from test_results_history_tab import ROWS, row  # noqa: E402
from ctwa.ui.results.results_tab import ResultsTab  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def make(qapp):
    made = []

    def _make(rows=ROWS, loader=None):
        loader = loader or FakeLoader(rows)
        tab = ResultsTab(loader)
        tab.resize(1200, 800)
        tab.show()
        made.append(tab)
        return tab, loader
    yield _make
    for t in made:
        t.close()


def test_titles(make):
    tab, _ = make()
    assert [tab.tabs.tabText(i) for i in range(tab.tabs.count())] == ["Summary", "History", "Compare"]
    assert tab.current_page() == "Summary"


def test_summary_compare_goes_to_compare(make):
    rows = [row(i) for i in range(1, 5)]
    tab, _ = make(rows)
    tab.summary.select_all.click()
    tab.summary.compare_button.click()
    assert tab.current_page() == "Compare"
    assert sorted(tab.compare.ids()) == [1, 2, 3, 4]


def test_history_open_in_viewer(make):
    tab, _ = make()
    tab.show_history(2)
    assert tab.current_page() == "History" and tab.history.selected_id() == 2
    tab.history.open_button.click()
    assert tab.current_page() == "Compare" and tab.compare.ids() == [2]


def test_show_summary_filters(make):
    tab, _ = make()
    tab.show_compare([1])
    tab.show_summary(ids=[1, 2])
    assert tab.current_page() == "Summary" and tab.summary.shown_count() == 2
    tab.show_summary(query="zzzz-nothing")
    assert tab.summary.shown_count() == 0


def test_login_needed_once_per_window(make):
    tab, _ = make()
    got = []
    tab.login_needed.connect(lambda: got.append(1))
    tab.summary.login_needed.emit()
    tab.history.login_needed.emit()
    assert got == [1]


def test_refresh_once_on_first_show(make):
    tab, loader = make()
    assert loader.calls.count(("refresh",)) == 1
    tab.hide()
    tab.show()
    assert loader.calls.count(("refresh",)) == 1


def test_flush_pending_forwards(qapp):
    loader = FakeLoader(ROWS)
    tab = ResultsTab(loader)
    tab.history._confirm = lambda t, m: True
    tab.show()
    tab.history.select_id(1)
    tab.history.delete_selected()
    assert not [c for c in loader.calls if c[0] == "delete"]
    tab.flush_pending()
    assert [c for c in loader.calls if c[0] == "delete"] == [("delete", 1)]
    tab.close()


def test_status_line_shows_and_clears(make):
    tab, _ = make()
    tab.history.message.emit("Failed to delete: x")
    assert tab.status_text() == "Failed to delete: x"
    tab._status_timer.timeout.emit()
    assert tab.status_text() == ""


def test_offline_empty_pages_do_not_raise(make):
    tab, loader = make([])
    loader.failed.emit("offline", "no network")
    QTest.qWait(20)
    for i in range(tab.tabs.count()):
        tab.tabs.setCurrentIndex(i)
        QApplication.processEvents()
