# Analysis Port (Plan 1 of the CTWA 2.0 build) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a Python copy of the webapp's analysis maths in `ctwa/analysis/`, proven by a test to give the webapp's numbers on real runs, for every mode.

**Architecture:**
- **The reference:** the webapp's one-file analysis flow moves out of `app/analysis/page.tsx` into a pure `lib/pipeline.ts`, so the page and a golden generator call the same code.
- **Golden numbers:** the generator runs that code on real runs and writes JSON.
- **The Python port:** a literal copy of each TS module. A pytest compares it to the JSON.
- **No UI in this plan.** The tabs come in later plans.

**Tech Stack:**
- Webapp: TypeScript, `tsx` (dev dependency, to run the generator).
- CTWA: Python 3, numpy only (no scipy), pytest.

**Spec:** `docs/superpowers/specs/2026-11-24-ctwa-desktop-analysis-design.md`

## Global Constraints

- **Branches:**
  - CTWA work on branch `desktop-analysis`.
  - Webapp work on branch `golden` (from `main` after the save-lock merge, or from `save-lock` if that isn't merged yet).
  - **No commits to `master`/`main`, no pushes, no tags, no Supabase writes.**
- **Untouchable files:** `ctwa/instruments/`, the `keithley*_driver.py` files and `ctwa/app.py`. `tests/test_equivalence_with_original_windows.py` must stay green.
- **Literal port:**
  - Same algorithm, same branch order, same constants, same thresholds as the TS file.
  - numpy is fine for bulk arithmetic. Where a comparison picks something (argmax, peak picks, threshold crossings, sort order, tie breaks), compute the compared values in the TS order, or the golden test will expose it.
- **JS semantics to reproduce:**
  - `Math.round(x)` = `math.floor(x + 0.5)`, never Python `round`.
  - `toFixed`/`toPrecision` strings must match exactly where they reach output (e.g. `LagFit.label`).
  - `NaN` propagation in `Math.max/min` over arrays.
  - `Array.sort` comparators.
  - Integer vs float division.
- **Names:** Python names are the TS names in snake_case (`runAutoFitAnalysis` → `run_auto_fit_analysis`, `amplitudeA1` → `amplitude_a1`). TS interfaces become `@dataclass` classes with snake_case fields, and TS `null`/`undefined` become `None`.
- **Tolerance:** floats agree to `rel=1e-9, abs=1e-12`. `None`/`NaN` must match as `None`/`NaN`. Ints, bools and strings must match exactly.
- **Speed:** `run_one_file_pipeline` on the Al₂O₃ CTWA run (17,700 rows) in under 10 s on Omer's Mac, for every mode.
- **Run data used by tests:** gzipped copies in `tests/data/runs/`, at most 10 MB in total.

## Review Focus

1. **A selection region with fewer than 10 points** must raise `PipelineError('tooFewPoints')`, the same code the webapp shows, not an IndexError deep in a mode.
2. **A run whose source column is all heater-off** (the ~6e-12 W floor, i.e. no oscillation) must raise a clear error or return the same `None`/NaN fields as the TS. It must not hang in a period search.
3. **A CSV saved in cp1252 with `°` and `µ`** (as CTWA writes it) must parse identically to the UTF-8 version.
4. **The ln term ≤ 0** (A₁/A₂ below √(r₂/r₁)) must give `alpha_combined_* = None` while the `alpha_phase_*` values are still computed, exactly as the TS does.
5. **A lag near 0 or a full period** must give the same `lag_cycles` and `lag_near_edge` as the TS, since the cycle choice is a discrete decision.

---

### Task 1 (webapp): Pull the one-file flow out of the page into `lib/pipeline.ts`

**Files:**
- Create: `lib/pipeline.ts`, `tests/pipeline.test.ts`
- Modify: `app/analysis/page.tsx` (load block ~L357–393, analysis block ~L676–757)

**Interfaces:**
- Produces:

```ts
export type PipelineErrorCode = 'tooFewPoints' | 'smoothFailed' | 'parseFailed' | 'notEnoughOverlap'
export class PipelineError extends Error { constructor(public code: PipelineErrorCode) }
export interface PipelineOptions {
  waveType: 'sine' | 'square'
  smoothToSine: boolean
  selMin: number; selMax: number
  squarePeriod?: number                    // square only; > 0 to override detection
  clicks?: [number, number][]              // Manual only: [peak1, peak2, resp, resp2] as the page builds them
  params: AnalysisParams
}
/** parse + build SyncedData exactly as the page's one-file load does (throws parseFailed / notEnoughOverlap). */
export function loadOneFile(buf: ArrayBuffer): { synced: SyncedData; parsed: CombinedParsed }
/** The page's default region and manual markers for a run (0.3/0.7 and 0.35/0.5/0.45/0.55 of the span, Math.round). */
export function defaultSelection(synced: SyncedData): { selMin: number; selMax: number; clicks: [number, number][] }
/** Filter to [selMin, selMax], optional smoothToSharedSine, dispatch on waveType/analysisMode — what runAnalysis does today. */
export function runOneFilePipeline(synced: SyncedData, opts: PipelineOptions): AnalysisResults
```

- [ ] **Step 1: Write the failing test.** `tests/pipeline.test.ts` loads `tests/fixtures/al2o3_ctwa.csv`, a copy of `~/Downloads/new_proble_Al2O3_test_short_50-100_15mw_17112026_2026-11-17_09-10-19.csv`.
  - `loadOneFile(buf).synced.tSrc.length === 17700`.
  - For each mode in `['Auto','AutoHybrid','AutoFFT','AutoFit','Manual']`, with `defaultSelection` and `smoothToSine:false`, the pipeline returns finite `alphaPhaseRaw`.
  - A region of 5 points throws `PipelineError` with `code === 'tooFewPoints'`.
- [ ] **Step 2: Run the test and see it fail.** `npm test -- pipeline`. Expected: FAIL, the module is missing.
- [ ] **Step 3: Implement and switch the page over.**
  - Move the code as it is.
  - The page calls `loadOneFile`/`defaultSelection`/`runOneFilePipeline` and maps `PipelineError.code` to its existing `t('analysis.err…')` keys.
  - The two-file path is unchanged.
- [ ] **Step 4: Run the tests, type check and build.** `npm test && npx tsc --noEmit && npm run build`. Expected: all pass.
- [ ] **Step 5: Hand check (no saving).** In `npm run dev`, analyze the Al₂O₃ file in Manual and AutoFit with the default region. α must be the same as on the live site with the same settings. Don't press Save. Block `/api/db` if this is browser-automated.
- [ ] **Step 6: Commit.** `git commit -am "Move the one-file analysis flow into lib/pipeline.ts"`

### Task 2 (webapp): Golden generator

**Files:**
- Create: `ops/golden/generate.ts`, `ops/golden/README.md`
- Modify: `package.json` (devDependency `tsx`, script `"golden": "tsx ops/golden/generate.ts"`)

**Interfaces:**
- Consumes (Task 1): `loadOneFile`, `defaultSelection`, `runOneFilePipeline`, plus `fitLagModels`, `serializeFit`, `describeLagModel` and `parseCombinedFile`.
- Produces, in `ops/golden/out/`:
  - one `<case_id>.json` per case: `{ "case_id", "input_file", "options": PipelineOptions, "results": AnalysisResults | null, "error": PipelineErrorCode | null }`;
  - `parser_<file>.json`: `{ n, first3, last3, sums }` for time/source/response/temperature, with NaN as `null` and sums skipping NaN;
  - `lagfit.json`: an array of `{kind, params, label, rms, r2, n, pMin, pMax, serialized, described, predict_at: {75:…,150:…,300:…,600:…}}`.

- [ ] **Step 1: Write the generator.** `npm run golden -- <dir-with-inputs> <out-dir>` builds these cases:
  - **Inputs:**
    - `al2o3_ctwa.csv` (the CTWA capture);
    - `al2o3_c80.csv` (its `_1.csv` C80 export);
    - `fiber_150_600.csv` and `fiber_75_105.csv` (from `msc results/results why no work/`, `…28082026…` and `…multi_75-90-105…`);
    - any steel one-file `*aio*` capture found under `msc results/`, if there is one.
  - **Cases per input:**
    - each of the 5 sine modes with `smoothToSine:false`, `r1Mm:6.72, r2Mm:14.86, useCalibration:false, systemLag:0, cycleShift:0, manualSnap:false`;
    - Manual and AutoFit again with `smoothToSine:true`;
    - AutoFit with `useCalibration:true, systemLag:120`;
    - AutoFit with `cycleShift:1`;
    - one square-mode case on `al2o3_ctwa.csv`, recorded even if it yields an error code;
    - one `tooFewPoints` case (`selMax = selMin + 3` s).
  - **Lag points** for `lagfit.json`: periods `[75, 90, 105, 150, 300, 600]`, with lags from `-4.920 + 5.8658·√P`, plus a deterministic alternating ±1.5 s offset.
  - **Other params:** `modelName:'golden'`, testDate/testTime empty, units `'Seconds'`/`'mW'`, `tCal`/`tSrc` `'00:00:00'`.
- [ ] **Step 2: Run it twice and check it's stable.** `npm run golden -- <inputs> /tmp/g1 && npm run golden -- <inputs> /tmp/g2 && diff -r /tmp/g1 /tmp/g2`. Expected: no differences, so the output is deterministic.
- [ ] **Step 3: Write the README.** `ops/golden/README.md` says: the webapp maths is the reference. After any change to `lib/` maths, regenerate and copy `out/` into the CTWA repo `tests/golden/analysis/`, and the CTWA app may not be released until its test passes.
- [ ] **Step 4: Commit.** `git add ops/golden package.json package-lock.json && git commit -m "Golden generator: webapp analysis numbers on real runs for the CTWA port"`

### Task 3 (CTWA): The check test (red)

**Files:**
- Create: `tests/data/runs/*.csv.gz` (the inputs above, gzipped), `tests/golden/analysis/*.json` (Task 2 output), `tests/test_analysis_matches_webapp.py`

**Interfaces:**
- Consumes:
  - `ctwa.analysis.pipeline.load_one_file(data: bytes) -> tuple[SyncedData, CombinedParsed]`
  - `run_one_file_pipeline(synced: SyncedData, opts: PipelineOptions) -> AnalysisResults`
  - `PipelineError(code: str)` (defined in `ctwa.analysis.types`, re-exported by `pipeline`)
  - `ctwa.analysis.lag_fit.fit_lag_models(points: list[LagPoint]) -> list[LagFit]`, `serialize_fit`, `describe_lag_model`

- [ ] **Step 1: Write the test.** It is parametrized over every `tests/golden/analysis/*.json`:
  - Case files: build `PipelineOptions` from `options` (camelCase → snake_case through one mapping helper in the test). Assert either `PipelineError.code == error`, or every field of `results` matches by the Global Constraints tolerance.
  - Parser files: compare n/first3/last3/sums.
  - `lagfit.json`: compare every field, and `fit.predict(P)` at the four periods.
  - On mismatch, the message lists the case id, the field, both values and the relative difference.
- [ ] **Step 2: Add a speed test.** `test_pipeline_speed`: every mode on `al2o3_ctwa` finishes in under 10 s each, marked `@pytest.mark.slow`.
- [ ] **Step 3: Run it and see it fail.** `pytest tests/test_analysis_matches_webapp.py -q`. Expected: collection error, `ctwa.analysis` doesn't exist yet.
- [ ] **Step 4: Commit** on `desktop-analysis`: `git add tests/data/runs tests/golden tests/test_analysis_matches_webapp.py && git commit -m "Check test: Python analysis must match the webapp's numbers"`

### Task 4 (CTWA): Types and parser

**Files:**
- Create: `ctwa/analysis/__init__.py`, `ctwa/analysis/types.py`, `ctwa/analysis/parser.py`
- Test: the parser cases of `tests/test_analysis_matches_webapp.py`, plus `tests/test_analysis_parser.py` for Review Focus 3

**Interfaces:**
- Produces (`types.py`): dataclasses `AnalysisParams`, `AnalysisResults`, `SyncedData`, `CombinedParsed`, `SineFit`, `SineLag`, `LagChoice`, `LagPoint`, `LagFit` (`predict` is a callable field), and `PipelineOptions`. Fields are those of the TS interfaces in `lib/analysis.ts`, `lib/fileParser.ts`, `lib/sineFit.ts` and `lib/lagFit.ts`, in snake_case. `PipelineOptions` and `PipelineError` live in `types.py` so every module can import them.
- Produces (`parser.py`), from `lib/fileParser.ts`:
  - `decode_bytes(data: bytes) -> str` (strict UTF-8, else cp1252);
  - `is_combined_file(data: bytes) -> bool`;
  - `parse_combined_file(data: bytes) -> CombinedParsed | None`;
  - `extract_start_date(data: bytes) -> str | None`;
  - `extract_date_from_filename(name: str) -> str | None`;
  - `extract_temperature_from_filename(name: str) -> float | None`.
  - Not ported: the two-file paths (`parseFile`, `detectFileType`, `extractStartTime`, `extractPowerUnit`).

- [ ] **Step 1: Write the failing encoding test.** In `tests/test_analysis_parser.py`, encode a 5-row CTWA-style CSV with `°C` and `µW` headers once as UTF-8 and once as cp1252. `parse_combined_file` must give equal `CombinedParsed` for both, with source scaled µW→mW by 1e-3.
- [ ] **Step 2: Run the tests and see them fail.** `pytest tests/test_analysis_parser.py tests/test_analysis_matches_webapp.py -k parser -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `types.py` and `parser.py` as literal ports.
- [ ] **Step 4: Run the tests and see them pass.** Same command. Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -am "ctwa.analysis: types and one-file parser (port of lib/fileParser.ts)"`

### Task 5 (CTWA): Peaks and sine fitting

**Files:**
- Create: `ctwa/analysis/peaks.py` (← `lib/peakDetection.ts`), `ctwa/analysis/sine_fit.py` (← `lib/sineFit.ts`)
- Test: `tests/test_analysis_units.py`

**Interfaces:**
- Produces:
  - `peaks.py`:
    - `find_peaks(values, distance) -> list[int]`
    - `auto_detect_peaks(time, values, min_distance_fraction=0.05) -> tuple[list[int], list[float]]`
    - `find_troughs(values, distance) -> list[int]`
    - `compute_cycle_amplitude(values, peak_indices) -> float`
    - `snap_to_peak(click_time, time, values, window_samples=50) -> tuple[float, float, int]`
  - `sine_fit.py`:
    - `baseline_degree(cycles) -> int`
    - `fit_sine(time, value, omega, degree=2) -> SineFit | None`
    - `remove_period_mean(time, value, period) -> tuple[list, list]`
    - `refine_period(time, value, period) -> float`
    - `lag_into_period(lag, period) -> float`
    - `choose_lag_cycle(lag, period, shift=0) -> LagChoice`
    - `sine_lag(t_src, v_src, t_cal, v_cal, period) -> SineLag | None`
    - `refine_peak(time, value, around, period) -> tuple[float, float] | None`

- [ ] **Step 1: Write the failing unit tests**, on synthetic data with known answers:
  - `fit_sine` on `3 + 2·cos(ωt − 0.7)` (t = 0..1000 s step 1, ω = 2π/200) recovers amplitude 2 and phase 0.7 to 1e-9.
  - `sine_lag` of a copy delayed by 37 s gives `lag == pytest.approx(37, abs=1e-6)`.
  - `choose_lag_cycle(0.01*T, T)` gives `lag_near_edge` behaviour equal to the TS rule (below 2 % or above 90 % of T).
  - `lag_into_period(-5, 100) == 95`.
  - `find_peaks([0,1,0,2,0,1,0], 1) == [1,3,5]`.
- [ ] **Step 2: Run the tests and see them fail.** `pytest tests/test_analysis_units.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** both modules as literal ports. The least-squares solve in `fit_sine` must follow the TS method (port its normal-equation or elimination code), not `numpy.linalg.lstsq`, unless the golden test still passes at 1e-9.
- [ ] **Step 4: Run the tests and see them pass.** Same command. Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -am "ctwa.analysis: peak detection and sine fitting"`

### Task 6 (CTWA): Diffusivity, Auto, Manual and square modes

**Files:**
- Create:
  - `ctwa/analysis/diffusivity.py`: from `lib/analysis.ts`, `calculate_thermal_diffusivity`, `sync_and_filter_data`, `theoretical_phase`, `theoretical_lag_dt`, unit factors;
  - `ctwa/analysis/modes.py`: `run_auto_analysis`, `run_manual_analysis`;
  - `ctwa/analysis/square.py`: from `lib/squareAnalysis.ts`, `detect_square_period`, `extract_fourier_fundamental`, `filter_to_range`, `run_square_analysis`.
- Test: `tests/test_analysis_units.py` (additions)

**Interfaces:**
- Consumes (Tasks 4–5): types, `peaks`, `sine_fit`.
- Produces: `run_auto_analysis(t_cal, v_cal, t_src, v_src, params, t_min, t_max) -> AnalysisResults`, and the same signature plus `clicks: list[tuple[float, float]]` for `run_manual_analysis`. `run_square_analysis(..., period_override: float | None = None)`.

- [ ] **Step 1: Write the failing unit tests.**
  - `calculate_thermal_diffusivity` with `a1=10, a2=5, T=300, dt=40, r1=6.72, r2=14.86, use_calibration=False`: `alpha_phase_raw == (ω/2)·(Δr/φ)²` in m²/s, with Δr = 8.14e-3 m, ω = 2π/300 and φ = ω·40.
  - Review Focus 4: `a1=10, a2=9` gives `ln_term ≤ 0`, so `alpha_combined_raw is None` while `alpha_phase_raw` stays finite.
- [ ] **Step 2: Run the tests and see them fail.** `pytest tests/test_analysis_units.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** all three modules as literal ports.
- [ ] **Step 4: Run the tests and see them pass.** Same command. Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -am "ctwa.analysis: diffusivity, Auto, Manual and square-wave analysis"`

### Task 7 (CTWA): Smoothing, Hybrid, FFT, Fit and the pipeline. The check test goes green.

**Files:**
- Create:
  - `ctwa/analysis/smoothing.py`: `estimate_fundamental_period`, `reconstruct_sine_at`, `smooth_to_shared_sine`, `detect_segments`, `smooth_piecewise`;
  - `ctwa/analysis/pipeline.py`: `load_one_file`, `default_selection`, `run_one_file_pipeline`.
- Modify: `ctwa/analysis/modes.py` (add `run_auto_hybrid_analysis`, `run_auto_fft_analysis`, `run_auto_fit_analysis`)

**Interfaces:**
- Produces: the pipeline signatures listed in Task 3, mirroring Task 1's TS exactly, including `PipelineError` codes.

- [ ] **Step 1: Write the failing tests.** Review Focus 2: a synthetic run with the source flat at 6e-12 mW and a noisy response gives, through `run_one_file_pipeline` in AutoFit and AutoFFT, either a `PipelineError` or the same `None`/NaN fields as the TS on the same input. Add that input as a golden case in Task 2's generator, regenerate, and copy it over. The test also has to finish within 10 s.
- [ ] **Step 2: Run the tests and see them fail.** `pytest tests/test_analysis_matches_webapp.py -q`. Expected: FAIL on the mode cases.
- [ ] **Step 3: Implement** the modules as literal ports.
- [ ] **Step 4: Run the check test.** `pytest tests/test_analysis_matches_webapp.py -q -m "not slow"`, then `pytest -m slow`. Expected: every case passes.
- [ ] **Step 5: Commit.** `git commit -am "ctwa.analysis: Hybrid, FFT, Fit modes and the one-file pipeline; matches the webapp"`

### Task 8 (CTWA): Lag-model fitting

Independent of Tasks 5–7, so it can run in parallel with them.

**Files:**
- Create: `ctwa/analysis/lag_fit.py` (← `lib/lagFit.ts`), `ctwa/analysis/references.py` (← `lib/referenceMaterials.ts`, `lib/materialColors.ts`)

**Interfaces:**
- Produces:
  - `fit_lag_models(points: list[LagPoint]) -> list[LagFit]`
  - `serialize_fit(fit) -> str`
  - `serialize_direct(lag_s: float) -> str`
  - `describe_lag_model(serialized: str | None) -> str`
  - `LITERATURE: dict[str, float]`
  - `material_color(name: str) -> str`

- [ ] **Step 1: Run and see it fail.** `pytest tests/test_analysis_matches_webapp.py -k lagfit -q`. Expected: FAIL.
- [ ] **Step 2: Implement** as a literal port. `label` and `serialize_fit` strings must match byte for byte, so reproduce JS `toFixed`/`toPrecision`/`toString` number formatting with one helper and use it everywhere.
- [ ] **Step 3: Run and see it pass.** Same command. Expected: PASS.
- [ ] **Step 4: Commit.** `git commit -am "ctwa.analysis: lag-model fitting and reference materials"`

### Task 9 (CTWA): Close-out

- [ ] **Step 1: Run the full suite.** `pytest -q`. Expected: everything passes, including `test_equivalence_with_original_windows.py`. The skip count stays as before (1).
- [ ] **Step 2: Add a README section,** "Analysis maths", stating the reference rule and how to regenerate the golden files (points at the webapp's `ops/golden/README.md`).
- [ ] **Step 3: Commit.** `git commit -am "README: the analysis maths follows the webapp; how to refresh the golden numbers"`
- [ ] **Step 4: Report to Omer** that Plan 1 is done, and write Plan 2 (cloud client and Runs + Analysis tabs).
