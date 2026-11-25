"""A saved ``graph_image`` as plain dataclasses (no Qt, never raises).

The webapp stores either Plotly JSON ({"data": [...], "layout": {...}}) or, in old rows, a base64
PNG/JPEG. parse_graph turns the text into a StoredFigure or StoredImage, or None when nothing can be
drawn (the History page then shows the alpha bar chart, see bar_values)."""
from __future__ import annotations

import base64
import binascii
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

__all__ = ["Trace", "Shape", "Annotation", "StoredFigure", "StoredImage", "parse_graph", "parse_color",
           "bar_values", "strip_tags"]

Color = Tuple[int, int, int, int]


@dataclass
class Trace:
    name: str
    x: List[float]
    y: List[float]
    color: str
    width: float
    dash: str          # solid | dash | dot | dashdot
    yaxis: str         # "y" | "y2"
    mode: str = "lines"   # Plotly mode: "lines", "markers", "lines+markers"


@dataclass
class Shape:
    x0: float
    y0: float
    x1: float
    y1: float
    xref: str          # "x" | "paper"
    yref: str          # "y" | "y2" | "paper"
    color: str
    width: float
    dash: str


@dataclass
class Annotation:
    x: float
    y: float
    text: str
    xref: str
    yref: str
    xanchor: str
    color: str
    size: float
    bgcolor: Optional[Color]
    mono: bool


@dataclass
class StoredFigure:
    title: str
    x_title: str
    y_title: str
    y2_title: str
    traces: List[Trace]
    shapes: List[Shape]
    annotations: List[Annotation]
    horizontal_legend: bool
    skipped: List[str] = field(default_factory=list)


@dataclass
class StoredImage:
    data: bytes
    fmt: str           # "PNG" | "JPEG"


# ---- small helpers ----

_TAG = re.compile(r"</?[a-zA-Z][^>]*>")


def strip_tags(text: Any) -> str:
    """Plotly's HTML-ish markup (<b>, <br>, <i>, ...) removed."""
    if text is None:
        return ""
    return _TAG.sub("", str(text))


_BR = re.compile(r"<br\s*/?>", re.I)


def _annotation_text(v: Any) -> str:
    """strip_tags, but <br> becomes a line break."""
    return strip_tags(_BR.sub("\n", str(v))) if v is not None else ""


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


_RGB = re.compile(r"rgba?\(\s*([^,)]+),\s*([^,)]+),\s*([^,)]+)(?:,\s*([^,)]+))?\s*\)\Z", re.I)
_BLACK: Color = (0, 0, 0, 255)


def parse_color(s: Any) -> Color:
    """(r, g, b, a) with alpha 0-255 for #rgb, #rrggbb, rgb() and rgba(); black for anything else."""
    if not isinstance(s, str):
        return _BLACK
    t = s.strip()
    try:
        if t.startswith("#"):
            h = t[1:]
            if not re.fullmatch(r"[0-9a-fA-F]+", h):
                return _BLACK
            if len(h) == 3:
                return (int(h[0] * 2, 16), int(h[1] * 2, 16), int(h[2] * 2, 16), 255)
            if len(h) == 6:
                return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
            return _BLACK
        m = _RGB.match(t)
        if m:
            rgb = [max(0, min(255, int(round(float(m.group(i)))))) for i in (1, 2, 3)]
            a = 255 if m.group(4) is None else max(0, min(255, int(round(float(m.group(4)) * 255))))
            return (rgb[0], rgb[1], rgb[2], a)
    except (ValueError, OverflowError):
        pass
    return _BLACK


_DASH = {"solid": "solid", "dot": "dot", "sysdot": "dot", "dash": "dash", "longdash": "dash", "sysdash": "dash",
         "dashdot": "dashdot", "longdashdot": "dashdot"}


def _dash(v: Any) -> str:
    return _DASH.get(v, "solid") if isinstance(v, str) else "solid"


def _dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _text_of(v: Any) -> str:
    """A Plotly title or axis title: a string or {"text": ...}."""
    if isinstance(v, dict):
        v = v.get("text")
    return strip_tags(v) if isinstance(v, str) else ""


# ---- parsing ----

def _floats(v: Any) -> Optional[List[float]]:
    if not isinstance(v, list):
        return None
    out = []
    for p in v:
        if p is None:
            out.append(math.nan)
        else:
            n = _num(p)
            if n is None:
                return None
            out.append(n)
    return out


def _mode(v: Any) -> str:
    if not isinstance(v, str):
        return "lines"
    lines, markers = "lines" in v, "markers" in v
    return "lines+markers" if lines and markers else "markers" if markers else "lines"


def _trace(tr: Any, skipped: List[str]) -> Optional[Trace]:
    if not isinstance(tr, dict):
        return None
    typ = tr.get("type", "scatter")
    if typ not in ("scatter", "scattergl"):
        skipped.append(str(typ))
        return None
    x, y = _floats(tr.get("x")), _floats(tr.get("y"))
    if x is None or y is None or len(x) != len(y):
        skipped.append("scatter (unreadable)")
        return None
    line = _dict(tr.get("line"))
    color = line.get("color")
    width = _num(line.get("width"))
    return Trace(name=str(tr.get("name") or ""), x=x, y=y,
                 color=color if isinstance(color, str) else "#1F5BB0",
                 width=2.0 if width is None else width, dash=_dash(line.get("dash")),
                 yaxis="y2" if tr.get("yaxis") == "y2" else "y", mode=_mode(tr.get("mode")))


def _shape(sh: Any) -> Optional[Shape]:
    if not isinstance(sh, dict) or sh.get("type") != "line":
        return None
    x0, x1, y0, y1 = (_num(sh.get(k)) for k in ("x0", "x1", "y0", "y1"))
    if None in (x0, x1, y0, y1):
        return None
    line = _dict(sh.get("line"))
    color, width = line.get("color"), _num(line.get("width"))
    xref, yref = sh.get("xref"), sh.get("yref")
    return Shape(x0=x0, y0=y0, x1=x1, y1=y1,
                 xref=xref if isinstance(xref, str) else "x", yref=yref if isinstance(yref, str) else "y",
                 color=color if isinstance(color, str) else "#000000",
                 width=1.0 if width is None else width, dash=_dash(line.get("dash")))


def _annotation(an: Any) -> Optional[Annotation]:
    if not isinstance(an, dict):
        return None
    x, y = _num(an.get("x")), _num(an.get("y"))
    if x is None or y is None:
        return None
    font = _dict(an.get("font"))
    color, size, family = font.get("color"), _num(font.get("size")), font.get("family")
    bg = an.get("bgcolor")
    xref, yref, xanchor = an.get("xref"), an.get("yref"), an.get("xanchor")
    return Annotation(x=x, y=y, text=_annotation_text(an.get("text")),
                      xref=xref if isinstance(xref, str) else "x", yref=yref if isinstance(yref, str) else "y",
                      xanchor=xanchor if isinstance(xanchor, str) else "auto",
                      color=color if isinstance(color, str) else "#000000", size=12.0 if size is None else size,
                      bgcolor=parse_color(bg) if isinstance(bg, str) and bg else None,
                      mono=isinstance(family, str) and "mono" in family.lower())


def _image(text: str) -> Optional[StoredImage]:
    try:
        data = base64.b64decode(re.sub(r"\s+", "", text), validate=True)
    except (binascii.Error, ValueError):
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return StoredImage(data, "PNG")
    if data.startswith(b"\xff\xd8\xff"):
        return StoredImage(data, "JPEG")
    return None


def _figure(text: str) -> Optional[StoredFigure]:
    parsed = json.loads(text)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("data"), list):
        return None
    skipped: List[str] = []
    traces = [t for t in (_trace(tr, skipped) for tr in parsed["data"]) if t is not None]
    if not traces:
        return None
    layout = _dict(parsed.get("layout"))
    shapes = layout.get("shapes")
    annotations = layout.get("annotations")
    return StoredFigure(
        title=_text_of(layout.get("title")),
        x_title=_text_of(_dict(layout.get("xaxis")).get("title")),
        y_title=_text_of(_dict(layout.get("yaxis")).get("title")),
        y2_title=_text_of(_dict(layout.get("yaxis2")).get("title")),
        traces=traces,
        shapes=[s for s in (_shape(x) for x in shapes) if s] if isinstance(shapes, list) else [],
        annotations=[a for a in (_annotation(x) for x in annotations) if a] if isinstance(annotations, list) else [],
        horizontal_legend=_dict(layout.get("legend")).get("orientation") == "h",
        skipped=skipped)


def parse_graph(raw: Optional[str]) -> Union[StoredFigure, StoredImage, None]:
    """None when nothing is drawable (also for any text that cannot be read: it never raises)."""
    try:
        if not isinstance(raw, str):
            return None
        text = raw.lstrip()
        if len(text) <= 10 and not text.startswith("{"):
            return None
        if text.startswith("{"):
            return _figure(text)
        if text.startswith("iVBOR") or text.startswith("/9j/"):
            return _image(text)
        return None
    except Exception:
        return None


# ---- fallback bars ----

def bar_values(row: Dict[str, Any]) -> List[Tuple[str, float, str]]:
    """AlphaBarChart of the History page: (label, mm²/s, colour) for each positive alpha."""
    def pos(k: str) -> bool:
        v = row.get(k)
        return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0

    cal = bool(row.get("use_calibration"))
    spec = (("alpha_combined_raw", "α comb (raw)", "#3498db", True), ("alpha_phase_raw", "α phase (raw)", "#e74c3c", True),
            ("alpha_combined_cal", "α comb (cal)", "#2ecc71", cal), ("alpha_phase_cal", "α phase (cal)", "#f39c12", cal))
    return [(label, row[k] * 1e6, color) for k, label, color, on in spec if on and pos(k)]
