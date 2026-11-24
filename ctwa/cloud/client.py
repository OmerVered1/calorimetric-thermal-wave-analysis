"""Cloud client: login to the webapp, read Supabase, write via /api/db.

urllib only. Tokens and passwords are never logged or printed.
"""
from __future__ import annotations

import http.client
import json
import re
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

    _MISSING = ("The 'keyring' package (with a working OS keyring) is "
                "required to store the login token (pip install keyring>=24)")

    @classmethod
    def _keyring(cls):
        try:
            import keyring  # lazy: not installed in every environment
        except ImportError:
            raise RuntimeError(cls._MISSING) from None
        return keyring

    def _call(self, name: str, *args):
        kr = self._keyring()
        try:
            return getattr(kr, name)(*args)
        except Exception as e:
            if type(e).__module__.startswith("keyring"):
                raise RuntimeError(self._MISSING) from None
            raise

    def get(self) -> Optional[str]:
        return self._call("get_password", KEYRING_SERVICE, KEYRING_USER)

    def set(self, token: str) -> None:
        self._call("set_password", KEYRING_SERVICE, KEYRING_USER, token)

    def clear(self) -> None:
        try:
            self._call("delete_password", KEYRING_SERVICE, KEYRING_USER)
        except RuntimeError:
            raise
        except Exception:  # already absent
            pass


_MAX_MSG = 200


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text[:_MAX_MSG]


def _error_message(body: bytes, status: int) -> str:
    fallback = "HTTP %s" % status
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return fallback
    if isinstance(data, dict):
        for key in ("error", "message"):
            if data.get(key):
                return _clean(str(data[key])) or fallback
    return fallback


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _check_url(url: str) -> str:
    url = url.rstrip("/")
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
        parts.port  # raises ValueError on a bad port
    except ValueError:
        raise ValueError("Invalid cloud URL") from None
    ok = False
    if parts.scheme == "https":
        ok = bool(host) and parts.username is None and parts.password is None
    elif parts.scheme == "http":
        ok = (host in ("localhost", "127.0.0.1")
              and parts.username is None and parts.password is None)
    if not ok:
        raise ValueError("Cloud URL must be https:// (http only for "
                         "localhost, without credentials)")
    return url


class CloudClient:
    def __init__(self, webapp_url: str, supabase_url: str, anon_key: str,
                 tokens: TokenStore, timeout: float = 15):
        self.webapp_url = _check_url(webapp_url)
        self.supabase_url = _check_url(supabase_url)
        self.anon_key = anon_key
        self.tokens = tokens
        self.timeout = timeout

    # -- transport ---------------------------------------------------------
    def _request(self, method: str, url: str, headers: Dict[str, str],
                 body: Any = None, unauth_is_server: bool = False) -> Any:
        data = None
        hdrs = dict(headers)
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        try:
            req = urllib.request.Request(url, data=data, headers=hdrs,
                                         method=method)
        except ValueError:
            raise ServerError(0, "invalid URL") from None
        try:
            with _OPENER.open(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            try:
                body = e.read()
            except Exception:
                body = b""
            if 300 <= e.code < 400:
                raise ServerError(e.code, "unexpected redirect") from None
            if e.code == 401:
                if unauth_is_server:
                    raise ServerError(401, "Supabase rejected the public key") from None
                msg = _error_message(body, 401)
                raise NotLoggedIn(msg) from None
            raise ServerError(e.code, _error_message(body, e.code)) from None
        except ValueError:
            raise ServerError(0, "invalid URL") from None
        except (urllib.error.URLError, socket.timeout, ConnectionError,
                http.client.HTTPException, OSError) as e:
            raise Offline(_clean(str(getattr(e, "reason", e)))) from None
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
        url = "%s/rest/v1/%s" % (self.supabase_url,
                                 urllib.parse.quote(table, safe=""))
        if query:
            url += "?" + urllib.parse.urlencode(
                query, quote_via=urllib.parse.quote)
        headers = {"apikey": self.anon_key,
                   "Authorization": "Bearer " + self.anon_key}
        out = self._request("GET", url, headers, unauth_is_server=True)
        if not isinstance(out, list):
            raise ServerError(200, "unexpected response")
        return out

    # -- writes (webapp /api/db) -------------------------------------------
    def _db(self, payload: dict) -> Any:
        return self._request("POST", self.webapp_url + "/api/db",
                             self._bearer(), payload)

    @staticmethod
    def _first(out: Any) -> dict:
        data = out.get("data") if isinstance(out, dict) else None
        return data[0] if isinstance(data, list) and data else {}

    def insert(self, table: str, row: dict) -> dict:
        return self._first(self._db(
            {"action": "insert", "table": table, "data": row}))

    def update(self, table: str, id: Any, data: dict) -> dict:
        return self._first(self._db(
            {"action": "update", "table": table, "id": id, "data": data}))

    def delete(self, table: str, id: Any) -> None:
        self._db({"action": "delete", "table": table, "id": id})
