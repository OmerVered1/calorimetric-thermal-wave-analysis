# Results Foundation (Plan 2.5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** One shared data layer and one set of display helpers for the three parallel plans: Results (Plan 3), Calibration (Plan 4) and Statistics (Plan 5). Built once on `desktop-analysis` before those plans branch off, so they don't each write their own copy.

**Architecture:**
- `ctwa/results/` is Qt-free: column metadata, literal ports of the webapp's small display helpers, and a blocking `ResultsStore` over `CloudClient`.
- `ctwa/ui/results_loader.py` is the Qt bridge: fetches run off the GUI thread and results come back by signals.

**Spec:** `docs/superpowers/specs/2026-11-24-ctwa-desktop-analysis-design.md`. The webapp feature inventories are in the session scratchpad (`plan3-results-inventory.md`, `plan4-calibration-inventory.md`, `plan5-statistics-inventory.md`).

## Global Constraints
- **Branch:** `desktop-analysis`. No push, no tags.
- **Python 3.9.** No real network in tests; use a fake client.
- **Literal ports:** the webapp (`/Users/omervered/Documents/msc results/Claude Code Works/angstrom-webapp-vercel`, `main`) is the reference for every helper. Pin TS outputs in tests via a throwaway `npx tsx` script.
- **GUI thread:** never blocks on the network.
- **Untouchable:** `ctwa/instruments/` and `keithley*_driver.py`.
- **Commits:** messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Interfaces (Plans 3–5 rely on these exact names)
- **`ctwa/results/columns.py`:**
  - `LIST_COLUMNS: tuple[str, ...]` (= the webapp's list columns in `lib/analysisColumns.ts`, no blob columns);
  - `COLUMNS: dict[str, ColumnInfo]` with `ColumnInfo(name, label, unit, numeric, editable)`, matching the webapp's column metadata.
- **`ctwa/results/helpers.py`**, each a port of the webapp function of the same purpose:
  - `format_alpha(v: float | None) -> str` (×1e6, JS `toPrecision(4)`, "—" for None/non-finite);
  - `parse_test_date(s: str | None) -> date | None` (the webapp's parsing of `DD/MM/YYYY` and the variants it accepts);
  - `with_ln_validity(row: dict) -> dict` (the webapp's ln-term fix-up, new dict returned);
  - `run_label(row: dict) -> str`;
  - `row_matches(row: dict, query: str) -> bool` (Summary search semantics);
  - `material_color(name)` (re-export the ported one from `ctwa.analysis.references`; verify the hash and KNOWN map match the webapp).
- **`ctwa/results/store.py`**, class `ResultsStore(client: CloudClient)`, all blocking (call off the GUI thread):
  - `fetch_rows() -> list[dict]`: `select=LIST_COLUMNS`, order `created_at.desc`, paged by 1000 until a short page;
  - `fetch_graph_images(ids: list[int]) -> dict[int, str | None]`: chunks of ≤ 20 ids;
  - `fetch_presets() -> list[dict]` (`alpha_presets`);
  - `update_fields(id: int, changes: dict) -> dict`: sends ONLY the changed fields;
  - `delete(id: int) -> None`;
  - `insert(table: str, row: dict) -> dict`;
  - `delete_preset(id)` / `insert_preset(row)`.
  - Errors are the client's (`NotLoggedIn`, `Offline`, `ServerError`).
- **`ctwa/ui/results_loader.py`**, class `ResultsLoader(QObject)` (one shared instance created by MainWindow as `self.results_loader`):
  - signals:
    - `rows_changed(list)`, `presets_changed(list)`, `failed(str kind, str message)`, `graph_loaded(int id, object str_or_None)`;
    - per write: `write_done(str op, int token, object result)` / `write_failed(str op, int token, str kind, str message)`. `op` is "insert" | "update" | "delete" | "preset_insert" | "preset_delete"; `token` is the int each apply_* call returns, so callers can sequence writes.
  - methods:
    - `refresh()`, `rows() -> list[dict]` (cached), `presets()`, `request_graph(id)`;
    - `apply_update(id, changes) -> int`, `apply_delete(id) -> int`, `apply_insert(row) -> int`, `apply_preset_insert(row) -> int`, `apply_preset_delete(id) -> int`;
    - property `store` (the ResultsStore) for read-only use off the GUI thread.
  - Writes run off-thread one at a time in call order. After each success they emit `write_done` and then refresh (`rows_changed` / `presets_changed`). `NotLoggedIn` → `write_failed(op, token, "login", …)` and `failed("login", …)`.
  - The Analysis tab's SavePanel calls `loader.refresh()` after a successful save (one line in `app.py` wiring).

## Task 1: Foundation modules
**Files:** create `ctwa/results/__init__.py`, `columns.py`, `helpers.py`, `store.py`, `ctwa/ui/results_loader.py`, `tests/test_results_foundation.py`; modify `ctwa/app.py` (create one `ResultsLoader` next to the cloud services; SavePanel success → `loader.refresh()`).
- [ ] **Step 1: Failing tests.**
  - Helper outputs equal TS-pinned values (≥ 6 cases each, including edge cases: None, NaN, 0, negative, a date with 2-digit year, non-ASCII search).
  - `ResultsStore` sends the exact PostgREST queries and pages and chunks correctly (fake client).
  - `update_fields` sends only the changes.
  - `ResultsLoader` never runs a fetch on the GUI thread (tripwire), emits `rows_changed` after `refresh`, and maps `NotLoggedIn` to `failed("login", …)`.
- [ ] **Step 2: Implement.** Then: `QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m pytest tests/test_results_foundation.py -q` passes and `-m "not slow"` stays green.
- [ ] **Step 3: Commit.**
