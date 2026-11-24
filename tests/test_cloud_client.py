"""Cloud client tests against a local fake server (no real network)."""
from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ctwa.cloud.client import (CloudClient, NotLoggedIn, Offline, ServerError,
                               TokenStore)


class MemoryTokenStore(TokenStore):
    def __init__(self, token=None):
        self.token = token

    def get(self):
        return self.token

    def set(self, token):
        self.token = token

    def clear(self):
        self.token = None


class Fake:
    """Records requests; replies from `responses[(method, path-prefix)]`."""

    def __init__(self):
        self.requests = []
        self.responses = {}
        outer = self

        class H(BaseHTTPRequestHandler):
            def _handle(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n).decode() if n else ""
                outer.requests.append({
                    "method": self.command, "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": body})
                key = (self.command, self.path.split("?")[0])
                status, payload = outer.responses.get(key, (200, {}))
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            do_GET = do_POST = _handle

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake():
    f = Fake()
    yield f
    f.close()


def make(fake, token=None):
    store = MemoryTokenStore(token)
    return CloudClient(fake.url, fake.url, "ANON", store, timeout=3), store


def test_login_stores_token(fake):
    fake.responses[("POST", "/api/auth")] = (200, {"ok": True, "token": "tok123"})
    c, store = make(fake)
    c.login("pw")
    assert store.get() == "tok123"
    assert json.loads(fake.requests[0]["body"]) == {"password": "pw"}


def test_login_wrong_password(fake):
    fake.responses[("POST", "/api/auth")] = (401, {"error": "Wrong"})
    c, store = make(fake)
    with pytest.raises(NotLoggedIn):
        c.login("bad")
    assert store.get() is None


def test_check_session(fake):
    fake.responses[("GET", "/api/auth")] = (200, {"ok": True})
    c, _ = make(fake, "tok")
    assert c.check_session() is True
    assert fake.requests[0]["headers"]["authorization"] == "Bearer tok"
    fake.responses[("GET", "/api/auth")] = (401, {"error": "Not logged in"})
    assert c.check_session() is False


def test_check_session_without_token(fake):
    c, _ = make(fake)
    assert c.check_session() is False
    assert fake.requests == []


def test_insert_sends_bearer_and_exact_body(fake):
    fake.responses[("POST", "/api/db")] = (200, {"data": [{"id": 7, "a": 1}]})
    c, _ = make(fake, "tok")
    out = c.insert("analyses", {"a": 1})
    assert out == {"id": 7, "a": 1}
    r = fake.requests[0]
    assert r["headers"]["authorization"] == "Bearer tok"
    assert json.loads(r["body"]) == {"action": "insert", "table": "analyses",
                                     "data": {"a": 1}}


def test_update_and_delete_bodies(fake):
    fake.responses[("POST", "/api/db")] = (200, {"data": [{"id": 3, "b": 2}]})
    c, _ = make(fake, "tok")
    assert c.update("setups", 3, {"b": 2}) == {"id": 3, "b": 2}
    assert json.loads(fake.requests[0]["body"]) == {
        "action": "update", "table": "setups", "id": 3, "data": {"b": 2}}
    assert c.delete("alpha_presets", 3) is None
    assert json.loads(fake.requests[1]["body"]) == {
        "action": "delete", "table": "alpha_presets", "id": 3}


def test_write_without_token_is_not_logged_in(fake):
    c, _ = make(fake)
    with pytest.raises(NotLoggedIn):
        c.insert("analyses", {})
    assert fake.requests == []


def test_401_on_write_raises_not_logged_in(fake):
    fake.responses[("POST", "/api/db")] = (401, {"error": "Not logged in"})
    c, _ = make(fake, "tok")
    with pytest.raises(NotLoggedIn):
        c.insert("analyses", {})


def test_500_raises_server_error_with_message(fake):
    fake.responses[("POST", "/api/db")] = (500, {"error": "boom"})
    c, _ = make(fake, "tok")
    with pytest.raises(ServerError) as ei:
        c.insert("analyses", {})
    assert ei.value.status == 500
    assert ei.value.message == "boom"


def test_400_raises_server_error(fake):
    fake.responses[("POST", "/api/db")] = (400, {"error": "bad table"})
    c, _ = make(fake, "tok")
    with pytest.raises(ServerError) as ei:
        c.delete("x", 1)
    assert ei.value.status == 400


def test_connection_refused_is_offline():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()  # nothing listens now
    url = "http://127.0.0.1:%d" % port
    c = CloudClient(url, url, "ANON", MemoryTokenStore("t"), timeout=2)
    with pytest.raises(Offline):
        c.select("analyses", {})
    with pytest.raises(Offline):
        c.login("pw")


def test_select_headers_and_query(fake):
    fake.responses[("GET", "/rest/v1/analyses")] = (200, [{"id": 1}])
    c, _ = make(fake)
    rows = c.select("analyses", {"model_name": "eq.unk foam", "order": "id.desc"})
    assert rows == [{"id": 1}]
    r = fake.requests[0]
    assert r["headers"]["apikey"] == "ANON"
    assert r["headers"]["authorization"] == "Bearer ANON"
    assert "model_name=eq.unk+foam" in r["path"] or "model_name=eq.unk%20foam" in r["path"]
    assert "order=id.desc" in r["path"]


def test_select_server_error(fake):
    fake.responses[("GET", "/rest/v1/analyses")] = (500, {"message": "db down"})
    c, _ = make(fake)
    with pytest.raises(ServerError) as ei:
        c.select("analyses", {})
    assert "db down" in ei.value.message


def test_default_token_store_without_keyring(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "keyring", None)
    with pytest.raises(RuntimeError, match="keyring"):
        TokenStore().get()
