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
    run, opts, res, plot = got[0]
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
    assert tab.title.text().endswith("Loading...")
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


def test_failed_region_request_frees_the_tab(tab):
    tab.settings.set_mode("Manual")
    settle(tab)
    tab.region.setRegion((10700, 12000))
    tab.region.sigRegionChangeFinished.emit(tab.region)
    assert tab.is_snapping()
    assert not tab.analyze_btn.isEnabled()
    before = [m.value() for m in tab.markers]
    tab.worker.region_failed.emit("crash", "boom")
    assert not tab.is_snapping()
    assert tab.analyze_btn.isEnabled()
    assert [m.value() for m in tab.markers] == before
    assert tab.results_panel.message() == \
        "Couldn't snap the markers; they stay where you dropped them."
    assert tab._pending == {} and not tab._place_pending


def test_region_request_that_really_fails_in_the_worker(tab):
    tab.settings.set_mode("Manual")
    settle(tab)
    failed, region_failed = [], []
    tab.worker.failed.connect(lambda k, m: failed.append((k, m)))
    tab.worker.region_failed.connect(lambda k, m: region_failed.append((k, m)))
    tab.run.path = tab.run.path + ".gone"   # the worker cannot stat it
    tab.region.setRegion((10600, 11900))
    tab.region.sigRegionChangeFinished.emit(tab.region)
    assert tab.is_snapping()
    assert wait_until(lambda: not tab.is_snapping())
    assert len(region_failed) == 1 and failed == []
    assert tab.analyze_btn.isEnabled()
    assert "Couldn't snap" in tab.results_panel.message()


def test_analysis_failure_after_a_snap_shows_the_analysis_error(tab):
    tab.settings.set_mode("Manual")
    settle(tab)   # a snap finished; the default region is gappy, so Manual analysis fails
    tab.settings.calib_check.setChecked(False)
    analyze_and_wait(tab)
    msg = tab.results_panel.message()
    assert "disagree" in msg and "Couldn't snap" not in msg


def test_pending_items_of_an_older_region_are_dropped(tab):
    tab.settings.set_mode("Manual")
    settle(tab)
    tab.region.setRegion((10600, 11900))   # a region the worker has not seen yet
    tab.markers[0].setValue(7000.0)
    tab.markers[0].sigPositionChangeFinished.emit(tab.markers[0])
    assert tab._pending == {0: 7000.0}
    tab.region.setRegion((10700, 12000))
    tab.markers[1].setValue(11000.0)
    tab.markers[1].sigPositionChangeFinished.emit(tab.markers[1])
    assert 0 not in tab._pending and 1 in tab._pending


def test_screenshot(tab):
    shot = os.environ.get("CTWA_ANALYSIS_SHOT")
    if not shot:
        pytest.skip("only when CTWA_ANALYSIS_SHOT is set")
    tab.settings.calib_check.setChecked(False)
    tab.show()
    analyze_and_wait(tab)
    tab.grab().save(shot)


# ---- final fix wave ----

def _trip_gui_maths(monkeypatch):
    """The maths belongs in the analysis process. Make every heavy function raise when it is
    called in THIS (GUI) process; the spawned child imports its own, untouched copies."""
    import importlib

    def boom(*a, **k):
        raise AssertionError("analysis maths ran in the GUI process")
    for mod, names in (
            ("ctwa.analysis.sine_fit", ("sine_lag", "remove_period_mean")),
            ("ctwa.analysis.smoothing", ("smooth_to_shared_sine",)),
            ("ctwa.analysis.row", ("build_analysis_plot", "smooth_to_shared_sine")),
            ("ctwa.analysis.pipeline", ("run_one_file_pipeline", "load_one_file")),
            ("ctwa.analysis.modes", ("run_auto_fit_analysis",)),
            ("ctwa.analysis.runner", ("sine_lag", "remove_period_mean", "smooth_to_shared_sine",
                                      "build_analysis_plot", "run_one_file_pipeline", "load_one_file",
                                      "run_auto_fit_analysis", "parse_combined_file")),
            ("ctwa.ui.analysis_tab", ("sine_lag", "remove_period_mean")),
            ("ctwa.ui.save_panel", ("build_analysis_plot", "smooth_to_shared_sine")),
            ("ctwa.ui.run_index", ("parse_combined_file", "compute_mean_temperature"))):
        m = importlib.import_module(mod)
        for n in names:
            if hasattr(m, n):
                monkeypatch.setattr(m, n, boom)


def test_manual_flow_and_save_never_run_the_maths_in_the_gui_process(tab, monkeypatch):
    from types import SimpleNamespace
    from ctwa.ui.save_panel import SavePanel
    _trip_gui_maths(monkeypatch)
    inserts = []

    class Client:
        def select(self, table, query):
            return []

        def insert(self, table, row):
            inserts.append(row)
            return dict(row, id=1)
    panel = SavePanel(SimpleNamespace(client=Client(), login_succeeded=lambda: None,
                                      request_flush=lambda: None, enqueue=lambda r: None))
    tab.set_save_panel(panel)
    tab.region.setRegion((10700, 12000))
    tab.region.sigRegionChangeFinished.emit(tab.region)
    tab.settings.set_mode("Manual")
    tab.settings.smooth_check.setChecked(True)
    tab.settings.calib_check.setChecked(False)
    settle(tab)
    placed = [m.value() for m in tab.markers]
    assert placed == sorted(placed[:2]) + sorted(placed[2:]) and placed[0] != placed[1]
    tab.markers[0].setValue(placed[0] + 3.0)               # a drop: snaps from the worker's series
    tab.markers[0].sigPositionChangeFinished.emit(tab.markers[0])
    settle(tab)
    tab.region.setRegion((10600, 11900))                   # a region change: placed again
    tab.region.sigRegionChangeFinished.emit(tab.region)
    settle(tab)
    analyze_and_wait(tab)
    assert tab.results_panel.message() == "", tab.results_panel.message()
    assert panel._plot is not None            # built in the process, carried by result_ready
    panel.sample_edit.setText("Alumina")
    panel.save_btn.click()
    assert wait_until(lambda: len(inserts) == 1)
    assert "graph_image" in inserts[0]
    panel.shutdown()


def test_manual_markers_placed_by_the_worker_match_the_webapp_placement(tab):
    """The same times the GUI used to compute itself, now computed in the process."""
    import math
    from ctwa.analysis.sine_fit import sine_lag
    from ctwa.analysis import runner
    tab.region.setRegion((10700, 12000))
    tab.region.sigRegionChangeFinished.emit(tab.region)
    tab.settings.set_mode("Manual")
    settle(tab)
    lo, hi = tab.region.getRegion()
    s = tab.run.synced
    ts = [t for t in s.t_src if lo <= t <= hi]
    vs = [v for t, v in zip(s.t_src, s.v_src) if lo <= t <= hi]
    tc = [t for t in s.t_cal if lo <= t <= hi]
    vc = [v for t, v in zip(s.t_cal, s.v_cal) if lo <= t <= hi]
    T = runner.region_period(tab.run.path, lo, hi)
    fit = sine_lag(ts, vs, tc, vc, T)
    info = runner.region_info(tab.run.path, lo, hi, False)
    assert info.period == T
    first, last, r1, r2 = info.placement
    assert r1 == pytest.approx(first + fit.lag) and r2 == pytest.approx(last + fit.lag)
    w = 2 * math.pi / T
    assert (first * w - fit.phase_src) / (2 * math.pi) == pytest.approx(round((first * w - fit.phase_src) / (2 * math.pi)))


class _PanelSpy:
    """A SavePanel stand-in that records what the tab tells it."""

    def __init__(self):
        self.events = []

    def clear_result(self):
        self.events.append("cleared")

    def set_result(self, payload):
        self.events.append("result")


def test_result_cleared_on_open_analyze_and_failure(tab, run_file):
    spy = _PanelSpy()
    tab.result_ready.connect(spy.set_result)
    tab.result_cleared.connect(spy.clear_result)
    analyze_and_wait(tab)
    assert spy.events == ["cleared", "result"]            # Analyze start clears, the result arrives
    tab.worker.failed.emit("analysis", "boom")
    assert spy.events[-1] == "cleared"                    # a failure clears
    n = len(spy.events)
    tab.open_run(run_file)
    assert spy.events[n:] == ["cleared"]                  # opening a run clears
    assert wait_until(lambda: tab.run is not None)


def test_save_is_disabled_after_open_run_analyze_start_and_failure(tab, run_file):
    from types import SimpleNamespace
    from ctwa.ui.save_panel import SavePanel
    panel = SavePanel(SimpleNamespace(client=None, login_succeeded=lambda: None))
    tab.set_save_panel(panel)
    analyze_and_wait(tab)
    assert panel.save_btn.isEnabled()
    tab.open_run(run_file)                      # run B (here: the file again) while A's result stands
    assert not panel.save_btn.isEnabled()
    assert wait_until(lambda: tab.run is not None)
    analyze_and_wait(tab)
    assert panel.save_btn.isEnabled()
    tab.analyze_btn.click()                     # a new Analyze starts: the old result is gone
    assert not panel.save_btn.isEnabled()
    assert wait_until(lambda: not tab.is_running())
    assert panel.save_btn.isEnabled()
    tab.worker.failed.emit("analysis", "boom")  # a failed analysis
    assert not panel.save_btn.isEnabled()
    panel.shutdown()


def test_opening_a_file_that_is_not_a_capture_says_so(qapp, tmp_path):
    bad = tmp_path / "garbage.csv"
    bad.write_bytes(b"this is\nnot a run\n")
    w = AnalysisTab()
    try:
        w.open_run(str(bad))
        assert w.title.text().endswith("Loading...")
        assert wait_until(lambda: not w._loading)
        assert w.results_panel.message() == "This file isn't a CTWA/C80 one-file capture."
        assert w.title.text() == "garbage.csv"
        assert not w.analyze_btn.isEnabled()
    finally:
        w.worker.shutdown()


def test_a_crash_while_loading_says_to_open_the_run_again(qapp, run_file):
    w = AnalysisTab()
    try:
        w.open_run(run_file)
        w.worker.failed.emit("crash", "boom")
        assert w.results_panel.message() == \
            "The analysis process stopped unexpectedly; open the run again."
        assert w.title.text() == os.path.basename(run_file)
    finally:
        w.worker.shutdown()


# ---- save follows staleness; resizable divider ----

def _save_panel(tab):
    from types import SimpleNamespace
    from ctwa.ui.save_panel import SavePanel
    panel = SavePanel(SimpleNamespace(client=None, login_succeeded=lambda: None))
    tab.set_save_panel(panel)
    return panel


def test_save_disabled_when_a_setting_changes_until_reanalyzed(tab):
    panel = _save_panel(tab)
    analyze_and_wait(tab)
    assert panel.save_btn.isEnabled()
    tab.settings.smooth_check.toggle()
    assert not panel.save_btn.isEnabled()
    analyze_and_wait(tab)
    assert panel.save_btn.isEnabled()
    panel.shutdown()


def test_save_disabled_when_the_region_moves_until_reanalyzed(tab):
    panel = _save_panel(tab)
    analyze_and_wait(tab)
    assert panel.save_btn.isEnabled()
    lo, hi = tab.region.getRegion()
    tab.region.setRegion((lo + 5, hi))
    tab.region.sigRegionChangeFinished.emit(tab.region)
    assert not panel.save_btn.isEnabled()
    analyze_and_wait(tab)
    assert panel.save_btn.isEnabled()
    panel.shutdown()


def test_divider_is_a_splitter_with_a_roomy_plot_and_remembers_its_state(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QSplitter
    path = str(tmp_path / "s.ini")
    s1 = QSettings(path, QSettings.IniFormat)
    a = AnalysisTab(settings=s1)
    a.resize(1200, 800)
    a.show()
    wait_until(lambda: False, 0.2)
    assert isinstance(a.splitter, QSplitter)
    plot_h, bottom_h = a.splitter.sizes()
    assert plot_h / (plot_h + bottom_h) >= 0.30
    a.splitter.setSizes([200, 500])
    a.splitter.splitterMoved.emit(200, 1)
    want = a.splitter.sizes()
    a.worker.shutdown()
    s1.sync()
    s2 = QSettings(path, QSettings.IniFormat)
    b = AnalysisTab(settings=s2)
    b.resize(1200, 800)
    b.show()
    qapp.processEvents()
    p, q = b.splitter.sizes()
    assert abs(p / (p + q) - want[0] / sum(want)) < 0.03
    b.worker.shutdown()
