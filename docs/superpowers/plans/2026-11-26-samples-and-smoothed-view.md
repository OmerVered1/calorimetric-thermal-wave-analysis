# Sample Names in the Dropdowns + Smoothed Region/Peaks View — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) The Sample dropdowns list the sample names already in the results database. (2) With "Smooth to single sine" ticked, ② Region and ③ Peaks draw the smoothed signals, as the webapp does.

**Omer's report (26 Nov 2026, after 2.0.3):** "sample doesn't have that thing I asked for where it loads existing sample names in a drop thingy, and in the region selection it doesn't show the smoothed graph".

**Root causes (from reading the code):**
1. **Sample names:** `MainWindow._sample_names()` reads `results_loader.rows()`. The loader only fetches when the Results, Statistics or Calibration tab is first shown, so before that the list is empty. `_refresh_detail_presets` runs only when the Run details box is shown or on save; nothing re-fills the presets when `rows_changed` arrives.
2. **Smoothed view:** the Analysis plot always draws the raw synced curves. The webapp (`app/analysis/page.tsx`) does two things:
   - **overview** (Region step): when smoothing is on (sine), it draws `smoothPiecewise(synced…)` (each burst fit to its own sine, gaps raw) over the whole run, titled "Full Experiment Overview (smoothed)";
   - **peaks view:** it draws `peakSignals`: the smoothed region when smoothing is on, else the signals with their slow baseline removed when the region spans ≥ 3 periods, else raw.

   The desktop already computes these: `ctwa.analysis.smoothing.smooth_piecewise`, and `runner.region_info(...).snap` (the same smoothed or flattened series, used today only for snapping).

**Calls made (Omer delegates; state them in the report):** the Analysis ① Setup form's Sample, Power source and Response device also become the same preset dropdowns, so every Sample field offers the database names.

## Global Constraints
- **Branch:** `desktop-analysis`. Commit per task; message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. No push. Never add stray `* 2.*` copies. No subagents. Nothing left running when done.
- **Untouchable:** `ctwa/analysis/` maths (reuse `smooth_piecewise` and `region_info` as they are), the saved row, `ctwa/instruments/`.
- **GUI thread never computes a smoothing:** `smooth_piecewise` over a whole run takes seconds, so it runs in the analysis worker process (`ctwa/ui/analysis_worker.py`, the same `_submit` pattern as `region_info`). The result is cached per path in the process, like `smoothed_region` / `_SMOOTH_CACHE` in `runner.py`. Until it arrives, the raw curves stay.
- **Tests:** only the touched area's (`tests/test_analysis_tab.py`, `tests/test_save_panel.py`, `tests/test_details_form.py`, `tests/test_experiment_details_ui.py`, `tests/test_main_window_tabs.py`, plus any new file). Python 3.9, `QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m pytest <files> -q`.

## Review Focus
1. Unticking smoothing brings the raw curves back immediately; ticking again uses the cached smoothed curves without recomputing. Pinned in Task 2.
2. Opening a different run never shows the previous run's smoothed curves. A late smoothing result for an old path is dropped. Pinned in Task 2.
3. Square wave: no smoothing display (the checkbox is hidden for square). Pinned in Task 2.
4. Rows arriving while the New dialog is open don't crash, and its presets are taken when it opens. Pinned in Task 1.
5. The save panel's Sample keeps `text()` / `setText()` behaviour, so its 40 tests and the save path are unchanged. Pinned in Task 1.

---

### Task 1: Sample names everywhere
**Files:** `ctwa/app.py`, `ctwa/ui/details_form.py` (`PresetCombo`: add `text()` / `setText()` aliases of `value()` / `set_value()`), `ctwa/ui/save_panel.py`; tests.
- After the main window is first shown, if `self.results_loader` exists, call `self.results_loader.refresh()` once (`QTimer.singleShot(0, …)` from the first `showEvent`). That's one fetch off the GUI thread; the tabs keep their own refresh logic.
- Connect `results_loader.rows_changed` → `_refresh_detail_presets` and → the save panel's preset refresh.
- `SavePanel`: `sample_edit`, `source_device_edit` and `response_device_edit` become `PresetCombo`s, with the same names and `text()` / `setText()` behaviour. Add `SavePanel.set_presets(field: str, values: list[str])`. MainWindow fills them with the same `presets_for(...)` lists.
- [ ] Tests:
  - a MainWindow with a fake loader whose `rows_changed` emits rows `[{"model_name": "Stainless Steel"}, {"model_name": "unk foam "}]` → the Run details Sample combo and the save panel Sample combo both list `Stainless Steel` and `unk foam` (trimmed), with `Fill in new…` last;
  - the first show triggers exactly one `refresh()`;
  - the save panel tests stay green.
- [ ] Commit.

### Task 2: Smoothed curves on ② and ③
**Files:** `ctwa/analysis/runner.py` (add `smoothed_full(path) -> tuple | None`, a cached `smooth_piecewise(synced.t_src, synced.v_src, synced.t_cal, synced.v_cal)`; it reuses the existing function, so it's no maths change), `ctwa/ui/analysis_worker.py` (a `smoothed_full(path)` request + `smoothed_ready(str path, object)` signal), `ctwa/ui/analysis_tab.py`; tests in `tests/test_analysis_tab.py`.
- **② Region with smoothing on (sine):** request `smoothed_full` once per run. When it arrives for the current path, draw it in place of the raw curves. The plot title or readout says `(smoothed)`. With smoothing off, or before it arrives, draw raw.
- **③ Peaks:** draw the current `RegionInfo.snap` series (smoothed region, or baseline-removed) when it's available for the current region and smoothing state. That's exactly what the markers snap to. Otherwise draw raw.
- **④ fallback** (no figure) keeps raw.
- [ ] Tests:
  - with smoothing on, after `smoothed_ready`, ② shows curves equal to `smooth_piecewise` of the run (compare `src_curve.getData()` with a direct call);
  - unticking restores the raw `synced` values;
  - ③ shows the `snap` series;
  - a late `smoothed_ready` for another path is ignored;
  - square wave → raw.
- [ ] Commit.
