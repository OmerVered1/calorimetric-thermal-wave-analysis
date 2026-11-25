"""CalibrationState: derived values, reconcile after a refresh, filter keys (Plan 4, Task 4)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from ctwa.analysis.calibration import device_lag_from_reference  # noqa: E402
from ctwa.ui.calibration.state import CalibrationState  # noqa: E402
from ctwa.ui.calibration.texts import TEXT  # noqa: E402
from tests.calibration_fakes import get_app, make_rows  # noqa: E402


@pytest.fixture
def qapp():
    return get_app()


@pytest.fixture
def state(qapp):
    s = CalibrationState()
    s.set_rows(make_rows())
    return s


def test_texts():
    assert TEXT["tooFewPoints"].startswith("Select at least 3 reference runs")
    assert TEXT["all"] == "All" and TEXT["none"] == "None" and TEXT["loading"] == "Loading..."
    assert TEXT["referencesHeading"] == "1. Reference runs"
    assert "{n}" in TEXT["confirmBatchTitle"] and "{name}" in TEXT["confirmBatchTitle"]


def test_initial_selects_nothing(state):
    assert state.selected_ref_ids == [] and state.selected == []
    assert state.fit is None and state.fits == [] and state.target is None and state.applied is None
    assert [r["id"] for r in state.references] == [10, 11, 12, 13, 14]
    assert 99 in [r["id"] for r in state.non_references] and 150 not in [r["id"] for r in state.non_references]
    assert state.copies == {101: [150]}


def test_fit_and_applied(state):
    state.selected_ref_ids = [10, 11, 12, 13, 14]
    state.target_id = 99
    assert state.fit.kind == "sqrt"
    assert state.source == "curve"
    assert state.applied.lag == pytest.approx(47.25456790896485, rel=1e-9)
    assert state.calibrated is not None
    state.lag_source = "direct"
    assert state.applied.lag == pytest.approx(46, rel=1e-9)
    assert state.direct_lag == pytest.approx(46, rel=1e-9) and state.direct_mean_period == 465


def test_method_change_changes_every_lag(state):
    state.selected_ref_ids = [10, 11]
    phase = [x.lag for x in state.ref_lags]
    state.method = "combined"
    comb = [x.lag for x in state.ref_lags]
    assert all(a != b for a, b in zip(phase, comb))
    r10 = state.references[0]
    assert state.ref_lags[0].lag == device_lag_from_reference(r10, 5.829, "combined")


def test_changed_emitted_once_per_real_change(state):
    n = []
    state.changed.connect(lambda: n.append(1))
    state.method = "combined"
    state.method = "combined"
    assert len(n) == 1


def test_derived_cached_until_changed(state):
    state.selected_ref_ids = [10, 11, 12]
    a = state.fits
    assert state.fits is a
    state.selected_ref_ids = [10, 11, 12, 13]
    assert state.fits is not a


def test_reconcile_drops_vanished_ids(state):
    """Review 3: a run vanished in Summary, a reference unmarked."""
    state.selected_ref_ids = [10, 12, 13]
    state.target_id = 12
    state.mark_ids = [99, 100]
    state.batch_material = "Stainless Steel"
    state.batch_picked = [99, 100]
    rows = [r for r in make_rows() if r["id"] not in (12, 99)]
    state.set_rows(rows)
    assert 12 not in state.selected_ref_ids and state.selected_ref_ids == [10, 13]
    assert state.target_id is None and state.target is None
    assert state.mark_ids == [100]
    assert state.batch_picked is None or 99 not in state.batch_picked
    # an unmarked reference leaves the ticked list as well
    state.selected_ref_ids = [10, 11]
    rows = [dict(r, is_reference=False, reference_alpha_mm2s=None) if r["id"] == 11 else r for r in rows]
    state.set_rows(rows)
    assert state.selected_ref_ids == [10]


def test_reconcile_keeps_everything_when_nothing_vanished(state):
    state.selected_ref_ids = [10, 12]
    state.target_id = 99
    state.mark_ids = [100]
    state.batch_material = "Stainless Steel"
    state.batch_picked = [99]
    state.set_rows(make_rows())
    assert state.selected_ref_ids == [10, 12] and state.target_id == 99
    assert state.mark_ids == [100] and state.batch_picked == [99]


def test_empty_rows_no_exception(state):
    state.selected_ref_ids = [10]
    state.target_id = 99
    state.set_rows([])
    assert state.selected_ref_ids == [] and state.target_id is None
    assert state.picker == [] and state.batch_rows == [] and state.fit is None


def test_batch_pick_resets_when_candidates_got_a_copy(state):
    state.batch_material = "Stainless Steel"
    state.batch_picked = [99, 100]
    rows = make_rows() + []
    rows.append(dict(rows[5], id=160, calibrated_from_id=99))
    state.set_rows(rows)
    assert state.batch_picked is None


def test_filter_keys(state):
    state.ref_filter_material = "Stainless Steel"
    state.ref_filter_temp = "780.5"
    state.set_rows(make_rows())
    assert state.ref_filter_temp == "780.5"
    state.ref_filter_material = "Al"
    assert state.ref_filter_temp == ""
    state.mark_filter_material = "Al"
    state.mark_filter_temp = "800"
    state.mark_filter_material = "Stainless Steel"
    assert state.mark_filter_temp == ""
    state.batch_picked = [1]
    state.batch_material = "Al"
    assert state.batch_picked is None
    state.batch_picked = [1]
    state.batch_temp = "800"
    assert state.batch_picked is None


def test_apply_preset(state):
    n = []
    state.changed.connect(lambda: n.append(1))
    state.mark_filter_temp = "800"
    state.apply_preset({"material_name": "Stainless Steel", "alpha_mm2s": 5.829})
    assert state.mark_alpha == "5.829" and state.mark_filter_material == "Stainless Steel"
    assert state.mark_filter_temp == ""


def test_picker_and_batch_rows(state):
    state.selected_ref_ids = [10, 11, 12, 13, 14]
    state.target_id = 99
    assert [p.ref["id"] for p in state.picker] == [10, 11, 12, 13, 14]
    state.batch_material = "Stainless Steel"
    ids = [r.a["id"] for r in state.batch_rows]
    assert ids == [99, 100, 103]


def test_curve_source_falls_back_to_direct_below_two_refs(state):
    state.selected_ref_ids = [10, 11, 12, 13, 14]
    state.lag_source = "curve"
    assert state.fit is not None and state.source == "curve"
    state.selected_ref_ids = [10]
    assert state.fit is None and state.source == "direct"      # no curve to apply any more
    state.selected_ref_ids = [10, 11, 12, 13, 14]
    assert state.source == "curve"                             # the user's choice comes back with the curve


def test_fits_memo_keeps_several_point_sets(state, monkeypatch):
    from ctwa.ui.calibration import state as state_mod
    calls = []
    real = state_mod.fit_lag_models
    monkeypatch.setattr(state_mod, "fit_lag_models", lambda pts: calls.append(len(pts)) or real(pts))
    a, b = [10, 11, 12, 13, 14], [10, 11, 12, 13]
    state.selected_ref_ids = a
    state.fits
    state.selected_ref_ids = b
    state.fits
    state.selected_ref_ids = a          # toggled back: instant, no refit
    state.fits
    state.selected_ref_ids = b
    state.fits
    assert len(calls) == 2
