"""MarkSection and ReferenceTable (Plan 4, Task 6)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402

from ctwa.analysis.calibration_logic import num  # noqa: E402
from ctwa.ui.calibration.mark_section import MarkSection  # noqa: E402
from ctwa.ui.calibration.reference_table import ReferenceTable  # noqa: E402
from ctwa.ui.calibration.state import CalibrationState  # noqa: E402
from ctwa.ui.calibration.texts import TEXT  # noqa: E402
from ctwa.ui.calibration.writes import WriteQueue  # noqa: E402
from tests.calibration_fakes import FakeLoader, get_app, make_row, make_rows, wait_until  # noqa: E402


@pytest.fixture
def qapp():
    return get_app()


def build(rows=None):
    loader = FakeLoader()
    state = CalibrationState()
    state.set_rows(rows if rows is not None else make_rows())
    queue = WriteQueue(loader)
    msgs = []
    on_message = lambda t, k: msgs.append((t, k))  # noqa: E731
    mark = MarkSection(state, queue, on_message)
    table = ReferenceTable(state, queue, on_message)
    return loader, state, queue, mark, table, msgs


@pytest.fixture
def env(qapp):
    return build()


def ids_shown(mark):
    return [mark.list.item(i).data(Qt.UserRole) for i in range(mark.list.count())]


def tick(mark, ids):
    for i in range(mark.list.count()):
        it = mark.list.item(i)
        if it.data(Qt.UserRole) in ids:
            it.setCheckState(Qt.Checked)


def test_filters(env):
    """Review 4: key '780.5' and key '800' for 800.0."""
    loader, state, queue, mark, table, msgs = env
    assert ids_shown(mark) == [99, 100, 101, 102, 103]   # no references, no copies
    mark.material.setCurrentIndex(mark.material.findData("Stainless Steel"))
    assert ids_shown(mark) == [99, 100, 103]
    assert [mark.temp.itemData(i) for i in range(mark.temp.count())] == ["", "780.5", "800", "831"]
    mark.temp.setCurrentIndex(mark.temp.findData("780.5"))
    assert ids_shown(mark) == [100]
    mark.temp.setCurrentIndex(mark.temp.findData("800"))
    assert ids_shown(mark) == [99]
    # the same rows with an int temperature: the choice is kept
    rows = [dict(r, temperature_c=800) if r.get("temperature_c") == 800.0 else r for r in make_rows()]
    state.set_rows(rows)
    assert state.mark_filter_temp == "800" and ids_shown(mark) == [99]
    assert mark.temp.currentData() == "800"


def test_filter_survives_refresh_and_material_change_clears_temp(env):
    _, state, _, mark, _, _ = env
    mark.material.setCurrentIndex(mark.material.findData("Stainless Steel"))
    mark.temp.setCurrentIndex(mark.temp.findData("780.5"))
    state.set_rows(make_rows())
    assert mark.temp.currentData() == "780.5"
    mark.material.setCurrentIndex(mark.material.findData("Al"))
    assert state.mark_filter_temp == "" and mark.temp.currentData() == ""


def test_mark_three_runs(env):
    loader, state, queue, mark, table, msgs = env
    mark.alpha.setText("5.829")
    tick(mark, [99, 100, 103])
    assert mark.mark_button.text() == "Mark as reference (3)" and mark.mark_button.isEnabled()
    mark.mark_button.click()
    assert wait_until(lambda: not queue.busy and msgs)
    assert loader.ops == [("update", i, {"is_reference": True, "reference_alpha_mm2s": 5.829})
                          for i in (99, 100, 103)]
    assert msgs[-1][0] == "Marked as reference: 3/3"
    assert state.mark_ids == []


def test_mark_failure_reported_and_rest_sent(env):
    loader, state, queue, mark, table, msgs = env
    loader.fail_at = {1: ("server", "boom")}
    mark.alpha.setText("5.829")
    tick(mark, [99, 100, 103])
    mark.mark_button.click()
    assert wait_until(lambda: msgs)
    assert msgs[-1][0] == "Marked as reference: 2/3 · #100: boom"
    assert len(loader.ops) == 3


@pytest.mark.parametrize("text", ["0", "", "-1", "abc"])
def test_mark_bad_alpha_queues_nothing(env, text):
    loader, state, queue, mark, table, msgs = env
    mark.alpha.setText(text)
    tick(mark, [99])
    mark.mark_button.click()
    assert loader.ops == [] and msgs == [(TEXT["errAlphaRequired"], "error")]


def test_mark_button_state(env):
    loader, state, queue, mark, table, msgs = env
    assert mark.mark_button.text() == "Mark as reference (0)" and not mark.mark_button.isEnabled()
    mark.alpha.setText("5")
    tick(mark, [99])
    assert mark.mark_button.isEnabled()
    loader.hang_at = {0}
    mark.mark_button.click()
    assert queue.busy and not mark.mark_button.isEnabled()
    mark.mark_button.click()
    assert len(loader.ops) == 1
    assert mark.progress_label.text() == "1 / 1"


def test_select_all_and_clear(env):
    _, state, _, mark, _, _ = env
    mark.material.setCurrentIndex(mark.material.findData("Stainless Steel"))
    mark.select_all.click()
    assert sorted(state.mark_ids) == [99, 100, 103]
    mark.clear.click()
    assert state.mark_ids == []


def test_warnings(env):
    _, state, _, mark, _, _ = env
    tick(mark, [99, 101])   # SS and Al
    assert not mark.mixed_label.isHidden()
    assert "Al" in mark.mixed_label.text() and "Stainless Steel" in mark.mixed_label.text()
    assert mark.spread_label.isHidden()
    state.mark_ids = [99, 103]   # 800 and 831
    assert mark.mixed_label.isHidden()
    assert not mark.spread_label.isHidden() and "31.0 °C" in mark.spread_label.text()
    state.mark_ids = [99, 100]   # 800 and 780.5
    assert mark.spread_label.isHidden()


def test_preset_fills_alpha_and_filter(env):
    _, state, _, mark, _, _ = env
    state.apply_preset({"material_name": "Al", "alpha_mm2s": 64.0})
    assert mark.alpha.text() == "64" and mark.material.currentData() == "Al"
    assert ids_shown(mark) == [101]


def test_empty_candidates(qapp):
    _, state, _, mark, _, _ = build([])
    assert not mark.empty_label.isHidden()


# ---- reference table ----

def edit(table, i, text):
    e = table.alpha_edits[i]
    e.setText(text)
    e.editingFinished.emit()


def test_table_rows(env):
    _, state, _, mark, table, _ = env
    assert sorted(table.alpha_edits) == [10, 11, 12, 13, 14]
    r = table._row_of[10]
    assert table.table.item(r, 1).text() == "800 °C" and table.table.item(r, 2).text() == "75 s"
    assert table.alpha_edits[10].text() == "5.829"
    assert table.table.item(r, 6).text() == "%s s" % ("%.2f" % state.ref_lags[0].lag)


def test_reference_without_alpha_shows_dashes(qapp):
    rows = make_rows()
    rows[0] = dict(rows[0], reference_alpha_mm2s=None)
    _, _, _, _, table, _ = build(rows)
    r = table._row_of[10]
    assert table.table.item(r, 5).text() == "—" and table.table.item(r, 6).text() == "—"
    assert table.alpha_edits[10].text() == ""


def test_alpha_cell_change_sends_only_alpha(env):
    loader, state, queue, mark, table, msgs = env
    edit(table, 11, "4")
    assert wait_until(lambda: not queue.busy)
    assert loader.ops == [("update", 11, {"reference_alpha_mm2s": 4.0})]


@pytest.mark.parametrize("text", ["5.829", "0", "-2", "abc", ""])
def test_alpha_cell_invalid_or_unchanged_sends_nothing(env, text):
    """Review 5."""
    loader, _, queue, _, table, _ = env
    edit(table, 11, text)
    assert loader.ops == []
    assert table.alpha_edits[11].text() == "5.829"


def test_alpha_cell_double_commit_one_update(env):
    loader, _, queue, _, table, _ = env
    e = table.alpha_edits[11]
    e.setText("4")
    e.editingFinished.emit()
    e.editingFinished.emit()
    assert wait_until(lambda: not queue.busy)
    assert len(loader.ops) == 1
    assert table.status_labels[11].text() == TEXT["cellSaved"]


def test_alpha_cell_failure(env):
    loader, _, queue, _, table, msgs = env
    loader.fail_at = {0: ("server", "boom")}
    edit(table, 11, "4")
    assert wait_until(lambda: msgs)
    assert table.status_labels[11].text() == TEXT["cellFailed"]
    assert table.alpha_edits[11].text() == "5.829"


def test_unmark(env):
    loader, state, queue, _, table, _ = env
    state.selected_ref_ids = [10, 11]
    table.unmark_buttons[11].click()
    assert wait_until(lambda: not queue.busy)
    assert loader.ops == [("update", 11, {"is_reference": False, "reference_alpha_mm2s": None})]
    assert state.selected_ref_ids == [10]
    # after the refresh (the row is no longer a reference) it is gone from the table
    state.set_rows([dict(r, is_reference=False, reference_alpha_mm2s=None) if r["id"] == 11 else r
                    for r in make_rows()])
    assert 11 not in table.alpha_edits and state.selected_ref_ids == [10]


def test_unmark_disabled_while_busy(env):
    loader, _, queue, _, table, _ = env
    loader.hang_at = {0}
    table.unmark_buttons[10].click()
    assert not table.unmark_buttons[11].isEnabled() and not table.alpha_edits[11].isEnabled()
    table.unmark(11)
    assert len(loader.ops) == 1


def test_empty_and_search(qapp):
    _, _, _, _, table, _ = build([make_row(99)])
    assert not table.empty_label.isHidden()
    _, _, _, _, table, _ = build()
    table.search.setText("#12")
    assert table.shown_ids() == [12]


def test_failed_ids_stay_selected(env):
    """Review item (d): only the ids that were written are cleared from the selection."""
    loader, state, queue, mark, table, msgs = env
    loader.fail_at = {1: ("server", "boom")}
    mark.alpha.setText("5.829")
    tick(mark, [99, 100, 103])
    mark.mark_button.click()
    assert wait_until(lambda: msgs and not queue.busy)
    assert state.mark_ids == [100]


def test_login_abort_keeps_unwritten_ids(env):
    loader, state, queue, mark, table, msgs = env
    loader.fail_at = {1: ("login", "no")}
    mark.alpha.setText("5.829")
    tick(mark, [99, 100, 103])
    mark.mark_button.click()
    assert wait_until(lambda: msgs and not queue.busy)
    assert state.mark_ids == [100, 103]


def test_typed_alpha_survives_rows_changed(env):
    """Review item (b): a rows_changed while the user types in an alpha cell keeps the text."""
    loader, state, queue, mark, table, msgs = env
    edit = table.alpha_edits[10]
    edit.setText("4.5")
    rows = [dict(r, raw_lag_dt=r["raw_lag_dt"] + 1) if r["id"] == 11 else r for r in make_rows()]
    state.set_rows(rows)
    assert table.alpha_edits[10] is edit and edit.text() == "4.5"
    # after the edit finishes the table catches up
    edit.setText("5.829")
    table._after_edit()
    assert wait_until(lambda: table.alpha_edits[10] is not edit)
    assert table.alpha_edits[10].text() == "5.829"


def test_committed_alpha_edit_does_not_block_refresh(env):
    """Review fix 3: Enter keeps focus in the cell and "0.50" is the saved 0.5; the next rows update shows."""
    from ctwa.analysis.calibration import true_lag_for_alpha
    loader, state, queue, mark, table, msgs = env
    edit = table.alpha_edits[10]
    edit.hasFocus = lambda: True          # focus stays in the cell after Enter
    edit.setText("0.50")
    edit.editingFinished.emit()
    assert wait_until(lambda: loader.ops and not queue.busy)
    assert loader.ops[-1] == ("update", 10, {"reference_alpha_mm2s": 0.5})
    rows = [dict(r, reference_alpha_mm2s=0.5) if r["id"] == 10 else r for r in make_rows()]
    state.set_rows(rows)
    assert wait_until(lambda: table.alpha_edits[10] is not edit)
    row = next(r for r in rows if r["id"] == 10)
    assert table.table.item(0, 5).text() == "%s s" % num(true_lag_for_alpha(row, 0.5))
    assert table.alpha_edits[10].text() == "0.5"
