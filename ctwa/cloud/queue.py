"""Offline upload queue: rows that could not be saved are kept on disk.

One JSON file per row (``<id>.json``), written atomically. A row is removed
only after a successful insert. No Qt here; ``default_queue_folder`` imports
it lazily.

Locking: ``_flush_lock`` serializes flushes (a second concurrent flush returns
at once). ``_lock`` guards only short file operations and is never held during
the network call, so ``enqueue`` (GUI thread) never waits on the network.

Known limit: if an upload times out after the server already committed it, the
next flush can insert that row again (the table has no idempotency key).
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import List, Optional, Tuple

from ctwa.cloud.client import NotLoggedIn, Offline, ServerError

TABLE = "analyses"
_EXT = ".json"
_ERR_EXT = ".error.txt"


def default_queue_folder() -> str:
    from PySide6.QtCore import QStandardPaths  # lazy: queue itself is Qt-free
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    return os.path.join(base, "upload_queue")


class UploadQueue:
    def __init__(self, folder: str):
        self.folder = folder
        self._lock = threading.Lock()
        self._flush_lock = threading.Lock()
        os.makedirs(folder, exist_ok=True)
        self._clean_old_temp()

    def _clean_old_temp(self) -> None:
        cutoff = time.time() - 600
        try:
            names = os.listdir(self.folder)
        except OSError:
            return
        for n in names:
            if n.endswith(".tmp"):
                path = os.path.join(self.folder, n)
                try:
                    if os.stat(path).st_mtime < cutoff:
                        os.remove(path)
                except OSError:
                    pass

    # -- paths -------------------------------------------------------------
    def _path(self, rid: str) -> str:
        return os.path.join(self.folder, rid + _EXT)

    def _err_path(self, rid: str) -> str:
        return os.path.join(self.folder, rid + _ERR_EXT)

    def _ids(self) -> List[str]:
        try:
            names = os.listdir(self.folder)
        except OSError:
            return []
        return sorted(n[:-len(_EXT)] for n in names
                      if n.endswith(_EXT) and not n.endswith(_ERR_EXT))

    def _read(self, rid: str) -> Optional[dict]:
        """Row dict, or None if missing. Corrupt files are moved aside."""
        path = self._path(rid)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except OSError:  # missing or transient: skip, leave the file alone
            return None
        except ValueError:  # genuinely bad content
            data = None
        if not isinstance(data, dict):
            try:
                os.replace(path, os.path.join(self.folder, rid + ".corrupt"))
            except OSError:
                pass
            return None
        return data

    @staticmethod
    def _remove(path: str) -> None:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

    # -- api ---------------------------------------------------------------
    def enqueue(self, row: dict) -> str:
        try:
            text = json.dumps(row, allow_nan=False)
        except (TypeError, ValueError) as e:
            raise ValueError("row cannot be queued: %s" % e) from None
        rid = "%020d-%s" % (time.time_ns(), uuid.uuid4().hex[:8])
        tmp = os.path.join(self.folder, rid + ".json.tmp")
        with self._lock:
            os.makedirs(self.folder, exist_ok=True)
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(text)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self._path(rid))
            except BaseException:
                self._remove(tmp)
                raise
        return rid

    def pending(self) -> List[Tuple[str, dict]]:
        out = []
        for rid in self._ids():
            with self._lock:
                row = self._read(rid)
            if row is not None:
                out.append((rid, row))
        return out

    def pending_with_errors(self) -> List[Tuple[str, dict, Optional[str]]]:
        return [(rid, row, self.last_error(rid))
                for rid, row in self.pending()]

    def last_error(self, rid: str) -> Optional[str]:
        try:
            with open(self._err_path(rid), "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None

    def flush(self, client) -> Tuple[int, int]:
        """Insert queued rows oldest first. Returns (sent, still_waiting)."""
        if not self._flush_lock.acquire(blocking=False):
            return 0, len(self.pending())
        try:
            sent = 0
            for rid in self._ids():
                with self._lock:
                    row = self._read(rid)
                if row is None:
                    continue
                try:
                    client.insert(TABLE, row)  # no lock held here
                except (NotLoggedIn, Offline):
                    break
                except ServerError as e:
                    self._write_error(rid, str(e))
                    continue
                except Exception as e:  # unexpected: keep row, stop
                    self._write_error(rid, "%s: %s" % (type(e).__name__, e))
                    break
                with self._lock:
                    self._remove(self._path(rid))
                    self._remove(self._err_path(rid))
                sent += 1
            return sent, len(self.pending())
        finally:
            self._flush_lock.release()

    def _write_error(self, rid: str, message: str) -> None:
        tmp = self._err_path(rid) + ".tmp"
        with self._lock:
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(message)
                os.replace(tmp, self._err_path(rid))
            except OSError:
                self._remove(tmp)
