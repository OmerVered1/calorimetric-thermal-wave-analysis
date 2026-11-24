# Runs and Analysis Tabs (Plan 2 of the CTWA 2.0 build) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the CTWA app, open a recorded run, analyze it with the ported maths, and save the result to Supabase so the webapp shows it, with no file moving.

**Architecture:**
- **Saved rows:** the webapp's save logic (row + plot + duplicate check) moves out of `app/analysis/page.tsx` into `lib/analysisRow.ts`, and the golden generator records reference rows. `ctwa/analysis/row.py` ports it and is checked against those rows.
- **Cloud:** `ctwa/cloud/` talks to the webapp (`/api/auth`, `/api/db`) and reads Supabase with the public key. Saves made while offline are queued.
- **Analysis process:** the analysis runs in one long-lived subprocess, so the sweep thread in the GUI process never competes with it.
- **Tabs:** two new tabs, **Runs** and **Analysis**, come after Real Time.

**Tech Stack:** PySide6, pyqtgraph, numpy, `concurrent.futures.ProcessPoolExecutor` (spawn), `urllib.request`, `keyring` (new), and on the webapp side TypeScript with vitest.

**Spec:** `docs/superpowers/specs/2026-11-24-ctwa-desktop-analysis-design.md`. These choices from Omer (24 Nov) refine it:
- one-screen Analysis tab;
- an **Analyze** button (no live recalculation);
- the region is dragged by hand;
- pre-fill date/time, devices, temperature, and sample + gas;
- Runs list columns: name, date, length, saved analyses, sample + temperature;
- the auto-save folder plus folders he adds.

## Global Constraints

- **Branches:** CTWA work on branch `desktop-analysis`; webapp work on a new branch `save-row` from `main`. No commits to `master`/`main`, no pushes, no tags.
- **Database:** no real Supabase writes and no real network in tests. Tests use a local fake HTTP server or a fake client.
- **Instrument code:** `ctwa/instruments/` and the `keithley*_driver.py` files are untouched. `ctwa/app.py` only gains the two tabs, a settings entry, a status-bar indicator, and the "current run file" hook. `tests/test_equivalence_with_original_windows.py` stays green.
- **The analysis never runs in the GUI process.**
  - The GUI thread never blocks for more than about 50 ms on analysis or network work.
  - Analysis and cloud errors are shown in the tab and never propagate to the sweep.
- **Python 3.9** (`from __future__ import annotations`). Run tests with `/usr/bin/python3 -m pytest`. Qt tests run with `QT_QPA_PLATFORM=offscreen` and follow the existing QApplication pattern in `tests/`.
- **Webapp:** `https://omersthesis.vercel.app`. Supabase URL and anon key are the webapp's `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_KEY` from `.env.local` (public values, already shipped in the site's JavaScript). **Never copy `SUPABASE_SERVICE_KEY`.**
- **Formats from the live data:**
  - `test_date` `DD/MM/YYYY`, `test_time` `HH:MM`;
  - `power_source_device` like `Keithley 2602B`, `power_response_device` like `Drop Calorimeter` (C80 runs: `C80`);
  - `gas_atmosphere` `Ar` / `Air`;
  - non-finite numbers are saved as `null`.
- **Defaults:** the Analysis tab's defaults equal the webapp page's `useState` defaults (mode `AutoFit`, `useCalibration` true, system lag 105 s, the page's r1/r2, smoothing, wave type).
- **Commits:** messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Internet down when pressing Save:** the row goes to the queue, the status bar shows "1 waiting to upload", and the row survives an app restart and uploads on the next retry.
2. **Token refused (password changed):** a 401 opens the password dialog. The row stays queued, never lost and never sent twice.
3. **Opening the run currently being recorded:** it is listed as "recording" and cannot be analyzed until the run ends.
4. **An analysis error or a crash of the worker process:** the message shows in the results panel. A running sweep is unaffected, and the next Analyze works (the worker restarts).
5. **Open… on a file that is not a one-file capture:** a clear "This file isn't a CTWA/C80 one-file capture" message, and no crash or traceback dialog.

---

### Task 1 (webapp): Save logic into `lib/analysisRow.ts`, record the run's file name, golden rows

**Files:**
- Create: `lib/analysisRow.ts`, `tests/analysisRow.test.ts`
- Modify: `app/analysis/page.tsx` (save block ~L880–1000, the analysis-plot builder for step 3, the duplicate modal's match logic), `ops/golden/generate.ts`, `ops/golden/README.md`

**Interfaces:**
- Produces:

```ts
export interface RowMeta { modelName: string; testDate: string; testTime: string; temperature: number | null;
  gasAtmosphere: string; powerSourceDevice: string; powerResponseDevice: string; waveType: 'sine'|'square';
  analysisMode: AnalysisMode; r1: number; r2: number; useCalibration: boolean; systemLag: number;
  inputMode: 'one'|'two'; dayOffset?: number; clockAhead?: number; sourceFileName?: string | null }
export function buildAnalysisPlot(synced: SyncedData, results: AnalysisResults, opts: PipelineOptions): { data: unknown[]; layout: unknown }
export function buildAnalysisRow(results: AnalysisResults, meta: RowMeta, plot: { data: unknown[]; layout: unknown } | null): Record<string, unknown>
export function findDuplicate(candidates: Pick<Analysis,'id'|'model_name'|'analysis_mode'|'period_t'|'amplitude_a1'>[], row: Record<string, unknown>): Analysis | null
```

- [ ] **Step 1: Write the failing test.** `tests/analysisRow.test.ts`:
  - On the Al₂O₃ fixture with the AutoFit default selection, `buildAnalysisRow` returns exactly the keys the page saves today, with `graph_image` a JSON string of `{data, layout}` and `extra_data` holding `lag_se_s`/`lag_se_source`.
  - `findDuplicate` matches a candidate with the same model and mode and period/A₁ within the page's tolerances, and rejects one just outside them.
- [ ] **Step 2: Run the tests and see them fail.** `npm test -- analysisRow`. Expected: FAIL, the module is missing.
- [ ] **Step 3: Move the logic and record the file name.**
  - Move the code as it is; the page calls the three functions.
  - One deliberate change: in one-file mode the page passes `sourceFileName = aioFile.name`, which is saved as `c80_filename`. Today it is null, which is why runs can't be matched to their results.
- [ ] **Step 4: Golden rows.** `generate.ts` also writes `row_<case>.json` (`{meta, row}`) for the AutoFit_raw, AutoFit_calib120, ManualDense_raw and Square cases of `al2o3_ctwa`, with a fixed `RowMeta`: `modelName:'golden'`, `testDate:'17/11/2026'`, `testTime:'09:10'`, `temperature:766`, `gasAtmosphere:'Ar'`, `powerSourceDevice:'Keithley 2602B'`, `powerResponseDevice:'Drop Calorimeter'`, and `sourceFileName` = the input name. Regenerate: only new files appear in `diff -r`.
- [ ] **Step 5: Verify.** `npm test && npx tsc --noEmit && npm run build` all pass.
- [ ] **Step 6: Commit** on `save-row`.

### Task 2 (CTWA): `ctwa/analysis/row.py`, matched against the golden rows

**Files:**
- Create: `ctwa/analysis/row.py`, `tests/test_analysis_row.py`
- Copy: webapp `ops/golden/out/row_*.json` → `tests/golden/analysis/`

**Interfaces:**
- Consumes: Plan 1's `load_one_file`, `default_selection` and `run_one_file_pipeline`; `AnalysisResults`.
- Produces:
  - `RowMeta` (dataclass, snake_case of the TS fields);
  - `build_analysis_plot(synced, results, opts) -> dict`;
  - `build_analysis_row(results, meta, plot) -> dict`;
  - `find_duplicate(candidates: list[dict], row: dict) -> dict | None`;
  - `clean_for_json(row) -> dict` (non-finite → None, applied inside `build_analysis_row`).

- [ ] **Step 1: Write the failing test.** For each golden row file, re-run the case, build the row, and compare it to golden key by key. Numbers match to rel 1e-9. `graph_image` is compared after `json.loads` on both sides, with the same numeric tolerance on array values and exact strings. Also: `find_duplicate` agrees with the TS tolerances, and a NaN `ln_term` becomes `None` and serializes with `json.dumps(allow_nan=False)`.
- [ ] **Step 2: Run and see it fail.** `/usr/bin/python3 -m pytest tests/test_analysis_row.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** as a literal port of `lib/analysisRow.ts`.
- [ ] **Step 4: Run and see it pass.** Same command. Expected: PASS.
- [ ] **Step 5: Commit.**

### Task 3 (CTWA): Cloud client

**Files:**
- Create: `ctwa/cloud/__init__.py`, `ctwa/cloud/config.py`, `ctwa/cloud/client.py`, `tests/test_cloud_client.py`
- Modify: `requirements.txt` (add `keyring>=24`)

**Interfaces:**
- Produces:
  - `config.py`: `WEBAPP_URL = "https://omersthesis.vercel.app"`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`.
  - Errors: `NotLoggedIn(Exception)`, `Offline(Exception)`, `ServerError(Exception)` (with `.status`, `.message`).
  - `class TokenStore`: `get() -> str | None`, `set(token)`, `clear()`. keyring service `"CTWA"`, user `"omersthesis"`. Injectable for tests.
  - `class CloudClient(webapp_url, supabase_url, anon_key, tokens: TokenStore, timeout=15)`:
    - `login(password) -> None` (POST /api/auth; stores `token`; wrong password → `NotLoggedIn`);
    - `check_session() -> bool` (GET /api/auth with the bearer token);
    - `select(table, query: dict) -> list[dict]` (PostgREST GET with the anon key);
    - `insert(table, row) -> dict`, `update(table, id, data) -> dict`, `delete(table, id) -> None` (POST /api/db `{action, table, data, id}` with the bearer token).
  - Status mapping: 401 → `NotLoggedIn`; URLError/timeout → `Offline`; other ≥400 → `ServerError`.

- [ ] **Step 1: Write the failing tests** against a local `http.server` fake on `127.0.0.1:0` that records requests:
  - login stores the token from the JSON;
  - insert sends `Authorization: Bearer <token>` and the exact JSON body;
  - 401 → NotLoggedIn;
  - connection refused → Offline;
  - 500 → ServerError carrying the body's `error`;
  - select sends `apikey` and `Authorization: Bearer <anon>` with the query string encoded;
  - an in-memory TokenStore is used, and keyring is never touched in tests.
- [ ] **Step 2: Run and see them fail,** then implement with `urllib.request` (no `requests` dependency).
- [ ] **Step 3: Run the tests and see them pass,** then commit.

### Task 4 (CTWA): Offline upload queue

**Files:**
- Create: `ctwa/cloud/queue.py`, `tests/test_cloud_queue.py`

**Interfaces:**
- Produces `class UploadQueue(folder: str)`:
  - `enqueue(row: dict) -> str` (id);
  - `pending() -> list[tuple[str, dict]]` (oldest first);
  - `flush(client) -> tuple[int, int]` (sent, still waiting).
- Behaviour: one JSON file per row, written atomically (write to a temp file, then `os.replace`), removed only after a successful insert. `NotLoggedIn` or `Offline` stops the flush and keeps the rest. `ServerError` keeps the row and records the error beside it.
- Folder: `QStandardPaths.AppDataLocation/upload_queue`.

- [ ] **Step 1: Write the failing tests** (fake client):
  - enqueue then a new `UploadQueue` on the same folder still sees the row (restart);
  - a successful flush deletes it;
  - an Offline in the middle keeps the order;
  - NotLoggedIn sends nothing twice;
  - a partially written temp file is ignored.
- [ ] **Step 2: See them fail, implement, see them pass, commit.**

### Task 5 (CTWA): Analysis runner in a subprocess

**Files:**
- Create: `ctwa/analysis/runner.py` (no Qt: process side), `ctwa/ui/__init__.py`, `ctwa/ui/analysis_worker.py` (Qt bridge), `tests/test_analysis_runner.py`
- Modify: `main.py` (`multiprocessing.freeze_support()` first)

**Interfaces:**
- Produces, from `runner.py` (process side, picklable):
  - `load_run(path) -> LoadedRun` with `synced`, `parsed`, `header: dict` (started, experiment, instrument, calorimeter), `default: (sel_min, sel_max, clicks)`, `mean_temperature: float | None`;
  - `analyze_run(path, opts: PipelineOptions) -> AnalysisResults`.
  - The worker caches the parsed file by `(path, mtime, size)`.
- Produces `class AnalysisWorker(QObject)` with signals `loaded(object)`, `finished(object)`, `failed(str, str)` (kind, message), and methods `load(path)`, `analyze(path, opts)`, `cancel()`, `shutdown()`.
  - It uses `ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn"))` and delivers results to the GUI thread through a queued signal.
  - `cancel()` and a crash recreate the pool.
  - Failures:
    - `PipelineError` → `failed("pipeline", code)`;
    - `ValueError` → `failed("analysis", str(e))`;
    - `BrokenProcessPool` → `failed("crash", …)`.

- [ ] **Step 1: Write the failing tests:**
  - `load_run` on `tests/data/runs/al2o3_ctwa.csv.gz` (decompressed to `tmp_path`) gives the header fields and 17,700 points;
  - `AnalysisWorker.analyze` (offscreen QApplication, waiting with `QSignalSpy`/an event loop, ≤ 30 s) emits `finished` with `alpha_phase_raw` equal to the golden AutoFit value;
  - a garbage file emits `failed("pipeline", "parseFailed")`;
  - killing the worker process mid-run emits `failed("crash", …)` and the next analyze succeeds;
  - the GUI thread is never blocked: a QTimer ticking every 20 ms during an analysis never misses more than 2 ticks.
- [ ] **Step 2: See them fail, implement, see them pass, commit.**

### Task 6 (CTWA): Runs tab

**Files:**
- Create: `ctwa/ui/runs_tab.py`, `ctwa/ui/run_index.py` (no Qt: scanning, header parse, cache), `tests/test_runs_tab.py`

**Interfaces:**
- Consumes: `CloudClient.select`, `load_run` header parsing (shared helper in `run_index.py`).
- Produces:
  - `run_index.py`: `scan(folders: list[str]) -> list[RunInfo]` with `RunInfo(path, name, started: datetime | None, length_s: float | None, size, mtime)`. The length comes from the last row's `Elapsed(s)`, read from the file's tail. The mean temperature is cached in a JSON file beside the queue folder, keyed by path + mtime + size.
  - `class RunsTab(QWidget)` with signal `open_run(str)` and methods `set_recording_path(path | None)` and `refresh()`.
- **Columns:** Name, Started, Length, Saved analyses, Sample, Temperature.
  - **Saved analyses** is exact when a saved row's `c80_filename` equals the file name. Otherwise it is the count of rows with the same `test_date`, shown grey with the tooltip "same day; older results don't record their file".
  - **Sample** is the `model_name` of the newest exact match.
- **Buttons:** Analyze (or double-click), Open…, Add folder…, Remove folder, Refresh.
  - The folders are the auto-save folder plus the added ones, kept in QSettings `runs/folders`.
  - The recording file shows "recording" and Analyze is disabled for it.
- Supabase reads run off the GUI thread (QThreadPool). If offline, the Saved/Sample columns show "—" with a tooltip.

- [ ] **Step 1: Write the failing tests:**
  - `scan` on a tmp tree with two gzipped-then-unpacked runs and one non-CSV finds the two, with correct `started`/`length_s`;
  - `RunsTab` with a fake client shows exact versus same-day counts;
  - the recording path disables Analyze;
  - Add folder persists across a new `RunsTab`.
- [ ] **Step 2: See them fail, implement, see them pass, commit.**

### Task 7 (CTWA): Analysis tab — plot, settings, Analyze, results

**Files:**
- Create: `ctwa/ui/analysis_tab.py`, `tests/test_analysis_tab.py`

**Interfaces:**
- Consumes: `AnalysisWorker`, `LoadedRun`, `PipelineOptions`/`AnalysisParams`, `peaks.snap_to_peak`.
- Produces `class AnalysisTab(QWidget)`:
  - method `open_run(path)`;
  - signal `result_ready(object)` carrying `(LoadedRun, PipelineOptions, AnalysisResults)` for Task 8.
- **Layout:** one screen. The top is a pyqtgraph plot of source and response over time, with a `LinearRegionItem` for the region and four draggable `InfiniteLine` markers (peak1, peak2, resp, resp2), shown only in Manual. Markers snap with `snap_to_peak` when dropped, as the webapp page does.
- **Settings (left):** wave type, mode, smooth-to-sine, cycle shift, r1, r2, use calibration + system lag, period override (AutoFFT/AutoFit), square period (square). Defaults come from the webapp page.
- **Results (right):** α_phase raw and calibrated, α_combined, lag ± SE, A₁, A₂, period, ln term, and a "check the cycle" warning when `lag_near_edge`.
- **Analyze** starts the worker and is disabled while running; **Cancel** appears while running.
- Errors appear in the results panel in plain words. Each PipelineError code is mapped to the webapp's English message text, and analysis messages are shown as they are.

- [ ] **Step 1: Write the failing offscreen tests:**
  - `open_run` on the Al₂O₃ file sets the region to the default selection;
  - Analyze in AutoFit shows `alpha_phase_raw` formatted from the golden value;
  - Manual shows four markers, and dropping one snaps it to a peak;
  - a 5-point region shows the tooFewPoints message;
  - pressing Analyze twice quickly runs once.
- [ ] **Step 2: See them fail, implement, see them pass, commit.**

### Task 8 (CTWA): Saving — form, pre-fill, duplicates, queue, login

**Files:**
- Create: `ctwa/ui/save_panel.py`, `ctwa/ui/login_dialog.py`, `tests/test_save_panel.py`

**Interfaces:**
- Consumes: `result_ready`, `build_analysis_plot`/`build_analysis_row`/`find_duplicate`, `CloudClient`, `UploadQueue`.
- Produces `class SavePanel(QWidget)` (under the results), with signal `saved(int | None)` (row id, or None when queued).
- **Pre-fill:**
  - date/time from the header's Started (`DD/MM/YYYY`, `HH:MM`);
  - devices: `Keithley <model>` from the Instrument line, `Drop Calorimeter` for a Drop/Alexsys calorimeter, `C80` for C80;
  - temperature: the mean `temperature` over the selected region;
  - sample and gas: the last values used for the same experiment name (QSettings `save/last/<experiment>`), else empty / `Ar`.
  - Everything stays editable.
- **Save:**
  1. Build the row with `sourceFileName` = the run file name.
  2. Read the same-date candidates (`select analyses id,model_name,analysis_mode,period_t,amplitude_a1 where test_date=eq.<date>`).
  3. On a match, show the webapp's duplicate dialog choices with the same effect.
  4. Insert.
- **Failures:** `Offline` → queue it and say "Saved on this computer; will upload when online". `NotLoggedIn` → login dialog, then retry once; if cancelled, queue it.
- **Status bar label:** "N waiting to upload", refreshed after each save and flush. A flush runs on start, after each save, and every 5 min (QTimer).
- **Login dialog:** password field, which calls `client.login` and shows an error on a wrong password.

- [ ] **Step 1: Write the failing tests** (fake client and in-memory queue):
  - pre-fill values from the Al₂O₃ header;
  - Save sends one insert whose row equals `build_analysis_row` output;
  - a duplicate shows the dialog, and Cancel sends nothing;
  - Offline → queued and the label says 1;
  - 401 → login dialog shown (auto-accepted in the test), then the insert is retried once.
- [ ] **Step 2: See them fail, implement, see them pass, commit.**

### Task 9 (CTWA): Wiring into the main window, packaging, screenshots

**Files:**
- Modify: `ctwa/app.py` (tabs after Real Time; `open_run` wiring; `set_recording_path` from the sweep's current CSV path; a Settings menu entry "Webapp login…"; status-bar label), `keithley_suite.spec` (`hiddenimports` for `ctwa.analysis.*`, `ctwa.cloud.*`, `ctwa.ui.*`, `keyring.backends.Windows`, `keyring.backends.macOS`), `requirements.txt` if not done
- Test: `tests/test_main_window_tabs.py`

- [ ] **Step 1: Write the failing test.** A simulated-2602B MainWindow has tabs `[…, "Real Time", "Runs", "Analysis"]`. Runs `open_run` switches to Analysis with that file loaded. A running simulated sweep marks its CSV as recording in Runs.
- [ ] **Step 2: Implement.** Rerun `tests/test_equivalence_with_original_windows.py`; it must stay green.
- [ ] **Step 3: Full suite.** `/usr/bin/python3 -m pytest -q` is all green (report counts).
- [ ] **Step 4: Screenshots.** Offscreen screenshots of the Runs and Analysis tabs, the latter after an AutoFit on the Al₂O₃ file, saved in the scratchpad for Omer.
- [ ] **Step 5: Commit.**

**After Plan 2:**
- Omer merges `save-row` (the webapp change) after review.
- The first real save from the lab PC is part of the 2.0.0 release checklist.
- Plan 3 covers Results, Calibration and Statistics.
