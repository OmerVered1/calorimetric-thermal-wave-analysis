"""TargetSection (Plan 4, Task 8): picker, lag source, models, result, save."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402

from ctwa.analysis.calibration_batch import build_calibrated_row, calibration_model_string  # noqa: E402
from ctwa.analysis.calibration_logic import num  # noqa: E402
from ctwa.ui.calibration.state import CalibrationState  # noqa: E402
from ctwa.ui.calibration.target_section import TargetSection  # noqa: E402
from ctwa.ui.calibration.texts import TEXT  # noqa: E402
from ctwa.ui.calibration.writes import WriteQueue  # noqa: E402
from tests.calibration_fakes import FakeLoader, get_app, make_row, make_rows, wait_until  # noqa: E402


@pytest.fixture
def qapp():
    return get_app()


def build(rows=None):
    loader = FakeLoader()
    loader.graphs = {99: "G"}
    state = CalibrationState()
    state.set_rows(rows if rows is not None else make_rows())
    queue = WriteQueue(loader)
    msgs = []
    sec = TargetSection(state, queue, lambda t, k: msgs.append((t, k)))
    return loader, state, queue, sec, msgs


def tick_refs(sec, ids):
    sec._state.selected_ref_ids = list(ids)


def picker_ids(sec):
    return [sec.list.item(i).data(Qt.UserRole) for i in range(sec.list.count())]


def test_sqrt_first_and_applied(qapp):
    loader, state, queue, sec, msgs = build()
    state.target_id = 99
    tick_refs(sec, [10, 11, 12, 13, 14])
    assert state.fit.kind == "sqrt" and state.model_kind is None
    assert TEXT["bestByRms"] in sec.range_label.text()
    assert "47.25 s" in sec.applied_label.text()
    assert sec.card_labels["lag"][1].text() == "102.75 s"
    assert sec.chart.isVisibleTo(sec)
    assert sec.model_table.rowCount() == len(state.fits)
    assert sec.status_label.text().startswith("Square root · RMS")
    state.model_kind = "linear"
    assert "%s s" % num(42.551971326164875) in sec.applied_label.text()
    assert TEXT["bestByRms"] not in sec.range_label.text()


def test_picker_sort_and_ticking(qapp):
    loader, state, queue, sec, msgs = build()
    state.target_id = 99
    sec.sort.setCurrentIndex(sec.sort.findData("nearPeriod"))
    assert picker_ids(sec) == [12, 13, 11, 10, 14]
    # the near-only percent field is disabled until the box is ticked
    assert not sec.near_pct.isEnabled()
    sec.near_box.setChecked(True)
    assert sec.near_pct.isEnabled() and state.ref_near_only
    sec.near_box.setChecked(False)


def test_sort_needs_target_and_no_lag_blocks_tick(qapp):
    rows = make_rows()
    rows[2] = dict(rows[2], reference_alpha_mm2s=None)       # id 12 has no known alpha: no lag
    loader, state, queue, sec, msgs = build(rows)
    assert not sec.sort.model().item(1).isEnabled() and not sec.near_box.isEnabled()
    item = next(sec.list.item(i) for i in range(sec.list.count()) if sec.list.item(i).data(Qt.UserRole) == 12)
    item.setCheckState(Qt.Checked)
    assert state.selected_ref_ids == [] and item.checkState() == Qt.Unchecked
    sec.select_all.click()
    assert sorted(state.selected_ref_ids) == [10, 11, 13, 14]
    sec.clear.click()
    assert state.selected_ref_ids == []


def test_direct_source(qapp):
    loader, state, queue, sec, msgs = build()
    state.target_id = 99
    tick_refs(sec, [10, 11, 12, 13, 14])
    sec.direct_radio.click()
    assert state.source == "direct"
    assert sec.direct_label.text().startswith("%s 5" % TEXT["directMean"])
    assert "46.00 s" in sec.applied_label.text()
    assert sec.mismatch_warn.isHidden()
    state.set_rows([dict(r, period_t=700) if r["id"] == 99 else r for r in make_rows()])
    assert not sec.mismatch_warn.isHidden() and TEXT["periodMismatchWarn"] in sec.mismatch_warn.text()


def test_one_reference_falls_back_to_direct(qapp):
    loader, state, queue, sec, msgs = build()
    state.target_id = 99
    tick_refs(sec, [10])
    assert state.source == "direct" and not sec.curve_radio.isEnabled()
    assert sec.direct_radio.isChecked()
    assert not sec.too_few_label.isHidden()
    assert sec.direct_label.text().startswith(TEXT["directSingle"])


def test_temperature_spread_none_at_19_5(qapp):
    loader, state, queue, sec, msgs = build()
    state.target_id = 99
    tick_refs(sec, [10, 11, 12, 13, 14])
    assert sec.spread_label.isHidden()


def test_temp_spread_shown(qapp):
    rows = [dict(r, temperature_c=800.0) if r["id"] == 10 else
            dict(r, temperature_c=831.0) if r["id"] == 14 else r for r in make_rows()]
    loader, state, queue, sec, msgs = build(rows)
    state.target_id = 99
    tick_refs(sec, [10, 11, 12, 13, 14])
    assert sec.spread_label.text().endswith("spread 31.0 °C") and not sec.spread_label.isHidden()


def test_out_of_range_and_existing_copy(qapp):
    rows = make_rows()
    rows.append(make_row(77, period=300, calibrated_from_id=99, use_calibration=True))
    rows = [dict(r, period_t=74) if r["id"] == 99 else r for r in rows]
    loader, state, queue, sec, msgs = build(rows)
    state.target_id = 99
    tick_refs(sec, [10, 11, 12, 13, 14])
    assert not sec.range_warn.isHidden() and TEXT["outOfRangeWarn"] in sec.range_warn.text()
    assert not sec.copy_warn.isHidden() and "%s (#77)" % TEXT["alreadyCalibrated"] in sec.copy_warn.text()


def run_save(sec, loader):
    sec.save_button.click()
    return wait_until(lambda: loader.ops and not sec._queue.busy and not sec.saving)


def ready(rows=None):
    env = build(rows)
    loader, state, queue, sec, msgs = env
    state.target_id = 99
    tick_refs(sec, [10, 11, 12, 13, 14])
    return env


def test_save_inserts_row(qapp):
    loader, state, queue, sec, msgs = ready()
    assert run_save(sec, loader)
    assert len(loader.ops) == 1 and loader.ops[0][0] == "insert"
    expect = build_calibrated_row(state.target, state.applied.lag, state.calibrated, "G",
                                  [10, 11, 12, 13, 14], calibration_model_string("curve", state.fit, None))
    assert loader.ops[0][1] == expect
    assert expect["graph_image"] == "G" and expect["calibration_ref_ids"] == "10,11,12,13,14"
    assert msgs[-1] == (TEXT["saved"], "ok")


def test_save_without_graph_still_inserts(qapp):
    loader, state, queue, sec, msgs = ready()
    loader.graphs = {}
    assert run_save(sec, loader)
    assert loader.ops[0][1]["graph_image"] is None


def test_save_failure_message(qapp):
    loader, state, queue, sec, msgs = ready()
    loader.fail_at = {0: ("server", "boom")}
    assert run_save(sec, loader)
    assert msgs[-1] == ("%s: #99: boom" % TEXT["saveFailed"], "error")


def test_double_click_one_insert(qapp):
    """Review 2 and item (a): the second click lands while the graph is still being fetched."""
    loader, state, queue, sec, msgs = ready()
    sec.save_button.click()
    assert sec.saving and not sec.save_button.isEnabled() and not queue.busy
    sec.save()                       # forced second call
    sec.save_button.click()
    assert wait_until(lambda: loader.ops and not sec.saving and not queue.busy)
    assert wait_until(lambda: True)
    assert len(loader.ops) == 1 and loader.requested_graphs == [99]


def test_not_calibratable_cannot_save(qapp):
    rows = [dict(r, raw_lag_dt=40) if r["id"] == 99 else r for r in make_rows()]
    loader, state, queue, sec, msgs = ready(rows)
    state.lag_source = "direct"
    assert state.calibrated is None
    assert not sec.save_button.isEnabled() and not sec.not_cal_label.isHidden()
    sec.save_button.click()
    sec.save()
    wait_until(lambda: False, 0.1)
    assert loader.ops == []
