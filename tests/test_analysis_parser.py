"""One-file CSV parser: encodings and the helpers around it."""

from __future__ import annotations

import math

from ctwa.analysis.parser import (
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
