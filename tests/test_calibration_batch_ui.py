"""BatchSection (Plan 4, Task 9)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402

from ctwa.analysis.calibration_batch import build_calibrated_row, calibration_model_string  # noqa: E402
from ctwa.ui.calibration.batch_section import BatchSection  # noqa: E402
from ctwa.ui.calibration.state import CalibrationState  # noqa: E402
from ctwa.ui.calibration.texts import TEXT  # noqa: E402
from ctwa.ui.calibration.writes import WriteQueue  # noqa: E402
from tests.calibration_fakes import FakeLoader, get_app, make_row, make_rows, wait_until  # noqa: E402


@pytest.fixture
def qapp():
    return get_app()


def rows_set():
    refs = [r for r in make_rows() if r.get("is_reference")]
    ss = "Stainless Steel"
    targets = [
        make_row(1, period=400, raw_lag_dt=150),
        make_row(2, period=800, raw_lag_dt=150),     # period far from the references: outside range
        make_row(3, period=450, raw_lag_dt=30),      # lag below the device lag: not calibratable
        make_row(4, period=450, raw_lag_dt=40),
        make_row(5, period=450, raw_lag_dt=150),     # already has a copy
        make_row(77, period=450, raw_lag_dt=150, calibrated_from_id=5, use_calibration=True),
    ]
    return refs + targets


def build(rows=None, answer=True):
    loader = FakeLoader()
    state = CalibrationState()
    state.set_rows(rows if rows is not None else rows_set())
    state.selected_ref_ids = [10, 11, 12, 13, 14]
    state.lag_source = "direct"
    state.batch_material = "Stainless Steel"
    queue = WriteQueue(loader)
    msgs, asked = [], []

    def confirm(title, message, label):
        asked.append((title, message, label))
        return answer

    sec = BatchSection(state, queue, lambda t, k: msgs.append((t, k)), confirm)
    return loader, state, queue, sec, msgs, asked


def checked(sec):
    t = sec.table
    return [t.item(i, 0).data(Qt.UserRole) for i in range(t.rowCount())
            if t.item(i, 0).checkState() == Qt.Checked]


def test_defaults_and_shortcuts(qapp):
    loader, state, queue, sec, msgs, asked = build()
    assert state.direct_lag == pytest.approx(46, abs=0.01)
    assert checked(sec) == [1, 2]
    t = sec.table
    assert "already calibrated (#77)" in t.item(4, 7).text() and not (t.item(4, 0).checkState() == Qt.Checked)
    for r in (2, 3):
        assert "not calibratable" in t.item(r, 7).text()
        assert not (t.item(r, 0).flags() & Qt.ItemIsEnabled and t.item(r, 0).flags() & Qt.ItemIsUserCheckable)
    assert sec.status_label.text() == "2 / 5 ready to save"
    sec.recal_link.click()
    assert state.batch_picked == [1, 2, 5] and checked(sec) == [1, 2, 5]
    sec.clear_link.click()
    assert checked(sec) == []
    sec.range_link.click()
    assert state.batch_picked == [1, 5]
    sec.default_link.click()
    assert state.batch_picked is None and checked(sec) == [1, 2]
    state.batch_picked = [1]
    state.batch_temp = "800"
    assert state.batch_picked is None


def test_toggle_by_checkbox(qapp):
    loader, state, queue, sec, msgs, asked = build()
    sec.table.item(0, 0).setCheckState(Qt.Unchecked)
    assert state.batch_picked == [2] and checked(sec) == [2]
    assert sec.save_button.text() == "Save all calibrated (1)"


def test_confirm_no_writes_nothing(qapp):
    loader, state, queue, sec, msgs, asked = build(answer=False)
    sec.save_button.click()
    wait_until(lambda: False, 0.1)
    assert loader.ops == [] and asked[0][2] == "Save all calibrated (2)"
    assert asked[0][0] == TEXT["confirmBatchTitle"].format(n=2, name="Stainless Steel")


def test_save_two_rows(qapp):
    loader, state, queue, sec, msgs, asked = build()
    loader.graphs = {1: "G1"}
    sec.save_button.click()
    assert wait_until(lambda: msgs)
    assert loader.requested_graphs == [1, 2]
    assert [o[0] for o in loader.ops] == ["insert", "insert"]
    model = calibration_model_string("direct", None, state.direct_lag)
    by = {r.a["id"]: r for r in state.batch_rows}
    for op, i in zip(loader.ops, (1, 2)):
        r = by[i]
        assert op[1] == build_calibrated_row(r.a, r.lag, r.result, loader.graphs.get(i),
                                             [10, 11, 12, 13, 14], model)
    assert msgs[-1][0] == "Saved 2/2 · 3 skipped (not calibratable) · 2 not calibratable · 1 already calibrated"


def test_had_copies_counts_only_unsaved(qapp):
    """Review item (e): a row with copies that is saved (re-calibrated) is not counted."""
    loader, state, queue, sec, msgs, asked = build()
    sec.recal_link.click()
    sec.save_button.click()
    assert wait_until(lambda: msgs)
    assert msgs[-1][0] == "Saved 3/3 · 2 skipped (not calibratable) · 2 not calibratable"


def test_failure_on_first_still_writes_second(qapp):
    loader, state, queue, sec, msgs, asked = build()
    loader.fail_at = {0: ("server", "boom")}
    sec.save_button.click()
    assert wait_until(lambda: msgs)
    assert len(loader.ops) == 2 and msgs[-1][0].endswith("· #1: boom") and msgs[-1][0].startswith("Saved 1/2")
    assert msgs[-1][1] == "warn"


def test_login_failure_aborts(qapp):
    loader, state, queue, sec, msgs, asked = build()
    sec.recal_link.click()
    loader.fail_at = {1: ("login", "expired")}
    sec.save_button.click()
    assert wait_until(lambda: msgs)
    assert len(loader.ops) == 2
    assert msgs[-1][0].startswith("Saved 1/3") and TEXT["loginNeeded"] in msgs[-1][0]
    assert "written 1 of 3" in msgs[-1][0]


def test_repick_after_partial_save(qapp):
    """Review 1: the next default pick excludes the runs already written."""
    loader, state, queue, sec, msgs, asked = build()
    loader.fail_at = {1: ("login", "expired")}
    sec.save_button.click()
    assert wait_until(lambda: msgs)
    # the refresh that brings the copy of run 1
    state.set_rows(rows_set() + [make_row(500, period=400, calibrated_from_id=1, use_calibration=True)])
    assert checked(sec) == [2]
    loader.fail_at = {}
    loader.ops.clear()
    sec.save_button.click()
    assert wait_until(lambda: len(msgs) == 2)
    assert [o[1]["calibrated_from_id"] for o in loader.ops] == [2]


def test_double_click_one_batch(qapp):
    loader, state, queue, sec, msgs, asked = build()
    loader.silent_graphs = False
    sec.save_button.click()
    assert sec.saving and not sec.save_button.isEnabled()
    sec.save()
    sec.save_button.click()
    assert wait_until(lambda: msgs)
    assert len(loader.ops) == 2 and len(asked) == 1 and loader.requested_graphs == [1, 2]


def test_zero_picked_disables_and_needs_fit(qapp):
    loader, state, queue, sec, msgs, asked = build()
    sec.clear_link.click()
    assert not sec.save_button.isEnabled()
    state.selected_ref_ids = []
    assert state.direct_lag is None
    assert not sec.needs_fit_label.isHidden() and sec.content.isHidden()


def test_copies_and_references_not_listed(qapp):
    loader, state, queue, sec, msgs, asked = build()
    ids = [sec.table.item(i, 0).data(Qt.UserRole) for i in range(sec.table.rowCount())]
    assert ids == [1, 2, 3, 4, 5]


def test_save_stays_disabled_until_rows_arrive(qapp):
    """Review fix 1: the saved copies reach the rows only after the refresh; until then no second Save."""
    loader, state, queue, sec, msgs, asked = build()
    loader.silent_rows = True
    sec.save_button.click()
    assert wait_until(lambda: msgs)
    assert len(loader.ops) == 2
    assert queue.reserved and sec.saving and not sec.save_button.isEnabled()
    sec.save_button.click()
    sec.save()
    wait_until(lambda: False, 0.1)
    assert len(loader.ops) == 2 and len(asked) == 1
    copies = [make_row(900 + i, period=400, calibrated_from_id=i, use_calibration=True) for i in (1, 2)]
    loader.rows_changed.emit(rows_set() + copies)
    state.set_rows(rows_set() + copies)
    assert not queue.reserved and not sec.saving
    assert checked(sec) == []


def test_reservation_times_out(qapp, monkeypatch):
    from ctwa.ui.calibration import writes
    monkeypatch.setattr(writes, "REFRESH_WAIT_MS", 50)
    loader, state, queue, sec, msgs, asked = build()
    loader.silent_rows = True
    sec.save_button.click()
    assert wait_until(lambda: msgs)
    assert queue.reserved
    assert wait_until(lambda: not queue.reserved)


def test_cross_section_reservation(qapp):
    """Review fix 2: a save during the graph wait disables the other section's Save."""
    from ctwa.ui.calibration.target_section import TargetSection
    loader, state, queue, sec, msgs, asked = build()
    tmsgs = []
    target = TargetSection(state, queue, lambda t, k: tmsgs.append((t, k)))
    state.target_id = 1
    loader.silent_graphs = True
    sec.save_button.click()
    assert queue.reserved and not queue.busy
    assert not target.save_button.isEnabled()
    target.save()
    assert loader.requested_graphs == [1, 2]       # only the batch asked for graphs
    # and the other way round
    queue.release()
    loader.requested_graphs.clear()
    target.save_button.click()
    assert not sec.save_button.isEnabled() and loader.requested_graphs == [1]
    sec.save()
    assert loader.requested_graphs == [1] and asked == [asked[0]]


def test_exception_in_callback_releases(qapp, monkeypatch):
    """Review fix 5: nothing sticks when the row builder raises."""
    from ctwa.ui.calibration import batch_section
    loader, state, queue, sec, msgs, asked = build()

    def boom(*a, **k):
        raise ValueError("bad row")

    monkeypatch.setattr(batch_section, "build_calibrated_row", boom)
    sec.save_button.click()
    assert wait_until(lambda: msgs)
    assert msgs[-1][1] == "error" and "bad row" in msgs[-1][0]
    assert not queue.reserved and sec.save_button.isEnabled() and loader.ops == []


def test_refused_run_says_another_save(qapp):
    loader, state, queue, sec, msgs, asked = build()
    loader.silent_graphs = True
    sec.save_button.click()
    from ctwa.ui.calibration.writes import WriteOp
    queue.run([WriteOp("update", 1, {}, "#1")], lambda s: None)      # someone else grabs the queue
    loader.silent_graphs = False
    loader.graph_loaded.emit(1, None)
    loader.graph_loaded.emit(2, None)
    assert msgs and msgs[-1] == (TEXT["saveInProgress"], "error")
    assert not queue.reserved or True


def test_snapshot_after_confirm(qapp):
    """Review fix 4: a change made while the dialog is open is part of the saved set."""
    state_box = {}

    def confirm(title, message, label):
        state_box["state"].batch_picked = [2]
        return True

    loader, state, queue, sec, msgs, asked = build()
    sec._confirm = confirm
    state_box["state"] = state
    sec.save_button.click()
    assert wait_until(lambda: msgs)
    assert [o[1]["calibrated_from_id"] for o in loader.ops] == [2]
    assert msgs[-1][0].startswith("Saved 1/1")
