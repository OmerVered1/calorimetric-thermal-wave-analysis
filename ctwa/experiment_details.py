"""The run details an experiment carries into every run file (no Qt).

An experiment record holds a `details` dict with the keys of FIELDS. At Start the
non-blank ones are written into the run CSV's comment header as `# Key: value`
lines, and the Analysis tab reads them back (ctwa.analysis.run_header)."""

from __future__ import annotations

import math
import re
from typing import Dict, List, Optional

__all__ = ["FIELDS", "HEADER_KEYS", "DEFAULT_GAS", "DEFAULT_R1_MM", "DEFAULT_R2_MM",
           "default_details", "header_lines", "parse_number"]

FIELDS = (
    ("sample", "Sample"),
    ("power_source", "Power source"),
    ("response_device", "Response device"),
    ("temperature_c", "Temperature (°C)"),
    ("gas", "Gas"),
    ("r1_mm", "Inner radius r₁ (mm)"),
    ("r2_mm", "Outer radius r₂ (mm)"),
)

# details key -> header key (one word, letters only: the parser reads `# Word: value`)
HEADER_KEYS = (
    ("sample", "Sample"),
    ("power_source", "PowerSource"),
    ("response_device", "ResponseDevice"),
    ("temperature_c", "Temperature"),
    ("gas", "Gas"),
    ("r1_mm", "InnerRadius"),
    ("r2_mm", "OuterRadius"),
)
_NUMERIC = ("temperature_c", "r1_mm", "r2_mm")

DEFAULT_GAS = "Ar"
DEFAULT_R1_MM = "6.72"   # = ctwa.ui.analysis_settings.DEFAULT_R1
DEFAULT_R2_MM = "14.86"  # = ctwa.ui.analysis_settings.DEFAULT_R2

_NUMBER = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")


def parse_number(text) -> Optional[float]:
    """'800', '800 °C', '0,5', '6.72 mm' -> float; None when it is not a finite number."""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text) if math.isfinite(text) else None
    if not isinstance(text, str):
        return None
    t = text.strip()
    for unit in ("°C", "mm", "°", "C"):
        if t.endswith(unit):
            t = t[: -len(unit)].strip()
            break
    t = t.replace(",", ".")
    if not _NUMBER.match(t):
        return None
    v = float(t)
    return v if math.isfinite(v) else None


def default_details(instrument: Optional[str], calorimeter: Optional[str]) -> Dict[str, str]:
    """Starting values for a new experiment; devices blank when nothing is connected."""
    from ctwa.ui.save_panel import calorimeter_device, instrument_device
    return {
        "sample": "",
        "power_source": instrument_device(instrument) if instrument else "",
        "response_device": calorimeter_device(calorimeter) if calorimeter else "",
        "temperature_c": "",
        "gas": DEFAULT_GAS,
        "r1_mm": DEFAULT_R1_MM,
        "r2_mm": DEFAULT_R2_MM,
    }


def header_lines(details: Optional[dict]) -> List[str]:
    """`# Key: value` lines for the filled fields; junk numbers are left out."""
    out: List[str] = []
    for key, header_key in HEADER_KEYS:
        raw = (details or {}).get(key)
        text = "" if raw is None else str(raw).strip()
        if not text:
            continue
        if key in _NUMERIC:
            v = parse_number(text)
            if v is None:
                continue
            text = "%g" % v
        else:
            text = " ".join(text.split())  # one line
        out.append("# %s: %s" % (header_key, text))
    return out
