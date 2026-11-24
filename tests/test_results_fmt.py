"""Display helpers that match JavaScript (Results tab, Task 1). Expected values from the webapp's own
TypeScript (Number.prototype.toFixed/toPrecision, compareCells of app/summary/page.tsx, nextSort of
components/ui/Table.tsx, runLabelText, labelOf of app/analyses-viewer/page.tsx), run with npx tsx."""
from __future__ import annotations

import math

import pytest

from ctwa.analysis.jsmath import js_number, js_to_fixed, js_to_precision
from ctwa.ui.results.fmt import (HISTORY_SEARCH_FIELDS, compare_cells, label_of, matches_fields,
                                 next_sort, run_label_text)

FIXED_TS = [(2.5, 0, "3"), (-2.5, 0, "-3"), (1.005, 2, "1.00"), (-0.0, 2, "0.00"), (-0.001, 2, "-0.00"),
            (1234.5678, 1, "1234.6"), (math.nan, 2, "NaN"), (math.inf, 1, "Infinity"), (1e21, 2, "1e+21"),
            (0.5, 0, "1"), (1.45, 1, "1.4"), (-1.5, 0, "-2"), (123456789.125, 2, "123456789.13"),
            (0.000001, 4, "0.0000")]
PREC_TS = [(0.0085, 4, "0.008500"), (0, 4, "0.000"), (12345.6, 4, "1.235e+4"), (1.234e-7, 4, "1.234e-7"),
           (0.000001234, 4, "0.000001234"), (8.5123, 4, "8.512"), (99999.5, 4, "1.000e+5"),
           (0.00000123456, 4, "0.000001235"), (-3.14159, 3, "-3.14"), (1e21, 4, "1.000e+21"),
           (123456, 6, "123456"), (0.1, 1, "0.1")]


@pytest.mark.parametrize("v,d,want", FIXED_TS)
def test_js_to_fixed_regression(v, d, want):
    assert js_to_fixed(v, d) == want


@pytest.mark.parametrize("v,p,want", PREC_TS)
def test_js_to_precision_regression(v, p, want):
    assert js_to_precision(v, p) == want


# (a, b, key, TS result); documents the TS run these cases were checked against
CMP_TS = [("01/02/2026", "15/01/2026", "test_date", 1468800000), (None, 5, "x", -5), ("", 5, "x", -5),
          (" 7 ", 5, "x", 2), ("12abc", "13", "x", -1), ("a", "B", "x", -1), ("a", "A", "x", -1),
          ("A", "a", "x", 1), ("Abs", "abs", "x", 1), (True, 0, "x", 1), ("1e3", "999", "x", 1),
          ("0x10", "15", "x", 1), ("ä", "b", "x", -1), ("a", "ä", "x", -1), ("z", "ä", "x", 1),
          ("a b", "ab", "x", -1), ("a-b", "ab", "x", -1), ("10", "9", "x", 1), ("b", "a1", "x", 1),
          (None, "abc", "x", -1)]


@pytest.mark.parametrize("a,b,key,want", [c for c in CMP_TS if c[2] != "test_date"])
def test_compare_cells_matches_ts(a, b, key, want):
    got = compare_cells(a, b, key)
    assert (got > 0) - (got < 0) == (want > 0) - (want < 0)
    if want in (-5, 2):
        assert got == want


def test_compare_cells_dates():
    assert compare_cells("01/02/2026", "15/01/2026", "test_date") == 1468800000
    # an unparsable date counts as 1970 (TS: new Date(0) / Invalid), so it sorts before any real date
    assert compare_cells("xx", "15/01/2026", "test_date") < 0
    assert compare_cells(None, "15/01/2026", "test_date") < 0
    assert compare_cells("15/01/2026", "15/01/2026", "test_date") == 0


def test_compare_cells_numbers_and_strings():
    assert compare_cells(None, 5, "x") == -5
    assert compare_cells("", 5, "x") == -5
    assert compare_cells(" 7 ", 5, "x") == 2
    assert compare_cells(3.5, 1, "x") == 2.5
    assert compare_cells("12abc", "13", "x") < 0          # not both numbers: string compare
    assert compare_cells("10", "9", "x") > 0              # both numbers: numeric
    assert compare_cells(True, 0, "x") == 1
    assert compare_cells("Infinity", "5", "x") == math.inf


def test_compare_cells_locale_order():
    assert compare_cells("a", "B", "x") < 0
    assert compare_cells("a", "A", "x") < 0
    assert compare_cells("A", "a", "x") > 0
    assert compare_cells("Abs", "abs", "x") > 0
    assert compare_cells("ä", "b", "x") < 0
    assert compare_cells("a", "ä", "x") < 0
    assert compare_cells("z", "ä", "x") > 0
    assert compare_cells("abc", "abc", "x") == 0


def test_next_sort_cycle():
    s = (None, None)
    s = next_sort(s, "id")
    assert s == ("id", "asc")
    s = next_sort(s, "id")
    assert s == ("id", "desc")
    s = next_sort(s, "id")
    assert s == (None, None)
    assert next_sort(("id", "desc"), "x") == ("x", "asc")
    assert next_sort(("id", "asc"), "x") == ("x", "asc")


def test_run_label_text():
    r = {"model_name": "Stainless Steel", "temperature_c": 766.0, "period_t": 600.5, "id": 254}
    assert run_label_text(r) == "Stainless Steel · 766 °C · 601 s · #254"
    r2 = {"model_name": "Stainless Steel", "temperature_c": None, "period_t": None, "id": 254}
    assert run_label_text(r2) == "Stainless Steel · #254"
    assert run_label_text({"model_name": "X", "temperature_c": 25.5, "period_t": -0.4, "id": 1}) == "X · 25.5 °C · 0 s · #1"


def test_label_of():
    r = {"model_name": "Alumina", "test_date": "17/11/2026", "temperature_c": 766, "gas_atmosphere": "Ar",
         "analysis_mode": "AutoFit", "amplitude_a1": 12.34, "period_t": 600.4, "id": 254}
    assert label_of(r) == "Alumina | 17/11/2026 | 766°C | Ar | AutoFit | A₁=12.3mW | T=600s #254"
    r2 = dict(r, temperature_c=None, gas_atmosphere=None, amplitude_a1=None, period_t=600.5)
    assert label_of(r2) == "Alumina | 17/11/2026 | AutoFit | T=601s #254"
    # TS: Array.join renders a null mode as an empty part; toFixed ties go up (0.25 -> 0.3)
    r3 = {"model_name": "A", "test_date": "1/1/2026", "temperature_c": 25.5, "gas_atmosphere": "",
          "analysis_mode": None, "amplitude_a1": 0.25, "period_t": 2.5, "id": 3}
    assert label_of(r3) == "A | 1/1/2026 | 25.5°C |  | A₁=0.3mW | T=3s #3"


ROW = {"id": 254, "model_name": "Stainless Steel", "test_date": "17/11/2026", "analysis_mode": "AutoFit",
       "temperature_c": 766.0, "period_t": 600.0, "gas_atmosphere": "Ar"}


def test_matches_fields():
    f = HISTORY_SEARCH_FIELDS
    assert f == ("id", "model_name", "test_date", "analysis_mode", "temperature_c")
    assert matches_fields(ROW, "steel 766", f)
    assert matches_fields(ROW, "#254", f)
    assert matches_fields(ROW, "", f)
    assert matches_fields(ROW, "  STEEL\t autofit ", f)
    assert not matches_fields(ROW, "zzz", f)
    assert not matches_fields(ROW, "steel zzz", f)
    assert not matches_fields(ROW, "600", f)             # period_t is not a history field
    assert matches_fields(ROW, "600", f + ("period_t",))
    assert matches_fields({"id": 1, "model_name": "Schäfer"}, "Ä", ("model_name",))
    assert not matches_fields({"id": 1, "model_name": None}, "none", ("model_name",))
