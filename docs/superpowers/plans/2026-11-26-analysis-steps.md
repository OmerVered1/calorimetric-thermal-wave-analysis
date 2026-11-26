# Analysis Tab in Steps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The desktop Analysis tab works in steps (① Setup → ② Region → ③ Peaks (Manual only) → ④ Results) like the webapp, and the results show the source and response period and frequency separately.

**Architecture:** Inside `AnalysisTab`, a step bar sits above the existing splitter. The plot stays the top pane, shown on ②–④ and hidden on ①. The bottom pane becomes a `QStackedWidget` with one page per step. `SavePanel` is split into a form part, placed on ①, and a save part, placed on ④. The maths, the worker and what is saved are unchanged.

**Tech Stack:** Python 3.9, PySide6, pyqtgraph, pytest (`QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m pytest`).

**Spec:** `docs/superpowers/specs/2026-11-26-analysis-steps-design.md`

## Global Constraints
- **Branch:** `desktop-analysis`. Commit per task; message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. No push. Never `git add` stray `* 2.py` / `* 2.*` copies.
- **Untouchable:** `ctwa/analysis/` maths, `ctwa/ui/analysis_worker.py` protocol, `ctwa/instruments/`, `keithley*_driver.py`, the saved row (`ctwa/analysis/row.py`).
- **Keep these `AnalysisTab` names and meanings,** because 31 analysis-tab tests use them: `region`, `markers`, `settings`, `analyze_btn`, `cancel_btn`, `results_panel`, `run`, `worker`, `open_run`, `result_ready`, `result_cleared`, `run_loaded`, `set_save_panel`, `is_snapping`, `is_running`, `src_curve`, `splitter`, `title`, `shutdown`.
  - Keep one `analyze_btn` object. Show it on ② for non-Manual modes and on ③ for Manual.
  - Where a test clicks Analyze without going through the steps, enabling still follows `_update_controls` (run loaded, not running, not snapping, settings valid). Being on the right step must **not** be part of `analyze_btn.isEnabled()`. Instead, `analyze_btn` is placed on the visible bar, and a hidden button's click still works.
- **Labels, exact:**
  - step bar: `1 Setup`, `2 Region`, `3 Peaks`, `4 Results`;
  - buttons: `Next: Region →`, `← Back`, `Next: Peaks →`, `← Region`, `Analyze`, `Save to database`;
  - region readout: `Region %.0f – %.0f s`;
  - Peaks hint: `Drag S1 and S2 onto two neighbouring source peaks, R1 and R2 onto the response peaks that follow them.`;
  - saving line: `Saving as: <sample> · <date> <time> · <temperature> °C · <gas>` plus an `Edit` link button. A missing part shows `—`.
- **Results rows:** `Period T` becomes `Source Period T`. Add `Response Period T` (s), `Source Frequency f` (Hz) and `Response Frequency f` (Hz), right after it. The frequencies use 4 significant figures (`_prec(x, 4)`), from `period_t_resp`, `frequency_f`, `frequency_f_resp` on `AnalysisResults`.
- **Tests:** only the touched area's: `tests/test_analysis_tab.py`, `tests/test_save_panel.py`, `tests/test_analysis_results*.py` if present, `tests/test_main_window_tabs.py`, `tests/test_experiment_details*.py`. No full suite.

## Review Focus
1. Opening a second run while on ④ returns to ① and clears the old result; ④ in the step bar is disabled. Pinned in Task 2.
2. Switching mode from Manual to Auto while on ③ goes back to ② (no Peaks step outside Manual). Pinned in Task 2.
3. A temperature typed at ① survives Analyze. A field left alone takes the measured average. Analyzing again with a new region updates an untouched field again. Pinned in Task 1.
4. ③'s zoom: the x-range is the region ± 5 % of its width. Going ← Region restores the whole-run view. Pinned in Task 2.
5. A save in flight keeps the ① form and the ④ Save button disabled, as the single panel did. Pinned in Task 1.

---

### Task 1: Results rows + save form split
**Files:** `ctwa/ui/analysis_results.py` (ROWS, `format_results`), `ctwa/ui/save_panel.py`; tests in `tests/test_save_panel.py` (+ a results-rows test wherever `format_results` is tested now).
**Produces (SavePanel):**
- `SavePanel.form_widget: QWidget`, the 7-field form, and `SavePanel.action_widget: QWidget`, holding the `Saving as:` line with its `Edit` button, `save_btn` and `status_label`. The panel's own layout no longer shows them; the tab places them.
- `SavePanel.set_run(run)`, called on `AnalysisTab.run_loaded`. It fills date, time, devices, sample, gas and temperature (= the header's `temperature_c`, `%g`, else empty) from the header, with the same fallbacks `set_result` uses today. It resets "temperature typed by user" to False.
- `set_result(payload)` no longer refills sample, devices, gas, date or time. It sets temperature to `region_temperature(...)` only if non-empty **and** the user hasn't typed in the field since `set_run`. It updates the saving line and the Save enabled state as before.
- Signal `edit_requested()` fires from the `Edit` link.
- The saving line is refreshed whenever any form field changes.
- [ ] Tests:
  - the results rows contain `Source Period T`, `Response Period T`, `Source Frequency f`, `Response Frequency f` with the formatted values;
  - `set_run` pre-fills from the header;
  - typed temperature survives `set_result`;
  - an untouched temperature takes the measured value, also on a second `set_result`;
  - the saving line text;
  - a busy save disables both parts;
  - existing save tests are adapted (call `set_run` before `set_result` where they relied on the pre-fill).
- [ ] Commit.

### Task 2: Steps in the Analysis tab
**Files:** `ctwa/ui/analysis_tab.py`, `ctwa/app.py` only if wiring changes (`set_save_panel` call site); tests in `tests/test_analysis_tab.py`.
**Consumes:** Task 1's `form_widget`, `action_widget`, `set_run`, `edit_requested`.
**Produces:** `AnalysisTab.step() -> str`, one of `"setup" | "region" | "peaks" | "results"`; `AnalysisTab.go(step: str) -> None`; `AnalysisTab.step_buttons: dict[str, QPushButton]`.
- The step bar is 4 checkable buttons. `3 Peaks` is hidden unless the mode is Manual. A step is enabled when reachable:
  - `setup`: always;
  - `region`: run loaded;
  - `peaks`: Manual and run loaded;
  - `results`: a result is shown.
- **Pages:**
  - setup = title/run line, `save_panel.form_widget` (if a save panel is attached), `settings`, `Next: Region →`;
  - region = readout, `← Back`, then `Next: Peaks →` or `analyze_btn`;
  - peaks = hint, `← Region`, `analyze_btn`;
  - results = `results_panel`, `save_panel.action_widget`, `← Back` (to peaks in Manual, else region).
- **Plot:**
  - hidden on setup;
  - region: markers hidden, region movable, autoRange to the whole run;
  - peaks: markers visible and movable, region not movable, x-range = region ± 5 %;
  - results: same view as peaks, markers not movable.
- `open_run` → `go("setup")`. A finished analysis → `go("results")`. `result_cleared` while on results → `go("peaks" if Manual else "region")`. A mode change away from Manual while on peaks → `go("region")`. `edit_requested` → `go("setup")`.
- The splitter state key changes to `analysis/splitter2`, so an old saved layout doesn't hide the new pages.
- [ ] Tests:
  - initial step is setup with the plot hidden;
  - Next goes to region once loaded;
  - Manual: region → peaks shows markers and zooms (x-range within region ± 5 %);
  - Auto: no peaks button, Analyze on the region page;
  - after Analyze it's results;
  - changing the region on results clears and returns;
  - opening another run returns to setup;
  - mode change on peaks goes to region;
  - Edit link goes to setup;
  - all existing analysis-tab tests pass, adapted only where they asserted the old one-screen layout.
- [ ] Commit.
