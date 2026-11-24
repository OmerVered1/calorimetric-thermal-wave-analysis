"""Page logic of app/calibration/page.tsx (rows, picker, lag source). TS-pinned values (lib/lagFit.ts, lib/analysis.ts)."""
from __future__ import annotations

import math

import pytest

from ctwa.analysis.calibration_logic import (
    DIRECT_PERIOD_HI, DIRECT_PERIOD_LO, TEMP_SPREAD_WARN_C, active_fit, active_source,
    all_materials, applied_lag, curve_points, direct_lag, direct_mean_period, fit_points,
    label_of, mark_warnings, num, picker_rows, ref_lags, ref_temps, selected_lags,
    split_rows, temp_key, temp_spread, temps_for)
from ctwa.analysis.lag_fit import fit_lag_models

PERIODS = [75, 150, 300, 600, 1200]
RAW = [28.2366967506017, 40.64844825385532, 57.4733935012034, 81.29689650771064, 114.9467870024068]


def make_refs():
    out = []
    for i, (p, raw) in enumerate(zip(PERIODS, RAW)):
        out.append({"id": 10 + i, "period_t": p, "angular_freq_w": 2 * math.pi / p, "r1_mm": 6.72,
                    "r2_mm": 14.86, "ln_term": 3, "temperature_c": 780.5 if i == 4 else 800.0,
                    "is_reference": True, "reference_alpha_mm2s": 5.829,
                    "model_name": "Stainless Steel", "raw_lag_dt": raw})
    return out


TARGET = {"id": 99, "period_t": 400, "temperature_c": 800.0, "raw_lag_dt": 150,
          "angular_freq_w": 0.015707963267948967, "ln_term": 3, "amplitude_a1": 4, "amplitude_a2": 1,
          "r1_mm": 6.72, "r2_mm": 14.86}
REFS = make_refs()


def ids(rows):
    return [r.ref["id"] for r in rows]


def test_constants():
    assert (TEMP_SPREAD_WARN_C, DIRECT_PERIOD_LO, DIRECT_PERIOD_HI) == (30, 0.8, 1.25)


def test_formatting():
    assert temp_key(25.0) == "25"
    assert temp_key(766.5) == "766.5"
    assert temp_key(None) == ""
    assert num(None) == "—"
    assert num(float("nan")) == "—"
    assert num(46.428548208374245) == "46.43"
    assert num(2.5, 0) == "3"
    assert num(1.005, 2) == "1.00"
    a = {"id": 12, "model_name": "Stainless Steel", "test_date": "17/11/2026", "temperature_c": 800.0,
         "period_t": 300.4, "analysis_mode": "AutoFit"}
    assert label_of(a) == "Stainless Steel | 17/11/2026 | 800°C | T=300s | AutoFit #12"
    assert label_of({**a, "temperature_c": None}) == "Stainless Steel | 17/11/2026 | T=300s | AutoFit #12"


def test_split_rows_and_lists():
    copy = {"id": 50, "model_name": "Stainless Steel", "calibrated_from_id": 10, "is_reference": False,
            "temperature_c": 800.0}
    plain = {"id": 51, "model_name": "Stainless Steel", "calibrated_from_id": None, "is_reference": False,
             "temperature_c": 800.0}
    rows = [copy, plain] + REFS
    refs, non_refs, copies = split_rows(rows)
    assert [r["id"] for r in refs] == [10, 11, 12, 13, 14]
    assert [r["id"] for r in non_refs] == [51]
    assert copies == {10: [50]}
    nr = [{"id": i, "model_name": "M", "temperature_c": t, "is_reference": False, "calibrated_from_id": None}
          for i, t in enumerate([800.0, 780.5, 800.0])]
    assert temps_for(nr, "M") == ["780.5", "800"]
    assert temps_for(nr, "") == []
    assert all_materials([{"model_name": "A "}, {"model_name": "A"}, {"model_name": ""},
                          {"model_name": None}, {"model_name": "B"}]) == ["A", "A ", "B"]
    assert ref_temps(REFS, "Stainless Steel") == ["780.5", "800"]
    assert ref_temps(REFS, "") == ["780.5", "800"]
    assert ref_temps(REFS, "X") == []


def test_ref_lags_and_selection():
    rl = ref_lags(REFS, "phase")
    for x, e in zip(rl, [20, 29, 41, 58, 82]):
        assert x.lag == pytest.approx(e, rel=1e-9)
    assert rl[0].true_lag == pytest.approx(RAW[0] - 20, rel=1e-9)
    no_alpha = {**REFS[0], "id": 70, "reference_alpha_mm2s": None}
    no_period = {**REFS[0], "id": 71, "period_t": None}
    rl2 = ref_lags([no_alpha, no_period] + REFS, "phase")
    assert rl2[0].lag is None and rl2[0].true_lag is None
    assert ids(selected_lags(rl2, [70, 71, 10, 12])) == [10, 12]
    assert ids(selected_lags(rl, [14, 10])) == [10, 14]


def test_picker_rows():
    rl = ref_lags(list(reversed(REFS)), "phase")
    P = lambda **k: ids(picker_rows(rl, TARGET, k.get("material", ""), k.get("temp", ""),
                                    k.get("near_only", False), k.get("near_pct", 50), k.get("sort", "period")))
    assert P() == [10, 11, 12, 13, 14]
    assert P(sort="nearPeriod") == [12, 13, 11, 10, 14]
    assert P(sort="nearTemp") == [13, 12, 11, 10, 14]
    assert P(near_only=True) == [12, 13]
    assert P(near_only=True, near_pct=0) == [10, 11, 12, 13, 14]
    assert P(near_only=True, near_pct=None) == [10, 11, 12, 13, 14]
    assert P(material="Other") == []
    assert P(temp="780.5") == [14]
    row = picker_rows(rl, TARGET, "", "", False, 50, "period")[0]
    assert row.d_t == 0 and row.d_p == -325
    none_t = picker_rows(rl, None, "", "", False, 50, "period")[0]
    assert none_t.d_t is None and none_t.d_p is None


def test_spread_and_warnings():
    sel = selected_lags(ref_lags(REFS, "phase"), [10, 11, 12, 13, 14])
    assert temp_spread(sel) == pytest.approx(19.5)
    assert temp_spread(sel[:1]) is None
    mk = lambda *ts: [{"model_name": "A", "temperature_c": t} for t in ts]
    assert mark_warnings(mk(800, 829.9))["temp_spread"] is None
    assert mark_warnings(mk(800, 830.5))["temp_spread"] == pytest.approx(30.5)
    assert mark_warnings(mk(800))["temp_spread"] is None
    w = mark_warnings([{"model_name": "A", "temperature_c": 1}, {"model_name": "B", "temperature_c": 1}])
    assert w["mixed_materials"] == ["A", "B"]
    assert mark_warnings(mk(1, 2))["mixed_materials"] is None


@pytest.fixture(scope="module")
def sel():
    return selected_lags(ref_lags(REFS, "phase"), [10, 11, 12, 13, 14])


def test_fits(sel):
    fits = fit_lag_models(fit_points(sel))
    assert [f.kind for f in fits] == ["sqrt", "power", "linear", "physical"]
    assert fits[0].rms == pytest.approx(0.16533243660484465, rel=1e-9)
    assert fits[0].predict(400) == pytest.approx(47.25456790896485, rel=1e-9)
    assert active_fit(fits, None).kind == "sqrt"
    assert active_fit(fits, "linear").kind == "linear"
    assert active_fit(fits, "gone").kind == "sqrt"
    assert active_fit([], "linear") is None
    assert active_source(None, fits[0]) == "curve"
    assert active_source(None, None) == "direct"
    assert active_source("direct", fits[0]) == "direct"
    assert active_source("curve", fits[0]) == "curve"
    assert fit_points(sel)[0].period == 75


def test_direct(sel):
    assert direct_lag(sel) == pytest.approx(46, rel=1e-9)
    assert direct_mean_period(sel) == 465
    assert direct_lag([]) is None and direct_mean_period([]) is None


def test_applied_lag(sel):
    fit = fit_lag_models(fit_points(sel))[0]
    t = lambda p: {**TARGET, "period_t": p}
    a = applied_lag(TARGET, "curve", fit, 46, 465)
    assert a.lag == pytest.approx(47.25456790896485, rel=1e-9) and not a.out_of_range
    assert applied_lag(t(74.9), "curve", fit, None, None).out_of_range
    assert applied_lag(t(1200.1), "curve", fit, None, None).out_of_range
    assert not applied_lag(t(75), "curve", fit, None, None).out_of_range
    assert not applied_lag(t(1200), "curve", fit, None, None).out_of_range
    assert applied_lag(TARGET, "curve", None, 46, 465) is None
    d = applied_lag(TARGET, "direct", fit, 46, 465)
    assert d.lag == 46 and d.ratio == pytest.approx(0.8602150537634409) and not d.period_mismatch
    assert not d.out_of_range
    for p, mm in [(372, False), (581.25, False), (371, True), (582, True), (700, True)]:
        assert applied_lag(t(p), "direct", fit, 46, 465).period_mismatch is mm, p
    assert applied_lag({**TARGET, "period_t": None}, "direct", fit, 46, 465) is None
    assert applied_lag(TARGET, "direct", fit, None, 465) is None
    assert applied_lag(TARGET, "direct", fit, 46, None).ratio is None


def test_curve_points(sel):
    fit = fit_lag_models(fit_points(sel))[0]
    x, y = curve_points(fit)
    assert len(x) == len(y) == 120
    assert x[0] == 75 and x[-1] == pytest.approx(1200, rel=1e-12)
    assert x[50] == pytest.approx(75 * 16 ** (50 / 119), rel=1e-12)
