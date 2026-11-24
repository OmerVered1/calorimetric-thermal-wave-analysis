"""Unit tests of ctwa.analysis.peaks and ctwa.analysis.sine_fit.

Pinned numbers marked TS were produced by running the webapp's TypeScript
(lib/peakDetection.ts, lib/sineFit.ts) on the same synthetic signals.
"""

from __future__ import annotations

import math

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
