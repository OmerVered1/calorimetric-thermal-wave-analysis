"""ctwa.analysis.row must give the rows the webapp's lib/analysisRow.ts gave.

tests/golden/analysis/row_*.json hold {meta, plot_inputs, row} written by the
webapp's own code for the matching al2o3_ctwa__<case>.json case.
Numbers: rel 1e-9 (abs 1e-12); graph_image / extra_data are compared after json.loads.
"""

from __future__ import annotations

import glob
import json
import math
import os
import re

import pytest

from tests.test_analysis_matches_webapp import (
    GOLDEN_DIR, build_options, check_value, read_input, snake,
)

ROW_FILES = sorted(glob.glob(os.path.join(GOLDEN_DIR, "row_*.json")))
JSON_FIELDS = ("graph_image", "extra_data")


def _ids(paths):
    return [os.path.basename(p)[4:-5] for p in paths]


def _case(path):
    name = os.path.basename(path)[4:-5]
    with open(os.path.join(GOLDEN_DIR, f"al2o3_ctwa__{name}.json"), encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("path", ROW_FILES, ids=_ids(ROW_FILES))
def test_row_matches_webapp(path):
    from ctwa.analysis.pipeline import load_one_file, run_one_file_pipeline
    from ctwa.analysis.row import RowMeta, build_analysis_plot, build_analysis_row

    with open(path, encoding="utf-8") as f:
        gold = json.load(f)
    case = _case(path)
    synced, _ = load_one_file(read_input(case["input_file"]))
    opts = build_options(case["options"])
    results = run_one_file_pipeline(synced, opts)
    meta = RowMeta(**{snake(k): v for k, v in gold["meta"].items()})
    plot = build_analysis_plot(synced, results, opts)
    row = build_analysis_row(results, meta, plot)

    expected = gold["row"]
    assert set(row) == set(expected), (
        f"keys differ: only python {sorted(set(row) - set(expected))}, only webapp {sorted(set(expected) - set(row))}")
    for key, exp in expected.items():
        if key in JSON_FIELDS:
            assert isinstance(row[key], str)
            json.dumps(json.loads(row[key]), allow_nan=False)
            check_value(path, key, json.loads(exp), json.loads(row[key]))
        else:
            check_value(path, key, exp, row[key])
    json.dumps(row, allow_nan=False)


def test_square_forces_fourier_and_omissions():
    from ctwa.analysis.pipeline import load_one_file, run_one_file_pipeline
    from ctwa.analysis.row import RowMeta, build_analysis_row

    path = os.path.join(GOLDEN_DIR, "row_AutoFit_raw.json")
    with open(path, encoding="utf-8") as f:
        gold = json.load(f)
    case = _case(path)
    synced, _ = load_one_file(read_input(case["input_file"]))
    results = run_one_file_pipeline(synced, build_options(case["options"]))
    fields = {snake(k): v for k, v in gold["meta"].items()}
    fields.update(source_file_name=None, model_name="  x y  ", wave_type="square")
    row = build_analysis_row(results, RowMeta(**fields), None)
    assert "c80_filename" not in row and "graph_image" not in row
    assert row["analysis_mode"] == "Fourier" and row["model_name"] == "x y"
    # extra_data: two-file offsets only in two-file mode, only when non-zero
    fields.update(input_mode="two", day_offset=1, clock_ahead=2.5, wave_type="sine")
    ed = json.loads(build_analysis_row(results, RowMeta(**fields), None)["extra_data"])
    assert ed["day_offset"] == 1 and ed["clock_ahead_s"] == 2.5
    fields.update(input_mode="one")
    assert "day_offset" not in json.loads(build_analysis_row(results, RowMeta(**fields), None)["extra_data"])


def test_nan_becomes_none_and_serializes():
    import dataclasses
    from ctwa.analysis.pipeline import load_one_file, run_one_file_pipeline
    from ctwa.analysis.row import RowMeta, build_analysis_row, clean_for_json

    path = os.path.join(GOLDEN_DIR, "row_AutoFit_raw.json")
    with open(path, encoding="utf-8") as f:
        gold = json.load(f)
    case = _case(path)
    synced, _ = load_one_file(read_input(case["input_file"]))
    results = run_one_file_pipeline(synced, build_options(case["options"]))
    results = dataclasses.replace(results, ln_term=math.nan, alpha_phase_raw=math.inf)
    meta = RowMeta(**{snake(k): v for k, v in gold["meta"].items()})
    row = build_analysis_row(results, meta, {"data": [{"x": [1.0, math.nan]}], "layout": {}})
    assert row["ln_term"] is None and row["alpha_phase_raw"] is None
    json.dumps(row, allow_nan=False)
    assert json.loads(row["graph_image"])["data"][0]["x"] == [1.0, None]
    assert clean_for_json({"a": [math.nan, -math.inf, 1]}) == {"a": [None, None, 1]}


def test_find_duplicate():
    from ctwa.analysis.row import find_duplicate

    row = {"model_name": "Foam", "analysis_mode": "AutoFit", "period_t": 100.0, "amplitude_a1": 10.0}
    base = {"id": 1, "model_name": " foam ", "analysis_mode": "AutoFit", "period_t": 101.5, "amplitude_a1": 10.1}
    assert find_duplicate([base], row) is base
    assert find_duplicate([dict(base, period_t=102.5)], row) is None   # tol max(1, 2)=2
    assert find_duplicate([dict(base, period_t=101.9)], row) is not None
    assert find_duplicate([dict(base, amplitude_a1=10.3)], row) is not None   # tol max(0.5, .2)
    assert find_duplicate([dict(base, amplitude_a1=10.6)], row) is None
    assert find_duplicate([dict(base, analysis_mode="Manual")], row) is None
    assert find_duplicate([dict(base, model_name="other")], row) is None
    assert find_duplicate([dict(base, model_name=None)], row) is None
    assert find_duplicate([], row) is None
    # first match wins
    second = dict(base, id=2)
    assert find_duplicate([base, second], row)["id"] == 1
