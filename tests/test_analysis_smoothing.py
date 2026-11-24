"""Smoothing helpers and the V8-exact sine/cosine.

The expected numbers were produced by running the TypeScript functions of
lib/analysis.ts (npx tsx) on exactly the signals built here.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from ctwa.analysis import smoothing as sm
from ctwa.analysis.jstrig import cos_array, sin_array


def _signals():
    t, vs, vc = [], [], []
    for i in range(1500):
        x = float(i)
        s, c = 1.0, 0.5
        if x < 400:
            s += 2 * math.cos(2 * math.pi * x / 20)
            c += 0.3 * math.cos(2 * math.pi * (x - 4) / 20)
        elif 800 <= x < 1400:
            s += 2 * math.cos(2 * math.pi * x / 30)
            c += 0.3 * math.cos(2 * math.pi * (x - 6) / 30)
        s += 0.05 * math.sin(i * 12.9898)
        c += 0.02 * math.sin(i * 78.233)
        t.append(x)
        vs.append(s)
        vc.append(c)
    return t, vs, vc


REL = 1e-9


def test_detect_segments_finds_the_two_bursts():
    t, vs, _ = _signals()
    assert sm.detect_segments(t, vs) == [(5, 414), (795, 1395)]
    assert sm.detect_segments(t[:10], vs[:10]) == [(0, 9)]
    assert sm.detect_segments(t[:100], [1.0] * 100) == [(0, 99)]


def test_estimate_and_reconstruct():
    t, vs, _ = _signals()
    assert sm.estimate_fundamental_period(t[:400], vs[:400]) == pytest.approx(19.991002999531574, rel=REL)
    rec = sm.reconstruct_sine_at(t[:400], vs[:400], 1 / 20)
    assert rec[:3] == pytest.approx([2.995653430182781, 2.8983457790142575, 2.6152175370610022], rel=REL)
    assert sum(rec) == pytest.approx(400.01111738584206, rel=REL)
    assert sm.reconstruct_sine_at(t[:400], vs[:400], 0.0) == vs[:400]
    assert sm.reconstruct_sine_at([], [], 1.0) == []


def test_smooth_to_shared_sine():
    t, vs, vc = _signals()
    out = sm.smooth_to_shared_sine(t[:400], vs[:400], t[:400], vc[:400])
    assert out is not None
    v_src, v_cal, freq = out
    assert freq == pytest.approx(0.05002250262397699, rel=REL)
    assert sum(v_src) == pytest.approx(400.3672029317733, rel=REL)
    assert sum(v_cal) == pytest.approx(200.0094890862515, rel=REL)
    assert v_cal[:3] == pytest.approx([0.5845948463742988, 0.6696210111356993, 0.7380289166887997], rel=REL)
    assert sm.smooth_to_shared_sine([0.0, 1.0], [1.0, 1.0], [0.0], [1.0]) is None


def test_smooth_piecewise_replaces_bursts_and_keeps_gaps():
    t, vs, vc = _signals()
    out_s, out_c = sm.smooth_piecewise(t, vs, t, vc)
    assert sum(out_s) == pytest.approx(1485.714949079755, rel=REL)
    assert sum(out_c) == pytest.approx(749.6407677465862, rel=REL)
    assert out_s[398:403] == pytest.approx(
        [2.5433218945107385, 2.8156801608724997, 2.908554964328001, 2.812856560996145, 2.5379510431188743], rel=REL)
    assert out_c[900:903] == pytest.approx([0.5903343100665004, 0.6474831348030645, 0.6982477910571878], rel=REL)
    assert out_s[600] == vs[600]  # heater-off gap keeps the raw values


def test_cos_sin_are_v8_bit_for_bit():
    # Math.cos / Math.sin of these arguments in node 22 (arm64): the platform libm differs in the last bit
    x = np.array([-2.077530943788588, 0.9541435106657445, 82.39515419118106, 4054.838251322508,
                  -41183.96742269397, 0.6841935813426971, -810.8206689357758, 472.3015640863164])
    expected_cos = [-0.48532480421546653, 0.5783077099298533, 0.7559153166842347, -0.5752680917605715,
                    -0.6753723932971004, 0.774928994550481, 0.958311245088582, 0.4865446057556355]
    expected_sin = [-0.8743339375851877, 0.8158187253524454, 0.6546694081765034, 0.8179649274890402,
                    0.7374768676861306, 0.6320482998988136, -0.2857263682910133, 0.8736557368953134]
    assert cos_array(x).tolist() == expected_cos
    assert sin_array(x).tolist() == expected_sin


def test_cos_sin_special_values():
    assert math.isnan(cos_array([math.inf])[0]) and math.isnan(sin_array([-math.inf])[0])
    assert math.isnan(cos_array([math.nan])[0])
    assert cos_array([0.0])[0] == 1.0 and sin_array([0.0])[0] == 0.0
    assert sin_array([1e-300])[0] == 1e-300
