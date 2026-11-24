"""Cloud client: login to the webapp, read Supabase, write via /api/db.

urllib only. Tokens and passwords are never logged or printed.
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

KEYRING_SERVICE = "CTWA"
KEYRING_USER = "omersthesis"


class NotLoggedIn(Exception):
    """No valid session (missing token, wrong password, or HTTP 401)."""


class Offline(Exception):
    """The server could not be reached (connection error or timeout)."""


class ServerError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__("HTTP %s: %s" % (status, message))
        self.status = status
        self.message = message


class TokenStore:
    """Default store: the OS keyring. Tests inject an in-memory subclass."""

    @staticmethod
    def _keyring():
        try:
            import keyring  # lazy: not installed in every environment
        except ImportError:
            raise RuntimeError(
                "The 'keyring' package is required to store the login token "
                "(pip install keyring>=24)") from None
        if keyring is None:
            raise RuntimeError("The 'keyring' package is required "
                               "(pip install keyring>=24)")
        return keyring

    def get(self) -> Optional[str]:
        return self._keyring().get_password(KEYRING_SERVICE, KEYRING_USER)

    def set(self, token: str) -> None:
        self._keyring().set_password(KEYRING_SERVICE, KEYRING_USER, token)

    def clear(self) -> None:
        kr = self._keyring()
        try:
            kr.delete_password(KEYRING_SERVICE, KEYRING_USER)
        except Exception:  # already absent
            pass


def _error_message(body: bytes) -> str:
    text = body.decode("utf-8", "replace")
    try:
        data = json.loads(text)
    except ValueError:
        return text.strip()
    if isinstance(data, dict):
        for key in ("error", "message"):
            if data.get(key):
                return str(data[key])
    return text.strip()


class CloudClient:
    def __init__(self, webapp_url: str, supabase_url: str, anon_key: str,
                 tokens: TokenStore, timeout: float = 15):
        self.webapp_url = webapp_url.rstrip("/")
        self.supabase_url = supabase_url.rstrip("/")
        self.anon_key = anon_key
        self.tokens = tokens
        self.timeout = timeout

    # -- transport ---------------------------------------------------------
    def _request(self, method: str, url: str, headers: Dict[str, str],
                 body: Any = None) -> Any:
        data = None
        hdrs = dict(headers)
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            msg = _error_message(e.read())
            if e.code == 401:
                raise NotLoggedIn(msg or "Not logged in") from None
            raise ServerError(e.code, msg) from None
        except (urllib.error.URLError, socket.timeout, ConnectionError,
                OSError) as e:
            raise Offline(str(getattr(e, "reason", e))) from None
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            raise ServerError(200, "Invalid JSON in response") from None

    def _bearer(self) -> Dict[str, str]:
        token = self.tokens.get()
        if not token:
            raise NotLoggedIn("Not logged in")
        return {"Authorization": "Bearer " + token}

    # -- auth --------------------------------------------------------------
    def login(self, password: str) -> None:
        out = self._request("POST", self.webapp_url + "/api/auth", {},
                            {"password": password})
        token = out.get("token") if isinstance(out, dict) else None
        if not token:
            raise ServerError(200, "Login response had no token")
        self.tokens.set(token)

    def check_session(self) -> bool:
        if not self.tokens.get():
            return False
        try:
            out = self._request("GET", self.webapp_url + "/api/auth",
                                self._bearer())
        except NotLoggedIn:
            return False
        return bool(isinstance(out, dict) and out.get("ok"))

    # -- reads (public key) ------------------------------------------------
    def select(self, table: str, query: Dict[str, str]) -> List[dict]:
        url = "%s/rest/v1/%s" % (self.supabase_url, urllib.parse.quote(table))
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {"apikey": self.anon_key,
                   "Authorization": "Bearer " + self.anon_key}
        out = self._request("GET", url, headers)
        return out if isinstance(out, list) else []

    # -- writes (webapp /api/db) -------------------------------------------
    def _db(self, payload: dict) -> Any:
        return self._request("POST", self.webapp_url + "/api/db",
                             self._bearer(), payload)

    @staticmethod
    def _first(out: Any) -> dict:
        data = out.get("data") if isinstance(out, dict) else None
        return data[0] if data else {}

    def insert(self, table: str, row: dict) -> dict:
        return self._first(self._db(
            {"action": "insert", "table": table, "data": row}))

    def update(self, table: str, id: Any, data: dict) -> dict:
        return self._first(self._db(
            {"action": "update", "table": table, "id": id, "data": data}))

    def delete(self, table: str, id: Any) -> None:
        self._db({"action": "delete", "table": table, "id": id})
