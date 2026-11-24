"""Batch statuses, calibrated-row builder, reports (page.tsx batchRows / buildCalibratedRow / saveBatch)."""
from __future__ import annotations

import json
import math

import pytest

from ctwa.analysis.calibration import apply_device_lag
from ctwa.analysis.calibration_batch import (
    batch_calibratable, batch_default_ids, batch_ok, batch_report, batch_rows, batch_targets,
    build_calibrated_row, calibration_model_string, mark_report, pick_clear, pick_default,
    pick_in_range, pick_recalibrate, toggle_pick)
from ctwa.analysis.calibration_logic import fit_points, ref_lags, selected_lags
from ctwa.analysis.lag_fit import fit_lag_models

PERIODS = [75, 150, 300, 600, 1200]
RAW = [28.2366967506017, 40.64844825385532, 57.4733935012034, 81.29689650771064, 114.9467870024068]


def make_refs():
    return [{"id": 10 + i, "period_t": p, "angular_freq_w": 2 * math.pi / p, "r1_mm": 6.72, "r2_mm": 14.86,
             "ln_term": 3, "temperature_c": 800.0, "is_reference": True, "reference_alpha_mm2s": 5.829,
             "model_name": "Stainless Steel", "raw_lag_dt": raw}
            for i, (p, raw) in enumerate(zip(PERIODS, RAW))]


def tgt(i, period, raw=150, **extra):
    d = {"id": i, "period_t": period, "raw_lag_dt": raw, "r1_mm": 6.72, "r2_mm": 14.86, "ln_term": 3,
         "angular_freq_w": 2 * math.pi / period if period is not None else 0.05,
         "model_name": "Stainless Steel", "temperature_c": 800.0}
    d.update(extra)
    return d


SEL = selected_lags(ref_lags(make_refs(), "phase"), [10, 11, 12, 13, 14])
FIT = fit_lag_models(fit_points(SEL))[0]
T = [tgt(1, 400), tgt(2, 1000), tgt(3, None), tgt(4, 450, raw=40), tgt(5, 500)]
COPIES = {5: [77]}
DIRECT = batch_rows(T, "direct", None, 46, 465, COPIES)
CURVE = batch_rows(T, "curve", FIT, None, None, COPIES)


def test_statuses():
    st = {r.a["id"]: r for r in DIRECT}
    assert [st[i].status for i in (1, 2, 3, 4, 5)] == ["ok", "outOfRange", "notCalibratable",
                                                       "notCalibratable", "ok"]
    assert st[3].lag is None and st[3].result is None
    assert st[4].lag == 46 and st[4].result is None
    assert st[5].existing == [77] and st[1].existing == []
    assert st[2].result is not None


def test_picks():
    assert [r.a["id"] for r in batch_calibratable(DIRECT)] == [1, 2, 5]
    assert batch_default_ids(DIRECT) == [1, 2]
    assert pick_default() is None
    assert pick_recalibrate(DIRECT) == [1, 2, 5]
    assert pick_in_range(DIRECT) == [1, 5]
    assert pick_clear() == []
    assert [r.a["id"] for r in batch_ok(DIRECT, None)] == [1, 2]
    assert [r.a["id"] for r in batch_ok(DIRECT, [5, 4])] == [5]
    assert batch_ok(DIRECT, []) == []


def test_toggle():
    d = batch_default_ids(DIRECT)
    assert toggle_pick(None, d, 5, True) == [1, 2, 5]
    assert toggle_pick(None, d, 1, False) == [2]
    once = toggle_pick(None, d, 5, True)
    assert toggle_pick(once, d, 5, True) == once
    assert toggle_pick([2], d, 2, False) == []
    assert toggle_pick([2], d, 2, False) == toggle_pick([], d, 2, False)


def test_curve_source():
    r1 = CURVE[0]
    assert r1.lag == pytest.approx(47.25456790896485, rel=1e-12)
    assert r1.result.net_lag_dt == pytest.approx(102.74543209103516, rel=1e-12)
    assert r1.result.alpha_phase_cal == pytest.approx(1.9979006643647911e-07, rel=1e-12)
    assert CURVE[1].status == "ok"  # 1000 s is inside the fitted 75-1200 s range
    assert batch_rows([tgt(8, 1300)], "curve", FIT, None, None, {})[0].status == "outOfRange"
    none = batch_rows(T, "curve", None, None, None, COPIES)
    assert all(r.status == "notCalibratable" for r in none)
    none_d = batch_rows(T, "direct", None, None, None, COPIES)
    assert all(r.status == "notCalibratable" for r in none_d)


def test_batch_targets():
    rows = [tgt(1, 400), tgt(2, 400, temperature_c=780.5), tgt(3, 400, model_name="Other"),
            tgt(4, 400, temperature_c=None)]
    assert [a["id"] for a in batch_targets(rows, "Stainless Steel", "780.5")] == [2]
    assert [a["id"] for a in batch_targets(rows, "Stainless Steel", "")] == [1, 2, 4]
    assert [a["id"] for a in batch_targets(rows, "Stainless Steel", "800")] == [1]
    assert batch_targets(rows, "", "") == []


SRC_KEYS = ["model_name", "test_date", "test_time", "temperature_c", "power_source_device",
            "power_response_device", "gas_atmosphere", "wave_type", "analysis_mode", "r1_mm", "r2_mm",
            "amplitude_a1", "amplitude_a2", "period_t", "frequency_f", "period_t_resp", "frequency_f_resp",
            "angular_freq_w", "raw_lag_dt", "raw_phase_phi", "ln_term", "alpha_combined_raw",
            "alpha_phase_raw"]
EXPECTED_KEYS = SRC_KEYS + ["graph_image", "use_calibration", "system_lag", "net_lag_dt", "net_phase_phi",
                            "alpha_combined_cal", "alpha_phase_cal", "is_reference", "calibrated_from_id",
                            "calibration_ref_ids", "calibration_model"]


def full_target():
    t = {"id": 99, "period_t": 400, "temperature_c": 800.0, "raw_lag_dt": 150,
         "angular_freq_w": 0.015707963267948967, "ln_term": 3, "amplitude_a1": 4, "amplitude_a2": 1,
         "r1_mm": 6.72, "r2_mm": 14.86, "model_name": "Stainless Steel", "test_date": "17/11/2026",
         "test_time": "10:00", "power_source_device": "K2602B", "power_response_device": "C80",
         "gas_atmosphere": "Ar", "wave_type": "Sine", "analysis_mode": "AutoFit", "frequency_f": 0.0025,
         "period_t_resp": 400.1, "frequency_f_resp": 0.0024, "raw_phase_phi": 2.3,
         "alpha_combined_raw": 1e-7, "alpha_phase_raw": 2e-7,
         # fields that must not be copied
         "created_at": "x", "reference_alpha_mm2s": 5.8, "extra_data": "{}", "graph_json": "{}",
         "c80_filename": "a", "keithley_filename": "b", "t_cal": "1", "t_src": "2", "t_min": 1, "t_max": 2,
         "is_reference": False, "calibrated_from_id": None}
    return t


def test_build_calibrated_row():
    src = full_target()
    before = json.loads(json.dumps(src))
    lag = 47.25456790896485
    res = apply_device_lag(src, lag)
    row = build_calibrated_row(src, lag, res, "G", [10, 11, 12, 13, 14], "sqrt:a=-0.341302,b=2.37979")
    assert set(row) == set(EXPECTED_KEYS) and len(row) == 34
    for k in SRC_KEYS:
        assert row[k] == src[k]
    assert row["use_calibration"] is True and row["is_reference"] is False
    assert row["calibrated_from_id"] == 99 and row["calibration_ref_ids"] == "10,11,12,13,14"
    assert row["system_lag"] == lag and row["graph_image"] == "G"
    assert row["calibration_model"] == "sqrt:a=-0.341302,b=2.37979"
    assert row["net_lag_dt"] == res.net_lag_dt and row["alpha_phase_cal"] == res.alpha_phase_cal
    assert row["alpha_combined_cal"] == res.alpha_combined_cal
    json.dumps(row, allow_nan=False)
    assert src == before
    assert build_calibrated_row(src, lag, res, None, [], None)["graph_image"] is None


def test_model_strings():
    fits = fit_lag_models(fit_points(SEL))
    assert calibration_model_string("curve", fits[0], None) == "sqrt:a=-0.341302,b=2.37979"
    phys = [f for f in fits if f.kind == "physical"][0]
    assert calibration_model_string("curve", phys, None) == "physical:t1=0.0373583,t2=79.0934"
    assert calibration_model_string("direct", None, 46) == "direct:lag=46.0000"
    assert calibration_model_string("direct", FIT, None) is None
    assert calibration_model_string("curve", None, 46) is None


def test_direct_build():
    t = full_target()
    res = apply_device_lag(t, 46)
    row = build_calibrated_row(t, 46, res, None, [10], "direct:lag=46.0000")
    assert row["net_lag_dt"] == pytest.approx(104, rel=1e-12)
    assert row["net_phase_phi"] == pytest.approx(1.6336281798666925, rel=1e-12)
    assert row["alpha_combined_cal"] == pytest.approx(1.0618525641025642e-07, rel=1e-12)
    assert row["alpha_phase_cal"] == pytest.approx(1.9499894355199244e-07, rel=1e-12)


def test_reports():
    assert mark_report(3, 4, ["#12: boom"]) == "Marked as reference: 3/4 · #12: boom"
    assert mark_report(4, 4, []) == "Marked as reference: 4/4"
    assert (batch_report(2, 2, 5, 3, 1, [])
            == "Saved 2/2 · 3 skipped (not calibratable) · 2 not calibratable · 1 already calibrated")
    assert batch_report(5, 5, 5, 5, 0, []) == "Saved 5/5"
    assert batch_report(5, 5, 5, 5, 0, ["#7: x", "#8: y"]) == "Saved 5/5 · #7: x; #8: y"
    assert (batch_report(2, 2, 3, 3, 0, ["#7: x"])
            == "Saved 2/2 · 1 skipped (not calibratable) · #7: x")
