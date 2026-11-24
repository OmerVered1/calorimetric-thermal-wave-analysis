"""The analysis runs in its own process; the Qt bridge hands results to the GUI thread."""

from __future__ import annotations

import gzip
import json
import math
import os
import shutil
import time
from datetime import datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS_DIR = os.path.join(HERE, "data", "runs")
GOLDEN_DIR = os.path.join(HERE, "golden", "analysis")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _unzip(name, tmp_path):
    out = tmp_path / (name + ".csv")
    with gzip.open(os.path.join(RUNS_DIR, name + ".csv.gz"), "rb") as src, open(out, "wb") as dst:
        shutil.copyfileobj(src, dst)
    return str(out)


def _opts(golden_name):
    from tests.test_analysis_matches_webapp import build_options
    with open(os.path.join(GOLDEN_DIR, golden_name)) as f:
        case = json.load(f)
    return build_options(case["options"]), case


class Collector:
    def __init__(self, worker):
        self.events = []
        worker.loaded.connect(lambda r: self.events.append(("loaded", r)))
        worker.finished.connect(lambda r: self.events.append(("finished", r)))
        worker.failed.connect(lambda k, m: self.events.append(("failed", (k, m))))

    def wait(self, timeout_s=30.0):
        loop = QEventLoop()
        deadline = time.time() + timeout_s
        t = QTimer()
        t.setInterval(10)

        def poll():
            if self.events or time.time() > deadline:
                loop.quit()
        t.timeout.connect(poll)
        t.start()
        loop.exec()
        t.stop()
        assert self.events, "no signal within %s s" % timeout_s
        return self.events.pop(0)


@pytest.fixture
def worker(qapp):
    from ctwa.ui.analysis_worker import AnalysisWorker
    w = AnalysisWorker()
    yield w
    w.shutdown()


# ---- header and load_run --------------------------------------------------

def test_parse_run_header_tolerates_quoted_lines():
    from ctwa.analysis.run_header import parse_run_header
    h = parse_run_header([
        "# Run 1",
        "# Started: 2026-11-17 09:10:19",
        "# Experiment: new proble",
        '"# Instrument: Keithley Instruments Inc., Model 2602B, 4316588, 3.2.2"',
        '"# Calorimeter: Drop (Alexsys) @ 169.254.185.1  channels=hf,t,ext_t"',
        "Index,Channel",
    ])
    assert h["started"] == datetime(2026, 11, 17, 9, 10, 19)
    assert h["experiment"] == "new proble"
    assert h["instrument"] == "Keithley Instruments Inc., Model 2602B, 4316588, 3.2.2"
    assert h["calorimeter"].startswith("Drop (Alexsys) @ 169.254.185.1")


def test_parse_run_header_missing_fields_are_none():
    from ctwa.analysis.run_header import parse_run_header
    h = parse_run_header("Time (s),Heat Flow(mW)\n1,2\n")
    assert h == {"started": None, "experiment": None, "instrument": None, "calorimeter": None}
    assert parse_run_header("# Started: not a date")["started"] is None


def test_load_run_ctwa(tmp_path):
    import pickle
    from ctwa.analysis.runner import load_run
    run = load_run(_unzip("al2o3_ctwa", tmp_path))
    assert len(run.synced.t_src) == 17700
    assert run.header["started"] == datetime(2026, 11, 17, 9, 10, 19)
    assert run.header["experiment"] == "new proble Al2O3 test short 50-100 15mw 17112026"
    assert "2602B" in run.header["instrument"]
    assert "Drop (Alexsys)" in run.header["calorimeter"]
    lo, hi, clicks = run.default
    assert lo < hi and len(clicks) == 4
    assert run.mean_temperature is not None and math.isfinite(run.mean_temperature)
    assert len(pickle.loads(pickle.dumps(run)).parsed.time) == 17700


def test_load_run_c80_has_no_header(tmp_path):
    from ctwa.analysis.runner import load_run
    run = load_run(_unzip("al2o3_c80", tmp_path))
    assert run.header["calorimeter"] is None and run.header["started"] is None


def test_worker_cache_keyed_by_path_mtime_size_max_three(tmp_path):
    from ctwa.analysis import runner
    runner._CACHE.clear()
    p = _unzip("al2o3_ctwa", tmp_path)
    a = runner.load_run(p)
    assert runner.load_run(p) is a
    os.utime(p, ns=(1, 1))
    assert runner.load_run(p) is not a
    for i in range(4):
        q = str(tmp_path / ("c%d.csv" % i))
        shutil.copy(p, q)
        runner.load_run(q)
    assert len(runner._CACHE) <= 3


# ---- the Qt bridge ---------------------------------------------------------

def test_worker_load_emits_loaded(worker, tmp_path):
    c = Collector(worker)
    worker.load(_unzip("al2o3_ctwa", tmp_path))
    kind, run = c.wait()
    assert kind == "loaded" and len(run.synced.t_src) == 17700


def test_worker_analyze_matches_golden(worker, tmp_path):
    opts, case = _opts("al2o3_ctwa__AutoFit_raw.json")
    c = Collector(worker)
    worker.analyze(_unzip("al2o3_ctwa", tmp_path), opts)
    kind, res = c.wait()
    assert kind == "finished"
    assert math.isclose(res.alpha_phase_raw, case["results"]["alphaPhaseRaw"], rel_tol=1e-9)


def test_worker_garbage_file_is_pipeline_parse_failed(worker, tmp_path):
    p = tmp_path / "garbage.csv"
    p.write_bytes(b"this is\nnot a run\n")
    opts, _ = _opts("al2o3_ctwa__AutoFit_raw.json")
    c = Collector(worker)
    worker.analyze(str(p), opts)
    assert c.wait() == ("failed", ("pipeline", "parseFailed"))
    worker.load(str(p))
    assert c.wait() == ("failed", ("pipeline", "parseFailed"))


def test_worker_too_few_points_is_pipeline_error(worker, tmp_path):
    opts, _ = _opts("al2o3_ctwa__AutoFit_raw.json")
    opts.sel_min, opts.sel_max = -5.0, -4.0
    c = Collector(worker)
    worker.analyze(_unzip("al2o3_ctwa", tmp_path), opts)
    assert c.wait() == ("failed", ("pipeline", "tooFewPoints"))


def test_worker_value_error_is_analysis_failure(worker, tmp_path):
    opts, case = _opts("al2o3_ctwa__Manual_raw.json")
    c = Collector(worker)
    worker.analyze(_unzip("al2o3_ctwa", tmp_path), opts)
    assert c.wait() == ("failed", ("analysis", case["error"]))


def test_worker_cancel_drops_result_and_next_works(worker, tmp_path):
    p = _unzip("al2o3_ctwa", tmp_path)
    opts, case = _opts("al2o3_ctwa__AutoFit_raw.json")
    c = Collector(worker)
    worker.analyze(p, opts)
    worker.cancel()
    worker.analyze(p, opts)
    kind, res = c.wait()
    assert kind == "finished"
    assert math.isclose(res.alpha_phase_raw, case["results"]["alphaPhaseRaw"], rel_tol=1e-9)
    assert c.events == []


@pytest.mark.slow
def test_worker_crash_then_next_analyze_succeeds(worker, tmp_path):
    p = _unzip("fiber_150_600", tmp_path)
    opts, case = _opts("fiber_150_600__AutoFit_raw.json")
    c = Collector(worker)
    worker.analyze(p, opts)
    # wait for the worker process to exist, then kill it while it computes
    deadline = time.time() + 20
    while time.time() < deadline:
        procs = list(getattr(worker._executor, "_processes", {}).values())
        if procs:
            break
        QApplication.processEvents()
        time.sleep(0.02)
    assert procs
    time.sleep(1.0)
    for pr in procs:
        pr.terminate()
    kind, payload = c.wait()
    assert kind == "failed" and payload[0] == "crash" and payload[1]
    worker.analyze(p, opts)
    kind, res = c.wait(60)
    assert kind == "finished"
    assert math.isclose(res.alpha_phase_raw, case["results"]["alphaPhaseRaw"], rel_tol=1e-9)


@pytest.mark.slow
def test_gui_thread_not_blocked_during_analysis(worker, tmp_path):
    p = _unzip("fiber_150_600", tmp_path)
    opts, _ = _opts("fiber_150_600__AutoFit_raw.json")
    c = Collector(worker)
    # let the process start before timing (spawn cost is not what is measured)
    worker.load(p)
    c.wait(60)
    ticks = []
    t = QTimer()
    t.setInterval(20)
    t.timeout.connect(lambda: ticks.append(time.perf_counter()))
    t.start()
    worker.analyze(p, opts)
    start = time.perf_counter()
    kind, _ = c.wait(60)
    t.stop()
    assert kind == "finished"
    elapsed = time.perf_counter() - start
    assert elapsed > 0.5, "analysis too quick to show anything"
    expected = int(elapsed / 0.020)
    missed = expected - len(ticks)
    assert missed <= 5, "GUI thread starved: %d of %d ticks missed" % (missed, expected)
