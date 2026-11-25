"""Statistics aggregation; expected values pinned from page.tsx's own code (node, bodies pasted verbatim)."""
from __future__ import annotations

import json
import os

import pytest

from ctwa.analysis.diffusivity import theoretical_lag_dt, theoretical_phase
from ctwa.stats import aggregate as A
from ctwa.stats import filters as F
from ctwa.stats import model as M

FIX = os.path.join(os.path.dirname(__file__), "data", "stats_rows.json")
with open(FIX, encoding="utf-8") as _f:
    ROWS = json.load(_f)

PIN_FIT = [{'slope': 2, 'intercept': 0}, None, None, {'slope': 0.7739130434782608, 'intercept': 0.34782608695652173}]
PIN_BINS_SYN = [{'x': 101.5, 'y': 10.15, 'sd': 0.21213203435596475, 'n': 2},
 {'x': 104.5, 'y': 10.45, 'sd': 0, 'n': 1},
 {'x': 110, 'y': 11, 'sd': 0, 'n': 1}]
PIN_BINS_FIX = {'Stainless Steel': [{'x': 254.99, 'y': 6.664068381706792, 'sd': 0, 'n': 2},
                     {'x': 600, 'y': 5.550951269061288, 'sd': 0, 'n': 1},
                     {'x': 1200, 'y': 5.353926764140904, 'sd': 0, 'n': 1},
                     {'x': 2400, 'y': 4.140005818230588, 'sd': 0.4033033703489577, 'n': 2}],
 'unk foam': [{'x': 199.95, 'y': 3.3229255180973793, 'sd': 0.16895319918890447, 'n': 2},
              {'x': 255, 'y': 2.267545453047912, 'sd': 0, 'n': 1},
              {'x': 1200, 'y': 1.0841701697385326, 'sd': 0, 'n': 1}],
 'Abs': [{'x': 75, 'y': 3.4265131290501776, 'sd': 0, 'n': 1},
         {'x': 300, 'y': 1.4160589972095123, 'sd': 0, 'n': 1},
         {'x': 523, 'y': 1.5920510331915743, 'sd': 0, 'n': 1}],
 'Al₂O₃': [{'x': 75, 'y': 4.336680678954131, 'sd': 0, 'n': 1},
           {'x': 1200, 'y': 3.2611688445568783, 'sd': 0, 'n': 1},
           {'x': 2400, 'y': 8.673361357908261, 'sd': 0, 'n': 1}]}
PIN_PAIRS = {'Stainless Steel|src|true|false': [[[254.99, 6.664068381706792], [254.99, 7.9968820580481506]]],
 'Stainless Steel|src|false|true': [[[254.99, 4.489762489605648], [254.99, 4.938738738566214]]],
 'Stainless Steel|src|true|true': [[[254.99, 6.664068381706792], [254.99, 7.9968820580481506]],
                                   [[254.99, 4.489762489605648], [254.99, 4.938738738566214]]],
 'Stainless Steel|resp|true|false': [[[257.5399, 6.664068381706792], [257.5399, 7.9968820580481506]]],
 'Stainless Steel|resp|false|true': [[[257.5399, 4.489762489605648], [257.5399, 4.938738738566214]]],
 'Stainless Steel|resp|true|true': [[[257.5399, 6.664068381706792], [257.5399, 7.9968820580481506]],
                                    [[257.5399, 4.489762489605648], [257.5399, 4.938738738566214]]],
 'Al₂O₃|src|true|false': [[[2400, 8.673361357908261], [2400, 10.408033629489914]]],
 'Al₂O₃|src|false|true': [[[2400, 0.715242960294227], [2400, 0.7867672563236497]]],
 'Al₂O₃|src|true|true': [[[2400, 8.673361357908261], [2400, 10.408033629489914]],
                         [[2400, 0.715242960294227], [2400, 0.7867672563236497]]],
 'Al₂O₃|resp|true|false': [[[2424, 8.673361357908261], [2424, 10.408033629489914]]],
 'Al₂O₃|resp|false|true': [[[2424, 0.715242960294227], [2424, 0.7867672563236497]]],
 'Al₂O₃|resp|true|true': [[[2424, 8.673361357908261], [2424, 10.408033629489914]],
                          [[2424, 0.715242960294227], [2424, 0.7867672563236497]]],
 'unk foam|src|true|false': [],
 'unk foam|src|false|true': [],
 'unk foam|src|true|true': [],
 'unk foam|resp|true|false': [],
 'unk foam|resp|false|true': [],
 'unk foam|resp|true|true': [],
 'Abs|src|true|false': [],
 'Abs|src|false|true': [],
 'Abs|src|true|true': [],
 'Abs|resp|true|false': [],
 'Abs|resp|false|true': [],
 'Abs|resp|true|true': []}
PIN_DR = {'dr': 8.14, 'all': [8.14, 6], 'mixed': True}
PIN_DR_ALL = {'dr': 8.14, 'all': [8.14, 6], 'mixed': True}
PIN_DR_NONE = None
PIN_DR_TIE = {'dr': 6, 'all': [6, 8.14], 'mixed': True}
PIN_CORR = [[1,
  0.7244250044166691,
  -0.001972997727954277,
  0.5079713765451327,
  -0.03564071332064896,
  -0.5679443724506104,
  0.04013799814481655,
  0.0233522280402775,
  0.6869065929970117,
  0.5797819405509159],
 [0.7244250044166691,
  1,
  -0.7124555633386697,
  0.3525825924637892,
  0.18896175368911525,
  -0.4951032035449219,
  -0.6901001276126458,
  0.41073177389882276,
  0.4652681709817987,
  0.6968867129751247],
 [-0.001972997727954277,
  -0.7124555633386697,
  1.0000000000000002,
  0.04410994930828666,
  -0.2947560992277661,
  0.13776510984280216,
  0.9716708219425343,
  -0.6754894087375709,
  0.0940152849116559,
  -0.40076546398447055],
 [0.5079713765451327,
  0.3525825924637892,
  0.04410994930828666,
  1,
  0.6878474509357495,
  -0.7728180291525872,
  0.0006430965066021622,
  -0.6072925944800776,
  0.28029119763992644,
  0.6158161441799443],
 [-0.03564071332064896,
  0.18896175368911525,
  -0.2947560992277661,
  0.6878474509357495,
  1,
  -0.47356151324843504,
  -0.39776231904614656,
  -0.7596116965150138,
  -0.3174433129499468,
  0.4625251091819373],
 [-0.5679443724506104,
  -0.4951032035449219,
  0.13776510984280216,
  -0.7728180291525872,
  -0.47356151324843504,
  1,
  0.11603309217302384,
  0.4316596661711584,
  -0.4879102840028239,
  -0.8022875431582963],
 [0.04013799814481655,
  -0.6901001276126458,
  0.9716708219425343,
  0.0006430965066021622,
  -0.39776231904614656,
  0.11603309217302384,
  1,
  -0.700905715402071,
  0.18831850641859327,
  -0.38284268975601665],
 [0.0233522280402775,
  0.41073177389882276,
  -0.6754894087375709,
  -0.6072925944800776,
  -0.7596116965150138,
  0.4316596661711584,
  -0.700905715402071,
  1.0000000000000002,
  0.3277448716236023,
  -0.07261490126796584],
 [0.6869065929970117,
  0.4652681709817987,
  0.0940152849116559,
  0.28029119763992644,
  -0.3174433129499468,
  -0.4879102840028239,
  0.18831850641859327,
  0.3277448716236023,
  0.9999999999999998,
  0.5162306880322357],
 [0.5797819405509159,
  0.6968867129751247,
  -0.40076546398447055,
  0.6158161441799443,
  0.4625251091819373,
  -0.8022875431582963,
  -0.38284268975601665,
  -0.07261490126796584,
  0.5162306880322357,
  1]]
PIN_CORR_RESP = [[1,
  0.7244250044166691,
  -0.001972997727954277,
  0.5168912698328308,
  -0.03564071332064896,
  -0.5679443724506104,
  0.04013799814481655,
  0.0233522280402775,
  0.6869065929970117,
  0.5797819405509159],
 [0.7244250044166691,
  1,
  -0.7124555633386697,
  0.35672665529996866,
  0.18896175368911525,
  -0.4951032035449219,
  -0.6901001276126458,
  0.41073177389882276,
  0.4652681709817987,
  0.6968867129751247],
 [-0.001972997727954277,
  -0.7124555633386697,
  1.0000000000000002,
  0.043221025945314274,
  -0.2947560992277661,
  0.13776510984280216,
  0.9716708219425343,
  -0.6754894087375709,
  0.0940152849116559,
  -0.40076546398447055],
 [0.5168912698328308,
  0.35672665529996866,
  0.043221025945314274,
  1,
  0.6863015388327022,
  -0.799235573833468,
  0.0028253457462399994,
  -0.6149112608455557,
  0.30069567932295904,
  0.6479756670596231],
 [-0.03564071332064896,
  0.18896175368911525,
  -0.2947560992277661,
  0.6863015388327022,
  1,
  -0.47356151324843504,
  -0.39776231904614656,
  -0.7596116965150138,
  -0.3174433129499468,
  0.4625251091819373],
 [-0.5679443724506104,
  -0.4951032035449219,
  0.13776510984280216,
  -0.799235573833468,
  -0.47356151324843504,
  1,
  0.11603309217302384,
  0.4316596661711584,
  -0.4879102840028239,
  -0.8022875431582963],
 [0.04013799814481655,
  -0.6901001276126458,
  0.9716708219425343,
  0.0028253457462399994,
  -0.39776231904614656,
  0.11603309217302384,
  1,
  -0.700905715402071,
  0.18831850641859327,
  -0.38284268975601665],
 [0.0233522280402775,
  0.41073177389882276,
  -0.6754894087375709,
  -0.6149112608455557,
  -0.7596116965150138,
  0.4316596661711584,
  -0.700905715402071,
  1.0000000000000002,
  0.3277448716236023,
  -0.07261490126796584],
 [0.6869065929970117,
  0.4652681709817987,
  0.0940152849116559,
  0.30069567932295904,
  -0.3174433129499468,
  -0.4879102840028239,
  0.18831850641859327,
  0.3277448716236023,
  0.9999999999999998,
  0.5162306880322357],
 [0.5797819405509159,
  0.6968867129751247,
  -0.40076546398447055,
  0.6479756670596231,
  0.4625251091819373,
  -0.8022875431582963,
  -0.38284268975601665,
  -0.07261490126796584,
  0.5162306880322357,
  1]]
PIN_CORR_ORIG = [[1,
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
  1.0000000000000002]]
PIN_SUMMARY_ALL = [{'model': 'Stainless Steel',
  'n': 6,
  'combRaw': {'n': 6, 'mean': '2.118', 'std': '1.70', 'min': '0.6251', 'max': '4.490'},
  'phaseRaw': {'n': 6, 'mean': '5.419', 'std': '1.05', 'min': '3.855', 'max': '6.664'},
  'combCal': {'n': 1, 'mean': '4.939', 'std': '0.00', 'min': '4.939', 'max': '4.939'},
  'phaseCal': {'n': 1, 'mean': '7.997', 'std': '0.00', 'min': '7.997', 'max': '7.997'}},
 {'model': 'unk foam',
  'n': 5,
  'combRaw': {'n': 3, 'mean': '1.691', 'std': '0.233', 'min': '1.375', 'max': '1.929'},
  'phaseRaw': {'n': 4, 'mean': '2.499', 'std': '0.928', 'min': '1.084', 'max': '3.442'},
  'combCal': {'n': 0, 'mean': '—', 'std': '—', 'min': '—', 'max': '—'},
  'phaseCal': {'n': 0, 'mean': '—', 'std': '—', 'min': '—', 'max': '—'}},
 {'model': 'Abs',
  'n': 4,
  'combRaw': {'n': 3, 'mean': '1.490', 'std': '0.778', 'min': '0.6883', 'max': '2.543'},
  'phaseRaw': {'n': 3, 'mean': '2.145', 'std': '0.909', 'min': '1.416', 'max': '3.427'},
  'combCal': {'n': 0, 'mean': '—', 'std': '—', 'min': '—', 'max': '—'},
  'phaseCal': {'n': 0, 'mean': '—', 'std': '—', 'min': '—', 'max': '—'}},
 {'model': 'Al₂O₃',
  'n': 3,
  'combRaw': {'n': 3, 'mean': '1.591', 'std': '1.36', 'min': '0.5516', 'max': '3.506'},
  'phaseRaw': {'n': 3, 'mean': '5.424', 'std': '2.34', 'min': '3.261', 'max': '8.673'},
  'combCal': {'n': 1, 'mean': '0.7868', 'std': '0.00', 'min': '0.7868', 'max': '0.7868'},
  'phaseCal': {'n': 1, 'mean': '10.41', 'std': '0.00', 'min': '10.41', 'max': '10.41'}}]
PIN_SUMMARY_ORIG = [{'model': 'Stainless Steel',
  'n': 5,
  'combRaw': {'n': 5, 'mean': '1.644', 'std': '1.46', 'min': '0.6251', 'max': '4.490'},
  'phaseRaw': {'n': 5, 'mean': '5.170', 'std': '0.969', 'min': '3.855', 'max': '6.664'},
  'combCal': {'n': 0, 'mean': '—', 'std': '—', 'min': '—', 'max': '—'},
  'phaseCal': {'n': 0, 'mean': '—', 'std': '—', 'min': '—', 'max': '—'}},
 {'model': 'unk foam',
  'n': 5,
  'combRaw': {'n': 3, 'mean': '1.691', 'std': '0.233', 'min': '1.375', 'max': '1.929'},
  'phaseRaw': {'n': 4, 'mean': '2.499', 'std': '0.928', 'min': '1.084', 'max': '3.442'},
  'combCal': {'n': 0, 'mean': '—', 'std': '—', 'min': '—', 'max': '—'},
  'phaseCal': {'n': 0, 'mean': '—', 'std': '—', 'min': '—', 'max': '—'}},
 {'model': 'Abs',
  'n': 4,
  'combRaw': {'n': 3, 'mean': '1.490', 'std': '0.778', 'min': '0.6883', 'max': '2.543'},
  'phaseRaw': {'n': 3, 'mean': '2.145', 'std': '0.909', 'min': '1.416', 'max': '3.427'},
  'combCal': {'n': 0, 'mean': '—', 'std': '—', 'min': '—', 'max': '—'},
  'phaseCal': {'n': 0, 'mean': '—', 'std': '—', 'min': '—', 'max': '—'}},
 {'model': 'Al₂O₃',
  'n': 3,
  'combRaw': {'n': 3, 'mean': '1.591', 'std': '1.36', 'min': '0.5516', 'max': '3.506'},
  'phaseRaw': {'n': 3, 'mean': '5.424', 'std': '2.34', 'min': '3.261', 'max': '8.673'},
  'combCal': {'n': 1, 'mean': '0.7868', 'std': '0.00', 'min': '0.7868', 'max': '0.7868'},
  'phaseCal': {'n': 1, 'mean': '10.41', 'std': '0.00', 'min': '10.41', 'max': '10.41'}}]
PIN_CSV_ALL = ('Model,N,alpha_comb_raw_mean,alpha_comb_raw_std,alpha_comb_raw_min,alpha_comb_raw_max,alpha_phase_raw_mean,alpha_phase_raw_std,alpha_phase_raw_min,alpha_phase_raw_max,alpha_comb_cal_mean,alpha_comb_cal_std,alpha_comb_cal_min,alpha_comb_cal_max,alpha_phase_cal_mean,alpha_phase_cal_std,alpha_phase_cal_min,alpha_phase_cal_max\n'
 'Stainless '
 'Steel,6,2.118,1.70,0.6251,4.490,5.419,1.05,3.855,6.664,4.939,0.00,4.939,4.939,7.997,0.00,7.997,7.997\n'
 'unk foam,5,1.691,0.233,1.375,1.929,2.499,0.928,1.084,3.442,—,—,—,—,—,—,—,—\n'
 'Abs,4,1.490,0.778,0.6883,2.543,2.145,0.909,1.416,3.427,—,—,—,—,—,—,—,—\n'
 'Al₂O₃,3,1.591,1.36,0.5516,3.506,5.424,2.34,3.261,8.673,0.7868,0.00,0.7868,0.7868,10.41,0.00,10.41,10.41')
PIN_CSV_ORIG = ('Model,N,alpha_comb_raw_mean,alpha_comb_raw_std,alpha_comb_raw_min,alpha_comb_raw_max,alpha_phase_raw_mean,alpha_phase_raw_std,alpha_phase_raw_min,alpha_phase_raw_max,alpha_comb_cal_mean,alpha_comb_cal_std,alpha_comb_cal_min,alpha_comb_cal_max,alpha_phase_cal_mean,alpha_phase_cal_std,alpha_phase_cal_min,alpha_phase_cal_max\n'
 'Stainless Steel,5,1.644,1.46,0.6251,4.490,5.170,0.969,3.855,6.664,—,—,—,—,—,—,—,—\n'
 'unk foam,5,1.691,0.233,1.375,1.929,2.499,0.928,1.084,3.442,—,—,—,—,—,—,—,—\n'
 'Abs,4,1.490,0.778,0.6883,2.543,2.145,0.909,1.416,3.427,—,—,—,—,—,—,—,—\n'
 'Al₂O₃,3,1.591,1.36,0.5516,3.506,5.424,2.34,3.261,8.673,0.7868,0.00,0.7868,0.7868,10.41,0.00,10.41,10.41')


def _prep():
    return M.prepare_rows(ROWS)


def _all():
    return F.apply_filters(_prep(), F.FilterState(row_kind="all"))


def _orig():
    return F.apply_filters(_prep(), F.FilterState())


def test_means_and_stds():
    assert A.mean([1, 2, 6]) == 3
    assert A.std_pop([1, 3]) == 1.0
    assert A.std_sample([1, 3]) == 1.4142135623730951
    assert A.std_sample([5]) == 0
    assert A.std_sample([]) == 0


def test_linear_fit():
    got = A.linear_fit([1, 2, 3], [2, 4, 6])
    assert got == (2.0, 0.0) and got == (PIN_FIT[0]["slope"], PIN_FIT[0]["intercept"])
    assert A.linear_fit([1, 2], [2, 4]) is None
    assert A.linear_fit([2, 2, 2], [1, 2, 3]) is None
    s, i = A.linear_fit([1, 2, 4, 8], [1, 3, 2, 7])
    assert (s, i) == (PIN_FIT[3]["slope"], PIN_FIT[3]["intercept"])


def test_bin_by_period_synthetic():
    pts = [(x, x / 10) for x in (110, 100, 104.5, 103)]      # unsorted on purpose
    bins = A.bin_by_period(pts)
    assert [b.n for b in bins] == [2, 1, 1]
    assert bins[0].x == 101.5
    for b, w in zip(bins, PIN_BINS_SYN):
        assert (b.x, b.y, b.n) == (w["x"], w["y"], w["n"]) and b.sd == pytest.approx(w["sd"], rel=1e-14, abs=0)
    assert A.bin_by_period([]) == []


def test_bin_by_period_fixture_models():
    rows = _all()
    for model, want in PIN_BINS_FIX.items():
        pts = []
        for a in rows:
            if a["model_name"] != model:
                continue
            v, p = M.extract_y(a, "alpha_phase_raw"), M.get_period(a, "src")
            if v is not None and p is not None:
                pts.append((p, v))
        got = A.bin_by_period(pts)
        assert len(got) == len(want), model
        for b, w in zip(got, want):
            assert b.n == w["n"] and b.x == pytest.approx(w["x"], rel=1e-13) and b.y == pytest.approx(w["y"], rel=1e-13)
            assert b.sd == pytest.approx(w["sd"], rel=1e-12, abs=1e-15)


def test_pair_segments_pinned():
    rows = _all()
    assert len(PIN_PAIRS) == 24
    for key, want in PIN_PAIRS.items():
        model, src, ph, cb = key.split("|")
        got = A.pair_segments(rows, model, src, ph == "true", cb == "true")
        assert len(got) == len(want), key
        for g, w in zip(got, want):
            assert g[0][0] == w[0][0] == g[1][0]
            assert g[0][1] == pytest.approx(w[0][1], rel=1e-14) and g[1][1] == pytest.approx(w[1][1], rel=1e-14)


def test_pair_segments_skip_single_sided():
    rows = _all()
    # Stainless Steel: only the reference-less copy pair 17 and the originals having both ends count
    segs = A.pair_segments(rows, "Stainless Steel", "src", True, False)
    assert len(segs) == 1                                   # row 17: raw and cal
    lone = dict(rows[0], alpha_phase_cal=None)
    assert A.pair_segments([lone], lone["model_name"], "src", True, True) == []
    assert A.pair_segments(rows, "Stainless Steel", "src", False, False) == []


def test_common_and_distinct_dr():
    assert A.common_dr(_orig()) == PIN_DR["dr"] == 8.14
    assert A.distinct_dr(_orig()) == PIN_DR["all"] == [8.14, 6]
    assert A.distinct_dr(_all()) == PIN_DR_ALL["all"]
    assert A.common_dr([]) is None and PIN_DR_NONE is None
    by_id = {r["id"]: r for r in ROWS}
    tie = [by_id[9], by_id[18]]                              # 6.0 first, one each: first appearance wins
    assert A.distinct_dr(tie) == PIN_DR_TIE["all"] == [6, 8.14] and A.common_dr(tie) == 6
    assert A.common_dr([dict(ROWS[0], r1_mm=None)]) is None
    assert A.common_dr([dict(ROWS[0], r1_mm=9, r2_mm=3)]) is None   # not > 0


def test_log_grid():
    g = A.log_grid(1, 1000)
    assert len(g) == 160 and g[0] == 1
    assert g[159] == pytest.approx(1000, rel=1e-12)
    assert all(b > a for a, b in zip(g, g[1:]))
    assert A.log_grid(2, 8, 3) == pytest.approx([2, 4, 8])


def test_theory_curve():
    ph = A.theory_curve(4.0, 8.14, [261], "Period (s)", "phase")[0]
    assert ph == theoretical_phase(4.0, 8.14, 261) and ph == pytest.approx(0.4465, abs=1e-4)
    lag = A.theory_curve(4.0, 8.14, [261], "Period (s)", "lag")[0]
    assert lag == theoretical_lag_dt(4.0, 8.14, 261)
    assert A.theory_curve(4.0, 8.14, [0, -5, 261], "Period (s)", "phase")[:2] == [None, None]
    fr = A.theory_curve(4.0, 8.14, [1 / 261], "Frequency (Hz)", "phase")[0]
    assert fr == pytest.approx(ph, rel=1e-12)
    assert A.theory_curve(4.0, 8.14, [261], "Temperature (°C)", "phase") == [None]
    assert A.theory_curve(0, 8.14, [261], "Period (s)", "phase") == [None]


def test_corr_matrix_pinned_and_properties():
    for rows, src, want in ((_all(), "src", PIN_CORR), (_all(), "resp", PIN_CORR_RESP), (_orig(), "src", PIN_CORR_ORIG)):
        got = A.corr_matrix(rows, src)
        assert len(got) == 10 and all(len(r) == 10 for r in got)
        for i in range(10):
            for j in range(10):
                assert got[i][j] == pytest.approx(want[i][j], abs=1e-12), (i, j, src)
    got = A.corr_matrix(_all())
    for i in range(10):
        for j in range(10):
            assert got[i][j] == pytest.approx(got[j][i], abs=1e-12)
        assert got[i][i] == pytest.approx(1.0, abs=1e-12)
    assert A.CORR_LABELS == ("A₁", "A₂", "A₁/A₂", "Period", "Δt", "φ", "ln term", "α comb raw", "α phase raw", "T (°C)")


def test_corr_matrix_sparse_column_is_zero():
    rows = _all()[:6]
    for r in rows[1:]:
        r["temperature_c"] = None      # fewer than 3 pairs for T
    got = A.corr_matrix(rows)
    assert got[9][0] == 0 and got[0][9] == 0 and got[9][9] == 0
    assert A.corr_matrix([]) == [[0.0] * 10 for _ in range(10)]


def test_points_in_polygon():
    sq = [(0, 0), (4, 0), (4, 4), (0, 4)]
    assert A.points_in_polygon(2, 2, sq) is True
    assert A.points_in_polygon(5, 2, sq) is False
    assert A.points_in_polygon(-1, 2, sq) is False
    assert A.points_in_polygon(2, 5, sq) is False
    assert A.points_in_polygon(4.5, 4.5, sq) is False
    tri_concave = [(0, 0), (6, 0), (3, 2), (6, 6), (0, 6)]
    assert A.points_in_polygon(1, 3, tri_concave) is True
    assert A.points_in_polygon(5, 2.5, tri_concave) is False
    assert A.points_in_polygon(1, 1, []) is False


def test_summary_rows_and_strings_pinned():
    for rows, want in ((_all(), PIN_SUMMARY_ALL), (_orig(), PIN_SUMMARY_ORIG)):
        got = A.summary_rows(rows)
        assert [s.model for s in got] == [w["model"] for w in want]
        for s, w in zip(got, want):
            assert s.n == w["n"]
            for key, wkey in zip(A.STAT_KEYS, ("combRaw", "phaseRaw", "combCal", "phaseCal")):
                st, ws = s.stats[key], w[wkey]
                if ws["n"] == 0:
                    assert st is None and A.fmt_stat(None, 4) == "—"
                    continue
                assert st[0] == ws["n"]
                assert A.fmt_stat(st[1], 4) == ws["mean"] and A.fmt_stat(st[2], 3) == ws["std"]
                assert A.fmt_stat(st[3], 4) == ws["min"] and A.fmt_stat(st[4], 4) == ws["max"]


def test_summary_csv_character_for_character():
    assert A.summary_csv(_all()) == PIN_CSV_ALL
    assert A.summary_csv(_orig()) == PIN_CSV_ORIG
    assert "\r" not in PIN_CSV_ALL and "—" in PIN_CSV_ALL
    assert PIN_CSV_ALL.split("\n")[0].startswith("Model,N,alpha_comb_raw_mean,alpha_comb_raw_std,")
    assert A.summary_csv([]) == PIN_CSV_ALL.split("\n")[0]


def test_summary_single_value_std_zero():
    one = [r for r in _all() if r["id"] == 10]
    s = A.summary_rows(one)[0]
    assert s.stats["phase_raw"][2] == 0 and A.fmt_stat(0.0, 3) == "0.00"   # JS (0).toPrecision(3); the plan text said 0.000
    assert s.n == 1
