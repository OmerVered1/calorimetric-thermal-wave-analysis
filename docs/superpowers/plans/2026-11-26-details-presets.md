# Run Details: Presets, Settings Box, Date-Ordered List — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sample, Power source and Response device become preset dropdowns ending in `Fill in new…`. The temperature field shows a grey `leave blank = automatic` hint. The run details live in a "Run details" box in the experiment Settings tab, behaving like the other settings. The experiment list is ordered newest-created first, with the date beside each name.

**Spec (short design, Omer's answers 26 Nov 2026 via the question tool):**
- **Presets:**
  - Sample = distinct trimmed `model_name` values from the results database rows the app already holds (`MainWindow.results_loader.rows()`, when present), plus values typed before.
  - Power source = `Keithley 2602B`, `Keithley 2611A`, `Keithley 2450`, `Keithley 6430`, plus typed before.
  - Response device = `C80`, `Drop Calorimeter`, plus typed before.
  - The last item is always `Fill in new…`.
- **Run details box:** in the experiment Settings tab, like the other settings. A change marks the experiment unsaved, Save keeps it, and Start writes what the box shows. The sidebar's details block and `Edit details…` are removed (duplicate).
- **List:** newest created first, date beside the name.
- **Temperature hint:** grey placeholder `leave blank = automatic`. This is the one deliberate grey text, in `theme.P.text_disabled`.

## Global Constraints
- **Branch:** `desktop-analysis`. Commit per task; message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. No push. Never add stray `* 2.*` copies.
- **Untouchable:**
  - `ctwa/instruments/` and `keithley*_driver.py`;
  - the run-header keys and their format (`ctwa/experiment_details.header_lines`, `ctwa/analysis/run_header.py`);
  - the Analysis tab.
- **Exact strings:**
  - `Fill in new…` (with `…`, U+2026);
  - `leave blank = automatic`;
  - group title `Run details`;
  - list date format `%d/%m/%Y` from the record's `created_at` (ISO). An item reads `<name>   <dd/mm/yyyy>`; a record without `created_at` sorts last and shows only the name.
- **Remembered typed values:** QSettings key `experiment/presets/<field>` (`sample`, `power_source`, `response_device`). It's a list, most recent first, de-duplicated (case-sensitive, trimmed), capped at 30. Values are added when an experiment is created or saved.
- **Old experiment records** without `details` load with every field blank.
- **Tests:** never touch the real experiments file or settings. Reuse the `_scratch_experiments_file` fixture pattern in `tests/test_experiment_details_ui.py`, and the conftest isolation. Run only the touched area's tests plus `tests/test_equivalence_with_original_windows.py`.

## Review Focus
1. Choosing `Fill in new…` clears the field and focuses it for typing. The literal text `Fill in new…` is never saved as a value. Pinned in Task 1.
2. A preset list with the current value missing (an old record says "Keithley 2400") still shows that value, not the first preset. Pinned in Task 1.
3. Renaming, cloning or deleting an experiment keeps the list order and selection right, now that item text ≠ name. Pinned in Task 3.
4. Start after editing the box but before Save writes the box's values into the run header. Pinned in Task 2.
5. Loading another experiment refreshes the box without marking anything dirty. Pinned in Task 2.

---

### Task 1: `DetailsForm` with preset combos (shared by the dialog and the box)
**Files:**
- create `ctwa/ui/details_form.py`;
- modify `ctwa/ui/experiment_details_dialog.py` (use the form);
- modify `ctwa/experiment_details.py` (add `SOURCE_PRESETS`, `RESPONSE_PRESETS`, `FILL_IN_NEW = "Fill in new…"`);
- test `tests/test_details_form.py`.

**Produces:**
- `PresetCombo(QComboBox)`: editable, items = presets + `Fill in new…`. `set_presets(list)` keeps the current text. Choosing `Fill in new…` clears the edit text and focuses it. `value() -> str` (never `Fill in new…`).
- `DetailsForm(QWidget)`: one row per `FIELDS` entry. Sample, power source and response device are `PresetCombo`s; gas is the existing editable combo with `GAS_CHOICES`; temperature, r1 and r2 are `QLineEdit`s. The temperature `QLineEdit` gets the placeholder `leave blank = automatic`, with its palette's `PlaceholderText` set to `theme.P.text_disabled`.
  - `values() -> dict`, `set_values(dict)` (emits nothing);
  - `changed = Signal()` on user edits;
  - `set_presets(field: str, values: list[str])`.
- Helpers in `ctwa/ui/details_form.py`:
  - `remembered(settings, field) -> list[str]`;
  - `remember(settings, details: dict) -> None`, storing typed values under the key above;
  - `presets_for(field, settings, sample_names=()) -> list[str]`, built-ins then sample names then remembered, de-duplicated, order kept.
- [ ] Tests:
  - combos contain presets + `Fill in new…` last;
  - choosing it clears and the value is `""`;
  - typed new value returned by `values()`;
  - a value not in the presets is kept by `set_values`;
  - the placeholder text and its colour equal `P.text_disabled`;
  - `remember` caps at 30, most recent first, no duplicates;
  - the dialog still returns `(name, details)` and refuses empty or taken names (existing tests keep passing).
- [ ] Commit.

### Task 2: "Run details" box in the Settings tab; sidebar block removed
**Files:** `ctwa/app.py` (Settings sub-tab grid, `_capture_state`, `_apply_state`, `_wire_dirty_tracking`, `_new_experiment`, `_save_experiment`, `_load_experiment`, `_clone_experiment`, `_build_csv_metadata_rows`, `ExperimentsSidebar`, `ExperimentStore.set_details`); tests in `tests/test_experiment_details_ui.py`.
**Consumes:** Task 1's `DetailsForm`, `remember`, `presets_for`.
- `self.run_details = QGroupBox("Run details")` holding a `DetailsForm`, added to the Settings grid at row 2 spanning both columns. Row stretch moves to row 3.
- `_capture_state()["details"] = form.values()`. `_apply_state` sets them (old record → all blank) under `_suppress_dirty`. `form.changed` marks dirty. Save stores them (via `_capture_state`) and calls `remember`. The header uses `form.values()` live. `self._current_experiment_details` is removed.
- New: the dialog (now with preset combos) → `form.set_values(details)` → save. Presets are refreshed whenever the Settings tab or the dialog is shown: `presets_for(...)`, with sample names from `self.results_loader.rows()` if the loader exists.
- Remove the sidebar details block, `Edit details…`, `details_edited`, `_on_details_edited` and `ExperimentStore.set_details`. Update their tests to the new behaviour.
- [ ] Tests:
  - the box exists in the Settings tab with the 7 fields;
  - editing it marks dirty, and Save stores `details`;
  - Start before Save writes the edited values into the CSV header;
  - loading another experiment fills the box, not dirty;
  - an old record → blanks;
  - clone copies details;
  - New's details land in the box;
  - sample presets include a name from a fake `results_loader.rows()`.
- [ ] Commit.

### Task 3: Experiment list newest-created first, with dates
**Files:** `ctwa/app.py` (`ExperimentStore.names` callers, `ExperimentsSidebar.refresh`, `_selected_name`, every place that compares `item.text()` with a name); tests in `tests/test_experiment_details_ui.py` or a new `tests/test_experiment_list_order.py`.
- `ExperimentStore.names_by_created() -> list[str]`: newest `created_at` first, records without it last (alphabetical among themselves).
- List items: text `<name>   <dd/mm/yyyy>`, name in `Qt.UserRole`. Every lookup uses `Qt.UserRole`.
- [ ] Tests:
  - order with three records of different `created_at` plus one without;
  - item text and date format;
  - select, rename, clone and delete still act on the right experiment;
  - the current-experiment highlight follows the name.
- [ ] Commit.
