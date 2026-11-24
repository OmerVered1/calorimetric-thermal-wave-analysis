"""One-file CSV parser: literal port of lib/fileParser.ts (combined-capture paths only).

JS behaviours reproduced here: TextDecoder (BOM stripped, fatal UTF-8 then
windows-1252 with C1 bytes passed through), String.trim, parseFloat, regex
`\\s` / `\\d` / `$` / `.` meanings, and Date's two-digit-year mapping.
"""

from __future__ import annotations

import calendar
import codecs
import re
from typing import List, Optional

from .jsmath import JS_WHITESPACE as _WS, js_trim
from .types import CombinedParsed

_S = "[" + _WS + "]"
_NOT_NL = "[^\n\r\u2028\u2029]"  # JS `.`
_F = re.ASCII  # \d, \w, [a-z] with i-less patterns behave like JS


def _js_lower(s: str) -> str:
    return s.lower()


def _cp1252_c1_passthrough(err: UnicodeDecodeError):
    # WHATWG windows-1252 maps the five bytes Python leaves undefined to C1 controls
    return "".join(chr(b) for b in err.object[err.start:err.end]), err.end


codecs.register_error("ctwa_cp1252_c1", _cp1252_c1_passthrough)

_PARSE_FLOAT = re.compile(r"[+-]?(?:Infinity|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)", _F)


def _parse_float(s: str) -> float:
    """JS parseFloat: longest numeric prefix after leading whitespace, else NaN."""
    m = _PARSE_FLOAT.match(s.lstrip(_WS))
    if not m:
        return float("nan")
    return float(m.group(0).replace("Infinity", "inf"))


def decode_bytes(data: bytes) -> str:
    """Raw bytes to text: BOM-marked UTF-16 / UTF-8, else strict UTF-8, else windows-1252."""
    b = bytes(data)
    if b[0:2] == b"\xff\xfe":
        return b[2:].decode("utf-16-le", errors="replace")
    if b[0:2] == b"\xfe\xff":
        return b[2:].decode("utf-16-be", errors="replace")
    if b[0:3] == b"\xef\xbb\xbf":
        return b[3:].decode("utf-8", errors="replace")
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("cp1252", errors="ctwa_cp1252_c1")


_NEWLINE = re.compile(r"\r?\n")

# mW per unit, for heat-flow columns written as "Heat Flow(<unit>)"
_HEAT_FLOW_MW = {"µw": 1e-3, "uw": 1e-3, "mw": 1.0, "w": 1000.0}

_RE_TIME = re.compile(r"time" + _S + r"*\(s\)|^time\Z", _F)
_RE_HEAT_FLOW = re.compile(r"^heat" + _S + r"*flow" + _S + r"*\((µw|uw|mw|w)\)\Z", _F)
_RE_SAMPLE_TEMP = re.compile(r"^sample" + _S + r"*temperature" + _S + r"*\(°c\)\Z", _F)


class _Columns:
    __slots__ = ("sep", "t", "src", "resp", "temp", "src_scale", "resp_scale")

    def __init__(self, sep, t, src, resp, temp, src_scale, resp_scale):
        self.sep = sep
        self.t = t
        self.src = src
        self.resp = resp
        self.temp = temp
        self.src_scale = src_scale
        self.resp_scale = resp_scale


def _find_index(cols: List[str], pred) -> int:
    for i, c in enumerate(cols):
        if pred(c):
            return i
    return -1


def _heat_flow_unit(c: str) -> Optional[str]:
    if c == "hf(mw)":
        return "mw"
    m = _RE_HEAT_FLOW.search(c)
    return m.group(1) if m else None


def _combined_columns(line: str) -> Optional[_Columns]:
    trimmed = js_trim(line)
    if "\t" in trimmed:
        cols = [_js_lower(js_trim(s)) for s in trimmed.split("\t")]
        t = _find_index(cols, lambda c: _RE_TIME.search(c) is not None)
        src = _find_index(cols, lambda c: "smu" in c)
        resp = _find_index(cols, lambda c: "heatflow" in c or "heat flow" in c)
        if t < 0 or src < 0 or resp < 0:
            return None
        return _Columns("\t", t, src, resp,
                        _find_index(cols, lambda c: c.startswith("temperature")), 1.0, 1.0)
    if trimmed.startswith("#") or "," not in trimmed:
        return None
    cols = [_js_lower(js_trim(s)) for s in trimmed.split(",")]
    t = _find_index(cols, lambda c: c == "elapsed(s)" or c == "time(s)")
    src = _find_index(cols, lambda c: c == "power(mw)" or c == "power(w)")
    resp = _find_index(cols, lambda c: _heat_flow_unit(c) is not None)
    if t < 0 or src < 0 or resp < 0:
        return None
    temp = _find_index(cols, lambda c: c == "t(c)" or _RE_SAMPLE_TEMP.search(c) is not None)
    return _Columns(",", t, src, resp, temp,
                    1000.0 if cols[src] == "power(w)" else 1.0,
                    _HEAT_FLOW_MW[_heat_flow_unit(cols[resp])])


def is_combined_file(data: bytes) -> bool:
    lines = _NEWLINE.split(decode_bytes(data))[:60]
    head = _js_lower("\n".join(lines))
    if "smu" in head and ("heatflow" in head or "heat flow" in head):
        return True
    return any(_combined_columns(line) is not None for line in lines)


def parse_combined_file(data: bytes) -> Optional[CombinedParsed]:
    lines = _NEWLINE.split(decode_bytes(data))
    time: List[float] = []
    source: List[float] = []
    response: List[float] = []
    temperature: List[float] = []
    cols: Optional[_Columns] = None

    for line in lines:
        trimmed = js_trim(line)
        if not trimmed:
            continue

        if cols is None:
            cols = _combined_columns(trimmed)
            continue

        row = trimmed.split(cols.sep)
        if len(row) <= max(cols.t, cols.src, cols.resp):
            continue
        tv = _parse_float(row[cols.t])
        sv = _parse_float(row[cols.src]) * cols.src_scale
        rv = _parse_float(row[cols.resp]) * cols.resp_scale
        if tv != tv or sv != sv or rv != rv:
            continue
        time.append(tv)
        source.append(sv)
        response.append(rv)
        tp = _parse_float(row[cols.temp]) if 0 <= cols.temp < len(row) else float("nan")
        temperature.append(tp)

    if len(time) > 10:
        return CombinedParsed(time=time, source=source, response=response, temperature=temperature)
    return None


_RE_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})", _F)
_RE_DMY = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})", _F)


def extract_start_date(data: bytes) -> Optional[str]:
    lines = _NEWLINE.split(decode_bytes(data))[:40]
    for line in lines:
        lower = _js_lower(line)
        if "zone start time" not in lower and not (js_trim(line).startswith("#") and "started" in lower):
            continue
        iso = _RE_ISO.search(line)
        if iso:
            return "%s-%s-%s" % (iso.group(1), iso.group(2), iso.group(3))
        # C80 writes the day first: 16/02/2026
        dmy = _RE_DMY.search(line)
        if dmy:
            return "%s-%s-%s" % (dmy.group(3), dmy.group(2).rjust(2, "0"), dmy.group(1).rjust(2, "0"))
    return None


_RE_EXT = re.compile(r"\.[^.]+\Z")
_RE_DIR = re.compile(r"^" + _NOT_NL + r"*[\\/]")


def _basename(filename: str) -> str:
    return _RE_DIR.sub("", _RE_EXT.sub("", filename, count=1), count=1)


def _is_valid_date(dd: str, mm: str, yyyy: str) -> bool:
    # new Date(y, m - 1, d) maps years 0..99 to 1900+y, so getFullYear() != y there;
    # elsewhere the date must survive without rolling over.
    y, m, d = int(yyyy), int(mm), int(dd)
    if y < 100 or y > 9999:
        return False
    if m < 1 or m > 12:
        return False
    return 1 <= d <= calendar.monthrange(y, m)[1]


_RE_DDMMYYYY = re.compile(r"(?:^|\D)(\d{2})(\d{2})(\d{4})(?:\D|\Z)", _F)
_RE_DDMMYY = re.compile(r"(?:^|\D)(\d{2})(\d{2})(\d{2})(?:\D|\Z)", _F)
_RE_DMY_SEP = re.compile(r"(\d{2})[.\-_](\d{2})[.\-_](\d{2,4})", _F)
_RE_YMD_SEP = re.compile(r"(\d{4})[.\-_](\d{2})[.\-_](\d{2})", _F)


def extract_date_from_filename(name: str) -> Optional[str]:
    """Test date from a filename as DD/MM/YYYY, or None."""
    basename = _basename(name)

    # DDMMYYYY (8 digits) - tried before DDMMYY so 27052026 is not misread as 052026
    m = _RE_DDMMYYYY.search(basename)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        if _is_valid_date(dd, mm, yyyy):
            return "%s/%s/%s" % (dd, mm, yyyy)

    # DDMMYY (6 digits)
    m = _RE_DDMMYY.search(basename)
    if m:
        dd, mm, yy = m.group(1), m.group(2), m.group(3)
        year = "20" + yy
        if _is_valid_date(dd, mm, year):
            return "%s/%s/%s" % (dd, mm, year)

    # DD-MM-YY / DD.MM.YY / DD_MM_YY
    m = _RE_DMY_SEP.search(basename)
    if m:
        dd, mm, raw = m.group(1), m.group(2), m.group(3)
        year = "20" + raw if len(raw) == 2 else raw
        if _is_valid_date(dd, mm, year):
            return "%s/%s/%s" % (dd, mm, year)

    # YYYY-MM-DD
    m = _RE_YMD_SEP.search(basename)
    if m:
        yyyy, mm, dd = m.group(1), m.group(2), m.group(3)
        if _is_valid_date(dd, mm, yyyy):
            return "%s/%s/%s" % (dd, mm, yyyy)

    return None


_NUM = r"(\d+(?:\.\d+)?)"
_RE_TEMP_C = re.compile(_NUM + _S + r"*°?c(?:" + _S + r"|\Z|[^a-z])", _F)
_RE_TEMP_T = re.compile(r"(?:temp|t)" + r"[" + _WS + r"_-]*" + _NUM, _F)
_RE_TEMP_DEG = re.compile(_NUM + _S + r"*(?:deg|degrees)", _F)


def extract_temperature_from_filename(name: str) -> Optional[float]:
    """Temperature (deg C) from a filename, or None."""
    basename = _js_lower(_basename(name))

    def valid(v: float) -> bool:
        return -50 <= v <= 500

    for pattern in (_RE_TEMP_C, _RE_TEMP_T, _RE_TEMP_DEG):
        m = pattern.search(basename)
        if m and valid(float(m.group(1))):
            return float(m.group(1))
    return None
