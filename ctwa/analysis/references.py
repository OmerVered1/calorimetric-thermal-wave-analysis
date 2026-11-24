"""Reference material tables (lib/referenceMaterials.ts, lib/materialColors.ts)."""

from __future__ import annotations

from typing import Dict, Optional

from ctwa.analysis.jsmath import js_trim

# Literature thermal diffusivity values, mm^2/s. Temperature dependent, so
# these are only starting points. (The TS table holds {alpha, color}; the
# alpha half is here, the colour half in LITERATURE_COLORS.)
LITERATURE: Dict[str, float] = {
    "Abs": 0.08,
    "Al": 64.0,
    "Brass": 34.1,
    "Stainless Steel": 4.0,
    "Al₂O₃": 8.0,
}

LITERATURE_COLORS: Dict[str, str] = {
    "Abs": "#c0392b",
    "Al": "#d68910",
    "Brass": "#b7950b",
    "Stainless Steel": "#717d7e",
    "Al₂O₃": "#2874a6",
}

LIT_MATERIALS = list(LITERATURE.keys())

_KNOWN: Dict[str, str] = {
    "stainless steel": "#1F5BB0",
    "stainless reverse": "#5B8FD9",
    "al2o3": "#E4572E",
    "al₂o₃": "#E4572E",
    "alumina": "#E4572E",
    "unk foam": "#2A9D8F",
    "unk fiber": "#8E44AD",
    "unk reverse": "#B07CC6",
    "unk left empty right": "#C0392B",
    "empty": "#7F8C8D",
    "abs": "#E9A23B",
    "brass": "#A67C00",
    "al": "#3BA3D9",
    "dc al waveform": "#76C7E8",
    "argon": "#16A085",
    "air": "#95A5A6",
}

_PALETTE = [
    "#1F5BB0", "#E4572E", "#2A9D8F", "#8E44AD", "#E9A23B",
    "#3BA3D9", "#C0392B", "#16A085", "#A67C00", "#D35D9B",
    "#4E6E58", "#6C5CE7",
]

SIGNAL_COLORS = {"source": "#1F5BB0", "response": "#E4572E"}


def _to_int32(n: int) -> int:
    n &= 0xFFFFFFFF
    return n - 0x100000000 if n & 0x80000000 else n


def _hash(s: str) -> int:
    """h = (h*31 + charCodeAt(i)) | 0 over UTF-16 code units; then Math.abs."""
    h = 0
    units = s.encode("utf-16-le")
    for i in range(0, len(units), 2):
        code = units[i] | (units[i + 1] << 8)
        h = _to_int32(h * 31 + code)
    return abs(h)


def _js_lower(s: str) -> str:
    # str.lower() differs from toLowerCase only in context rules (final sigma)
    return s.lower()


def material_color(name: Optional[str]) -> str:
    """colorFor: one colour per name, the same on every chart."""
    key = _js_lower(js_trim("" if name is None else str(name)))
    if not key:
        return "#7F8C8D"
    known = _KNOWN.get(key)
    if known is not None:
        return known
    return _PALETTE[_hash(key) % len(_PALETTE)]
