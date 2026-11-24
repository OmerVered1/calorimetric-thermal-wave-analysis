"""The Python analysis must give the webapp's numbers.

Every file in tests/golden/analysis/ was written by the webapp's own TypeScript
code (ops/golden in the webapp repo) from the inputs in tests/data/runs/.
Floats must agree to a relative 1e-9 (absolute 1e-12), NaN equals NaN, ints,
bools and strings must be identical.

Python names follow one rule from the webapp's camelCase: put "_" before each
capital and lower-case it (amplitudeA1 -> amplitude_a1, r1Mm -> r1_mm).
"""

from __future__ import annotations

import glob
import gzip
import json
import math
import os
import re
import time

import pytest

from ctwa.analysis.lag_fit import describe_lag_model, fit_lag_models, serialize_fit
from ctwa.analysis.parser import parse_combined_file
from ctwa.analysis.pipeline import load_one_file, run_one_file_pipeline
from ctwa.analysis.types import AnalysisParams, LagPoint, PipelineError, PipelineOptions

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN_DIR = os.path.join(HERE, "golden", "analysis")
RUNS_DIR = os.path.join(HERE, "data", "runs")

REL_TOL = 1e-9
ABS_TOL = 1e-12
OPTIONAL_RESULT_FIELDS = ("lagSe", "lagSeSource", "lagBlocks", "lagCycles", "lagNearEdge")
PREDICT_PERIODS = (75, 150, 300, 600)
NONFINITE = {"NaN": math.nan, "Infinity": math.inf, "-Infinity": -math.inf}


def snake(name: str) -> str:
    """The one camelCase -> snake_case rule for every option, parameter and result name."""
    return re.sub(r"([A-Z])", r"_\1", name).lower()


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _golden(prefix_match):
    return sorted(p for p in glob.glob(os.path.join(GOLDEN_DIR, "*.json")) if prefix_match(os.path.basename(p)))


CASE_FILES = _golden(lambda n: "__" in n)
PARSER_FILES = _golden(lambda n: n.startswith("parser_"))
LAGFIT_FILES = _golden(lambda n: n.startswith("lagfit"))


def _ids(paths):
    return [os.path.basename(p)[:-5] for p in paths]


def read_input(input_file: str) -> bytes:
    name = os.path.splitext(input_file)[0]
    with gzip.open(os.path.join(RUNS_DIR, name + ".csv.gz"), "rb") as f:
        return f.read()


def restore_nonfinite(obj, nonfinite):
    """Put NaN / +-Infinity back where the golden JSON wrote null.
    Paths are dot-separated keys, list indexes as numbers."""
    for path, kind in (nonfinite or {}).items():
        parts = path.split(".")
        cur = obj
        for part in parts[:-1]:
            cur = cur[int(part)] if isinstance(cur, list) else cur[part]
        last = parts[-1]
        if isinstance(cur, list):
            cur[int(last)] = NONFINITE[kind]
        else:
            cur[last] = NONFINITE[kind]
    return obj


def check_value(case_id, field, expected, actual):
    """Compare one value by the tolerance rules; fail with a message that shows everything."""
    if isinstance(expected, (list, tuple)):
        assert isinstance(actual, (list, tuple)) and len(actual) == len(expected), (
            f"[{case_id}] {field}: expected {expected!r}, got {actual!r} (length differs)")
        for i, (e, a) in enumerate(zip(expected, actual)):
            check_value(case_id, f"{field}[{i}]", e, a)
        return
    if isinstance(expected, dict):
        assert isinstance(actual, dict) and set(actual) == set(expected), (
            f"[{case_id}] {field}: expected {expected!r}, got {actual!r}")
        for k in expected:
            check_value(case_id, f"{field}.{k}", expected[k], actual[k])
        return
    if isinstance(expected, (bool, str)) or expected is None:
        assert actual == expected and type(actual) is type(expected), (
            f"[{case_id}] {field}: expected {expected!r}, got {actual!r}")
        return
    if isinstance(expected, int):
        assert not isinstance(actual, bool) and actual == expected, (
            f"[{case_id}] {field}: expected {expected!r}, got {actual!r}")
        return
    # float
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"[{case_id}] {field}: expected float {expected!r}, got {actual!r}")
    if math.isnan(expected):
        assert math.isnan(actual), f"[{case_id}] {field}: expected NaN, got {actual!r}"
        return
    if math.isinf(expected):
        assert actual == expected, f"[{case_id}] {field}: expected {expected!r}, got {actual!r}"
        return
    if not math.isclose(actual, expected, rel_tol=REL_TOL, abs_tol=ABS_TOL):
        rel = abs(actual - expected) / abs(expected) if expected else float("inf")
        raise AssertionError(
            f"[{case_id}] {field}: expected {expected!r}, got {actual!r}, relative difference {rel:.3e}")


def build_options(options: dict) -> PipelineOptions:
    params = AnalysisParams(**{snake(k): v for k, v in options["params"].items()})
    kwargs = {snake(k): v for k, v in options.items() if k not in ("params", "clicks")}
    kwargs["params"] = params
    if options.get("clicks") is not None:
        kwargs["clicks"] = [tuple(c) for c in options["clicks"]]
    return PipelineOptions(**kwargs)


@pytest.mark.parametrize("path", CASE_FILES, ids=_ids(CASE_FILES))
def test_case_matches_webapp(path):
    case = _load_json(path)
    case_id = case["case_id"]
    synced, _parsed = load_one_file(read_input(case["input_file"]))
    opts = build_options(case["options"])

    if case["error"] is not None:
        with pytest.raises(Exception) as caught:
            run_one_file_pipeline(synced, opts)
        exc = caught.value
        actual_error = exc.code if isinstance(exc, PipelineError) else str(exc)
        assert actual_error == case["error"], (
            f"[{case_id}] error: expected {case['error']!r}, got {actual_error!r} ({exc!r})")
        return

    results = restore_nonfinite(case["results"], case["nonfinite"])
    actual = run_one_file_pipeline(synced, opts)
    for name, expected in results.items():
        field = snake(name)
        assert hasattr(actual, field), f"[{case_id}] result has no field {field!r} (webapp: {name})"
        check_value(case_id, name, expected, getattr(actual, field))
    for name in OPTIONAL_RESULT_FIELDS:
        if name not in results:
            got = getattr(actual, snake(name), None)
            assert got is None, f"[{case_id}] {name}: absent in webapp, got {got!r} (must be None)"


@pytest.mark.parametrize("path", PARSER_FILES, ids=_ids(PARSER_FILES))
def test_parser_matches_webapp(path):
    gold = _load_json(path)
    case_id = os.path.basename(path)[:-5]
    gold = restore_nonfinite(gold, gold.get("nonfinite"))
    parsed = parse_combined_file(read_input(gold["input_file"]))
    assert parsed is not None, f"[{case_id}] parser returned None"
    check_value(case_id, "n", gold["n"], len(parsed.time))
    for name, expected in gold["fields"].items():
        values = [float(v) for v in getattr(parsed, name)]
        check_value(case_id, f"{name}.n", expected["n"], len(values))
        check_value(case_id, f"{name}.first3", expected["first3"], values[:3])
        check_value(case_id, f"{name}.last3", expected["last3"], values[-3:])
        # NaN is skipped in the sum; fsum so the order of adding cannot matter
        check_value(case_id, f"{name}.sum", expected["sum"],
                    math.fsum(v for v in values if not math.isnan(v)))


@pytest.mark.parametrize("path", LAGFIT_FILES, ids=_ids(LAGFIT_FILES))
def test_lagfit_matches_webapp(path):
    case_id = os.path.basename(path)[:-5]
    entries = _load_json(path)
    points_raw = entries[0]["points"]
    points = [LagPoint(period=p["period"], lag=p["lag"]) for p in points_raw]
    fits = fit_lag_models(points)
    assert len(fits) == len(entries), (
        f"[{case_id}] number of fits: expected {len(entries)}, got {len(fits)}")
    assert [f.kind for f in fits] == [e["kind"] for e in entries], (
        f"[{case_id}] fit order (best first): expected {[e['kind'] for e in entries]}, "
        f"got {[f.kind for f in fits]}")
    for e, fit in zip(entries, fits):
        cid = f"{case_id}/{e['kind']}"
        check_value(cid, "params", e["params"], list(fit.params))
        check_value(cid, "label", e["label"], fit.label)
        check_value(cid, "rms", e["rms"], fit.rms)
        check_value(cid, "r2", e["r2"], fit.r2)
        check_value(cid, "n", e["n"], fit.n)
        check_value(cid, "pMin", e["pMin"], fit.p_min)
        check_value(cid, "pMax", e["pMax"], fit.p_max)
        check_value(cid, "serialized", e["serialized"], serialize_fit(fit))
        check_value(cid, "described", e["described"], describe_lag_model(serialize_fit(fit)))
        for period in PREDICT_PERIODS:
            check_value(cid, f"predict({period})", e["predict_at"][str(period)], fit.predict(period))


def test_describe_lag_model_of_nothing():
    assert describe_lag_model(None) == "\u2014"
    assert describe_lag_model("") == "\u2014"


SPEED_CASES = [p for p in CASE_FILES if os.path.basename(p).startswith("al2o3_ctwa__")]


@pytest.mark.slow
@pytest.mark.parametrize("path", SPEED_CASES, ids=_ids(SPEED_CASES))
def test_pipeline_speed(path):
    """Every mode on al2o3_ctwa finishes in under 10 s (errors count: they ran the maths too)."""
    case = _load_json(path)
    synced, _parsed = load_one_file(read_input(case["input_file"]))
    opts = build_options(case["options"])
    start = time.perf_counter()
    try:
        run_one_file_pipeline(synced, opts)
    except Exception:
        pass
    elapsed = time.perf_counter() - start
    assert elapsed < 10.0, f"[{case['case_id']}] took {elapsed:.1f} s (limit 10 s)"
