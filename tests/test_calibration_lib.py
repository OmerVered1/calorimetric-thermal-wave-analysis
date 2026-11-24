"""Pinned against lib/analysis.ts (calibrationBasis, trueLagForAlpha, deviceLagFromReference, applyDeviceLag)."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from ctwa.analysis.calibration import (AppliedLag, apply_device_lag, calibration_basis,
                                       device_lag_from_reference, true_lag_for_alpha)

GOLDEN = Path(__file__).parent / "golden" / "analysis"


def row_from_golden(case: str) -> dict:
    d = json.loads((GOLDEN / f"{case}.json").read_text())
    o, r = d["options"]["params"], d["results"]
    return {"r1_mm": o["r1Mm"], "r2_mm": o["r2Mm"], "angular_freq_w": r["angularFreqW"],
            "raw_lag_dt": r["rawLagDt"], "ln_term": r["lnTerm"], "period_t": r["periodT"]}


REF = row_from_golden("al2o3_ctwa__AutoFit_raw")
FIBER = row_from_golden("fiber_150_600__AutoFit_raw")
BASE = {"r1_mm": 6.72, "r2_mm": 14.86, "angular_freq_w": 0.05, "raw_lag_dt": 60, "ln_term": 2}


def approx(x):
    return pytest.approx(x, rel=1e-12)


def check(res, expected):
    assert isinstance(res, AppliedLag)
    got = (res.net_lag_dt, res.net_phase_phi, res.alpha_combined_cal, res.alpha_phase_cal)
    for g, e in zip(got, expected):
        assert g == approx(e)


def test_true_and_device_lag_from_reference():
    assert true_lag_for_alpha(REF, 5.829) == approx(8.519616453527574)
    assert true_lag_for_alpha(REF, 5.829, "combined") == approx(1.40556420142513)
    assert device_lag_from_reference(REF, 5.829) == approx(37.90893175484667)
    assert device_lag_from_reference(REF, 5.829, "combined") == approx(45.022984006949116)


def test_apply_device_lag_reference():
    check(apply_device_lag(REF, 10),
          (36.428548208374245, 2.8525057936174756, 2.2490695163700366e-07, 3.188235662579634e-07))
    zero = apply_device_lag(REF, 0)
    check(zero, (46.428548208374245, 3.635547098832526, 1.764654301344128e-07, 1.9627452500328294e-07))
    d = json.loads((GOLDEN / "al2o3_ctwa__AutoFit_raw.json").read_text())["results"]
    assert zero.alpha_combined_cal == approx(d["alphaCombinedRaw"])
    assert zero.alpha_phase_cal == approx(d["alphaPhaseRaw"])
    assert apply_device_lag(REF, 47) is None


def test_apply_device_lag_fiber():
    check(apply_device_lag(FIBER, 37.90893175484667),
          (92.5091317965836, 1.279281183287191, 4.482162758350282e-07, 2.799420876759157e-07))
    res = apply_device_lag(FIBER, -20)
    assert res.net_lag_dt == approx(150.41806355143027)
    assert res.alpha_phase_cal == approx(1.0588572644407653e-07)


def test_apply_device_lag_base():
    check(apply_device_lag(BASE, 20), (40, 2, 4.141225000000002e-07, 4.1412250000000013e-07))
    assert apply_device_lag(BASE, 60) is None
    assert apply_device_lag(BASE, float("nan")) is None
    assert apply_device_lag({**BASE, "raw_lag_dt": -60}, 20).net_lag_dt == 40


def test_negative_ln_term():
    neg = {**BASE, "ln_term": -0.3}
    assert true_lag_for_alpha(neg, 5, "combined") is None
    res = apply_device_lag(neg, 20)
    assert res.alpha_combined_cal is None
    assert res.alpha_phase_cal == approx(4.1412250000000013e-07)
    assert apply_device_lag({**BASE, "ln_term": None}, 20).alpha_combined_cal is None


def test_negative_device_lag_kept():
    assert device_lag_from_reference({**BASE, "raw_lag_dt": 5}, 5) == approx(-6.511698397716996)


def test_none_cases():
    assert true_lag_for_alpha(BASE, 0) is None
    assert true_lag_for_alpha(BASE, -1) is None
    assert true_lag_for_alpha(BASE, float("nan")) is None
    assert true_lag_for_alpha({**BASE, "angular_freq_w": 0}, 5) is None
    assert true_lag_for_alpha({**BASE, "angular_freq_w": math.inf}, 5) is None
    assert true_lag_for_alpha({**BASE, "r1_mm": None}, 5) is None
    assert true_lag_for_alpha({**BASE, "r2_mm": 6.72}, 5) is None
    assert device_lag_from_reference({**BASE, "raw_lag_dt": None}, 5) is None
    assert apply_device_lag({**BASE, "raw_lag_dt": None}, 5) is None
    assert calibration_basis(BASE) is not None
    assert calibration_basis({**BASE, "r1_mm": None}) is None
