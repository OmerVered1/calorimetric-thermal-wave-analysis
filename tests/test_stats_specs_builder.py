"""Statistics builder chart spec; expected values pinned from page.tsx's own code (node, bodies pasted verbatim)."""
from __future__ import annotations

import json
import math
import os

import pytest

from ctwa.analysis.diffusivity import theoretical_lag_dt, theoretical_phase
from ctwa.analysis.references import LITERATURE, LITERATURE_COLORS
from ctwa.results.helpers import material_color
from ctwa.stats import specs as S
from ctwa.stats.filters import FilterState, apply_filters
from ctwa.stats.model import extract_y, prepare_rows
from ctwa.stats.view_state import ViewState

FIX = os.path.join(os.path.dirname(__file__), "data", "stats_rows.json")
with open(FIX, encoding="utf-8") as _f:
    RAW = json.load(_f)
ALL = prepare_rows(RAW)
ORIGS = apply_filters(ALL, FilterState())
PRESETS = [{"id": 1, "material_name": "Stainless Steel", "temperature_c": 25, "alpha_mm2s": 4.0},
           {"id": 2, "material_name": "Al", "temperature_c": 25, "alpha_mm2s": 64},
           {"id": 3, "material_name": "Abs", "temperature_c": 150, "alpha_mm2s": 0.08}]
JS_COLORS = ['#3498db', '#e74c3c', '#2ecc71', '#f39c12', '#9b59b6', '#1abc9c', '#e67e22', '#34495e', '#c0392b', '#16a085']

PINS = {'B': {'box': {'groups': ['Stainless Steel', 'unk foam', 'Abs', 'Al₂O₃'],
               'ticktext': ['Stainless Steel<br>n = 5', 'unk foam<br>n = 3', 'Abs<br>n = 3', 'Al₂O₃<br>n = 3'],
               'traces': [{'name': 'Stainless Steel',
                           'vals': [0.9691418580874664,
                                    4.489762489605648,
                                    1.4791356434388696,
                                    0.6569858967997513,
                                    0.6251318614600125]},
                          {'name': 'unk foam', 'vals': [1.37496173181514, 1.9291902643256769, 1.7698621584590173]},
                          {'name': 'Abs', 'vals': [2.543086081046141, 0.6882723484653432, 1.2389023164709594]},
                          {'name': 'Al₂O₃', 'vals': [0.715242960294227, 0.5515971271051913, 3.506152416128607]}],
               'drInfo': {'dr': 8.14, 'all': [8.14, 6], 'mixed': True}},
       'bar': {'groups': ['Stainless Steel', 'unk foam', 'Abs', 'Al₂O₃'],
               'ticktext': ['Stainless Steel<br>n = 5', 'unk foam<br>n = 4', 'Abs<br>n = 3', 'Al₂O₃<br>n = 3'],
               'traces': [{'name': 'Stainless Steel', 'y': 5.169791610274032, 'err': 0.9690843795608122},
                          {'name': 'unk foam', 'y': 2.499391664745301, 'err': 0.9275728737621688},
                          {'name': 'Abs', 'y': 2.144874386483755, 'err': 0.9090990774819171},
                          {'name': 'Al₂O₃', 'y': 5.42373696047309, 'err': 2.33940526199667}],
               'drInfo': {'dr': 8.14, 'all': [8.14, 6], 'mixed': True}},
       'barBand': {'groups': ['> 1200 s', '200–400 s', '< 200 s', '400–700 s'],
                   'ticktext': ['> 1200 s<br>n = 1', '200–400 s<br>n = 0', '< 200 s<br>n = 0', '400–700 s<br>n = 0'],
                   'traces': [{'name': '> 1200 s', 'y': 0.7867672563236497, 'err': 0},
                              {'name': '200–400 s', 'y': 0, 'err': 0},
                              {'name': '< 200 s', 'y': 0, 'err': 0},
                              {'name': '400–700 s', 'y': 0, 'err': 0}],
                   'drInfo': {'dr': 8.14, 'all': [8.14, 6], 'mixed': True}},
       'scatter': {'traces': [{'name': 'Stainless Steel',
                               'x': [1200, 254.99, 600, 2400, 2400],
                               'y': [0.18, 0.35, 0.25, 0.14, 0.15],
                               'ids': [18, 16, 7, 5, 2],
                               'hover0': 'Stainless Steel | 1200s | 01/09/2026 | #18\n'
                                         'Period (s): 1200\n'
                                         'Raw Phase φ (rad): 0.18'},
                              {'name': 'unk foam',
                               'x': [255, 199.9, 200, 1200, 699.9],
                               'y': [0.6, 0.55, 0.57, 0.4, 0.45],
                               'ids': [15, 14, 13, 8, 4],
                               'hover0': 'unk foam | 260s | 15/08/2026 | #15\n'
                                         'Period (s): 255\n'
                                         'Raw Phase φ (rad): 0.6'},
                              {'name': 'Abs',
                               'x': [75, 523, 300, 400],
                               'y': [0.9, 0.5, 0.7, 0.4],
                               'ids': [12, 11, 6, 3],
                               'hover0': 'Abs | 80s | 01/09/2026 | #12\nPeriod (s): 75\nRaw Phase φ (rad): 0.9'},
                              {'name': 'Al₂O₃',
                               'x': [2400, 1200, 75],
                               'y': [0.1, 0.17, 0.8],
                               'ids': [10, 9, 1],
                               'hover0': 'Al₂O₃ | 2400s | 01/09/2026 | #10\n'
                                         'Period (s): 2400\n'
                                         'Raw Phase φ (rad): 0.1'}],
                   'trends': [{'x': [254.99, 2400],
                               'y': [0.3023776019323007, 0.13251247558839976],
                               'name': 'Trend (Stainless Steel)',
                               'slope': -7.919083190470016e-05,
                               'intercept': 0.32257047215968015},
                              {'x': [199.9, 1200],
                               'y': [0.5711094864641113, 0.387494758074869],
                               'name': 'Trend (unk foam)',
                               'slope': -0.0001835963687523671,
                               'intercept': 0.6078104005777095},
                              {'x': [75, 523],
                               'y': [0.8844311876464753, 0.41859883467805437],
                               'name': 'Trend (Abs)',
                               'slope': -0.0010398043593045111,
                               'intercept': 0.9624165145943137},
                              {'x': [75, 2400],
                               'y': [0.6998058252427184, 0.0060679611650483745],
                               'name': 'Trend (Al₂O₃)',
                               'slope': -0.0002983818770226538,
                               'intercept': 0.7221844660194174}],
                   'theory': [],
                   'drInfo': {'dr': 8.14, 'all': [8.14, 6], 'mixed': True}},
       'line': {'traces': [{'name': 'Stainless Steel',
                            'x': [254.99, 600, 1200, 2400, 2400],
                            'y': [0.35, 0.25, 0.18, 0.14, 0.15],
                            'ids': [16, 7, 18, 5, 2],
                            'hover0': 'Stainless Steel | 250s | 01/09/2026 | #16\n'
                                      'Period (s): 254.99\n'
                                      'Raw Phase φ (rad): 0.35'},
                           {'name': 'unk foam',
                            'x': [199.9, 200, 255, 699.9, 1200],
                            'y': [0.55, 0.57, 0.6, 0.45, 0.4],
                            'ids': [14, 13, 15, 4, 8],
                            'hover0': 'unk foam | 200s | 01/09/2026 | #14\n'
                                      'Period (s): 199.9\n'
                                      'Raw Phase φ (rad): 0.55'},
                           {'name': 'Abs',
                            'x': [75, 300, 400, 523],
                            'y': [0.9, 0.7, 0.4, 0.5],
                            'ids': [12, 6, 3, 11],
                            'hover0': 'Abs | 80s | 01/09/2026 | #12\nPeriod (s): 75\nRaw Phase φ (rad): 0.9'},
                           {'name': 'Al₂O₃',
                            'x': [75, 1200, 2400],
                            'y': [0.8, 0.17, 0.1],
                            'ids': [1, 9, 10],
                            'hover0': 'Al₂O₃ | 80s | 10/01/2026 | #1\nPeriod (s): 75\nRaw Phase φ (rad): 0.8'}],
                'trends': [],
                'theory': [],
                'drInfo': {'dr': 8.14, 'all': [8.14, 6], 'mixed': True}},
       'theory': {'traces': [{'name': 'All',
                              'x': [1200,
                                    254.99,
                                    255,
                                    199.9,
                                    200,
                                    75,
                                    523,
                                    2400,
                                    1200,
                                    1200,
                                    600,
                                    300,
                                    2400,
                                    699.9,
                                    400,
                                    2400,
                                    75],
                              'y': [0.18,
                                    0.35,
                                    0.6,
                                    0.55,
                                    0.57,
                                    0.9,
                                    0.5,
                                    0.1,
                                    0.17,
                                    0.4,
                                    0.25,
                                    0.7,
                                    0.14,
                                    0.45,
                                    0.4,
                                    0.15,
                                    0.8],
                              'ids': [18, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1],
                              'hover0': 'Stainless Steel | 1200s | 01/09/2026 | #18\n'
                                        'Period (s): 1200\n'
                                        'Raw Phase φ (rad): 0.18'}],
                  'trends': [{'x': [75, 2400],
                              'y': [0.6041042702923294, 0.0613757643195979],
                              'name': 'Trend (All)',
                              'slope': -0.00023343161547214255,
                              'intercept': 0.6216116414527401}],
                  'theory': [{'name': 'Stainless Steel 25°C (α=4)',
                              'color': '#1abc9c',
                              'n': 160,
                              'x': [75, 2400],
                              'y': [0.8329879402684418, 0.14725285530260748]},
                             {'name': 'Abs 150°C (α=0.08)',
                              'color': '#e67e22',
                              'n': 160,
                              'x': [75, 2400],
                              'y': [5.8901142121043, 1.0412349253355522]}],
                  'drInfo': {'dr': 8.14, 'all': [8.14, 6], 'mixed': True}},
       'theoryDt': {'traces': [{'name': 'All',
                                'x': [0.0004166666666666667,
                                      0.0004166666666666667,
                                      0.0004166666666666667,
                                      0.0008333333333333334,
                                      0.0008333333333333334,
                                      0.0008333333333333334,
                                      0.0014287755393627662,
                                      0.0016666666666666668,
                                      0.0019120458891013384,
                                      0.0025,
                                      0.0033333333333333335,
                                      0.00392156862745098,
                                      0.003921722420487078,
                                      0.005,
                                      0.0050025012506253125,
                                      0.013333333333333334,
                                      0.013333333333333334],
                                'y': [38.197186342054884,
                                      53.476060878876844,
                                      57.29577951308232,
                                      34.3774677078494,
                                      32.467608390746655,
                                      76.39437268410977,
                                      50.1266451015079,
                                      23.873241463784304,
                                      41.619017618530634,
                                      25.464790894703253,
                                      33.42253804929802,
                                      24.350706293059986,
                                      14.204021628650837,
                                      18.143663512476067,
                                      17.498290218238434,
                                      10.742958658702937,
                                      9.549296585513721],
                                'ids': [10, 5, 2, 18, 9, 8, 4, 7, 11, 3, 6, 15, 16, 13, 14, 12, 1],
                                'hover0': 'Al₂O₃ | 2400s | 01/09/2026 | #10\n'
                                          'Frequency (Hz): 0.00041667\n'
                                          'Raw Time Lag Δt (s): 38.197'}],
                    'trends': [],
                    'theory': [{'name': 'Al 25°C (α=64)',
                                'color': '#1abc9c',
                                'n': 160,
                                'x': [0.0004166666666666667, 0.013333333333333334],
                                'y': [14.061611883483357, 2.485765279306106]}],
                    'drInfo': {'dr': 8.14, 'all': [8.14, 6], 'mixed': True}},
       'theoryTemp': {'traces': [{'name': 'All',
                                  'x': [150, 150, 25, 25, 25, 25, 150, 150, 150, 150, 25, 150, 150, 25, 150, 25],
                                  'y': [0.18,
                                        0.35,
                                        0.55,
                                        0.57,
                                        0.9,
                                        0.5,
                                        0.1,
                                        0.17,
                                        0.4,
                                        0.25,
                                        0.7,
                                        0.14,
                                        0.45,
                                        0.4,
                                        0.15,
                                        0.8],
                                  'ids': [18, 16, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1],
                                  'hover0': 'Stainless Steel | 1200s | 01/09/2026 | #18\n'
                                            'Temperature (°C): 150\n'
                                            'Raw Phase φ (rad): 0.18'}],
                      'trends': [{'x': [25, 150],
                                  'y': [0.6314285714285715, 0.2433333333333333],
                                  'name': 'Trend (All)',
                                  'slope': -0.003104761904761905,
                                  'intercept': 0.709047619047619}],
                      'theory': [],
                      'drInfo': {'dr': 8.14, 'all': [8.14, 6], 'mixed': True}},
       'respPeriod': {'traces': [{'name': 'Stainless Steel',
                                  'x': [1212, 257.5399, 257.5399, 2424, 2424],
                                  'y': [1212, 257.5399, 257.5399, 2424, 2424],
                                  'ids': [18, 17, 16, 5, 2],
                                  'hover0': 'Stainless Steel | 1210s | 01/09/2026 | #18\n'
                                            'Period (s): 1212\n'
                                            'Period (s): 1212'},
                                 {'name': 'unk foam',
                                  'x': [257.55, 201.899, 202, 1212, 706.899],
                                  'y': [257.55, 201.899, 202, 1212, 706.899],
                                  'ids': [15, 14, 13, 8, 4],
                                  'hover0': 'unk foam | 260s | 15/08/2026 | #15\n'
                                            'Period (s): 257.55\n'
                                            'Period (s): 257.55'},
                                 {'name': 'Abs',
                                  'x': [75.75, 528.23, 303, 404],
                                  'y': [75.75, 528.23, 303, 404],
                                  'ids': [12, 11, 6, 3],
                                  'hover0': 'Abs | 80s | 01/09/2026 | #12\nPeriod (s): 75.75\nPeriod (s): 75.75'},
                                 {'name': 'Al₂O₃',
                                  'x': [2424, 1212, 75.75],
                                  'y': [2424, 1212, 75.75],
                                  'ids': [10, 9, 1],
                                  'hover0': 'Al₂O₃ | 2420s | 01/09/2026 | #10\nPeriod (s): 2424\nPeriod (s): 2424'}],
                      'trends': [{'x': [257.5399, 2424],
                                  'y': [257.5399, 2424],
                                  'name': 'Trend (Stainless Steel)',
                                  'slope': 1,
                                  'intercept': 0},
                                 {'x': [201.899, 1212],
                                  'y': [201.899, 1212],
                                  'name': 'Trend (unk foam)',
                                  'slope': 1,
                                  'intercept': 0},
                                 {'x': [75.75, 528.23],
                                  'y': [75.75, 528.23],
                                  'name': 'Trend (Abs)',
                                  'slope': 1,
                                  'intercept': 0},
                                 {'x': [75.75, 2424],
                                  'y': [75.75, 2424],
                                  'name': 'Trend (Al₂O₃)',
                                  'slope': 1,
                                  'intercept': 0}],
                      'theory': [],
                      'drInfo': {'dr': 8.14, 'all': [8.14, 6], 'mixed': True}},
       'respExact': {'groups': ['1210 s', '260 s', '200 s', '80 s', '530 s', '2420 s', '300 s', '710 s', '400 s'],
                     'ticktext': ['1210 s<br>n = 3',
                                  '260 s<br>n = 3',
                                  '200 s<br>n = 2',
                                  '80 s<br>n = 2',
                                  '530 s<br>n = 1',
                                  '2420 s<br>n = 3',
                                  '300 s<br>n = 1',
                                  '710 s<br>n = 1',
                                  '400 s<br>n = 1'],
                     'traces': [{'name': '1210 s', 'vals': [0.18, 0.17, 0.4]},
                                {'name': '260 s', 'vals': [0.35, 0.35, 0.6]},
                                {'name': '200 s', 'vals': [0.55, 0.57]},
                                {'name': '80 s', 'vals': [0.9, 0.8]},
                                {'name': '530 s', 'vals': [0.5]},
                                {'name': '2420 s', 'vals': [0.1, 0.14, 0.15]},
                                {'name': '300 s', 'vals': [0.7]},
                                {'name': '710 s', 'vals': [0.45]},
                                {'name': '400 s', 'vals': [0.4]}],
                     'drInfo': {'dr': 8.14, 'all': [8.14, 6], 'mixed': True}},
       'scatter2': {'traces': [{'name': 'Stainless Steel',
                                'x': [1200, 254.99, 600, 2400, 2400],
                                'y': [0.18, 0.35, 0.25, 0.14, 0.15],
                                'ids': [18, 16, 7, 5, 2],
                                'hover0': 'Stainless Steel | 1200s | 01/09/2026 | #18\n'
                                          'Period (s): 1200\n'
                                          'Raw Phase φ (rad): 0.18'},
                               {'name': 'unk foam',
                                'x': [255, 199.9, 200, 1200, 699.9],
                                'y': [0.6, 0.55, 0.57, 0.4, 0.45],
                                'ids': [15, 14, 13, 8, 4],
                                'hover0': 'unk foam | 260s | 15/08/2026 | #15\n'
                                          'Period (s): 255\n'
                                          'Raw Phase φ (rad): 0.6'},
                               {'name': 'Abs',
                                'x': [75, 300],
                                'y': [0.9, 0.7],
                                'ids': [12, 6],
                                'hover0': 'Abs | 80s | 01/09/2026 | #12\nPeriod (s): 75\nRaw Phase φ (rad): 0.9'},
                               {'name': 'Al₂O₃',
                                'x': [2400, 1200, 75],
                                'y': [0.1, 0.17, 0.8],
                                'ids': [10, 9, 1],
                                'hover0': 'Al₂O₃ | 2400s | 01/09/2026 | #10\n'
                                          'Period (s): 2400\n'
                                          'Raw Phase φ (rad): 0.1'}],
                    'trends': [{'x': [254.99, 2400],
                                'y': [0.3023776019323007, 0.13251247558839976],
                                'name': 'Trend (Stainless Steel)',
                                'slope': -7.919083190470016e-05,
                                'intercept': 0.32257047215968015},
                               {'x': [199.9, 1200],
                                'y': [0.5711094864641113, 0.387494758074869],
                                'name': 'Trend (unk foam)',
                                'slope': -0.0001835963687523671,
                                'intercept': 0.6078104005777095},
                               {'x': [75, 2400],
                                'y': [0.6998058252427184, 0.0060679611650483745],
                                'name': 'Trend (Al₂O₃)',
                                'slope': -0.0002983818770226538,
                                'intercept': 0.7221844660194174}],
                    'theory': [],
                    'drInfo': {'dr': 8.14, 'all': [8.14, 6], 'mixed': True}},
       'scatterTemp': {'traces': [{'name': 'Stainless Steel',
                                   'x': [150, 150, 150, 150, 150],
                                   'y': [0.18, 0.35, 0.25, 0.14, 0.15],
                                   'ids': [18, 16, 7, 5, 2],
                                   'hover0': 'Stainless Steel | 1200s | 01/09/2026 | #18\n'
                                             'Temperature (°C): 150\n'
                                             'Raw Phase φ (rad): 0.18'},
                                  {'name': 'unk foam',
                                   'x': [25, 25, 150, 150],
                                   'y': [0.55, 0.57, 0.4, 0.45],
                                   'ids': [14, 13, 8, 4],
                                   'hover0': 'unk foam | 200s | 01/09/2026 | #14\n'
                                             'Temperature (°C): 25\n'
                                             'Raw Phase φ (rad): 0.55'},
                                  {'name': 'Abs',
                                   'x': [25, 25, 25, 25],
                                   'y': [0.9, 0.5, 0.7, 0.4],
                                   'ids': [12, 11, 6, 3],
                                   'hover0': 'Abs | 80s | 01/09/2026 | #12\n'
                                             'Temperature (°C): 25\n'
                                             'Raw Phase φ (rad): 0.9'},
                                  {'name': 'Al₂O₃',
                                   'x': [150, 150, 25],
                                   'y': [0.1, 0.17, 0.8],
                                   'ids': [10, 9, 1],
                                   'hover0': 'Al₂O₃ | 2400s | 01/09/2026 | #10\n'
                                             'Temperature (°C): 150\n'
                                             'Raw Phase φ (rad): 0.1'}],
                       'trends': [{'x': [25, 150],
                                   'y': [0.5599999999999999, 0.42499999999999993],
                                   'name': 'Trend (unk foam)',
                                   'slope': -0.00108,
                                   'intercept': 0.587},
                                  {'x': [25, 150],
                                   'y': [0.8, 0.135],
                                   'name': 'Trend (Al₂O₃)',
                                   'slope': -0.00532,
                                   'intercept': 0.933}],
                       'theory': [],
                       'drInfo': {'dr': 8.14, 'all': [8.14, 6], 'mixed': True}}},
 'dr': {'dr': 8.14, 'all': [8.14, 6], 'mixed': True}}


def V(**kw) -> ViewState:
    return ViewState(**kw)


def _xy(spec, with_trend=False):
    return [s for s in spec.series if with_trend or not s.name.startswith("Trend (")]


def _tick(t):
    return t.replace("<br>", "\n")


# ------------------------------------------------------------------ box / violin / bar

def test_box_defaults_categories_ticks_and_colors():
    spec = S.build_builder_spec(ORIGS, V(), PRESETS)
    pin = PINS["B"]["box"]
    assert spec.kind == "box" and spec.series == []
    assert spec.categories == [(g, _tick(t)) for g, t in zip(pin["groups"], pin["ticktext"])]
    assert [g.name for g in spec.groups] == pin["groups"]
    assert [g.color for g in spec.groups] == [material_color(g) for g in pin["groups"]]
    assert [g.values for g in spec.groups] == [t["vals"] for t in pin["traces"]]
    assert all(len(g.ids) == len(g.values) for g in spec.groups)
    assert spec.title == "α Combined (raw) mm²/s by Model" and spec.xlabel == "Model"
    assert spec.ylabel == "α Combined (raw) mm²/s" and spec.height == 500
    assert spec.ref_lines == []                         # alpha Y but no literature chosen


def test_violin_uses_the_same_groups():
    spec = S.build_builder_spec(ORIGS, V(chart_type="violin"), PRESETS)
    assert spec.kind == "violin" and [g.name for g in spec.groups] == PINS["B"]["box"]["groups"]


def test_group_by_period_band_resp_drops_rows_without_period():
    spec = S.build_builder_spec(ALL, V(group_by="Period (exact)", y_metric="raw_phase_phi", period_source="resp"),
                                PRESETS)
    pin = PINS["B"]["respExact"]
    assert [c[0] for c in spec.categories] == pin["groups"]
    assert [_tick(t) for t in pin["ticktext"]] == [c[1] for c in spec.categories]
    assert [g.values for g in spec.groups] == [t["vals"] for t in pin["traces"]]
    # row 7 has no response period: it is in no group
    assert 7 not in [i for g in spec.groups for i in g.ids]


def test_bar_means_and_population_std():
    spec = S.build_builder_spec(ORIGS, V(chart_type="bar", y_metric="alpha_phase_raw"), PRESETS)
    pin = PINS["B"]["bar"]
    assert spec.kind == "bar"
    assert [s.name for s in spec.series] == [t["name"] for t in pin["traces"]]
    assert [s.y for s in spec.series] == [[t["y"]] for t in pin["traces"]]
    assert [s.yerr for s in spec.series] == [[t["err"]] for t in pin["traces"]]
    assert [s.x for s in spec.series] == [[float(i)] for i in range(len(pin["traces"]))]
    assert spec.categories == [(g, _tick(t)) for g, t in zip(pin["groups"], pin["ticktext"])]


def test_bar_empty_group_is_zero_and_zero():
    spec = S.build_builder_spec(ORIGS, V(chart_type="bar", y_metric="alpha_combined_cal", group_by="Period Band"),
                                PRESETS)
    pin = PINS["B"]["barBand"]
    assert [s.y for s in spec.series] == [[t["y"]] for t in pin["traces"]]
    assert [s.yerr for s in spec.series] == [[t["err"]] for t in pin["traces"]]
    assert [s.y[0] for s in spec.series] == [0.7867672563236497, 0, 0, 0]       # three groups have no values
    assert [c[1].endswith("n = 0") for c in spec.categories] == [False, True, True, True]


def test_bar_single_point_has_no_error_bar():
    one = [r for r in ORIGS if r["id"] == 12]
    spec = S.build_builder_spec(one, V(chart_type="bar", y_metric="alpha_phase_raw"), PRESETS)
    assert spec.series[0].y == [extract_y(one[0], "alpha_phase_raw")] and spec.series[0].yerr == [0]
    assert spec.categories == [("Abs", "Abs\nn = 1")]


# ------------------------------------------------------------------ scatter / line

def _check_points(spec, pin_traces):
    pts = _xy(spec)
    assert [s.name for s in pts] == [t["name"] for t in pin_traces]
    assert [s.x for s in pts] == [t["x"] for t in pin_traces]
    assert [s.y for s in pts] == [t["y"] for t in pin_traces]
    assert [s.ids for s in pts] == [t["ids"] for t in pin_traces]
    assert [s.hover[0] for s in pts] == [t["hover0"] for t in pin_traces]
    assert all(len(s.hover) == len(s.x) == len(s.y) == len(s.ids) for s in pts)


def test_scatter_period_vs_phi_by_model():
    spec = S.build_builder_spec(ORIGS, V(chart_type="scatter", y_metric="raw_phase_phi", color_by="Model"), PRESETS)
    pin = PINS["B"]["scatter"]
    assert spec.kind == "xy" and spec.height == 500
    assert spec.title == "Raw Phase φ (rad) vs Period (s)" and spec.xlabel == "Period (s)"
    _check_points(spec, pin["traces"])
    assert spec.series[0].hover[0] == "Stainless Steel | 1200s | 01/09/2026 | #18\nPeriod (s): 1200\nRaw Phase φ (rad): 0.18"
    pts = _xy(spec)
    assert all(s.mode == "markers" and s.size == 8 and s.color == material_color(s.name) for s in pts)
    trends = [s for s in spec.series if s.name.startswith("Trend (")]
    assert [s.name for s in trends] == [t["name"] for t in pin["trends"]]
    for s, t in zip(trends, pin["trends"]):
        assert s.x == t["x"] and s.y == t["y"]
        assert (s.mode, s.dash, s.width, s.legend) == ("lines", "dot", 1.5, False)
        assert s.color == material_color(s.name[len("Trend ("):-1])
        assert s.y == [t["slope"] * t["x"][0] + t["intercept"], t["slope"] * t["x"][1] + t["intercept"]]


def test_trend_only_for_groups_with_three_points_and_null_x_dropped():
    spec = S.build_builder_spec([r for r in ORIGS if r["id"] not in (11, 3)],
                                V(chart_type="scatter", y_metric="raw_phase_phi", color_by="Model"), PRESETS)
    _check_points(spec, PINS["B"]["scatter2"]["traces"])
    assert [s.name for s in spec.series if s.name.startswith("Trend (")] == [t["name"] for t in PINS["B"]["scatter2"]["trends"]]
    assert "Trend (Abs)" not in [s.name for s in spec.series]                 # two points: no fit
    spec = S.build_builder_spec(ORIGS, V(chart_type="scatter", y_metric="raw_phase_phi", color_by="Model",
                                         x_axis="Temperature (°C)"), PRESETS)
    _check_points(spec, PINS["B"]["scatterTemp"]["traces"])
    assert 15 not in [i for s in _xy(spec) for i in s.ids]                      # row 15 has no temperature


def test_no_color_by_is_one_all_series():
    spec = S.build_builder_spec(ORIGS, V(chart_type="scatter", y_metric="raw_phase_phi"), PRESETS)
    assert [s.name for s in _xy(spec)] == ["All"]


def test_line_sorted_by_x_with_markers():
    spec = S.build_builder_spec(ORIGS, V(chart_type="line", y_metric="raw_phase_phi", color_by="Model"), PRESETS)
    _check_points(spec, PINS["B"]["line"]["traces"])
    for s in spec.series:
        assert s.x == sorted(s.x) and s.mode == "lines+markers" and s.size == 6 and s.width == 2
    assert not any(s.name.startswith("Trend (") for s in spec.series)


# ------------------------------------------------------------------ reference lines

def test_literature_lines_on_alpha_y_only():
    spec = S.build_builder_spec(ORIGS, V(y_metric="alpha_phase_raw", lit_builder=["Al", "Abs"]), PRESETS)
    assert [(r.y, r.label, r.color, r.dash, r.width) for r in spec.ref_lines] == [
        (LITERATURE["Abs"], "Abs", LITERATURE_COLORS["Abs"], "dash", 1.5),
        (LITERATURE["Al"], "Al", LITERATURE_COLORS["Al"], "dash", 1.5)]
    assert S.lit_ref_lines(["Al", "Abs"]) == spec.ref_lines
    spec = S.build_builder_spec(ORIGS, V(y_metric="raw_phase_phi", lit_builder=["Al", "Abs"]), PRESETS)
    assert spec.ref_lines == []


def test_preset_lines_are_dotted_flat_lines_on_alpha_y_with_no_theory_curve():
    spec = S.build_builder_spec(ORIGS, V(chart_type="scatter", y_metric="alpha_combined_raw", theory_ids=[3, 1]),
                                PRESETS)
    assert [(r.y, r.label, r.color, r.dash, r.width) for r in spec.ref_lines] == [
        (4.0, "Stainless Steel 25°C", JS_COLORS[5], "dot", 2), (0.08, "Abs 150°C", JS_COLORS[6], "dot", 2)]
    assert S.preset_ref_lines(PRESETS, [3, 1]) == spec.ref_lines
    assert not [s for s in spec.series if s.dash == "dash"]
    spec = S.build_builder_spec(ORIGS, V(chart_type="scatter", y_metric="amplitude_a1", theory_ids=[3, 1]), PRESETS)
    assert spec.ref_lines == []


# ------------------------------------------------------------------ theory curves

def _theory(spec):
    return [s for s in spec.series if s.dash == "dash"]


def test_theory_phase_vs_period_one_dashed_series_per_selected_preset():
    spec = S.build_builder_spec(ORIGS, V(chart_type="scatter", y_metric="raw_phase_phi", theory_ids=[3, 1]), PRESETS)
    pin = PINS["B"]["theory"]["theory"]
    th = _theory(spec)
    assert [s.name for s in th] == [t["name"] for t in pin] == ["Stainless Steel 25°C (α=4)", "Abs 150°C (α=0.08)"]
    assert [s.color for s in th] == [t["color"] for t in pin] == [JS_COLORS[5], JS_COLORS[6]]
    for s, t in zip(th, pin):
        assert len(s.x) == len(s.y) == t["n"] == 160 and s.mode == "lines" and s.width == 2 and s.legend
        assert [s.x[0], s.x[-1]] == t["x"] and [s.y[0], s.y[-1]] == t["y"]
    dr = PINS["dr"]["dr"]
    assert th[0].y[0] == theoretical_phase(4.0, dr, th[0].x[0]) and th[0].y[-1] == theoretical_phase(4.0, dr, th[0].x[-1])
    assert th[1].y[0] == theoretical_phase(0.08, dr, th[1].x[0])
    assert th[0].x[0] == 75 and math.isclose(th[0].x[-1], 2400)


def test_theory_lag_vs_frequency_and_not_defined_cases():
    spec = S.build_builder_spec(ORIGS, V(chart_type="line", y_metric="raw_lag_dt", x_axis="Frequency (Hz)",
                                         theory_ids=[2]), PRESETS)
    th = _theory(spec)
    pin = PINS["B"]["theoryDt"]["theory"]
    assert len(th) == 1 and th[0].name == pin[0]["name"] and len(th[0].x) == pin[0]["n"]
    assert [th[0].y[0], th[0].y[-1]] == pin[0]["y"] and [th[0].x[0], th[0].x[-1]] == pin[0]["x"]
    assert th[0].y[0] == theoretical_lag_dt(64, PINS["dr"]["dr"], 1 / th[0].x[0])
    # temperature on X: nothing is drawn and the curve is reported undefined
    spec = S.build_builder_spec(ORIGS, V(chart_type="scatter", y_metric="raw_phase_phi", x_axis="Temperature (°C)",
                                         theory_ids=[1]), PRESETS)
    assert PINS["B"]["theoryTemp"]["theory"] == [] and _theory(spec) == []
    info = S.theory_info(ORIGS, V(y_metric="raw_phase_phi", x_axis="Temperature (°C)"))
    assert info.defined is False
    assert S.theory_info(ORIGS, V(y_metric="alpha_phase_raw")).defined is False
    assert S.theory_info(ORIGS, V(y_metric="raw_lag_dt", x_axis="Frequency (Hz)")).defined is True


def test_theory_info_mixed_dr_uses_the_most_common():
    info = S.theory_info(ORIGS, V(y_metric="raw_phase_phi", x_axis="Period (s)"))
    assert info.defined and info.dr == 8.14 == PINS["dr"]["dr"]
    assert info.mixed == [6.0, 8.14] and PINS["dr"]["all"] == [8.14, 6]
    only = [r for r in ORIGS if r["id"] != 9]
    info = S.theory_info(only, V(y_metric="raw_phase_phi"))
    assert info.dr == 8.14 and info.mixed == []
    assert S.theory_info([], V(y_metric="raw_phase_phi")) == S.TheoryInfo(True, None, [])


def test_theory_needs_a_dr_and_a_span():
    no_dr = [dict(r, r1_mm=None) for r in ORIGS]
    spec = S.build_builder_spec(no_dr, V(chart_type="scatter", y_metric="raw_phase_phi", theory_ids=[1]), PRESETS)
    assert _theory(spec) == []
    one_period = [r for r in ORIGS if r["period_t"] == 1200]
    spec = S.build_builder_spec(one_period, V(chart_type="scatter", y_metric="raw_phase_phi", theory_ids=[1]), PRESETS)
    assert _theory(spec) == []


# ------------------------------------------------------------------ flags, empty, period source

def test_log_flags_are_copied_and_empty_rows_give_none():
    spec = S.build_builder_spec(ORIGS, V(log_x=True, log_y=True), PRESETS)
    assert spec.xlog is True and spec.ylog is True
    spec = S.build_builder_spec(ORIGS, V(), PRESETS)
    assert spec.xlog is False and spec.ylog is False
    assert S.build_builder_spec([], V(), PRESETS) is None


def test_period_source_resp_drops_rows_without_response_period():
    spec = S.build_builder_spec(ALL, V(chart_type="scatter", y_metric="period_t", color_by="Model",
                                       period_source="resp"), PRESETS)
    _check_points(spec, PINS["B"]["respPeriod"]["traces"])
    assert 7 not in [i for s in _xy(spec) for i in s.ids]
    spec = S.build_builder_spec(ALL, V(chart_type="scatter", y_metric="period_t", color_by="Period (exact)",
                                       period_source="resp"), PRESETS)
    assert 7 not in [i for s in _xy(spec) for i in s.ids]
    assert all(s.name.endswith(" s") for s in _xy(spec))
