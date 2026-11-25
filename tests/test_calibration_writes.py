"""WriteQueue over a FakeLoader (Plan 4, Task 4): order, failures, login abort, busy, watchdog, graphs."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from ctwa.ui.calibration import writes  # noqa: E402
from ctwa.ui.calibration.writes import WriteOp, WriteQueue  # noqa: E402
from tests.calibration_fakes import FakeLoader, get_app, wait_until  # noqa: E402


@pytest.fixture
def qapp():
    return get_app()


@pytest.fixture
def env(qapp):
    loader = FakeLoader()
    return loader, WriteQueue(loader)


def updates(n):
    return [WriteOp("update", 10 + i, {"is_reference": True}, "#%d" % (10 + i)) for i in range(n)]


def run(q, ops):
    out = []
    assert q.run(ops, out.append)
    assert wait_until(lambda: out)
    return out[0]


def test_three_updates_in_order(env):
    loader, q = env
    s = run(q, updates(3))
    assert (s.done, s.total, s.failures, s.aborted) == (3, 3, [], None)
    assert [o[1] for o in loader.ops] == [10, 11, 12]
    assert not q.busy


def test_server_failure_continues(env):
    loader, q = env
    loader.fail_at = {1: ("server", "boom")}
    s = run(q, updates(3))
    assert s.done == 2 and s.failures == ["#11: boom"] and s.aborted is None
    assert len(loader.ops) == 3


def test_login_failure_aborts_and_writes_nothing_twice(env):
    """Review 1."""
    loader, q = env
    loader.fail_at = {1: ("login", "Not logged in")}
    s = run(q, updates(4))
    assert s.done == 1 and s.total == 4 and s.aborted
    assert len(loader.ops) == 2   # ops 2 and 3 never reached the loader
    assert not q.busy


def test_busy_second_run_does_nothing(env):
    """Review 2."""
    loader, q = env
    out = []
    assert q.run(updates(2), out.append)
    assert q.busy
    assert q.run(updates(1), out.append) is False
    assert len(loader.ops) == 1
    assert wait_until(lambda: out)
    assert [o[1] for o in loader.ops] == [10, 11]
    assert len(out) == 1


def test_free_again_after_done(env):
    loader, q = env
    run(q, updates(1))
    run(q, updates(1))
    assert len(loader.ops) == 2


def test_empty_run(env):
    _, q = env
    s = run(q, [])
    assert (s.done, s.total) == (0, 0)


def test_progress(env):
    _, q = env
    seen = []
    q.progress.connect(lambda d, t: seen.append((d, t)))
    run(q, updates(2))
    assert seen == [(1, 2), (2, 2)]


def test_watchdog(env, monkeypatch):
    loader, q = env
    monkeypatch.setattr(writes, "WATCHDOG_MS", 50)
    loader.hang_at = {0}
    s = run(q, updates(2))
    assert s.done == 1 and s.failures == ["#10: timed out"]
    assert not q.busy
    assert run(q, updates(1)).done == 1


def test_late_signal_of_timed_out_op_is_ignored(env, monkeypatch):
    loader, q = env
    monkeypatch.setattr(writes, "WATCHDOG_MS", 30)
    loader.hang_at = {0}
    s = run(q, updates(1))
    assert s.done == 0
    loader.write_done.emit("update", 1, {})   # the first token arrives late
    wait_until(lambda: False, 0.05)
    assert not q.busy and s.done == 0


def test_op_kinds_reach_the_loader(env):
    loader, q = env
    ops = [WriteOp("insert", None, {"a": 1}, "x"), WriteOp("delete", 5, None, "y"),
           WriteOp("preset_insert", None, {"material_name": "M"}, "p"), WriteOp("preset_delete", 3, None, "q")]
    s = run(q, ops)
    assert s.done == 4
    assert loader.ops == [("insert", {"a": 1}), ("delete", 5), ("preset_insert", {"material_name": "M"}),
                          ("preset_delete", 3)]
    assert loader.store.calls == [("insert_preset", {"material_name": "M"}), ("delete_preset", 3)]


def test_with_graphs(env):
    loader, q = env
    loader.graphs = {1: "G"}
    out = []
    q.with_graphs([1, 2], out.append)
    assert wait_until(lambda: out)
    assert out == [{1: "G", 2: None}]


def test_with_graphs_times_out_to_none(env, monkeypatch):
    loader, q = env
    monkeypatch.setattr(writes, "GRAPH_TIMEOUT_MS", 50)
    loader.silent_graphs = True
    out = []
    q.with_graphs([7], out.append)
    assert wait_until(lambda: out)
    assert out == [{7: None}]


def test_with_graphs_timeout_restarts_on_each_result(env, monkeypatch):
    loader, q = env
    monkeypatch.setattr(writes, "GRAPH_TIMEOUT_MS", 120)
    loader.silent_graphs = True
    out = []
    q.with_graphs([1, 2, 3, 4], out.append)
    for i in (1, 2, 3, 4):              # 4 x 70 ms = 280 ms in all, never 120 ms without news
        QTest.qWait(70)
        loader.graph_loaded.emit(i, "G%d" % i)
    assert out == [{1: "G1", 2: "G2", 3: "G3", 4: "G4"}]


def test_with_graphs_failed_fetch_resolves_at_once(env, monkeypatch):
    loader, q = env
    monkeypatch.setattr(writes, "GRAPH_TIMEOUT_MS", 60_000)
    loader.silent_graphs = True
    out = []
    q.with_graphs([1, 2], out.append)
    loader.graph_loaded.emit(1, "G")
    loader.graph_loaded.emit(2, None)      # the loader's answer to a failed fetch
    assert out == [{1: "G", 2: None}]


def test_with_graphs_empty(env):
    _, q = env
    out = []
    q.with_graphs([], out.append)
    assert out == [{}]


def test_synchronous_failure_does_not_hang(env):
    """Review item (c): write_failed emitted before apply_* returns its token."""
    loader, q = env
    loader.sync_fail_at = {1: ("server", "closed")}
    s = run(q, updates(3))
    assert s.done == 2 and s.failures == ["#11: closed"] and len(loader.ops) == 3


def test_synchronous_login_failure_aborts(env):
    loader, q = env
    loader.sync_fail_at = {0: ("login", "no login")}
    s = run(q, updates(3))
    assert s.done == 0 and s.aborted == "no login" and len(loader.ops) == 1


def test_summary_lists_written_labels(env):
    loader, q = env
    loader.fail_at = {1: ("server", "boom")}
    s = run(q, updates(3))
    assert s.succeeded == ["#10", "#12"]
