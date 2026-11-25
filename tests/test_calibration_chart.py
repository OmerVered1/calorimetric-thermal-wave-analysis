"""FitChart (Plan 4, Task 7): Task 2 fixtures, five references, target 400, sqrt fit."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from ctwa.analysis.calibration_logic import ref_lags, selected_lags, fit_points  # noqa: E402
from ctwa.analysis.lag_fit import fit_lag_models  # noqa: E402
from ctwa.results.helpers import material_color  # noqa: E402
from ctwa.ui.calibration.fit_chart import FitChart  # noqa: E402
from ctwa.ui.calibration.texts import TEXT  # noqa: E402
from tests.calibration_fakes import get_app, make_rows  # noqa: E402


@pytest.fixture
def qapp():
    return get_app()


def setup_data(two_materials=True):
    rows = make_rows()
    refs = [r for r in rows if r.get("is_reference")]
    if two_materials:
        refs[3] = dict(refs[3], model_name="Al₂O₃")
        refs[4] = dict(refs[4], model_name="Al₂O₃")
    sel = selected_lags(ref_lags(refs, "phase"), [r["id"] for r in refs])
    fit = fit_lag_models(fit_points(sel))[0]
    target = next(r for r in rows if r["id"] == 99)
    return fit, sel, target


def brush_hex(item):
    return item.opts["symbolBrush"].color().name().lower()


def test_two_materials_two_scatter_items(qapp):
    fit, sel, target = setup_data()
    c = FitChart()
    c.set_data(fit, sel, target)
    assert not c.isHidden()
    assert len(c.scatter_items) == 2
    assert [i.opts["name"] for i in c.scatter_items] == ["Stainless Steel", "Al₂O₃"]
    for it, name in zip(c.scatter_items, ["Stainless Steel", "Al₂O₃"]):
        assert brush_hex(it) == material_color(name).lower()
        pts = [x for x in sel if x.ref["model_name"] == name]
        assert list(it.xData) == [x.ref["period_t"] for x in pts]
        assert list(it.yData) == [x.lag for x in pts]
        assert it.opts["symbolSize"] == 9


def test_curve_region_target_star(qapp):
    fit, sel, target = setup_data()
    c = FitChart()
    c.set_data(fit, sel, target)
    assert len(c.curve_item.xData) == 120
    assert c.curve_item.xData[0] == 75 and c.curve_item.xData[-1] == pytest.approx(1200, rel=1e-9)
    lo, hi = c.region_item.getRegion()
    assert (lo, hi) == (pytest.approx(math.log10(75)), pytest.approx(math.log10(1200)))
    assert not c.region_item.movable
    assert c.target_line.value() == pytest.approx(math.log10(400))
    assert c.target_line.angle == 90
    assert c.star_item.xData[0] == 400 and c.star_item.yData[0] == pytest.approx(47.25456790896485)
    assert c.star_item.opts["symbolSize"] == 15 and c.star_item.opts["symbol"] == "star"
    assert c.star_item.opts["name"] == "#99"
    assert c.item.vb.state["logMode"][0] is True
    assert c.plot.height() == 340 or c.plot.maximumHeight() == 340


def test_target_outside_range_still_drawn(qapp):
    fit, sel, target = setup_data()
    c = FitChart()
    c.set_data(fit, sel, dict(target, period_t=3600))
    assert c.target_line.value() == pytest.approx(math.log10(3600))
    assert c.star_item is not None and c.star_item.xData[0] == 3600


def test_no_fit_hides(qapp):
    fit, sel, target = setup_data()
    c = FitChart()
    c.set_data(fit, sel, target)
    c.set_data(None, [], None)
    assert c.isHidden()
    c.set_data(fit, [], target)
    assert c.isHidden()


def test_no_target(qapp):
    fit, sel, _ = setup_data()
    c = FitChart()
    c.set_data(fit, sel, None)
    assert c.target_line is None and c.star_item is None and not c.isHidden()


def test_nonfinite_prediction_no_star(qapp):
    fit, sel, target = setup_data()
    bad = type(fit)(**{**fit.__dict__, "predict": lambda p: float("nan") if p == 400 else fit.predict(p)})
    c = FitChart()
    c.set_data(bad, sel, target)
    assert c.star_item is None and c.target_line is not None


def test_set_data_twice_replaces_items(qapp):
    fit, sel, target = setup_data()
    c = FitChart()
    c.set_data(fit, sel, target)
    n = len(c.item.items)
    c.set_data(fit, sel, target)
    assert len(c.item.items) == n


def test_titles(qapp):
    c = FitChart()
    assert c.item.titleLabel.text and TEXT["fitChartTitle"] in c.item.titleLabel.text
