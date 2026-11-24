"""The one-file analysis flow: literal port of lib/pipeline.ts of the webapp."""

from __future__ import annotations

from typing import List, Tuple

from ctwa.analysis.jsmath import js_round
from ctwa.analysis.modes import (
    run_auto_analysis,
    run_auto_fft_analysis,
    run_auto_fit_analysis,
    run_auto_hybrid_analysis,
    run_manual_analysis,
)
from ctwa.analysis.parser import parse_combined_file
from ctwa.analysis.smoothing import smooth_to_shared_sine
from ctwa.analysis.square import run_square_analysis
from ctwa.analysis.types import (
    AnalysisResults,
    CombinedParsed,
    PipelineError,
    PipelineOptions,
    SyncedData,
)

__all__ = ["PipelineError", "load_one_file", "default_selection", "run_one_file_pipeline"]


def load_one_file(data: bytes) -> Tuple[SyncedData, CombinedParsed]:
    """Parse and build SyncedData as the page's one-file load does (raises parseFailed / notEnoughOverlap)."""
    parsed = parse_combined_file(data)
    if parsed is None:
        raise PipelineError("parseFailed")
    synced = SyncedData(t_src=parsed.time, v_src=parsed.source, t_cal=parsed.time, v_cal=parsed.response)
    if len(synced.t_src) < 20:
        raise PipelineError("notEnoughOverlap")
    return synced, parsed


def default_selection(synced: SyncedData) -> Tuple[float, float, List[Tuple[float, float]]]:
    """(sel_min, sel_max, clicks): 0.3/0.7 and 0.35/0.5/0.45/0.55 of the span, Math.round."""
    t_min = float("inf")
    t_max = float("-inf")
    for tt in synced.t_src:
        if tt < t_min:
            t_min = tt
        if tt > t_max:
            t_max = tt
    span = t_max - t_min
    return (
        js_round(t_min + span * 0.3),
        js_round(t_min + span * 0.7),
        [
            (js_round(t_min + span * 0.35), 0),
            (js_round(t_min + span * 0.5), 0),
            (js_round(t_min + span * 0.45), 0),
            (js_round(t_min + span * 0.55), 0),
        ],
    )


def run_one_file_pipeline(synced: SyncedData, opts: PipelineOptions) -> AnalysisResults:
    """Filter to [sel_min, sel_max], optional smoothing, dispatch on wave type / analysis mode."""
    params = opts.params
    mode = params.analysis_mode
    sel_min = opts.sel_min
    sel_max = opts.sel_max

    t_src_f: List[float] = []
    v_src_f: List[float] = []
    for i in range(len(synced.t_src)):
        if synced.t_src[i] >= sel_min and synced.t_src[i] <= sel_max:
            t_src_f.append(synced.t_src[i])
            v_src_f.append(synced.v_src[i])
    t_cal_f: List[float] = []
    v_cal_f: List[float] = []
    for i in range(len(synced.t_cal)):
        if synced.t_cal[i] >= sel_min and synced.t_cal[i] <= sel_max:
            t_cal_f.append(synced.t_cal[i])
            v_cal_f.append(synced.v_cal[i])

    if len(t_src_f) < 10 or len(t_cal_f) < 10:
        raise PipelineError("tooFewPoints")

    v_src_use, v_cal_use = v_src_f, v_cal_f
    if opts.smooth_to_sine and opts.wave_type != "square":
        sm = smooth_to_shared_sine(t_src_f, v_src_f, t_cal_f, v_cal_f)
        if sm is None:
            raise PipelineError("smoothFailed")
        v_src_use, v_cal_use = sm[0], sm[1]

    if opts.wave_type == "square":
        sq = opts.square_period
        return run_square_analysis(
            t_cal_f, v_cal_use, t_src_f, v_src_use, params, sel_min, sel_max,
            sq if sq is not None and sq > 0 else None,
        )
    args = (t_cal_f, v_cal_use, t_src_f, v_src_use, params, sel_min, sel_max)
    if mode == "Auto":
        return run_auto_analysis(*args)
    if mode == "AutoHybrid":
        return run_auto_hybrid_analysis(*args)
    if mode == "AutoFFT":
        return run_auto_fft_analysis(*args)
    if mode == "AutoFit":
        return run_auto_fit_analysis(*args)
    return run_manual_analysis(*args, opts.clicks if opts.clicks is not None else [])
