"""Finding recorded run files and what is known about them (no Qt).

``scan`` reads only the first and last few KB of each file, so a hundred runs
list in a few milliseconds. The slow parts (mean temperature, the cloud
query) are separate functions for the caller to run off the GUI thread.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from ctwa.analysis.parser import decode_bytes, is_combined_file, parse_combined_file
from ctwa.analysis.run_header import parse_run_header

__all__ = ["RunInfo", "scan", "scan_limited", "MAX_FILES", "MeanTempCache",
           "default_cache_path", "SavedInfo", "match_saved", "fmt_date",
           "query_saved_rows"]

MAX_FILES = 2000
_HEAD = 4096   # holds the comment block and the column-header row
_TAIL = 2048


@dataclass
class RunInfo:
    path: str
    name: str
    started: Optional[datetime]
    length_s: Optional[float]
    size: int
    mtime: float
    mtime_ns: int = 0
    is_capture: bool = True   # False: not a one-file CTWA/C80 capture


def fmt_date(dt: datetime) -> str:
    return dt.strftime("%d/%m/%Y")


# -- scanning ---------------------------------------------------------------

def _find_csvs(folders: Sequence[str], limit: int) -> Tuple[List[str], bool]:
    found: List[str] = []
    seen = set()
    for folder in folders:
        for root, dirs, files in os.walk(folder):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for f in sorted(files):
                if not f.lower().endswith(".csv") or f.startswith("."):
                    continue
                p = os.path.normpath(os.path.join(root, f))
                if p in seen:
                    continue
                if len(found) >= limit:
                    return found, True
                seen.add(p)
                found.append(p)
    return found, False


def _last_elapsed(head_text: str, tail: bytes, whole: bool) -> Optional[float]:
    """Elapsed(s) of the last data row, from the header row and the file's tail."""
    sep, idx = ",", -1
    for line in head_text.splitlines():
        s = line.strip().lstrip("﻿")
        if not s.strip(",\t ") or s.startswith("#") or s.startswith('"#'):
            continue
        sep = "\t" if "\t" in s else ","
        cols = [c.strip().lower() for c in s.split(sep)]
        for i, c in enumerate(cols):
            if c in ("elapsed(s)", "time(s)") or (sep == "\t" and c.startswith("time")):
                idx = i
                break
        break
    if idx < 0:
        return None
    lines = decode_bytes(tail).splitlines()
    if not whole and lines:
        lines = lines[1:]   # the first tail line may be cut in half
    for line in reversed(lines):
        row = line.split(sep)
        if len(row) <= idx:
            continue
        try:
            v = float(row[idx])
        except ValueError:
            continue
        if math.isfinite(v):
            return v
    return None


def _inspect(path: str) -> Optional[RunInfo]:
    try:
        st = os.stat(path)
        with open(path, "rb") as f:
            head = f.read(_HEAD)
            if st.st_size <= _HEAD + _TAIL:
                tail, whole = head + f.read(), True
            else:
                f.seek(max(0, st.st_size - _TAIL))
                tail, whole = f.read(), False
    except OSError:
        return None
    if not head:
        return RunInfo(path, os.path.basename(path), None, None, st.st_size,
                       st.st_mtime, st.st_mtime_ns, False)
    text = decode_bytes(head)
    hdr = parse_run_header(text)
    started = hdr["started"] if isinstance(hdr["started"], datetime) else None
    is_cap = started is not None or is_combined_file(head)
    length = _last_elapsed(text, tail, whole) if is_cap else None
    return RunInfo(path, os.path.basename(path), started, length, st.st_size,
                   st.st_mtime, st.st_mtime_ns, is_cap)


def scan_limited(folders: Iterable[str], limit: int = MAX_FILES) -> Tuple[List[RunInfo], bool]:
    """(runs, truncated). Newest start first; files without a start last."""
    paths, truncated = _find_csvs([f for f in folders if f], limit)
    runs = [r for r in (_inspect(p) for p in paths) if r is not None]
    runs.sort(key=lambda r: (r.started is None,
                             -(r.started.timestamp() if r.started else r.mtime),
                             r.name))
    return runs, truncated


def scan(folders: Iterable[str]) -> List[RunInfo]:
    return scan_limited(folders)[0]


# -- mean temperature cache -------------------------------------------------

def default_cache_path() -> str:
    from ctwa.cloud.queue import default_queue_folder
    return os.path.join(os.path.dirname(default_queue_folder()), "run_index_cache.json")


class MeanTempCache:
    """JSON file {"version":1,"entries":{path:{mtime_ns,size,mean_c}}}.

    An entry is valid only while the file's (mtime_ns, size) are unchanged.
    mean_c is null for a file with no temperature column (remembered too)."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._entries: Dict[str, dict] = {}
        self._dirty = False
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            ents = data.get("entries") if isinstance(data, dict) else None
            if isinstance(ents, dict):
                self._entries = {k: v for k, v in ents.items() if isinstance(v, dict)}
        except (OSError, ValueError):
            pass

    def lookup(self, run: RunInfo) -> Tuple[bool, Optional[float]]:
        """(known, mean)."""
        with self._lock:
            e = self._entries.get(run.path)
        if e and e.get("mtime_ns") == run.mtime_ns and e.get("size") == run.size:
            return True, e.get("mean_c")
        return False, None

    def put(self, run: RunInfo, mean: Optional[float]) -> None:
        with self._lock:
            self._entries[run.path] = {"mtime_ns": run.mtime_ns, "size": run.size,
                                       "mean_c": mean}
            self._dirty = True

    def save(self) -> None:
        with self._lock:
            if not self._dirty:
                return
            payload = json.dumps({"version": 1, "entries": self._entries})
            self._dirty = False
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path) or ".", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp, self.path)
        except OSError:
            pass   # a cache that cannot be written is only slower


def compute_mean_temperature(run: RunInfo) -> Optional[float]:
    """Full parse of the file: slow, call off the GUI thread."""
    try:
        with open(run.path, "rb") as f:
            parsed = parse_combined_file(f.read())
    except OSError:
        return None
    if parsed is None:
        return None
    vals = [t for t in parsed.temperature if math.isfinite(t)]
    return sum(vals) / len(vals) if vals else None


# -- saved analyses ---------------------------------------------------------

@dataclass
class SavedInfo:
    count: int
    exact: bool          # False: the count is "same day", not "this file"
    sample: str = ""


def match_saved(run: RunInfo, rows: Iterable[dict]) -> SavedInfo:
    rows = list(rows)
    exact = [r for r in rows if r.get("c80_filename") == run.name]
    if exact:
        newest = max(exact, key=lambda r: r.get("id") or 0)
        return SavedInfo(len(exact), True, str(newest.get("model_name") or ""))
    if run.started is not None:
        day = fmt_date(run.started)
        return SavedInfo(sum(1 for r in rows if r.get("test_date") == day), False, "")
    return SavedInfo(0, False, "")


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def query_saved_rows(client, runs: Sequence[RunInfo], chunk: int = 40) -> Dict[str, SavedInfo]:
    """path -> SavedInfo. Raises the client's NotLoggedIn / Offline / ServerError."""
    sel = "id,c80_filename,model_name,test_date"
    by_name: Dict[str, List[dict]] = {}
    names = sorted({r.name for r in runs})
    for i in range(0, len(names), chunk):
        part = names[i:i + chunk]
        rows = client.select("analyses", {
            "select": sel, "order": "id.desc",
            "c80_filename": "in.(" + ",".join(_q(n) for n in part) + ")"})
        for row in rows:
            by_name.setdefault(row.get("c80_filename"), []).append(row)
    exact_names = set(by_name)
    days = sorted({fmt_date(r.started) for r in runs
                   if r.started is not None and r.name not in exact_names})
    by_day: Dict[str, List[dict]] = {}
    for i in range(0, len(days), chunk):
        part = days[i:i + chunk]
        rows = client.select("analyses", {
            "select": sel, "order": "id.desc",
            "test_date": "in.(" + ",".join(_q(d) for d in part) + ")"})
        for row in rows:
            by_day.setdefault(row.get("test_date"), []).append(row)
    out: Dict[str, SavedInfo] = {}
    for r in runs:
        rows = by_name.get(r.name) or by_day.get(fmt_date(r.started) if r.started else "", [])
        out[r.path] = match_saved(r, rows)
    return out
