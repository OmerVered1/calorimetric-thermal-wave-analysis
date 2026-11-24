# Calibration Tab (Plan 4 of the CTWA 2.0 build) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the CTWA app, mark reference runs, keep known-α presets, fit a device-lag model, and write calibrated copies of analyses (one or a whole material at once), with the same numbers and the same saved rows as the webapp's Calibration page.

**Architecture:**
- **Maths** (`ctwa/analysis/calibration.py`, `calibration_logic.py`, `calibration_batch.py`, no Qt): literal ports of the four not-yet-ported `lib/analysis.ts` functions and of the page's own logic (picker, lag source, batch statuses, calibrated-row builder). Pinned against values produced by running the TypeScript.
- **State and writes** (`ctwa/ui/calibration/state.py`, `writes.py`): one `CalibrationState` holds rows, presets and every selection. One `WriteQueue` runs all writes one at a time through the shared `ResultsLoader`.
- **Views** (`ctwa/ui/calibration/*.py`): one scrolling page of section cards (presets, mark references, reference table, calibrate one run with the pyqtgraph fit chart, batch) inside `CalibrationTab`.
- **Wiring:** one delimited block in `ctwa/app.py`, in the final task.

**Tech Stack:** Python 3.9, PySide6, pyqtgraph, numpy; reuses `ctwa.analysis.lag_fit`, `ctwa.analysis.references`, `ctwa.analysis.jsmath`, and the Results Foundation (`ctwa/results/*`, `ctwa/ui/results_loader.py`).

**Spec:** `docs/superpowers/specs/2026-11-24-ctwa-desktop-analysis-design.md` (stage 5). Webapp reference: `angstrom-webapp-vercel/app/calibration/page.tsx`, `lib/analysis.ts` (L503–612), `lib/analysisColumns.ts` (`withLnValidity`), `lib/i18n/en.ts` (`calibration.*`, `common.*`). The inventory is `plan4-calibration-inventory.md` in the session scratchpad.

> **Controller note (24 Nov):** the Results Foundation now provides `ResultsLoader.apply_preset_insert/apply_preset_delete`, per-write signals `write_done(op, token, result)` / `write_failed(op, token, kind, message)` (each apply_* returns a token; writes run one at a time in call order) and a `store` property. Use these for presets and for sequencing batch writes instead of waiting on `rows_changed`. Ruling accepted: a reference with no period is excluded from fits (the TS would fit it as period 0). Tab order at merge: Runs, Analysis, Calibration, Results, Statistics.

## Global Constraints

- **Branch:** `plan4-calibration`, in its own git worktree, branched from `desktop-analysis` after the Results Foundation (Plan 2.5) has landed there. Plans 3 and 5 are built in parallel in their own worktrees, so this plan edits **no existing file** except `ctwa/app.py` (one delimited block, last task) and `keithley_suite.spec` (`hiddenimports`, same task). No push, no tags, no commits to `desktop-analysis`/`master`.
- **Foundation names are used exactly:** `ctwa.results.helpers` (`format_alpha`, `with_ln_validity`, `material_color`), `ctwa.results.columns.LIST_COLUMNS`, and `ResultsLoader` (signals `rows_changed(list)`, `presets_changed(list)`, `failed(str, str)`, `graph_loaded(int, object)`; methods `refresh()`, `rows()`, `presets()`, `request_graph(id)`, `apply_update(id, changes)`, `apply_delete(id)`, `apply_insert(row)`). Do not edit the Foundation; if a name differs from this list, change only the one adapter line in `writes.py` and say so in the report.
- **Maths parity:** the webapp is the reference. Every function is a literal port: same order of operations, JS number formatting through `ctwa.analysis.jsmath` (`js_to_fixed`, `js_number_to_string`, `js_to_precision`), sums as plain left-to-right loops (never `math.fsum`, never the built-in `sum` on floats), `NaN`/`None` handled like JS comparisons (`not (x > 0)`). Expected values in tests are literals produced by running the TS with a throwaway `npx tsx` script (kept outside the repo); no live recomputation in tests.
- **Writes, exactly as the webapp** (all through `ResultsLoader`, off the GUI thread, followed by a refresh):
  - calibrated copy = INSERT of a new `analyses` row, the source row is never edited;
  - mark / unmark / edit known α = one UPDATE per row, only the changed fields;
  - presets = INSERT / DELETE on `alpha_presets` (no update);
  - batch save = one confirmation, then one insert per run, sequential, a failure never stops the rest;
  - `graph_image` is fetched for the rows being saved (`request_graph`), and a failed fetch means `null`.
- **GUI never blocks:** no network call, no loop over the network, on the GUI thread. A write in progress disables every write button of the tab.
- **Untouchable:** `ctwa/instruments/`, `keithley*_driver.py`. `tests/test_equivalence_with_original_windows.py` stays green.
- **Python 3.9** (`from __future__ import annotations`). Run tests with `/usr/bin/python3 -m pytest`, Qt tests with `QT_QPA_PLATFORM=offscreen`. No real network; tests use `tests/calibration_fakes.py` (Task 4).
- **Texts:** English, copied from the webapp's `lib/i18n/en.ts` (`calibration.*`, `common.all` = "All", `common.none` = "None", `common.loading` = "Loading..."). Put them in one dict `TEXT` in `ctwa/ui/calibration/texts.py` (Task 4) so no view contains a literal sentence.
- **Commits:** messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus (most likely user-facing failures; each is pinned by a test in the task named)

1. **Login lost or internet down in the middle of "Save all":** the queue stops at the first `login` failure, reports "written n of m", writes nothing twice, and the next default pick excludes the runs already written (Task 4 queue test, Task 9 re-pick test).
2. **Double click on Save / Save all / Mark:** a second click while a write is running does nothing, so no duplicate calibrated copy (Task 4 `busy` test, Task 8 and 9 button tests).
3. **Stale selections after a refresh:** a reference unmarked, a run deleted in Summary, or a new material, must drop from the ticked lists, the target, and the batch pick, with no crash and no copy written for a vanished id (Task 4 `reconcile` test).
4. **Temperature filter never matches:** the temperature combo and the rows must use the same key (`25` not `25.0`), and the choice survives a refresh (Task 2 `temp_key` test, Task 6 filter test).
5. **Unchanged or invalid known α:** leaving the α cell without a change, with `0`, with text, or negative sends no request; a not-calibratable run (corrected lag ≤ 0) can never be saved, single or batch (Task 6 `alpha cell` test, Task 8 and 9 tests).

---

### Task 1: Worktree and the four `lib/analysis.ts` functions

**Files:**
- Create: `ctwa/analysis/calibration.py`, `tests/test_calibration_lib.py`
- Test data: reads `tests/golden/analysis/al2o3_ctwa__AutoFit_raw.json` and `fiber_150_600__AutoFit_raw.json`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class AppliedLag: net_lag_dt: float; net_phase_phi: float; alpha_combined_cal: Optional[float]; alpha_phase_cal: float`
  - `calibration_basis(a: dict) -> Optional[Tuple[float, float]]` (returns `(dr_m, w)`)
  - `true_lag_for_alpha(a, known_alpha_mm2s, method="phase") -> Optional[float]`
  - `device_lag_from_reference(a, known_alpha_mm2s, method="phase") -> Optional[float]`
  - `apply_device_lag(a, lag) -> Optional[AppliedLag]`
- Rows are `dict`s with the DB column names (`r1_mm`, `r2_mm`, `angular_freq_w`, `raw_lag_dt`, `ln_term`), as the loader returns them.

- [ ] **Step 0: Worktree.** From the CTWA repo: confirm `ctwa/results/helpers.py` and `ctwa/ui/results_loader.py` exist on `desktop-analysis` and `/usr/bin/python3 -m pytest tests/test_results_foundation.py -q` passes. Then `git worktree add ../calorimetric-thermal-wave-analysis-plan4 -b plan4-calibration desktop-analysis` and work only there. Open `ctwa/ui/results_loader.py` and note in the Task 4 report which attribute holds the `ResultsStore` (used there for presets).
- [ ] **Step 1: Pin the TS values** with a throwaway script in the session scratchpad (not in either repo) that imports `lib/analysis.ts` and `lib/analysisColumns.ts` from the webapp and prints the numbers below; check they equal the literals here before pasting.
- [ ] **Step 2: Failing tests** (`tests/test_calibration_lib.py`; helper `row_from_golden(case)` builds a row from the golden file: `r1_mm`/`r2_mm` from `options.params.r1Mm/r2Mm`, `angular_freq_w`, `raw_lag_dt`, `ln_term`, `period_t` from `results`). Compare with `pytest.approx(rel=1e-12)`; `None` exactly.
  - Real reference/target pair. `ref` = `al2o3_ctwa__AutoFit_raw` (w 0.07830413052150505, raw lag 46.428548208374245, ln 4.043654779334957), known α 5.829:
    - `true_lag_for_alpha(ref, 5.829)` = 8.519616453527574; `"combined"` = 1.40556420142513.
    - `device_lag_from_reference(ref, 5.829)` = 37.90893175484667; `"combined"` = 45.022984006949116.
    - `apply_device_lag(ref, 10)` = (36.428548208374245, 2.8525057936174756, 2.2490695163700366e-07, 3.188235662579634e-07).
    - `apply_device_lag(ref, 0)` = (46.428548208374245, 3.635547098832526, 1.764654301344128e-07, 1.9627452500328294e-07), equal to the golden `alphaCombinedRaw`/`alphaPhaseRaw`.
    - `apply_device_lag(ref, 47)` is `None` (lag above raw lag).
  - `fiber` = `fiber_150_600__AutoFit_raw` (raw lag 130.41806355143027, ln 0.7989996447735968), lag taken from the reference: `apply_device_lag(fiber, 37.90893175484667)` = (92.5091317965836, 1.279281183287191, 4.482162758350282e-07, 2.799420876759157e-07). Lag -20 (negative lags are accepted): net 150.41806355143027, α phase 1.0588572644407653e-07.
  - Hand-built `base` = `{r1_mm: 6.72, r2_mm: 14.86, angular_freq_w: 0.05, raw_lag_dt: 60, ln_term: 2}`:
    - `apply_device_lag(base, 20)` = (40, 2, 4.141225000000002e-07, 4.1412250000000013e-07); lag 60 → `None`; lag `nan` → `None`.
    - raw lag -60 with lag 20 gives net 40 (uses `abs`).
    - `ln_term` -0.3: `true_lag_for_alpha(…, 5, "combined")` is `None`, and `apply_device_lag(…, 20).alpha_combined_cal` is `None` with α phase 4.1412250000000013e-07.
    - `device_lag_from_reference({**base, "raw_lag_dt": 5}, 5)` = -6.511698397716996 (negative kept).
    - `None`: known α 0 or -1; `angular_freq_w` 0; `r1_mm` None; `r2_mm` = 6.72 (dr 0); `raw_lag_dt` None for `device_lag_from_reference`.
- [ ] **Step 3: Run, see FAIL** (`/usr/bin/python3 -m pytest tests/test_calibration_lib.py -q`, import error).
- [ ] **Step 4: Implement** as literal ports of `calibrationBasis`, `trueLagForAlpha`, `deviceLagFromReference`, `applyDeviceLag`. Decisions: use a helper `_pos(x)` = `x is not None and x > 0` for every `!(x > 0)` test (NaN and None are false); `isFinite(w)` is `math.isfinite`; α is `known * 1e-6`; `(dr / phi) ** 2` stays `** 2`.
- [ ] **Step 5: Run, see PASS. Commit.**

### Task 2: Page logic, part 1 (rows, picker, lag source)

**Files:**
- Create: `ctwa/analysis/calibration_logic.py`, `tests/test_calibration_logic.py`

**Interfaces:**
- Consumes: Task 1; `ctwa.analysis.lag_fit.fit_lag_models`, `ctwa.analysis.types.LagFit/LagPoint`; `ctwa.analysis.jsmath`; `ctwa.results.helpers.with_ln_validity`.
- Constants: `TEMP_SPREAD_WARN_C = 30`, `DIRECT_PERIOD_LO = 0.8`, `DIRECT_PERIOD_HI = 1.25`.
- Produces:
  - `temp_key(v: Optional[float]) -> str` (`js_number_to_string`, `""` for None); `label_of(a) -> str`; `num(v, d=2) -> str`;
  - `split_rows(rows) -> Tuple[List[dict], List[dict], Dict[int, List[int]]]` = references (`is_reference`), non-references (`not is_reference and calibrated_from_id is None`), copies by source id; order of `rows` is kept (newest first);
  - `all_materials(rows) -> List[str]` (non-empty, sorted by code point); `temps_for(non_refs, material) -> List[str]` (keys, numeric ascending, `[]` for no material); `ref_temps(refs, material) -> List[str]`;
  - `@dataclass RefLag: ref: dict; lag: Optional[float]; true_lag: Optional[float]`; `ref_lags(refs, method) -> List[RefLag]`;
  - `selected_lags(rl, ids) -> List[RefLag]` (order of `rl`; lag finite; `period_t` finite and > 0);
  - `@dataclass PickerRow: ref, lag, true_lag, d_t: Optional[float], d_p: Optional[float]`; `picker_rows(rl, target, material, temp, near_only, near_pct, sort) -> List[PickerRow]`, `sort` in `"period" | "nearPeriod" | "nearTemp"`;
  - `temp_spread(sel) -> Optional[float]`; `mark_warnings(selected_rows) -> dict` (`mixed_materials: Optional[List[str]]`, `temp_spread: Optional[float]`);
  - `active_fit(fits, model_kind) -> Optional[LagFit]`; `active_source(user: Optional[str], fit) -> str`;
  - `direct_lag(sel) -> Optional[float]`; `direct_mean_period(sel) -> Optional[float]`;
  - `@dataclass Applied: lag: float; out_of_range: bool; period_mismatch: bool; ratio: Optional[float]`; `applied_lag(target, source, fit, d_lag, d_mean_p) -> Optional[Applied]`;
  - `fit_points(sel) -> List[LagPoint]`; `curve_points(fit, n=120) -> Tuple[List[float], List[float]]` (`pMin * (pMax/pMin) ** (i/(n-1))`, non-finite dropped).

- [ ] **Step 1: Failing tests.** Fixture `refs` = five rows ids 10–14, `period_t` 75, 150, 300, 600, 1200, `angular_freq_w` = 2π/period, `r1_mm` 6.72, `r2_mm` 14.86, `ln_term` 3, `temperature_c` 800.0 (id 14: 780.5), `is_reference` True, `reference_alpha_mm2s` 5.829, `model_name` "Stainless Steel", `raw_lag_dt` = 28.2366967506017, 40.64844825385532, 57.4733935012034, 81.29689650771064, 114.9467870024068. Target = `{id: 99, period_t: 400, temperature_c: 800.0, raw_lag_dt: 150, angular_freq_w: 0.015707963267948967, ln_term: 3, amplitude_a1: 4, amplitude_a2: 1, r1_mm: 6.72, r2_mm: 14.86}`.
  - Formatting: `temp_key(25.0)` = "25", `temp_key(766.5)` = "766.5", `temp_key(None)` = "". `num(None)` = "—", `num(float("nan"))` = "—", `num(46.428548208374245)` = "46.43", `num(2.5, 0)` = "3", `num(1.005, 2)` = "1.00". `label_of` of `{id: 12, model_name: "Stainless Steel", test_date: "17/11/2026", temperature_c: 800.0, period_t: 300.4, analysis_mode: "AutoFit"}` = "Stainless Steel | 17/11/2026 | 800°C | T=300s | AutoFit #12"; with `temperature_c` None the temperature part is dropped.
  - `split_rows`: a copy (`calibrated_from_id` 10) and a reference never appear in non-references; `copies[10] == [copy_id]`. `temps_for` returns `["780.5", "800"]` for rows with 800.0, 780.5, 800.0; `all_materials` skips empty names and does not trim (`"A "` and `"A"` stay two).
  - `ref_lags(refs, "phase")` device lags = 20, 29, 41, 58, 82 (`approx rel=1e-9`); a reference without `reference_alpha_mm2s` has `lag` None and is dropped by `selected_lags`; a reference with `period_t` None is dropped too (deliberate: the TS would fit a null period as 0).
  - `picker_rows` (input order reversed 14…10): sort "period" → ids [10, 11, 12, 13, 14]; "nearPeriod" → [12, 13, 11, 10, 14]; "nearTemp" → [13, 12, 11, 10, 14] (stable, `d_t` None sorts last). Near-only 50 % on target 400 keeps [12, 13] (ratio 1.5 is kept, 0.375 is dropped); near_pct 0 or None filters nothing. Material "Other" → []. Temp key "780.5" → [14].
  - `temp_spread` of ids 10–14 = 19.5, `mark_warnings` on rows at 800 and 829.9 gives `temp_spread` 29.9 → None, at 800 and 830.5 → 30.5; two materials give `mixed_materials` both names; one selected row gives no spread.
  - Fits on all five (`fit_lag_models(fit_points(sel))`, TS pins): kinds in order sqrt, power, linear, physical; sqrt `rms` 0.16533243660484465, `predict(400)` 47.25456790896485; `active_fit(fits, None)` is the sqrt fit, `active_fit(fits, "linear")` the linear one, `active_fit(fits, "gone")` the best. `active_source(None, fit)` = "curve", `active_source(None, None)` = "direct", `active_source("direct", fit)` = "direct".
  - Direct: `direct_lag(sel)` = 46 (`approx rel=1e-9`), `direct_mean_period(sel)` = 465, empty selection → None.
  - `applied_lag`: curve at target 400 → lag 47.25456790896485, not out of range; target period 74.9 and 1200.1 → `out_of_range` True, 75 and 1200 → False. Direct at 400 → ratio 0.8602150537634409, no mismatch; at 372 (ratio exactly 0.8) and 581.25 (exactly 1.25) no mismatch; at 371 and 582 mismatch; at 700 mismatch. Target without `period_t` → None. Direct with `d_lag` None → None.
  - `curve_points(fit)`: 120 points, first x = 75, last x ≈ 1200 (`approx rel=1e-12`), x[i] = 75 * 16 ** (i/119).
- [ ] **Step 2: See FAIL. Step 3: Implement** (decisions: `Number(refNearPct)` becomes a float argument; the near window test is `ratio < 1 - pct/100 or ratio > 1 + pct/100`; sorts use `sorted(..., key=...)`, stable like JS; null distance is `float("inf")`; the period sort key is `period_t or 0`; the `selected_lags` period guard is the one deviation, commented as such). **Step 4: PASS. Step 5: Commit.**

### Task 3: Page logic, part 2 (batch, calibrated row, reports)

**Files:**
- Create: `ctwa/analysis/calibration_batch.py`, `tests/test_calibration_batch.py`

**Interfaces:**
- Consumes: Tasks 1–2; `ctwa.analysis.lag_fit.serialize_fit/serialize_direct`.
- Produces:
  - `@dataclass BatchRow: a: dict; existing: List[int]; lag: Optional[float]; result: Optional[AppliedLag]; status: str` (`"ok" | "outOfRange" | "notCalibratable"`);
  - `batch_targets(non_refs, material, temp_key_) -> List[dict]` (exact `model_name`, temperature compared by `temp_key`; `""` = all);
  - `batch_rows(targets, source, fit, d_lag, d_mean_p, copies) -> List[BatchRow]`;
  - `batch_calibratable(rows)`, `batch_default_ids(rows) -> List[int]`, `batch_ok(rows, picked: Optional[List[int]]) -> List[BatchRow]`, `toggle_pick(picked, default_ids, id, on) -> List[int]`;
  - the four shortcuts `pick_default() -> None`, `pick_recalibrate(rows)`, `pick_clear()`, `pick_in_range(rows)` (lists of ids; `None` = default);
  - `calibration_model_string(source, fit, d_lag) -> Optional[str]`; `build_calibrated_row(src, lag, result, graph_image, ref_ids, model) -> dict`;
  - `mark_report(done, total, failures)`, `batch_report(written, n_ok, n_rows, n_calibratable, had_copies, failures) -> str`.
- Statuses: not calibratable when `period_t` is missing/non-finite, no lag can be formed, or `apply_device_lag` is `None`; else "outOfRange" when flagged (curve outside `[pMin, pMax]`, direct period ratio outside 0.8–1.25), else "ok".

- [ ] **Step 1: Failing tests** (source rows built as in Task 2; direct source, `d_lag` 46, `d_mean_p` 465; targets t1 `{id: 1, period_t: 400, raw_lag_dt: 150}`, t2 `{id: 2, period_t: 1000, raw_lag_dt: 150}`, t3 `{id: 3, period_t: None}`, t4 `{id: 4, period_t: 450, raw_lag_dt: 40}`, t5 `{id: 5, period_t: 500, raw_lag_dt: 150}`, all with the geometry of Task 2 and `angular_freq_w` = 2π/period except where `period_t` is None (use 0.05); `copies = {5: [77]}`):
  - statuses: t1 ok, t2 outOfRange, t3 notCalibratable with `lag` None, t4 notCalibratable with `lag` 46 and `result` None, t5 ok with `existing == [77]`.
  - `batch_default_ids` = [1, 2]; `pick_recalibrate` = [1, 2, 5]; `pick_in_range` = [1, 5]; `pick_clear` = []; `batch_ok(rows, None)` ids [1, 2]; `batch_ok(rows, [5, 4])` ids [5] (t4 dropped, it has no result).
  - `toggle_pick(None-materialized default [1, 2], 5, True)` = [1, 2, 5]; off for 1 → [2]; toggling twice is idempotent.
  - Curve source with the Task 2 sqrt fit: t1 lag 47.25456790896485 (result `net_lag_dt` 102.74543209103516, `alpha_phase_cal` 1.9979006643647911e-07); no fit and no direct lag → every row notCalibratable.
  - `batch_targets` with material "Stainless Steel" and temp key "780.5" returns only the 780.5 rows; key `""` returns all of that material.
  - `build_calibrated_row(target, 47.25456790896485, result, "G", [10, 11, 12, 13, 14], "sqrt:a=-0.341302,b=2.37979")` has **exactly** these 34 keys: `model_name, test_date, test_time, temperature_c, power_source_device, power_response_device, gas_atmosphere, wave_type, analysis_mode, r1_mm, r2_mm, amplitude_a1, amplitude_a2, period_t, frequency_f, period_t_resp, frequency_f_resp, angular_freq_w, raw_lag_dt, raw_phase_phi, ln_term, alpha_combined_raw, alpha_phase_raw, graph_image, use_calibration, system_lag, net_lag_dt, net_phase_phi, alpha_combined_cal, alpha_phase_cal, is_reference, calibrated_from_id, calibration_ref_ids, calibration_model`. Values: `use_calibration` True, `is_reference` False, `calibrated_from_id` 99, `calibration_ref_ids` "10,11,12,13,14", `system_lag` = lag, copied fields equal the source; it contains no `id`, `created_at`, `reference_alpha_mm2s`, `extra_data`, `graph_json`, `c80_filename`, `keithley_filename`, `t_cal`, `t_src`, `t_min`, `t_max`, unit columns. It is `json.dumps(..., allow_nan=False)`-safe. The source dict is unchanged afterwards.
  - Model strings from the TS: curve `sqrt:a=-0.341302,b=2.37979`; physical fit of the same data `physical:t1=0.0373583,t2=79.0934`; direct `direct:lag=46.0000`; source "direct" with `d_lag` None → None.
  - Direct `build` for the target with lag 46 equals (net 104, φ 1.6336281798666925, α comb 1.0618525641025642e-07, α phase 1.9499894355199244e-07).
  - Reports (webapp text): `mark_report(3, 4, ["#12: boom"])` = "Marked as reference: 3/4 · #12: boom"; `batch_report(2, 2, 5, 3, 1, [])` = "Saved 2/2 · 3 skipped (not calibratable) · 2 not calibratable · 1 already calibrated"; `batch_report(5, 5, 5, 5, 0, [])` = "Saved 5/5"; with `["#7: x", "#8: y"]` appended " · #7: x; #8: y". (skipped = n_rows − n_ok; not-calibratable = n_rows − n_calibratable.)
- [ ] **Step 2: See FAIL. Step 3: Implement** literally from `batchRows`, `batchOk`, `buildCalibratedRow`, `saveBatch`. **Step 4: PASS. Step 5: Commit.**

### Task 4: State, texts, write queue, test fakes

**Files:**
- Create: `ctwa/ui/calibration/__init__.py`, `texts.py`, `state.py`, `writes.py`, `tests/calibration_fakes.py`, `tests/test_calibration_state.py`, `tests/test_calibration_writes.py`

**Interfaces:**
- `texts.TEXT: Dict[str, str]`: every `calibration.*` string of `en.ts` that Tasks 5–10 show, keyed without the prefix (e.g. `TEXT["tooFewPoints"]`), plus `all`, `none`, `loading`; `{n}`/`{name}` placeholders kept.
- `CalibrationState(QObject)`, signal `changed()`:
  - inputs: `set_rows(rows)` (applies `with_ln_validity`, prunes every selection to ids that still exist, clears `target_id` if gone, resets the batch pick when the candidate set changed), `set_presets(list)`;
  - plain attributes with setters that emit `changed`: `method` ("phase"), `selected_ref_ids: List[int]`, `model_kind`, `lag_source`, `target_id`, `ref_filter_material`, `ref_filter_temp`, `ref_near_only` (False), `ref_near_pct` (50.0), `ref_sort` ("period"), `mark_alpha` (""), `mark_ids: List[int]`, `mark_filter_material`, `mark_filter_temp`, `batch_material`, `batch_temp`, `batch_picked: Optional[List[int]]`;
  - derived, cached until the next `changed`: `references`, `non_references`, `copies`, `ref_lags`, `selected`, `fits`, `fit`, `source`, `direct_lag`, `direct_mean_period`, `target`, `applied`, `calibrated`, `batch_rows`, `picker`;
  - `apply_preset(p)`: sets `mark_alpha = js_number_to_string(p.alpha_mm2s)`, `mark_filter_material = p.material_name`, `mark_filter_temp = ""`;
  - rule: changing `ref_filter_material` or `mark_filter_material` clears the matching temperature filter; changing `batch_material`/`batch_temp` sets `batch_picked = None`.
- `WriteOp(kind, id, data, label)` with kind in `update | insert | delete | preset_insert | preset_delete`.
- `WriteQueue(loader, parent=None)`: `busy: bool`; `run(ops: List[WriteOp], on_done: Callable[[WriteSummary], None]) -> bool` (False and nothing happens when busy); `with_graphs(ids, callback)`; signal `progress(int done, int total)`. `WriteSummary(done: int, total: int, failures: List[str], aborted: Optional[str])`.
  - Op *i+1* starts after op *i* succeeded (`rows_changed`) or failed (`failed`). A `failed("login", …)` aborts the rest (`aborted` set). Any other kind records `"{label}: {message}"` and continues. Each op has a 60 s watchdog (failure "timed out").
  - Preset ops call the loader's `ResultsStore` (`insert_preset`/`delete_preset`) in a `QRunnable`, then `loader.refresh()`.
  - `with_graphs`: calls `request_graph(id)` for every id, collects `graph_loaded` for 20 s at most, then calls `callback({id: str|None})` (missing → None).
- `tests/calibration_fakes.py`: `FakeLoader(QObject)` with the loader's signals and methods, `rows_list`, `presets_list`, an `ops` log, `fail_at: Dict[int, Tuple[str, str]]` (op index → (kind, message)), `graphs: Dict[int, Optional[str]]`, a `store` with recording `insert_preset`/`delete_preset`; completion is emitted through `QTimer.singleShot(0, …)`. `make_rows()` builds the Task 2 fixtures plus targets and copies.

- [ ] **Step 1: Failing tests.**
  - State: `set_rows` with the Task 2 data selects nothing; after `selected_ref_ids = [10..14]` the active fit is sqrt and `applied.lag` 47.25456790896485 for target 99; `lag_source = "direct"` gives lag 46; changing `method` to "combined" changes every `ref_lags` lag (id 10 → `device_lag_from_reference(..., "combined")`).
  - **`reconcile` (Review 3):** after `set_rows` with id 12 removed (it was ticked, was the batch pick, and one was the target), `selected_ref_ids` lacks 12, `target_id` is None when the target vanished, `batch_picked` lacks it; with the same id present nothing is dropped; no exception for an empty row list.
  - Filter keys: `ref_filter_temp = "780.5"` survives `set_rows` of the same rows; it is cleared when `ref_filter_material` changes.
  - Queue (fake loader): three updates run in order and `on_done` gets `done 3, failures []`; failure at op 1 with `("server", "boom")` gives `done 2, failures ["#11: boom"]`; **login failure (Review 1)** at op 1 of 4 gives `done 1, aborted` set, and ops 2–3 never reached the loader; **busy (Review 2)**: `run` while running returns False and logs nothing; a hung op times out (watchdog shortened by a module constant patched to 50 ms) and the queue is free again; `with_graphs([1, 2])` with the fake giving `{1: "G"}` returns `{1: "G", 2: None}`; preset ops hit `store.insert_preset(row)` and `store.delete_preset(id)` and then `refresh()`, never `apply_*`.
- [ ] **Step 2: See FAIL. Step 3: Implement.** Decision: the queue never touches the network itself; `busy` is true from `run` until `on_done` returns. **Step 4: PASS. Step 5: Commit.**

### Task 5: Presets section

**Files:**
- Create: `ctwa/ui/calibration/presets_section.py`, `ctwa/ui/calibration/common.py` (`StepCard(title)` with `set_status(text, done)`, `MessageBar`, `link_button(text)`), `tests/test_calibration_presets.py`

**Interfaces:**
- `PresetsSection(state, queue, on_message)`, where `on_message(text, kind)` is the tab's `show_message`.
- Layout (a plain widget; the tab puts it, `MarkSection` and `ReferenceTable` into one `StepCard` titled `referencesHeading` "1. Reference runs" with status "`n` references"): note line `presetsNote`; chips "Material @ T °C → α mm²/s" (`js_number_to_string` for T and α; tooltip = note) with an × button; empty text `noPresets`; load error text `presetsLoadFailed: …`; add form: material (QLineEdit with QCompleter over `all_materials`), temperature °C, α mm²/s, note (placeholder `presetNotePlaceholder`), "Literature" combo (`LIT_MATERIALS`; choosing fills α with `LITERATURE[name]` and the material when it is empty), button "+ Save preset". Clicking a chip calls `state.apply_preset(p)`: sets the mark α field value (a `state.mark_alpha: str` attribute added in `state.py`, emits `changed`), `mark_filter_material = p.material_name`, `mark_filter_temp = ""`.
- Validation (messages `errPresetMaterial`, `errPresetTemp`, `errAlphaRequired`): material non-blank after trim, temperature finite, α > 0. Insert row: `{material_name: trimmed, temperature_c, alpha_mm2s, note: trimmed or None}`.

- [ ] **Step 1: Failing tests** (offscreen, `FakeLoader`):
  - Presets `[{id: 1, material_name: "Stainless Steel", temperature_c: 800, alpha_mm2s: 5.829, note: None}]` show the chip text "Stainless Steel @ 800 °C → 5.829 mm²/s"; clicking it calls `state.apply_preset` and sets `state.mark_alpha == "5.829"`, `mark_filter_material == "Stainless Steel"`.
  - Saving with material "  Al₂O₃ ", 150, 8, note "" queues exactly one `preset_insert` with `{"material_name": "Al₂O₃", "temperature_c": 150.0, "alpha_mm2s": 8.0, "note": None}`; the form clears after success; blank material, temperature "abc", α 0 and α -1 queue nothing and show the matching message.
  - Choosing "Stainless Steel" in the Literature combo fills α "4"; it fills the material only when empty.
  - × queues one `preset_delete` with that id; buttons disabled while `queue.busy`.
- [ ] **Step 2: See FAIL, implement, PASS, commit.**

### Task 6: Mark references and reference table

**Files:**
- Create: `ctwa/ui/calibration/mark_section.py`, `ctwa/ui/calibration/reference_table.py`, `tests/test_calibration_mark.py`

**Interfaces:**
- `MarkSection(state, queue, on_message)`: filters (material from `all_materials(non_refs)`, temperature from `temps_for`, both with "All"), α field (bound to `state.mark_alpha`, step 0.001), a checkable list of candidates (`label_of`), "Select all shown" (adds all candidates), "Clear selection", button "Mark as reference (n)", progress label "i / n", the two warnings (`mixedMaterialsWarn — A, B`; `markTempSpreadWarn — spread 31.5 °C` with `num(x, 1)`), empty text `noCandidates`. `state.mark_ids` is a new list attribute (pruned in `set_rows`).
- `ReferenceTable(state, queue, on_message)`: columns Run (`#id model`), Temperature, Period, Known α (editable), Measured Δt (`num(raw_lag_dt)`), Δt from known α (`num(true_lag)`), Device lag (`num(lag)`), and an "Unmark" button; empty text `noReferences`.
- Writes: mark = one `WriteOp("update", id, {"is_reference": True, "reference_alpha_mm2s": alpha})` per ticked row, then `mark_report`, clear the ticks. Unmark = `{"is_reference": False, "reference_alpha_mm2s": None}` and the id leaves `selected_ref_ids`. Edit α = `{"reference_alpha_mm2s": alpha}` committed on `editingFinished`; the cell shows a small status ("saving…", "saved" for 2.5 s, "failed").

- [ ] **Step 1: Failing tests.**
  - Material filter "Stainless Steel" and temperature key "780.5" list only matching candidates; `temperature_c` 800.0 rows appear under key "800" (Review 4); after `state.set_rows(same rows with 800 as int)` the choice is kept.
  - Ticking three runs with α "5.829" and pressing Mark queues three updates with exactly `{"is_reference": True, "reference_alpha_mm2s": 5.829}`; a failure on the second reports `Marked as reference: 2/3 · #<id>: boom` and the third is still sent; α "0" and "" queue nothing and show `errAlphaRequired`; the button shows "(3)" and is disabled at 0 ticks or while busy.
  - Warnings: ticking an Al and a Stainless Steel row shows both names; rows at 800 and 831 °C show "31.0 °C"; rows at 800 and 830 show none.
  - **Alpha cell (Review 5):** editing a reference's α from 5.829 to 4 queues `{"reference_alpha_mm2s": 4.0}` only; leaving the cell with 5.829 unchanged, with "0", "-2", "abc", or empty queues nothing and restores the old text; two quick `editingFinished` calls queue one update.
  - Unmark queues `{"is_reference": False, "reference_alpha_mm2s": None}`; after the refresh the id is gone from `selected_ref_ids`. A reference without α shows "—" in the three lag columns.
- [ ] **Step 2: See FAIL, implement, PASS, commit.**

### Task 7: Fit chart

**Files:**
- Create: `ctwa/ui/calibration/fit_chart.py`, `tests/test_calibration_chart.py`

**Interfaces:**
- `FitChart(QWidget)` (`pyqtgraph.PlotWidget`, 340 px high, `theme.style_plot`): `set_data(fit: Optional[LagFit], sel: List[RefLag], target: Optional[dict]) -> None` (hides itself when `fit` is None or `sel` is empty); `scatter_items`, `curve_item`, `region_item`, `target_line`, `star_item` for tests.
- Look (as the webapp): title `fitChartTitle`; x "Period (s)" on a log axis (`setLogMode(x=True)`); y "Device lag (s)"; one marker trace per material, `material_color(name)`, size 9, name = material; curve `pen("#7f8c8d", 2, dashed=True)` over `curve_points(fit)`; fit range as a non-movable `LinearRegionItem` `rgba(31,91,176,0.07)`; target as an `InfiniteLine` (angle 90, `#E4572E`, dash-dot, 1.5) and a star (`symbol "star"`, size 15, white outline) at `(target.period_t, fit.predict(target.period_t))` named `#id` (skipped when not finite); horizontal-below legend via `theme.legend`; hover text "%d s → %.1f s".
- Decision: with `setLogMode(x=True)` pyqtgraph converts plot data itself, but not `InfiniteLine`/`LinearRegionItem`, so those two get `log10(x)` positions.

- [ ] **Step 1: Failing tests** (Task 2 fixtures, five references, target 400, sqrt fit): two materials give two scatter items with the colours of `material_color`; each point `(period, device lag)` equals the selection's; the curve has 120 points, first x 75, last x ≈ 1200; `region_item.getRegion()` = `(log10(75), log10(1200))` and is not movable; `target_line.value()` = `log10(400)`; the star is at `(400, 47.25456790896485)` (`approx`) with size 15; a target outside the fit range still draws; `set_data(None, [], None)` hides the widget; a non-finite prediction draws no star and no error.
- [ ] **Step 2: See FAIL, implement, PASS, commit.**

### Task 8: Calibrate one run (target, reference picker, lag source, models, result, save)

**Files:**
- Create: `ctwa/ui/calibration/target_section.py`, `tests/test_calibration_target.py`

**Interfaces:**
- `TargetSection(state, queue, on_message)` with a card status as the webapp (curve: "`<model name>` · RMS `x` s", direct: "Direct", otherwise "no lag yet"). Contents, top to bottom:
  - target combo (searchable `QComboBox`, editable with completer, items `label_of(a)` of non-references, first item `chooseTarget`), and the line "Measured Δt: `num(raw_lag_dt)` s";
  - reference picker (hidden with `noReferences` when there are no references): filters (material, temperature), sort combo (Period / Closest period to target / Closest temperature to target; the last two disabled without a target), "Near target only, ±" checkbox + percent field (default off, 50), "Select all shown" (only rows with a lag) and "Clear selection", counter "`shown` / `all` shown · `n` reference(s)", note `nearTargetHint` when near-only is on, `noRefsMatch`, a checkable list (each row: label, "Δt from known α", "Device lag = x s", ΔT and ΔP versus the target; the box is disabled when the lag is None);
  - `tempSpreadWarn — spread x °C` when `temp_spread > 30`;
  - lag source radios (Curve fit disabled without fits; Direct), the hint text, and `directSingle` / `directMean N · Period ≈ x s`;
  - model table of fits (radio, Model `model_<kind>`, Formula = `fit.label`, RMS s `num(rms)`, R² `num(r2, 3)`, n), "Fitted range: a–b s" and "auto-selected: lowest RMS" while `model_kind` is None; `tooFewPoints` when there is no fit;
  - the `FitChart`;
  - result panel: "Applied device lag: x s (n reference(s)[, Direct])", warnings `outOfRangeWarn — P = … s, Fitted range a–b s`, `alreadyCalibrated (#ids) — saveMakesAnother`, `periodMismatchWarn — Target P = … s, reference(s) ≈ … s`; four cards: Corrected Δt `num(net_lag_dt)` s, net φ `num(net_phase_phi, 3)` rad, α phase (cal, "primary") with raw underneath, α combined (cal, "cross-check") with raw underneath, all through `format_alpha`; when `calibrated` is None the red `notCalibratable` text replaces the cards and the Save button is disabled;
  - button "Save as calibrated analysis".
- Save: `queue.with_graphs([target.id], cb)`, then one `WriteOp("insert", None, build_calibrated_row(target, applied.lag, calibrated, graph, [x.ref.id for x in state.selected], calibration_model_string(...)), f"#{target.id}")`; success message `saved`; failure `saveFailed: …`.

- [ ] **Step 1: Failing tests** (state with the Task 2 fixtures; `FakeLoader` graphs `{99: "G"}`):
  - Picking target 99 and ticking five references shows the sqrt model first, the "auto-selected" text, `applied lag` "47.25 s", Corrected Δt "102.75", chart visible; picking the linear row (`model_kind = "linear"`) changes the applied lag to `num(42.551971326164875)` = "42.55" and removes the auto text.
  - The picker with sort "Closest period to target" lists ids [12, 13, 11, 10, 14]; ticking is blocked for a reference whose lag is None; "Select all shown" ticks only those with a lag; the near-only field is disabled until the box is ticked.
  - Direct radio with the five references: "Mean device lag … 5", applied 46, no mismatch warning; target at 700 shows `periodMismatchWarn`. One reference ticked and no fit possible: Curve radio disabled, source falls back to direct, `tooFewPoints` shown.
  - Temperature spread 19.5 shows nothing; ticked references at 800 and 831 show `tempSpreadWarn — spread 31.0 °C`.
  - Target period 74 with the curve shows `outOfRangeWarn`; target with an existing copy shows `alreadyCalibrated (#77)`.
  - Save: one insert op, `data` equals `build_calibrated_row(...)` for the sqrt fit, `graph_image` "G", `calibration_ref_ids` "10,11,12,13,14"; a graph fetch that returns nothing saves `graph_image` None and still inserts. **Double click (Review 2):** clicking Save twice quickly logs one insert. Target with raw lag 40 and applied lag 46: red text, Save disabled, no op even if `click()` is forced (Review 5).
- [ ] **Step 2: See FAIL, implement, PASS, commit.**

### Task 9: Batch section

**Files:**
- Create: `ctwa/ui/calibration/batch_section.py`, `tests/test_calibration_batch_ui.py`

**Interfaces:**
- `BatchSection(state, queue, on_message, confirm)` where `confirm(title, message, button_label) -> bool` (production: `QMessageBox.question`; tests inject a stub).
- Contents (status "`ok` / `rows` ready to save"): note `batchNote`; if there is no lag (curve source without fit, or direct without lag) only `batchNeedsFit`; otherwise material combo (all materials, "None" first) and temperature combo ("All" + `temps_for`), shortcut links ("Select all shown" → default, "Include already-calibrated" only when some calibratable row has copies, "Clear selection", "Only those in range"), the counter "`n` / `m` selected to save", the preview table (checkbox disabled without a result; Run `#id model`, Period `num(.,0)`, α raw `format_alpha`, Applied lag, Corrected Δt, α cal bold, status "✓ ok" / "⚠️ outside fitted range" / "✕ not calibratable", plus "⚠️ already calibrated (#ids)"; rows not picked or not calibratable are dimmed), button "Save all calibrated (n)", progress "i / n".
- Save: `confirm(confirmBatchTitle with n and material, confirmBatchMessage, "Save all calibrated (n)")`; on Yes `queue.with_graphs(ids, …)` once, then one insert per picked row in table order via `queue.run`, then `batch_report(written, n_ok, n_rows, n_calibratable, had_copies, failures)` shown for 12 s. `had_copies` = rows with copies that were not saved.

- [ ] **Step 1: Failing tests** (state: material "Stainless Steel", direct source lag 46, targets as Task 3 t1–t5 given `model_name`):
  - Defaults: checked ids [1, 2]; t5 unchecked and shows "already calibrated (#77)"; t3 and t4 show "not calibratable" with disabled boxes; shortcuts give [1, 2, 5], [], [1, 5], and "Select all shown" returns to the default; changing the material or temperature resets the pick.
  - Save all with `confirm` stub returning False writes nothing; returning True with 2 picked rows runs one `with_graphs` call, two inserts in table order, each `data == build_calibrated_row(...)`, and the message `Saved 2/2 · 3 skipped (not calibratable) · 2 not calibratable · 1 already calibrated`.
  - Failure on the first insert (`("server", "boom")`) still writes the second and the message ends `· #1: boom`; a login failure on the second of three aborts and the message says how many were written (`Saved 1/3`) and that login is required.
  - **Re-pick after a partial save (Review 1):** after the refresh that returns the first row's new copy (`calibrated_from_id` = 1), the default pick no longer contains id 1, so pressing Save again writes only the rest.
  - **Double click (Review 2):** a second press while running logs one batch. Zero picked rows disables the button. No fit and no direct lag shows only `batchNeedsFit`.
  - A copy row (`calibrated_from_id` set) and a reference never appear in the preview (Review 5).
- [ ] **Step 2: See FAIL, implement, PASS, commit.**

### Task 10: The tab (assembly, messages, load states)

**Files:**
- Create: `ctwa/ui/calibration/calibration_tab.py`, `tests/test_calibration_tab.py`

**Interfaces:**
- `CalibrationTab(loader, parent=None)`: methods `refresh()`, `on_shown()` (first call triggers `loader.refresh()`), `show_message(text, kind="info", ms=5000)` (`MessageBar`: info 12 000 ms for multi-row reports, errors stay until the next action), property `state`.
- Layout: title row with the lag-method segmented control (`methodPhase` "Phase (α phase)" / `methodCombined` "Combined (α comb)", hint `methodHint`, tooltip `lagMethod`) and a Refresh button; message bar; one `QScrollArea` with `PresetsSection`, `MarkSection`, `ReferenceTable` (all three in the one card "1. Reference runs"), `TargetSection` (card "2. Calibrate a run"), `BatchSection` (card "3. Batch calibration"); the page note `note` as a caption under the title.
- Wiring: `loader.rows_changed → state.set_rows`, `loader.presets_changed → state.set_presets`. A `failed(kind, message)` while `queue.busy` belongs to the queue; otherwise it shows in the message bar: kind "login" → "Not logged in. Use Settings → Webapp login…", others `message`. Until the first `rows_changed` the page shows `loading` and no sections.

- [ ] **Step 1: Failing tests** (full tab on `FakeLoader` with the Task 4 rows):
  - Before data: "Loading..." only; after `rows_changed` all five cards exist and the reference status reads "5 references"; `on_shown()` twice calls `refresh()` once.
  - `failed("login", …)` outside a write shows the login text in the message bar; during a write it does not (the queue reports it).
  - End to end with the fake: tick five references, pick target 99, Save → exactly one `apply_insert` call; then the fake emits `rows_changed` with the new copy and the target's status shows `alreadyCalibrated (#<new id>)`.
  - Mark flow: tick two runs, α 4, Mark → two `apply_update` calls with `{"is_reference": True, "reference_alpha_mm2s": 4.0}`, after the refresh both appear in the reference table and no longer in the candidate list.
  - Toggling the method to "combined" recomputes the reference table's device-lag column (id 10 shows `num(device_lag_from_reference(row, 5.829, "combined"))`).
  - The tab never calls the loader from the GUI thread in a blocking way: with a fake loader whose methods return immediately, a `QTimer` ticking every 20 ms during a 30-row batch save never misses more than 2 ticks.
- [ ] **Step 2: See FAIL, implement, PASS, commit.**

### Task 11: Wiring, packaging, full suite, screenshot

**Files:**
- Modify: `ctwa/app.py` (one block), `keithley_suite.spec` (`hiddenimports`)
- Create: `tests/test_calibration_wiring.py`

- [ ] **Step 1: Failing test.** A simulated-2602B `MainWindow` (pattern of `tests/test_main_window_tabs.py`) has a tab titled "Calibration" right after "Analysis" (this plan inserts directly after the Analysis tab; the order among Plans 3–5 is settled when they are merged), the widget is a `CalibrationTab`, switching to it calls `on_shown()` once, and a `MainWindow` built with the tab still passes `tests/test_equivalence_with_original_windows.py`.
- [ ] **Step 2: Implement** exactly one block in `MainWindow.__init__`, directly after the line that adds the Analysis tab:

  ```
  # --- Calibration tab (Plan 4) ---
  # (imports, CalibrationTab(self.results_loader), tabs.addTab(..., "Calibration"),
  #  tabs.currentChanged hook calling on_shown when the tab is current)
  # --- end Calibration tab (Plan 4) ---
  ```
  The shared loader's attribute name is whatever the Foundation wiring used (`grep "ResultsLoader(" ctwa/app.py`), expected `self.results_loader`. Add `ctwa.analysis.calibration`, `.calibration_logic`, `.calibration_batch`, `ctwa.ui.calibration` and its modules (`calibration_tab`, `state`, `writes`, `texts`, `common`, `presets_section`, `mark_section`, `reference_table`, `target_section`, `fit_chart`, `batch_section`) to `hiddenimports`, in alphabetical position next to the existing entries.
- [ ] **Step 3: Full suite.** `QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m pytest -q` is all green; report the counts. `tests/test_equivalence_with_original_windows.py` and `tests/test_analysis_matches_webapp.py` are named in the report as passing.
- [ ] **Step 4: Screenshot.** Offscreen, `FakeLoader` seeded with the Task 4 rows (five Stainless Steel references, six targets, one copy, two presets), five references ticked, target 99, batch material "Stainless Steel": `tab.resize(1280, 1900); tab.grab().save(...)` to `/private/tmp/claude-501/-Users-omervered/35e79076-53f0-40ac-a750-a4dd8ddf2241/scratchpad/calibration_tab.png`. Look at it; fix anything cut off or unreadable (fit chart with star, model table, result cards, batch preview).
- [ ] **Step 5: Commit.** The branch `plan4-calibration` is left for Omer to merge; no push.
