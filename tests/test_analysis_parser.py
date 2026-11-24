"""One-file CSV parser: encodings and the helpers around it."""

from __future__ import annotations

import gzip
import math
import os

import pytest

from ctwa.analysis.jsmath import js_trim
from ctwa.analysis.parser import (
    _parse_float,
    decode_bytes, extract_date_from_filename, extract_start_date,
    extract_temperature_from_filename, is_combined_file, parse_combined_file,
)

HEADER = "Elapsed(s),Power(mW),Heat Flow(µW),Sample Temperature(°C)"


def _csv() -> str:
    rows = [HEADER]
    for i in range(12):
        rows.append(f"{i},{10 + i},{2000 + 10 * i},{150.5}")
    return "\n".join(rows) + "\n"


def test_utf8_and_cp1252_parse_equal():
    text = _csv()
    a = parse_combined_file(text.encode("utf-8"))
    b = parse_combined_file(text.encode("cp1252"))
    assert a is not None and b is not None
    assert a == b
    assert a.response[0] == 2000 * 1e-3
    assert a.source[3] == 13
    assert a.temperature[0] == 150.5
    assert len(a.time) == 12


def test_cp1252_bytes_decode_not_replacement():
    assert "°C" in decode_bytes("T(°C)".encode("cp1252"))


def test_bom_variants():
    assert decode_bytes(b"\xef\xbb\xbfab") == "ab"  # TextDecoder drops the BOM
    assert decode_bytes(b"\xff\xfea\x00b\x00") == "ab"
    assert decode_bytes(b"\xff\xfea\x00") == "a"
    assert decode_bytes(b"\xfe\xff\x00a") == "a"


def test_too_few_rows_is_none_and_is_combined():
    short = "\n".join([HEADER] + ["1,1,1,1"] * 5).encode()
    assert parse_combined_file(short) is None
    assert is_combined_file(short)
    assert not is_combined_file(b"a,b\n1,2\n")


def test_temperature_nan_when_column_absent():
    text = "Elapsed(s),Power(mW),HF(mW)\n" + "\n".join(f"{i},1,2" for i in range(12))
    p = parse_combined_file(text.encode())
    assert p is not None and all(math.isnan(v) for v in p.temperature)


def test_start_date():
    assert extract_start_date(b"# Started: 2026-02-16 14:48:43\n") == "2026-02-16"
    assert extract_start_date(b"Zone Start Time : 6/2/2026 12:52:04\n") == "2026-02-06"
    assert extract_start_date(b"nothing\n") is None


def test_filename_helpers():
    assert extract_date_from_filename("run 27052026.csv") == "27/05/2026"
    assert extract_date_from_filename("a_270526.csv") == "27/05/2026"
    assert extract_date_from_filename("x 31022026.csv") is None
    assert extract_temperature_from_filename("SS 150C run.csv") == 150.0
    assert extract_temperature_from_filename("temp_75.5.csv") == 75.5
    assert extract_temperature_from_filename("plain.csv") is None


def test_js_trim_and_parse_float():
    assert js_trim("-x-") == "-x-"
    assert js_trim(" x ") == "x"
    assert js_trim("\u2003x\u2009\ufeff") == "x"
    assert _parse_float("-5.5") == -5.5
    assert _parse_float(" -5") == -5.0
    assert _parse_float("12abc") == 12.0
    assert math.isnan(_parse_float(""))
    assert _parse_float("\u2003-1e2x") == -100.0


# Expected values below were produced by running the TypeScript functions of
# lib/fileParser.ts (npx tsx) on exactly these inputs.
RUNS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "runs")
SYNTH = {
    "headerless": b"1,2,3\n4,5,6\n",
    "c80_synth": b"Zone Start Time : 6/2/2026 12:52:04\nx\n",
    "c80_iso": b"Zone Start Time : 2026-02-16 12:52:04\n",
    "keithley_synth": b"# Started: 2026-02-16 14:48:43\n",
    "hash_nostart": b"# Run 5\n# Created 2026-01-01\n",
}
START_CASES = [
    ('al2o3_c80', None),
    ('al2o3_ctwa', '2026-11-17'),
    ('fiber_150_600', '2026-08-28'),
    ('fiber_75_105', '2026-08-30'),
    ('headerless', None),
    ('c80_synth', '2026-02-06'),
    ('c80_iso', '2026-02-16'),
    ('keithley_synth', '2026-02-16'),
    ('hash_nostart', None),
]
DATE_CASES = [
    ('run 27052026.csv', '27/05/2026'),
    ('a_270526.csv', '27/05/2026'),
    ('x 31022026.csv', None),
    ('SS 150C 15-03-26.csv', '15/03/2026'),
    ('SS 15_03_2026.xlsx', '15/03/2026'),
    ('2026-03-15 foam.csv', '26/03/2015'),
    ('2026_03_15.csv', '26/03/2015'),
    ('C:\\data\\run 01012025.csv', '01/01/2025'),
    ('no date here.csv', None),
    ('15.03.26', None),
    ('29022024.csv', '29/02/2024'),
    ('29022023.csv', None),
    ('12-5-26.csv', None),
    ('45 150C 010203.csv', '01/02/2003'),
    ('1503266.csv', None),
    ('a 15/03/2026 b', None),
]
TEMP_CASES = [
    ('SS 150C run.csv', 150),
    ('ss 150c.csv', 150),
    ('SS 150 C.csv', 150),
    ('foam 800°C.csv', None),
    ('temp_75.5.csv', 75.5),
    ('T150.csv', 150),
    ('x 300 deg.csv', 300),
    ('x 300 degrees y.csv', 300),
    ('plain.csv', None),
    ('alumina 600C_ar.csv', None),
    ('1000C.csv', None),
    ('-20C.csv', 20),
    ('150Cr.csv', None),
    ('t-60.csv', 60),
    ('C:\\a\\b 25.5°c x.csv', 25.5),
    ('150c', 150),
    ('run 3 t 50.csv', 50),
    ('1.5.5C.csv', 5.5),
]


@pytest.mark.parametrize("name,expected", START_CASES)
def test_extract_start_date_matches_ts(name, expected):
    if name in SYNTH:
        data = SYNTH[name]
    else:
        with gzip.open(os.path.join(RUNS_DIR, name + ".csv.gz"), "rb") as f:
            data = f.read()[:2048]
    assert extract_start_date(data) == expected


@pytest.mark.parametrize("name,expected", DATE_CASES)
def test_extract_date_from_filename_matches_ts(name, expected):
    assert extract_date_from_filename(name) == expected


@pytest.mark.parametrize("name,expected", TEMP_CASES)
def test_extract_temperature_from_filename_matches_ts(name, expected):
    assert extract_temperature_from_filename(name) == expected
