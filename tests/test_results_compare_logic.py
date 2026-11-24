"""Compare logic (Results tab, Task 4). Expected values are the output of the webapp's own code in
app/analyses-viewer/page.tsx (PARAM_ROWS, METRICS, the overlay useMemo, differingRows), copied verbatim into a throwaway
npx tsx script and run on tests/data/results/overlay_fixture.json."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from ctwa.ui.results import compare_logic as cl
from ctwa.ui.results.figure_model import parse_graph

FIXTURE = (Path(__file__).parent / "data" / "results" / "overlay_fixture.json").read_text(encoding="utf-8")

ROW = {"id": 254, "model_name": "Stainless Steel", "test_date": "17/11/2026", "test_time": "10:30", "temperature_c": 766,
       "gas_atmosphere": "Ar", "power_source_device": "K2602B", "power_response_device": "C80", "wave_type": "sine",
       "analysis_mode": "AutoFit", "r1_mm": 6.72, "r2_mm": 14.86, "amplitude_a1": 12.34, "amplitude_a2": 5.67,
       "period_t": 600.4, "period_t_resp": 600.45, "frequency_f": 0.001666, "frequency_f_resp": 0.0016655,
       "angular_freq_w": 0.010466, "raw_lag_dt": 105.2, "raw_phase_phi": 0.1835, "ln_term": 0.7123,
       "alpha_combined_raw": 8.5123e-6, "alpha_phase_raw": 9e-6, "use_calibration": True, "system_lag": 98.76,
       "net_lag_dt": 6.44, "alpha_combined_cal": 8e-6, "alpha_phase_cal": 1.5e-5}
ROW_NONE = {"id": 8, "model_name": "Empty", "test_date": "01/02/2026", "test_time": None, "temperature_c": None,
            "gas_atmosphere": "", "power_source_device": "", "power_response_device": None, "wave_type": None,
            "analysis_mode": "Auto", "r1_mm": None, "r2_mm": None, "amplitude_a1": None, "amplitude_a2": None,
            "period_t": None, "period_t_resp": None, "frequency_f": None, "frequency_f_resp": None,
            "angular_freq_w": None, "raw_lag_dt": None, "raw_phase_phi": None, "ln_term": None,
            "alpha_combined_raw": None, "alpha_phase_raw": 0, "use_calibration": False, "system_lag": None,
            "net_lag_dt": None, "alpha_combined_cal": None, "alpha_phase_cal": 0}

PARAMS_TS = [[('Model', 'Stainless Steel'), ('Test date', '17/11/2026'), ('Test time', '10:30'), ('Temperature (°C)', '766'), ('Gas atmosphere', 'Ar'), ('Power source device', 'K2602B'), ('Power response device', 'C80'), ('Wave type', 'sine'), ('Analysis mode', 'AutoFit'), ('r₁ (mm)', '6.72'), ('r₂ (mm)', '14.86'), ('A₁ (mW)', '12.3400'), ('A₂ (mW)', '5.6700'), ('Src Period (s)', '600.40'), ('Resp Period (s)', '600.45'), ('Src f (Hz)', '0.001666'), ('Resp f (Hz)', '0.001666'), ('ω (rad/s)', '0.01047'), ('Δt (s)', '105.20'), ('φ (rad)', '0.1835'), ('ln term', '0.7123'), ('α Combined raw (mm²/s)', '8.512'), ('α Phase raw (mm²/s)', '9.000'), ('Calibration', '✓'), ('System lag (s)', '98.8'), ('Net Δt (s)', '6.44'), ('α Combined cal (mm²/s)', '8.000'), ('α Phase cal (mm²/s)', '15.00')], [('Model', 'Empty'), ('Test date', '01/02/2026'), ('Test time', '—'), ('Temperature (°C)', '—'), ('Gas atmosphere', '—'), ('Power source device', '—'), ('Power response device', '—'), ('Wave type', '—'), ('Analysis mode', 'Auto'), ('r₁ (mm)', '—'), ('r₂ (mm)', '—'), ('A₁ (mW)', '—'), ('A₂ (mW)', '—'), ('Src Period (s)', '—'), ('Resp Period (s)', '—'), ('Src f (Hz)', '—'), ('Resp f (Hz)', '—'), ('ω (rad/s)', '—'), ('Δt (s)', '—'), ('φ (rad)', '—'), ('ln term', '—'), ('α Combined raw (mm²/s)', '—'), ('α Phase raw (mm²/s)', '—'), ('Calibration', '✗'), ('System lag (s)', '—'), ('Net Δt (s)', '—'), ('α Combined cal (mm²/s)', '—'), ('α Phase cal (mm²/s)', '—')]]
METRIC_KEYS_TS = [['alpha_comb_raw', 'α Combined (raw) (mm²/s)'], ['alpha_phase_raw', 'α Phase (raw) (mm²/s)'], ['alpha_comb_cal', 'α Combined (cal) (mm²/s)'], ['alpha_phase_cal', 'α Phase (cal) (mm²/s)'], ['raw_lag_dt', 'Δt (s)'], ['net_lag_dt', 'Net Δt (s)'], ['raw_phase_phi', 'φ (rad)'], ['ln_term', 'ln term'], ['amplitude_a1', 'A₁ (mW)'], ['amplitude_a2', 'A₂ (mW)'], ['a1_a2', 'A₁/A₂ ratio'], ['period_t', 'Src Period (s)'], ['period_t_resp', 'Resp Period (s)'], ['frequency_f', 'Src f (Hz)'], ['angular_freq_w', 'ω (rad/s)'], ['temperature_c', 'Temperature (°C)'], ['system_lag', 'System lag (s)']]
METRICS_FULL_TS = [8.5123, 9, 8, 15, 105.2, 6.44, 0.1835, 0.7123, 12.34, 5.67, 2.17636684303351, 600.4, 600.45, 0.001666, 0.010466, 766, 98.76]
METRIC_TEXT_TS = [(1234.5, '1235'), (8.5123, '8.512'), (None, '—'), (-1500, '-1500'), (999.96, '1000'), (0, '0.000'), (1e-07, '1.000e-7'), (-0.5, '-0.5000'), (12345.678, '12346')]

# overlay_run output projected the same way for the TS result: traces, shapes (yref defaults to y), the label
# texts of the annotations other than the pinned value box, and that box.
OVERLAY_TS = {
    'default0': {'traces': [['Stainless Steel | 17/11/2026 | 766°C | Ar | AutoFit | A₁=12.3mW | T=600s #254 — Source', [0, 50, 100, 150, 200, 250, 300, 350], [7.5, 11, 12, 9, 3.5, 3, 6, 10.5], '#1F5BB0', 'solid'], ['Stainless Steel | 17/11/2026 | 766°C | Ar | AutoFit | A₁=12.3mW | T=600s #254 — Response', [0, 50, 100, 150, 200, 250, 300, 350], [40, 41.5, 44, 47, 46, 43, 41, 42.5], '#E4572E', 'dash']], 'shapes': [[0, 350, 12, 12, 'y', '#1F5BB0', 'dot'], [0, 350, 3, 3, 'y', '#1F5BB0', 'dot'], [0, 350, 47, 47, 'y', '#E4572E', 'dot'], [0, 350, 43, 43, 'y', '#E4572E', 'dot'], [100, 100, 0, 1, 'paper', '#1F5BB0', 'dashdot'], [300, 300, 0, 1, 'paper', '#1F5BB0', 'dashdot'], [205.20000000000005, 205.20000000000005, 0, 1, 'paper', '#E4572E', 'dashdot']], 'labels': ['  A₁ peak (12.0 mW)', '  A₁ trough (3.0 mW)', '  A₂ peak (47.0 mW)', '  A₂ trough (43.0 mW)', 'Src peak', 'Resp peak (Δt=105s)'], 'box': 'Stainless Steel #254:  Δt=105 s · A₁=12.3 · A₂=5.7 mW'},
    'default1': {'traces': [['Stainless Steel | 17/11/2026 | 766°C | Ar | AutoFit | A₁=12.3mW | T=600s #254 — Source', [0, 50, 100, 150, 200, 250, 300, 350], [7.5, 11, 12, 9, 3.5, 3, 6, 10.5], '#2A9D8F', 'solid'], ['Stainless Steel | 17/11/2026 | 766°C | Ar | AutoFit | A₁=12.3mW | T=600s #254 — Response', [0, 50, 100, 150, 200, 250, 300, 350], [40, 41.5, 44, 47, 46, 43, 41, 42.5], '#E9A23B', 'dash']], 'shapes': [[0, 350, 12, 12, 'y', '#2A9D8F', 'dot'], [0, 350, 3, 3, 'y', '#2A9D8F', 'dot'], [0, 350, 47, 47, 'y', '#E9A23B', 'dot'], [0, 350, 43, 43, 'y', '#E9A23B', 'dot'], [100, 100, 0, 1, 'paper', '#2A9D8F', 'dashdot'], [300, 300, 0, 1, 'paper', '#2A9D8F', 'dashdot'], [205.20000000000005, 205.20000000000005, 0, 1, 'paper', '#E9A23B', 'dashdot']], 'labels': [], 'box': 'Stainless Steel #254:  Δt=105 s · A₁=12.3 · A₂=5.7 mW'},
    'noalign': {'traces': [['Stainless Steel | 17/11/2026 | 766°C | Ar | AutoFit | A₁=12.3mW | T=600s #254 — Source', [1000, 1050, 1100, 1150, 1200, 1250, 1300, 1350], [7.5, 11, 12, 9, 3.5, 3, 6, 10.5], '#1F5BB0', 'solid'], ['Stainless Steel | 17/11/2026 | 766°C | Ar | AutoFit | A₁=12.3mW | T=600s #254 — Response', [1000, 1050, 1100, 1150, 1200, 1250, 1300, 1350], [40, 41.5, 44, 47, 46, 43, 41, 42.5], '#E4572E', 'dash']], 'shapes': [[1000, 1350, 12, 12, 'y', '#1F5BB0', 'dot'], [1000, 1350, 3, 3, 'y', '#1F5BB0', 'dot'], [1000, 1350, 47, 47, 'y', '#E4572E', 'dot'], [1000, 1350, 43, 43, 'y', '#E4572E', 'dot'], [1100, 1100, 0, 1, 'paper', '#1F5BB0', 'dashdot'], [1300, 1300, 0, 1, 'paper', '#1F5BB0', 'dashdot'], [1205.2, 1205.2, 0, 1, 'paper', '#E4572E', 'dashdot']], 'labels': ['  A₁ peak (12.0 mW)', '  A₁ trough (3.0 mW)', '  A₂ peak (47.0 mW)', '  A₂ trough (43.0 mW)', 'Src peak', 'Resp peak (Δt=105s)'], 'box': 'Stainless Steel #254:  Δt=105 s · A₁=12.3 · A₂=5.7 mW'},
    'normamp': {'traces': [['Stainless Steel | 17/11/2026 | 766°C | Ar | AutoFit | A₁=12.3mW | T=600s #254 — Source', [0, 50, 100, 150, 200, 250, 300, 350], [0.5, 0.8888888888888888, 1, 0.6666666666666666, 0.05555555555555555, 0, 0.3333333333333333, 0.8333333333333334], '#1F5BB0', 'solid'], ['Stainless Steel | 17/11/2026 | 766°C | Ar | AutoFit | A₁=12.3mW | T=600s #254 — Response', [0, 50, 100, 150, 200, 250, 300, 350], [0, 0.21428571428571427, 0.5714285714285714, 1, 0.8571428571428571, 0.42857142857142855, 0.14285714285714285, 0.35714285714285715], '#E4572E', 'dash']], 'shapes': [], 'labels': [], 'box': 'Stainless Steel #254:  Δt=105 s · A₁=12.3 · A₂=5.7 mW'},
    'normtime': {'traces': [['Stainless Steel | 17/11/2026 | 766°C | Ar | AutoFit | A₁=12.3mW | T=600s #254 — Source', [0, 0.14285714285714285, 0.2857142857142857, 0.42857142857142855, 0.5714285714285714, 0.7142857142857143, 0.8571428571428571, 1], [7.5, 11, 12, 9, 3.5, 3, 6, 10.5], '#1F5BB0', 'solid'], ['Stainless Steel | 17/11/2026 | 766°C | Ar | AutoFit | A₁=12.3mW | T=600s #254 — Response', [0, 0.14285714285714285, 0.2857142857142857, 0.42857142857142855, 0.5714285714285714, 0.7142857142857143, 0.8571428571428571, 1], [40, 41.5, 44, 47, 46, 43, 41, 42.5], '#E4572E', 'dash']], 'shapes': [[0, 1, 12, 12, 'y', '#1F5BB0', 'dot'], [0, 1, 3, 3, 'y', '#1F5BB0', 'dot'], [0, 1, 47, 47, 'y', '#E4572E', 'dot'], [0, 1, 43, 43, 'y', '#E4572E', 'dot'], [0.2857142857142857, 0.2857142857142857, 0, 1, 'paper', '#1F5BB0', 'dashdot'], [0.8571428571428571, 0.8571428571428571, 0, 1, 'paper', '#1F5BB0', 'dashdot'], [0.5862857142857144, 0.5862857142857144, 0, 1, 'paper', '#E4572E', 'dashdot']], 'labels': ['  A₁ peak (12.0 mW)', '  A₁ trough (3.0 mW)', '  A₂ peak (47.0 mW)', '  A₂ trough (43.0 mW)', 'Src peak', 'Resp peak (Δt=105s)'], 'box': 'Stainless Steel #254:  Δt=105 s · A₁=12.3 · A₂=5.7 mW'},
    'normtime_noalign': {'traces': [['Stainless Steel | 17/11/2026 | 766°C | Ar | AutoFit | A₁=12.3mW | T=600s #254 — Source', [0, 0.14285714285714285, 0.2857142857142857, 0.42857142857142855, 0.5714285714285714, 0.7142857142857143, 0.8571428571428571, 1], [7.5, 11, 12, 9, 3.5, 3, 6, 10.5], '#1F5BB0', 'solid'], ['Stainless Steel | 17/11/2026 | 766°C | Ar | AutoFit | A₁=12.3mW | T=600s #254 — Response', [0, 0.14285714285714285, 0.2857142857142857, 0.42857142857142855, 0.5714285714285714, 0.7142857142857143, 0.8571428571428571, 1], [40, 41.5, 44, 47, 46, 43, 41, 42.5], '#E4572E', 'dash']], 'shapes': [[0, 1, 12, 12, 'y', '#1F5BB0', 'dot'], [0, 1, 3, 3, 'y', '#1F5BB0', 'dot'], [0, 1, 47, 47, 'y', '#E4572E', 'dot'], [0, 1, 43, 43, 'y', '#E4572E', 'dot'], [0.2857142857142857, 0.2857142857142857, 0, 1, 'paper', '#1F5BB0', 'dashdot'], [0.8571428571428571, 0.8571428571428571, 0, 1, 'paper', '#1F5BB0', 'dashdot'], [0.5862857142857144, 0.5862857142857144, 0, 1, 'paper', '#E4572E', 'dashdot']], 'labels': ['  A₁ peak (12.0 mW)', '  A₁ trough (3.0 mW)', '  A₂ peak (47.0 mW)', '  A₂ trough (43.0 mW)', 'Src peak', 'Resp peak (Δt=105s)'], 'box': 'Stainless Steel #254:  Δt=105 s · A₁=12.3 · A₂=5.7 mW'},
    'source1': {'traces': [['Stainless Steel | 17/11/2026 | 766°C | Ar | AutoFit | A₁=12.3mW | T=600s #254 — Source', [0, 50, 100, 150, 200, 250, 300, 350], [7.5, 11, 12, 9, 3.5, 3, 6, 10.5], '#2A9D8F', 'solid']], 'shapes': [[0, 350, 12, 12, 'y', '#2A9D8F', 'dot'], [0, 350, 3, 3, 'y', '#2A9D8F', 'dot'], [100, 100, 0, 1, 'paper', '#2A9D8F', 'dashdot'], [300, 300, 0, 1, 'paper', '#2A9D8F', 'dashdot']], 'labels': [], 'box': 'Stainless Steel #254:  Δt=105 s · A₁=12.3 · A₂=5.7 mW'},
    'response0': {'traces': [['Stainless Steel | 17/11/2026 | 766°C | Ar | AutoFit | A₁=12.3mW | T=600s #254 — Response', [0, 50, 100, 150, 200, 250, 300, 350], [40, 41.5, 44, 47, 46, 43, 41, 42.5], '#E4572E', 'dash']], 'shapes': [[0, 350, 47, 47, 'y', '#E4572E', 'dot'], [0, 350, 43, 43, 'y', '#E4572E', 'dot'], [205.20000000000005, 205.20000000000005, 0, 1, 'paper', '#E4572E', 'dashdot']], 'labels': ['  A₂ peak (47.0 mW)', '  A₂ trough (43.0 mW)', 'Resp peak (Δt=105s)'], 'box': 'Stainless Steel #254:  Δt=105 s · A₁=12.3 · A₂=5.7 mW'},
    'noguides': {'traces': [['Stainless Steel | 17/11/2026 | 766°C | Ar | AutoFit | A₁=12.3mW | T=600s #254 — Source', [0, 50, 100, 150, 200, 250, 300, 350], [7.5, 11, 12, 9, 3.5, 3, 6, 10.5], '#1F5BB0', 'solid'], ['Stainless Steel | 17/11/2026 | 766°C | Ar | AutoFit | A₁=12.3mW | T=600s #254 — Response', [0, 50, 100, 150, 200, 250, 300, 350], [40, 41.5, 44, 47, 46, 43, 41, 42.5], '#E4572E', 'dash']], 'shapes': [], 'labels': [], 'box': None},
    'run3': {'traces': [['Empty | 01/02/2026 | Auto #8 — Source', [0, 50, 100, 150, 200, 250, 300, 350], [7.5, 11, 12, 9, 3.5, 3, 6, 10.5], '#16A085', 'solid'], ['Empty | 01/02/2026 | Auto #8 — Response', [0, 50, 100, 150, 200, 250, 300, 350], [40, 41.5, 44, 47, 46, 43, 41, 42.5], '#D35D9B', 'dash']], 'shapes': [[0, 350, 12, 12, 'y', '#16A085', 'dot'], [0, 350, 3, 3, 'y', '#16A085', 'dot'], [0, 350, 47, 47, 'y', '#D35D9B', 'dot'], [0, 350, 43, 43, 'y', '#D35D9B', 'dot'], [100, 100, 0, 1, 'paper', '#16A085', 'dashdot'], [300, 300, 0, 1, 'paper', '#16A085', 'dashdot'], [205.20000000000005, 205.20000000000005, 0, 1, 'paper', '#D35D9B', 'dashdot']], 'labels': [], 'box': 'Empty #8:  Δt=— s · A₁=— · A₂=— mW'},
}


def _case(name, row, index, **opts):
    run = cl.overlay_run(row, FIXTURE, index, cl.OverlayOptions(**opts))
    assert run is not None
    return run


def _check(run, case):
    want = OVERLAY_TS[case]
    assert [t.name for t in run.traces] == [t[0] for t in want["traces"]]
    for got, (_, x, y, color, dash) in zip(run.traces, want["traces"]):
        assert got.x == pytest.approx(x, rel=1e-12, abs=1e-12) and got.y == pytest.approx(y, rel=1e-12, abs=1e-12)
        assert (got.color, got.dash) == (color, dash)
    assert len(run.lines) == len(want["shapes"])
    for got, (x0, x1, y0, y1, yref, color, dash) in zip(run.lines, want["shapes"]):
        assert [got.x0, got.x1, got.y0, got.y1] == pytest.approx([x0, x1, y0, y1], rel=1e-12, abs=1e-12)
        assert (got.yref, got.color, got.dash) == (yref, color, dash)
    assert [ln.label for ln in run.lines if ln.label is not None] == want["labels"]
    assert run.box_text == want["box"]


def test_constants():
    assert cl.MAX_RUNS == 4
    assert len(cl.COMPARE_COLORS) == 10 and cl.COMPARE_COLORS[0] == "#1F5BB0" and cl.COMPARE_COLORS[9] == "#C0392B"
    assert cl.run_colors(0) == ("#1F5BB0", "#E4572E")
    assert cl.run_colors(1) == ("#2A9D8F", "#E9A23B")
    assert cl.run_colors(5) == (cl.COMPARE_COLORS[0], cl.COMPARE_COLORS[1])      # wraps at 10


def test_param_rows_and_values_match_ts():
    assert len(cl.PARAM_ROWS) == 28 == len(PARAMS_TS[0])
    assert [label for label, _ in cl.PARAM_ROWS] == [p[0] for p in PARAMS_TS[0]]
    for row, want in ((ROW, PARAMS_TS[0]), (ROW_NONE, PARAMS_TS[1])):
        for label, text in want:
            assert cl.param_value(label, row) == text, label


def test_param_value_spec_cases():
    assert cl.param_value("Temperature (°C)", {"temperature_c": None}) == "—"
    assert cl.param_value("A₁ (mW)", {"amplitude_a1": None}) == "—"
    assert cl.param_value("Calibration", {"use_calibration": False}) == "✗"
    assert cl.param_value("α Phase raw (mm²/s)", {"alpha_phase_raw": 0}) == "—"
    assert cl.param_value("A₁ (mW)", {"amplitude_a1": math.inf}) == "—"
    assert cl.param_value("Temperature (°C)", {"temperature_c": 25.5}) == "25.5"


def test_metrics_match_ts():
    assert len(cl.METRICS) == 17
    assert [(k, label) for k, label, _ in cl.METRICS] == [tuple(m) for m in METRIC_KEYS_TS]
    for (key, _), want in zip(METRIC_KEYS_TS, METRICS_FULL_TS):
        got = cl.metric_value(key, ROW)
        assert got == pytest.approx(want, rel=1e-12), key


def test_metric_value_spec_cases():
    assert cl.metric_value("a1_a2", ROW) == 12.34 / 5.67
    assert cl.metric_value("a1_a2", dict(ROW, amplitude_a2=0)) is None
    assert cl.metric_value("alpha_phase_raw", {"alpha_phase_raw": 8.5e-6}) == 8.5
    assert cl.metric_value("alpha_phase_raw", {"alpha_phase_raw": 0}) is None
    assert cl.metric_value("alpha_comb_raw", {"alpha_combined_raw": None}) is None
    assert cl.metric_value("alpha_comb_raw", {"alpha_combined_raw": 1e-5}) == 10
    assert cl.metric_value("net_lag_dt", {}) is None
    assert cl.metric_value("raw_lag_dt", {"raw_lag_dt": None}) is None
    # JS: null/null is NaN and 12/null is Infinity (the webapp only guards against a literal 0)
    assert math.isnan(cl.metric_value("a1_a2", ROW_NONE))
    assert cl.metric_value("a1_a2", dict(ROW, amplitude_a2=None)) == math.inf


def test_metric_text_matches_ts():
    for v, want in METRIC_TEXT_TS:
        assert cl.metric_text(v) == want, v
    assert cl.metric_text(1234.5) == "1235" and cl.metric_text(8.5123) == "8.512"
    assert cl.metric_text(None) == "—" and cl.metric_text(-1500) == "-1500"


def test_differing_rows():
    a = dict(ROW)
    b = dict(ROW, temperature_c=800, alpha_phase_raw=1e-5)
    assert cl.differing_rows([a, b]) == {"Temperature (°C)", "α Phase raw (mm²/s)"}
    assert cl.differing_rows([a]) == set() and cl.differing_rows([]) == set()
    assert "Model" not in cl.differing_rows([a, dict(b, id=9)])
    assert cl.differing_rows([a, dict(a, model_name="Other")]) == {"Model"}
    assert cl.differing_rows([a, dict(a), dict(a, gas_atmosphere="Air")]) == {"Gas atmosphere"}


def test_overlay_defaults_match_ts():
    _check(_case("d0", ROW, 0), "default0")
    _check(_case("d1", ROW, 1), "default1")
    _check(_case("d3", ROW_NONE, 3), "run3")


def test_overlay_names_colors_and_shift():
    run = _case("d0", ROW, 0)
    from ctwa.ui.results.fmt import label_of
    assert [t.name for t in run.traces] == [label_of(ROW) + " — Source", label_of(ROW) + " — Response"]
    assert (run.traces[0].color, run.traces[0].dash) == ("#1F5BB0", "solid")
    assert (run.traces[1].color, run.traces[1].dash) == ("#E4572E", "dash")
    assert run.traces[0].x[0] == 0 and run.traces[1].x[0] == 0 and run.traces[0].x[-1] == 350


def test_overlay_options_match_ts():
    _check(_case("a", ROW, 0, align=False), "noalign")
    _check(_case("b", ROW, 0, norm_amp=True), "normamp")
    _check(_case("c", ROW, 0, norm_time=True), "normtime")
    _check(_case("c2", ROW, 0, norm_time=True, align=False), "normtime_noalign")
    _check(_case("d", ROW, 1, signal="source"), "source1")
    _check(_case("e", ROW, 0, signal="response"), "response0")
    _check(_case("f", ROW, 0, guides=False), "noguides")


def test_norm_amp_details():
    run = _case("b", ROW, 0, norm_amp=True)
    for tr in run.traces:
        assert min(tr.y) == 0 and max(tr.y) == 1
    assert run.lines == []
    const = {"data": [{"name": "Source", "x": [0, 1, 2], "y": [5, 5, 5]}], "layout": {}}
    r = cl.overlay_run(ROW, json.dumps(const), 0, cl.OverlayOptions(norm_amp=True))
    assert r.traces[0].y == [0, 0, 0]
    # a single point: span falls back to 1
    one = {"data": [{"name": "Source", "x": [7], "y": [5]}], "layout": {}}
    r = cl.overlay_run(ROW, json.dumps(one), 0, cl.OverlayOptions(norm_time=True))
    assert r.traces[0].x == [0]


def test_guides_spec_cases():
    run = _case("d0", ROW, 0)
    levels = [ln for ln in run.lines if ln.dash == "dot"]
    assert [(ln.y0, ln.y1, ln.x0, ln.x1, ln.yref) for ln in levels] == [(12.0, 12.0, 0, 350, "y"), (3.0, 3.0, 0, 350, "y"),
                                                                       (47.0, 47.0, 0, 350, "y"), (43.0, 43.0, 0, 350, "y")]
    assert [ln.label for ln in levels] == ["  A₁ peak (12.0 mW)", "  A₁ trough (3.0 mW)", "  A₂ peak (47.0 mW)",
                                           "  A₂ trough (43.0 mW)"]
    marks = [ln for ln in run.lines if ln.dash == "dashdot"]
    assert [(ln.yref, ln.y0, ln.y1, ln.x0 == ln.x1) for ln in marks] == [("paper", 0, 1, True)] * 3
    assert [ln.label for ln in marks] == ["Src peak", None, "Resp peak (Δt=105s)"]
    assert {ln.color for ln in run.lines[:2] + marks[:2]} == {"#1F5BB0"}
    other = _case("d1", ROW, 1)
    assert all(ln.label is None for ln in other.lines) and len(other.lines) == 7
    # the stored colours (#27ae60, #f39c12, ...) never leak through
    assert {ln.color for ln in other.lines} == {"#2A9D8F", "#E9A23B"}
    assert run.box_text == "Stainless Steel #254:  Δt=105 s · A₁=12.3 · A₂=5.7 mW"
    assert _case("n", ROW_NONE, 0).box_text == "Empty #8:  Δt=— s · A₁=— · A₂=— mW"


def test_guide_levels():
    fig = parse_graph(FIXTURE)
    src_l, resp_l, src_m, resp_m = cl.guide_levels(fig)
    assert src_l == [3.0, 12.0] and resp_l == [43.0, 47.0]
    assert src_m == [1100.0, 1300.0] and resp_m == [1205.2]       # grey, rect and mean lines are ignored


def test_old_colours_and_case_insensitive():
    d = json.loads(FIXTURE)
    for s in d["layout"]["shapes"]:
        c = s.get("line", {}).get("color", "")
        s.setdefault("line", {})["color"] = {"#1F5BB0": "#3498db", "#E4572E": "#E74C3C"}.get(c, c)
    fig = parse_graph(json.dumps(d))
    _, _, src_m, resp_m = cl.guide_levels(fig)
    assert src_m == [1100.0, 1300.0] and resp_m == [1205.2]


def test_no_waveform():
    d = json.loads(FIXTURE)
    only_other = {"data": [dict(d["data"][0], name="Other")], "layout": {}}
    for raw in (None, "", "iVBORw0KGgoAAAANSUhEUg" * 2, "{", "{}", '{"data":5}', json.dumps(only_other),
                json.dumps({"data": [{"type": "bar", "name": "Source", "x": ["a"], "y": [1]}]})):
        assert cl.overlay_run(ROW, raw, 0, cl.OverlayOptions()) is None
    import base64
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 40).decode()
    assert cl.overlay_run(ROW, png, 0, cl.OverlayOptions()) is None


def test_options_defaults():
    o = cl.OverlayOptions()
    assert (o.signal, o.align, o.norm_amp, o.norm_time, o.guides) == ("both", True, False, False, True)
