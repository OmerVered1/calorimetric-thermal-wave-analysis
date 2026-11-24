"""Offline upload queue: rows that could not be saved are kept on disk.

One JSON file per row (``<id>.json``), written atomically. A row is removed
only after a successful insert. No Qt here; ``default_queue_folder`` imports
it lazily.
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
        os.makedirs(folder, exist_ok=True)

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
        try:
            with open(self._path(rid), "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

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
            row = self._read(rid)
            if row is not None:  # unreadable/partial files are skipped
                out.append((rid, row))
        return out

    def last_error(self, rid: str) -> Optional[str]:
        try:
            with open(self._err_path(rid), "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None

    def flush(self, client) -> Tuple[int, int]:
        """Insert queued rows oldest first. Returns (sent, still_waiting)."""
        sent = 0
        for rid in self._ids():
            with self._lock:
                row = self._read(rid)
                if row is None:
                    continue
                try:
                    client.insert(TABLE, row)
                except (NotLoggedIn, Offline):
                    break
                except ServerError as e:
                    self._write_error(rid, str(e))
                    continue
                self._remove(self._path(rid))
                self._remove(self._err_path(rid))
                sent += 1
        return sent, len(self._ids())

    def _write_error(self, rid: str, message: str) -> None:
        tmp = self._err_path(rid) + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(message)
            os.replace(tmp, self._err_path(rid))
        except OSError:
            self._remove(tmp)
