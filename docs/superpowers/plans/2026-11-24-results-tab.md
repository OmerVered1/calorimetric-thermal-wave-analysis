# Results Tab (Plan 3 of the CTWA 2.0 build) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the CTWA app, a **Results** tab with the webapp's Summary, History and Compare pages: the same data, columns, editable fields, plots and numbers, so Omer no longer opens the webapp to look at, fix or compare saved analyses.

**Architecture:**
- **Qt-free logic first:** formatting, sorting, filtering, CSV, parameter and metric tables and the Compare guide extraction live in plain modules, each pinned to values produced by the webapp's own TypeScript.
- **One figure model, two views:** a parser turns a saved `graph_image` into plain dataclasses; `FigureView` draws them with pyqtgraph (History) and Compare reuses the parser for its overlay.
- **Pages:** three widgets (`SummaryTab`, `HistoryTab`, `CompareTab`) inside one `ResultsTab`. They read rows only from the shared `ResultsLoader` (Plan 2.5) and write only through its `apply_*` methods. The network is never touched from the GUI thread.
- **Isolation:** everything is new files under `ctwa/ui/results/`. `ctwa/app.py` is touched once, in the last task.

**Tech Stack:** PySide6, pyqtgraph, `json`/`base64`/`decimal` from the standard library. The webapp side uses a throwaway `npx tsx` script, never committed.

**Spec:** `docs/superpowers/specs/2026-11-24-ctwa-desktop-analysis-design.md`. Builds on `docs/superpowers/plans/2026-11-24-results-foundation.md` (`LIST_COLUMNS`, `COLUMNS`, `format_alpha`, `parse_test_date`, `with_ln_validity`, `run_label`, `row_matches`, `material_color`, `ResultsStore`, `ResultsLoader`) and Plan 2's `ctwa/analysis/lag_fit.describe_lag_model` and `ctwa/analysis/jsmath.js_round`. Webapp references: `app/summary/page.tsx`, `app/history/page.tsx`, `app/analyses-viewer/page.tsx`, `components/ui/RunLabel.tsx`, `lib/utils.ts`, `lib/i18n/en.ts` (English texts only; Hebrew and RTL are not ported). Inventory: `plan3-results-inventory.md` in the session scratchpad.

## Global Constraints

- **Branch and worktree:** `plan3-results`, in its own git worktree, branched from `desktop-analysis` after Plan 2.5 (Results Foundation) has landed. Plans 4 (Calibration) and 5 (Statistics) run in parallel on their own branches. No push, no tags, no commits to `desktop-analysis` or `master`.
- **Merge-friendliness:** all new code is in new modules under `ctwa/ui/results/` and `tests/test_results_*.py`. `ctwa/app.py` changes only in Task 14, inside one block opened by `# --- Results tab (Plan 3) ---` and closed by `# --- end Results tab (Plan 3) ---`. The `keithley_suite.spec` `hiddenimports` additions go in that same task. No other existing file is edited.
- **Names:** use the Foundation's names exactly (`ResultsLoader`, `rows_changed`, `failed`, `graph_loaded`, `request_graph`, `apply_update`, `apply_delete`, `with_ln_validity`, `format_alpha`, `COLUMNS`, `material_color`, ...). Do not re-specify or copy them.
- **Parity:** same data, same formatting, same columns and editable fields, same texts as the webapp (`lib/i18n/en.ts`).
  - Summary edits send only the changed fields (the webapp sends the whole row; this is a deliberate improvement).
  - Deletes ask for confirmation and offer the 6-second Undo, as the webapp's toast does.
  - Compare takes at most 4 runs.
  - Two deliberate output differences from the webapp's CSV: a UTF-8 BOM (Excel then shows α, Δ, ω correctly) and quoting of a cell only when it contains a comma, quote or newline. Everything else in the CSV is byte-identical.
- **TS-pinned tests:** every webapp calculation that is not already ported gets a unit test whose expected values come from running the TypeScript. Write a throwaway `npx tsx` script in the webapp checkout (or the scratchpad), import the real function (copy it verbatim if the page does not export it), print JSON, and paste the output as literals into the test. The script is never committed. The values written in this plan are the ones that are certain from the JS specification; the implementer re-checks them with the script and adds the other cases it lists.
- **GUI thread:** never blocks on the network. Widgets get rows from `loader.rows()` and graphs from `loader.request_graph`/`graph_loaded`. Tests use a `FakeLoader` (a `QObject` with the Foundation's signals and methods that records calls); no real network and no real `CloudClient`.
- **Python 3.9** (`from __future__ import annotations`; no `X | Y` annotations at runtime). Tests run with `QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m pytest`. Use the QApplication fixture pattern of `tests/test_runs_tab.py`.
- **Untouchable:** `ctwa/instruments/` and `keithley*_driver.py`. `tests/test_equivalence_with_original_windows.py` stays green.
- **Look:** colours, fonts and plot styling come from `ctwa/theme.py` (`theme.P`, `style_plot`, `configure_pyqtgraph`, `swatch`, `ui_font`). The stored-figure colours (`#1F5BB0`, `#E4572E`, ...) are data and are drawn as saved.
- **Commits:** messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

Each is pinned by a test in the task named.

1. **A slow graph arrives after Omer clicked another row.** History would show row A's plot under row B's numbers. A late `graph_loaded` for a row that is no longer selected is ignored. (Task 9)
2. **A background refresh lands while a Summary cell is being edited.** The editor must stay open with what was typed, on the same row, and saving must still send only the changes. (Task 8)
3. **Delete timing.** The row disappears at once, Undo inside the 6 s sends nothing, a failed delete brings the row back with the error, and quitting the app sends pending deletes immediately (the webapp does this when the page closes). (Task 10)
4. **A write fails (offline, or login refused).** The edit stays open with the message and the typed value, or the deleted row returns. Nothing is silently lost and the login prompt is asked for once. (Tasks 8, 10, 13)
5. **A stored figure that is not the usual one:** broken JSON, an image with line breaks in its base64, a bar trace, `{}`, shapes on `y2` or in paper units. History and Compare must show the fallback or a note, never an exception. (Tasks 3, 5, 12)

---

### Task 1: Display helpers that match JavaScript (`fmt.py`)

**Files:**
- Create: `ctwa/ui/results/__init__.py` (empty), `ctwa/ui/results/fmt.py`, `tests/test_results_fmt.py`

**Interfaces:**
- Consumes: `ctwa.analysis.jsmath.js_round`, `js_to_fixed`, `js_to_precision`, `js_number_to_string` (already ported and node-pinned in Plan 1 — **reuse them, do not re-implement**; if a case below disagrees with them, the existing pinned implementation wins and the test is corrected), `ctwa.analysis.diffusivity._js_number` (JS `Number(string)`; promote it to `jsmath.js_number` and import it from there in both places), Foundation `parse_test_date`, `run_label`, `row_matches`.
- Produces (all pure):
  - (controller note: `js_to_fixed`, `js_to_precision`, `js_str`/`js_number_to_string` and `js_number` come from `ctwa.analysis.jsmath`; their test cases below stay as regression checks against the existing functions);
  - `compare_cells(a, b, key: str) -> float`;
  - `next_sort(state: tuple, key: str) -> tuple` where state is `(key | None, "asc" | "desc" | None)`;
  - `run_label_text(row: dict) -> str`;
  - `label_of(row: dict) -> str`;
  - `matches_fields(row: dict, query: str, fields: tuple) -> bool`;
  - `HISTORY_SEARCH_FIELDS = ("id","model_name","test_date","analysis_mode","temperature_c")`.

- [ ] **Step 1: Write the failing tests** (`tests/test_results_fmt.py`):
  - `js_to_fixed`: `(2.5,0)` is `"3"`, `(-2.5,0)` is `"-3"` (ties go away from zero, unlike Python's `round`), `(1.005,2)` is `"1.00"`, `(-0.0,2)` is `"0.00"`, `(-0.001,2)` is `"-0.00"`, `(1234.5678,1)` is `"1234.6"`, `(nan,2)` is `"NaN"`, `(inf,1)` is `"Infinity"`, `(1e21,2)` is `"1e+21"`.
  - `js_to_precision(·,4)`: `0.0085` is `"0.008500"`, `0` is `"0.000"`, `12345.6` is `"1.235e+4"`, `1.234e-7` is `"1.234e-7"`, `0.000001234` is `"0.000001234"`, `8.5123` is `"8.512"`. Exponent below -6 or at least `p` switches to exponential form, as in JS.
  - `compare_cells`:
    - `test_date`: `"01/02/2026"` against `"15/01/2026"` is positive; an unparsable date counts as 1970.
    - `None` against `5` is `-5` (`Number(null)` is 0).
    - `""` against `5` is `-5`.
    - `" 7 "` against `5` is `2`.
    - `"12abc"` against `"13"` falls to string comparison.
    - `("a","B")`, `("a","A")` negative and `("A","a")`, `("Abs","abs")` positive: the `localeCompare` order, lower case first on a tie.
  - `next_sort`: `(None,None)` + `"id"` gives `("id","asc")`; then `("id","desc")`; then `(None,None)`; `("id","desc")` + `"x"` gives `("x","asc")`.
  - `run_label_text({"model_name":"Stainless Steel","temperature_c":766.0,"period_t":600.5,"id":254})` is `"Stainless Steel · 766 °C · 601 s · #254"`; with `temperature_c` and `period_t` None it is `"Stainless Steel · #254"`.
  - `label_of` for model `Alumina`, date `17/11/2026`, T 766, gas `Ar`, mode `AutoFit`, A₁ 12.34, period 600.4, id 254 is `"Alumina | 17/11/2026 | 766°C | Ar | AutoFit | A₁=12.3mW | T=600s #254"`; a None gas, temperature and A₁ leave their parts out.
  - `matches_fields` strips `#`, splits on whitespace, needs every term as a lowercase substring of some field: `"steel 600"` matches a row, `"#254"` matches id 254, `"zzz"` does not; `Ä` in the query matches `ä` in the row (non-ASCII).
  - At least 6 of the above are cross-checked against the TS script.
- [ ] **Step 2: Run and see it fail.** `QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m pytest tests/test_results_fmt.py -q`. Expected: FAIL, the module is missing.
- [ ] **Step 3: Implement.**
  - `js_to_fixed`: build from `decimal.Decimal(v)` (the exact binary value) quantized with `ROUND_HALF_UP` applied to the absolute value, sign re-applied unless the result is `-0` from a `-0.0` input. Values with `abs(v) >= 1e21` use `js_str`.
  - `js_to_precision`: decide the exponent from the same exact decimal, then format fixed or exponential (`e+4`, `e-7`, no zero padding of the exponent).
  - `compare_cells` follows the TSX function line for line. `js_number` trims, maps `""` to 0, accepts decimal/exponent/`Infinity` forms only (no `nan`, no underscores), else NaN. String comparison key is `(s.casefold(), swapcase(s))` so lower case sorts first.
- [ ] **Step 4: Run and see it pass.** Same command.
- [ ] **Step 5: Commit.**

### Task 2: Summary logic (`summary_logic.py`)

**Files:**
- Create: `ctwa/ui/results/summary_logic.py`, `tests/test_results_summary_logic.py`

**Interfaces:**
- Consumes: Task 1 helpers, Foundation `COLUMNS`, `format_alpha`, `with_ln_validity`, `parse_test_date`, `row_matches`, `describe_lag_model`.
- Produces:
  - `SummaryCol(key, label, numeric: bool, editable: bool)` and `SUMMARY_COLS: list[SummaryCol]`: the 27 columns of `DISPLAY_COLS`, same order and labels (`ID, Model, Date, T (°C), Atmosphere, Mode, r₁ (mm), r₂ (mm), A₁ (mW), A₂ (mW), Src Period (s), Resp Period (s), Src f (Hz), Resp f (Hz), ω (rad/s), Δt (s), φ (rad), ln term, α comb (raw), α phase (raw), Cal, Lag (s), Cal source, Refs, Net Δt (s), α comb (cal), α phase (cal)`, 27 in all). Editable is false only for `id`, `calibration_model`, `calibration_ref_ids`. Text (left-aligned) keys are `model_name, test_date, gas_atmosphere, analysis_mode, calibration_model, calibration_ref_ids, use_calibration`.
  - `format_cell(key: str, row: dict) -> str`.
  - `PRESETS: dict[str, list[str] | None]` (`"key"`, `"cal"`, `"all"`, the same key lists as the TSX) and `ALWAYS_SHOWN = {"id","model_name"}`; `hidden_for_preset(name) -> list[str]`; `preset_of(hidden: set) -> str` (`"custom"` when none fits).
  - `base_order(rows: list[dict]) -> list[dict]`: stable sort by `parse_test_date` descending, `None` counting as 1970-01-01, then each row through `with_ln_validity`.
  - `filter_rows(rows, *, model="All", mode="All", cal="All", ids: set | None = None, query="") -> list[dict]`; `cal` is one of `"All"`, `"Calibrated Only"`, `"Non-Calibrated Only"`.
  - `summary_stats(rows) -> dict` with `total`, `models`, `avg_raw`, `avg_cal` (strings).
  - `csv_text(rows) -> str`.
  - `NUMERIC_EDIT_KEYS` (the TSX `NUMERIC_KEYS` plus `period_t_resp`, `frequency_f_resp`), `parse_float_js(text) -> float | None`, `build_update(stored: dict, edits: dict) -> dict`.

- [ ] **Step 1: Write the failing tests:**
  - `format_cell`:
    - `temperature_c` None gives `"25.0"`, 766 gives `"766.0"`.
    - `r1_mm` 6.72 gives `"6.72"`, None gives `"0.00"` (the TSX `Number(null)` quirk).
    - `alpha_phase_raw` 8.5123e-6 gives `"8.512"`, None and 0 give `"—"`.
    - `use_calibration` True gives `"✓"`, False gives `"✗"`.
    - `calibration_ref_ids` `"12,15"` gives `"2 refs"`, `"12"` gives `"1 ref"`, `""` and None give `"—"`.
    - `calibration_model` None gives `"—"`.
    - `period_t_resp` None gives `"—"`, `frequency_f` 0.001666 gives `"0.001666"`.
  - `preset_of`: after `hidden_for_preset("key")` it returns `"key"`; hiding one more column gives `"custom"`.
  - `base_order`: rows dated `"01/02/2026"`, `"15/01/2026"`, `"not a date"` come out in that order; two rows with the same date keep their input order; a row with `ln_term` 0.4 and A₁/A₂ and radii giving a negative log has `alpha_combined_raw` None while the input dict is unchanged.
  - `filter_rows`: model/mode filters are exact; `"Calibrated Only"` keeps `use_calibration` true; `ids={2,3}` keeps those; a query `"steel 766"` goes through `row_matches` (AND of terms); all combined.
  - `summary_stats` for combined-raw values `[8e-6, 9e-6, 0, None]` (4 rows, 2 models) gives `total 4`, `models 2`, `avg_raw "8.500 mm²/s"`; with no positive values `avg_cal` is `"—"`.
  - `csv_text`: the header is the 27 labels joined by `,`; a row's cells equal `format_cell` for the formatted columns and the raw value (`""` for None) for the others; lines end in `\n`; a model name `Foam, A` is quoted `"Foam, A"`; all 27 columns appear whatever the visible set is. Pinned against the TSX `downloadCSV` run on two rows.
  - `parse_float_js`: `"1e-6"` is `1e-6`, `"12abc"` is `12.0`, `".5"` is `0.5`, `""`, `"abc"`, `"Infinity"` are None.
  - `build_update(stored, edits)`: edits are the editor's strings. Unchanged values (`"766"` against stored 766.0, and `"8.5e-6"` against stored 8.5e-6) are omitted; a changed number is sent parsed; an emptied numeric field is `None`; `use_calibration` as a bool; `analysis_mode` and text fields as strings; `id`, `created_at`, `graph_image`, `extra_data` never appear; no edits gives `{}`.
- [ ] **Step 2: Run and see it fail.**
- [ ] **Step 3: Implement** as literal ports of the TSX (`DISPLAY_COLS`, `PRESETS`, filters, stats, `downloadCSV`, the `cleaned` block). `build_update` compares parsed new against stored with `==` after `parse_float_js`, so `"766"` equals 766.0. Comparison of text uses the stored value `""` when None.
- [ ] **Step 4: Run and see it pass.**
- [ ] **Step 5: Commit.**

### Task 3: Stored figure model (`figure_model.py`)

**Files:**
- Create: `ctwa/ui/results/figure_model.py`, `tests/test_results_figure_model.py`, `tests/data/results/` fixtures (`fig_web.json`: a figure with the shape of the webapp's saved one: two traces, 2 dashed means, 4 dotted levels, 3 dashdot paper lines, 3 annotations, copied from one real saved row with the arrays cut to 12 points; `fig_old_colors.json`)

**Interfaces:**
- Produces:
  - dataclasses `Trace(name, x, y, color, width, dash, yaxis)`, `Shape(x0, y0, x1, y1, xref, yref, color, width, dash)`, `Annotation(x, y, text, xref, yref, xanchor, color, size, bgcolor, mono)`, `StoredFigure(title, x_title, y_title, y2_title, traces, shapes, annotations, horizontal_legend, skipped: list[str])`, `StoredImage(data: bytes, fmt: str)`.
  - `parse_graph(raw: str | None) -> StoredFigure | StoredImage | None` (None = nothing drawable, show the bar fallback).
  - `parse_color(s: str) -> tuple` giving `(r, g, b, a)` with a 0-255 alpha, for `#rgb`, `#rrggbb`, `rgb()` and `rgba()`; unknown gives `(0,0,0,255)`.
  - `bar_values(row: dict) -> list[tuple]` of `(label, value_mm2s, color)`.
  - `strip_tags(text) -> str` (removes `<b>`, `<br>` etc.).

- [ ] **Step 1: Write the failing tests:**
  - `fig_web.json` text: 2 traces, `Source` on `y`, `Response` on `y2` with colours `#1F5BB0`, `#E4572E` and width 2; 2 dashed shapes, 4 dotted ones (2 `#27ae60` on y, 2 `#f39c12` on `y2`), 3 `dashdot` with `yref == "paper"`, `y0 == 0`, `y1 == 1`; 3 annotations, the level ones with `mono` true and `bgcolor == (255,255,255,204)`; `x_title "Time (s)"`, `y_title "Source Power (mW)"`, `y2_title "Response Power (mW)"`, `horizontal_legend` true.
  - The title `"<b>Stable Zone Analysis — Δt = 105.20s</b>"` becomes `"Stable Zone Analysis — Δt = 105.20s"`; a title given as `{"text": ...}` works the same.
  - A base64 PNG (`iVBOR...`) and a JPEG (`/9j/...`), each split with `\n` every 76 characters, give `StoredImage` with `fmt` `"PNG"` / `"JPEG"` and the decoded bytes. Base64 that does not decode, or decodes to the wrong magic bytes, gives None.
  - `None`, `""`, `"abc"`, `"{"`, `"{}"`, `{"data":[]}` and `{"data":"x"}` give None. A bar trace plus the two scatter traces gives a figure with `skipped == ["bar"]`; a figure with only a bar trace gives None. Dash names `longdash`, `sysdash` map to `dash`, an unknown name to `solid`.
  - `parse_color("rgba(255,255,255,.8)") == (255,255,255,204)`, `parse_color("#3498db") == (52,152,219,255)`, `parse_color("#fff") == (255,255,255,255)`.
  - `bar_values` for raw comb 8.5e-6, raw phase 9e-6, `use_calibration` true, cal comb 8e-6, cal phase None gives `[("α comb (raw)",8.5,"#3498db"),("α phase (raw)",9.0,"#e74c3c"),("α comb (cal)",8.0,"#2ecc71")]`; with `use_calibration` false the cal bars are dropped; all absent gives `[]`.
- [ ] **Step 2: Run and see it fail.**
- [ ] **Step 3: Implement.** A trace is drawable when `type` is `scatter` (or missing) and `x` and `y` are equal-length lists of numbers; other types are recorded in `skipped` by their type name. `None` entries in `x`/`y` become NaN. Never raise: any exception inside `parse_graph` returns None.
- [ ] **Step 4: Run and see it pass.**
- [ ] **Step 5: Commit.**

### Task 4: Compare logic (`compare_logic.py`)

**Files:**
- Create: `ctwa/ui/results/compare_logic.py`, `tests/test_results_compare_logic.py`, `tests/data/results/overlay_fixture.json` (a stored figure with 8-point `Source`/`Response` traces, two source levels, two response levels, two source markers, one response marker)

**Interfaces:**
- Consumes: Task 1 (`js_to_fixed`, `js_to_precision`, `label_of`, `run_label_text`), Task 3 `parse_graph`, `StoredFigure`, Foundation `format_alpha`.
- Produces:
  - `MAX_RUNS = 4`, `COMPARE_COLORS` (the TSX `COLORS` list of 10), `run_colors(i) -> (source_hex, response_hex)` = `COMPARE_COLORS[2i % 10]`, `COMPARE_COLORS[(2i+1) % 10]`.
  - `PARAM_ROWS: list[tuple[str, Callable]]` (28 rows, labels and formats of the TSX), `param_value(label, row) -> str`, `differing_rows(rows) -> set[str]` (empty with fewer than 2 rows).
  - `METRICS: list[tuple[key, label, Callable]]` (17), `metric_value(key, row) -> float | None`, `metric_text(v) -> str`.
  - `OverlayOptions(signal: "source"|"response"|"both" = "both", align=True, norm_amp=False, norm_time=False, guides=True)`.
  - `OverlayTrace(name, x, y, color, dash)` (`dash` is `"solid"` or `"dash"`), `OverlayLine(x0, x1, y0, y1, yref, color, dash, label)` (`dash` is `"dot"` or `"dashdot"`; `yref` is `"y"` or `"paper"`; `label` may be None), `OverlayRun(traces, lines, box_text)`.
  - `overlay_run(row: dict, raw_graph: str | None, index: int, opts: OverlayOptions) -> OverlayRun | None` (None when there is no JSON figure or no `Source`/`Response` trace: the page lists the run in the "no stored waveform" note).
  - `guide_levels(fig) -> (src_levels, resp_levels, src_markers, resp_markers)`.

- [ ] **Step 1: Write the failing tests** (expected values from the TSX `useMemo` at `analyses-viewer/page.tsx` ~L185-300, run on `overlay_fixture.json` and a row with `raw_lag_dt` 105.2, `amplitude_a1` 12.34, `amplitude_a2` 5.67):
  - `param_value` for each of the 28 labels on one full row and one row of Nones equals the TS strings (for example `"Temperature (°C)"` None gives `"—"`, `"A₁ (mW)"` None gives `"—"`, `"Calibration"` false gives `"✗"`, `"α Phase raw (mm²/s)"` 0 gives `"—"`).
  - `metric_value("a1_a2", row)` is `12.34/5.67`, and None when A₂ is 0; `"alpha_phase_raw"` of 8.5e-6 is `8.5`, of 0 is None; `metric_text(1234.5)` is `"1235"` (`toFixed(0)`), `metric_text(8.5123)` is `"8.512"`, `metric_text(None)` is `"—"`, `metric_text(-1500)` is `"-1500"`.
  - `differing_rows` with two rows that differ only in temperature and in `α Phase raw` returns exactly those two labels; with one row it is empty; two rows with the same `Model` do not list `Model`.
  - `overlay_run` with defaults: traces named `"<label_of(row)> — Source"` and `"<label_of(row)> — Response"`; x shifted so each run starts at 0; Source solid in `run_colors(i)[0]`, Response dash in `run_colors(i)[1]`.
  - `norm_amp`: every y is `(y-min)/(max-min)`; a constant trace gives all 0; guide lines are dropped. `norm_time`: x is `(x-x0)/span` and wins over `align`; `align=False` leaves x as stored.
  - `signal="source"` keeps only the Source trace and only the source guides; `"response"` the reverse.
  - Guides: levels `[12.0, 3.0]` become `OverlayLine` dotted at y 12.0 and 3.0, from the run's left x to its right x, with labels `"  A₁ peak (12.0 mW)"` and `"  A₁ trough (3.0 mW)"` for run 0 and None for run 1; the response levels use `A₂`. Markers become dash-dot lines with `yref="paper"`, `y0=0`, `y1=1`, labelled `"Src peak"` (first marker only) and `"Resp peak (Δt=105s)"` for run 0 only. Colours are the run's own, never the stored ones. Shapes whose colour is not in the TSX's `SRC_GUIDE_COLORS` / `RESP_GUIDE_COLORS` sets, or that are not `line`, are ignored.
  - `box_text` is `"<model> #<id>:  Δt=105 s · A₁=12.3 · A₂=5.7 mW"` (two spaces after the colon, as in the TSX); with Nones the parts are `"—"`.
  - A raw graph that is an image, broken JSON, None or a figure with no Source/Response trace gives None.
- [ ] **Step 2: Run and see it fail.**
- [ ] **Step 3: Implement** as a literal port of the TSX blocks, same order of operations. The ignored `yaxis: "y2"` of the stored response trace stays ignored (one y axis).
- [ ] **Step 4: Run and see it pass.**
- [ ] **Step 5: Commit.**

### Task 5: Figure view (`figure_view.py`)

**Files:**
- Create: `ctwa/ui/results/figure_view.py`, `tests/test_results_figure_view.py`

**Interfaces:**
- Consumes: Task 3 (`StoredFigure`, `StoredImage`, `parse_graph`, `bar_values`, `parse_color`), `ctwa.theme`.
- Produces `class FigureView(QWidget)`:
  - `show_graph(raw: str | None, row: dict) -> None` (parses and draws; `row` feeds the bar fallback);
  - `show_loading() -> None`, `clear() -> None`;
  - inspection for tests and screenshots: `mode() -> str` (`"figure"`, `"image"`, `"bars"`, `"loading"`, `"empty"`), `curve_count(second_axis: bool = False) -> int`, `line_items() -> list[tuple]` of `(x0, y0, x1, y1, dash, axis)`, `annotation_texts() -> list[str]`, `legend_labels() -> list[str]`, `note() -> str`, `bar_labels() -> list[str]`, `axis_titles() -> tuple`.
- Module function `draw_stored_figure(plot_item, fig: StoredFigure) -> FigureHandles` is reused by nobody else (Compare draws its own overlay) but is kept separate for testing.

- [ ] **Step 1: Write the failing offscreen tests:**
  - With the `fig_web.json` text: `mode() == "figure"`, `curve_count() == 1`, `curve_count(True) == 1`, `legend_labels() == ["Source", "Response"]`, axis titles `("Time (s)", "Source Power (mW)", "Response Power (mW)")`.
  - Shapes: 6 horizontal lines (2 dashed means, 4 dotted levels) of which 2 dashed and 2 dotted on the second axis; 3 dash-dot lines whose `y0`,`y1` are `0` and `1` in paper units and which still span the full plot height after the view is resized or zoomed (assert their on-screen height equals the view box height after `resize` and `setYRange`).
  - Annotations: the 3 text labels are present with their texts; the level ones use a monospace font and a white 80 % background (the item's `fill` colour alpha is 204).
  - The legend is laid out horizontally (one row; assert the legend item's `columnCount`/layout positions share one y).
  - `show_graph` with a PNG and a JPEG (`fig_*` base64 with line breaks): `mode() == "image"`; the label shows a non-null pixmap whose size equals the image size scaled to fit.
  - `show_graph(None, row)` and `show_graph("{}", row)`, a broken string, a bar-only figure: `mode() == "bars"`, `bar_labels()` equal `bar_values(row)` labels; a row with no α values gives `mode() == "empty"` and a note `"No stored graph"`.
  - A figure with an extra bar trace: `mode() == "figure"`, `note() == "Not drawn: bar"`.
  - A figure whose shapes reference `y2` and an `xref` of `paper` does not raise.
  - Switching figure → bars → figure leaves exactly one set of items in the plot (no leftover curves or lines).
  - The old-colour fixture (`#3498db`/`#e74c3c`) is drawn in those colours.
- [ ] **Step 2: Run and see it fail.**
- [ ] **Step 3: Implement.**
  - A `pg.PlotItem` with a second `pg.ViewBox` linked on x for `y2` (the right axis is shown only when a trace or shape uses it).
  - Horizontal and sloped shapes are two-point `PlotCurveItem`s with a `Qt.DashLine`/`DotLine`/`DashDotLine` pen. Shapes with `yref == "paper"` or annotations with a paper coordinate are `PaperItem`s: they are repositioned on every `sigRangeChanged` and `sigResized` of the view box (`y = bottom + frac * (top - bottom)`).
  - Annotations are `pg.TextItem` with the stored font colour, size, `xanchor` and background fill.
  - Images: `QPixmap.loadFromData`, scaled to the widget, in a `QLabel`. Bar fallback: `pg.BarGraphItem` with text items of `js_to_precision(v, 4)`, title `"Thermal Diffusivity α"`, y title `"α (mm²/s)"`.
  - `show_graph` wraps parsing and drawing in one try/except that falls back to the bars (and sets `note()`), so a draw error never reaches the user as a traceback. Style via `theme.style_plot`.
- [ ] **Step 4: Run and see it pass.**
- [ ] **Step 5: Commit.**

### Task 6: Summary table model (`summary_model.py`)

**Files:**
- Create: `ctwa/ui/results/summary_model.py`, `tests/test_results_summary_model.py`

**Interfaces:**
- Consumes: Task 1 `compare_cells`, `next_sort`; Task 2 `SUMMARY_COLS`, `format_cell`, `base_order`, `filter_rows`; Foundation `material_color`.
- Produces:
  - `class SummaryModel(QAbstractTableModel)`: column 0 is a check column, columns 1..27 are `SUMMARY_COLS`. Methods: `set_rows(rows: list[dict])` (stores the stored copies and the `base_order` display copies), `row_by_id(id) -> dict | None` (the stored row), `display_row(id) -> dict`, `selected_ids() -> set[int]` (survives `set_rows` and filtering; ids that vanished are dropped), `set_selected(id, on)`, `set_all_shown(on)`, `pending_hide(ids: set)`.
  - Roles: DisplayRole = `format_cell` of the display row; `EditRole` = the stored value; `CheckStateRole` on column 0; `DecorationRole` on Model = a colour dot of `material_color(model_name)`; `TextAlignmentRole` right for numeric, left for text columns.
  - `class SummaryProxy(QSortFilterProxyModel)`: `set_filters(model="All", mode="All", cal="All", ids=None, query="")`, `set_sort(key, direction)` (3-state: none restores the model's base order), `shown_ids() -> list[int]`, `shown_rows() -> list[dict]` (display rows in sorted order, for stats and CSV of "filtered"), `distinct_models()`, `distinct_modes()`.

- [ ] **Step 1: Write the failing tests:**
  - 3 rows with ids 1 to 3 give 28 columns; `data` of the α phase raw cell of a row with `8.5123e-6` is `"8.512"`, of its `EditRole` is `8.5123e-06`.
  - Base order: rows come out by date descending (as Task 2).
  - A row that needs the ln fix shows `"—"` in `α comb (raw)` while `EditRole` still returns the stored value (display only, never written back).
  - Sorting by `period_t`: asc, desc, none give the three orders, the last being base order; a column with a None sorts as 0 (`compare_cells`).
  - Filters: model `"Stainless Steel"` and `cal "Calibrated Only"` reduce `rowCount`; the selection of a row that gets filtered out is kept (`selected_ids()` unchanged) and `set_all_shown(True)` selects only the shown rows.
  - `set_rows` with a refreshed list keeps the selection of ids that still exist and drops the missing ones.
  - `pending_hide({2})` removes row 2 from the proxy without losing it from the model, and an empty set brings it back.
  - `distinct_models()` is the sorted distinct model names of the loaded rows.
- [ ] **Step 2: Run and see it fail.**
- [ ] **Step 3: Implement.** `lessThan` is never used for the sort: the proxy sorts by its own `(key, dir)` via `compare_cells` on the stored values, so the result equals the webapp's. `set_sort` invalidates the proxy.
- [ ] **Step 4: Run and see it pass.**
- [ ] **Step 5: Commit.**

### Task 7: Summary tab view (`summary_tab.py`)

**Files:**
- Create: `ctwa/ui/results/summary_tab.py`, `tests/test_results_summary_tab.py`

**Interfaces:**
- Consumes: Task 6 model and proxy, Task 2 `summary_stats`, `csv_text`, `PRESETS`, `hidden_for_preset`, `preset_of`; Foundation `ResultsLoader` (signals `rows_changed`, `failed`; `rows()`, `refresh()`).
- Produces `class SummaryTab(QWidget)`, `SummaryTab(loader, settings: QSettings | None = None, parent=None)`:
  - signals `compare_requested(list)` (ids, at most 4), `message(str)`;
  - methods `set_search(text)`, `set_id_filter(ids: set | None)`, `selected_ids() -> list[int]`, `export_csv(path: str, selected_only: bool = False) -> int` (rows written), `shown_count() -> int`.
- **Layout (texts from `en.ts`):** title `Results Summary`; four stat cards `Total Analyses`, `Unique Models`, `Avg α (raw)`, `Avg α (cal)`, with the caption `Statistics for the {n} analyses shown (of {total}).` while filtered; toolbar with search (`Search name, date, mode, °C or #id`), combos `Filter by Model`, `Filter by Mode`, `Filter by Calibration` (`All`, `Calibrated Only`, `Non-Calibrated Only`), the `Column set` segmented control (`Key results`, `Calibration`, `Everything`, none selected when custom), a `Columns` menu (check list of the 25 columns without ID and Model, plus `Show all columns`), a density toggle (`Compact rows`, `Comfortable rows`), `Download CSV`; a line `Showing x of y results · Double-click a cell to edit · Enter saves · Esc cancels`; a chip `{n} runs from a link` with a clear button when an id filter is set; the table; and a selection bar (visible when something is selected): `n analyses selected`, `Compare` (disabled with the tooltip `Compare up to 4 at a time` when more than 4), `Download CSV` of the selection (default file name `angstrom_results_selected.csv`; the toolbar one is `angstrom_results_summary.csv`), `Clear`.
- Hidden columns and density persist in QSettings (`results/summary/hidden` as a JSON list, `results/summary/density`).

- [ ] **Step 1: Write the failing offscreen tests** (FakeLoader with 3 rows):
  - On `rows_changed` the stat cards read `3`, `2`, `8.500 mm²/s` style values (equal to `summary_stats`); typing `steel` in search changes them and shows the caption with `n` and `total`.
  - Column presets: clicking `Key results` hides exactly `hidden_for_preset("key")` (ID and Model stay); the segmented control shows none selected after unchecking one column in the menu; `Everything` shows all 27. A new `SummaryTab` on the same QSettings restores the hidden set and the density.
  - Select all shown with a filter active selects only shown rows; with 5 selected `Compare` is disabled, with 4 it emits `compare_requested` with the 4 ids in table order.
  - `export_csv(tmp)` with a filter on writes only the filtered rows, in the base order (not the sorted order), all 27 columns, starting with the BOM; `selected_only=True` writes the selected rows; the return value is the row count.
  - `set_id_filter({1,3})` shows the chip `2 runs from a link` and 2 rows; its clear button restores all rows; `set_search("steel")` pre-fills the search box.
  - A `failed("offline", "no route")` shows the banner `Can't reach the database: no route` with a Retry button that calls `loader.refresh()`; rows already shown stay.
  - Before the first `rows_changed`, a loading label `Loading…` shows; with zero rows and no filter the text `No data` shows, with a filter that matches nothing it shows `No data` as well.
- [ ] **Step 2: Run and see it fail.**
- [ ] **Step 3: Implement.** Sticky left columns are the frozen first three columns (check, ID, Model) via a second `QTableView` overlay or `setFirstColumnFrozen`-style approach, whichever the implementer proves works with horizontal scrolling in an offscreen test; the check, ID and Model columns must stay visible when scrolled right. Row height `theme.ROW_HEIGHT` (compact) or `theme.ROW_HEIGHT + 10`.
- [ ] **Step 4: Run and see it pass.**
- [ ] **Step 5: Commit.**

### Task 8: Summary inline editing (`summary_edit.py`)

**Files:**
- Create: `ctwa/ui/results/summary_edit.py`, `tests/test_results_summary_edit.py`
- Modify: `ctwa/ui/results/summary_tab.py` (install the delegate and the edit buttons; this file is new in this plan, so there is no merge risk)

**Interfaces:**
- Consumes: Task 2 `build_update`, `SUMMARY_COLS`, `ANALYSIS_MODES`; Foundation `loader.apply_update(id, changes)`, `rows_changed`, `failed`.
- Produces:
  - `ANALYSIS_MODES = ["Auto", "AutoHybrid", "AutoFFT", "AutoFit", "Manual"]`;
  - `class EditSession`: `row_id`, `values: dict[str, str | bool]` (what the editor holds), `focus_key`;
  - `class SummaryDelegate(QStyledItemDelegate)`: a `QCheckBox` for `use_calibration`, an editable `QComboBox` for `analysis_mode` (the five modes plus the current value when it is another), a `QLineEdit` for everything else, always showing the stored raw value (so α is edited in m²/s, the database unit);
  - `SummaryTab` gains `begin_edit(row_id, focus_key=None)`, `commit_edit() -> dict` (the changes sent), `cancel_edit()`, `editing_id() -> int | None`, signal `login_needed()`.
- **Behaviour:**
  - One row is edited at a time; double-clicking an editable cell or pressing the row's `Edit` button starts it; `Enter` saves, `Esc` cancels; `Save` and `Cancel` buttons replace `Edit` while editing.
  - Starting another edit while one is open cancels nothing silently: it asks `Discard changes to #n?` only when the open row has changes.
  - Save sends `loader.apply_update(id, build_update(stored, session.values))`; with no changes it just closes the editor. On success (`rows_changed`) the editor closes and the message `Saved #<id>` is emitted; on `failed` the editor stays open and the message is `Could not save #<id>: <message>`.

- [ ] **Step 1: Write the failing offscreen tests:**
  - Double-clicking the `T (°C)` cell opens a line edit holding `"766.0"`'s stored value `766`; typing `770` and pressing Enter calls `apply_update(id, {"temperature_c": 770.0})` exactly once and nothing else (a `FakeLoader` records it). Editing an α cell shows the stored `8.5123e-06` text, not `8.512`.
  - `ID`, `Cal source` and `Refs` cells never open an editor.
  - `use_calibration` is a checkbox; toggling it sends `{"use_calibration": False}`. The `Mode` editor lists `Auto, AutoHybrid, AutoFFT, AutoFit, Manual`, plus a stored value `AutoHybrid2` if the row has one; choosing `Manual` sends `{"analysis_mode": "Manual"}`.
  - Emptying `A₁ (mW)` sends `{"amplitude_a1": None}`; typing `abc` sends `None` too (the webapp's `parseFloat` NaN gives null); `period_t_resp` is parsed as a number.
  - A row whose display is ln-corrected (Task 6) saves only the edited field, never the corrected `alpha_combined_raw` (parity).
  - Esc cancels and sends nothing. Pressing Enter without a change sends nothing.
  - **Review Focus 2:** while editing row 2 with the typed text `771`, the loader emits `rows_changed` with a new list in which a row above was deleted and row 2 moved: the editor is still open on row 2 (by id), still holds `771`, and saving sends `{"temperature_c": 771.0}`. If row 2 is gone from the new list the editor closes and the message `#2 was removed elsewhere` is shown.
  - **Review Focus 4:** `failed("offline", "no route")` after Save keeps the editor open with `771` and shows `Could not save #2: no route`; `failed("login", ...)` emits `login_needed` once and keeps the editor open.
  - Two quick Enter presses send one update.
- [ ] **Step 2: Run and see it fail.**
- [ ] **Step 3: Implement.** The editor state lives in `EditSession`, not in the model, so a refresh cannot disturb it; the delegate reads `session.values`. While a save is pending the row's editor is disabled.
- [ ] **Step 4: Run and see it pass.**
- [ ] **Step 5: Commit.**

### Task 9: History tab (`history_tab.py`)

**Files:**
- Create: `ctwa/ui/results/history_tab.py`, `tests/test_results_history_tab.py`

**Interfaces:**
- Consumes: Task 1 (`matches_fields`, `HISTORY_SEARCH_FIELDS`, `compare_cells`, `next_sort`, `run_label_text`, `js_to_fixed`), Task 2 `base_order`, Task 5 `FigureView`; Foundation `loader.rows()`, `request_graph`, `graph_loaded`, `format_alpha`, `describe_lag_model`, `material_color`.
- Produces `class HistoryTab(QWidget)`, `HistoryTab(loader, parent=None)`:
  - signal `open_in_viewer(int)`; methods `select_id(id: int | None)`, `selected_id() -> int | None`, `set_search(text)`, `detail_text() -> dict` (the key/value pairs shown), `kpis() -> list[str]`, `figure_view() -> FigureView`.
- **Layout:** left, the title `All Analyses (shown / total total)` (the `shown /` part only while a search is active), a search box (`Search name, date, mode, °C or #id`), the 10-column table (`ID, Model, Date, Mode, r₁, r₂, α comb (raw), α phase (raw), Cal, T (°C)`; α by `format_alpha`, Cal `✓`/`✗`, T the raw number or `—`, r₁/r₂ unrounded, nulls `—`), 3-state header sort, up/down keys move the selection through the sorted order and scroll it into view. Right, the detail panel: the run label with a colour dot, the line `<date> · <mode> · Cal (Lag: <n>s)` or `No Cal`, buttons `Open in Viewer` and `Delete`, four KPI tiles (`α phase` of calibrated else raw, highlighted; `α comb`; `Source period` as `toFixed(1)` s; `Raw Δt` as `toFixed(1)` s; null or 0 gives `—`), the `Select analysis to view` combo listing all rows as `<model> | <date> | <mode> | Cal (Lag: <n>s)` or `... | No Cal`, then the `FigureView`, then `Full Details:` as a two-column table with the keys of the webapp (`Created`, `Model`, `Test Date`, `Radii` as `r₁=6.72mm, r₂=14.86mm`, `Temperature` default 25, `Gas Atmosphere`, `Source Period T` 2 decimals, `Response Period T`, `Source Frequency` 5 decimals, `Response Frequency`, `Raw Δt` 2 decimals, α values in mm²/s; and when `use_calibration`: `System Lag` 1 decimal, `Net Δt` 2 decimals, the calibrated α values; and the calibration lines (single reference or `N reference runs`, the `describe_lag_model` text, refs as `#1, #2`, raw `calibration_model`, source run `#<calibrated_from_id>`) and, for a reference run, the known α with 3 decimals).
- On start the first row of the base order is selected, or the one passed to `select_id`. Selecting a row calls `loader.request_graph(id)` and shows `FigureView.show_loading()`.

- [ ] **Step 1: Write the failing offscreen tests:**
  - Rows and columns as above: the α phase raw cell of a row with `8.5123e-6` is `"8.512"`, `T` None is `"—"`, the title says `All Analyses (3 total)` and, after searching `steel`, `All Analyses (2 / 3 total)`. Search uses only the five history fields (`"Ar"` as a query does not match on gas).
  - Selecting a row fills the detail panel: a calibrated row gives the KPI list `["8.512", "8.200", "600.4", "105.2"]` style values from a fixed row, `Radii == "r₁=6.72mm, r₂=14.86mm"`, a missing temperature shows `25`, an uncalibrated row has no `System Lag` key; a reference row shows `Known α` with 3 decimals.
  - The combo lists every row, also ones hidden by the search.
  - `↓` on the focused table moves from the first to the second row of the sorted order; at the last row it stays.
  - `request_graph` is called with the selected id on every selection change, once per change.
  - **Review Focus 1:** select row A (graph requested), select row B, then emit `graph_loaded(A, <figure text>)`: the figure view still says loading and `kpis()` are B's; emit `graph_loaded(B, ...)` and the figure shows. `graph_loaded(B, None)` shows the bar fallback of row B.
  - **Review Focus 5:** `graph_loaded(B, "<broken json")` shows the bar fallback with no exception.
  - `Open in Viewer` emits `open_in_viewer(B)`.
  - A `rows_changed` with the selected row still present keeps the selection and does not call `request_graph` again; if the row is gone the neighbour is selected.
  - `set_search("#254")` selects nothing special but shows only that row; with no match the table is empty and the detail shows `No data`.
- [ ] **Step 2: Run and see it fail.**
- [ ] **Step 3: Implement.** The expected selected id is stored on the tab; `graph_loaded` handler compares ids first. Re-use `SummaryModel`'s base order (`base_order`) so both pages list in the same order.
- [ ] **Step 4: Run and see it pass.**
- [ ] **Step 5: Commit.**

### Task 10: History delete with confirmation and Undo (`undo_bar.py`)

**Files:**
- Create: `ctwa/ui/results/undo_bar.py`, `tests/test_results_history_delete.py`
- Modify: `ctwa/ui/results/history_tab.py`

**Interfaces:**
- Produces:
  - `class UndoBar(QWidget)`: one stacked entry per pending delete with the text `Deleted! #<id>` and an `Undo` button; signals `undone(int)`, `expired(int)`; `add(id, delay_ms=6000)`, `pending_ids()`, `flush()` (expire everything now).
  - `HistoryTab(loader, confirm=None, delay_ms=6000)`: `confirm` is a callable `(title, message) -> bool` (default a `QMessageBox` with a `Delete` and a `Cancel` button); new `delete_selected()`, `flush_pending()`, signal `message(str)`.
- **Behaviour (as the webapp's `history/page.tsx` ~L219-251):**
  - `Delete` asks `Delete this analysis?` / `"<model>" (ID <id>) will be removed from the database permanently.`.
  - On confirm the row is hidden at once (`SummaryModel`-style `pending_hide` on the history model), the neighbour (next, else previous) is selected, and an Undo entry starts.
  - `Undo` shows the row again and re-selects it, and no delete is sent. On expiry `loader.apply_delete(id)` is called.
  - `rows_changed` after a successful delete removes the id from the pending set. `failed` for a pending delete unhides the row and emits `message("Failed to delete: <message>")`; `failed("login", ...)` also emits `login_needed` (a new signal on `HistoryTab`).

- [ ] **Step 1: Write the failing tests** (a 20 ms `delay_ms`, and a fake `confirm`):
  - Cancel in the dialog changes nothing and sends nothing. The dialog texts are exactly the two strings above (checked through the fake `confirm`).
  - Confirm hides the row at once, selects the neighbour (next, else previous), the `UndoBar` shows `Deleted! #<id>`, and `apply_delete` has not been called yet.
  - **Review Focus 3:** Undo within the delay restores the row and the selection, and after waiting longer than the delay `apply_delete` was never called. Without Undo `apply_delete(id)` is called exactly once.
  - Two deletes in a row keep two entries, each with its own timer; Undo of the first leaves the second pending.
  - `flush_pending()` calls `apply_delete` for every pending id immediately and stops their timers (no second call afterwards).
  - **Review Focus 4:** `failed("offline", "no route")` after the delete call unhides the row and the message is `Failed to delete: no route`; the row is selectable again.
  - The pending row is also left out of the search count in the title (`analyses - pending`) while the combo still lists it (the webapp's quirk, kept).
- [ ] **Step 2: Run and see it fail.**
- [ ] **Step 3: Implement.** Timers are `QTimer.singleShot`-style objects owned by the `UndoBar` entry, so deleting the tab stops them without a send.
- [ ] **Step 4: Run and see it pass.**
- [ ] **Step 5: Commit.**

### Task 11: Compare run picker (`compare_picker.py`)

**Files:**
- Create: `ctwa/ui/results/compare_picker.py`, `tests/test_results_compare_picker.py`

**Interfaces:**
- Consumes: Task 1 (`label_of`, `run_label_text`, `matches_fields`), Task 4 `MAX_RUNS`, `run_colors`; Foundation `material_color`.
- Produces `class RunPicker(QWidget)`:
  - `set_rows(rows: list[dict])` (drops chosen ids that no longer exist), `set_ids(ids: list[int])` (known ids only, de-duplicated, at most 4), `ids() -> list[int]` (order of addition), `add(id) -> bool`, `remove(id)`, `clear_all()`;
  - signal `ids_changed(list)`; `hits() -> list[int]` for tests.
- **Layout:** a line edit with the placeholder `Add a run: type a name, date, °C or #id`; a result list under it (at most 60 hits, hidden when the text is empty); one chip per chosen run (colour dot in `run_colors(i)[0]`, `run_label_text`, a remove button); `Remove all`; a counter `n / 4`. Title `Select analyses to compare`.
- **Search:** case-insensitive AND of terms over `label_of(row)`, `#` stripped, already-chosen runs excluded. Up/Down move the highlight, Enter adds it, Esc closes the list; at 4 runs the edit is disabled with the text `Compare up to 4 at a time`.

- [ ] **Step 1: Write the failing offscreen tests:**
  - Typing `steel 766` lists only rows whose `label_of` contains both, typing `#12` finds id 12 only, a chosen run is not offered again, more than 60 matches show 60.
  - Down, Down, Enter adds the second hit; `ids_changed` carries `[id]`; the chip text equals `run_label_text`; the dot colours follow `run_colors(i)[0]` by position (removing the first run recolours the others).
  - A fifth `add` returns False and changes nothing; the counter reads `4 / 4`; the edit is disabled and shows the placeholder-tooltip text above.
  - `set_ids([5, 5, 9999, 3])` with known ids 5 and 3 gives `[5, 3]`; more than 4 known ids are cut to 4.
  - `Remove all` empties and emits `ids_changed([])`. `set_rows` with a list missing a chosen id removes that chip and emits `ids_changed`.
- [ ] **Step 2: Run and see it fail.**
- [ ] **Step 3: Implement** with a `QLineEdit` and an inline `QListWidget` (not a popup window, so offscreen key tests work).
- [ ] **Step 4: Run and see it pass.**
- [ ] **Step 5: Commit.**

### Task 12: Compare charts and tab (`compare_charts.py`, `compare_tab.py`)

**Files:**
- Create: `ctwa/ui/results/compare_charts.py`, `ctwa/ui/results/compare_tab.py`, `tests/test_results_compare_tab.py`

**Interfaces:**
- Consumes: Task 4 (`overlay_run`, `OverlayOptions`, `METRICS`, `metric_value`, `metric_text`, `PARAM_ROWS`, `param_value`, `differing_rows`, `run_colors`), Task 11 `RunPicker`, Task 3 `parse_graph` (through Task 4), Task 1 helpers; Foundation `loader.rows()`, `request_graph`, `graph_loaded`.
- Produces:
  - `class OverlayChart(QWidget)` (`set_runs(list[OverlayRun | None], opts)`; `curve_names()`, `line_count()`, `box_texts()`, `x_title()`, `y_title()`) and `class MetricChart(QWidget)` (`set_values(labels, values, colors, metric_label)`; `dot_values()`, `dot_labels()`, `text_labels()`), both pyqtgraph.
  - `class CompareTab(QWidget)`, `CompareTab(loader, parent=None)`: `set_ids(ids)`, `ids()`, `no_waveform() -> list[str]`, `table_texts() -> list[list[str]]`, `differing() -> set[str]`, `view_mode() -> str`.
- **Layout (en.ts):** title `Analyses Viewer`, the picker, then (when at least one run is chosen) `Result Waveforms — Overlay` with `Signal` (`Source`, `Response`, `Both`), `Align to common start` (on), `Normalize amplitude` (off), `Normalize time from start` (off), `Show amplitude & Δt guides` (on); x title `Time (s)` / `Time from start (s)` / `Normalized time (0–1)`, y title `Power (mW)` / `Normalized power`; the legend is horizontal below the plot; one y axis. The footnote `No stored waveform (shown in table only): <labels>` lists runs without one, and `None of the selected analyses has a stored waveform to overlay.` shows when none has. A `Compare parameter` combo (17 metrics) drives the dot chart titled `<metric label> — comparison across analyses`: one dot per run in its source colour, the value text above it (`—` for None, which draws no dot), runs listed top to bottom in the order chosen. Then `Comparison table` / `Cards` toggle, `Only rows that differ (n)` (shown only with 2 or more runs), rows differing across runs highlighted; the table has the parameter label and one coloured column header per run; Cards shows one table per run.
- Graphs are requested with `loader.request_graph(id)` for each chosen run, once per run until `rows_changed`; arrived graphs are cached by id.

- [ ] **Step 1: Write the failing offscreen tests:**
  - `set_ids([1, 2, 3, 4, 5])` keeps four. An unknown id is ignored. An empty selection shows `Select one or more analyses above to view and compare them.` and no charts.
  - **Waveform overlay:** after `graph_loaded` for two runs, the overlay has 4 curves named `<label_of> — Source` / `— Response` with the Source curve solid and the Response curve dashed in the run colours; a run whose graph is an image or broken JSON is listed in `no_waveform()` and the footnote, and drawing the other still works (**Review Focus 5**); all runs without waveform shows the `None of the selected...` text.
  - The toggles change the data: `Align to common start` off shows the stored x; `Normalize amplitude` gives y in 0..1, drops the guides and changes the y title to `Normalized power`; `Normalize time` gives x in 0..1 and the x title `Normalized time (0–1)`; `Signal = Source` leaves 2 curves for two runs. Guides: `line_count()` equals the `OverlayLine` count from Task 4 for the options, and the value box texts equal `box_text` per run.
  - **Late graphs:** a `graph_loaded` for an id that was removed from the selection is ignored and does not redraw.
  - **Metric chart:** `α Phase (raw) (mm²/s)` for runs with 8.5e-6, 0 and 9e-6 gives dot values `[8.5, None, 9.0]` and texts `["8.500", "—", "9.000"]`; a 1234.5 value shows `1235`; the chart height is `120 + 70 n`.
  - **Parameter table:** `table_texts()` rows equal `param_value` for each chosen run; with two runs differing only in temperature and `α Phase raw`, `differing()` is exactly `{"Temperature (°C)", "α Phase raw (mm²/s)"}`, the `Only rows that differ (2)` checkbox filters the table to them; with one run the checkbox is hidden. Cards mode shows one table per run with 28 rows each.
  - A run that is deleted elsewhere (`rows_changed` without its id) disappears from the selection.
- [ ] **Step 2: Run and see it fail.**
- [ ] **Step 3: Implement.** `OverlayChart` draws `OverlayLine`s as two-point curves (data units) or paper-positioned items (reuse `PaperItem` from `figure_view.py`); labels are `pg.TextItem` with a white 75 % background. The metric chart uses `pg.ScatterPlotItem` with size 16 and a white outline, reversed y axis, with the run labels as the left axis ticks.
- [ ] **Step 4: Run and see it pass.**
- [ ] **Step 5: Commit.**

### Task 13: Results tab container (`results_tab.py`)

**Files:**
- Create: `ctwa/ui/results/results_tab.py`, `tests/test_results_tab.py`

**Interfaces:**
- Consumes: `SummaryTab`, `HistoryTab`, `CompareTab`, Foundation `ResultsLoader`.
- Produces `class ResultsTab(QWidget)`, `ResultsTab(loader, settings=None, parent=None)`:
  - sub-tabs `Summary`, `History`, `Compare` in that order, attributes `summary`, `history`, `compare`;
  - `show_compare(ids)`, `show_history(id)`, `show_summary(ids=None, query=None)`; signal `login_needed()`; `flush_pending()` (History deletes); `current_page() -> str`.
- **Wiring between pages:** Summary `compare_requested(ids)` → `show_compare(ids)`; History `open_in_viewer(id)` → `show_compare([id])`. Each page's `message` goes to the tab's status label (a quiet line under the sub-tabs that clears after 6 s). `login_needed` of Summary and History is re-emitted once per 5 s window so one refused login produces one prompt.
- The first time the tab is shown it calls `loader.refresh()`; showing it again does not refetch (the loader keeps rows fresh through `rows_changed`).

- [ ] **Step 1: Write the failing offscreen tests:**
  - Sub-tab titles are `["Summary", "History", "Compare"]`.
  - Summary → select 3 rows → `Compare`: the current page is `Compare` and `compare.ids()` equals the 3 ids; History `Open in Viewer` shows Compare with that one id.
  - **Review Focus 4:** two `login_needed` signals from Summary and History within a short time give one `login_needed` from the tab.
  - `loader.refresh` is called once on the first `showEvent`, not on later ones.
  - `flush_pending()` forwards to History (its pending delete is sent at once).
  - With a loader whose `rows()` is empty and a `failed("offline", ...)`, all three pages show their banner or empty text and none raises.
- [ ] **Step 2: Run and see it fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run and see it pass.**
- [ ] **Step 5: Commit.**

### Task 14: Wiring, packaging, full suite, screenshots

**Files:**
- Modify: `ctwa/app.py` (one block), `keithley_suite.spec` (`hiddenimports`)
- Test: `tests/test_results_main_window.py`

- [ ] **Step 1: Write the failing test.** A simulated-2602B `MainWindow` (as `tests/test_main_window_tabs.py`) has tab titles `[…, "Real Time", "Runs", "Analysis", "Results"]` with Results as a `ResultsTab`, plus whatever Plans 4 and 5 add around it; the test checks only the relative order `Runs`, `Analysis`, `Results` and that the Results tab exists. With no cloud client (`cloud_client is None`) the tab still exists and shows the offline banner. `window.results_tab.login_needed` is connected to the same slot the File menu's `Webapp login…` uses (`_webapp_login`). `QApplication.aboutToQuit` is connected to `results_tab.flush_pending`.
- [ ] **Step 2: Implement.** In `ctwa/app.py`, after the `tabs.addTab(self.analysis_tab, "Analysis")` line, add only:

```
# --- Results tab (Plan 3) ---
...creates ResultsTab(self.results_loader, settings=self.settings), adds it with tabs.addTab(..., "Results"),
connects login_needed -> self._webapp_login and aboutToQuit -> flush_pending...
# --- end Results tab (Plan 3) ---
```

  using the `ResultsLoader` that Plan 2.5 already created in `MainWindow` (the attribute name it chose; do not create a second one). In `keithley_suite.spec` add `ctwa.ui.results` and each of its modules (`fmt`, `summary_logic`, `figure_model`, `compare_logic`, `figure_view`, `summary_model`, `summary_tab`, `summary_edit`, `history_tab`, `undo_bar`, `compare_picker`, `compare_charts`, `compare_tab`, `results_tab`) to `hiddenimports` in one contiguous block with the same comment markers. `git diff --stat` for `ctwa/app.py` and the spec shows only those additions.
- [ ] **Step 3: Equivalence and area tests.** `QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m pytest tests/test_equivalence_with_original_windows.py tests/test_results_*.py -q` is all green.
- [ ] **Step 4: Full suite.** `QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m pytest -q` is all green (report counts).
- [ ] **Step 5: Screenshots.** A throwaway script (not committed) builds the three pages offscreen with a fake loader holding about 12 rows (calibrated and uncalibrated, two samples, one row with an old-colour figure, one with a PNG) and the `fig_web.json` figure, then `grab()`s Summary (with a selection and a preset applied), History (a calibrated row with its plot) and Compare (3 runs, overlay with guides, the α metric, the table with differences) to `/private/tmp/claude-501/-Users-omervered/35e79076-53f0-40ac-a750-a4dd8ddf2241/scratchpad/results_summary.png`, `results_history.png` and `results_compare.png`. Open each and check that nothing is cut off and the plots are drawn.
- [ ] **Step 6: Commit.**

**After Plan 3:**
- Omer reviews the three screenshots; the merge of `plan3-results` into `desktop-analysis` follows the other plans' branches and conflicts only in the single marked block of `ctwa/app.py` and the `hiddenimports` block.
- The real-data check (Omer opens Results on the lab PC and sees the same rows as the webapp) is part of the 2.0.0 release checklist.
