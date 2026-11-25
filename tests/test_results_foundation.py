"""Results foundation (Plan 2.5): column metadata, display helpers, ResultsStore, ResultsLoader.
Offscreen Qt, fake client, no network."""
from __future__ import annotations

import math
import os
import threading
import time
from datetime import date

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ctwa.cloud.client import NotLoggedIn, Offline, ServerError  # noqa: E402
from ctwa.results import columns, helpers  # noqa: E402
from ctwa.results.store import ResultsStore  # noqa: E402

# ---- pinned from the webapp with a throwaway `npx tsx` script (lib/utils.ts, RunLabel.tsx,
# materialColors.ts, analysisColumns.ts and the Summary page's search) ----

ALPHA_TS = [('null', '—'),
 ('undefined', '—'),
 ('0', '—'),
 ('NaN', 'NaN'),
 ('0.000001234', '1.234'),
 ('0.000008', '8.000'),
 ('-0.0000025', '-2.500'),
 ('0.000004', '4.000'),
 ('1e-12', '0.000001000'),
 ('0.000123456', '123.5'),
 ('0.00000999995', '10.00'),
 ('Infinity', 'Infinity'),
 ('0.00004', '40.00')]

DATE_TS = [('05/03/2025', [2025, 3, 5]),
 ('5/3/25', [1925, 3, 5]),
 ('31/02/2025', [2025, 3, 3]),
 ('01/13/2024', [2025, 1, 1]),
 ('', [1970, 1, 1]),
 ('abc', [1970, 1, 1]),
 ('1/2', [1970, 1, 1]),
 ('1/2/3/4', [1970, 1, 1]),
 ('00/00/0000', [1899, 11, 30]),
 (' 7 / 8 / 2020', [2020, 8, 7]),
 ('29/02/2024', [2024, 2, 29]),
 ('15/06/0099', [1999, 6, 15]),
 ('15/06/100', [100, 6, 15]),
 ('1.5/2/2024', [2024, 2, 1]),
 ('10/10/1e3', [1000, 10, 10]),
 ('x/1/2020', None),
 ('0x10/1/2020', [2020, 1, 16]),
 ('31/12/1999', [1999, 12, 31]),
 ('1/1/-5', [-5, 1, 1]),
 ('1/1/10000', [10000, 1, 1])]

RUN_TS = ['Stainless Steel · 766 °C · 600 s · #254',
 'Abs · #1',
 'Al₂O₃ · 25.5 °C · 1 s · #2',
 ' · 0 °C · #3',
 ' · 2 s · #4',
 'unk foam · 800.25 °C · 0 s · #5',
 'x · 1e+21 °C · 3 s · #6',
 'x · 1e-7 °C · #7',
 'עברית · -3 °C · 4 s · #8']

COLOR_TS = [('Stainless Steel', '#1F5BB0'),
 ('  stainless steel ', '#1F5BB0'),
 ('Al₂O₃', '#E4572E'),
 ('al2o3', '#E4572E'),
 ('Alumina', '#E4572E'),
 ('unk foam', '#2A9D8F'),
 ('UNK FIBER', '#8E44AD'),
 ('', '#7F8C8D'),
 ('null', '#7F8C8D'),
 ('undefined', '#7F8C8D'),
 ('   ', '#7F8C8D'),
 ('Copper', '#8E44AD'),
 ('Zirconia', '#E4572E'),
 ('Ti-6Al-4V', '#C0392B'),
 ('עברית', '#C0392B'),
 ('İstanbul', '#16A085'),
 ('ΑΣ', '#3BA3D9'),
 ('Mullite 3:2', '#16A085'),
 ('x', '#1F5BB0'),
 ('Alumina-Mullite', '#2A9D8F')]

SEARCH_TS = [('base', '', True),
 ('base', '   ', True),
 ('base', 'steel 766', True),
 ('base', '#254', True),
 ('base', 'STEEL', True),
 ('base', 'steel 800', False),
 ('base', 'ar', True),
 ('base', '2602b c80', True),
 ('base', '05/03', True),
 ('base', '766.0', False),
 ('base', 'null', False),
 ('base', '\xa0steel', True),
 ('base', 'steel\u2003766', True),
 ('base', '##', True),
 ('base', '#2 54', True),
 ('base', 'sine ar', True),
 ('base', 'stainless  steel\t766', True),
 ('base', 'zzz', False),
 ('base', '\u200bsteel', False),
 ('heb', 'עברית', True),
 ('heb', 'קרמיקה 25.5', True),
 ('heb', 'עברית 800', False),
 ('heb', 'null', False),
 ('heb', 'square', True),
 ('istanbul', 'i̇stanbul', True),
 ('istanbul', 'İSTANBUL', True),
 ('sigma', 'οδος', True),
 ('sigma', 'οδοσ', False),
 ('sigma', 'ΟΔΟΣ', True)]

LN_TS = [({'amplitude_a1': 10,
   'amplitude_a2': 8,
   'r1_mm': 6.72,
   'r2_mm': 14.86,
   'alpha_combined_raw': 3e-06,
   'alpha_combined_cal': 4e-06,
   'id': 1,
   'ln_term': 1},
  {'amplitude_a1': 10,
   'amplitude_a2': 8,
   'r1_mm': 6.72,
   'r2_mm': 14.86,
   'alpha_combined_raw': None,
   'alpha_combined_cal': None,
   'id': 1,
   'ln_term': -0.17364889106306775}),
 ({'amplitude_a1': 10,
   'amplitude_a2': 8,
   'r1_mm': 6.72,
   'r2_mm': 14.86,
   'alpha_combined_raw': 3e-06,
   'alpha_combined_cal': 4e-06,
   'id': 1,
   'ln_term': 0.5},
  {'amplitude_a1': 10,
   'amplitude_a2': 8,
   'r1_mm': 6.72,
   'r2_mm': 14.86,
   'alpha_combined_raw': 3e-06,
   'alpha_combined_cal': 4e-06,
   'id': 1,
   'ln_term': 0.5}),
 ({'amplitude_a1': 10,
   'amplitude_a2': 8,
   'r1_mm': 6.72,
   'r2_mm': 14.86,
   'alpha_combined_raw': 3e-06,
   'alpha_combined_cal': 4e-06,
   'id': 1,
   'ln_term': None},
  {'amplitude_a1': 10,
   'amplitude_a2': 8,
   'r1_mm': 6.72,
   'r2_mm': 14.86,
   'alpha_combined_raw': None,
   'alpha_combined_cal': None,
   'id': 1,
   'ln_term': -0.17364889106306775}),
 ({'amplitude_a1': 10,
   'amplitude_a2': 8,
   'r1_mm': 6.72,
   'r2_mm': 14.86,
   'alpha_combined_raw': 3e-06,
   'alpha_combined_cal': 4e-06,
   'id': 1},
  {'amplitude_a1': 10,
   'amplitude_a2': 8,
   'r1_mm': 6.72,
   'r2_mm': 14.86,
   'alpha_combined_raw': None,
   'alpha_combined_cal': None,
   'id': 1,
   'ln_term': -0.17364889106306775}),
 ({'amplitude_a1': 10,
   'amplitude_a2': 8,
   'r1_mm': 6.72,
   'r2_mm': 14.86,
   'alpha_combined_raw': 3e-06,
   'alpha_combined_cal': 4e-06,
   'id': 1,
   'ln_term': -0.2},
  {'amplitude_a1': 10,
   'amplitude_a2': 8,
   'r1_mm': 6.72,
   'r2_mm': 14.86,
   'alpha_combined_raw': None,
   'alpha_combined_cal': None,
   'id': 1,
   'ln_term': -0.17364889106306775}),
 ({'amplitude_a1': 10,
   'amplitude_a2': 8,
   'r1_mm': 6.72,
   'r2_mm': 14.86,
   'alpha_combined_raw': 3e-06,
   'alpha_combined_cal': 4e-06,
   'id': 1,
   'ln_term': 0},
  {'amplitude_a1': 10,
   'amplitude_a2': 8,
   'r1_mm': 6.72,
   'r2_mm': 14.86,
   'alpha_combined_raw': None,
   'alpha_combined_cal': None,
   'id': 1,
   'ln_term': -0.17364889106306775}),
 ({'amplitude_a1': 100,
   'amplitude_a2': 20,
   'r1_mm': 6.72,
   'r2_mm': 14.86,
   'alpha_combined_raw': 3e-06,
   'alpha_combined_cal': 4e-06,
   'id': 1,
   'ln_term': 1},
  {'amplitude_a1': 100,
   'amplitude_a2': 20,
   'r1_mm': 6.72,
   'r2_mm': 14.86,
   'alpha_combined_raw': 3e-06,
   'alpha_combined_cal': 4e-06,
   'id': 1,
   'ln_term': 1}),
 ({'amplitude_a1': 100,
   'amplitude_a2': 20,
   'r1_mm': 6.72,
   'r2_mm': 14.86,
   'alpha_combined_raw': 3e-06,
   'alpha_combined_cal': 4e-06,
   'id': 1,
   'ln_term': None},
  {'amplitude_a1': 100,
   'amplitude_a2': 20,
   'r1_mm': 6.72,
   'r2_mm': 14.86,
   'alpha_combined_raw': 3e-06,
   'alpha_combined_cal': 4e-06,
   'id': 1,
   'ln_term': None}),
 ({'amplitude_a1': 100,
   'amplitude_a2': 20,
   'r1_mm': 6.72,
   'r2_mm': 14.86,
   'alpha_combined_raw': 3e-06,
   'alpha_combined_cal': 4e-06,
   'id': 1,
   'ln_term': 0},
  {'amplitude_a1': 100,
   'amplitude_a2': 20,
   'r1_mm': 6.72,
   'r2_mm': 14.86,
   'alpha_combined_raw': 3e-06,
   'alpha_combined_cal': 4e-06,
   'id': 1,
   'ln_term': 0}),
 ({'amplitude_a1': 100,
   'amplitude_a2': 20,
   'r1_mm': 6.72,
   'r2_mm': 14.86,
   'alpha_combined_raw': 3e-06,
   'alpha_combined_cal': 4e-06,
   'id': 1,
   'ln_term': 1.7},
  {'amplitude_a1': 100,
   'amplitude_a2': 20,
   'r1_mm': 6.72,
   'r2_mm': 14.86,
   'alpha_combined_raw': 3e-06,
   'alpha_combined_cal': 4e-06,
   'id': 1,
   'ln_term': 1.7}),
 ({'amplitude_a1': 10,
   'amplitude_a2': 0,
   'r1_mm': 6.72,
   'r2_mm': 14.86,
   'alpha_combined_raw': 3e-06,
   'alpha_combined_cal': 4e-06,
   'id': 1,
   'ln_term': 1},
  {'amplitude_a1': 10,
   'amplitude_a2': 0,
   'r1_mm': 6.72,
   'r2_mm': 14.86,
   'alpha_combined_raw': 3e-06,
   'alpha_combined_cal': 4e-06,
   'id': 1,
   'ln_term': 1}),
 ({'amplitude_a1': None,
   'amplitude_a2': 8,
   'r1_mm': 6.72,
   'r2_mm': 14.86,
   'alpha_combined_raw': 3e-06,
   'alpha_combined_cal': 4e-06,
   'id': 1,
   'ln_term': 1},
  {'amplitude_a1': None,
   'amplitude_a2': 8,
   'r1_mm': 6.72,
   'r2_mm': 14.86,
   'alpha_combined_raw': 3e-06,
   'alpha_combined_cal': 4e-06,
   'id': 1,
   'ln_term': 1}),
 ({'amplitude_a1': 10,
   'amplitude_a2': 8,
   'r2_mm': 14.86,
   'alpha_combined_raw': 3e-06,
   'alpha_combined_cal': 4e-06,
   'id': 1,
   'ln_term': 1},
  {'amplitude_a1': 10,
   'amplitude_a2': 8,
   'r2_mm': 14.86,
   'alpha_combined_raw': 3e-06,
   'alpha_combined_cal': 4e-06,
   'id': 1,
   'ln_term': 1}),
 ({'amplitude_a1': 8,
   'amplitude_a2': 8,
   'r1_mm': 14.86,
   'r2_mm': 14.86,
   'alpha_combined_raw': 3e-06,
   'alpha_combined_cal': 4e-06,
   'id': 1,
   'ln_term': 1},
  {'amplitude_a1': 8,
   'amplitude_a2': 8,
   'r1_mm': 14.86,
   'r2_mm': 14.86,
   'alpha_combined_raw': None,
   'alpha_combined_cal': None,
   'id': 1,
   'ln_term': 0}),
 ({'amplitude_a1': 20,
   'amplitude_a2': 20,
   'r1_mm': 6.72,
   'r2_mm': 6.72,
   'alpha_combined_raw': 3e-06,
   'alpha_combined_cal': 4e-06,
   'id': 1,
   'ln_term': 1},
  {'amplitude_a1': 20,
   'amplitude_a2': 20,
   'r1_mm': 6.72,
   'r2_mm': 6.72,
   'alpha_combined_raw': None,
   'alpha_combined_cal': None,
   'id': 1,
   'ln_term': 0})]


LIST_COLUMNS_TS = (
    "id,"
    "created_at,"
    "model_name,"
    "test_date,"
    "test_time,"
    "c80_filename,"
    "keithley_filename,"
    "r1_mm,"
    "r2_mm,"
    "t_cal,"
    "t_src,"
    "c80_time_unit,"
    "c80_pwr_unit,"
    "src_time_unit,"
    "src_pwr_unit,"
    "analysis_mode,"
    "use_calibration,"
    "system_lag,"
    "t_min,"
    "t_max,"
    "amplitude_a1,"
    "amplitude_a2,"
    "period_t,"
    "frequency_f,"
    "angular_freq_w,"
    "raw_lag_dt,"
    "raw_phase_phi,"
    "ln_term,"
    "alpha_combined_raw,"
    "alpha_combined_cal,"
    "alpha_phase_raw,"
    "alpha_phase_cal,"
    "net_lag_dt,"
    "net_phase_phi,"
    "temperature_c,"
    "power_source_device,"
    "power_response_device,"
    "wave_type,"
    "period_t_resp,"
    "frequency_f_resp,"
    "gas_atmosphere,"
    "is_reference,"
    "reference_alpha_mm2s,"
    "calibrated_from_id,"
    "calibration_ref_ids,"
    "calibration_model")

# ---- test inputs that mirror the TS script ----

RUN_ROWS = [
    {"id": 254, "model_name": "Stainless Steel", "temperature_c": 766, "period_t": 600.4},
    {"id": 1, "model_name": "Abs", "temperature_c": None, "period_t": None},
    {"id": 2, "model_name": "Al₂O₃", "temperature_c": 25.5, "period_t": 0.5},
    {"id": 3, "model_name": "", "temperature_c": 0, "period_t": math.nan},
    {"id": 4, "model_name": None, "period_t": 1.5},
    {"id": 5, "model_name": "unk foam", "temperature_c": 800.25, "period_t": -0.5},
    {"id": 6, "model_name": "x", "temperature_c": 1e21, "period_t": 2.5},
    {"id": 7, "model_name": "x", "temperature_c": 1e-7, "period_t": math.inf},
    {"id": 8, "model_name": "עברית", "temperature_c": -3, "period_t": 3.5},
]
ALPHA_IN = [None, None, 0, math.nan, 1.234e-6, 8.0e-6, -2.5e-6, 4.0e-6, 1e-12, 123.456e-6, 9.99995e-6,
            math.inf, 0.00004]
COLOR_IN = ["Stainless Steel", "  stainless steel ", "Al₂O₃", "al2o3", "Alumina", "unk foam", "UNK FIBER",
            "", None, None, "   ", "Copper", "Zirconia", "Ti-6Al-4V", "עברית", "İstanbul", "ΑΣ",
            "Mullite 3:2", "x", "Alumina-Mullite"]
_BASE = {"id": 254, "model_name": "Stainless Steel", "test_date": "05/03/2025", "analysis_mode": "sine",
         "gas_atmosphere": "Ar", "temperature_c": 766, "power_source_device": "Keithley 2602B",
         "power_response_device": "C80"}
SEARCH_ROWS = {
    "base": _BASE,
    "heb": {"id": 7, "model_name": "קרמיקה עברית", "test_date": "1/2/2024", "analysis_mode": "square",
            "gas_atmosphere": None, "temperature_c": 25.5, "power_source_device": None,
            "power_response_device": None},
    "istanbul": dict(_BASE, id=9, model_name="İstanbul"),
    "sigma": dict(_BASE, id=10, model_name="ΟΔΟΣ"),
}


# ---- columns ----

def test_list_columns_match_the_webapp():
    assert isinstance(columns.LIST_COLUMNS, tuple)
    assert columns.LIST_COLUMNS[:5] == ("id", "created_at", "model_name", "test_date", "test_time")
    assert columns.LIST_COLUMNS[-3:] == ("calibrated_from_id", "calibration_ref_ids", "calibration_model")
    assert ",".join(columns.LIST_COLUMNS) == LIST_COLUMNS_TS    # lib/analysisColumns.ts
    assert len(set(columns.LIST_COLUMNS)) == 46
    for blob in ("graph_image", "graph_json", "extra_data"):
        assert blob not in columns.LIST_COLUMNS


def test_every_list_column_has_info():
    assert set(columns.COLUMNS) == set(columns.LIST_COLUMNS)
    for name, info in columns.COLUMNS.items():
        assert info.name == name and info.label


def test_column_metadata_spot_checks():
    c = columns.COLUMNS
    assert (c["id"].label, c["id"].editable, c["id"].numeric) == ("ID", False, True)
    assert (c["model_name"].label, c["model_name"].editable, c["model_name"].numeric) == ("Model", True, False)
    assert c["temperature_c"].label == "T (°C)" and c["temperature_c"].unit == "°C"
    assert c["amplitude_a1"].label == "A₁ (mW)" and c["amplitude_a1"].unit == "mW"
    assert c["alpha_phase_cal"].label == "α phase (cal)" and c["alpha_phase_cal"].numeric
    assert c["use_calibration"].numeric is False and c["use_calibration"].editable is True
    assert c["calibration_model"].editable is False and c["calibration_model"].numeric is False
    assert c["calibration_ref_ids"].editable is False
    assert c["test_date"].numeric is False and c["analysis_mode"].numeric is False
    assert c["gas_atmosphere"].numeric is False
    assert c["created_at"].editable is False
    assert c["id"].unit == "" and c["model_name"].unit == ""


# ---- helpers (TS-pinned) ----

def test_format_alpha_pinned():
    assert len(ALPHA_TS) == len(ALPHA_IN)
    for v, (label, expected) in zip(ALPHA_IN, ALPHA_TS):
        got = helpers.format_alpha(v)
        # the webapp prints NaN / Infinity here; the interface says "—" for non-finite
        if v is not None and not math.isfinite(v):
            assert got == "—", label
        else:
            assert got == expected, (label, got, expected)


def test_format_alpha_edge_values():
    assert helpers.format_alpha(None) == "—"
    assert helpers.format_alpha(0) == "—"
    assert helpers.format_alpha(math.nan) == "—"
    assert helpers.format_alpha(-math.inf) == "—"
    assert helpers.format_alpha(8.0e-6) == "8.000"
    assert helpers.format_alpha(-2.5e-6) == "-2.500"


DATE_IN = ["05/03/2025", "5/3/25", "31/02/2025", "01/13/2024", "", "abc", "1/2", "1/2/3/4", "00/00/0000",
           " 7 / 8 / 2020", "29/02/2024", "15/06/0099", "15/06/100", "1.5/2/2024", "10/10/1e3", "x/1/2020",
           "0x10/1/2020", "31/12/1999", "1/1/-5", "1/1/10000"]


def test_parse_test_date_pinned():
    assert [s for s, _ in DATE_TS] == DATE_IN
    for s, ts in DATE_TS:
        got = helpers.parse_test_date(s)
        if s in ("", "abc", "1/2", "1/2/3/4"):
            assert got is None, s            # the webapp's epoch placeholder
        elif ts is None or ts[0] < 1 or ts[0] > 9999:
            assert got is None, s            # Invalid Date / outside Python's date range
        else:
            assert got == date(*ts), (s, got, ts)


def test_parse_test_date_specifics():
    assert helpers.parse_test_date("05/03/2025") == date(2025, 3, 5)
    assert helpers.parse_test_date("5/3/25") == date(1925, 3, 5)      # 2-digit years are 19xx, as in JS
    assert helpers.parse_test_date("31/02/2025") == date(2025, 3, 3)  # rolls over, as in JS
    assert helpers.parse_test_date(None) is None
    assert helpers.parse_test_date("   ") is None


def test_sort_key_test_date_unparsable_is_the_1970_epoch():
    epoch = date(1970, 1, 1)
    assert helpers.sort_key_test_date("05/03/2025") == date(2025, 3, 5)
    assert helpers.sort_key_test_date("31/02/2026") == date(2026, 3, 3)   # rolls over, as in JS
    for bad in (None, "", "garbage", "1/2"):
        assert helpers.sort_key_test_date(bad) == epoch
    dates = ["05/03/2025", None, "garbage", "01/01/2020", ""]
    assert sorted(dates, key=helpers.sort_key_test_date)[-2:] == ["01/01/2020", "05/03/2025"]


def test_run_label_pinned():
    assert len(RUN_ROWS) == len(RUN_TS)
    for row, expected in zip(RUN_ROWS, RUN_TS):
        assert helpers.run_label(row) == expected, row


def test_material_color_pinned():
    assert len(COLOR_IN) == len(COLOR_TS)
    for name, (_label, expected) in zip(COLOR_IN, COLOR_TS):
        assert helpers.material_color(name) == expected, name


def test_material_color_is_the_ported_one():
    from ctwa.analysis import references
    assert helpers.material_color is references.material_color


def test_row_matches_pinned():
    assert len(SEARCH_TS) >= 25
    for key, query, expected in SEARCH_TS:
        assert helpers.row_matches(SEARCH_ROWS[key], query) is expected, (key, query)


def test_row_matches_missing_fields_and_non_ascii():
    assert helpers.row_matches({"id": 3}, "") is True
    assert helpers.row_matches({"id": 3}, "#3") is True
    assert helpers.row_matches({}, "steel") is False
    assert helpers.row_matches(SEARCH_ROWS["heb"], "קרמיקה") is True


def test_with_ln_validity_pinned():
    for before, after in LN_TS:
        original = dict(before)
        got = helpers.with_ln_validity(before)
        assert got == after, (before, got, after)
        assert got is not before and before == original   # a new dict; the input is untouched


def test_with_ln_validity_nulls_both_alphas_only_when_invalid():
    bad = {"ln_term": 1, "amplitude_a1": 10, "amplitude_a2": 8, "r1_mm": 6.72, "r2_mm": 14.86,
           "alpha_combined_raw": 3e-6, "alpha_combined_cal": 4e-6, "alpha_phase_raw": 5e-6}
    got = helpers.with_ln_validity(bad)
    assert got["alpha_combined_raw"] is None and got["alpha_combined_cal"] is None
    assert got["alpha_phase_raw"] == 5e-6 and got["ln_term"] < 0
    assert bad["alpha_combined_raw"] == 3e-6


# ---- ResultsStore (fake client) ----

class FakeClient:
    """Records every call; `pages` scripts select results (a callable or a list per call)."""

    def __init__(self, select=None):
        self.calls = []
        self._select = select

    def select(self, table, query):
        self.calls.append(("select", table, dict(query)))
        if callable(self._select):
            return self._select(table, query)
        return list(self._select or [])

    def insert(self, table, row):
        self.calls.append(("insert", table, dict(row)))
        return dict(row, id=77)

    def update(self, table, id, data):
        self.calls.append(("update", table, id, dict(data)))
        return dict(data, id=id)

    def delete(self, table, id):
        self.calls.append(("delete", table, id))


def test_fetch_rows_query_and_paging():
    total = 2350

    def select(table, q):
        off, lim = int(q["offset"]), int(q["limit"])
        return [{"id": i} for i in range(off, min(off + lim, total))]
    c = FakeClient(select)
    rows = ResultsStore(c).fetch_rows()
    assert len(rows) == total and rows[0] == {"id": 0} and rows[-1] == {"id": total - 1}
    assert [(k[0], k[1]) for k in c.calls] == [("select", "analyses")] * 3
    q0 = c.calls[0][2]
    assert q0 == {"select": ",".join(columns.LIST_COLUMNS), "order": "created_at.desc",
                  "limit": "1000", "offset": "0"}
    assert [x[2]["offset"] for x in c.calls] == ["0", "1000", "2000"]


def test_fetch_rows_exact_multiple_asks_for_one_more_page():
    def select(table, q):
        return [{"id": 1}] * 1000 if q["offset"] == "0" else []
    c = FakeClient(select)
    assert len(ResultsStore(c).fetch_rows()) == 1000
    assert len(c.calls) == 2


def test_fetch_rows_empty_table():
    c = FakeClient([])
    assert ResultsStore(c).fetch_rows() == []
    assert len(c.calls) == 1


def test_fetch_graph_images_chunks_of_20():
    def select(table, q):
        ids = [int(x) for x in q["id"][4:-1].split(",")]
        return [{"id": i, "graph_image": "img%d" % i} for i in ids if i % 2 == 0]
    c = FakeClient(select)
    ids = list(range(1, 46))
    out = ResultsStore(c).fetch_graph_images(ids)
    assert len(c.calls) == 3
    for call, expect in zip(c.calls, (ids[:20], ids[20:40], ids[40:])):
        assert call[:2] == ("select", "analyses")
        assert call[2]["select"] == "id,graph_image"
        assert call[2]["id"] == "in.(" + ",".join(map(str, expect)) + ")"
    assert set(out) == set(ids)
    assert out[2] == "img2" and out[3] is None and out[44] == "img44"


def test_fetch_graph_images_empty_and_duplicates():
    c = FakeClient([])
    s = ResultsStore(c)
    assert s.fetch_graph_images([]) == {}
    assert c.calls == []
    assert s.fetch_graph_images([5, 5, 5]) == {5: None}
    assert c.calls[0][2]["id"] == "in.(5)"


def test_fetch_graph_images_blank_image_is_none():
    c = FakeClient([{"id": 1, "graph_image": ""}, {"id": 2, "graph_image": None}])
    assert ResultsStore(c).fetch_graph_images([1, 2]) == {1: None, 2: None}


def test_fetch_presets():
    c = FakeClient([{"id": 1, "material_name": "Abs"}])
    assert ResultsStore(c).fetch_presets() == [{"id": 1, "material_name": "Abs"}]
    assert c.calls == [("select", "alpha_presets", {"select": "*", "order": "material_name.asc"})]


def test_update_fields_sends_only_the_changes():
    c = FakeClient()
    out = ResultsStore(c).update_fields(5, {"model_name": "Abs"})
    assert c.calls == [("update", "analyses", 5, {"model_name": "Abs"})]
    assert out == {"model_name": "Abs", "id": 5}
    c.calls.clear()
    assert ResultsStore(c).update_fields(5, {}) == {}
    assert c.calls == []          # nothing changed: nothing sent


def test_update_fields_does_not_alias_the_callers_dict():
    c = FakeClient()
    changes = {"temperature_c": 25}
    ResultsStore(c).update_fields(1, changes)
    changes["temperature_c"] = 99
    assert c.calls[0][3] == {"temperature_c": 25}


def test_delete_insert_and_presets():
    c = FakeClient()
    s = ResultsStore(c)
    assert s.delete(9) is None
    assert s.insert("analyses", {"a": 1}) == {"a": 1, "id": 77}
    assert s.insert_preset({"material_name": "Abs"}) == {"material_name": "Abs", "id": 77}
    assert s.delete_preset(4) is None
    assert c.calls == [("delete", "analyses", 9), ("insert", "analyses", {"a": 1}),
                       ("insert", "alpha_presets", {"material_name": "Abs"}),
                       ("delete", "alpha_presets", 4)]


@pytest.mark.parametrize("exc", [NotLoggedIn("x"), Offline("x"), ServerError(500, "x")])
def test_store_lets_client_errors_through(exc):
    def boom(*a, **k):
        raise exc
    c = FakeClient(boom)
    with pytest.raises(type(exc)):
        ResultsStore(c).fetch_rows()


# ---- ResultsLoader ----

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _pump(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    QCoreApplication.processEvents()
    return cond()


class ThreadedFakeClient(FakeClient):
    """Tripwire: every network call records the thread it ran on."""

    def __init__(self, rows=None, presets=None, errors=None, delay=0.0):
        super().__init__()
        self.rows = rows if rows is not None else [{"id": 2}, {"id": 1}]
        self.presets = presets if presets is not None else [{"id": 1, "material_name": "Abs"}]
        self.errors = errors or {}     # method name -> exception
        self.delay = delay
        self.threads = []
        self.log = []                  # order of write calls

    def _enter(self, name):
        self.threads.append(threading.current_thread())
        if self.delay:
            time.sleep(self.delay)
        if name in self.errors:
            raise self.errors[name]

    def select(self, table, query):
        self._enter("select")
        self.calls.append(("select", table, dict(query)))
        if table == "alpha_presets":
            return list(self.presets)
        if "graph_image" in query.get("select", ""):
            ids = [int(x) for x in query["id"][4:-1].split(",")]
            return [{"id": i, "graph_image": "img%d" % i} for i in ids if i != 404]
        off = int(query.get("offset", "0"))
        return list(self.rows) if off == 0 else []

    def insert(self, table, row):
        self._enter("insert")
        self.log.append(("insert", table))
        return super().insert(table, row)

    def update(self, table, id, data):
        self._enter("update")
        self.log.append(("update", id))
        return super().update(table, id, data)

    def delete(self, table, id):
        self._enter("delete")
        self.log.append(("delete", table, id))
        return super().delete(table, id)


@pytest.fixture
def make_loader(qapp):
    from ctwa.ui.results_loader import ResultsLoader
    made = []

    def make(client):
        loader = ResultsLoader(client)
        made.append(loader)
        return loader
    yield make
    for loader in made:
        loader.shutdown(2000)
        QCoreApplication.processEvents()


def test_loader_refresh_runs_off_the_gui_thread_and_emits_rows_changed(make_loader):
    c = ThreadedFakeClient()
    loader = make_loader(c)
    got, presets, failed = [], [], []
    loader.rows_changed.connect(got.append)
    loader.presets_changed.connect(presets.append)
    loader.failed.connect(lambda k, m: failed.append((k, m)))
    assert loader.rows() == []
    loader.refresh()
    assert not c.threads            # nothing ran inline on the GUI thread
    assert _pump(lambda: got and presets)
    assert got[0] == [{"id": 2}, {"id": 1}] and presets[0] == [{"id": 1, "material_name": "Abs"}]
    assert loader.rows() == [{"id": 2}, {"id": 1}] and loader.presets() == presets[0]
    assert c.threads and all(t is not threading.main_thread() for t in c.threads)
    assert failed == []
    assert isinstance(loader.store, ResultsStore)


def test_loader_maps_errors_to_failed(make_loader):
    for exc, kind in ((NotLoggedIn("Not logged in"), "login"), (Offline("down"), "offline"),
                      (ServerError(500, "boom"), "server")):
        loader = make_loader(ThreadedFakeClient(errors={"select": exc}))
        failed, rows = [], []
        loader.failed.connect(lambda k, m: failed.append((k, m)))
        loader.rows_changed.connect(rows.append)
        loader.refresh()
        assert _pump(lambda: failed)
        assert failed[0][0] == kind and failed[0][1]
        assert rows == []


def test_loader_refresh_while_busy_runs_again_not_in_parallel(make_loader):
    c = ThreadedFakeClient(delay=0.05)
    loader = make_loader(c)
    got = []
    loader.rows_changed.connect(got.append)
    loader.refresh()
    loader.refresh()
    loader.refresh()
    assert _pump(lambda: len(got) >= 1)
    _pump(lambda: False, 0.4)
    assert 1 <= len(got) <= 2       # coalesced, never three parallel fetches


def test_loader_writes_run_in_order_off_thread_with_tokens(make_loader):
    c = ThreadedFakeClient(delay=0.02)
    loader = make_loader(c)
    done, failed, rows = [], [], []
    loader.write_done.connect(lambda op, tok, res: done.append((op, tok, res)))
    loader.write_failed.connect(lambda *a: failed.append(a))
    loader.rows_changed.connect(rows.append)
    t1 = loader.apply_update(5, {"model_name": "Abs"})
    t2 = loader.apply_delete(6)
    t3 = loader.apply_insert({"model_name": "x"})
    t4 = loader.apply_preset_insert({"material_name": "Abs"})
    t5 = loader.apply_preset_delete(3)
    assert len({t1, t2, t3, t4, t5}) == 5 and all(isinstance(t, int) for t in (t1, t2, t3, t4, t5))
    assert not c.threads
    assert _pump(lambda: len(done) == 5)
    assert [d[:2] for d in done] == [("update", t1), ("delete", t2), ("insert", t3),
                                     ("preset_insert", t4), ("preset_delete", t5)]
    assert c.log == [("update", 5), ("delete", "analyses", 6), ("insert", "analyses"),
                     ("insert", "alpha_presets"), ("delete", "alpha_presets", 3)]
    assert done[0][2] == {"model_name": "Abs", "id": 5}
    assert done[1][2] is None and done[2][2] == {"model_name": "x", "id": 77}
    assert failed == []
    assert _pump(lambda: rows)                       # a refresh followed the writes
    assert all(t is not threading.main_thread() for t in c.threads)


def test_loader_write_done_comes_before_the_refresh(make_loader):
    loader = make_loader(ThreadedFakeClient())
    order = []
    loader.write_done.connect(lambda *a: order.append("done"))
    loader.rows_changed.connect(lambda r: order.append("rows"))
    loader.apply_update(1, {"model_name": "x"})
    assert _pump(lambda: "rows" in order)
    assert order[0] == "done"


def test_loader_preset_write_refreshes_presets(make_loader):
    loader = make_loader(ThreadedFakeClient())
    presets = []
    loader.presets_changed.connect(presets.append)
    loader.apply_preset_insert({"material_name": "Abs"})
    assert _pump(lambda: presets)


def test_loader_failed_write_is_reported_and_next_write_still_runs(make_loader):
    c = ThreadedFakeClient(errors={"update": NotLoggedIn("expired")})
    loader = make_loader(c)
    wf, wd, failed = [], [], []
    loader.write_failed.connect(lambda op, tok, kind, msg: wf.append((op, tok, kind, msg)))
    loader.write_done.connect(lambda op, tok, res: wd.append((op, tok)))
    loader.failed.connect(lambda k, m: failed.append((k, m)))
    t1 = loader.apply_update(1, {"model_name": "x"})
    t2 = loader.apply_delete(2)
    assert _pump(lambda: wf and wd)
    assert wf[0][:3] == ("update", t1, "login") and wf[0][3]
    assert wd == [("delete", t2)]
    assert failed == []     # a write failure is reported by write_failed only


@pytest.mark.parametrize("exc,kind", [(Offline("x"), "offline"), (ServerError(400, "bad"), "server"),
                                       (RuntimeError("bug"), "error")])
def test_loader_write_error_kinds(make_loader, exc, kind):
    loader = make_loader(ThreadedFakeClient(errors={"insert": exc}))
    wf = []
    loader.write_failed.connect(lambda op, tok, k, m: wf.append((op, k)))
    loader.apply_insert({"a": 1})
    assert _pump(lambda: wf)
    assert wf == [("insert", kind)]


def test_loader_request_graph(make_loader):
    c = ThreadedFakeClient()
    loader = make_loader(c)
    got = []
    loader.graph_loaded.connect(lambda i, img: got.append((i, img)))
    loader.request_graph(7)
    loader.request_graph(404)
    assert not c.threads
    assert _pump(lambda: len(got) == 2)
    assert sorted(got, key=lambda x: x[0]) == [(7, "img7"), (404, "")]   # "" = row has no stored graph
    assert all(t is not threading.main_thread() for t in c.threads)
    n = len(c.calls)
    loader.request_graph(7)          # cached: answered again without a request
    assert _pump(lambda: len(got) == 3)
    assert got[-1] == (7, "img7") and len(c.calls) == n


def test_loader_failed_graph_fetch_resolves_the_waiter_with_none(make_loader):
    c = ThreadedFakeClient(errors={"select": Offline("down")})
    loader = make_loader(c)
    got, failed = [], []
    loader.graph_loaded.connect(lambda i, img: got.append((i, img)))
    loader.failed.connect(lambda k, m: failed.append((k, m)))
    loader.request_graph(7)
    assert _pump(lambda: got)
    _pump(lambda: False, 0.1)
    assert got == [(7, None)] and failed == []      # None = the fetch FAILED (graph_loaded only)
    c.errors = {}
    loader.request_graph(7)          # the failure was not cached: a retry fetches for real
    assert _pump(lambda: len(got) == 2)
    assert got[-1] == (7, "img7")


def test_loader_update_forgets_the_cached_graph(make_loader):
    c = ThreadedFakeClient()
    loader = make_loader(c)
    got = []
    loader.graph_loaded.connect(lambda i, img: got.append((i, img)))
    loader.request_graph(7)
    assert _pump(lambda: got)
    loader.apply_delete(7)
    assert _pump(lambda: loader.rows() != [])
    n = len(c.calls)
    loader.request_graph(7)
    assert _pump(lambda: len(got) == 2)
    assert len(c.calls) > n


def test_loader_signals_after_deletion_are_harmless(qapp):
    from ctwa.ui.results_loader import ResultsLoader
    c = ThreadedFakeClient(delay=0.1)
    loader = ResultsLoader(c)
    loader.refresh()
    loader.apply_update(1, {"a": 1})
    loader.shutdown(2000)
    loader.deleteLater()
    QCoreApplication.processEvents()
    time.sleep(0.3)
    QCoreApplication.processEvents()


def test_main_window_has_a_results_loader_and_save_refreshes_it(qapp, monkeypatch):
    from ctwa import app as appmod
    from ctwa.ui.results_loader import ResultsLoader
    monkeypatch.setattr(appmod.MainWindow, "_check_license_agreement", lambda self: True)
    win = appmod.MainWindow()
    try:
        assert isinstance(win.results_loader, ResultsLoader)
        calls = []
        monkeypatch.setattr(win.results_loader, "refresh", lambda: calls.append(1))
        win.save_panel.saved.emit(12)
        assert calls == [1]
        win.save_panel.saved.emit(None)     # a queued save: nothing to fetch yet
        assert calls == [1]
    finally:
        win.close()


def test_closing_the_window_shuts_the_loader_down(qapp, monkeypatch):
    from ctwa import app as appmod
    monkeypatch.setattr(appmod.MainWindow, "_check_license_agreement", lambda self: True)
    win = appmod.MainWindow()
    calls = []
    monkeypatch.setattr(win.results_loader, "shutdown", lambda *a: calls.append(1))
    win.close()
    assert calls == [1]
    win2 = appmod.MainWindow()
    win2.results_loader = None          # cloud off
    win2.close()


def test_webapp_login_refreshes_the_loader(qapp, monkeypatch):
    from PySide6.QtWidgets import QDialog
    from ctwa import app as appmod
    from ctwa.ui import login_dialog
    monkeypatch.setattr(appmod.MainWindow, "_check_license_agreement", lambda self: True)
    win = appmod.MainWindow()
    try:
        calls = []
        monkeypatch.setattr(win.results_loader, "refresh", lambda: calls.append(1))
        monkeypatch.setattr(login_dialog.LoginDialog, "exec", lambda self: QDialog.Rejected)
        win._webapp_login()
        assert calls == []
        monkeypatch.setattr(login_dialog.LoginDialog, "exec", lambda self: QDialog.Accepted)
        win._webapp_login()
        assert calls == [1]
        win.results_loader = None          # cloud off: nothing to refresh, no crash
        win._webapp_login()
    finally:
        win.close()


def _row_fetches(c):
    return len([x for x in c.calls if x[0] == "select" and x[1] != "alpha_presets"])


def test_loader_a_batch_of_writes_causes_one_refresh(make_loader):
    c = ThreadedFakeClient(delay=0.02)
    loader = make_loader(c)
    done = []
    loader.write_done.connect(lambda *a: done.append(a))
    for i in range(6):
        loader.apply_update(i + 1, {"model_name": "x"})
    assert _pump(lambda: len(done) == 6)
    _pump(lambda: False, 0.5)
    assert _row_fetches(c) == 1


def test_loader_failed_write_still_refreshes(make_loader):
    c = ThreadedFakeClient(errors={"update": Offline("timed out")})
    loader = make_loader(c)
    wf, rows = [], []
    loader.write_failed.connect(lambda *a: wf.append(a))
    loader.rows_changed.connect(rows.append)
    loader.apply_update(1, {"model_name": "x"})
    assert _pump(lambda: wf and rows)


def test_loader_refresh_requested_during_a_failing_fetch_runs_again(make_loader):
    c = ThreadedFakeClient(delay=0.1, errors={"select": Offline("down")})
    loader = make_loader(c)
    failed = []
    loader.failed.connect(lambda k, m: failed.append(k))
    loader.refresh()
    _pump(lambda: False, 0.03)
    loader.refresh()                     # in flight: remembered
    assert _pump(lambda: failed)         # the first fetch failed ...
    c.errors = {}                        # ... the network is back for the re-run
    assert _pump(lambda: loader.rows() == [{"id": 2}, {"id": 1}])
    assert set(failed) == {"offline"}


def test_loader_shutdown_waits_briefly_for_plots_and_longer_for_writes(make_loader):
    loader = make_loader(ThreadedFakeClient())
    waits = {}
    real_w, real_g = loader._pool.waitForDone, loader._graph_pool.waitForDone
    loader._pool.waitForDone = lambda ms=-1: waits.setdefault("write", ms) and real_w(ms)
    loader._graph_pool.waitForDone = lambda ms=-1: waits.setdefault("plot", ms) and real_g(ms)
    loader.shutdown(3000)
    assert waits == {"write": 3000, "plot": 200}
