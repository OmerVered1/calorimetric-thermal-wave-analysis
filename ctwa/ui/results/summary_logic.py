"""Logic of the Summary page, ported literally from app/summary/page.tsx (DISPLAY_COLS, PRESETS,
filters, stats, downloadCSV and the saveEdit `cleaned` block). No Qt."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set

from ctwa.analysis.jsmath import (JS_WHITESPACE, js_number_to_string, js_to_fixed, js_to_precision,
                                  js_truthy)
from ctwa.analysis.lag_fit import describe_lag_model
from ctwa.results.helpers import format_alpha, row_matches, sort_key_test_date, with_ln_validity
from ctwa.ui.results.fmt import js_str

DASH = "—"


@dataclass(frozen=True)
class SummaryCol:
    key: str
    label: str
    numeric: bool
    editable: bool


_TEXT_KEYS = {"model_name", "test_date", "gas_atmosphere", "analysis_mode", "calibration_model",
              "calibration_ref_ids", "use_calibration"}
_READONLY = {"id", "calibration_model", "calibration_ref_ids"}
_COLS = (
    ("id", "ID"), ("model_name", "Model"), ("test_date", "Date"), ("temperature_c", "T (°C)"),
    ("gas_atmosphere", "Atmosphere"), ("analysis_mode", "Mode"), ("r1_mm", "r₁ (mm)"), ("r2_mm", "r₂ (mm)"),
    ("amplitude_a1", "A₁ (mW)"), ("amplitude_a2", "A₂ (mW)"), ("period_t", "Src Period (s)"),
    ("period_t_resp", "Resp Period (s)"), ("frequency_f", "Src f (Hz)"), ("frequency_f_resp", "Resp f (Hz)"),
    ("angular_freq_w", "ω (rad/s)"), ("raw_lag_dt", "Δt (s)"), ("raw_phase_phi", "φ (rad)"),
    ("ln_term", "ln term"), ("alpha_combined_raw", "α comb (raw)"), ("alpha_phase_raw", "α phase (raw)"),
    ("use_calibration", "Cal"), ("system_lag", "Lag (s)"), ("calibration_model", "Cal source"),
    ("calibration_ref_ids", "Refs"), ("net_lag_dt", "Net Δt (s)"), ("alpha_combined_cal", "α comb (cal)"),
    ("alpha_phase_cal", "α phase (cal)"),
)
SUMMARY_COLS: List[SummaryCol] = [SummaryCol(k, l, k not in _TEXT_KEYS, k not in _READONLY) for k, l in _COLS]


# ---- cell text ----

def _num(v: Any) -> float:
    """Number(v) of a stored value."""
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    from ctwa.analysis.jsmath import js_number
    return js_number(str(v))


def _fixed(digits: int, null_text: Optional[str] = None) -> Callable[[Any], str]:
    """Number(v).toFixed(digits); with null_text, a null shows that text instead (v != null ? ... : x)."""
    def f(v: Any) -> str:
        if v is None and null_text is not None:
            return null_text
        return js_to_fixed(_num(v), digits)
    return f


def _alpha(v: Any) -> str:
    n = _num(v)
    if n != n:
        return "NaN"   # formatAlpha(NaN) in the webapp
    return format_alpha(n)


def _gas(v: Any) -> str:
    return js_str(v) if v is not None and v != "" else DASH


def _refs(v: Any) -> str:
    n = len([s for s in js_str(v).split(",") if s.strip(JS_WHITESPACE)])
    return DASH if n == 0 else "%d ref%s" % (n, "" if n == 1 else "s")


_FMT: Dict[str, Callable[[Any], str]] = {
    "temperature_c": _fixed(1, "25.0"),
    "gas_atmosphere": _gas,
    "r1_mm": _fixed(2), "r2_mm": _fixed(2),
    "amplitude_a1": _fixed(4), "amplitude_a2": _fixed(4),
    "period_t": _fixed(2), "period_t_resp": _fixed(2, DASH),
    "frequency_f": _fixed(6), "frequency_f_resp": _fixed(6, DASH),
    "angular_freq_w": _fixed(5), "raw_lag_dt": _fixed(2), "raw_phase_phi": _fixed(4), "ln_term": _fixed(4),
    "alpha_combined_raw": _alpha, "alpha_phase_raw": _alpha,
    "use_calibration": lambda v: "✓" if js_truthy(v) else "✗",
    "system_lag": _fixed(1, DASH),
    "calibration_model": lambda v: describe_lag_model(v),
    "calibration_ref_ids": _refs,
    "net_lag_dt": _fixed(2, DASH),
    "alpha_combined_cal": _alpha, "alpha_phase_cal": _alpha,
}


def format_cell(key: str, row: Dict[str, Any]) -> str:
    """The text the Summary table shows for row[key]."""
    v = row.get(key)
    f = _FMT.get(key)
    return f(v) if f else (DASH if v is None else js_str(v))


# ---- column presets ----

PRESETS: Dict[str, Optional[List[str]]] = {
    "key": ["test_date", "temperature_c", "analysis_mode", "period_t", "raw_lag_dt", "ln_term", "alpha_phase_raw",
            "alpha_combined_raw", "use_calibration", "alpha_phase_cal", "alpha_combined_cal"],
    "cal": ["test_date", "temperature_c", "period_t", "raw_lag_dt", "use_calibration", "system_lag",
            "calibration_model", "calibration_ref_ids", "net_lag_dt", "alpha_phase_raw", "alpha_phase_cal",
            "alpha_combined_cal"],
    "all": None,
}
ALWAYS_SHOWN = {"id", "model_name"}


def hidden_for_preset(name: str) -> List[str]:
    keep = PRESETS[name]
    if keep is None:
        return []
    return [c.key for c in SUMMARY_COLS if c.key not in ALWAYS_SHOWN and c.key not in keep]


def preset_of(hidden: set) -> str:
    for name in PRESETS:
        if set(hidden_for_preset(name)) == set(hidden):
            return name
    return "custom"


# ---- rows ----

def base_order(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Newest test date first (unparsable = 1970, ties keep input order), each row through
    with_ln_validity. Inputs are not modified."""
    ordered = sorted(rows, key=lambda r: sort_key_test_date(r.get("test_date")), reverse=True)
    return [with_ln_validity(r) for r in ordered]


def filter_rows(rows: List[Dict[str, Any]], *, model: str = "All", mode: str = "All", cal: str = "All",
                ids: Optional[Set[int]] = None, query: str = "") -> List[Dict[str, Any]]:
    out = []
    for a in rows:
        if ids is not None and a.get("id") not in ids:
            continue
        if model != "All" and a.get("model_name") != model:
            continue
        if mode != "All" and a.get("analysis_mode") != mode:
            continue
        if cal == "Calibrated Only" and not js_truthy(a.get("use_calibration")):
            continue
        if cal == "Non-Calibrated Only" and js_truthy(a.get("use_calibration")):
            continue
        if query and not row_matches(a, query):
            continue
        out.append(a)
    return out


def _avg(rows: List[Dict[str, Any]], key: str) -> str:
    vals = []
    for a in rows:
        v = a.get(key)
        if v is not None and not isinstance(v, bool) and v > 0:
            vals.append(v)
    if not vals:
        return DASH
    total = 0.0
    for v in vals:            # a plain left-to-right sum, as reduce() does
        total += v
    return js_to_precision(total / len(vals) * 1e6, 4) + " mm²/s"


def summary_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"total": len(rows), "models": len({a.get("model_name") for a in rows}),
            "avg_raw": _avg(rows, "alpha_combined_raw"), "avg_cal": _avg(rows, "alpha_combined_cal")}


# ---- CSV ----

def _csv_cell(s: str) -> str:
    if any(ch in s for ch in ',"\n\r'):
        return '"' + s.replace('"', '""') + '"'
    return s


def csv_text(rows: List[Dict[str, Any]]) -> str:
    """downloadCSV: all 27 columns, formatted columns as shown, the others raw ('' for None), joined by
    "\\n" with no trailing newline. Cells are quoted only when needed (the webapp never quotes)."""
    lines = [",".join(_csv_cell(c.label) for c in SUMMARY_COLS)]
    for a in rows:
        cells = []
        for c in SUMMARY_COLS:
            if c.key in _FMT:
                cells.append(format_cell(c.key, a))
            else:
                cells.append(js_str(a.get(c.key)))
        lines.append(",".join(_csv_cell(s) for s in cells))
    return "\n".join(lines)


def csv_bytes(rows: List[Dict[str, Any]]) -> bytes:
    """The file as saved: UTF-8 with a BOM so Excel shows α, Δ, ω."""
    return b"\xef\xbb\xbf" + csv_text(rows).encode("utf-8")


# ---- editing ----

NUMERIC_EDIT_KEYS = {
    "temperature_c", "r1_mm", "r2_mm", "amplitude_a1", "amplitude_a2", "period_t", "frequency_f",
    "angular_freq_w", "raw_lag_dt", "raw_phase_phi", "ln_term", "alpha_combined_raw", "alpha_phase_raw",
    "system_lag", "net_lag_dt", "alpha_combined_cal", "alpha_phase_cal",
    "period_t_resp", "frequency_f_resp",
}
_NEVER_SENT = {"id", "created_at", "graph_image", "extra_data", "graph_json"}

_FLOAT_PREFIX = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?", re.ASCII)


def parse_float_js(text: Any) -> Optional[float]:
    """parseFloat(text) as the webapp stores it: the longest numeric prefix; None when there is none
    (NaN) or the value is not finite (Infinity is sent as null by JSON.stringify)."""
    s = js_str(text).lstrip(JS_WHITESPACE)
    m = _FLOAT_PREFIX.match(s)
    if not m:
        return None
    v = float(m.group(0))
    return v if math.isfinite(v) else None


def _same(a: Optional[float], b: Optional[float]) -> bool:
    return a == b


def build_update(stored: Dict[str, Any], edits: Dict[str, Any]) -> Dict[str, Any]:
    """The fields to send for an edit: only those whose parsed value differs from the stored row.
    `edits` holds what the editor shows (strings; a bool for use_calibration)."""
    out: Dict[str, Any] = {}
    for k, v in edits.items():
        if k in _NEVER_SENT:
            continue
        old = stored.get(k)
        if k in NUMERIC_EDIT_KEYS:
            new = parse_float_js(v) if isinstance(v, str) else (None if v is None else v)
            if isinstance(old, bool) or not (old is None or isinstance(old, (int, float))):
                old = None
            if not _same(new, None if old is None else float(old)):
                out[k] = new
        elif k == "use_calibration":
            if bool(v) != bool(old):
                out[k] = bool(v)
        else:
            new = "" if v is None else v
            if new != ("" if old is None else old):
                out[k] = new
    return out
