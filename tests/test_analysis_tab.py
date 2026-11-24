"""The Analysis tab: plot, settings, Analyze, results (offscreen, real worker)."""

from __future__ import annotations

import gzip
import json
import os
import shutil
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ctwa.analysis.jsmath import js_to_precision  # noqa: E402
from ctwa.ui.analysis_tab import AnalysisTab  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS_DIR = os.path.join(HERE, "data", "runs")
GOLDEN_DIR = os.path.join(HERE, "golden", "analysis")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def run_file(tmp_path_factory):
    out = tmp_path_factory.mktemp("ana") / "al2o3_ctwa.csv"
    with gzip.open(os.path.join(RUNS_DIR, "al2o3_ctwa.csv.gz"), "rb") as src, open(out, "wb") as dst:
        shutil.copyfileobj(src, dst)
    return str(out)


def golden(name):
    with open(os.path.join(GOLDEN_DIR, name)) as f:
        return json.load(f)


def wait_until(cond, timeout_s=30.0):
    loop = QEventLoop()
    deadline = time.time() + timeout_s
    t = QTimer()
    t.setInterval(10)

    def poll():
        if cond() or time.time() > deadline:
            loop.quit()

    t.timeout.connect(poll)
    t.start()
    loop.exec()
    t.stop()
    return cond()


@pytest.fixture
def tab(qapp, run_file):
    w = AnalysisTab()
    w.resize(1200, 800)
    w.open_run(run_file)
    assert wait_until(lambda: w.run is not None), "run did not load"
    yield w
    w.worker.shutdown()


def settle(w):
    """Wait for the markers' snapping (period / smoothed series from the worker)."""
    assert wait_until(lambda: not w.is_snapping()), "markers never settled"


def analyze_and_wait(w):
    w.analyze_btn.click()
    assert wait_until(lambda: w.analyze_btn.isEnabled() and not w.is_running())


def test_open_run_sets_region_to_default_selection(tab):
    sel_min, sel_max, _clicks = tab.run.default
    lo, hi = tab.region.getRegion()
    assert (lo, hi) == (sel_min, sel_max)
    assert tab.analyze_btn.isEnabled()
    assert not tab.cancel_btn.isVisibleTo(tab)


def test_autofit_shows_alpha_phase_raw_from_golden(tab):
    case = golden("al2o3_ctwa__AutoFit_raw.json")
    tab.settings.calib_check.setChecked(False)  # the golden case: raw, no lag
    tab.settings.lag_spin.setValue(0)
    tab.region.setRegion((case["options"]["selMin"], case["options"]["selMax"]))
    got = []
    tab.result_ready.connect(got.append)
    analyze_and_wait(tab)
    expected = js_to_precision(case["results"]["alphaPhaseRaw"] * 1e6, 4)
    assert tab.results_panel.text("alpha_phase_raw") == expected
    assert len(got) == 1
    run, opts, res = got[0]
    assert run is tab.run
    assert (opts.sel_min, opts.sel_max) == (case["options"]["selMin"], case["options"]["selMax"])
    assert opts.params.analysis_mode == "AutoFit"
    assert opts.params.manual_snap is False
    assert res.alpha_phase_raw == pytest.approx(case["results"]["alphaPhaseRaw"], rel=1e-9)
    # other fields: lag with 1 decimal and its SE, amplitudes with 3 significant figures
    lag = case["results"]["netLagDt"]
    se = case["results"]["lagSe"]
    assert tab.results_panel.text("lag") == "%.1f ± %.1f" % (lag, se)
    assert tab.results_panel.text("a1") == js_to_precision(case["results"]["amplitudeA1"], 3)
    assert not tab.results_panel.warning_visible()


def test_manual_shows_four_markers_and_drop_snaps_to_peak(tab):
    assert not any(m.isVisible() for m in tab.markers)
    tab.settings.set_mode("Manual")
    tab.show()
    assert all(m.isVisible() for m in tab.markers)
    assert len(tab.markers) == 4
    settle(tab)
    # a marker dropped away from any peak moves onto the nearest source peak
    x0 = tab.markers[0].value()
    T = 80.24
    off = x0 + T / 4.0
    tab.markers[0].setValue(off)
    tab.markers[0].sigPositionChangeFinished.emit(tab.markers[0])
    settle(tab)
    x = tab.markers[0].value()
    assert x != off
    assert abs(x - off) <= T / 4.0 + 1.0
    ts, vs = tab.run.synced.t_src, tab.run.synced.v_src
    near = [v for t, v in zip(ts, vs) if abs(t - x) <= T / 10.0]
    here = min(zip(ts, vs), key=lambda p: abs(p[0] - x))[1]
    span = max(vs) - min(vs)
    assert here >= max(near) - 0.1 * span


def test_manual_run_sends_marker_times_as_placed(tab):
    # the default region spans idle gaps between bursts, where the webapp's own Manual
    # analysis also fails (golden al2o3_ctwa__Manual_raw); use one burst
    tab.region.setRegion((10700, 12000))
    tab.region.sigRegionChangeFinished.emit(tab.region)
    tab.settings.set_mode("Manual")
    tab.show()
    tab.settings.calib_check.setChecked(False)
    assert not tab.analyze_btn.isEnabled()  # markers still being placed
    settle(tab)
    assert tab.analyze_btn.isEnabled()
    got = []
    tab.result_ready.connect(got.append)
    analyze_and_wait(tab)
    assert len(got) == 1, tab.results_panel.message()
    opts = got[0][1]
    assert opts.params.analysis_mode == "Manual"
    assert opts.params.manual_snap is False
    assert [c[0] for c in opts.clicks] == [m.value() for m in tab.markers]


def test_too_few_points_shows_webapp_message(tab):
    tab.region.setRegion((5463, 5466))
    got = []
    tab.result_ready.connect(got.append)
    analyze_and_wait(tab)
    assert tab.results_panel.message() == \
        "Selected region has too few data points. Widen the selection range."
    assert got == []


@pytest.mark.parametrize("kind,message,expected", [
    ("pipeline", "parseFailed", "Could not parse one or both files. Check the file format."),
    ("pipeline", "notEnoughOverlap",
     "Not enough overlapping data after clock synchronisation. Check start times."),
    ("pipeline", "smoothFailed",
     "Could not fit a sine to the selected region — widen it or check the signal."),
    ("analysis", "Need at least 3 click coordinates for manual analysis",
     "Need at least 3 click coordinates for manual analysis"),
    ("crash", "boom", "The analysis process stopped unexpectedly; press Analyze to try again."),
])
def test_error_mapping(tab, kind, message, expected):
    tab.worker.failed.emit(kind, message)
    assert tab.results_panel.message() == expected
    assert tab.analyze_btn.isEnabled()


def test_analyze_twice_quickly_runs_once(tab):
    calls = []
    real = tab.worker.analyze
    tab.worker.analyze = lambda *a, **k: (calls.append(a), real(*a, **k))[1]
    got = []
    tab.result_ready.connect(got.append)
    tab.analyze_btn.click()
    assert not tab.analyze_btn.isEnabled()
    assert tab.cancel_btn.isVisibleTo(tab)
    tab.analyze_btn.click()  # disabled: no second job
    assert wait_until(lambda: not tab.is_running())
    assert len(calls) == 1
    assert len(got) == 1


def test_cancel_returns_to_idle_without_result(tab):
    got = []
    tab.result_ready.connect(got.append)
    tab.analyze_btn.click()
    tab.cancel_btn.click()
    assert tab.analyze_btn.isEnabled()
    assert not tab.cancel_btn.isVisibleTo(tab)
    wait_until(lambda: False, 0.5)
    assert got == []


def test_settings_follow_mode_and_wave(tab):
    s = tab.settings
    assert s.mode() == "AutoFit"
    assert s.period_spin.isVisibleTo(s)       # override: AutoFFT / AutoFit only
    s.set_mode("Auto")
    assert not s.period_spin.isVisibleTo(s)
    s.set_wave("square")
    assert s.square_spin.isVisibleTo(s)
    assert not s.mode_combo.isVisibleTo(s)
    assert not s.smooth_check.isVisibleTo(s)
    p = s.build_params()
    assert (p.r1_mm, p.r2_mm) == (6.72, 14.86)
    assert (p.t_cal, p.t_src) == ("00:00:00", "00:00:00")
    assert p.c80_time_unit == "Seconds" and p.c80_pwr_unit == "mW"
    assert p.src_time_unit == "Seconds" and p.src_pwr_unit == "Watts"  # the page's useState defaults


def test_open_run_while_analyzing_drops_the_old_result(tab, run_file):
    got = []
    tab.result_ready.connect(got.append)
    tab.analyze_btn.click()
    assert tab.is_running()
    tab.open_run(run_file)
    assert not tab.is_running()
    assert tab.run is None
    assert tab.title.text().endswith("loading\u2026")
    assert len(tab.src_curve.xData if tab.src_curve.xData is not None else []) == 0
    assert wait_until(lambda: tab.run is not None)
    wait_until(lambda: False, 4.0)
    assert got == []
    assert tab.results_panel.text("alpha_phase_raw") == "\u2014"


def test_region_and_markers_locked_while_running(tab):
    tab.settings.set_mode("Manual")
    settle(tab)
    assert tab.region.movable and all(m.movable for m in tab.markers)
    tab.analyze_btn.click()
    assert tab.is_running()
    assert not tab.region.movable
    assert not any(m.movable for m in tab.markers)
    assert wait_until(lambda: not tab.is_running())
    assert tab.region.movable and all(m.movable for m in tab.markers)


def test_region_edges_are_whole_seconds_after_a_drag(tab):
    tab.region.setRegion((5463.4, 12744.6))
    tab.region.sigRegionChangeFinished.emit(tab.region)
    assert tab.region.getRegion() == (5463, 12745)


def test_marker_stays_where_dropped_when_no_peak_found(tab, monkeypatch):
    import ctwa.ui.analysis_tab as mod
    tab.settings.set_mode("Manual")
    settle(tab)
    monkeypatch.setattr(mod, "refine_peak", lambda *a, **k: None)
    tab.markers[1].setValue(7001.2345)
    tab.markers[1].sigPositionChangeFinished.emit(tab.markers[1])
    settle(tab)
    assert tab.markers[1].value() == 7001.23


@pytest.mark.slow
def test_manual_with_smoothing_snaps_on_the_smoothed_series(tab):
    from ctwa.analysis import runner
    from ctwa.analysis.sine_fit import refine_peak
    tab.settings.set_mode("Manual")
    settle(tab)
    tab.settings.smooth_check.setChecked(True)
    lo, hi = tab.region.getRegion()
    line = tab.markers[0]
    off = 7000.4
    line.setValue(off)
    line.sigPositionChangeFinished.emit(line)
    assert line.value() == off  # smoothing runs in the worker; the marker waits where dropped
    settle(tab)
    assert line.value() != off
    sm = runner.smoothed_region(tab.run.path, lo, hi)
    t_s, v_s = sm[0], sm[1]
    peak = refine_peak(t_s, v_s, off, runner.region_period(tab.run.path, lo, hi))
    expected = round(peak[0] if peak else off, 2)
    assert line.value() == expected


def test_screenshot(tab):
    shot = os.environ.get("CTWA_ANALYSIS_SHOT")
    if not shot:
        pytest.skip("only when CTWA_ANALYSIS_SHOT is set")
    tab.settings.calib_check.setChecked(False)
    tab.show()
    analyze_and_wait(tab)
    tab.grab().save(shot)
