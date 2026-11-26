# Experiment Details + Black Text Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Experiments carry run details (sample, devices, temperature, gas, r₁, r₂) into every run file and on into the Analysis tab. All grey text in the desktop app becomes black, except disabled controls.

**Architecture:** A Qt-free module `ctwa/experiment_details.py` owns the fields, defaults and the header lines. `ctwa/analysis/run_header.py` parses the new header keys. The UI parts are a details dialog, the sidebar panel and Start writing the header, plus the Analysis tab and save form reading it.

**Tech Stack:** Python 3.9, PySide6, pytest (`QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m pytest`).

**Spec:** `docs/superpowers/specs/2026-11-26-experiment-details-design.md`

## Global Constraints
- **Branch:** `desktop-analysis`. Commit per task. No push.
- **Commit messages** end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Untouchable:** `ctwa/instruments/` and `keithley*_driver.py`. `tests/test_equivalence_with_original_windows.py` must stay green: no instrument command changes.
- **Header keys,** exact, one word each (the parser reads `# Word: value`): `Sample`, `PowerSource`, `ResponseDevice`, `Temperature`, `Gas`, `InnerRadius`, `OuterRadius`. Radii are written as plain mm numbers, temperature as plain °C numbers. Blank fields are not written.
- **Defaults:** gas `Ar`, r₁ `6.72`, r₂ `14.86` (= `ctwa/ui/analysis_settings.py` DEFAULT_R1/DEFAULT_R2), sample and temperature blank. Power source = `instrument_device(idn)`, response device = `calorimeter_device(cal)` (both in `ctwa/ui/save_panel.py`).
- **Temperature in the save form:** the measured average over the selected region when the run has it, else the header's `Temperature`.
- **Tests:** only the touched area's tests (Omer's speed rule).
- **Ignore** stray files named `* 2.py`. Never `git add` them.

## Review Focus
1. Old experiments (no `details` key) load, save and clone without error; their runs write no detail lines. Pinned in Task 3.
2. A typed temperature like `800 °C` or `800,5` is stored as text; the header writes it only if it parses as a number (comma decimal accepted). Otherwise it is left out, not written as junk. Pinned in Task 2.
3. A run file with detail lines but no temperature column gets the typed temperature; a run with the column gets the measured one. Pinned in Task 4.
4. The details must survive Save, so editing a sweep and saving the experiment doesn't wipe them. Pinned in Task 3.
5. r₂ ≤ r₁ in a header doesn't break the Analysis tab. The spins are set, and the existing r₂ > r₁ validity check stops Analyze, as when typed. Pinned in Task 4.

---

### Task 1: Grey text → black (controller does this one)
**Files:** `ctwa/theme.py`, `ctwa/ui/runs_tab.py:117`, `ctwa/ui/statistics/legend_bar.py:91`, `ctwa/app.py:2590`; test `tests/test_theme_text.py`.
- `Palette`: `text_muted` and `text_faint` become `"#1B1C1E"` (= `text`). New `text_disabled: str = "#84878D"`.
- Every `:disabled` rule in `stylesheet()` uses `p.text_disabled`. Also these "off" cues use `text_disabled`: runs that aren't captures (runs_tab:117), hidden legend entries, the preview's segment-boundary line (a line, not text). The radio/check indicator hover border uses `p.border_strong`.
- `QPalette.PlaceholderText` uses `P.text`.
- [ ] Test `test_text_is_black_and_disabled_stays_grey`: `P.text_muted == P.text_faint == P.text`; `P.text_disabled != P.text`; every stylesheet block whose selector contains `:disabled` and sets `color:` uses `P.text_disabled`; after `theme.apply(app)`, the placeholder colour equals `P.text`.
- [ ] Commit.

### Task 2: Details module + header write/parse
**Files:** create `ctwa/experiment_details.py`; modify `ctwa/analysis/run_header.py`, `ctwa/app.py` (`_build_csv_metadata_rows`, after the `# Experiment:` row); test `tests/test_experiment_details.py`.
**Produces:**
- `FIELDS: tuple[tuple[str, str], ...]` = (key, label): `("sample","Sample"), ("power_source","Power source"), ("response_device","Response device"), ("temperature_c","Temperature (°C)"), ("gas","Gas"), ("r1_mm","Inner radius r₁ (mm)"), ("r2_mm","Outer radius r₂ (mm)")`.
- `default_details(instrument: str | None, calorimeter: str | None) -> dict` (all keys; strings, radii as the strings `"6.72"`/`"14.86"`).
- `header_lines(details: dict | None) -> list[str]` → e.g. `["# Sample: Al2O3", "# PowerSource: Keithley 2602B", ..., "# InnerRadius: 6.72"]`, omitting blank and non-numeric temperature/radius values.
- `parse_number(text) -> float | None` (comma decimal, strips `°C`/`mm`, finite only).
- `parse_run_header` additionally returns `sample`, `power_source`, `response_device`, `gas` (str or None) and `temperature_c`, `r1_mm`, `r2_mm` (float or None).
- [ ] Tests: `header_lines` exact output for a full dict; blanks omitted; `"800 °C"` → `# Temperature: 800`, `"abc"` → omitted, `"0,5"` → `0.5`; round trip `parse_run_header("\n".join(["# Started: 2026-11-26 10:00:00","# Experiment: E"] + header_lines(d)) + "\nTime,V")` gives the values back; an old header gives `None` for every new key.
- [ ] Wire `_build_csv_metadata_rows` to append `header_lines(self._current_experiment_details)` right after the Experiment row. Test: a simulated sweep with details set writes them in the live CSV (reuse the `_sweep` helper pattern from `tests/test_equivalence_with_original_windows.py`, auto-save to a tmp dir).
- [ ] Commit.

### Task 3: New/Edit dialog, sidebar panel, persistence
**Files:** create `ctwa/ui/experiment_details_dialog.py`; modify `ctwa/app.py` (`ExperimentsSidebar`, `_new_experiment`, `_save_experiment`, `_load_experiment`, `_clone_experiment`, `_capture_state`-adjacent payload); test `tests/test_experiment_details_ui.py`.
**Consumes:** Task 2's `FIELDS`, `default_details`.
- `ExperimentDetailsDialog(parent, name: str | None, details: dict, taken_names: set[str])`: name field shown only when `name` is not None (New), then one row per FIELD (gas = editable combo with `GAS_CHOICES`). `.values() -> tuple[str | None, dict]`. OK is refused with a message for an empty or taken name.
- **New:** the sidebar's New opens the dialog, defaulting to `default_details(<connected instrument IDN or None>, <connected calorimeter name or None>)`. The signal `new_requested` carries `(name, details)`.
- **Panel:** under the current-experiment label, a compact read-only block, one line per filled field ("Sample: Al2O3"), plus an **Edit details…** button. Hidden when no experiment is loaded. Edit saves the new details straight into the store record (`details` key) without touching other keys or the dirty flag.
- `MainWindow._current_experiment_details: dict` is set on new/load (`exp.get("details") or {}`) and included in every `_save_experiment` payload as `payload["details"]`. Clone copies it (deep copy).
- [ ] Tests (offscreen MainWindow, simulated 2602B, experiments file in tmp): New with details → the store record has them and the panel shows "Sample: X"; Save after changing a sweep keeps `details`; loading an old record without `details` works and the panel shows nothing; clone copies details; Edit changes the store and leaves the dirty flag alone.
- [ ] Commit.

### Task 4: Analysis reads the details
**Files:** `ctwa/ui/analysis_tab.py` (`_on_loaded`), `ctwa/ui/save_panel.py` (`set_result`); test additions in `tests/test_save_panel.py` and the analysis-tab test file.
- `_on_loaded`: if `run.header["r1_mm"]` / `["r2_mm"]` is a number, set `settings.r1_spin` / `r2_spin` to it, so the first Analyze uses it. Otherwise leave the spins as they are.
- `set_result`:
  - Sample = header `sample`, else today's per-experiment memory.
  - Gas = header `gas`, else memory, else `Ar`.
  - Power source = header `power_source`, else `instrument_device(...)`.
  - Response device = header `response_device`, else `calorimeter_device(...)`.
  - Temperature = `region_temperature(...)` if non-empty, else header `temperature_c` formatted with `js_to_precision`-free `%g`.
- [ ] Tests: each field's header-wins and fallback cases; temperature measured vs header-only (a run file without a temperature column); r₁/r₂ spins set from the header; r₂ ≤ r₁ in the header leaves Analyze disabled with no exception.
- [ ] Commit.
