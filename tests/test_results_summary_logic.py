"""Summary logic (Results tab, Task 2). Expected cell texts, CSV and parseFloat results are the output of
the webapp's own DISPLAY_COLS / downloadCSV (app/summary/page.tsx), run with npx tsx on ROW_A / ROW_B."""
from __future__ import annotations

import math

import pytest

from ctwa.ui.results import summary_logic as sl

ROW_A = {"id": 254, "model_name": "Foam, A", "test_date": "17/11/2026", "temperature_c": 766, "gas_atmosphere": "Ar",
         "analysis_mode": "AutoFit", "r1_mm": 6.72, "r2_mm": 14.86, "amplitude_a1": 12.3456, "amplitude_a2": 5.6789,
         "period_t": 600.4, "period_t_resp": 600.45, "frequency_f": 0.001666, "frequency_f_resp": 0.0016655,
         "angular_freq_w": 0.010466, "raw_lag_dt": 105.2, "raw_phase_phi": 0.1835, "ln_term": 0.7123,
         "alpha_combined_raw": 8.5123e-6, "alpha_phase_raw": 9e-6, "use_calibration": True, "system_lag": 98.76,
         "calibration_model": "sqrt:1,2", "calibration_ref_ids": "12,15", "net_lag_dt": 6.44,
         "alpha_combined_cal": 8e-6, "alpha_phase_cal": None}
ROW_B = {"id": 7, "model_name": "Alumina", "test_date": "01/02/2026", "temperature_c": None, "gas_atmosphere": "",
         "analysis_mode": "Manual", "r1_mm": None, "r2_mm": None, "amplitude_a1": None, "amplitude_a2": None,
         "period_t": None, "period_t_resp": None, "frequency_f": None, "frequency_f_resp": None,
         "angular_freq_w": None, "raw_lag_dt": None, "raw_phase_phi": None, "ln_term": None,
         "alpha_combined_raw": 0, "alpha_phase_raw": None, "use_calibration": False, "system_lag": None,
         "calibration_model": None, "calibration_ref_ids": "12", "net_lag_dt": None, "alpha_combined_cal": None,
         "alpha_phase_cal": 1.5e-5}

CELLS_A = {
    'id': '254',
    'model_name': 'Foam, A',
    'test_date': '17/11/2026',
    'temperature_c': '766.0',
    'gas_atmosphere': 'Ar',
    'analysis_mode': 'AutoFit',
    'r1_mm': '6.72',
    'r2_mm': '14.86',
    'amplitude_a1': '12.3456',
    'amplitude_a2': '5.6789',
    'period_t': '600.40',
    'period_t_resp': '600.45',
    'frequency_f': '0.001666',
    'frequency_f_resp': '0.001666',
    'angular_freq_w': '0.01047',
    'raw_lag_dt': '105.20',
    'raw_phase_phi': '0.1835',
    'ln_term': '0.7123',
    'alpha_combined_raw': '8.512',
    'alpha_phase_raw': '9.000',
    'use_calibration': '✓',
    'system_lag': '98.8',
    'calibration_model': '√P',
    'calibration_ref_ids': '2 refs',
    'net_lag_dt': '6.44',
    'alpha_combined_cal': '8.000',
    'alpha_phase_cal': '—',
}
CELLS_B = {
    'id': '7',
    'model_name': 'Alumina',
    'test_date': '01/02/2026',
    'temperature_c': '25.0',
    'gas_atmosphere': '—',
    'analysis_mode': 'Manual',
    'r1_mm': '0.00',
    'r2_mm': '0.00',
    'amplitude_a1': '0.0000',
    'amplitude_a2': '0.0000',
    'period_t': '0.00',
    'period_t_resp': '—',
    'frequency_f': '0.000000',
    'frequency_f_resp': '—',
    'angular_freq_w': '0.00000',
    'raw_lag_dt': '0.00',
    'raw_phase_phi': '0.0000',
    'ln_term': '0.0000',
    'alpha_combined_raw': '—',
    'alpha_phase_raw': '—',
    'use_calibration': '✗',
    'system_lag': '—',
    'calibration_model': '—',
    'calibration_ref_ids': '1 ref',
    'net_lag_dt': '—',
    'alpha_combined_cal': '—',
    'alpha_phase_cal': '15.00',
}
CSV_TS = 'ID,Model,Date,T (°C),Atmosphere,Mode,r₁ (mm),r₂ (mm),A₁ (mW),A₂ (mW),Src Period (s),Resp Period (s),Src f (Hz),Resp f (Hz),ω (rad/s),Δt (s),φ (rad),ln term,α comb (raw),α phase (raw),Cal,Lag (s),Cal source,Refs,Net Δt (s),α comb (cal),α phase (cal)\n254,Foam, A,17/11/2026,766.0,Ar,AutoFit,6.72,14.86,12.3456,5.6789,600.40,600.45,0.001666,0.001666,0.01047,105.20,0.1835,0.7123,8.512,9.000,✓,98.8,√P,2 refs,6.44,8.000,—\n9,Plain,01/02/2026,25.0,—,Manual,0.00,0.00,0.0000,0.0000,0.00,—,0.000000,—,0.00000,0.00,0.0000,0.0000,—,—,✗,—,—,1 ref,—,—,15.00'
LABELS_TS = ['ID', 'Model', 'Date', 'T (°C)', 'Atmosphere', 'Mode', 'r₁ (mm)', 'r₂ (mm)', 'A₁ (mW)', 'A₂ (mW)', 'Src Period (s)', 'Resp Period (s)', 'Src f (Hz)', 'Resp f (Hz)', 'ω (rad/s)', 'Δt (s)', 'φ (rad)', 'ln term', 'α comb (raw)', 'α phase (raw)', 'Cal', 'Lag (s)', 'Cal source', 'Refs', 'Net Δt (s)', 'α comb (cal)', 'α phase (cal)']
PARSE_FLOAT_TS = [['1e-6', 1e-06], ['12abc', 12], ['.5', 0.5], ['', 'NaN'], ['abc', 'NaN'], ['Infinity', 'Infinity'], ['  3.5', 3.5], ['-.5', -0.5], ['+5', 5], ['0x10', 0], ['1.e3', 1000], ['1e', 1], ['-', 'NaN'], ['.', 'NaN'], ['1_000', 1], ['\xa07', 7], ['5 6', 5], ['1e400', 'Infinity'], ['-0', 0]]
AVG_TS = [[[8e-06, 9e-06], '8.500 mm²/s'], [[8e-06, 9e-06, 1.234e-05], '9.780 mm²/s'], [[1e-06, 2e-06, 2e-06], '1.667 mm²/s'], [[3.3333e-07], '0.3333 mm²/s']]


def test_columns():
    cols = sl.SUMMARY_COLS
    assert len(cols) == 27
    assert [c.label for c in cols] == LABELS_TS
    assert [c.key for c in cols][:4] == ["id", "model_name", "test_date", "temperature_c"]
    assert {c.key for c in cols if not c.editable} == {"id", "calibration_model", "calibration_ref_ids"}
    text = {c.key for c in cols if not c.numeric}
    assert text == {"model_name", "test_date", "gas_atmosphere", "analysis_mode", "calibration_model",
                    "calibration_ref_ids", "use_calibration"}


@pytest.mark.parametrize("row,cells", [(ROW_A, CELLS_A), (ROW_B, CELLS_B)])
def test_format_cell_matches_ts(row, cells):
    for key, want in cells.items():
        assert sl.format_cell(key, row) == want, key


def test_format_cell_spec_cases():
    assert sl.format_cell("temperature_c", {"temperature_c": None}) == "25.0"
    assert sl.format_cell("temperature_c", {"temperature_c": 766}) == "766.0"
    assert sl.format_cell("r1_mm", {"r1_mm": 6.72}) == "6.72"
    assert sl.format_cell("r1_mm", {"r1_mm": None}) == "0.00"
    assert sl.format_cell("alpha_phase_raw", {"alpha_phase_raw": 8.5123e-6}) == "8.512"
    assert sl.format_cell("alpha_phase_raw", {"alpha_phase_raw": None}) == "—"
    assert sl.format_cell("alpha_phase_raw", {"alpha_phase_raw": 0}) == "—"
    assert sl.format_cell("use_calibration", {"use_calibration": True}) == "✓"
    assert sl.format_cell("use_calibration", {"use_calibration": False}) == "✗"
    assert sl.format_cell("use_calibration", {}) == "✗"
    for ids, want in (("12,15", "2 refs"), ("12", "1 ref"), ("", "—"), (None, "—"), (" , ", "—")):
        assert sl.format_cell("calibration_ref_ids", {"calibration_ref_ids": ids}) == want
    assert sl.format_cell("calibration_model", {"calibration_model": None}) == "—"
    assert sl.format_cell("period_t_resp", {"period_t_resp": None}) == "—"
    assert sl.format_cell("frequency_f", {"frequency_f": 0.001666}) == "0.001666"
    assert sl.format_cell("model_name", {"model_name": None}) == "—"


def test_presets():
    assert set(sl.PRESETS) == {"key", "cal", "all"} and sl.PRESETS["all"] is None
    assert sl.ALWAYS_SHOWN == {"id", "model_name"}
    for name in ("key", "cal", "all"):
        assert sl.preset_of(set(sl.hidden_for_preset(name))) == name
    hidden = set(sl.hidden_for_preset("key"))
    assert "id" not in hidden and "model_name" not in hidden and "test_date" not in hidden
    assert "r1_mm" in hidden
    hidden.add("test_date")
    assert sl.preset_of(hidden) == "custom"
    assert sl.hidden_for_preset("all") == []
    assert sl.preset_of(set()) == "all"


def test_base_order():
    a = {"id": 1, "test_date": "15/01/2026"}
    b = {"id": 2, "test_date": "01/02/2026"}
    c = {"id": 3, "test_date": "not a date"}
    d = {"id": 4, "test_date": "15/01/2026"}
    assert [r["id"] for r in sl.base_order([a, c, b, d])] == [2, 1, 4, 3]
    assert [r["id"] for r in sl.base_order([d, a])] == [4, 1]
    assert [r["id"] for r in sl.base_order([{"id": 5, "test_date": None}, a])] == [1, 5]
    bad = {"id": 9, "test_date": "01/01/2026", "ln_term": 1, "amplitude_a1": 5.0, "amplitude_a2": 4.0,
           "r1_mm": 6.72, "r2_mm": 14.86, "alpha_combined_raw": 1e-6, "alpha_combined_cal": 2e-6}
    out = sl.base_order([bad])[0]
    assert out["alpha_combined_raw"] is None and out["alpha_combined_cal"] is None
    assert out["ln_term"] < 0
    assert bad["alpha_combined_raw"] == 1e-6 and bad["ln_term"] == 1


def test_filter_rows():
    rows = [
        {"id": 1, "model_name": "Stainless Steel", "analysis_mode": "AutoFit", "use_calibration": True, "temperature_c": 766},
        {"id": 2, "model_name": "Stainless Steel", "analysis_mode": "Manual", "use_calibration": False, "temperature_c": 766},
        {"id": 3, "model_name": "Alumina", "analysis_mode": "AutoFit", "use_calibration": False, "temperature_c": 150},
    ]
    ids = lambda rs: [r["id"] for r in rs]
    assert ids(sl.filter_rows(rows)) == [1, 2, 3]
    assert ids(sl.filter_rows(rows, model="Alumina")) == [3]
    assert ids(sl.filter_rows(rows, model="alumina")) == []
    assert ids(sl.filter_rows(rows, mode="AutoFit")) == [1, 3]
    assert ids(sl.filter_rows(rows, cal="Calibrated Only")) == [1]
    assert ids(sl.filter_rows(rows, cal="Non-Calibrated Only")) == [2, 3]
    assert ids(sl.filter_rows(rows, ids={2, 3})) == [2, 3]
    assert ids(sl.filter_rows(rows, query="steel 766")) == [1, 2]
    assert ids(sl.filter_rows(rows, query="steel 150")) == []
    assert ids(sl.filter_rows(rows, model="Stainless Steel", mode="AutoFit", cal="Calibrated Only", ids={1, 3},
                              query="#1")) == [1]


def test_summary_stats():
    rows = [{"model_name": "A", "alpha_combined_raw": v} for v in (8e-6, 9e-6)] + \
           [{"model_name": "B", "alpha_combined_raw": 0}, {"model_name": "B", "alpha_combined_raw": None}]
    s = sl.summary_stats(rows)
    assert s == {"total": 4, "models": 2, "avg_raw": "8.500 mm²/s", "avg_cal": "—"}
    for vals, want in AVG_TS:
        got = sl.summary_stats([{"model_name": "A", "alpha_combined_cal": v} for v in vals])["avg_cal"]
        assert got == want
    assert sl.summary_stats([]) == {"total": 0, "models": 0, "avg_raw": "—", "avg_cal": "—"}


def test_csv_text_matches_ts():
    row_c = dict(ROW_B, model_name="Plain", id=9)
    got = sl.csv_text([ROW_A, row_c])
    # Differences from the webapp, deliberate: a cell is quoted only when it holds a comma, quote or newline
    want = CSV_TS.replace("254,Foam, A,", '254,"Foam, A",')
    assert got == want
    assert got.split("\n")[0] == ",".join(LABELS_TS)
    assert len(got.split("\n")) == 3 and "\r" not in got


def test_csv_quoting_and_blanks():
    row = dict(ROW_B, model_name='He said "hi"\nbye', test_date=None, analysis_mode=None, id=5)
    lines = sl.csv_text([row]).split("\n", 1)[1]
    assert lines.startswith('5,"He said ""hi""\nbye",,')
    # all 27 columns are written whatever the table shows
    assert len(sl.csv_text([]).split(",")) == 27
    assert sl.csv_text([]) == ",".join(LABELS_TS)


def test_csv_bytes_has_bom():
    assert sl.csv_bytes([ROW_B]).startswith(b"\xef\xbb\xbfID,Model")
    assert sl.csv_bytes([ROW_B])[3:].decode("utf-8") == sl.csv_text([ROW_B])


@pytest.mark.parametrize("text,want", PARSE_FLOAT_TS)
def test_parse_float_js_matches_ts(text, want):
    got = sl.parse_float_js(text)
    if want in ("NaN", "Infinity", "-Infinity"):
        assert got is None
    else:
        assert got == want


def test_parse_float_js_spec():
    assert sl.parse_float_js("1e-6") == 1e-6
    assert sl.parse_float_js("12abc") == 12.0
    assert sl.parse_float_js(".5") == 0.5
    for t in ("", "abc", "Infinity"):
        assert sl.parse_float_js(t) is None


def test_numeric_edit_keys():
    k = sl.NUMERIC_EDIT_KEYS
    assert {"temperature_c", "system_lag", "alpha_phase_cal", "period_t_resp", "frequency_f_resp"} <= k
    assert "use_calibration" not in k and "model_name" not in k and len(k) == 19


def test_build_update():
    stored = {"id": 5, "temperature_c": 766.0, "alpha_combined_raw": 8.5e-6, "model_name": "Foam", "test_date": None,
              "gas_atmosphere": "Ar", "use_calibration": False, "analysis_mode": "Auto", "system_lag": 10.0,
              "graph_image": "x", "extra_data": "y"}
    assert sl.build_update(stored, {}) == {}
    assert sl.build_update(stored, {"temperature_c": "766", "alpha_combined_raw": "8.5e-6", "model_name": "Foam",
                                    "test_date": "", "use_calibration": False}) == {}
    assert sl.build_update(stored, {"temperature_c": "770.5"}) == {"temperature_c": 770.5}
    assert sl.build_update(stored, {"system_lag": ""}) == {"system_lag": None}
    assert sl.build_update(stored, {"system_lag": "abc"}) == {"system_lag": None}
    assert sl.build_update(stored, {"use_calibration": True}) == {"use_calibration": True}
    assert sl.build_update(stored, {"analysis_mode": "AutoFit", "model_name": "Foam 2", "test_date": "01/01/2026"}) == \
        {"analysis_mode": "AutoFit", "model_name": "Foam 2", "test_date": "01/01/2026"}
    assert sl.build_update(stored, {"gas_atmosphere": ""}) == {"gas_atmosphere": ""}
    out = sl.build_update(stored, {"id": "9", "created_at": "z", "graph_image": "g", "extra_data": "e",
                                   "graph_json": "j", "temperature_c": "1"})
    assert out == {"temperature_c": 1.0}
    # a numeric field stored as None stays unchanged when left empty
    assert sl.build_update({"system_lag": None}, {"system_lag": ""}) == {}
    assert sl.build_update({"period_t_resp": None}, {"period_t_resp": "600.5"}) == {"period_t_resp": 600.5}


def test_avg_skips_non_numeric_stored_values():
    rows = [{"model_name": "A", "alpha_combined_raw": "abc"}, {"model_name": "A", "alpha_combined_raw": 8e-6},
            {"model_name": "A", "alpha_combined_raw": [1]}, {"model_name": "A", "alpha_combined_raw": True}]
    assert sl.summary_stats(rows)["avg_raw"] == "8.000 mm²/s"
    assert sl.summary_stats(rows[:1])["avg_raw"] == "—"
