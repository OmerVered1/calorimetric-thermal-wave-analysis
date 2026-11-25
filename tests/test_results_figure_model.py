"""Stored figure model (Results tab, Task 3): graph_image text -> plain dataclasses. Never raises.
Fixtures in tests/data/results are shaped like what the app saves (ctwa.analysis.row.build_analysis_plot);
bar values are the webapp's AlphaBarChart numbers (checked with node: 8.5e-6 * 1e6 === 8.5)."""
from __future__ import annotations

import base64
import json
import math
from pathlib import Path

import pytest

from ctwa.ui.results.figure_model import (Annotation, Shape, StoredFigure, StoredImage, Trace, bar_values,
                                          parse_color, parse_graph, strip_tags)

DATA = Path(__file__).parent / "data" / "results"
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 2
JPG = b"\xff\xd8\xff\xe0" + bytes(range(256)) * 2


def _fixture(name):
    return (DATA / name).read_text(encoding="utf-8")


def _wrapped(b: bytes, every=76):
    s = base64.b64encode(b).decode()
    return "\n".join(s[i:i + every] for i in range(0, len(s), every))


def test_web_figure():
    fig = parse_graph(_fixture("fig_web.json"))
    assert isinstance(fig, StoredFigure)
    assert len(fig.traces) == 2
    src, resp = fig.traces
    assert (src.name, src.yaxis, src.color, src.width, src.dash) == ("Source", "y", "#1F5BB0", 2, "solid")
    assert (resp.name, resp.yaxis, resp.color, resp.width) == ("Response", "y2", "#E4572E", 2)
    assert len(src.x) == len(src.y) == 12
    dashed = [s for s in fig.shapes if s.dash == "dash"]
    dotted = [s for s in fig.shapes if s.dash == "dot"]
    dd = [s for s in fig.shapes if s.dash == "dashdot"]
    assert len(dashed) == 2 and len(dotted) == 4 and len(dd) == 3 and len(fig.shapes) == 9
    assert sorted((s.color, s.yref) for s in dotted) == [("#27ae60", "y")] * 2 + [("#f39c12", "y2")] * 2
    for s in dd:
        assert s.yref == "paper" and s.y0 == 0 and s.y1 == 1 and s.x0 == s.x1
    assert dashed[0].width == 1 and dashed[0].xref == "x"
    assert len(fig.annotations) == 3
    marker, lvl_a, lvl_b = fig.annotations
    assert not marker.mono and marker.bgcolor is None and marker.yref == "paper" and marker.text == "Src Peak 1"
    assert lvl_a.mono and lvl_b.mono
    assert lvl_a.bgcolor == (255, 255, 255, 204) and lvl_b.bgcolor == (255, 255, 255, 204)
    assert lvl_b.xanchor == "right" and lvl_b.yref == "y2" and lvl_a.size == 10
    assert fig.title == "Stable Zone Analysis — Δt = 105.20s"
    assert (fig.x_title, fig.y_title, fig.y2_title) == ("Time (s)", "Source Power (mW)", "Response Power (mW)")
    assert fig.horizontal_legend is True
    assert fig.skipped == []


def test_old_colors_figure_with_string_titles():
    fig = parse_graph(_fixture("fig_old_colors.json"))
    assert isinstance(fig, StoredFigure)
    assert [t.color for t in fig.traces] == ["#3498db", "#e74c3c"]
    assert fig.title == "Stable Zone Analysis — Δt = 105.20s"      # <b> removed, plain-string title
    assert (fig.x_title, fig.y_title, fig.y2_title) == ("Time (s)", "Source Power (mW)", "Response Power (mW)")
    assert fig.horizontal_legend is False
    assert fig.annotations[0].text == "Src Peak 1"


def test_title_forms():
    d = json.loads(_fixture("fig_web.json"))
    d["layout"]["title"] = "<b>Stable Zone Analysis — Δt = 105.20s</b>"
    assert parse_graph(json.dumps(d)).title == "Stable Zone Analysis — Δt = 105.20s"
    d["layout"]["title"] = {"text": "<b>Stable Zone Analysis — Δt = 105.20s</b>"}
    assert parse_graph(json.dumps(d)).title == "Stable Zone Analysis — Δt = 105.20s"
    del d["layout"]["title"]
    assert parse_graph(json.dumps(d)).title == ""
    del d["layout"]
    fig = parse_graph(json.dumps(d))
    assert isinstance(fig, StoredFigure) and fig.shapes == [] and fig.x_title == ""


def test_strip_tags():
    assert strip_tags("<b>Bold</b> text<br>more <i>x</i>") == "Bold textmore x"
    assert strip_tags("a < b") == "a < b"
    assert strip_tags(None) == ""


@pytest.mark.parametrize("data,magic,fmt", [(PNG, b"iVBOR", "PNG"), (JPG, b"/9j/", "JPEG")])
def test_images(data, magic, fmt):
    text = _wrapped(data)
    assert "\n" in text and text.startswith(magic.decode())
    img = parse_graph(text)
    assert isinstance(img, StoredImage) and img.fmt == fmt and img.data == data
    assert parse_graph(base64.b64encode(data).decode()).data == data


def test_bad_images():
    assert parse_graph("iVBOR" + "!!!!not base64!!!!" * 3) is None
    # decodes, but not a PNG
    assert parse_graph(base64.b64encode(b"iVBOR is not a png at all" * 3).decode()) is None
    assert parse_graph("iVBOR" + "A" * 7) is None            # bad padding


@pytest.mark.parametrize("raw", [None, "", "abc", "{", "{}", '{"data":[]}', '{"data":"x"}', "[1,2]", "null",
                                 '{"data":[null,1,"a"]}', '{"data":[{"x":[1,2],"y":[1]}]}',
                                 '{"data":[{"x":["a","b"],"y":[1,2]}]}', '{"data":[{"y":[1,2]}]}', 5, b"{}",
                                 '{"data":[{"type":"scatter","x":[1],"y":[1]}],"layout":5}'][:-1])
def test_unusable(raw):
    assert parse_graph(raw) is None


def test_odd_layout_does_not_raise():
    # layout of the wrong type: the traces still draw
    fig = parse_graph('{"data":[{"type":"scatter","x":[1,2],"y":[1,2]}],"layout":5}')
    assert isinstance(fig, StoredFigure) and fig.shapes == []
    fig = parse_graph(json.dumps({"data": [{"x": [1, 2], "y": [1, 2]}],
                                  "layout": {"shapes": "no", "annotations": [None, 3, {"x": "a"}], "title": 7,
                                             "xaxis": [], "legend": "h"}}))
    assert isinstance(fig, StoredFigure) and fig.annotations == [] and fig.title == ""


def test_bar_trace_skipped():
    d = json.loads(_fixture("fig_web.json"))
    d["data"].append({"type": "bar", "x": ["a"], "y": [1]})
    fig = parse_graph(json.dumps(d))
    assert len(fig.traces) == 2 and fig.skipped == ["bar"]
    only_bar = {"data": [{"type": "bar", "x": ["a", "b"], "y": [1, 2]}], "layout": {}}
    assert parse_graph(json.dumps(only_bar)) is None


def test_dash_names_and_none_points():
    d = {"data": [
        {"x": [0, 1, None, 3], "y": [1, None, 2, 3], "name": "n", "line": {"dash": "longdash"}},
        {"x": [0, 1], "y": [1, 2], "line": {"dash": "sysdash"}},
        {"x": [0, 1], "y": [1, 2], "line": {"dash": "banana"}},
        {"x": [0, 1], "y": [1, 2], "line": {"dash": "sysdot"}},
        {"x": [0, 1], "y": [1, 2], "line": {"dash": "longdashdot"}}],
        "layout": {"shapes": [
            {"type": "line", "x0": 0, "x1": 1, "y0": 0, "y1": 0, "line": {"dash": "longdash"}},
            {"type": "line", "x0": 0, "x1": 1, "y0": 0, "y1": 0, "line": {"dash": "zig"}},
            {"type": "rect", "x0": 0, "x1": 1, "y0": 0, "y1": 0},
            {"type": "line", "x0": "a", "x1": 1, "y0": 0, "y1": 0}]}}
    fig = parse_graph(json.dumps(d))
    assert [t.dash for t in fig.traces] == ["dash", "dash", "solid", "dot", "dashdot"]
    assert math.isnan(fig.traces[0].x[2]) and math.isnan(fig.traces[0].y[1]) and fig.traces[0].x[3] == 3
    assert [s.dash for s in fig.shapes] == ["dash", "solid"]      # rect and non-numeric shapes are dropped
    assert fig.shapes[0].yref == "y" and fig.shapes[0].xref == "x"


def test_shapes_in_paper_and_y2_units_kept():
    d = json.loads(_fixture("fig_web.json"))
    d["layout"]["shapes"].append({"type": "line", "xref": "paper", "x0": 0, "x1": 1, "yref": "y2", "y0": 5, "y1": 5})
    fig = parse_graph(json.dumps(d))
    s = fig.shapes[-1]
    assert (s.xref, s.yref) == ("paper", "y2")


def test_parse_color():
    assert parse_color("rgba(255,255,255,.8)") == (255, 255, 255, 204)
    assert parse_color("rgba(255, 255, 255, 0.8)") == (255, 255, 255, 204)
    assert parse_color("#3498db") == (52, 152, 219, 255)
    assert parse_color("#3498DB") == (52, 152, 219, 255)
    assert parse_color("#fff") == (255, 255, 255, 255)
    assert parse_color("rgb(1, 2, 3)") == (1, 2, 3, 255)
    assert parse_color("rgba(0,0,0,0)") == (0, 0, 0, 0)
    for bad in ("", "red", "#12", "#gggggg", "rgb(1,2)", None, 5, "rgba(a,b,c,d)"):
        assert parse_color(bad) == (0, 0, 0, 255)


def test_bar_values():
    row = {"alpha_combined_raw": 8.5e-6, "alpha_phase_raw": 9e-6, "use_calibration": True,
           "alpha_combined_cal": 8e-6, "alpha_phase_cal": None}
    assert bar_values(row) == [("α comb (raw)", 8.5, "#3498db"), ("α phase (raw)", 9.0, "#e74c3c"),
                               ("α comb (cal)", 8.0, "#2ecc71")]
    assert bar_values(dict(row, use_calibration=False)) == bar_values(row)[:2]
    assert bar_values(dict(row, alpha_phase_cal=1.5e-5))[-1] == ("α phase (cal)", 15.0, "#f39c12")
    assert bar_values({}) == []
    assert bar_values({"alpha_combined_raw": 0, "alpha_phase_raw": -1e-6, "alpha_combined_cal": None}) == []


def test_trace_mode_and_annotation_line_breaks():
    d = json.loads(_fixture("fig_web.json"))
    assert [t.mode for t in parse_graph(json.dumps(d)).traces] == ["lines", "lines"]
    d["data"][0]["mode"] = "markers"
    d["data"][1]["mode"] = "lines+markers"
    d["layout"]["annotations"][0]["text"] = "<b>Src</b><br>Peak 1<br />x"
    fig = parse_graph(json.dumps(d))
    assert [t.mode for t in fig.traces] == ["markers", "lines+markers"]
    assert fig.annotations[0].text == "Src\nPeak 1\nx"
    d["data"][0].pop("mode")
    assert parse_graph(json.dumps(d)).traces[0].mode == "lines"
