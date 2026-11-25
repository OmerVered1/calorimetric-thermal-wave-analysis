"""History delete with confirmation and the 6-second Undo (Results tab, Task 10)."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from results_fakes import FakeLoader  # noqa: E402
from test_results_history_tab import ROWS, row, table_ids  # noqa: E402
from ctwa.ui.results.history_tab import HistoryTab  # noqa: E402
from ctwa.ui.results.undo_bar import UndoBar  # noqa: E402

DELAY = 20


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class Confirm:
    def __init__(self, answer=True):
        self.answer, self.asked = answer, []

    def __call__(self, title, message):
        self.asked.append((title, message))
        return self.answer


@pytest.fixture
def make(qapp):
    made = []

    def _make(rows=ROWS, answer=True, loader=None):
        loader = loader or FakeLoader(rows)
        confirm = Confirm(answer)
        tab = HistoryTab(loader, confirm=confirm, delay_ms=DELAY)
        tab.resize(1200, 700)
        tab.show()
        made.append(tab)
        return tab, loader, confirm
    yield _make
    for t in made:
        t.close()


def deletes(loader):
    return [c[1] for c in loader.calls if c[0] == "delete"]


def wait():
    QTest.qWait(DELAY * 4)


def test_cancel_changes_nothing(make):
    tab, loader, confirm = make(answer=False)
    tab.select_id(2)
    tab.delete_selected()
    assert confirm.asked == [("Delete this analysis?",
                              '"Stainless Steel" (ID 2) will be removed from the database permanently.')]
    wait()
    assert table_ids(tab) == [3, 2, 1] and tab.selected_id() == 2 and deletes(loader) == []
    assert tab.undo_bar.pending_ids() == []


def test_confirm_hides_row_selects_neighbour_and_waits(make):
    tab, loader, _ = make()
    tab.select_id(2)
    tab.delete_selected()
    assert table_ids(tab) == [3, 1]
    assert tab.selected_id() == 1                   # the next row, else the previous
    assert tab.undo_bar.texts() == ["Deleted! #2"]
    assert deletes(loader) == []
    tab.select_id(1)
    tab.delete_selected()                           # the last row: the previous one is selected
    assert tab.selected_id() == 3
    tab.undo_bar.flush()


def test_undo_within_delay_sends_nothing(make):          # Review Focus 3
    tab, loader, _ = make()
    tab.select_id(2)
    tab.delete_selected()
    tab.undo_bar.undo(2)
    assert table_ids(tab) == [3, 2, 1] and tab.selected_id() == 2
    assert tab.undo_bar.texts() == []
    wait()
    assert deletes(loader) == []


def test_expiry_sends_exactly_once(make):
    tab, loader, _ = make()
    tab.select_id(2)
    tab.delete_selected()
    wait()
    assert deletes(loader) == [2]
    wait()
    assert deletes(loader) == [2]
    assert table_ids(tab) == [3, 1]                 # still hidden until the refresh confirms it
    assert tab.undo_bar.texts() == []


def test_two_deletes_have_their_own_timers(make):
    tab, loader, _ = make()
    tab.select_id(2)
    tab.delete_selected()
    tab.select_id(3)
    tab.delete_selected()
    assert tab.undo_bar.texts() == ["Deleted! #2", "Deleted! #3"]
    tab.undo_bar.undo(2)
    assert tab.undo_bar.pending_ids() == [3]
    wait()
    assert deletes(loader) == [3]
    assert table_ids(tab) == [2, 1]


def test_flush_pending_sends_all_at_once_and_stops_timers(make):
    tab, loader, _ = make()
    tab.select_id(2)
    tab.delete_selected()
    tab.select_id(3)
    tab.delete_selected()
    tab.flush_pending()
    assert sorted(deletes(loader)) == [2, 3]
    wait()
    assert sorted(deletes(loader)) == [2, 3]        # no second send from the timers
    tab.flush_pending()
    assert len(deletes(loader)) == 2


def test_closing_the_tab_sends_pending_deletes(make):
    tab, loader, _ = make()
    tab.select_id(2)
    tab.delete_selected()
    tab.close()
    assert deletes(loader) == [2]
    wait()
    assert deletes(loader) == [2]


def test_failure_brings_the_row_back_with_the_message(make):          # Review Focus 4
    tab, loader, _ = make()
    msgs, logins = [], []
    tab.message.connect(msgs.append)
    tab.login_needed.connect(lambda: logins.append(1))
    tab.select_id(2)
    tab.delete_selected()
    wait()
    token = loader._token
    loader.write_failed.emit("delete", token, "offline", "no route")
    assert msgs == ["Failed to delete: no route"] and logins == []
    assert table_ids(tab) == [3, 2, 1]
    assert tab.error_text() == "Failed to delete: no route"
    tab.select_id(2)
    assert tab.selected_id() == 2                   # selectable again
    tab.delete_selected()                           # and can be deleted again
    wait()
    assert deletes(loader) == [2, 2]


def test_login_failure_asks_for_login_once(make):
    tab, loader, _ = make()
    logins = []
    tab.login_needed.connect(lambda: logins.append(1))
    tab.select_id(2)
    tab.delete_selected()
    wait()
    loader.write_failed.emit("delete", loader._token, "login", "Not logged in")
    loader.failed.emit("login", "Not logged in")    # the loader reports it a second way: still one prompt
    assert logins == [1]
    assert table_ids(tab) == [3, 2, 1]


def test_read_error_never_settles_a_delete(make):
    tab, loader, _ = make()
    msgs = []
    tab.message.connect(msgs.append)
    tab.select_id(2)
    tab.delete_selected()
    loader.failed.emit("offline", "refresh failed")     # during the undo window
    assert table_ids(tab) == [3, 1] and msgs == []
    wait()
    loader.failed.emit("server", "graph fetch failed")  # while the delete is in flight
    assert table_ids(tab) == [3, 1] and msgs == []
    loader.write_done.emit("delete", loader._token, None)
    loader.set_rows([r for r in ROWS if r["id"] != 2])
    assert table_ids(tab) == [3, 1] and tab.pending_ids() == []


def test_failure_of_other_operations_is_ignored(make):
    tab, loader, _ = make()
    msgs = []
    tab.message.connect(msgs.append)
    tab.select_id(2)
    tab.delete_selected()
    wait()
    loader.write_failed.emit("update", loader._token, "offline", "x")
    loader.write_failed.emit("delete", loader._token + 7, "offline", "x")   # not our token
    assert msgs == [] and table_ids(tab) == [3, 1]


def test_failure_that_arrives_before_the_token_returns(make):
    class Eager(FakeLoader):
        def apply_delete(self, id):
            self.calls.append(("delete", id))
            self.write_failed.emit("delete", 99, "error", "The results loader is closed")
            return 99
    tab, loader, _ = make(loader=Eager(ROWS))
    tab.select_id(2)
    tab.delete_selected()
    wait()
    assert table_ids(tab) == [3, 2, 1] and tab.pending_ids() == []
    assert tab.error_text() == "Failed to delete: The results loader is closed"


def test_refresh_during_undo_window_keeps_the_row_hidden_and_sends_nothing(make):
    tab, loader, _ = make()
    tab.select_id(2)
    tab.delete_selected()
    loader.set_rows(ROWS)                            # a refresh that still lists the row
    assert table_ids(tab) == [3, 1] and tab.selected_id() == 1
    assert deletes(loader) == []
    tab.undo_bar.undo(2)
    assert table_ids(tab) == [3, 2, 1]
    wait()
    assert deletes(loader) == []


def test_refresh_removing_the_row_before_expiry_sends_nothing(make):
    tab, loader, _ = make()
    tab.select_id(2)
    tab.delete_selected()
    loader.set_rows([r for r in ROWS if r["id"] != 2])   # deleted elsewhere meanwhile
    assert tab.pending_ids() == []
    wait()
    assert deletes(loader) == []                     # nothing left to delete


def test_double_delete_of_same_id_is_sent_once(make):
    tab, loader, _ = make()
    tab.select_id(2)
    tab.delete_selected()
    assert tab.undo_bar.add(2) is False             # the same row can't be queued twice
    tab._send(2)
    tab._send(2)
    wait()
    assert deletes(loader) == [2]


def test_delete_with_nothing_selected_does_nothing(make):
    tab, loader, confirm = make(rows=[])
    tab.delete_selected()
    assert confirm.asked == [] and deletes(loader) == []


def test_title_count_leaves_out_pending_but_combo_keeps_it(make):
    tab, _, _ = make()
    tab.select_id(2)
    tab.delete_selected()
    assert tab.title_text() == "All Analyses (2 total)"
    assert tab.combo.count() == 3
    tab.set_search("steel")
    assert tab.title_text() == "All Analyses (1 / 2 total)"
    tab.undo_bar.flush()


def test_undo_bar_stands_alone(qapp):
    bar = UndoBar()
    got, exp = [], []
    bar.undone.connect(got.append)
    bar.expired.connect(exp.append)
    assert bar.add(7, 30) is True
    assert bar.texts() == ["Deleted! #7"]
    bar.undo(7)
    bar.undo(7)
    assert got == [7] and bar.pending_ids() == []
    bar.add(8, 20)
    bar.add(9, 20)
    bar.flush()
    assert exp == [8, 9]
    QTest.qWait(80)
    assert exp == [8, 9]


def test_deleting_the_tab_stops_timers_without_sending(make, qapp):
    loader = FakeLoader(ROWS)
    tab = HistoryTab(loader, confirm=Confirm(True), delay_ms=DELAY)
    tab.select_id(2)
    tab.delete_selected()
    tab.deleteLater()
    QApplication.sendPostedEvents(None, 0)
    QTest.qWait(DELAY * 4)
    assert deletes(loader) == []
