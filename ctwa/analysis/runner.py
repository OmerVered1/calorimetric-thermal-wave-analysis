"""Process side of the analysis: loading a run file and analysing it (no Qt).

These functions run inside the long-lived worker process started by
ctwa.ui.analysis_worker.AnalysisWorker, so that the heavy maths never shares
the GUI process's GIL with the sweep thread."""

from __future__ import annotations

import math
import os
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ctwa.analysis.parser import decode_bytes
from ctwa.analysis.pipeline import default_selection, load_one_file, run_one_file_pipeline
from ctwa.analysis.run_header import parse_run_header
from ctwa.analysis.types import AnalysisResults, CombinedParsed, PipelineOptions, SyncedData

__all__ = ["LoadedRun", "load_run", "analyze_run"]

_CACHE_MAX = 3
# (path, mtime_ns, size) -> LoadedRun, least recently used first
_CACHE: "OrderedDict[Tuple[str, int, int], LoadedRun]" = OrderedDict()


@dataclass
class LoadedRun:
    path: str
    synced: SyncedData
    parsed: CombinedParsed
    header: Dict[str, object]  # started, experiment, instrument, calorimeter
    default: Tuple[float, float, List[Tuple[float, float]]]  # sel_min, sel_max, clicks
    mean_temperature: Optional[float]  # mean of the finite temperatures, whole file


def _mean_finite(values) -> Optional[float]:
    total = 0.0
    n = 0
    for v in values:
        if math.isfinite(v):
            total += v
            n += 1
    return total / n if n else None


def load_run(path: str) -> LoadedRun:
    st = os.stat(path)
    key = (path, st.st_mtime_ns, st.st_size)
    hit = _CACHE.get(key)
    if hit is not None:
        _CACHE.move_to_end(key)
        return hit
    with open(path, "rb") as f:
        data = f.read()
    synced, parsed = load_one_file(data)
    run = LoadedRun(
        path=path,
        synced=synced,
        parsed=parsed,
        header=parse_run_header(decode_bytes(data[:8192]).splitlines()),
        default=default_selection(synced),
        mean_temperature=_mean_finite(parsed.temperature),
    )
    for k in [k for k in _CACHE if k[0] == path]:
        del _CACHE[k]  # an older version of the same file
    _CACHE[key] = run
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return run


def analyze_run(path: str, opts: PipelineOptions) -> AnalysisResults:
    return run_one_file_pipeline(load_run(path).synced, opts)
