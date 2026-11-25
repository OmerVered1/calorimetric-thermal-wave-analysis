"""Row model of the Statistics page: extractors, groups, bands, formatting (page.tsx L35-158).

Rows are the DB's snake_case dicts (alphas in m^2/s as stored); extractors return alphas in mm^2/s.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ctwa.analysis.jsmath import js_div, js_round, js_to_precision
from ctwa.analysis.lag_fit import describe_lag_model
from ctwa.results.helpers import material_color, run_label, with_ln_validity

__all__ = ["PERIOD_SOURCES", "get_period", "get_frequency", "round10", "YMetric", "Y_METRICS", "Y_BY_KEY",
           "X_AXES", "GROUP_OPTIONS", "extract_y", "extract_x", "group_value", "period_band", "temp_band",
           "prepare_rows", "fmt_g", "run_label_text", "color_for", "finite_or_none"]

PERIOD_SOURCES = ("src", "resp")


def _num(v: Any) -> Optional[float]:
    """A finite number or None (JS null/NaN/Infinity collapse to the page's null)."""
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def finite_or_none(v: Any) -> Optional[float]:
    return _num(v)


def get_period(row: Dict[str, Any], source: str) -> Optional[float]:
    if source == "resp":
        return _num(row.get("period_t_resp"))
    return _num(row.get("period_t"))


def get_frequency(row: Dict[str, Any], source: str) -> Optional[float]:
    if source == "resp":
        return _num(row.get("frequency_f_resp"))
    return _num(row.get("frequency_f"))


def round10(p: float) -> int:
    """Math.round(p / 10) * 10 (JS rounding: half up)."""
    return int(js_round(p / 10) * 10)


@dataclass(frozen=True)
class YMetric:
    key: str
    label: str
    is_alpha: bool = False


Y_METRICS: Tuple[YMetric, ...] = (
    YMetric("alpha_combined_raw", "α Combined (raw) mm²/s", True),
    YMetric("alpha_phase_raw", "α Phase (raw) mm²/s", True),
    YMetric("alpha_combined_cal", "α Combined (cal) mm²/s", True),
    YMetric("alpha_phase_cal", "α Phase (cal) mm²/s", True),
    YMetric("raw_lag_dt", "Raw Time Lag Δt (s)"),
    YMetric("raw_phase_phi", "Raw Phase φ (rad)"),
    YMetric("ln_term", "ln term"),
    YMetric("amplitude_a1", "A₁ (mW)"),
    YMetric("amplitude_a2", "A₂ (mW)"),
    YMetric("a1_a2_ratio", "A₁/A₂ ratio"),
    YMetric("period_t", "Period (s)"),
    YMetric("temperature_c", "Temperature (°C)"),
)
Y_BY_KEY: Dict[str, YMetric] = {m.key: m for m in Y_METRICS}

X_AXES: Tuple[str, ...] = ("Period (s)", "Frequency (Hz)", "Temperature (°C)", "Raw Δt (s)", "ln term",
                           "A₁/A₂ ratio", "System Lag (s)", "A₁ (mW)", "A₂ (mW)")

GROUP_OPTIONS: Tuple[str, ...] = ("Model", "Model + Period", "Period (exact)", "Period Band", "Temp Band",
                                  "Calibration", "Analysis Mode", "Reference Status", "Lag Model")


def _alpha_mm2s(v: Any) -> Optional[float]:
    """(v ?? 0) > 0 ? v * 1e6 : null"""
    f = _num(v)
    if f is None or not f > 0:
        return None
    return _num(f * 1e6)


def _ratio(row: Dict[str, Any]) -> Optional[float]:
    a2 = row.get("amplitude_a2")
    if a2 is not None and a2 == 0:
        return None
    a1 = row.get("amplitude_a1")
    return _num(js_div(float(a1 or 0), float(a2 or 0)))


def extract_y(row: Dict[str, Any], key: str, source: str = "src") -> Optional[float]:
    if key in ("alpha_combined_raw", "alpha_phase_raw", "alpha_combined_cal", "alpha_phase_cal"):
        return _alpha_mm2s(row.get(key))
    if key == "a1_a2_ratio":
        return _ratio(row)
    if key == "period_t":
        return get_period(row, source)   # the page's "Override Y extract when the Y metric is Period"
    if key in Y_BY_KEY:
        return _num(row.get(key))
    raise KeyError(key)


def extract_x(row: Dict[str, Any], axis: str, source: str = "src") -> Optional[float]:
    if axis == "Period (s)":
        return get_period(row, source)
    if axis == "Frequency (Hz)":
        return get_frequency(row, source)
    if axis == "Temperature (°C)":
        return _num(row.get("temperature_c"))
    if axis == "Raw Δt (s)":
        return _num(row.get("raw_lag_dt"))
    if axis == "ln term":
        return _num(row.get("ln_term"))
    if axis == "A₁/A₂ ratio":
        return _ratio(row)
    if axis == "System Lag (s)":
        return _num(row.get("system_lag"))
    if axis == "A₁ (mW)":
        return _num(row.get("amplitude_a1"))
    if axis == "A₂ (mW)":
        return _num(row.get("amplitude_a2"))
    return None


def period_band(p: float) -> str:
    if p < 200:
        return "< 200 s"
    if p < 400:
        return "200–400 s"
    if p < 700:
        return "400–700 s"
    if p < 1200:
        return "700–1200 s"
    return "> 1200 s"


def temp_band(t: Optional[float]) -> str:
    t = 25 if t is None else t
    if t < 50:
        return "< 50 °C"
    if t < 100:
        return "50–100 °C"
    if t < 200:
        return "100–200 °C"
    if t < 300:
        return "200–300 °C"
    return "> 300 °C"


def group_value(row: Dict[str, Any], group_by: str, source: str = "src") -> Optional[str]:
    if group_by == "Model + Period":
        p = get_period(row, source)
        return "%s | %ds" % (row.get("model_name"), round10(p)) if p is not None else None
    if group_by == "Period (exact)":
        p = get_period(row, source)
        return "%d s" % round10(p) if p is not None else None
    if group_by == "Period Band":
        p = get_period(row, source)
        return period_band(p) if p is not None else None
    if group_by == "Temp Band":
        return temp_band(_num(row.get("temperature_c")))
    if group_by == "Calibration":
        return "Calibrated" if row.get("use_calibration") else "Uncalibrated"
    if group_by == "Analysis Mode":
        return row.get("analysis_mode")
    if group_by == "Reference Status":
        if row.get("is_reference"):
            return "Reference"
        return "Calibrated copy" if row.get("calibrated_from_id") is not None else "Measurement"
    if group_by == "Lag Model":
        if row.get("calibration_model"):
            return describe_lag_model(row["calibration_model"])
        return "unknown" if row.get("calibrated_from_id") is not None else "not reference-calibrated"
    return row.get("model_name")   # "Model" and the page's default


NO_MODEL = "(none)"


def prepare_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """with_ln_validity on every row (new dicts; the input is untouched); an empty model name reads "(none)"."""
    out = []
    for r in rows:
        r = with_ln_validity(r)
        if not r.get("model_name"):
            r = dict(r, model_name=NO_MODEL)
        out.append(r)
    return out


def fmt_g(x: float, sig: int) -> str:
    """d3-format ".{sig}~g": toPrecision(sig), then insignificant trailing zeros trimmed."""
    s = js_to_precision(x, sig)
    if "e" in s:
        mant, exp = s.split("e")
    else:
        mant, exp = s, ""
    if "." in mant:
        mant = mant.rstrip("0").rstrip(".")
    return mant + ("e" + exp if exp else "")


def run_label_text(row: Dict[str, Any]) -> str:
    """The page's runLabelText: "Model · T °C · {Math.round(period)} s · #id" (the foundation's run_label)."""
    return run_label(row)


def color_for(name: Optional[str]) -> str:
    return material_color(name)
