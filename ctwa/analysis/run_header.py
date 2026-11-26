"""The comment lines at the top of a CTWA run CSV (no Qt, no file access)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, Iterable, Optional, Union

from ctwa.experiment_details import parse_number

__all__ = ["parse_run_header"]

_KEYS = {"started": "started", "experiment": "experiment",
         "instrument": "instrument", "calorimeter": "calorimeter",
         "sample": "sample", "powersource": "power_source", "responsedevice": "response_device",
         "gas": "gas", "temperature": "temperature_c",
         "innerradius": "r1_mm", "outerradius": "r2_mm"}
_NUMBERS = ("temperature_c", "r1_mm", "r2_mm")
_LINE = re.compile(r"^#\s*([A-Za-z]+)\s*:\s*(.*?)\s*$")
_MAX_LINES = 60


def _parse_started(value: str) -> Optional[datetime]:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def parse_run_header(text_or_lines: Union[str, Iterable[str]]) -> Dict[str, object]:
    """started (datetime or None), experiment, instrument, calorimeter, sample, power_source,
    response_device, gas (str or None), temperature_c, r1_mm, r2_mm (float or None).

    Reads the leading comment lines only; a line wrapped in double quotes (the
    CSV writer quotes the ones with commas) is unwrapped first."""
    lines = text_or_lines.splitlines() if isinstance(text_or_lines, str) else text_or_lines
    out: Dict[str, object] = {"started": None, "experiment": None,
                              "instrument": None, "calorimeter": None,
                              "sample": None, "power_source": None, "response_device": None,
                              "gas": None, "temperature_c": None, "r1_mm": None, "r2_mm": None}
    for n, raw in enumerate(lines):
        if n >= _MAX_LINES:
            break
        line = raw.strip().lstrip("﻿")
        if len(line) >= 2 and line[0] == '"' and line[-1] == '"':
            line = line[1:-1].replace('""', '"')
        if not line.startswith("#"):
            if line:
                break  # the header row: comments are over
            continue
        line = line.rstrip(",").rstrip()  # a spreadsheet pads comment rows with commas
        m = _LINE.match(line)
        if not m:
            continue
        key = _KEYS.get(m.group(1).lower())
        if key is None or out[key] is not None:
            continue
        value = m.group(2)
        if key == "started":
            out[key] = _parse_started(value)
        elif key in _NUMBERS:
            out[key] = parse_number(value)
        else:
            out[key] = value or None
    return out
