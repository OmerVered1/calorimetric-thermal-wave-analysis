from __future__ import annotations

import json
import os
import threading

import pytest

from ctwa.cloud.client import NotLoggedIn, Offline, ServerError
from ctwa.cloud.queue import UploadQueue


class FakeClient:
    def __init__(self, script=None):
        self.script = list(script or [])  # exceptions or None, per call
        self.inserted = []
        self.calls = 0

    def insert(self, table, row):
        self.calls += 1
        assert table == "analyses"
        if self.script:
            action = self.script.pop(0)
            if action is not None:
                raise action
        self.inserted.append(row)
        return dict(row, id=len(self.inserted))


def rows(n):
    return [{"model_name": "r%d" % i, "x": i} for i in range(n)]


def test_enqueue_survives_restart(tmp_path):
    q = UploadQueue(str(tmp_path))
    rid = q.enqueue({"a": 1})
    q2 = UploadQueue(str(tmp_path))
    assert q2.pending() == [(rid, {"a": 1})]


def test_creates_missing_folder(tmp_path):
    q = UploadQueue(str(tmp_path / "sub" / "q"))
    q.enqueue({"a": 1})
    assert len(q.pending()) == 1


def test_pending_oldest_first(tmp_path):
    q = UploadQueue(str(tmp_path))
    ids = [q.enqueue(r) for r in rows(5)]
    assert [i for i, _ in q.pending()] == ids
    assert len(set(ids)) == 5


def test_successful_flush_deletes(tmp_path):
    q = UploadQueue(str(tmp_path))
    for r in rows(3):
        q.enqueue(r)
    c = FakeClient()
    assert q.flush(c) == (3, 0)
    assert c.inserted == rows(3)
    assert q.pending() == []
    assert os.listdir(str(tmp_path)) == []


def test_offline_in_middle_keeps_order(tmp_path):
    q = UploadQueue(str(tmp_path))
    ids = [q.enqueue(r) for r in rows(4)]
    c = FakeClient([None, Offline("down")])
    assert q.flush(c) == (1, 3)
    assert c.calls == 2  # stopped, did not try the rest
    assert [i for i, _ in q.pending()] == ids[1:]
    c2 = FakeClient()
    assert q.flush(c2) == (3, 0)
    assert c2.inserted == rows(4)[1:]


def test_not_logged_in_sends_nothing_twice(tmp_path):
    q = UploadQueue(str(tmp_path))
    for r in rows(3):
        q.enqueue(r)
    c = FakeClient([None, NotLoggedIn("no")])
    assert q.flush(c) == (1, 2)
    assert c.calls == 2
    c2 = FakeClient()
    assert q.flush(c2) == (2, 0)
    assert c.inserted + c2.inserted == rows(3)


def test_server_error_keeps_row_records_error_and_continues(tmp_path):
    q = UploadQueue(str(tmp_path))
    ids = [q.enqueue(r) for r in rows(3)]
    c = FakeClient([None, ServerError(400, "bad column")])
    assert q.flush(c) == (2, 1)
    assert [i for i, _ in q.pending()] == [ids[1]]
    assert "bad column" in q.last_error(ids[1])
    assert q.last_error(ids[0]) is None
    # retry succeeds -> row and error file both gone
    assert q.flush(FakeClient()) == (1, 0)
    assert os.listdir(str(tmp_path)) == []


def test_partial_temp_file_ignored(tmp_path):
    q = UploadQueue(str(tmp_path))
    rid = q.enqueue({"a": 1})
    (tmp_path / "00000000000000000001-abcd.json.tmp").write_text('{"half')
    (tmp_path / "junk.error.txt").write_text("x")
    assert q.pending() == [(rid, {"a": 1})]
    assert q.flush(FakeClient()) == (1, 0)


def test_corrupt_json_file_is_skipped_not_fatal(tmp_path):
    q = UploadQueue(str(tmp_path))
    (tmp_path / "00000000000000000001-bad.json").write_text('{"half')
    rid = q.enqueue({"a": 1})
    assert q.pending() == [(rid, {"a": 1})]


def test_nan_row_raises_valueerror_and_leaves_nothing(tmp_path):
    q = UploadQueue(str(tmp_path))
    with pytest.raises(ValueError):
        q.enqueue({"a": float("nan")})
    with pytest.raises(ValueError):
        q.enqueue({"a": object()})
    assert os.listdir(str(tmp_path)) == []


def test_unexpected_exception_keeps_row_and_propagates(tmp_path):
    q = UploadQueue(str(tmp_path))
    q.enqueue({"a": 1})
    with pytest.raises(RuntimeError):
        q.flush(FakeClient([RuntimeError("boom")]))
    assert len(q.pending()) == 1


def test_concurrent_enqueue_during_flush(tmp_path):
    q = UploadQueue(str(tmp_path))
    for r in rows(20):
        q.enqueue(r)
    c = FakeClient()
    t = threading.Thread(target=lambda: [q.enqueue({"n": i}) for i in range(20)])
    t.start()
    sent, _ = q.flush(c)
    t.join()
    sent2, left = q.flush(c)
    assert sent + sent2 == 40 and left == 0
    assert len(c.inserted) == 40
