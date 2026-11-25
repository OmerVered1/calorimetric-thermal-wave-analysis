"""Statistics section chart specs (alpha vs period, heat loss, phase, temperature, correlation); expected values
pinned from page.tsx's own code (node, bodies pasted verbatim)."""
from __future__ import annotations

import json
import math
import os

import pytest

from ctwa.analysis.references import LIT_MATERIALS, LITERATURE, LITERATURE_COLORS
from ctwa.results.helpers import material_color
from ctwa.stats import specs as S
from ctwa.stats.aggregate import bin_by_period, pair_segments
from ctwa.stats.filters import FilterState, apply_filters
from ctwa.stats.model import extract_y, get_period, prepare_rows
from ctwa.stats.view_state import ViewState

FIX = os.path.join(os.path.dirname(__file__), "data", "stats_rows.json")
with open(FIX, encoding="utf-8") as _f:
    RAW = json.load(_f)
ALL = prepare_rows(RAW)
ORIGS = apply_filters(ALL, FilterState())

PINS = {'A': {'plain': {'title': 'α Combined (raw) vs Period — by Model',
                 'height': 480,
                 'traces': [{'x': [254.99, 600, 1200, 2400, 2400],
                             'y': [4.489762489605648,
                                   1.4791356434388696,
                                   0.9691418580874664,
                                   0.6569858967997513,
                                   0.6251318614600125],
                             'ids': [16, 7, 18, 5, 2],
                             'text': ['Stainless Steel · 150 °C · 255 s · #16 · 01/09/2026\n'
                                      'T = 255 s\n'
                                      'α Combined (raw) = 4.49 mm²/s',
                                      'Stainless Steel · 150 °C · 600 s · #7 · 01/09/2026\n'
                                      'T = 600 s\n'
                                      'α Combined (raw) = 1.479 mm²/s',
                                      'Stainless Steel · 150 °C · 1200 s · #18 · 01/09/2026\n'
                                      'T = 1200 s\n'
                                      'α Combined (raw) = 0.9691 mm²/s',
                                      'Stainless Steel · 150 °C · 2400 s · #5 · garbage\n'
                                      'T = 2400 s\n'
                                      'α Combined (raw) = 0.657 mm²/s',
                                      'Stainless Steel · 150 °C · 2400 s · #2 · 05/09/2026\n'
                                      'T = 2400 s\n'
                                      'α Combined (raw) = 0.6251 mm²/s'],
                             'name': 'Stainless Steel',
                             'mode': 'lines+markers',
                             'symbol': 0,
                             'opacity': 1,
                             'dash': 'solid',
                             'legendgroup': 'Stainless Steel',
                             'showlegend': True},
                            {'x': [199.9, 200, 255],
                             'y': [1.9291902643256769, 1.7698621584590173, 1.37496173181514],
                             'ids': [14, 13, 15],
                             'text': ['unk foam · 25 °C · 200 s · #14 · 01/09/2026\n'
                                      'T = 200 s\n'
                                      'α Combined (raw) = 1.929 mm²/s',
                                      'unk foam · 25 °C · 200 s · #13 · 05/09/2026\n'
                                      'T = 200 s\n'
                                      'α Combined (raw) = 1.77 mm²/s',
                                      'unk foam · 255 s · #15 · 15/08/2026\n'
                                      'T = 255 s\n'
                                      'α Combined (raw) = 1.375 mm²/s'],
                             'name': 'unk foam',
                             'mode': 'lines+markers',
                             'symbol': 0,
                             'opacity': 1,
                             'dash': 'solid',
                             'legendgroup': 'unk foam',
                             'showlegend': True},
                            {'x': [75, 400, 523],
                             'y': [2.543086081046141, 1.2389023164709594, 0.6882723484653432],
                             'ids': [12, 3, 11],
                             'text': ['Abs · 25 °C · 75 s · #12 · 01/09/2026\n'
                                      'T = 75 s\n'
                                      'α Combined (raw) = 2.543 mm²/s',
                                      'Abs · 25 °C · 400 s · #3 · 01/09/2026\n'
                                      'T = 400 s\n'
                                      'α Combined (raw) = 1.239 mm²/s',
                                      'Abs · 25 °C · 523 s · #11 · 01/09/2026\n'
                                      'T = 523 s\n'
                                      'α Combined (raw) = 0.6883 mm²/s'],
                             'name': 'Abs',
                             'mode': 'lines+markers',
                             'symbol': 0,
                             'opacity': 1,
                             'dash': 'solid',
                             'legendgroup': 'Abs',
                             'showlegend': True},
                            {'x': [75, 1200, 2400],
                             'y': [3.506152416128607, 0.5515971271051913, 0.715242960294227],
                             'ids': [1, 9, 10],
                             'text': ['Al₂O₃ · 25 °C · 75 s · #1 · 10/01/2026\n'
                                      'T = 75 s\n'
                                      'α Combined (raw) = 3.506 mm²/s',
                                      'Al₂O₃ · 150 °C · 1200 s · #9 · 31/12/2025\n'
                                      'T = 1200 s\n'
                                      'α Combined (raw) = 0.5516 mm²/s',
                                      'Al₂O₃ · 150 °C · 2400 s · #10 · 01/09/2026\n'
                                      'T = 2400 s\n'
                                      'α Combined (raw) = 0.7152 mm²/s'],
                             'name': 'Al₂O₃',
                             'mode': 'lines+markers',
                             'symbol': 0,
                             'opacity': 1,
                             'dash': 'solid',
                             'legendgroup': 'Al₂O₃',
                             'showlegend': True}]},
       'two': {'title': 'α Combined (raw), α Phase (raw) vs Period — by Model',
               'height': 520,
               'traces': [{'x': [254.99, 600, 1200, 2400, 2400],
                           'y': [4.489762489605648,
                                 1.4791356434388696,
                                 0.9691418580874664,
                                 0.6569858967997513,
                                 0.6251318614600125],
                           'ids': [16, 7, 18, 5, 2],
                           'text': ['Stainless Steel · 150 °C · 255 s · #16 · 01/09/2026\n'
                                    'T = 255 s\n'
                                    'α Combined (raw) = 4.49 mm²/s',
                                    'Stainless Steel · 150 °C · 600 s · #7 · 01/09/2026\n'
                                    'T = 600 s\n'
                                    'α Combined (raw) = 1.479 mm²/s',
                                    'Stainless Steel · 150 °C · 1200 s · #18 · 01/09/2026\n'
                                    'T = 1200 s\n'
                                    'α Combined (raw) = 0.9691 mm²/s',
                                    'Stainless Steel · 150 °C · 2400 s · #5 · garbage\n'
                                    'T = 2400 s\n'
                                    'α Combined (raw) = 0.657 mm²/s',
                                    'Stainless Steel · 150 °C · 2400 s · #2 · 05/09/2026\n'
                                    'T = 2400 s\n'
                                    'α Combined (raw) = 0.6251 mm²/s'],
                           'name': 'Stainless Steel (α Combined (raw))',
                           'mode': 'lines+markers',
                           'symbol': 0,
                           'opacity': 1,
                           'dash': 'solid',
                           'legendgroup': 'Stainless Steel',
                           'showlegend': True},
                          {'x': [254.99, 600, 1200, 2400, 2400],
                           'y': [6.664068381706792,
                                 5.550951269061288,
                                 5.353926764140904,
                                 4.4251843662797254,
                                 3.8548272701814503],
                           'ids': [16, 7, 18, 5, 2],
                           'text': ['Stainless Steel · 150 °C · 255 s · #16 · 01/09/2026\n'
                                    'T = 255 s\n'
                                    'α Phase (raw) = 6.664 mm²/s',
                                    'Stainless Steel · 150 °C · 600 s · #7 · 01/09/2026\n'
                                    'T = 600 s\n'
                                    'α Phase (raw) = 5.551 mm²/s',
                                    'Stainless Steel · 150 °C · 1200 s · #18 · 01/09/2026\n'
                                    'T = 1200 s\n'
                                    'α Phase (raw) = 5.354 mm²/s',
                                    'Stainless Steel · 150 °C · 2400 s · #5 · garbage\n'
                                    'T = 2400 s\n'
                                    'α Phase (raw) = 4.425 mm²/s',
                                    'Stainless Steel · 150 °C · 2400 s · #2 · 05/09/2026\n'
                                    'T = 2400 s\n'
                                    'α Phase (raw) = 3.855 mm²/s'],
                           'name': 'Stainless Steel (α Phase (raw))',
                           'mode': 'lines+markers',
                           'symbol': 1,
                           'opacity': 1,
                           'dash': 'dash',
                           'legendgroup': 'Stainless Steel',
                           'showlegend': True},
                          {'x': [199.9, 200, 255],
                           'y': [1.9291902643256769, 1.7698621584590173, 1.37496173181514],
                           'ids': [14, 13, 15],
                           'text': ['unk foam · 25 °C · 200 s · #14 · 01/09/2026\n'
                                    'T = 200 s\n'
                                    'α Combined (raw) = 1.929 mm²/s',
                                    'unk foam · 25 °C · 200 s · #13 · 05/09/2026\n'
                                    'T = 200 s\n'
                                    'α Combined (raw) = 1.77 mm²/s',
                                    'unk foam · 255 s · #15 · 15/08/2026\nT = 255 s\nα Combined (raw) = 1.375 mm²/s'],
                           'name': 'unk foam (α Combined (raw))',
                           'mode': 'lines+markers',
                           'symbol': 0,
                           'opacity': 1,
                           'dash': 'solid',
                           'legendgroup': 'unk foam',
                           'showlegend': True},
                          {'x': [199.9, 200, 255, 1200],
                           'y': [3.442393470947015, 3.2034575652477435, 2.267545453047912, 1.0841701697385326],
                           'ids': [14, 13, 15, 8],
                           'text': ['unk foam · 25 °C · 200 s · #14 · 01/09/2026\n'
                                    'T = 200 s\n'
                                    'α Phase (raw) = 3.442 mm²/s',
                                    'unk foam · 25 °C · 200 s · #13 · 05/09/2026\n'
                                    'T = 200 s\n'
                                    'α Phase (raw) = 3.203 mm²/s',
                                    'unk foam · 255 s · #15 · 15/08/2026\nT = 255 s\nα Phase (raw) = 2.268 mm²/s',
                                    'unk foam · 150 °C · 1200 s · #8 · 20/10/2026\n'
                                    'T = 1200 s\n'
                                    'α Phase (raw) = 1.084 mm²/s'],
                           'name': 'unk foam (α Phase (raw))',
                           'mode': 'lines+markers',
                           'symbol': 1,
                           'opacity': 1,
                           'dash': 'dash',
                           'legendgroup': 'unk foam',
                           'showlegend': True},
                          {'x': [75, 400, 523],
                           'y': [2.543086081046141, 1.2389023164709594, 0.6882723484653432],
                           'ids': [12, 3, 11],
                           'text': ['Abs · 25 °C · 75 s · #12 · 01/09/2026\nT = 75 s\nα Combined (raw) = 2.543 mm²/s',
                                    'Abs · 25 °C · 400 s · #3 · 01/09/2026\n'
                                    'T = 400 s\n'
                                    'α Combined (raw) = 1.239 mm²/s',
                                    'Abs · 25 °C · 523 s · #11 · 01/09/2026\n'
                                    'T = 523 s\n'
                                    'α Combined (raw) = 0.6883 mm²/s'],
                           'name': 'Abs (α Combined (raw))',
                           'mode': 'lines+markers',
                           'symbol': 0,
                           'opacity': 1,
                           'dash': 'solid',
                           'legendgroup': 'Abs',
                           'showlegend': True},
                          {'x': [75, 300, 523],
                           'y': [3.4265131290501776, 1.4160589972095123, 1.5920510331915743],
                           'ids': [12, 6, 11],
                           'text': ['Abs · 25 °C · 75 s · #12 · 01/09/2026\nT = 75 s\nα Phase (raw) = 3.427 mm²/s',
                                    'Abs · 25 °C · 300 s · #6 · 01/09/2026\nT = 300 s\nα Phase (raw) = 1.416 mm²/s',
                                    'Abs · 25 °C · 523 s · #11 · 01/09/2026\nT = 523 s\nα Phase (raw) = 1.592 mm²/s'],
                           'name': 'Abs (α Phase (raw))',
                           'mode': 'lines+markers',
                           'symbol': 1,
                           'opacity': 1,
                           'dash': 'dash',
                           'legendgroup': 'Abs',
                           'showlegend': True},
                          {'x': [75, 1200, 2400],
                           'y': [3.506152416128607, 0.5515971271051913, 0.715242960294227],
                           'ids': [1, 9, 10],
                           'text': ['Al₂O₃ · 25 °C · 75 s · #1 · 10/01/2026\n'
                                    'T = 75 s\n'
                                    'α Combined (raw) = 3.506 mm²/s',
                                    'Al₂O₃ · 150 °C · 1200 s · #9 · 31/12/2025\n'
                                    'T = 1200 s\n'
                                    'α Combined (raw) = 0.5516 mm²/s',
                                    'Al₂O₃ · 150 °C · 2400 s · #10 · 01/09/2026\n'
                                    'T = 2400 s\n'
                                    'α Combined (raw) = 0.7152 mm²/s'],
                           'name': 'Al₂O₃ (α Combined (raw))',
                           'mode': 'lines+markers',
                           'symbol': 0,
                           'opacity': 1,
                           'dash': 'solid',
                           'legendgroup': 'Al₂O₃',
                           'showlegend': True},
                          {'x': [75, 1200, 2400],
                           'y': [4.336680678954131, 3.2611688445568783, 8.673361357908261],
                           'ids': [1, 9, 10],
                           'text': ['Al₂O₃ · 25 °C · 75 s · #1 · 10/01/2026\nT = 75 s\nα Phase (raw) = 4.337 mm²/s',
                                    'Al₂O₃ · 150 °C · 1200 s · #9 · 31/12/2025\n'
                                    'T = 1200 s\n'
                                    'α Phase (raw) = 3.261 mm²/s',
                                    'Al₂O₃ · 150 °C · 2400 s · #10 · 01/09/2026\n'
                                    'T = 2400 s\n'
                                    'α Phase (raw) = 8.673 mm²/s'],
                           'name': 'Al₂O₃ (α Phase (raw))',
                           'mode': 'lines+markers',
                           'symbol': 1,
                           'opacity': 1,
                           'dash': 'dash',
                           'legendgroup': 'Al₂O₃',
                           'showlegend': True}]},
       'mean': {'title': 'α Phase (raw) vs Period — by Model',
                'height': 480,
                'traces': [{'x': [254.99, 600, 1200, 2400, 2400],
                            'y': [6.664068381706792,
                                  5.550951269061288,
                                  5.353926764140904,
                                  4.4251843662797254,
                                  3.8548272701814503],
                            'ids': [16, 7, 18, 5, 2],
                            'text': ['Stainless Steel · 150 °C · 255 s · #16 · 01/09/2026\n'
                                     'T = 255 s\n'
                                     'α Phase (raw) = 6.664 mm²/s',
                                     'Stainless Steel · 150 °C · 600 s · #7 · 01/09/2026\n'
                                     'T = 600 s\n'
                                     'α Phase (raw) = 5.551 mm²/s',
                                     'Stainless Steel · 150 °C · 1200 s · #18 · 01/09/2026\n'
                                     'T = 1200 s\n'
                                     'α Phase (raw) = 5.354 mm²/s',
                                     'Stainless Steel · 150 °C · 2400 s · #5 · garbage\n'
                                     'T = 2400 s\n'
                                     'α Phase (raw) = 4.425 mm²/s',
                                     'Stainless Steel · 150 °C · 2400 s · #2 · 05/09/2026\n'
                                     'T = 2400 s\n'
                                     'α Phase (raw) = 3.855 mm²/s'],
                            'name': 'Stainless Steel',
                            'mode': 'markers',
                            'symbol': 0,
                            'opacity': 0.4,
                            'dash': 'solid',
                            'legendgroup': 'Stainless Steel',
                            'showlegend': False},
                           {'x': [254.99, 600, 1200, 2400],
                            'y': [6.664068381706792, 5.550951269061288, 5.353926764140904, 4.140005818230588],
                            'yerr': [0, 0, 0, 0.4033033703489577],
                            'text': ['Stainless Steel\nT ≈ 255 s\nα Phase (raw): mean 6.664 ± 0 mm²/s\nn = 1',
                                     'Stainless Steel\nT ≈ 600 s\nα Phase (raw): mean 5.551 ± 0 mm²/s\nn = 1',
                                     'Stainless Steel\nT ≈ 1200 s\nα Phase (raw): mean 5.354 ± 0 mm²/s\nn = 1',
                                     'Stainless Steel\nT ≈ 2400 s\nα Phase (raw): mean 4.14 ± 0.403 mm²/s\nn = 2'],
                            'name': 'Stainless Steel — mean ± std',
                            'mode': 'lines+markers',
                            'dash': 'solid',
                            'legendgroup': 'Stainless Steel'},
                           {'x': [199.9, 200, 255, 1200],
                            'y': [3.442393470947015, 3.2034575652477435, 2.267545453047912, 1.0841701697385326],
                            'ids': [14, 13, 15, 8],
                            'text': ['unk foam · 25 °C · 200 s · #14 · 01/09/2026\n'
                                     'T = 200 s\n'
                                     'α Phase (raw) = 3.442 mm²/s',
                                     'unk foam · 25 °C · 200 s · #13 · 05/09/2026\n'
                                     'T = 200 s\n'
                                     'α Phase (raw) = 3.203 mm²/s',
                                     'unk foam · 255 s · #15 · 15/08/2026\nT = 255 s\nα Phase (raw) = 2.268 mm²/s',
                                     'unk foam · 150 °C · 1200 s · #8 · 20/10/2026\n'
                                     'T = 1200 s\n'
                                     'α Phase (raw) = 1.084 mm²/s'],
                            'name': 'unk foam',
                            'mode': 'markers',
                            'symbol': 0,
                            'opacity': 0.4,
                            'dash': 'solid',
                            'legendgroup': 'unk foam',
                            'showlegend': False},
                           {'x': [199.95, 255, 1200],
                            'y': [3.3229255180973793, 2.267545453047912, 1.0841701697385326],
                            'yerr': [0.16895319918890447, 0, 0],
                            'text': ['unk foam\nT ≈ 200 s\nα Phase (raw): mean 3.323 ± 0.169 mm²/s\nn = 2',
                                     'unk foam\nT ≈ 255 s\nα Phase (raw): mean 2.268 ± 0 mm²/s\nn = 1',
                                     'unk foam\nT ≈ 1200 s\nα Phase (raw): mean 1.084 ± 0 mm²/s\nn = 1'],
                            'name': 'unk foam — mean ± std',
                            'mode': 'lines+markers',
                            'dash': 'solid',
                            'legendgroup': 'unk foam'},
                           {'x': [75, 300, 523],
                            'y': [3.4265131290501776, 1.4160589972095123, 1.5920510331915743],
                            'ids': [12, 6, 11],
                            'text': ['Abs · 25 °C · 75 s · #12 · 01/09/2026\nT = 75 s\nα Phase (raw) = 3.427 mm²/s',
                                     'Abs · 25 °C · 300 s · #6 · 01/09/2026\nT = 300 s\nα Phase (raw) = 1.416 mm²/s',
                                     'Abs · 25 °C · 523 s · #11 · 01/09/2026\n'
                                     'T = 523 s\n'
                                     'α Phase (raw) = 1.592 mm²/s'],
                            'name': 'Abs',
                            'mode': 'markers',
                            'symbol': 0,
                            'opacity': 0.4,
                            'dash': 'solid',
                            'legendgroup': 'Abs',
                            'showlegend': False},
                           {'x': [75, 300, 523],
                            'y': [3.4265131290501776, 1.4160589972095123, 1.5920510331915743],
                            'yerr': [0, 0, 0],
                            'text': ['Abs\nT ≈ 75 s\nα Phase (raw): mean 3.427 ± 0 mm²/s\nn = 1',
                                     'Abs\nT ≈ 300 s\nα Phase (raw): mean 1.416 ± 0 mm²/s\nn = 1',
                                     'Abs\nT ≈ 523 s\nα Phase (raw): mean 1.592 ± 0 mm²/s\nn = 1'],
                            'name': 'Abs — mean ± std',
                            'mode': 'lines+markers',
                            'dash': 'solid',
                            'legendgroup': 'Abs'},
                           {'x': [75, 1200, 2400],
                            'y': [4.336680678954131, 3.2611688445568783, 8.673361357908261],
                            'ids': [1, 9, 10],
                            'text': ['Al₂O₃ · 25 °C · 75 s · #1 · 10/01/2026\nT = 75 s\nα Phase (raw) = 4.337 mm²/s',
                                     'Al₂O₃ · 150 °C · 1200 s · #9 · 31/12/2025\n'
                                     'T = 1200 s\n'
                                     'α Phase (raw) = 3.261 mm²/s',
                                     'Al₂O₃ · 150 °C · 2400 s · #10 · 01/09/2026\n'
                                     'T = 2400 s\n'
                                     'α Phase (raw) = 8.673 mm²/s'],
                            'name': 'Al₂O₃',
                            'mode': 'markers',
                            'symbol': 0,
                            'opacity': 0.4,
                            'dash': 'solid',
                            'legendgroup': 'Al₂O₃',
                            'showlegend': False},
                           {'x': [75, 1200, 2400],
                            'y': [4.336680678954131, 3.2611688445568783, 8.673361357908261],
                            'yerr': [0, 0, 0],
                            'text': ['Al₂O₃\nT ≈ 75 s\nα Phase (raw): mean 4.337 ± 0 mm²/s\nn = 1',
                                     'Al₂O₃\nT ≈ 1200 s\nα Phase (raw): mean 3.261 ± 0 mm²/s\nn = 1',
                                     'Al₂O₃\nT ≈ 2400 s\nα Phase (raw): mean 8.673 ± 0 mm²/s\nn = 1'],
                            'name': 'Al₂O₃ — mean ± std',
                            'mode': 'lines+markers',
                            'dash': 'solid',
                            'legendgroup': 'Al₂O₃'}]},
       'meanResp': {'title': 'α Combined (raw), α Phase (raw) vs Period — by Model',
                    'height': 520,
                    'traces': [{'x': [257.5399, 1212, 2424, 2424],
                                'y': [4.489762489605648, 0.9691418580874664, 0.6569858967997513, 0.6251318614600125],
                                'ids': [16, 18, 5, 2],
                                'text': ['Stainless Steel · 150 °C · 255 s · #16 · 01/09/2026\n'
                                         'T = 258 s\n'
                                         'α Combined (raw) = 4.49 mm²/s',
                                         'Stainless Steel · 150 °C · 1200 s · #18 · 01/09/2026\n'
                                         'T = 1212 s\n'
                                         'α Combined (raw) = 0.9691 mm²/s',
                                         'Stainless Steel · 150 °C · 2400 s · #5 · garbage\n'
                                         'T = 2424 s\n'
                                         'α Combined (raw) = 0.657 mm²/s',
                                         'Stainless Steel · 150 °C · 2400 s · #2 · 05/09/2026\n'
                                         'T = 2424 s\n'
                                         'α Combined (raw) = 0.6251 mm²/s'],
                                'name': 'Stainless Steel (α Combined (raw))',
                                'mode': 'markers',
                                'symbol': 0,
                                'opacity': 0.4,
                                'dash': 'solid',
                                'legendgroup': 'Stainless Steel',
                                'showlegend': False},
                               {'x': [257.5399, 1212, 2424],
                                'y': [4.489762489605648, 0.9691418580874664, 0.6410588791298819],
                                'yerr': [0, 0, 0.022524204396885194],
                                'text': ['Stainless Steel\nT ≈ 258 s\nα Combined (raw): mean 4.49 ± 0 mm²/s\nn = 1',
                                         'Stainless Steel\n'
                                         'T ≈ 1212 s\n'
                                         'α Combined (raw): mean 0.9691 ± 0 mm²/s\n'
                                         'n = 1',
                                         'Stainless Steel\n'
                                         'T ≈ 2424 s\n'
                                         'α Combined (raw): mean 0.6411 ± 0.0225 mm²/s\n'
                                         'n = 2'],
                                'name': 'Stainless Steel (α Combined (raw)) — mean ± std',
                                'mode': 'lines+markers',
                                'dash': 'solid',
                                'legendgroup': 'Stainless Steel'},
                               {'x': [257.5399, 1212, 2424, 2424],
                                'y': [6.664068381706792, 5.353926764140904, 4.4251843662797254, 3.8548272701814503],
                                'ids': [16, 18, 5, 2],
                                'text': ['Stainless Steel · 150 °C · 255 s · #16 · 01/09/2026\n'
                                         'T = 258 s\n'
                                         'α Phase (raw) = 6.664 mm²/s',
                                         'Stainless Steel · 150 °C · 1200 s · #18 · 01/09/2026\n'
                                         'T = 1212 s\n'
                                         'α Phase (raw) = 5.354 mm²/s',
                                         'Stainless Steel · 150 °C · 2400 s · #5 · garbage\n'
                                         'T = 2424 s\n'
                                         'α Phase (raw) = 4.425 mm²/s',
                                         'Stainless Steel · 150 °C · 2400 s · #2 · 05/09/2026\n'
                                         'T = 2424 s\n'
                                         'α Phase (raw) = 3.855 mm²/s'],
                                'name': 'Stainless Steel (α Phase (raw))',
                                'mode': 'markers',
                                'symbol': 1,
                                'opacity': 0.4,
                                'dash': 'dash',
                                'legendgroup': 'Stainless Steel',
                                'showlegend': False},
                               {'x': [257.5399, 1212, 2424],
                                'y': [6.664068381706792, 5.353926764140904, 4.140005818230588],
                                'yerr': [0, 0, 0.4033033703489577],
                                'text': ['Stainless Steel\nT ≈ 258 s\nα Phase (raw): mean 6.664 ± 0 mm²/s\nn = 1',
                                         'Stainless Steel\nT ≈ 1212 s\nα Phase (raw): mean 5.354 ± 0 mm²/s\nn = 1',
                                         'Stainless Steel\n'
                                         'T ≈ 2424 s\n'
                                         'α Phase (raw): mean 4.14 ± 0.403 mm²/s\n'
                                         'n = 2'],
                                'name': 'Stainless Steel (α Phase (raw)) — mean ± std',
                                'mode': 'lines+markers',
                                'dash': 'dash',
                                'legendgroup': 'Stainless Steel'},
                               {'x': [201.899, 202, 257.55],
                                'y': [1.9291902643256769, 1.7698621584590173, 1.37496173181514],
                                'ids': [14, 13, 15],
                                'text': ['unk foam · 25 °C · 200 s · #14 · 01/09/2026\n'
                                         'T = 202 s\n'
                                         'α Combined (raw) = 1.929 mm²/s',
                                         'unk foam · 25 °C · 200 s · #13 · 05/09/2026\n'
                                         'T = 202 s\n'
                                         'α Combined (raw) = 1.77 mm²/s',
                                         'unk foam · 255 s · #15 · 15/08/2026\n'
                                         'T = 258 s\n'
                                         'α Combined (raw) = 1.375 mm²/s'],
                                'name': 'unk foam (α Combined (raw))',
                                'mode': 'markers',
                                'symbol': 0,
                                'opacity': 0.4,
                                'dash': 'solid',
                                'legendgroup': 'unk foam',
                                'showlegend': False},
                               {'x': [201.9495, 257.55],
                                'y': [1.8495262113923472, 1.37496173181514],
                                'yerr': [0.11266198409192313, 0],
                                'text': ['unk foam\nT ≈ 202 s\nα Combined (raw): mean 1.85 ± 0.113 mm²/s\nn = 2',
                                         'unk foam\nT ≈ 258 s\nα Combined (raw): mean 1.375 ± 0 mm²/s\nn = 1'],
                                'name': 'unk foam (α Combined (raw)) — mean ± std',
                                'mode': 'lines+markers',
                                'dash': 'solid',
                                'legendgroup': 'unk foam'},
                               {'x': [201.899, 202, 257.55, 1212],
                                'y': [3.442393470947015, 3.2034575652477435, 2.267545453047912, 1.0841701697385326],
                                'ids': [14, 13, 15, 8],
                                'text': ['unk foam · 25 °C · 200 s · #14 · 01/09/2026\n'
                                         'T = 202 s\n'
                                         'α Phase (raw) = 3.442 mm²/s',
                                         'unk foam · 25 °C · 200 s · #13 · 05/09/2026\n'
                                         'T = 202 s\n'
                                         'α Phase (raw) = 3.203 mm²/s',
                                         'unk foam · 255 s · #15 · 15/08/2026\n'
                                         'T = 258 s\n'
                                         'α Phase (raw) = 2.268 mm²/s',
                                         'unk foam · 150 °C · 1200 s · #8 · 20/10/2026\n'
                                         'T = 1212 s\n'
                                         'α Phase (raw) = 1.084 mm²/s'],
                                'name': 'unk foam (α Phase (raw))',
                                'mode': 'markers',
                                'symbol': 1,
                                'opacity': 0.4,
                                'dash': 'dash',
                                'legendgroup': 'unk foam',
                                'showlegend': False},
                               {'x': [201.9495, 257.55, 1212],
                                'y': [3.3229255180973793, 2.267545453047912, 1.0841701697385326],
                                'yerr': [0.16895319918890447, 0, 0],
                                'text': ['unk foam\nT ≈ 202 s\nα Phase (raw): mean 3.323 ± 0.169 mm²/s\nn = 2',
                                         'unk foam\nT ≈ 258 s\nα Phase (raw): mean 2.268 ± 0 mm²/s\nn = 1',
                                         'unk foam\nT ≈ 1212 s\nα Phase (raw): mean 1.084 ± 0 mm²/s\nn = 1'],
                                'name': 'unk foam (α Phase (raw)) — mean ± std',
                                'mode': 'lines+markers',
                                'dash': 'dash',
                                'legendgroup': 'unk foam'},
                               {'x': [75.75, 404, 528.23],
                                'y': [2.543086081046141, 1.2389023164709594, 0.6882723484653432],
                                'ids': [12, 3, 11],
                                'text': ['Abs · 25 °C · 75 s · #12 · 01/09/2026\n'
                                         'T = 76 s\n'
                                         'α Combined (raw) = 2.543 mm²/s',
                                         'Abs · 25 °C · 400 s · #3 · 01/09/2026\n'
                                         'T = 404 s\n'
                                         'α Combined (raw) = 1.239 mm²/s',
                                         'Abs · 25 °C · 523 s · #11 · 01/09/2026\n'
                                         'T = 528 s\n'
                                         'α Combined (raw) = 0.6883 mm²/s'],
                                'name': 'Abs (α Combined (raw))',
                                'mode': 'markers',
                                'symbol': 0,
                                'opacity': 0.4,
                                'dash': 'solid',
                                'legendgroup': 'Abs',
                                'showlegend': False},
                               {'x': [75.75, 404, 528.23],
                                'y': [2.543086081046141, 1.2389023164709594, 0.6882723484653432],
                                'yerr': [0, 0, 0],
                                'text': ['Abs\nT ≈ 76 s\nα Combined (raw): mean 2.543 ± 0 mm²/s\nn = 1',
                                         'Abs\nT ≈ 404 s\nα Combined (raw): mean 1.239 ± 0 mm²/s\nn = 1',
                                         'Abs\nT ≈ 528 s\nα Combined (raw): mean 0.6883 ± 0 mm²/s\nn = 1'],
                                'name': 'Abs (α Combined (raw)) — mean ± std',
                                'mode': 'lines+markers',
                                'dash': 'solid',
                                'legendgroup': 'Abs'},
                               {'x': [75.75, 303, 528.23],
                                'y': [3.4265131290501776, 1.4160589972095123, 1.5920510331915743],
                                'ids': [12, 6, 11],
                                'text': ['Abs · 25 °C · 75 s · #12 · 01/09/2026\n'
                                         'T = 76 s\n'
                                         'α Phase (raw) = 3.427 mm²/s',
                                         'Abs · 25 °C · 300 s · #6 · 01/09/2026\n'
                                         'T = 303 s\n'
                                         'α Phase (raw) = 1.416 mm²/s',
                                         'Abs · 25 °C · 523 s · #11 · 01/09/2026\n'
                                         'T = 528 s\n'
                                         'α Phase (raw) = 1.592 mm²/s'],
                                'name': 'Abs (α Phase (raw))',
                                'mode': 'markers',
                                'symbol': 1,
                                'opacity': 0.4,
                                'dash': 'dash',
                                'legendgroup': 'Abs',
                                'showlegend': False},
                               {'x': [75.75, 303, 528.23],
                                'y': [3.4265131290501776, 1.4160589972095123, 1.5920510331915743],
                                'yerr': [0, 0, 0],
                                'text': ['Abs\nT ≈ 76 s\nα Phase (raw): mean 3.427 ± 0 mm²/s\nn = 1',
                                         'Abs\nT ≈ 303 s\nα Phase (raw): mean 1.416 ± 0 mm²/s\nn = 1',
                                         'Abs\nT ≈ 528 s\nα Phase (raw): mean 1.592 ± 0 mm²/s\nn = 1'],
                                'name': 'Abs (α Phase (raw)) — mean ± std',
                                'mode': 'lines+markers',
                                'dash': 'dash',
                                'legendgroup': 'Abs'},
                               {'x': [75.75, 1212, 2424],
                                'y': [3.506152416128607, 0.5515971271051913, 0.715242960294227],
                                'ids': [1, 9, 10],
                                'text': ['Al₂O₃ · 25 °C · 75 s · #1 · 10/01/2026\n'
                                         'T = 76 s\n'
                                         'α Combined (raw) = 3.506 mm²/s',
                                         'Al₂O₃ · 150 °C · 1200 s · #9 · 31/12/2025\n'
                                         'T = 1212 s\n'
                                         'α Combined (raw) = 0.5516 mm²/s',
                                         'Al₂O₃ · 150 °C · 2400 s · #10 · 01/09/2026\n'
                                         'T = 2424 s\n'
                                         'α Combined (raw) = 0.7152 mm²/s'],
                                'name': 'Al₂O₃ (α Combined (raw))',
                                'mode': 'markers',
                                'symbol': 0,
                                'opacity': 0.4,
                                'dash': 'solid',
                                'legendgroup': 'Al₂O₃',
                                'showlegend': False},
                               {'x': [75.75, 1212, 2424],
                                'y': [3.506152416128607, 0.5515971271051913, 0.715242960294227],
                                'yerr': [0, 0, 0],
                                'text': ['Al₂O₃\nT ≈ 76 s\nα Combined (raw): mean 3.506 ± 0 mm²/s\nn = 1',
                                         'Al₂O₃\nT ≈ 1212 s\nα Combined (raw): mean 0.5516 ± 0 mm²/s\nn = 1',
                                         'Al₂O₃\nT ≈ 2424 s\nα Combined (raw): mean 0.7152 ± 0 mm²/s\nn = 1'],
                                'name': 'Al₂O₃ (α Combined (raw)) — mean ± std',
                                'mode': 'lines+markers',
                                'dash': 'solid',
                                'legendgroup': 'Al₂O₃'},
                               {'x': [75.75, 1212, 2424],
                                'y': [4.336680678954131, 3.2611688445568783, 8.673361357908261],
                                'ids': [1, 9, 10],
                                'text': ['Al₂O₃ · 25 °C · 75 s · #1 · 10/01/2026\n'
                                         'T = 76 s\n'
                                         'α Phase (raw) = 4.337 mm²/s',
                                         'Al₂O₃ · 150 °C · 1200 s · #9 · 31/12/2025\n'
                                         'T = 1212 s\n'
                                         'α Phase (raw) = 3.261 mm²/s',
                                         'Al₂O₃ · 150 °C · 2400 s · #10 · 01/09/2026\n'
                                         'T = 2424 s\n'
                                         'α Phase (raw) = 8.673 mm²/s'],
                                'name': 'Al₂O₃ (α Phase (raw))',
                                'mode': 'markers',
                                'symbol': 1,
                                'opacity': 0.4,
                                'dash': 'dash',
                                'legendgroup': 'Al₂O₃',
                                'showlegend': False},
                               {'x': [75.75, 1212, 2424],
                                'y': [4.336680678954131, 3.2611688445568783, 8.673361357908261],
                                'yerr': [0, 0, 0],
                                'text': ['Al₂O₃\nT ≈ 76 s\nα Phase (raw): mean 4.337 ± 0 mm²/s\nn = 1',
                                         'Al₂O₃\nT ≈ 1212 s\nα Phase (raw): mean 3.261 ± 0 mm²/s\nn = 1',
                                         'Al₂O₃\nT ≈ 2424 s\nα Phase (raw): mean 8.673 ± 0 mm²/s\nn = 1'],
                                'name': 'Al₂O₃ (α Phase (raw)) — mean ± std',
                                'mode': 'lines+markers',
                                'dash': 'dash',
                                'legendgroup': 'Al₂O₃'}]},
       'pairs': {'title': 'α Combined (raw), α Phase (raw), α Combined (cal), α Phase (cal) vs Period — by Model',
                 'height': 600,
                 'traces': [{'x': [254.99, 254.99, 600, 1200, 2400, 2400],
                             'y': [4.489762489605648,
                                   4.489762489605648,
                                   1.4791356434388696,
                                   0.9691418580874664,
                                   0.6569858967997513,
                                   0.6251318614600125],
                             'ids': [17, 16, 7, 18, 5, 2],
                             'text': ['Stainless Steel · 150 °C · 255 s · #17 · 01/09/2026\n'
                                      'T = 255 s\n'
                                      'α Combined (raw) = 4.49 mm²/s',
                                      'Stainless Steel · 150 °C · 255 s · #16 · 01/09/2026\n'
                                      'T = 255 s\n'
                                      'α Combined (raw) = 4.49 mm²/s',
                                      'Stainless Steel · 150 °C · 600 s · #7 · 01/09/2026\n'
                                      'T = 600 s\n'
                                      'α Combined (raw) = 1.479 mm²/s',
                                      'Stainless Steel · 150 °C · 1200 s · #18 · 01/09/2026\n'
                                      'T = 1200 s\n'
                                      'α Combined (raw) = 0.9691 mm²/s',
                                      'Stainless Steel · 150 °C · 2400 s · #5 · garbage\n'
                                      'T = 2400 s\n'
                                      'α Combined (raw) = 0.657 mm²/s',
                                      'Stainless Steel · 150 °C · 2400 s · #2 · 05/09/2026\n'
                                      'T = 2400 s\n'
                                      'α Combined (raw) = 0.6251 mm²/s'],
                             'name': 'Stainless Steel (α Combined (raw))',
                             'mode': 'markers',
                             'symbol': 'diamond-open',
                             'opacity': 1,
                             'dash': 'solid',
                             'legendgroup': 'Stainless Steel',
                             'showlegend': True},
                            {'x': [254.99, 254.99, 600, 1200, 2400, 2400],
                             'y': [6.664068381706792,
                                   6.664068381706792,
                                   5.550951269061288,
                                   5.353926764140904,
                                   4.4251843662797254,
                                   3.8548272701814503],
                             'ids': [17, 16, 7, 18, 5, 2],
                             'text': ['Stainless Steel · 150 °C · 255 s · #17 · 01/09/2026\n'
                                      'T = 255 s\n'
                                      'α Phase (raw) = 6.664 mm²/s',
                                      'Stainless Steel · 150 °C · 255 s · #16 · 01/09/2026\n'
                                      'T = 255 s\n'
                                      'α Phase (raw) = 6.664 mm²/s',
                                      'Stainless Steel · 150 °C · 600 s · #7 · 01/09/2026\n'
                                      'T = 600 s\n'
                                      'α Phase (raw) = 5.551 mm²/s',
                                      'Stainless Steel · 150 °C · 1200 s · #18 · 01/09/2026\n'
                                      'T = 1200 s\n'
                                      'α Phase (raw) = 5.354 mm²/s',
                                      'Stainless Steel · 150 °C · 2400 s · #5 · garbage\n'
                                      'T = 2400 s\n'
                                      'α Phase (raw) = 4.425 mm²/s',
                                      'Stainless Steel · 150 °C · 2400 s · #2 · 05/09/2026\n'
                                      'T = 2400 s\n'
                                      'α Phase (raw) = 3.855 mm²/s'],
                             'name': 'Stainless Steel (α Phase (raw))',
                             'mode': 'markers',
                             'symbol': 'circle-open',
                             'opacity': 1,
                             'dash': 'dash',
                             'legendgroup': 'Stainless Steel',
                             'showlegend': True},
                            {'x': [254.99],
                             'y': [4.938738738566214],
                             'ids': [17],
                             'text': ['Stainless Steel · 150 °C · 255 s · #17 · 01/09/2026\n'
                                      'T = 255 s\n'
                                      'α Combined (cal) = 4.939 mm²/s'],
                             'name': 'Stainless Steel (α Combined (cal))',
                             'mode': 'markers',
                             'symbol': 'diamond',
                             'opacity': 1,
                             'dash': 'dot',
                             'legendgroup': 'Stainless Steel',
                             'showlegend': True},
                            {'x': [254.99],
                             'y': [7.9968820580481506],
                             'ids': [17],
                             'text': ['Stainless Steel · 150 °C · 255 s · #17 · 01/09/2026\n'
                                      'T = 255 s\n'
                                      'α Phase (cal) = 7.997 mm²/s'],
                             'name': 'Stainless Steel (α Phase (cal))',
                             'mode': 'markers',
                             'symbol': 'circle',
                             'opacity': 1,
                             'dash': 'dashdot',
                             'legendgroup': 'Stainless Steel',
                             'showlegend': True},
                            {'x': [254.99, 254.99, None, 254.99, 254.99, None],
                             'y': [6.664068381706792,
                                   7.9968820580481506,
                                   None,
                                   4.489762489605648,
                                   4.938738738566214,
                                   None],
                             'name': 'Stainless Steel',
                             'mode': 'lines',
                             'seg': True,
                             'legendgroup': 'Stainless Steel'},
                            {'x': [199.9, 200, 255],
                             'y': [1.9291902643256769, 1.7698621584590173, 1.37496173181514],
                             'ids': [14, 13, 15],
                             'text': ['unk foam · 25 °C · 200 s · #14 · 01/09/2026\n'
                                      'T = 200 s\n'
                                      'α Combined (raw) = 1.929 mm²/s',
                                      'unk foam · 25 °C · 200 s · #13 · 05/09/2026\n'
                                      'T = 200 s\n'
                                      'α Combined (raw) = 1.77 mm²/s',
                                      'unk foam · 255 s · #15 · 15/08/2026\n'
                                      'T = 255 s\n'
                                      'α Combined (raw) = 1.375 mm²/s'],
                             'name': 'unk foam (α Combined (raw))',
                             'mode': 'markers',
                             'symbol': 'diamond-open',
                             'opacity': 1,
                             'dash': 'solid',
                             'legendgroup': 'unk foam',
                             'showlegend': True},
                            {'x': [199.9, 200, 255, 1200],
                             'y': [3.442393470947015, 3.2034575652477435, 2.267545453047912, 1.0841701697385326],
                             'ids': [14, 13, 15, 8],
                             'text': ['unk foam · 25 °C · 200 s · #14 · 01/09/2026\n'
                                      'T = 200 s\n'
                                      'α Phase (raw) = 3.442 mm²/s',
                                      'unk foam · 25 °C · 200 s · #13 · 05/09/2026\n'
                                      'T = 200 s\n'
                                      'α Phase (raw) = 3.203 mm²/s',
                                      'unk foam · 255 s · #15 · 15/08/2026\nT = 255 s\nα Phase (raw) = 2.268 mm²/s',
                                      'unk foam · 150 °C · 1200 s · #8 · 20/10/2026\n'
                                      'T = 1200 s\n'
                                      'α Phase (raw) = 1.084 mm²/s'],
                             'name': 'unk foam (α Phase (raw))',
                             'mode': 'markers',
                             'symbol': 'circle-open',
                             'opacity': 1,
                             'dash': 'dash',
                             'legendgroup': 'unk foam',
                             'showlegend': True},
                            {'x': [75, 400, 523],
                             'y': [2.543086081046141, 1.2389023164709594, 0.6882723484653432],
                             'ids': [12, 3, 11],
                             'text': ['Abs · 25 °C · 75 s · #12 · 01/09/2026\n'
                                      'T = 75 s\n'
                                      'α Combined (raw) = 2.543 mm²/s',
                                      'Abs · 25 °C · 400 s · #3 · 01/09/2026\n'
                                      'T = 400 s\n'
                                      'α Combined (raw) = 1.239 mm²/s',
                                      'Abs · 25 °C · 523 s · #11 · 01/09/2026\n'
                                      'T = 523 s\n'
                                      'α Combined (raw) = 0.6883 mm²/s'],
                             'name': 'Abs (α Combined (raw))',
                             'mode': 'markers',
                             'symbol': 'diamond-open',
                             'opacity': 1,
                             'dash': 'solid',
                             'legendgroup': 'Abs',
                             'showlegend': True},
                            {'x': [75, 300, 523],
                             'y': [3.4265131290501776, 1.4160589972095123, 1.5920510331915743],
                             'ids': [12, 6, 11],
                             'text': ['Abs · 25 °C · 75 s · #12 · 01/09/2026\nT = 75 s\nα Phase (raw) = 3.427 mm²/s',
                                      'Abs · 25 °C · 300 s · #6 · 01/09/2026\nT = 300 s\nα Phase (raw) = 1.416 mm²/s',
                                      'Abs · 25 °C · 523 s · #11 · 01/09/2026\n'
                                      'T = 523 s\n'
                                      'α Phase (raw) = 1.592 mm²/s'],
                             'name': 'Abs (α Phase (raw))',
                             'mode': 'markers',
                             'symbol': 'circle-open',
                             'opacity': 1,
                             'dash': 'dash',
                             'legendgroup': 'Abs',
                             'showlegend': True},
                            {'x': [75, 1200, 2400],
                             'y': [3.506152416128607, 0.5515971271051913, 0.715242960294227],
                             'ids': [1, 9, 10],
                             'text': ['Al₂O₃ · 25 °C · 75 s · #1 · 10/01/2026\n'
                                      'T = 75 s\n'
                                      'α Combined (raw) = 3.506 mm²/s',
                                      'Al₂O₃ · 150 °C · 1200 s · #9 · 31/12/2025\n'
                                      'T = 1200 s\n'
                                      'α Combined (raw) = 0.5516 mm²/s',
                                      'Al₂O₃ · 150 °C · 2400 s · #10 · 01/09/2026\n'
                                      'T = 2400 s\n'
                                      'α Combined (raw) = 0.7152 mm²/s'],
                             'name': 'Al₂O₃ (α Combined (raw))',
                             'mode': 'markers',
                             'symbol': 'diamond-open',
                             'opacity': 1,
                             'dash': 'solid',
                             'legendgroup': 'Al₂O₃',
                             'showlegend': True},
                            {'x': [75, 1200, 2400],
                             'y': [4.336680678954131, 3.2611688445568783, 8.673361357908261],
                             'ids': [1, 9, 10],
                             'text': ['Al₂O₃ · 25 °C · 75 s · #1 · 10/01/2026\nT = 75 s\nα Phase (raw) = 4.337 mm²/s',
                                      'Al₂O₃ · 150 °C · 1200 s · #9 · 31/12/2025\n'
                                      'T = 1200 s\n'
                                      'α Phase (raw) = 3.261 mm²/s',
                                      'Al₂O₃ · 150 °C · 2400 s · #10 · 01/09/2026\n'
                                      'T = 2400 s\n'
                                      'α Phase (raw) = 8.673 mm²/s'],
                             'name': 'Al₂O₃ (α Phase (raw))',
                             'mode': 'markers',
                             'symbol': 'circle-open',
                             'opacity': 1,
                             'dash': 'dash',
                             'legendgroup': 'Al₂O₃',
                             'showlegend': True},
                            {'x': [2400],
                             'y': [0.7867672563236497],
                             'ids': [10],
                             'text': ['Al₂O₃ · 150 °C · 2400 s · #10 · 01/09/2026\n'
                                      'T = 2400 s\n'
                                      'α Combined (cal) = 0.7868 mm²/s'],
                             'name': 'Al₂O₃ (α Combined (cal))',
                             'mode': 'markers',
                             'symbol': 'diamond',
                             'opacity': 1,
                             'dash': 'dot',
                             'legendgroup': 'Al₂O₃',
                             'showlegend': True},
                            {'x': [2400],
                             'y': [10.408033629489914],
                             'ids': [10],
                             'text': ['Al₂O₃ · 150 °C · 2400 s · #10 · 01/09/2026\n'
                                      'T = 2400 s\n'
                                      'α Phase (cal) = 10.41 mm²/s'],
                             'name': 'Al₂O₃ (α Phase (cal))',
                             'mode': 'markers',
                             'symbol': 'circle',
                             'opacity': 1,
                             'dash': 'dashdot',
                             'legendgroup': 'Al₂O₃',
                             'showlegend': True},
                            {'x': [2400, 2400, None, 2400, 2400, None],
                             'y': [8.673361357908261,
                                   10.408033629489914,
                                   None,
                                   0.715242960294227,
                                   0.7867672563236497,
                                   None],
                             'name': 'Al₂O₃',
                             'mode': 'lines',
                             'seg': True,
                             'legendgroup': 'Al₂O₃'}]},
       'pairsMean': {'title': 'α Phase (raw), α Phase (cal) vs Period — by Model',
                     'height': 520,
                     'traces': [{'x': [254.99, 254.99, 600, 1200, 2400, 2400],
                                 'y': [6.664068381706792,
                                       6.664068381706792,
                                       5.550951269061288,
                                       5.353926764140904,
                                       4.4251843662797254,
                                       3.8548272701814503],
                                 'ids': [17, 16, 7, 18, 5, 2],
                                 'text': ['Stainless Steel · 150 °C · 255 s · #17 · 01/09/2026\n'
                                          'T = 255 s\n'
                                          'α Phase (raw) = 6.664 mm²/s',
                                          'Stainless Steel · 150 °C · 255 s · #16 · 01/09/2026\n'
                                          'T = 255 s\n'
                                          'α Phase (raw) = 6.664 mm²/s',
                                          'Stainless Steel · 150 °C · 600 s · #7 · 01/09/2026\n'
                                          'T = 600 s\n'
                                          'α Phase (raw) = 5.551 mm²/s',
                                          'Stainless Steel · 150 °C · 1200 s · #18 · 01/09/2026\n'
                                          'T = 1200 s\n'
                                          'α Phase (raw) = 5.354 mm²/s',
                                          'Stainless Steel · 150 °C · 2400 s · #5 · garbage\n'
                                          'T = 2400 s\n'
                                          'α Phase (raw) = 4.425 mm²/s',
                                          'Stainless Steel · 150 °C · 2400 s · #2 · 05/09/2026\n'
                                          'T = 2400 s\n'
                                          'α Phase (raw) = 3.855 mm²/s'],
                                 'name': 'Stainless Steel (α Phase (raw))',
                                 'mode': 'markers',
                                 'symbol': 'circle-open',
                                 'opacity': 0.4,
                                 'dash': 'solid',
                                 'legendgroup': 'Stainless Steel',
                                 'showlegend': False},
                                {'x': [254.99, 600, 1200, 2400],
                                 'y': [6.664068381706792, 5.550951269061288, 5.353926764140904, 4.140005818230588],
                                 'yerr': [0, 0, 0, 0.4033033703489577],
                                 'text': ['Stainless Steel\nT ≈ 255 s\nα Phase (raw): mean 6.664 ± 0 mm²/s\nn = 2',
                                          'Stainless Steel\nT ≈ 600 s\nα Phase (raw): mean 5.551 ± 0 mm²/s\nn = 1',
                                          'Stainless Steel\nT ≈ 1200 s\nα Phase (raw): mean 5.354 ± 0 mm²/s\nn = 1',
                                          'Stainless Steel\n'
                                          'T ≈ 2400 s\n'
                                          'α Phase (raw): mean 4.14 ± 0.403 mm²/s\n'
                                          'n = 2'],
                                 'name': 'Stainless Steel (α Phase (raw)) — mean ± std',
                                 'mode': 'lines+markers',
                                 'dash': 'solid',
                                 'legendgroup': 'Stainless Steel'},
                                {'x': [254.99],
                                 'y': [7.9968820580481506],
                                 'ids': [17],
                                 'text': ['Stainless Steel · 150 °C · 255 s · #17 · 01/09/2026\n'
                                          'T = 255 s\n'
                                          'α Phase (cal) = 7.997 mm²/s'],
                                 'name': 'Stainless Steel (α Phase (cal))',
                                 'mode': 'markers',
                                 'symbol': 'circle',
                                 'opacity': 0.4,
                                 'dash': 'dash',
                                 'legendgroup': 'Stainless Steel',
                                 'showlegend': False},
                                {'x': [254.99],
                                 'y': [7.9968820580481506],
                                 'yerr': [0],
                                 'text': ['Stainless Steel\nT ≈ 255 s\nα Phase (cal): mean 7.997 ± 0 mm²/s\nn = 1'],
                                 'name': 'Stainless Steel (α Phase (cal)) — mean ± std',
                                 'mode': 'lines+markers',
                                 'dash': 'dash',
                                 'legendgroup': 'Stainless Steel'},
                                {'x': [254.99, 254.99, None],
                                 'y': [6.664068381706792, 7.9968820580481506, None],
                                 'name': 'Stainless Steel',
                                 'mode': 'lines',
                                 'seg': True,
                                 'legendgroup': 'Stainless Steel'},
                                {'x': [199.9, 200, 255, 1200],
                                 'y': [3.442393470947015, 3.2034575652477435, 2.267545453047912, 1.0841701697385326],
                                 'ids': [14, 13, 15, 8],
                                 'text': ['unk foam · 25 °C · 200 s · #14 · 01/09/2026\n'
                                          'T = 200 s\n'
                                          'α Phase (raw) = 3.442 mm²/s',
                                          'unk foam · 25 °C · 200 s · #13 · 05/09/2026\n'
                                          'T = 200 s\n'
                                          'α Phase (raw) = 3.203 mm²/s',
                                          'unk foam · 255 s · #15 · 15/08/2026\n'
                                          'T = 255 s\n'
                                          'α Phase (raw) = 2.268 mm²/s',
                                          'unk foam · 150 °C · 1200 s · #8 · 20/10/2026\n'
                                          'T = 1200 s\n'
                                          'α Phase (raw) = 1.084 mm²/s'],
                                 'name': 'unk foam (α Phase (raw))',
                                 'mode': 'markers',
                                 'symbol': 'circle-open',
                                 'opacity': 0.4,
                                 'dash': 'solid',
                                 'legendgroup': 'unk foam',
                                 'showlegend': False},
                                {'x': [199.95, 255, 1200],
                                 'y': [3.3229255180973793, 2.267545453047912, 1.0841701697385326],
                                 'yerr': [0.16895319918890447, 0, 0],
                                 'text': ['unk foam\nT ≈ 200 s\nα Phase (raw): mean 3.323 ± 0.169 mm²/s\nn = 2',
                                          'unk foam\nT ≈ 255 s\nα Phase (raw): mean 2.268 ± 0 mm²/s\nn = 1',
                                          'unk foam\nT ≈ 1200 s\nα Phase (raw): mean 1.084 ± 0 mm²/s\nn = 1'],
                                 'name': 'unk foam (α Phase (raw)) — mean ± std',
                                 'mode': 'lines+markers',
                                 'dash': 'solid',
                                 'legendgroup': 'unk foam'},
                                {'x': [75, 300, 523],
                                 'y': [3.4265131290501776, 1.4160589972095123, 1.5920510331915743],
                                 'ids': [12, 6, 11],
                                 'text': ['Abs · 25 °C · 75 s · #12 · 01/09/2026\n'
                                          'T = 75 s\n'
                                          'α Phase (raw) = 3.427 mm²/s',
                                          'Abs · 25 °C · 300 s · #6 · 01/09/2026\n'
                                          'T = 300 s\n'
                                          'α Phase (raw) = 1.416 mm²/s',
                                          'Abs · 25 °C · 523 s · #11 · 01/09/2026\n'
                                          'T = 523 s\n'
                                          'α Phase (raw) = 1.592 mm²/s'],
                                 'name': 'Abs (α Phase (raw))',
                                 'mode': 'markers',
                                 'symbol': 'circle-open',
                                 'opacity': 0.4,
                                 'dash': 'solid',
                                 'legendgroup': 'Abs',
                                 'showlegend': False},
                                {'x': [75, 300, 523],
                                 'y': [3.4265131290501776, 1.4160589972095123, 1.5920510331915743],
                                 'yerr': [0, 0, 0],
                                 'text': ['Abs\nT ≈ 75 s\nα Phase (raw): mean 3.427 ± 0 mm²/s\nn = 1',
                                          'Abs\nT ≈ 300 s\nα Phase (raw): mean 1.416 ± 0 mm²/s\nn = 1',
                                          'Abs\nT ≈ 523 s\nα Phase (raw): mean 1.592 ± 0 mm²/s\nn = 1'],
                                 'name': 'Abs (α Phase (raw)) — mean ± std',
                                 'mode': 'lines+markers',
                                 'dash': 'solid',
                                 'legendgroup': 'Abs'},
                                {'x': [75, 1200, 2400],
                                 'y': [4.336680678954131, 3.2611688445568783, 8.673361357908261],
                                 'ids': [1, 9, 10],
                                 'text': ['Al₂O₃ · 25 °C · 75 s · #1 · 10/01/2026\n'
                                          'T = 75 s\n'
                                          'α Phase (raw) = 4.337 mm²/s',
                                          'Al₂O₃ · 150 °C · 1200 s · #9 · 31/12/2025\n'
                                          'T = 1200 s\n'
                                          'α Phase (raw) = 3.261 mm²/s',
                                          'Al₂O₃ · 150 °C · 2400 s · #10 · 01/09/2026\n'
                                          'T = 2400 s\n'
                                          'α Phase (raw) = 8.673 mm²/s'],
                                 'name': 'Al₂O₃ (α Phase (raw))',
                                 'mode': 'markers',
                                 'symbol': 'circle-open',
                                 'opacity': 0.4,
                                 'dash': 'solid',
                                 'legendgroup': 'Al₂O₃',
                                 'showlegend': False},
                                {'x': [75, 1200, 2400],
                                 'y': [4.336680678954131, 3.2611688445568783, 8.673361357908261],
                                 'yerr': [0, 0, 0],
                                 'text': ['Al₂O₃\nT ≈ 75 s\nα Phase (raw): mean 4.337 ± 0 mm²/s\nn = 1',
                                          'Al₂O₃\nT ≈ 1200 s\nα Phase (raw): mean 3.261 ± 0 mm²/s\nn = 1',
                                          'Al₂O₃\nT ≈ 2400 s\nα Phase (raw): mean 8.673 ± 0 mm²/s\nn = 1'],
                                 'name': 'Al₂O₃ (α Phase (raw)) — mean ± std',
                                 'mode': 'lines+markers',
                                 'dash': 'solid',
                                 'legendgroup': 'Al₂O₃'},
                                {'x': [2400],
                                 'y': [10.408033629489914],
                                 'ids': [10],
                                 'text': ['Al₂O₃ · 150 °C · 2400 s · #10 · 01/09/2026\n'
                                          'T = 2400 s\n'
                                          'α Phase (cal) = 10.41 mm²/s'],
                                 'name': 'Al₂O₃ (α Phase (cal))',
                                 'mode': 'markers',
                                 'symbol': 'circle',
                                 'opacity': 0.4,
                                 'dash': 'dash',
                                 'legendgroup': 'Al₂O₃',
                                 'showlegend': False},
                                {'x': [2400],
                                 'y': [10.408033629489914],
                                 'yerr': [0],
                                 'text': ['Al₂O₃\nT ≈ 2400 s\nα Phase (cal): mean 10.41 ± 0 mm²/s\nn = 1'],
                                 'name': 'Al₂O₃ (α Phase (cal)) — mean ± std',
                                 'mode': 'lines+markers',
                                 'dash': 'dash',
                                 'legendgroup': 'Al₂O₃'},
                                {'x': [2400, 2400, None],
                                 'y': [8.673361357908261, 10.408033629489914, None],
                                 'name': 'Al₂O₃',
                                 'mode': 'lines',
                                 'seg': True,
                                 'legendgroup': 'Al₂O₃'}]}},
 'H': [{'title': 'ln term by Model',
        'yLabel': 'ln(A₁√r₁ / A₂√r₂)',
        'traces': [{'name': 'Stainless Steel',
                    'vals': [0.9943919040368049,
                             0.5194982894968776,
                             0.9382086243550626,
                             0.9429819031077202,
                             0.924963397605042]},
                   {'name': 'unk foam',
                    'vals': [0.9895019187426131,
                             0.9814047085099937,
                             1.0317022732329895,
                             -0.2914319267194513,
                             1.084812098546938]},
                   {'name': 'Abs', 'vals': [1.2126454700568228, 1.1565560034057791, 1.0501265405590479]},
                   {'name': 'Al₂O₃', 'vals': [1.2126454700568228, 1.0050790265790195, 0.9895019187426131]}],
        'refLine': None},
       {'title': 'A₁/A₂ Ratio by Model',
        'yLabel': 'A₁/A₂',
        'traces': [{'name': 'Stainless Steel', 'vals': [4.019607843137255, 2.5, 3.8, 3.8181818181818183, 3.75]},
                   {'name': 'unk foam', 'vals': [4, 3.967741935483871, 4.172413793103448, 1.1111111111111112, 4.4]},
                   {'name': 'Abs', 'vals': [5, 4.727272727272727, 4.25]},
                   {'name': 'Al₂O₃', 'vals': [5, 4.461538461538462, 4]}],
        'refLine': None},
       {'title': 'α phase/α comb by Model',
        'yLabel': 'α phase / α combined',
        'traces': [{'name': 'Stainless Steel',
                    'vals': [5.524399466871138,
                             1.484280827133936,
                             3.75283449742025,
                             6.735585022198,
                             6.16642265070028]},
                   {'name': 'unk foam', 'vals': [1.649169864571022, 1.7843721972908972, 1.810003988128052]},
                   {'name': 'Abs', 'vals': [1.3473838556186915, 2.3131120068115583]},
                   {'name': 'Al₂O₃', 'vals': [12.126454700568226, 5.912229568111879, 1.2368773984282662]}],
        'refLine': 1}],
 'P': [{'title': 'Raw Phase φ vs Period',
        'yLabel': 'φ (rad)',
        'traces': [{'name': 'Stainless Steel',
                    'x': [254.99, 600, 1200, 2400, 2400],
                    'y': [0.35, 0.25, 0.18, 0.14, 0.15],
                    'ids': [16, 7, 18, 5, 2],
                    'text': ['Stainless Steel · 150 °C · 255 s · #16 · 01/09/2026\nT = 255 s\nφ (rad) = 0.35',
                             'Stainless Steel · 150 °C · 600 s · #7 · 01/09/2026\nT = 600 s\nφ (rad) = 0.25',
                             'Stainless Steel · 150 °C · 1200 s · #18 · 01/09/2026\nT = 1200 s\nφ (rad) = 0.18',
                             'Stainless Steel · 150 °C · 2400 s · #5 · garbage\nT = 2400 s\nφ (rad) = 0.14',
                             'Stainless Steel · 150 °C · 2400 s · #2 · 05/09/2026\nT = 2400 s\nφ (rad) = 0.15']},
                   {'name': 'unk foam',
                    'x': [199.9, 200, 255, 699.9, 1200],
                    'y': [0.55, 0.57, 0.6, 0.45, 0.4],
                    'ids': [14, 13, 15, 4, 8],
                    'text': ['unk foam · 25 °C · 200 s · #14 · 01/09/2026\nT = 200 s\nφ (rad) = 0.55',
                             'unk foam · 25 °C · 200 s · #13 · 05/09/2026\nT = 200 s\nφ (rad) = 0.57',
                             'unk foam · 255 s · #15 · 15/08/2026\nT = 255 s\nφ (rad) = 0.6',
                             'unk foam · 150 °C · 700 s · #4 · 01/09/2026\nT = 700 s\nφ (rad) = 0.45',
                             'unk foam · 150 °C · 1200 s · #8 · 20/10/2026\nT = 1200 s\nφ (rad) = 0.4']},
                   {'name': 'Abs',
                    'x': [75, 300, 400, 523],
                    'y': [0.9, 0.7, 0.4, 0.5],
                    'ids': [12, 6, 3, 11],
                    'text': ['Abs · 25 °C · 75 s · #12 · 01/09/2026\nT = 75 s\nφ (rad) = 0.9',
                             'Abs · 25 °C · 300 s · #6 · 01/09/2026\nT = 300 s\nφ (rad) = 0.7',
                             'Abs · 25 °C · 400 s · #3 · 01/09/2026\nT = 400 s\nφ (rad) = 0.4',
                             'Abs · 25 °C · 523 s · #11 · 01/09/2026\nT = 523 s\nφ (rad) = 0.5']},
                   {'name': 'Al₂O₃',
                    'x': [75, 1200, 2400],
                    'y': [0.8, 0.17, 0.1],
                    'ids': [1, 9, 10],
                    'text': ['Al₂O₃ · 25 °C · 75 s · #1 · 10/01/2026\nT = 75 s\nφ (rad) = 0.8',
                             'Al₂O₃ · 150 °C · 1200 s · #9 · 31/12/2025\nT = 1200 s\nφ (rad) = 0.17',
                             'Al₂O₃ · 150 °C · 2400 s · #10 · 01/09/2026\nT = 2400 s\nφ (rad) = 0.1']}]},
       {'title': 'Raw Time Lag Δt vs Period',
        'yLabel': 'Δt (s)',
        'traces': [{'name': 'Stainless Steel',
                    'x': [254.99, 600, 1200, 2400, 2400],
                    'y': [14.204021628650837,
                          23.873241463784304,
                          34.3774677078494,
                          53.476060878876844,
                          57.29577951308232],
                    'ids': [16, 7, 18, 5, 2],
                    'text': ['Stainless Steel · 150 °C · 255 s · #16 · 01/09/2026\nT = 255 s\nΔt (s) = 14.2',
                             'Stainless Steel · 150 °C · 600 s · #7 · 01/09/2026\nT = 600 s\nΔt (s) = 23.87',
                             'Stainless Steel · 150 °C · 1200 s · #18 · 01/09/2026\nT = 1200 s\nΔt (s) = 34.38',
                             'Stainless Steel · 150 °C · 2400 s · #5 · garbage\nT = 2400 s\nΔt (s) = 53.48',
                             'Stainless Steel · 150 °C · 2400 s · #2 · 05/09/2026\nT = 2400 s\nΔt (s) = 57.3']},
                   {'name': 'unk foam',
                    'x': [199.9, 200, 255, 699.9, 1200],
                    'y': [17.498290218238434,
                          18.143663512476067,
                          24.350706293059986,
                          50.1266451015079,
                          76.39437268410977],
                    'ids': [14, 13, 15, 4, 8],
                    'text': ['unk foam · 25 °C · 200 s · #14 · 01/09/2026\nT = 200 s\nΔt (s) = 17.5',
                             'unk foam · 25 °C · 200 s · #13 · 05/09/2026\nT = 200 s\nΔt (s) = 18.14',
                             'unk foam · 255 s · #15 · 15/08/2026\nT = 255 s\nΔt (s) = 24.35',
                             'unk foam · 150 °C · 700 s · #4 · 01/09/2026\nT = 700 s\nΔt (s) = 50.13',
                             'unk foam · 150 °C · 1200 s · #8 · 20/10/2026\nT = 1200 s\nΔt (s) = 76.39']},
                   {'name': 'Abs',
                    'x': [75, 300, 400, 523],
                    'y': [10.742958658702937, 33.42253804929802, 25.464790894703253, 41.619017618530634],
                    'ids': [12, 6, 3, 11],
                    'text': ['Abs · 25 °C · 75 s · #12 · 01/09/2026\nT = 75 s\nΔt (s) = 10.74',
                             'Abs · 25 °C · 300 s · #6 · 01/09/2026\nT = 300 s\nΔt (s) = 33.42',
                             'Abs · 25 °C · 400 s · #3 · 01/09/2026\nT = 400 s\nΔt (s) = 25.46',
                             'Abs · 25 °C · 523 s · #11 · 01/09/2026\nT = 523 s\nΔt (s) = 41.62']},
                   {'name': 'Al₂O₃',
                    'x': [75, 1200, 2400],
                    'y': [9.549296585513721, 32.467608390746655, 38.197186342054884],
                    'ids': [1, 9, 10],
                    'text': ['Al₂O₃ · 25 °C · 75 s · #1 · 10/01/2026\nT = 75 s\nΔt (s) = 9.549',
                             'Al₂O₃ · 150 °C · 1200 s · #9 · 31/12/2025\nT = 1200 s\nΔt (s) = 32.47',
                             'Al₂O₃ · 150 °C · 2400 s · #10 · 01/09/2026\nT = 2400 s\nΔt (s) = 38.2']}]}],
 'PResp': [{'title': 'Raw Phase φ vs Period',
            'yLabel': 'φ (rad)',
            'traces': [{'name': 'Stainless Steel',
                        'x': [257.5399, 257.5399, 1212, 2424, 2424],
                        'y': [0.35, 0.35, 0.18, 0.14, 0.15],
                        'ids': [17, 16, 18, 5, 2],
                        'text': ['Stainless Steel · 150 °C · 255 s · #17 · 01/09/2026\nT = 258 s\nφ (rad) = 0.35',
                                 'Stainless Steel · 150 °C · 255 s · #16 · 01/09/2026\nT = 258 s\nφ (rad) = 0.35',
                                 'Stainless Steel · 150 °C · 1200 s · #18 · 01/09/2026\nT = 1212 s\nφ (rad) = 0.18',
                                 'Stainless Steel · 150 °C · 2400 s · #5 · garbage\nT = 2424 s\nφ (rad) = 0.14',
                                 'Stainless Steel · 150 °C · 2400 s · #2 · 05/09/2026\nT = 2424 s\nφ (rad) = 0.15']},
                       {'name': 'unk foam',
                        'x': [201.899, 202, 257.55, 706.899, 1212],
                        'y': [0.55, 0.57, 0.6, 0.45, 0.4],
                        'ids': [14, 13, 15, 4, 8],
                        'text': ['unk foam · 25 °C · 200 s · #14 · 01/09/2026\nT = 202 s\nφ (rad) = 0.55',
                                 'unk foam · 25 °C · 200 s · #13 · 05/09/2026\nT = 202 s\nφ (rad) = 0.57',
                                 'unk foam · 255 s · #15 · 15/08/2026\nT = 258 s\nφ (rad) = 0.6',
                                 'unk foam · 150 °C · 700 s · #4 · 01/09/2026\nT = 707 s\nφ (rad) = 0.45',
                                 'unk foam · 150 °C · 1200 s · #8 · 20/10/2026\nT = 1212 s\nφ (rad) = 0.4']},
                       {'name': 'Abs',
                        'x': [75.75, 303, 404, 528.23],
                        'y': [0.9, 0.7, 0.4, 0.5],
                        'ids': [12, 6, 3, 11],
                        'text': ['Abs · 25 °C · 75 s · #12 · 01/09/2026\nT = 76 s\nφ (rad) = 0.9',
                                 'Abs · 25 °C · 300 s · #6 · 01/09/2026\nT = 303 s\nφ (rad) = 0.7',
                                 'Abs · 25 °C · 400 s · #3 · 01/09/2026\nT = 404 s\nφ (rad) = 0.4',
                                 'Abs · 25 °C · 523 s · #11 · 01/09/2026\nT = 528 s\nφ (rad) = 0.5']},
                       {'name': 'Al₂O₃',
                        'x': [75.75, 1212, 2424],
                        'y': [0.8, 0.17, 0.1],
                        'ids': [1, 9, 10],
                        'text': ['Al₂O₃ · 25 °C · 75 s · #1 · 10/01/2026\nT = 76 s\nφ (rad) = 0.8',
                                 'Al₂O₃ · 150 °C · 1200 s · #9 · 31/12/2025\nT = 1212 s\nφ (rad) = 0.17',
                                 'Al₂O₃ · 150 °C · 2400 s · #10 · 01/09/2026\nT = 2424 s\nφ (rad) = 0.1']}]},
           {'title': 'Raw Time Lag Δt vs Period',
            'yLabel': 'Δt (s)',
            'traces': [{'name': 'Stainless Steel',
                        'x': [257.5399, 257.5399, 1212, 2424, 2424],
                        'y': [14.204021628650837,
                              14.204021628650837,
                              34.3774677078494,
                              53.476060878876844,
                              57.29577951308232],
                        'ids': [17, 16, 18, 5, 2],
                        'text': ['Stainless Steel · 150 °C · 255 s · #17 · 01/09/2026\nT = 258 s\nΔt (s) = 14.2',
                                 'Stainless Steel · 150 °C · 255 s · #16 · 01/09/2026\nT = 258 s\nΔt (s) = 14.2',
                                 'Stainless Steel · 150 °C · 1200 s · #18 · 01/09/2026\nT = 1212 s\nΔt (s) = 34.38',
                                 'Stainless Steel · 150 °C · 2400 s · #5 · garbage\nT = 2424 s\nΔt (s) = 53.48',
                                 'Stainless Steel · 150 °C · 2400 s · #2 · 05/09/2026\nT = 2424 s\nΔt (s) = 57.3']},
                       {'name': 'unk foam',
                        'x': [201.899, 202, 257.55, 706.899, 1212],
                        'y': [17.498290218238434,
                              18.143663512476067,
                              24.350706293059986,
                              50.1266451015079,
                              76.39437268410977],
                        'ids': [14, 13, 15, 4, 8],
                        'text': ['unk foam · 25 °C · 200 s · #14 · 01/09/2026\nT = 202 s\nΔt (s) = 17.5',
                                 'unk foam · 25 °C · 200 s · #13 · 05/09/2026\nT = 202 s\nΔt (s) = 18.14',
                                 'unk foam · 255 s · #15 · 15/08/2026\nT = 258 s\nΔt (s) = 24.35',
                                 'unk foam · 150 °C · 700 s · #4 · 01/09/2026\nT = 707 s\nΔt (s) = 50.13',
                                 'unk foam · 150 °C · 1200 s · #8 · 20/10/2026\nT = 1212 s\nΔt (s) = 76.39']},
                       {'name': 'Abs',
                        'x': [75.75, 303, 404, 528.23],
                        'y': [10.742958658702937, 33.42253804929802, 25.464790894703253, 41.619017618530634],
                        'ids': [12, 6, 3, 11],
                        'text': ['Abs · 25 °C · 75 s · #12 · 01/09/2026\nT = 76 s\nΔt (s) = 10.74',
                                 'Abs · 25 °C · 300 s · #6 · 01/09/2026\nT = 303 s\nΔt (s) = 33.42',
                                 'Abs · 25 °C · 400 s · #3 · 01/09/2026\nT = 404 s\nΔt (s) = 25.46',
                                 'Abs · 25 °C · 523 s · #11 · 01/09/2026\nT = 528 s\nΔt (s) = 41.62']},
                       {'name': 'Al₂O₃',
                        'x': [75.75, 1212, 2424],
                        'y': [9.549296585513721, 32.467608390746655, 38.197186342054884],
                        'ids': [1, 9, 10],
                        'text': ['Al₂O₃ · 25 °C · 75 s · #1 · 10/01/2026\nT = 76 s\nΔt (s) = 9.549',
                                 'Al₂O₃ · 150 °C · 1200 s · #9 · 31/12/2025\nT = 1212 s\nΔt (s) = 32.47',
                                 'Al₂O₃ · 150 °C · 2400 s · #10 · 01/09/2026\nT = 2424 s\nΔt (s) = 38.2']}]}],
 'T': [{'title': 'α Combined (raw) vs Temperature',
        'traces': [{'name': 'Stainless Steel',
                    'x': [150, 150, 150, 150, 150],
                    'y': [0.9691418580874664,
                          4.489762489605648,
                          1.4791356434388696,
                          0.6569858967997513,
                          0.6251318614600125]},
                   {'name': 'unk foam', 'x': [25, 25], 'y': [1.9291902643256769, 1.7698621584590173]},
                   {'name': 'Abs',
                    'x': [25, 25, 25],
                    'y': [2.543086081046141, 0.6882723484653432, 1.2389023164709594]},
                   {'name': 'Al₂O₃',
                    'x': [25, 150, 150],
                    'y': [3.506152416128607, 0.715242960294227, 0.5515971271051913]}]},
       {'title': 'α Phase (raw) vs Temperature',
        'traces': [{'name': 'Stainless Steel',
                    'x': [150, 150, 150, 150, 150],
                    'y': [5.353926764140904,
                          6.664068381706792,
                          5.550951269061288,
                          4.4251843662797254,
                          3.8548272701814503]},
                   {'name': 'unk foam',
                    'x': [25, 25, 150],
                    'y': [3.442393470947015, 3.2034575652477435, 1.0841701697385326]},
                   {'name': 'Abs',
                    'x': [25, 25, 25],
                    'y': [3.4265131290501776, 1.5920510331915743, 1.4160589972095123]},
                   {'name': 'Al₂O₃',
                    'x': [25, 150, 150],
                    'y': [4.336680678954131, 8.673361357908261, 3.2611688445568783]}]}],
 'TOne': [],
 'TNone': [],
 'C': {'labels': ['A₁', 'A₂', 'A₁/A₂', 'Period', 'Δt', 'φ', 'ln term', 'α comb raw', 'α phase raw', 'T (°C)'],
       'text': [['1.00', '0.73', '0.04', '0.54', '-0.01', '-0.56', '0.07', '-0.03', '0.70', '0.57'],
                ['0.73', '1.00', '-0.68', '0.44', '0.29', '-0.50', '-0.66', '0.26', '0.40', '0.68'],
                ['0.04', '-0.68', '1.00', '-0.02', '-0.42', '0.13', '0.97', '-0.53', '0.23', '-0.36'],
                ['0.54', '0.44', '-0.02', '1.00', '0.68', '-0.80', '-0.05', '-0.62', '0.37', '0.68'],
                ['-0.01', '0.29', '-0.42', '0.68', '1.00', '-0.51', '-0.50', '-0.77', '-0.26', '0.54'],
                ['-0.56', '-0.50', '0.13', '-0.80', '-0.51', '1.00', '0.10', '0.55', '-0.49', '-0.81'],
                ['0.07', '-0.66', '0.97', '-0.05', '-0.50', '0.10', '1.00', '-0.55', '0.30', '-0.35'],
                ['-0.03', '0.26', '-0.53', '-0.62', '-0.77', '0.55', '-0.55', '1.00', '0.19', '-0.25'],
                ['0.70', '0.40', '0.23', '0.37', '-0.26', '-0.49', '0.30', '0.19', '1.00', '0.48'],
                ['0.57', '0.68', '-0.36', '0.68', '0.54', '-0.81', '-0.35', '-0.25', '0.48', '1.00']],
       'matrix': [[1,
                   0.7298419902734941,
                   0.0377109995483998,
                   0.5397673429669045,
                   -0.007264006670010008,
                   -0.5646873523069184,
                   0.07150408985736463,
                   -0.026573854122561323,
                   0.6970987300857754,
                   0.5724887081538185],
                  [0.7298419902734941,
                   1,
                   -0.6755020195766882,
                   0.4362071270768031,
                   0.2899696991617662,
                   -0.49896377701479705,
                   -0.6615312006538867,
                   0.2588914233003301,
                   0.40424836029011646,
                   0.679894502480955],
                  [0.0377109995483998,
                   -0.6755020195766882,
                   1,
                   -0.021919119459592677,
                   -0.41838576555925705,
                   0.12505432982127446,
                   0.9728004515753911,
                   -0.5298525292064074,
                   0.2317732704614937,
                   -0.3602881100477231],
                  [0.5397673429669045,
                   0.4362071270768031,
                   -0.021919119459592677,
                   1.0000000000000002,
                   0.6763025396081661,
                   -0.7993045875361107,
                   -0.05121984842020298,
                   -0.6179568880098827,
                   0.3664381868317343,
                   0.6805437868705471],
                  [-0.007264006670010008,
                   0.2899696991617662,
                   -0.41838576555925705,
                   0.6763025396081661,
                   0.9999999999999998,
                   -0.5079671668083572,
                   -0.49532439361104186,
                   -0.7683244518307838,
                   -0.2598976979661152,
                   0.5437366524036166],
                  [-0.5646873523069184,
                   -0.49896377701479705,
                   0.12505432982127446,
                   -0.7993045875361107,
                   -0.5079671668083572,
                   1,
                   0.1040442049053571,
                   0.5533409493025853,
                   -0.49225122731238813,
                   -0.8083786078988419],
                  [0.07150408985736463,
                   -0.6615312006538867,
                   0.9728004515753911,
                   -0.05121984842020298,
                   -0.49532439361104186,
                   0.1040442049053571,
                   1.0000000000000002,
                   -0.5544009153893152,
                   0.2983997718920841,
                   -0.348940746273503],
                  [-0.026573854122561323,
                   0.2588914233003301,
                   -0.5298525292064074,
                   -0.6179568880098827,
                   -0.7683244518307838,
                   0.5533409493025853,
                   -0.5544009153893152,
                   1,
                   0.1889735254945457,
                   -0.24955602970439433],
                  [0.6970987300857754,
                   0.40424836029011646,
                   0.2317732704614937,
                   0.3664381868317343,
                   -0.2598976979661152,
                   -0.49225122731238813,
                   0.2983997718920841,
                   0.1889735254945457,
                   0.9999999999999999,
                   0.4826680769358833],
                  [0.5724887081538185,
                   0.679894502480955,
                   -0.3602881100477231,
                   0.6805437868705471,
                   0.5437366524036166,
                   -0.8083786078988419,
                   -0.348940746273503,
                   -0.24955602970439433,
                   0.4826680769358833,
                   1.0000000000000002]]},
 'CResp': {'text': [['1.00', '0.72', '-0.00', '0.52', '-0.04', '-0.57', '0.04', '0.02', '0.69', '0.58'],
                    ['0.72', '1.00', '-0.71', '0.36', '0.19', '-0.50', '-0.69', '0.41', '0.47', '0.70'],
                    ['-0.00', '-0.71', '1.00', '0.04', '-0.29', '0.14', '0.97', '-0.68', '0.09', '-0.40'],
                    ['0.52', '0.36', '0.04', '1.00', '0.69', '-0.80', '0.00', '-0.61', '0.30', '0.65'],
                    ['-0.04', '0.19', '-0.29', '0.69', '1.00', '-0.47', '-0.40', '-0.76', '-0.32', '0.46'],
                    ['-0.57', '-0.50', '0.14', '-0.80', '-0.47', '1.00', '0.12', '0.43', '-0.49', '-0.80'],
                    ['0.04', '-0.69', '0.97', '0.00', '-0.40', '0.12', '1.00', '-0.70', '0.19', '-0.38'],
                    ['0.02', '0.41', '-0.68', '-0.61', '-0.76', '0.43', '-0.70', '1.00', '0.33', '-0.07'],
                    ['0.69', '0.47', '0.09', '0.30', '-0.32', '-0.49', '0.19', '0.33', '1.00', '0.52'],
                    ['0.58', '0.70', '-0.40', '0.65', '0.46', '-0.80', '-0.38', '-0.07', '0.52', '1.00']]},
 'CSmall': None}


def V(**kw) -> ViewState:
    return ViewState(**kw)


def nan_eq(a, b) -> bool:
    """Equal lists where a JS null (None) matches a NaN gap."""
    if len(a) != len(b):
        return False
    for u, v in zip(a, b):
        u = math.nan if u is None else u
        v = math.nan if v is None else v
        if not (u == v or (isinstance(u, float) and isinstance(v, float) and math.isnan(u) and math.isnan(v))):
            return False
    return True


SYMBOLS = ["o", "s", "d", "+", "x"]
DASHES = ["solid", "dash", "dot", "dashdot"]


# ------------------------------------------------------------------ alpha vs period

def test_alpha_plain_one_series():
    spec = S.build_alpha_period_spec(ORIGS, V())
    pin = PINS["A"]["plain"]
    assert spec.kind == "xy" and spec.title == pin["title"] == "α Combined (raw) vs Period — by Model"
    assert (spec.xlabel, spec.ylabel, spec.xlog, spec.ylog, spec.height) == ("Period (s)", "α (mm²/s)", True, False, 480)
    assert pin["height"] == 440 + 2 * 20 == 480              # 4 models: ceil(4/3) legend rows
    assert [s.name for s in spec.series] == [t["name"] for t in pin["traces"]]
    for s, t in zip(spec.series, pin["traces"]):
        assert s.x == t["x"] and s.y == t["y"] and s.ids == t["ids"] and s.hover == t["text"]
        assert (s.mode, s.symbol, s.filled, s.size, s.width, s.dash) == ("lines+markers", "o", True, 7, 1, "solid")
        assert (s.opacity, s.legend, s.legendgroup, s.segments) == (1, True, t["legendgroup"], False)
        assert s.color == material_color(s.name) and s.yerr is None
    assert spec.series[0].hover[0] == 'Stainless Steel · 150 °C · 255 s · #16 · 01/09/2026\nT = 255 s\nα Combined (raw) = 4.49 mm²/s'


def test_alpha_two_series_names_symbols_dashes_and_title_height():
    spec = S.build_alpha_period_spec(ORIGS, V(alpha_series=["phase_raw", "combined_raw"]))   # order = ALPHA_SERIES
    pin = PINS["A"]["two"]
    assert spec.title == pin["title"] == "α Combined (raw), α Phase (raw) vs Period — by Model"
    assert spec.height == pin["height"] == 440 + 2 * 2 * 20 == 520
    assert [s.name for s in spec.series] == [t["name"] for t in pin["traces"]]
    for s, t in zip(spec.series, pin["traces"]):
        assert s.x == t["x"] and s.y == t["y"] and s.ids == t["ids"]
        assert s.symbol == SYMBOLS[0 if "Combined" in s.name else 1]
        assert s.dash == DASHES[0 if "Combined" in s.name else 1]
        assert s.dash == t["dash"] and s.legendgroup == t["legendgroup"]
    assert S.ALPHA_LABELS == {"combined_raw": "α Combined (raw)", "phase_raw": "α Phase (raw)",
                              "combined_cal": "α Combined (cal)", "phase_cal": "α Phase (cal)"}


def test_alpha_none_cases_and_reference_lines():
    assert S.build_alpha_period_spec([], V()) is None
    assert S.build_alpha_period_spec(ORIGS, V(alpha_series=[])) is None
    spec = S.build_alpha_period_spec(ORIGS, V(lit_alpha=["Al", "Brass"], period_log=False, log_y=True))
    assert [(r.y, r.label, r.color, r.dash, r.width) for r in spec.ref_lines] == [
        (LITERATURE[n], n, LITERATURE_COLORS[n], "dash", 1.5) for n in ("Al", "Brass")]
    assert spec.xlog is False and spec.ylog is True
    assert len(S.build_alpha_period_spec(ORIGS, V()).ref_lines) == len(LIT_MATERIALS)
    assert S.build_alpha_period_spec(ORIGS, V(lit_alpha=[])).ref_lines == []


def test_alpha_show_mean_dims_runs_and_adds_mean_series():
    spec = S.build_alpha_period_spec(ORIGS, V(alpha_series=["phase_raw"], show_mean=True))
    pin = PINS["A"]["mean"]["traces"]
    assert [s.name for s in spec.series] == [t["name"] for t in pin]
    for s, t in zip(spec.series, pin):
        assert s.x == t["x"] and s.y == t["y"] and s.legendgroup == t["legendgroup"]
        if s.name.endswith("— mean ± std"):
            assert s.mode == "lines+markers" and s.symbol == "s" and s.size == 10 and s.width == 2 and s.legend
            assert s.yerr == t["yerr"] and s.hover == t["text"] and s.opacity == 1
            assert s.ids == [None] * len(s.x)
        else:
            assert s.mode == "markers" and s.opacity == 0.4 and s.legend is False and s.hover == t["text"]
    # the mean series are the foundation's period bins
    model = "Stainless Steel"
    runs = [(get_period(a, "src"), extract_y(a, "alpha_phase_raw")) for a in ORIGS if a["model_name"] == model]
    bins = bin_by_period([r for r in runs if r[0] is not None and r[1] is not None])
    mean_s = next(s for s in spec.series if s.name == model + " — mean ± std")
    assert mean_s.x == [b.x for b in bins] and mean_s.y == [b.y for b in bins]
    assert mean_s.yerr[0] == 0 and any(e > 0 for e in mean_s.yerr)
    assert mean_s.yerr == [b.sd if b.n >= 2 else 0 for b in bins]


def test_alpha_show_mean_with_two_series_and_resp_source():
    spec = S.build_alpha_period_spec(ORIGS, V(alpha_series=["combined_raw", "phase_raw"], show_mean=True,
                                              period_source="resp"))
    pin = PINS["A"]["meanResp"]["traces"]
    assert [s.name for s in spec.series] == [t["name"] for t in pin]
    for s, t in zip(spec.series, pin):
        assert s.x == t["x"] and s.y == t["y"] and s.dash == t["dash"] and s.hover == t["text"]
    assert 7 not in [i for s in spec.series for i in s.ids if i is not None]            # no response period


def test_alpha_pairs_connectors_and_symbols():
    series = ["combined_raw", "phase_raw", "combined_cal", "phase_cal"]
    spec = S.build_alpha_period_spec(ALL, V(alpha_series=series, show_pairs=True))
    pin = PINS["A"]["pairs"]["traces"]
    assert [s.name for s in spec.series] == [t["name"] for t in pin]
    table = {"phase_raw": ("o", False), "phase_cal": ("o", True), "combined_raw": ("d", False),
             "combined_cal": ("d", True)}
    labels = {v: k for k, v in S.ALPHA_LABELS.items()}
    n_segments = 0
    for s, t in zip(spec.series, pin):
        if t.get("seg"):
            assert s.segments and nan_eq(s.x, t["x"]) and nan_eq(s.y, t["y"])
            assert (s.mode, s.width, s.opacity, s.legend, s.legendgroup) == ("lines", 1.5, 0.55, False, t["legendgroup"])
            assert s.hover == [""] * len(s.x) and s.ids == [None] * len(s.x)
            n_segments += sum(1 for v in s.x if not math.isnan(v)) // 2
        else:
            key = labels[s.name[s.name.index("(") + 1:-1]]
            assert (s.symbol, s.filled) == table[key] and s.mode == "markers" and s.opacity == 1 and s.legend
    expected = sum(len(pair_segments(ALL, m, "src", True, True)) for m in dict.fromkeys(a["model_name"] for a in ALL))
    assert n_segments == expected > 0


def test_alpha_pairs_and_mean_together():
    spec = S.build_alpha_period_spec(ALL, V(alpha_series=["phase_raw", "phase_cal"], show_mean=True, show_pairs=True))
    pin = PINS["A"]["pairsMean"]["traces"]
    assert [s.name for s in spec.series] == [t["name"] for t in pin]
    for s, t in zip(spec.series, pin):
        assert nan_eq(s.x, t["x"]) and nan_eq(s.y, t["y"])
    runs = [s for s in spec.series if s.mode == "markers" and not s.segments]
    assert runs and all(s.opacity == 0.4 and not s.legend for s in runs)


# ------------------------------------------------------------------ heat loss

def test_heat_loss_three_box_specs():
    specs = S.build_heat_loss_specs(ORIGS, V(log_y=True))
    pins = PINS["H"]
    assert len(specs) == 3
    assert [s.title for s in specs] == ["ln term by Model", "A₁/A₂ Ratio by Model", "α phase/α comb by Model"]
    assert [s.title for s in specs] == [p["title"] for p in pins]
    assert [s.ylabel for s in specs] == [p["yLabel"] for p in pins]
    for s, p in zip(specs, pins):
        assert s.kind == "box" and s.xlabel == "Model" and s.ylog is True and s.height == 350 and s.xlog is False
        assert [g.name for g in s.groups] == [t["name"] for t in p["traces"]]
        assert [g.values for g in s.groups] == [t["vals"] for t in p["traces"]]
        assert [g.color for g in s.groups] == [material_color(g.name) for g in s.groups]
        assert [c[0] for c in s.categories] == [g.name for g in s.groups]
    assert S.build_heat_loss_specs(ORIGS, V())[0].ylog is False


def test_heat_loss_ratio_needs_both_alphas_positive_and_ideal_line_only_on_third():
    specs = S.build_heat_loss_specs(ORIGS, V())
    assert specs[0].ref_lines == [] and specs[1].ref_lines == []
    (ref,) = specs[2].ref_lines
    assert (ref.y, ref.label, ref.color, ref.dash, ref.width) == (1, "Ideal", "#888", "dash", 1)
    by_id = {i: v for g in specs[2].groups for i, v in zip(g.ids, g.values)}
    for a in ORIGS:
        c, p = a.get("alpha_combined_raw"), a.get("alpha_phase_raw")
        if c is not None and c > 0 and p is not None and p > 0:
            assert by_id[a["id"]] == p / c
        else:
            assert a["id"] not in by_id
    assert 3 not in by_id and 4 not in by_id and 8 not in by_id        # phase<=0, phase 0, ln-invalid (combined None)
    assert S.build_heat_loss_specs([], V()) == []


# ------------------------------------------------------------------ phase lag

def test_phase_specs_sorted_per_model():
    specs = S.build_phase_specs(ORIGS, V())
    pins = PINS["P"]
    assert [s.title for s in specs] == ["Raw Phase φ vs Period", "Raw Time Lag Δt vs Period"]
    assert [s.ylabel for s in specs] == ["φ (rad)", "Δt (s)"] == [p["yLabel"] for p in pins]
    for s, p in zip(specs, pins):
        assert s.kind == "xy" and s.xlabel == "Period (s)" and s.xlog is True and s.ylog is False and s.height == 380
        assert [x.name for x in s.series] == [t["name"] for t in p["traces"]]
        for x, t in zip(s.series, p["traces"]):
            assert x.x == t["x"] and x.x == sorted(x.x) and x.y == t["y"] and x.ids == t["ids"] and x.hover == t["text"]
            assert (x.mode, x.size, x.width, x.color) == ("lines+markers", 6, 1, material_color(x.name))


def test_phase_specs_flags_and_response_period():
    specs = S.build_phase_specs(ORIGS, V(period_log=False, log_y=True))
    assert all(s.xlog is False and s.ylog is True for s in specs)
    specs = S.build_phase_specs(ALL, V(period_source="resp"))
    for s, p in zip(specs, PINS["PResp"]):
        for x, t in zip(s.series, p["traces"]):
            assert x.x == t["x"] and x.y == t["y"] and x.ids == t["ids"]
        assert 7 not in [i for x in s.series for i in x.ids]
    assert S.build_phase_specs([], V()) == []


# ------------------------------------------------------------------ temperature

def test_temp_specs_two_temperatures():
    specs = S.build_temp_specs(ORIGS, V(log_y=True, period_log=True, log_x=True))
    pins = PINS["T"]
    assert [s.title for s in specs] == ["α Combined (raw) vs Temperature", "α Phase (raw) vs Temperature"]
    for s, p in zip(specs, pins):
        assert (s.xlabel, s.ylabel, s.xlog, s.ylog, s.height) == ("Temperature (°C)", "α (mm²/s)", False, False, 400)
        assert [x.name for x in s.series] == [t["name"] for t in p["traces"]]
        for x, t in zip(s.series, p["traces"]):
            assert x.x == t["x"] and x.y == t["y"] and x.mode == "lines+markers" and x.size == 7 and x.width == 1
            assert all(v > 0 for v in x.y) and x.x == sorted(x.x)
        assert [(r.y, r.label, r.color, r.dash, r.width) for r in s.ref_lines] == [
            (v, n, LITERATURE_COLORS[n], "dash", 1.5) for n, v in LITERATURE.items()]


def test_temp_specs_need_two_distinct_temperatures():
    assert PINS["TOne"] == [] and PINS["TNone"] == []
    assert S.build_temp_specs([r for r in ORIGS if r.get("temperature_c") == 150], V()) == []
    assert S.build_temp_specs([r for r in ORIGS if r.get("temperature_c") in (None, 25)], V()) == []
    assert S.build_temp_specs([], V()) == []


# ------------------------------------------------------------------ correlation

def test_corr_spec_matches_the_page():
    spec = S.build_corr_spec(ORIGS, V())
    pin = PINS["C"]
    assert spec.kind == "heatmap" and spec.title == "Correlation Matrix (Pearson r)" and spec.height == 560
    assert spec.heat.labels == pin["labels"]
    assert spec.heat.matrix == pin["matrix"]
    assert spec.heat.text == pin["text"]
    assert spec.heat.text[0][1] == "0.73" and spec.heat.text[0][0] == "1.00" and spec.heat.text[0][4] == "-0.01"
    assert S.build_corr_spec(ALL, V(period_source="resp")).heat.text == PINS["CResp"]["text"]


def test_corr_needs_three_rows():
    assert PINS["CSmall"] is None
    assert S.build_corr_spec(ORIGS[:2], V()) is None
    assert S.build_corr_spec(ORIGS[:3], V()) is not None


def test_corr_pair_to_builder():
    assert S.corr_pair_to_builder("φ", "α comb raw") is None                  # neither has an X
    assert S.corr_pair_to_builder("Δt", "φ") == ("raw_phase_phi", "Raw Δt (s)")
    assert S.corr_pair_to_builder("φ", "Δt") == ("raw_phase_phi", "Raw Δt (s)")
    assert S.corr_pair_to_builder("A₁", "A₁") is None                         # diagonal
    assert S.corr_pair_to_builder("A₁", "A₂") == ("amplitude_a1", "A₂ (mW)")
    assert S.corr_pair_to_builder("α comb raw", "T (°C)") == ("alpha_combined_raw", "Temperature (°C)")
    assert S.corr_pair_to_builder("A₁", "nope") is None
