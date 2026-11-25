"""FigureView (Results tab, Task 5): offscreen drawing of stored figures, images and the bar fallback."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QFontInfo, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ctwa.ui.results.figure_model import bar_values  # noqa: E402
from ctwa.ui.results.figure_view import FigureView  # noqa: E402

DATA = Path(__file__).parent / "data" / "results"
ROW = {"alpha_combined_raw": 8.5e-6, "alpha_phase_raw": 9.1234e-6, "use_calibration": True,
       "alpha_combined_cal": 8e-6, "alpha_phase_cal": None}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def view(qapp):
    v = FigureView()
    v.resize(640, 420)
    v.show()
    qapp.processEvents()
    yield v
    v.close()


def fixture_text(name="fig_web.json"):
    return (DATA / name).read_text(encoding="utf-8")


def fig_text(mutate):
    d = json.loads(fixture_text())
    mutate(d)
    return json.dumps(d)


def image_b64(fmt, w=120, h=60, wrap=True):
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor("#336699"))
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, fmt)
    s = base64.b64encode(bytes(ba)).decode()
    return "\n".join(s[i:i + 76] for i in range(0, len(s), 76)) if wrap else s


def test_web_figure(view):
    view.show_graph(fixture_text(), ROW)
    assert view.mode() == "figure" and view.note() == ""
    assert view.curve_count() == 1 and view.curve_count(True) == 1
    assert view.legend_labels() == ["Source", "Response"]
    assert view.axis_titles() == ("Time (s)", "Source Power (mW)", "Response Power (mW)")


def test_shapes(view, qapp):
    view.show_graph(fixture_text(), ROW)
    lines = view.line_items()
    horiz = [l for l in lines if l[5] != "paper"]
    assert len(horiz) == 6 and all(l[1] == l[3] for l in horiz)
    assert sorted((l[4], l[5]) for l in horiz) == sorted([("dash", "y"), ("dash", "y2"), ("dot", "y"), ("dot", "y"),
                                                           ("dot", "y2"), ("dot", "y2")])
    paper = [l for l in lines if l[5] == "paper"]
    assert len(paper) == 3 and all(l[4] == "dashdot" and (l[1], l[3]) == (0, 1) for l in paper)

    def check():
        vb = view.plot_item().vb
        rect = vb.sceneBoundingRect()
        for pl in view.paper_lines():
            ys = pl.curve.getData()[1]
            a = vb.mapViewToScene(QPointF(0, ys[0])).y()
            b = vb.mapViewToScene(QPointF(0, ys[1])).y()
            assert abs(abs(a - b) - rect.height()) < 1.0
    check()
    view.resize(900, 600)
    qapp.processEvents()
    check()
    view.plot_item().vb.setYRange(-5, 50, padding=0)
    qapp.processEvents()
    check()
    assert view.plot_item().vb.viewRange()[1] == pytest.approx([-5, 50])


def test_annotations(view):
    view.show_graph(fixture_text(), ROW)
    assert view.annotation_texts() == ["Src Peak 1", "  Src peak: 13.80", "Resp peak: 31.40  "]
    items = view.annotation_items()
    for it in items[1:]:
        assert it.fill.color().alpha() == 204
        f = it.textItem.font()
        assert f.styleHint() == QFont.Monospace or QFontInfo(f).fixedPitch()
    assert items[0].fill.style() == Qt.NoBrush or items[0].fill.color().alpha() == 0


def test_legend_is_one_row(view):
    view.show_graph(fixture_text(), ROW)
    lg = view.legend_item()
    assert lg.columnCount == 2
    pos = [round(lab.geometry().y()) for _, lab in lg.items]
    assert len(set(pos)) == 1


@pytest.mark.parametrize("fmt", ["PNG", "JPEG"])
def test_image(view, qapp, fmt):
    view.show_graph(image_b64(fmt), ROW)
    assert view.mode() == "image"
    pm = view.image_label().pixmap()
    assert pm is not None and not pm.isNull()
    lab = view.image_label().size()
    scaled = pm.size()
    assert scaled.width() <= lab.width() and scaled.height() <= lab.height()
    assert abs(scaled.width() / scaled.height() - 2.0) < 0.05
    assert scaled.width() == lab.width() or scaled.height() == lab.height()


@pytest.mark.parametrize("raw", [None, "{}", "{not json", fixture_text("fig_web.json")[:0] + '{"data":[{"type":"bar","x":[1],"y":[2]}]}'])
def test_bars_fallback(view, raw):
    view.show_graph(raw, ROW)
    assert view.mode() == "bars"
    assert view.bar_labels() == [b[0] for b in bar_values(ROW)]


def test_no_alpha_is_empty(view):
    view.show_graph(None, {"use_calibration": False})
    assert view.mode() == "empty" and view.note() == "No stored graph"


def test_extra_bar_trace_is_noted(view):
    def add(d):
        d["data"].append({"type": "bar", "x": [1], "y": [2]})
    view.show_graph(fig_text(add), ROW)
    assert view.mode() == "figure" and view.note() == "Not drawn: bar"


def test_odd_references_do_not_raise(view):
    def add(d):
        d["layout"]["shapes"].append({"type": "line", "xref": "paper", "yref": "y2", "x0": 0, "x1": 1, "y0": 3, "y1": 4})
        d["layout"]["annotations"].append({"x": 0.5, "y": 0.5, "xref": "paper", "yref": "paper", "text": "mid"})
    view.show_graph(fig_text(add), ROW)
    assert view.mode() == "figure" and "mid" in view.annotation_texts()


def test_switching_leaves_one_set_of_items(view):
    def count():
        pi = view.plot_item()
        return (len(pi.vb.addedItems), len(view._view2.addedItems), len(pi.scene().items()))
    view.show_graph(fixture_text(), ROW)
    first = count()
    view.show_graph(None, ROW)
    assert view.curve_count() == 0 and view.line_items() == []
    view.show_graph(fixture_text(), ROW)
    assert count() == first
    view.show_graph(None, ROW)
    view.show_graph(None, ROW)
    assert len(view._view2.addedItems) == 0 and view.legend_labels() == []


def test_old_colours(view):
    view.show_graph(fixture_text("fig_old_colors.json"), ROW)
    h = view._handles
    assert h.curves[0].opts["pen"].color().name() == "#3498db"
    assert h.curves2[0].opts["pen"].color().name() == "#e74c3c"


def test_trace_modes(view):
    def mark(d):
        d["data"][0]["mode"] = "markers"
        d["data"][1]["mode"] = "lines+markers"
    view.show_graph(fig_text(mark), ROW)
    a, b = view._handles.curves[0], view._handles.curves2[0]
    assert a.opts["pen"] is None or a.opts["pen"].style() == Qt.NoPen
    assert a.opts["symbol"] == "o"
    assert b.opts["symbol"] == "o" and b.opts["pen"] is not None and b.opts["pen"].style() != Qt.NoPen
    view.show_graph(fixture_text(), ROW)
    c = view._handles.curves[0]
    assert c.opts["symbol"] is None and c.opts["pen"].style() != Qt.NoPen


def test_annotation_line_break(view):
    def br(d):
        d["layout"]["annotations"][0]["text"] = "Src<br>Peak 1"
    view.show_graph(fig_text(br), ROW)
    assert view.annotation_texts()[0] == "Src\nPeak 1"
    assert view.annotation_items()[0].textItem.toPlainText() == "Src\nPeak 1"


def test_loading_and_clear(view):
    view.show_loading()
    assert view.mode() == "loading"
    view.show_graph(fixture_text(), ROW)
    view.clear()
    assert view.mode() == "empty" and view.curve_count() == 0
