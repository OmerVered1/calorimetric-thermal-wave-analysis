"""Unit tests of ctwa.analysis.peaks and ctwa.analysis.sine_fit.

Pinned numbers marked TS were produced by running the webapp's TypeScript
(lib/peakDetection.ts, lib/sineFit.ts) on the same synthetic signals.
"""

from __future__ import annotations

import math
import re

import pytest

from ctwa.analysis import peaks as pk
from ctwa.analysis import sine_fit as sf

PERIOD = 200.0
OMEGA = 2 * math.pi / PERIOD


def _nz(i):
    return 0.3 * math.sin(i * 12.9898 + 1.3)


T = [float(i) for i in range(1001)]
SRC = [5 + 0.01 * i + 3 * math.cos(2 * math.pi * i / PERIOD - 0.4) + _nz(i) for i in range(1001)]
CAL = [2 + 1.2 * math.cos(2 * math.pi * (i - 37.5) / PERIOD - 0.4) + _nz(i + 777) for i in range(1001)]


def test_fit_sine_recovers_amplitude_and_phase():
    t = [float(i) for i in range(1001)]
    v = [3 + 2 * math.cos(OMEGA * x - 0.7) for x in t]
    fit = sf.fit_sine(t, v, OMEGA)
    assert fit.amplitude == pytest.approx(2, rel=1e-9)
    assert fit.phase == pytest.approx(0.7, rel=1e-9)


def test_sine_lag_of_delayed_copy():
    t = [float(i) for i in range(1001)]
    a = [3 + 2 * math.cos(OMEGA * x - 0.7) for x in t]
    b = [3 + 2 * math.cos(OMEGA * (x - 37) - 0.7) for x in t]
    res = sf.sine_lag(t, a, t, b, PERIOD)
    assert res.lag == pytest.approx(37, abs=1e-6)


def test_choose_lag_cycle_near_edge():
    assert sf.choose_lag_cycle(0.01 * PERIOD, PERIOD).near_edge is True
    assert sf.choose_lag_cycle(0.5 * PERIOD, PERIOD).near_edge is False
    c = sf.choose_lag_cycle(95, 100, 1.5)  # Math.round(1.5) = 2
    assert (c.dt, c.cycles, c.near_edge) == (295, 2, False)
    c = sf.choose_lag_cycle(95, 100, -3)
    assert (c.dt, c.cycles, c.near_edge) == (95, 0, True)


def test_lag_into_period():
    assert sf.lag_into_period(-5, 100) == 95
    assert sf.lag_into_period(250, 100) == 50
    assert sf.lag_into_period(-200, 100) == 0


def test_find_peaks_simple():
    assert pk.find_peaks([0, 1, 0, 2, 0, 1, 0], 1) == [1, 3, 5]
    assert pk.find_peaks([0, 1], 1) == []


def test_find_peaks_plateau_and_distance():
    # plateau: rising edge strict, falling edge >= -> first sample of plateau
    assert pk.find_peaks([0, 2, 2, 0], 1) == [1]
    # distance 3: tallest (idx 3) suppresses idx 1 and 5? |3-1|=2<3 yes, |5-3|=2<3 yes
    assert pk.find_peaks([0, 1, 0, 2, 0, 1, 0], 3) == [3]


def test_ts_pinned_peaks():  # TS
    assert pk.find_peaks(SRC[:60], 1) == [1, 16, 30, 44, 58]
    assert pk.find_peaks(SRC[:120], 7) == [1, 16, 30, 44, 58, 73, 89, 104]
    idx, times = pk.auto_detect_peaks(T, SRC)
    assert idx == [16, 73, 166, 223, 281, 359, 416, 474, 552, 609, 667, 760, 817, 875, 937, 996]
    assert times == [T[i] for i in idx]
    assert pk.find_troughs(SRC, 50) == [54, 112, 169, 247, 305, 362, 455, 512, 570, 648, 706, 763, 856, 913, 970]
    assert pk.compute_cycle_amplitude(SRC, idx) == pytest.approx(1.0291989109340225, rel=1e-12)
    assert pk.compute_cycle_amplitude(SRC, [3]) == pytest.approx(7.499271746121643, rel=1e-12)
    t, v, i = pk.snap_to_peak(210, T, SRC)
    assert (t, i) == (223, 223)
    assert v == pytest.approx(10.373955610054429, rel=1e-12)


def test_ts_pinned_fit_sine():  # TS
    f = sf.fit_sine(T, SRC, OMEGA, 2)
    assert f.amplitude == pytest.approx(3.0013651687233933, rel=1e-9)
    assert f.phase == pytest.approx(0.3997672460266339, rel=1e-9)
    assert f.sigma == pytest.approx(0.21262889630402307, rel=1e-9)
    assert f.se_phase == pytest.approx(0.0031666597779031382, rel=1e-9)
    assert f.n == 1001
    g = sf.fit_sine(T, CAL, OMEGA, 1)
    assert g.amplitude == pytest.approx(1.200036864309978, rel=1e-9)
    assert g.phase == pytest.approx(1.5804506811141905, rel=1e-9)
    assert sf.fit_sine(T[:5], SRC[:5], OMEGA) is None
    assert sf.fit_sine(T, SRC, -1.0) is None


def test_ts_pinned_baseline_degree():  # TS
    assert [sf.baseline_degree(c) for c in [0, 2, 4, 7, 8, 10, 30]] == [2, 2, 2, 2, 3, 3, 6]


def test_ts_pinned_remove_period_mean_and_refine_period():  # TS
    t, v = sf.remove_period_mean(T, SRC, PERIOD)
    assert len(t) == 801
    assert v[0] == pytest.approx(-2.865365351899327, rel=1e-9)
    assert v[300] == pytest.approx(3.0256677181320963, rel=1e-9)
    assert v[-1] == pytest.approx(-3.001300164654486, rel=1e-9)
    assert sf.refine_period(T, SRC, 198) == pytest.approx(200.78414366136298, rel=1e-9)
    assert sf.refine_period(T[:5], SRC[:5], 198) == 198


def test_ts_pinned_sine_lag():  # TS
    r = sf.sine_lag(T, SRC, T, CAL, PERIOD)
    assert r.lag == pytest.approx(37.4859414402232, rel=1e-9)
    assert r.lag_se == pytest.approx(0.03609436894749193, rel=1e-9)
    assert (r.se_source, r.blocks) == ("blocks", 4)
    assert r.amplitude_src == pytest.approx(3.0001968485999018, rel=1e-9)
    assert r.amplitude_cal == pytest.approx(1.1999059173790476, rel=1e-9)
    assert r.phase_src == pytest.approx(0.4002621061583671, rel=1e-9)
    r = sf.sine_lag(T[:350], SRC[:350], T[:350], CAL[:350], PERIOD)
    assert r.lag == pytest.approx(37.67504675375746, rel=1e-9)
    assert r.lag_se == pytest.approx(0.4592742824715196, rel=1e-9)
    assert (r.se_source, r.blocks) == ("formal", 0)
    assert sf.sine_lag(T[:5], SRC[:5], T, CAL, PERIOD) is None


def test_ts_pinned_refine_peak():  # TS
    t, v = sf.refine_peak(T, SRC, 215, PERIOD)
    assert t == pytest.approx(216.43224329830002, rel=1e-9)
    assert v == pytest.approx(10.096439851641367, rel=1e-9)
    assert sf.refine_peak(T[:4], SRC[:4], 2, PERIOD) is None


# ---------------------------------------------------------------------------
# Task 6: diffusivity, Auto, Manual and square-wave analysis
# ---------------------------------------------------------------------------

import dataclasses  # noqa: E402
import gzip  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402

from ctwa.analysis import diffusivity as dfs  # noqa: E402
from ctwa.analysis import jsmath as jm  # noqa: E402
from ctwa.analysis import modes as md  # noqa: E402
from ctwa.analysis import smoothing as sm  # noqa: E402
from ctwa.analysis import square as sq  # noqa: E402
from ctwa.analysis.parser import parse_combined_file  # noqa: E402
from ctwa.analysis.types import AnalysisParams  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))


def _params(**over):
    base = dict(
        model_name="golden", test_date="", test_time="", t_cal="00:00:00", t_src="00:00:00",
        r1_mm=6.72, r2_mm=14.86, c80_time_unit="Seconds", c80_pwr_unit="mW",
        src_time_unit="Seconds", src_pwr_unit="mW", use_calibration=False, system_lag=0,
        analysis_mode="Auto", cycle_shift=0, manual_snap=False,
    )
    base.update(over)
    return AnalysisParams(**base)


def _assert_results(res, expected):
    """Every AnalysisResults field equals the TS output (fields the TS leaves out are None)."""
    for f in dataclasses.fields(res):
        want = expected.get(f.name)
        got = getattr(res, f.name)
        if want is None:
            assert got is None, f.name
        elif isinstance(want, (bool, str)):
            assert got == want and type(got) is type(want), f.name
        elif math.isnan(want):
            assert math.isnan(got), f.name
        else:
            assert got == pytest.approx(want, rel=1e-9, abs=1e-12), f.name


# -- jsmath ------------------------------------------------------------------


def test_jsmath_non_finite_semantics():
    nan, inf = math.nan, math.inf
    assert jm.js_floor(2.5) == 2 and jm.js_floor(-2.5) == -3
    assert jm.js_floor(inf) == inf and jm.js_floor(-inf) == -inf and math.isnan(jm.js_floor(nan))
    assert jm.js_round(2.5) == 3 and jm.js_round(-2.5) == -2 and jm.js_round(inf) == inf
    assert math.isnan(jm.js_round(nan))
    assert jm.js_div(1, 0) == inf and jm.js_div(-1, 0) == -inf and math.isnan(jm.js_div(0, 0))
    assert jm.js_div(1, -0.0) == -inf
    assert math.isnan(jm.js_fmod(5, 0)) and math.isnan(jm.js_fmod(inf, 3)) and jm.js_fmod(-7, 3) == -1
    assert jm.js_fmod(3, inf) == 3
    assert math.isnan(jm.js_min(1, nan)) and math.isnan(jm.js_max(nan, 1))
    assert jm.js_log(0) == -inf and math.isnan(jm.js_log(-1)) and math.isnan(jm.js_sqrt(-1))
    assert math.isnan(jm.js_cos(inf)) and math.isnan(jm.js_sin(-inf))
    assert jm.array_max([1, nan, 3]) == 3 and jm.array_min([]) == inf


# -- calculate_thermal_diffusivity ---------------------------------------------


def test_diffusivity_phase_alpha_formula():
    # TS: phi = w * |dt| (rad), alpha in m^2/s from r in metres.
    w = 2 * math.pi / 300
    r = dfs.calculate_thermal_diffusivity(
        10, 5, 300, w, 40, _params(), 0, 1, 2, 3, 4
    )
    dr = (14.86 - 6.72) / 1000
    phi = w * 40
    assert r.raw_phase_phi == pytest.approx(phi, rel=1e-12)
    assert r.alpha_phase_raw == pytest.approx((w / 2) * (dr / phi) ** 2, rel=1e-12)
    _assert_results(r, TS_DIFF1)


def test_diffusivity_ln_term_not_positive_gives_none_combined():
    w = 2 * math.pi / 300
    r = dfs.calculate_thermal_diffusivity(10, 9, 300, w, 40, _params(), 0, 1, 2, 3, 4)
    assert r.ln_term <= 0
    assert r.alpha_combined_raw is None and r.alpha_combined_cal is None
    assert math.isfinite(r.alpha_phase_raw) and r.alpha_phase_raw > 0
    _assert_results(r, TS_DIFF2)


def test_diffusivity_calibration_and_edges():
    w = 2 * math.pi / 300
    cal = _params(use_calibration=True, system_lag=50)
    _assert_results(dfs.calculate_thermal_diffusivity(10, 5, 300, w, -40, cal, 0, 1, 2, 3, 4), TS_DIFF3)
    cal40 = _params(use_calibration=True, system_lag=40)
    _assert_results(dfs.calculate_thermal_diffusivity(10, 5, 300, w, 40, cal40, 0, 1, 2, 3, 4), TS_DIFF4)
    # dt = 0: JS divides by zero to Infinity instead of raising
    _assert_results(dfs.calculate_thermal_diffusivity(10, 5, 300, w, 0, _params(), 0, 1, 2, 3, 4), TS_DIFF5)
    with pytest.raises(ValueError) as e:
        dfs.calculate_thermal_diffusivity(0, 5, 300, 1, 40, _params(), 0, 1, 2, 3, 4)
    assert str(e.value) == "Amplitudes and radii must be positive"


def test_theoretical_phase_and_lag():  # TS
    assert dfs.theoretical_phase(0.1, 8.14, 300) == pytest.approx(2.634139154700566, rel=1e-12)
    assert dfs.theoretical_lag_dt(0.1, 8.14, 300) == pytest.approx(125.77088017875057, rel=1e-12)
    assert dfs.theoretical_phase(0, 8.14, 300) is None
    assert dfs.theoretical_lag_dt(0.1, 8.14, 0) is None


def test_sync_and_filter_data():  # TS
    p = _params(t_cal="01:00:00", t_src="01:10:30", c80_time_unit="Minutes", c80_pwr_unit="Watts",
                src_time_unit="ms", src_pwr_unit="uW", day_offset=1, clock_ahead_s=5)
    s = dfs.sync_and_filter_data([0, 100, 600, 3000, 3700], [1, 2, 3, 4, 5], [1, 2, 3], [10, 20, 30], p)
    assert s.t_src == [87025.001, 87025.002, 87025.003]
    assert s.v_src == [0.01, 0.02, 0.03]
    assert s.t_cal == [] and s.v_cal == []
    s = dfs.sync_and_filter_data(
        [0, 100, 600, 1200], [1, 2, 3, 4], [1, 2, 3], [10, 20, 30], _params(t_src="00:10:00")
    )
    assert (s.t_src, s.v_src, s.t_cal, s.v_cal) == ([601, 602, 603], [10, 20, 30], [600], [3])


# -- square helpers ------------------------------------------------------------


def test_square_helpers_small():
    t = [float(i) for i in range(40)]
    v = [1.0 if (i // 5) % 2 else 0.0 for i in range(40)]
    assert sq.detect_square_period(t, v) == pytest.approx(10.0, rel=1e-12)
    assert math.isnan(sq.detect_square_period(t[:3], v[:3]))
    assert math.isnan(sq.detect_square_period(t[:8], v[:8]))
    ft, fv = sq.filter_to_range(t, v, 3, 6)
    assert ft == [3.0, 4.0, 5.0, 6.0] and fv == v[3:7]
    assert sq.extract_fourier_fundamental(t[:1], v[:1], 0.1) == (0.0, 0.0)
    assert sq.extract_fourier_fundamental(t, v[:5], 0.1) == (0.0, 0.0)


# -- the real run: TS-pinned Auto / Manual / square ------------------------------


@pytest.fixture(scope="module")
def real_run():
    with gzip.open(os.path.join(_HERE, "data", "runs", "al2o3_ctwa.csv.gz"), "rb") as f:
        parsed = parse_combined_file(f.read())
    t = parsed.time
    span = max(t) - min(t)
    sel_min = math.floor(min(t) + span * 0.3 + 0.5)
    sel_max = math.floor(min(t) + span * 0.7 + 0.5)
    assert (sel_min, sel_max) == (5463, 12745)
    idx = [i for i in range(len(t)) if sel_min <= t[i] <= sel_max]
    ts = [t[i] for i in idx]
    return dict(
        t_src=ts, v_src=[parsed.source[i] for i in idx],
        t_cal=list(ts), v_cal=[parsed.response[i] for i in idx],
        t_min=sel_min, t_max=sel_max,
    )


def _args(r):
    return (r["t_cal"], r["v_cal"], r["t_src"], r["v_src"])


def _golden_clicks(name):
    with open(os.path.join(_HERE, "golden", "analysis", name), encoding="utf-8") as f:
        g = json.load(f)
    return [tuple(c) for c in g["options"]["clicks"]], g


def test_ts_pinned_estimate_fundamental_period(real_run):
    est = sm.estimate_fundamental_period(real_run["t_src"], sm.linear_detrend(real_run["t_src"], real_run["v_src"]))
    assert est == pytest.approx(80.2460169850423, rel=1e-9)
    assert sm.estimate_fundamental_period([0.0] * 3, [1.0] * 3) is None


def test_ts_pinned_fourier_and_square_period(real_run):
    assert sq.detect_square_period(real_run["t_src"], real_run["v_src"]) == pytest.approx(94.8212881566514, rel=1e-9)
    f = sq.extract_fourier_fundamental(real_run["t_src"], real_run["v_src"], 1 / 80)
    assert f.amplitude == pytest.approx(3.5794497664757357, rel=1e-9)
    assert f.phase == pytest.approx(-2.942214683498426, rel=1e-9)


def test_ts_pinned_auto(real_run):
    r = real_run
    _assert_results(md.run_auto_analysis(*_args(r), _params(), r["t_min"], r["t_max"]), TS_AUTO)
    p = _params(use_calibration=True, system_lag=20, cycle_shift=1)
    _assert_results(md.run_auto_analysis(*_args(r), p, r["t_min"], r["t_max"]), TS_AUTO_CALIB)


def test_ts_pinned_manual_dense_clicks_as_given(real_run):
    r = real_run
    clicks, g = _golden_clicks("al2o3_ctwa__ManualDense_raw.json")
    res = md.run_manual_analysis(*_args(r), _params(analysis_mode="Manual"), r["t_min"], r["t_max"], clicks)
    _assert_results(res, TS_MANUAL_DENSE)
    for k, v in g["results"].items():  # and the golden file itself
        assert getattr(res, re.sub(r"([A-Z])", r"_\1", k).lower()) == pytest.approx(v, rel=1e-9)


def test_ts_pinned_manual_with_snapping(real_run):
    r = real_run
    clicks, _ = _golden_clicks("al2o3_ctwa__ManualDense_raw.json")
    p = _params(analysis_mode="Manual", manual_snap=None)
    _assert_results(md.run_manual_analysis(*_args(r), p, r["t_min"], r["t_max"], clicks), TS_MANUAL_SNAP)
    # three clicks: no second response peak, so no pair spread and the period is read from the peaks
    _assert_results(md.run_manual_analysis(*_args(r), p, r["t_min"], r["t_max"], clicks[:3]), TS_MANUAL_SNAP3)


def test_ts_manual_errors(real_run):
    r = real_run
    clicks, g = _golden_clicks("al2o3_ctwa__Manual_raw.json")
    with pytest.raises(ValueError) as e:
        md.run_manual_analysis(*_args(r), _params(), r["t_min"], r["t_max"], clicks)
    assert str(e.value) == g["error"]
    assert "disagree by more than a quarter of a period" in g["error"]

    def err(c):
        with pytest.raises(ValueError) as ei:
            md.run_manual_analysis(*_args(r), _params(), r["t_min"], r["t_max"], c)
        return str(ei.value)

    assert err([(1, 0), (2, 0)]) == "Need at least 3 click coordinates for manual analysis"
    assert err([(5600, 0), (5600, 0), (5700, 0)]) == (
        "The two source peaks are at the same time. Place them on different peaks."
    )
    assert err([(5527.966715, 0), (5611.993398, 0), (5500, 0)]) == (
        "Each response peak must come after its source peak."
    )


def test_ts_pinned_square(real_run):
    r = real_run
    _assert_results(sq.run_square_analysis(*_args(r), _params(analysis_mode="AutoFit"), r["t_min"], r["t_max"]), TS_SQUARE)
    p = _params(cycle_shift=1)
    _assert_results(sq.run_square_analysis(*_args(r), p, r["t_min"], r["t_max"], 80), TS_SQUARE_OVERRIDE)
    with pytest.raises(ValueError) as e:
        sq.run_square_analysis(*_args(r), _params(), r["t_min"], r["t_min"] + 1)
    assert str(e.value) == "Not enough samples in the selected range for Fourier analysis."


def test_auto_without_peaks_error():
    t = [float(i) for i in range(100)]
    v = [1.0] * 100
    with pytest.raises(ValueError) as e:
        md.run_auto_analysis(t, v, t, v, _params(), 0, 99)
    assert str(e.value) == "Not enough peaks detected. Try manual mode or adjust the selection range."


TS_AUTO = {
    "amplitude_a1": 3.851735248604363,
    "amplitude_a2": 0.04541888482608224,
    "period_t": 80.2460169850423,
    "frequency_f": 0.012461677695310385,
    "period_t_resp": 80.86377017948718,
    "frequency_f_resp": 0.012366477568141776,
    "angular_freq_w": 0.07829903019798178,
    "raw_lag_dt": 45.009656985043335,
    "raw_phase_phi": 3.5242124914727095,
    "ln_term": 4.043558613396837,
    "alpha_combined_raw": 1.820326820900969e-07,
    "alpha_combined_cal": 1.820326820900969e-07,
    "alpha_phase_raw": 2.088579565977171e-07,
    "alpha_phase_cal": 2.088579565977171e-07,
    "net_lag_dt": 45.009656985043335,
    "net_phase_phi": 3.5242124914727095,
    "t_min": 5463,
    "t_max": 12745,
    "marker_src_time": 5817.989333,
    "marker_src2_time": 5887.962995,
    "marker_cal_time": 5862.998989985043,
    "mean_peak_src": 29.987678305666652,
    "mean_trough_src": 0.005959161250782027,
    "mean_peak_cal": 150.23837500000002,
    "mean_trough_cal": 150.0035641025641,
    "lag_cycles": 0,
    "lag_near_edge": False,
}

TS_AUTO_CALIB = {
    "amplitude_a1": 3.851735248604363,
    "amplitude_a2": 0.04541888482608224,
    "period_t": 80.2460169850423,
    "frequency_f": 0.012461677695310385,
    "period_t_resp": 80.86377017948718,
    "frequency_f_resp": 0.012366477568141776,
    "angular_freq_w": 0.07829903019798178,
    "raw_lag_dt": 125.25567397008564,
    "raw_phase_phi": 9.807397798652294,
    "ln_term": 4.043558613396837,
    "alpha_combined_raw": 6.541203540926587e-08,
    "alpha_combined_cal": 7.784120581728709e-08,
    "alpha_phase_raw": 2.6969172111617866e-08,
    "alpha_phase_cal": 3.819191175789337e-08,
    "net_lag_dt": 105.25567397008564,
    "net_phase_phi": 8.24141719469266,
    "t_min": 5463,
    "t_max": 12745,
    "marker_src_time": 5817.989333,
    "marker_src2_time": 5887.962995,
    "marker_cal_time": 5943.245006970086,
    "mean_peak_src": 29.987678305666652,
    "mean_trough_src": 0.005959161250782027,
    "mean_peak_cal": 150.23837500000002,
    "mean_trough_cal": 150.0035641025641,
    "lag_cycles": 1,
    "lag_near_edge": False,
}

TS_MANUAL_DENSE = {
    "amplitude_a1": 1.038789284657105,
    "amplitude_a2": 0.013640678283608725,
    "period_t": 84.02668300000005,
    "frequency_f": 0.011900981501316665,
    "period_t_resp": 71.99280499999986,
    "frequency_f_resp": 0.013890276951981547,
    "angular_freq_w": 0.07477607211008892,
    "raw_lag_dt": 47.00590100000045,
    "raw_phase_phi": 3.514916642775735,
    "ln_term": 3.9359623435254956,
    "alpha_combined_raw": 1.7906697528818693e-07,
    "alpha_combined_cal": 1.7906697528818693e-07,
    "alpha_phase_raw": 2.0051709423946169e-07,
    "alpha_phase_cal": 2.0051709423946169e-07,
    "net_lag_dt": 47.00590100000045,
    "net_phase_phi": 3.514916642775735,
    "t_min": 5463,
    "t_max": 12745,
    "marker_src_time": 5527.966715,
    "marker_src2_time": 5611.993398,
    "marker_cal_time": 5580.989555,
    "mean_peak_src": 29.988623341666667,
    "mean_trough_src": 0.0041126531780861,
    "mean_peak_cal": 150.351,
    "mean_trough_cal": 149.4573333333333,
    "lag_se": 6.016939000000093,
    "lag_se_source": 'pairs',
}

TS_MANUAL_SNAP = {
    "amplitude_a1": 3.0722936168463413,
    "amplitude_a2": 0.029943827264612727,
    "period_t": 74.33275688582307,
    "frequency_f": 0.013453019125014083,
    "period_t_resp": 75.4529755731055,
    "frequency_f_resp": 0.013253287791561139,
    "angular_freq_w": 0.08452781210349446,
    "raw_lag_dt": 51.122547520536045,
    "raw_phase_phi": 4.321277091067837,
    "ln_term": 4.234064023752296,
    "alpha_combined_raw": 1.5305548788485735e-07,
    "alpha_combined_cal": 1.5305548788485735e-07,
    "alpha_phase_raw": 1.499664847298626e-07,
    "alpha_phase_cal": 1.499664847298626e-07,
    "net_lag_dt": 51.122547520536045,
    "net_phase_phi": 4.321277091067837,
    "t_min": 5463,
    "t_max": 12745,
    "marker_src_time": 5547.973617,
    "marker_src2_time": 5622.306373885823,
    "marker_cal_time": 5598.5360551768945,
    "mean_peak_src": 29.988623341666667,
    "mean_trough_src": 0.0041126531780861,
    "mean_peak_cal": 150.351,
    "mean_trough_cal": 149.4573333333333,
    "lag_se": 0.5601093436412157,
    "lag_se_source": 'pairs',
}

TS_MANUAL_SNAP3 = {
    "amplitude_a1": 3.0722936168463413,
    "amplitude_a2": 0.029943827264612727,
    "period_t": 74.33275688582307,
    "frequency_f": 0.013453019125014083,
    "period_t_resp": 1051.2290123333332,
    "frequency_f_resp": 0.0009512675052416751,
    "angular_freq_w": 0.08452781210349446,
    "raw_lag_dt": 50.56243817689483,
    "raw_phase_phi": 4.273932273711121,
    "ln_term": 4.234064023752296,
    "alpha_combined_raw": 1.5475097196258225e-07,
    "alpha_combined_cal": 1.5475097196258225e-07,
    "alpha_phase_raw": 1.5330741833644624e-07,
    "alpha_phase_cal": 1.5330741833644624e-07,
    "net_lag_dt": 50.56243817689483,
    "net_phase_phi": 4.273932273711121,
    "t_min": 5463,
    "t_max": 12745,
    "marker_src_time": 5547.973617,
    "marker_src2_time": 5622.306373885823,
    "marker_cal_time": 5598.5360551768945,
    "mean_peak_src": 29.988623341666667,
    "mean_trough_src": 0.0041126531780861,
    "mean_peak_cal": 150.351,
    "mean_trough_cal": 149.4573333333333,
}

TS_SQUARE = {
    "amplitude_a1": 0.37339921114221464,
    "amplitude_a2": 0.021202163241739617,
    "period_t": 94.8212881566514,
    "frequency_f": 0.010546154976801517,
    "period_t_resp": 160.53337450000072,
    "frequency_f_resp": 0.0062292342829932575,
    "angular_freq_w": 0.06626344599747816,
    "raw_lag_dt": 71.28464741904035,
    "raw_phase_phi": 4.7235663847008516,
    "ln_term": 2.471752459916475,
    "alpha_combined_raw": 1.880259679952176e-07,
    "alpha_combined_cal": 1.880259679952176e-07,
    "alpha_phase_raw": 9.839041331686268e-08,
    "alpha_phase_cal": 9.839041331686268e-08,
    "net_lag_dt": 71.28464741904035,
    "net_phase_phi": 4.7235663847008516,
    "t_min": 5463,
    "t_max": 12745,
    "marker_src_time": 5499.959068,
    "marker_src2_time": 5594.780356156652,
    "marker_cal_time": 5571.24371541904,
    "mean_peak_src": 0,
    "mean_trough_src": 0,
    "mean_peak_cal": 0,
    "mean_trough_cal": 0,
    "lag_cycles": 0,
    "lag_near_edge": False,
}

TS_SQUARE_OVERRIDE = {
    "amplitude_a1": 3.5794497664757357,
    "amplitude_a2": 0.06201769519878743,
    "period_t": 80,
    "frequency_f": 0.0125,
    "period_t_resp": 160.53337450000072,
    "frequency_f_resp": 0.0062292342829932575,
    "angular_freq_w": 0.07853981633974483,
    "raw_lag_dt": 124.8156133810015,
    "raw_phase_phi": 9.802995351276454,
    "ln_term": 3.6587521779333123,
    "alpha_combined_raw": 7.25465735081742e-08,
    "alpha_combined_cal": 7.25465735081742e-08,
    "alpha_phase_raw": 2.70764112715885e-08,
    "alpha_phase_cal": 2.70764112715885e-08,
    "net_lag_dt": 124.8156133810015,
    "net_phase_phi": 9.802995351276454,
    "t_min": 5463,
    "t_max": 12745,
    "marker_src_time": 5499.959068,
    "marker_src2_time": 5579.959068,
    "marker_cal_time": 5624.774681381002,
    "mean_peak_src": 0,
    "mean_trough_src": 0,
    "mean_peak_cal": 0,
    "mean_trough_cal": 0,
    "lag_cycles": 1,
    "lag_near_edge": False,
}

TS_DIFF1 = {
    "amplitude_a1": 10,
    "amplitude_a2": 5,
    "period_t": 300,
    "frequency_f": 0.0033333333333333335,
    "period_t_resp": None,
    "frequency_f_resp": None,
    "angular_freq_w": 0.020943951023931952,
    "raw_lag_dt": 40,
    "raw_phase_phi": 0.8377580409572781,
    "ln_term": 0.2963547381826678,
    "alpha_combined_raw": 2.7947756296357405e-06,
    "alpha_combined_cal": 2.7947756296357405e-06,
    "alpha_phase_raw": 9.886446438086018e-07,
    "alpha_phase_cal": 9.886446438086018e-07,
    "net_lag_dt": 40,
    "net_phase_phi": 0.8377580409572781,
    "t_min": 0,
    "t_max": 1,
    "marker_src_time": 2,
    "marker_src2_time": 3,
    "marker_cal_time": 4,
    "mean_peak_src": 0,
    "mean_trough_src": 0,
    "mean_peak_cal": 0,
    "mean_trough_cal": 0,
}

TS_DIFF2 = {
    "amplitude_a1": 10,
    "amplitude_a2": 9,
    "period_t": 300,
    "frequency_f": 0.0033333333333333335,
    "period_t_resp": None,
    "frequency_f_resp": None,
    "angular_freq_w": 0.020943951023931952,
    "raw_lag_dt": 40,
    "raw_phase_phi": 0.8377580409572781,
    "ln_term": -0.2914319267194513,
    "alpha_combined_raw": None,
    "alpha_combined_cal": None,
    "alpha_phase_raw": 9.886446438086018e-07,
    "alpha_phase_cal": 9.886446438086018e-07,
    "net_lag_dt": 40,
    "net_phase_phi": 0.8377580409572781,
    "t_min": 0,
    "t_max": 1,
    "marker_src_time": 2,
    "marker_src2_time": 3,
    "marker_cal_time": 4,
    "mean_peak_src": 0,
    "mean_trough_src": 0,
    "mean_peak_cal": 0,
    "mean_trough_cal": 0,
}

TS_DIFF3 = {
    "amplitude_a1": 10,
    "amplitude_a2": 5,
    "period_t": 300,
    "frequency_f": 0.0033333333333333335,
    "period_t_resp": None,
    "frequency_f_resp": None,
    "angular_freq_w": 0.020943951023931952,
    "raw_lag_dt": 40,
    "raw_phase_phi": 0.8377580409572781,
    "ln_term": 0.2963547381826678,
    "alpha_combined_raw": 2.7947756296357405e-06,
    "alpha_combined_cal": -1,
    "alpha_phase_raw": 9.886446438086018e-07,
    "alpha_phase_cal": -1,
    "net_lag_dt": -10,
    "net_phase_phi": 0,
    "t_min": 0,
    "t_max": 1,
    "marker_src_time": 2,
    "marker_src2_time": 3,
    "marker_cal_time": 4,
    "mean_peak_src": 0,
    "mean_trough_src": 0,
    "mean_peak_cal": 0,
    "mean_trough_cal": 0,
}

TS_DIFF4 = {
    "amplitude_a1": 10,
    "amplitude_a2": 5,
    "period_t": 300,
    "frequency_f": 0.0033333333333333335,
    "period_t_resp": None,
    "frequency_f_resp": None,
    "angular_freq_w": 0.020943951023931952,
    "raw_lag_dt": 40,
    "raw_phase_phi": 0.8377580409572781,
    "ln_term": 0.2963547381826678,
    "alpha_combined_raw": 2.7947756296357405e-06,
    "alpha_combined_cal": -1,
    "alpha_phase_raw": 9.886446438086018e-07,
    "alpha_phase_cal": -1,
    "net_lag_dt": 0,
    "net_phase_phi": 0,
    "t_min": 0,
    "t_max": 1,
    "marker_src_time": 2,
    "marker_src2_time": 3,
    "marker_cal_time": 4,
    "mean_peak_src": 0,
    "mean_trough_src": 0,
    "mean_peak_cal": 0,
    "mean_trough_cal": 0,
}

TS_DIFF5 = {
    "amplitude_a1": 10,
    "amplitude_a2": 5,
    "period_t": 300,
    "frequency_f": 0.0033333333333333335,
    "period_t_resp": None,
    "frequency_f_resp": None,
    "angular_freq_w": 0.020943951023931952,
    "raw_lag_dt": 0,
    "raw_phase_phi": 0,
    "ln_term": 0.2963547381826678,
    "alpha_combined_raw": math.inf,
    "alpha_combined_cal": -1,
    "alpha_phase_raw": math.inf,
    "alpha_phase_cal": -1,
    "net_lag_dt": 0,
    "net_phase_phi": 0,
    "t_min": 0,
    "t_max": 1,
    "marker_src_time": 2,
    "marker_src2_time": 3,
    "marker_cal_time": 4,
    "mean_peak_src": 0,
    "mean_trough_src": 0,
    "mean_peak_cal": 0,
    "mean_trough_cal": 0,
}
