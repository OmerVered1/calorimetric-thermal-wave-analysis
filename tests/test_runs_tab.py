"""The Runs tab: scanning, saved-analysis counts, recording lock, folders."""

from __future__ import annotations

import gzip
import os
import re
import shutil
import time
from datetime import datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QModelIndex, QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ctwa.cloud.client import Offline  # noqa: E402
from ctwa.ui import run_index  # noqa: E402
from ctwa.ui.runs_tab import COLUMNS, RunsTab  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(HERE, "data", "runs")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def unpack(name, dest):
    os.makedirs(dest, exist_ok=True)
    out = os.path.join(dest, name + ".csv")
    with gzip.open(os.path.join(RUNS, name + ".csv.gz"), "rb") as f, open(out, "wb") as g:
        shutil.copyfileobj(f, g)
    return out


def make_run(path, started="2026-11-17 09:10:19", last=123.5, mean_t=25.0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = [f"# Started: {started}", "# Experiment: x",
             "Index,Channel,Computer_Time,Elapsed(s),Voltage(V),Current(A),"
             "Resistance(Ohm),Power(mW),Heat Flow(mW),Sample Temperature(°C)"]
    for i in range(20):
        t = last * i / 19
        lines.append(f"{i},A,2026,{t:.3f},1,1,1,{i},{i * 0.5},{mean_t}")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


class FakeClient:
    def __init__(self, rows=None, error=None):
        self.rows, self.error, self.calls = rows or [], error, []

    def select(self, table, query):
        self.calls.append(query)
        if self.error:
            raise self.error
        out = self.rows
        for key in ("c80_filename", "test_date"):
            if key in query:
                vals = {v.replace('\\"', '"') for v in re.findall(r'"((?:[^"\\]|\\.)*)"', query[key])}
                out = [r for r in out if r.get(key) in vals]
        return list(out)


@pytest.fixture
def env(qapp, tmp_path):
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    auto = tmp_path / "auto"
    auto.mkdir()

    def make(client=None, **kw):
        return RunsTab(str(auto), client=client, settings=settings,
                       cache_path=str(tmp_path / "cache" / "c.json"), **kw)
    return make, auto, settings, tmp_path


def settle(tab):
    tab.wait_for_workers()
    QCoreApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, 0)
    QCoreApplication.processEvents()


def cell(tab, row, col, role=Qt.DisplayRole):
    return tab.model.index(row, col).data(role)


def row_of(tab, name):
    return [r.name for r in tab.model.runs].index(name)


# -- scan ---------------------------------------------------------------------

def test_scan_finds_runs_with_started_and_length(tmp_path):
    a = unpack("al2o3_ctwa", str(tmp_path / "x"))
    b = unpack("fiber_75_105", str(tmp_path / "x" / "sub"))
    (tmp_path / "x" / "notes.txt").write_text("hello")
    runs = {r.name: r for r in run_index.scan([str(tmp_path / "x")])}
    assert set(runs) == {"al2o3_ctwa.csv", "fiber_75_105.csv"}
    assert runs["al2o3_ctwa.csv"].started == datetime(2026, 11, 17, 9, 10, 19)
    assert runs["al2o3_ctwa.csv"].length_s == pytest.approx(18207.041078)
    assert runs["fiber_75_105.csv"].started == datetime(2026, 8, 30, 10, 52, 14)
    assert runs["fiber_75_105.csv"].length_s == pytest.approx(12599.93345)
    assert all(r.is_capture for r in runs.values())


def test_scan_skips_hidden_folders_and_caps(tmp_path):
    make_run(str(tmp_path / ".hidden" / "h.csv"))
    for i in range(5):
        make_run(str(tmp_path / f"r{i}.csv"))
    runs, truncated = run_index.scan_limited([str(tmp_path)], limit=3)
    assert len(runs) == 3 and truncated
    runs, truncated = run_index.scan_limited([str(tmp_path)])
    assert len(runs) == 5 and not truncated


def test_scan_flags_non_capture_but_lists_it(tmp_path):
    (tmp_path / "other.csv").write_text("a,b,c\n1,2,3\n")
    [r] = run_index.scan([str(tmp_path)])
    assert not r.is_capture and r.started is None


def test_scan_of_100_files_is_fast(tmp_path):
    for i in range(100):
        make_run(str(tmp_path / f"r{i}.csv"))
    t0 = time.perf_counter()
    assert len(run_index.scan([str(tmp_path)])) == 100
    assert time.perf_counter() - t0 < 0.5   # budget is 50 ms; slack for slow CI disks


def test_mean_temperature_cache_keyed_by_mtime_and_size(tmp_path):
    p = make_run(str(tmp_path / "r.csv"), mean_t=30.0)
    [r] = run_index.scan([str(tmp_path)])
    cache = run_index.MeanTempCache(str(tmp_path / "c" / "cache.json"))
    assert cache.lookup(r) == (False, None)
    cache.put(r, run_index.compute_mean_temperature(r))
    cache.save()
    again = run_index.MeanTempCache(str(tmp_path / "c" / "cache.json"))
    assert again.lookup(r) == (True, pytest.approx(30.0))
    with open(p, "a") as f:
        f.write("20,A,2026,200,1,1,1,1,1,30\n")
    [r2] = run_index.scan([str(tmp_path)])
    assert again.lookup(r2) == (False, None)


# -- tab ------------------------------------------------------------------------

def test_columns(env):
    make, *_ = env
    tab = make()
    assert COLUMNS == ["Name", "Started", "Length", "Saved analyses", "Sample", "Temperature"]
    assert [tab.model.headerData(i, Qt.Horizontal) for i in range(6)] == COLUMNS


def test_exact_and_same_day_counts(env):
    make, auto, *_ = env
    make_run(str(auto / "exp" / "a.csv"), started="2026-11-17 09:00:00")
    make_run(str(auto / "exp" / "b.csv"), started="2026-11-17 11:00:00")
    make_run(str(auto / "exp" / "c.csv"), started="2026-10-01 11:00:00")
    rows = [
        {"id": 1, "c80_filename": "a.csv", "model_name": "old", "test_date": "17/11/2026"},
        {"id": 5, "c80_filename": "a.csv", "model_name": "newest", "test_date": "17/11/2026"},
        {"id": 3, "c80_filename": None, "model_name": "legacy", "test_date": "17/11/2026"},
        {"id": 4, "c80_filename": "zzz.csv", "model_name": "other", "test_date": "05/05/2026"},
    ]
    tab = make(FakeClient(rows))
    tab.refresh()
    settle(tab)
    a, b, c = (row_of(tab, n) for n in ("a.csv", "b.csv", "c.csv"))
    assert cell(tab, a, 3) == "2" and cell(tab, a, 4) == "newest"
    assert cell(tab, a, 3, Qt.ForegroundRole) is None
    # b has no exact match: same day (17/11/2026) holds 3 rows, shown grey with the tooltip
    assert cell(tab, b, 3) == "3" and cell(tab, b, 4) == ""
    assert cell(tab, b, 3, Qt.ForegroundRole) is not None
    assert cell(tab, b, 3, Qt.ToolTipRole) == "same day; older results don't record their file"
    assert cell(tab, c, 3) == "0"


def test_offline_shows_dash_with_reason(env):
    make, auto, *_ = env
    make_run(str(auto / "a.csv"))
    tab = make(FakeClient(error=Offline("no network")))
    tab.refresh()
    settle(tab)
    assert cell(tab, 0, 3) == "—" and cell(tab, 0, 4) == "—"
    assert "Offline" in cell(tab, 0, 3, Qt.ToolTipRole)


def test_no_client_shows_dash(env):
    make, auto, *_ = env
    make_run(str(auto / "a.csv"))
    tab = make(None)
    tab.refresh()
    settle(tab)
    assert cell(tab, 0, 3) == "—"


def test_mean_temperature_filled_in_by_worker_and_cached(env):
    make, auto, _, tmp = env
    make_run(str(auto / "a.csv"), mean_t=27.5)
    tab = make(FakeClient())
    tab.refresh()
    settle(tab)
    assert cell(tab, 0, 5) == "27.5 °C"
    assert os.path.exists(tmp / "cache" / "c.json")
    tab2 = make(FakeClient())
    tab2.refresh()   # straight from the cache, before any worker finishes
    assert cell(tab2, 0, 5) == "27.5 °C"
    settle(tab2)


def test_length_formatted(env):
    make, auto, *_ = env
    make_run(str(auto / "a.csv"), last=3725)
    tab = make(FakeClient())
    tab.refresh()
    settle(tab)
    assert cell(tab, 0, 2) == "1:02:05"


def test_recording_path_disables_analyze(env):
    make, auto, *_ = env
    p = make_run(str(auto / "a.csv"))
    make_run(str(auto / "b.csv"))
    tab = make(FakeClient())
    tab.refresh()
    tab.set_recording_path(p)
    got = []
    tab.open_run.connect(got.append)
    tab.table.selectRow(row_of(tab, "a.csv"))
    assert cell(tab, row_of(tab, "a.csv"), 2) == "recording"
    assert not tab.analyze_btn.isEnabled()
    tab.analyze_selected()
    assert got == []
    tab.table.selectRow(row_of(tab, "b.csv"))
    assert tab.analyze_btn.isEnabled()
    tab.analyze_btn.click()
    assert got == [os.path.normpath(str(auto / "b.csv"))]
    tab.set_recording_path(None)
    tab.table.selectRow(row_of(tab, "a.csv"))
    assert tab.analyze_btn.isEnabled()
    settle(tab)


def test_non_capture_file_cannot_be_analyzed(env):
    make, auto, *_ = env
    (auto / "other.csv").write_text("a,b\n1,2\n")
    tab = make(FakeClient())
    tab.refresh()
    tab.table.selectRow(0)
    assert not tab.analyze_btn.isEnabled()
    assert tab.analyze_btn.toolTip() == "Not a CTWA/C80 one-file capture"
    settle(tab)


def test_double_click_opens(env):
    make, auto, *_ = env
    make_run(str(auto / "a.csv"))
    tab = make(FakeClient())
    tab.refresh()
    got = []
    tab.open_run.connect(got.append)
    tab.table.selectRow(0)
    tab.table.doubleClicked.emit(tab.model.index(0, 0))
    assert len(got) == 1
    settle(tab)


def test_added_folder_persists_and_auto_folder_cannot_be_removed(env):
    make, auto, settings, tmp = env
    extra = tmp / "extra"
    make_run(str(extra / "e.csv"))
    tab = make(FakeClient())
    assert tab.add_folder(str(extra))
    settle(tab)
    assert [r.name for r in tab.model.runs] == ["e.csv"]
    tab2 = make(FakeClient())
    assert tab2.folders() == [str(auto), os.path.normpath(str(extra))]
    tab2.refresh()
    assert [r.name for r in tab2.model.runs] == ["e.csv"]
    assert not tab2.remove_folder(str(auto))
    assert tab2.remove_folder(str(extra))
    assert make(FakeClient()).folders() == [str(auto)]
    settle(tab2)
    settle(tab)


def test_stale_results_from_an_earlier_refresh_are_ignored(env):
    make, auto, *_ = env
    make_run(str(auto / "a.csv"))
    tab = make(FakeClient())
    tab.refresh()
    tab._on_cloud_error(tab._gen - 1, "stale")
    assert tab.model.cloud_state == "loading"
    settle(tab)
