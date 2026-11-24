# Statistics Tab (Plan 5 of the CTWA 2.0 build) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A **Statistics** tab in the CTWA app with every chart, filter and export of the webapp's Statistics page (`app/statistics/page.tsx`), drawn natively, reading the rows the Results Foundation already loads.

**Architecture:**
- **`ctwa/stats/`** is pure Python (no Qt): row extractors, filters, aggregation, box/violin maths, and one *chart spec* builder per chart. A spec is a plain dataclass (series, colours, hover text, ids, reference lines) that says what to draw, so almost all behaviour is tested without a widget.
- **`ctwa/ui/statistics/`** holds the widgets: one `ChartView` (pyqtgraph) that draws any spec, the filter panel, the controls, the summary table and `StatisticsTab`.
- **Data:** rows and presets come from the shared `ResultsLoader` (no extra queries). Rows pass through `with_ln_validity` once per `rows_changed`.
- **State:** chart settings and filters persist in `QSettings` (replacing the webapp's URL/localStorage). Hidden points are session-only.

**Tech Stack:** PySide6, pyqtgraph 0.13, numpy (no scipy: the KDE is Plotly's own 20-line kernel sum), `ctwa.results.*` (Results Foundation), `ctwa.analysis.references`, `ctwa.analysis.diffusivity`, `ctwa.analysis.jsmath` (`js_round`, `js_to_precision`).

**Spec:** `docs/superpowers/specs/2026-11-24-ctwa-desktop-analysis-design.md` (stage 6: "every chart type/option from the web page"; Statistics settings remembered in QSettings; pyqtgraph throughout, box and violin as custom items). Feature inventory: scratchpad `plan5-statistics-inventory.md`. Where the inventory and the Plotly source disagree, this plan follows the **Plotly source** (see Task 4).

## Global Constraints

- **Branch and worktree:** `plan5-statistics`, in its own worktree: `git worktree add ../ctwa-plan5 -b plan5-statistics desktop-analysis`, created only **after the Results Foundation commit is on `desktop-analysis`**. Plans 3 and 4 are built in parallel; nothing here waits for them. No push, no tags, no commits to `master`.
- **New modules only:** `ctwa/stats/*`, `ctwa/ui/statistics/*`, `tests/test_stats_*.py`, `tests/test_statistics_*.py`, `tests/data/stats_rows.json`. `ctwa/app.py` changes only in Task 13, inside **one** block delimited by `# --- Statistics tab (Plan 5) ---` and `# --- end Statistics tab ---`. `keithley_suite.spec` `hiddenimports` change only in Task 13. Foundation modules are consumed, never edited.
- **Untouchable:** `ctwa/instruments/`, `keithley*_driver.py`. `tests/test_equivalence_with_original_windows.py` stays green.
- **Python 3.9** (`from __future__ import annotations`; no `X | Y` at runtime). `/usr/bin/python3 -m pytest`; Qt tests use `QT_QPA_PLATFORM=offscreen` and the existing QApplication pattern in `tests/`. No real network (the tab never touches the network itself).
- **Literal ports.** Each pure function keeps the page's algorithm and order of operations. Its test expected values come from a **throwaway `npx tsx` script** in the scratchpad that pastes the page's function bodies verbatim (they are not exported) and runs them on `tests/data/stats_rows.json`; results are pasted into the test as literals. The script is never committed. For Plotly-internal maths (Task 4) the script `require`s `node_modules/plotly.js/src/lib/stats.js` and `src/traces/violin/helpers.js` directly.
- **Fixture:** `tests/data/stats_rows.json`, 18 rows in the DB's snake_case columns (alphas in m²/s, as stored), made once in Task 1. It must contain: 4 models (`Stainless Steel`, `unk foam`, `Abs`, `Al₂O₃`); periods 75–2400 s including 254.99, 255, 199.9, 200, 1200; two temperatures (25/null and 150); two Δr values (8.14 and one 6.0); one calibrated copy (`calibrated_from_id` set); a row with `ln_term` ≤ 0 and valid amplitudes (so `with_ln_validity` fires); a row with `period_t_resp` null; a row with `amplitude_a2 == 0`; a row with `test_date` malformed; alphas ≤ 0 and null; one `is_reference`.
- **GUI never blocks:** all aggregation is O(rows × models) and cheap. **Budget:** building every section's spec for 600 rows ≤ 1.0 s in the test (typically < 150 ms), and redraws are debounced 150 ms (`QTimer`, single shot) so dragging a slider or typing never builds more than ~7 per second. Nothing here runs a thread; there is no I/O.
- **One look:** colours and fonts from `ctwa.theme` (`theme.P`, `theme.TEXT_SMALL`, `theme.TEXT_AXIS`). The app has one light theme, so the webapp's dark-mode tokens are not ported. Group/model colours are `material_color(name)`; literature colours `LITERATURE_COLORS`.
- **Texts:** English, taken verbatim from `lib/i18n/en.ts` (`statistics.*`, with `\u` escapes resolved). Group options `Reference Status` and `Lag Model` are not in `en.ts`; use those two literals from the page.
- **Commits:** messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

Likely user-facing failures that no task is *about*; each is pinned by a test in the task named.

1. **Calibrated copies double-counted.** First open shows only originals (`calibrated_from_id is None`); switching to "Both" shows the warning text `rowKindWarn`. Pinned in Task 2 (filter) and Task 12 (default tab state, warning visible only for non-originals).
2. **Stale saved filters after new data arrives.** A saved period range, excluded period or model that no longer exists must not blank the charts silently: the range is clamped to the new domain (empty intersection resets it), unknown excluded values are dropped on load. Pinned in Task 5 (`sanitize`) and Task 12 (rows refresh with a saved narrow range).
3. **Log axis with zero/negative values** (φ, Δt, ln term and α can be ≤ 0): points are dropped, never an exception, never an all-blank chart when other points are positive. Pinned in Task 8.
4. **Garbage in QSettings** (older version, hand edit, wrong type): any unreadable key falls back to its default, the tab still opens. Pinned in Task 5.
5. **Rows refresh while the user has hidden points or a selection, and "open run" with no History wired.** Hidden ids stay hidden (ids no longer present are ignored, count badge counts only present ones), the selection clears, and a click on a point emits `open_analysis(int)` that does nothing harmful when nothing is connected; box/violin/bar points carry no id and emit nothing. Pinned in Task 12.

---

### Task 1: Row model: extractors, groups, bands, formatting

**Files:**
- Create: `ctwa/stats/__init__.py`, `ctwa/stats/model.py`, `tests/data/stats_rows.json`, `tests/test_stats_model.py`

**Interfaces:**
- Produces in `model.py` (ports of `page.tsx` L35–158, plus `AC withLnValidity` via the foundation):
  - `PERIOD_SOURCES = ("src", "resp")`; `get_period(row, source) -> Optional[float]`, `get_frequency(row, source)` (resp → `period_t_resp` / `frequency_f_resp`, None when null).
  - `round10(p: float) -> int` = `int(js_round(p / 10) * 10)` (JS rounding: half up).
  - `@dataclass(frozen=True) YMetric(key, label, is_alpha)`; `Y_METRICS: Tuple[YMetric, ...]` in the page's order with the page's labels verbatim (`"α Combined (raw) mm²/s"`, …, `"Raw Time Lag Δt (s)"`, `"Raw Phase φ (rad)"`, `"ln term"`, `"A₁ (mW)"`, `"A₂ (mW)"`, `"A₁/A₂ ratio"`, `"Period (s)"`, `"Temperature (°C)"`); `Y_BY_KEY: Dict[str, YMetric]`.
  - `X_AXES: Tuple[str, ...]` = the page's `X_OPTIONS` (9 names, exact).
  - `GROUP_OPTIONS: Tuple[str, ...]` = `Model, Model + Period, Period (exact), Period Band, Temp Band, Calibration, Analysis Mode, Reference Status, Lag Model`.
  - `extract_y(row, key, source) -> Optional[float]`, `extract_x(row, axis, source) -> Optional[float]`, `group_value(row, group_by, source) -> Optional[str]`, `period_band(p)`, `temp_band(t)`.
  - `prepare_rows(rows: List[dict]) -> List[dict]` = `[with_ln_validity(r) for r in rows]`.
  - `fmt_g(x: float, sig: int) -> str`: d3's `.{sig}~g` (exponential only when exponent < −6 or ≥ sig; exponent written `e+6`/`e-7` without padding; trailing zeros trimmed). Python's `%g` differs, so do not use it.
  - `run_label_text(row) -> str` = `"Model · {T} °C · {round10 period} s · #id"` exactly as the page's `runLabelText`.
  - `color_for(name) = material_color(name)` (re-export; the foundation already checks hash and KNOWN map).

- [ ] **Step 1: Failing tests** in `tests/test_stats_model.py`:
  - Build the fixture first (script-generated once from real-shaped values, committed).
  - `round10`: `254.99 → 250`, `255 → 260`, `245 → 250` (JS half-up), `0 → 0`.
  - `period_band`: `199.9 → "< 200 s"`, `200 → "200–400 s"` (en dash), `699.9 → "400–700 s"`, `1200 → "> 1200 s"`. `temp_band(None) → "< 50 °C"` (missing T is treated as 25), `100 → "100–200 °C"`, `300 → "> 300 °C"`.
  - `extract_y` for every metric on every fixture row equals the TS pins (literal dict `{row_id: {metric: value}}`), including α ×1e6 only when > 0, `a1_a2_ratio` None when `amplitude_a2 == 0`, and `period_t` following `source="resp"` (None for the row with null `period_t_resp`).
  - `group_value` for each of the 9 options on every row equals TS pins; `Model + Period` → `"Al₂O₃ | 260s"` style; `Reference Status` → `"Reference"/"Calibrated copy"/"Measurement"`; `Lag Model` for a row with `calibration_model="sqrt:..."` → what `describe_lag_model` returns, and a copy without a model → `"unknown"`, an original → `"not reference-calibrated"`.
  - `fmt_g(1234567, 5) == "1.2346e+6"`, `fmt_g(0.5, 5) == "0.5"`, `fmt_g(0.00001234, 4) == "0.00001234"`, `fmt_g(1e-7, 3) == "1e-7"`, `fmt_g(0, 5) == "0"`.
  - `prepare_rows` nulls both combined alphas and rewrites `ln_term` for the ln ≤ 0 row, and leaves the input list's dicts unmodified.
- [ ] **Step 2: Run to fail:** `/usr/bin/python3 -m pytest tests/test_stats_model.py -q` → ImportError.
- [ ] **Step 3: Implement.** Decisions: `extract_*` return `None` for NaN/inf as well as missing (the page's `null`); group order is not decided here (callers keep first appearance, Task 7).
- [ ] **Step 4: Run to pass.**
- [ ] **Step 5: Commit** `stats: row model (extractors, groups, bands)`.

### Task 2: Filters (excluded sets, row kind, ranges, dates)

**Files:**
- Create: `ctwa/stats/filters.py`, `tests/test_stats_filters.py`

**Interfaces:**
- Produces:
  - `@dataclass FilterState`: `exclude_models, exclude_periods (set of int round10 values), exclude_source_devices, exclude_response_devices, exclude_gas, exclude_modes: Set[...]`; `row_kind: str = "originals"` (`"originals" | "copies" | "all"`); `cal: str = "All"` (`"All" | "Calibrated" | "Uncalibrated"`); `period_range: Optional[Tuple[int,int]] = None` (None = whole domain); `a1_range: Optional[Tuple[float,float]] = None`; `date_from, date_to: Optional[date] = None`; `hidden_ids: Set[int]`. `copy()` and `reset_keep_hidden() -> FilterState`.
  - `apply_filters(rows, f) -> List[dict]` (keeps input order, i.e. created_at descending).
  - `distinct_values(rows, field) -> List[str]` (non-empty, sorted); `period_options(rows, f) -> List[int]` (round10 values inside the current period range, sorted numerically); `period_domain(rows) -> Optional[Tuple[int,int]]`; `a1_domain(rows) -> Optional[Tuple[int,int]]` (floor/ceil); `a1_step(lo, hi) -> float` (5 if span > 200, 1 if > 50, 0.5 if > 5, else 0.1).
  - `active_filters(f, rows) -> List[Tuple[str, str]]` (label, key) for the chips, labels as the page (`"Models −2"`, `"Periods −1"`, `"{lo}–{hi} s"`, `"A₁ {lo}–{hi} mW"`, `"Calibrated copies only"`/`"Both"`, `"Calibrated"`/`"Uncalibrated"`); `clear_filter(f, key) -> FilterState`.

- [ ] **Step 1: Failing tests** (fixture rows):
  - Defaults keep only rows with `calibrated_from_id is None`; `row_kind="copies"` keeps only copies; `"all"` keeps both (**Review Focus 1**).
  - A row with a null field is never excluded by that field's exclusion set.
  - The period range compares `round10(period_t)` (the source period, even when the view's period source is `resp`), inclusive at both ends: with range `(250, 260)` the 254.99 and 255 rows pass, a 199.9 row does not. A null `period_t` is treated as 0, as JS does (`Math.round(null/10)*10`), so it is dropped by any range starting above 0. The excluded-period set compares the same `round10` value.
  - `date_from`/`date_to` inclusive of the whole end day; the malformed `test_date` row counts as epoch 0 (excluded by any `date_from`, kept by `date_to` only).
  - A row with null `amplitude_a1` passes the A₁ range.
  - `a1_step(0,100) == 1`, `a1_step(0,300) == 5`, `a1_step(0,20) == 0.5`, `a1_step(0,2) == 0.1`, `period_domain` on the fixture equals the TS pin.
  - `active_filters` of a state with 2 excluded models and a narrowed period range returns `[("Models −2","models"), ("{lo}–{hi} s","period")]`; `clear_filter` removes just that; `reset_keep_hidden` keeps `hidden_ids`.
  - Hidden ids are removed from the result.
  - The filtered id list of 6 hand-picked `FilterState` combos equals TS pins.
- [ ] **Step 2: Run to fail.** `/usr/bin/python3 -m pytest tests/test_stats_filters.py -q`.
- [ ] **Step 3: Implement** as a literal port of the page's apply block; `parse_test_date` comes from `ctwa.results.helpers` (`None` → `date(1970,1,1)`).
- [ ] **Step 4: Run to pass. Step 5: Commit** `stats: filters`.

### Task 3: Aggregation: means, bins, pairs, theory, correlation, summary

**Files:**
- Create: `ctwa/stats/aggregate.py`, `tests/test_stats_aggregate.py`

**Interfaces:**
- Produces (all ports of page code, names fixed):
  - `mean(v) -> float`; `std_pop(v) -> float` (divide by n; used by bar error bars and the summary); `std_sample(v) -> float` (n−1; 0 for n < 2; used by the α mean±std).
  - `linear_fit(xs, ys) -> Optional[Tuple[float, float]]` (slope, intercept; needs n ≥ 3; zero denominator → None; normal equations as P:162).
  - `bin_by_period(points: List[Tuple[float, float]]) -> List[PeriodBin]`, `PeriodBin(x, y, sd, n)`: sort by x, start a new bin when `x > first_x_of_bin * 1.04`; `x` and `y` are bin means, `sd` sample std.
  - `pair_segments(rows, model, source, phase: bool, combined: bool) -> List[Tuple[Tuple[float,float], Tuple[float,float]]]`: per run with period and both raw and calibrated α non-null (> 0), `((p, raw), (p, cal))`; phase and combined handled separately.
  - `common_dr(rows) -> Optional[float]`: most common 3-dp rounding of `r2_mm − r1_mm` > 0; ties → first by the page's sort; `distinct_dr(rows) -> List[float]`.
  - `log_grid(xmin, xmax, n=160) -> List[float]` (`xmin*(xmax/xmin)**(k/(n-1))`).
  - `theory_curve(alpha_mm2s, dr_mm, xs, x_axis, kind) -> List[Optional[float]]`, `kind` in `"phase" | "lag"`, uses `theoretical_phase` / `theoretical_lag_dt` (for `Frequency (Hz)` the period is `1/x`).
  - `CORR_LABELS: Tuple[str, ...]` (the 10 labels: `A₁, A₂, A₁/A₂, Period, Δt, φ, ln term, α comb raw, α phase raw, T (°C)`); `corr_matrix(rows, source) -> List[List[float]]`.
  - `points_in_polygon(px, py, poly: List[Tuple[float,float]]) -> bool` (even-odd rule).
  - `@dataclass SummaryRow(model, n, stats: Dict[str, Optional[Tuple[int, float, float, float, float]]])` keyed `combined_raw, phase_raw, combined_cal, phase_cal` → `(n, mean, std_pop, min, max)`; `summary_rows(rows) -> List[SummaryRow]` (models in first-appearance order); `fmt_stat(x, digits) -> str` (`js_to_precision`, `"—"` for None); `summary_csv(rows) -> str` with header `Model,N,alpha_comb_raw_mean,alpha_comb_raw_std,alpha_comb_raw_min,alpha_comb_raw_max,alpha_phase_raw_*,alpha_comb_cal_*,alpha_phase_cal_*` (4 columns each) and values `toPrecision(4/3/4/4)`; CRLF-free `\n` line ends.

- [ ] **Step 1: Failing tests:**
  - `std_pop([1,3]) == 1.0`, `std_sample([1,3]) == 1.4142135623730951`, `std_sample([5]) == 0`.
  - `linear_fit([1,2,3],[2,4,6]) == (2.0, 0.0)`, 2 points → None, identical x → None.
  - `bin_by_period` on periods `[100, 103, 104.5, 110]` → 3 bins with `n == [2,1,1]` (`104.5 > 100*1.04`; `110 > 104.5*1.04`), first bin `x == 101.5`.
  - `pair_segments` on the fixture equals the TS pin and skips a run with only one of raw/cal.
  - `common_dr(fixture)` and `distinct_dr` equal TS pins (8.14 wins, 6.0 listed).
  - `log_grid(1, 1000)[0] == 1`, `[159] == 1000` (rel 1e-12), len 160.
  - `theory_curve(4.0, 8.14, [261], "Period (s)", "phase")[0]` equals `theoretical_phase(4.0, 8.14, 261)` and is within 1e-4 of 0.4465; `"lag"` equals `theoretical_lag_dt`; `x ≤ 0` → None; `Frequency (Hz)` with `x = 1/261` gives the same phase.
  - `corr_matrix(fixture)` equals the TS pin to 1e-12; diagonal is 1.0 where ≥ 3 pairs and variance > 0; a column with < 3 pairs gives 0 off-diagonal; the matrix is symmetric.
  - `points_in_polygon` square cases (inside, outside, on a vertex's far side).
  - `summary_rows`/`summary_csv(fixture)` equal TS pins character for character, including `—` for empty series and `0.000` std for n=1.
- [ ] **Step 2: Run to fail. Step 3: Implement** (literal ports; `corr_matrix` uses the page's `num/(dx*dy)` with `dx*dy == 0 → 0`). **Step 4: Pass. Step 5: Commit** `stats: aggregation`.

### Task 4: Box and violin maths (Plotly-exact)

**Files:**
- Create: `ctwa/stats/dist.py`, `tests/test_stats_dist.py`

**Decisions (from Plotly 3.x source, which override the inventory):**
- **Quartile method:** Plotly's default `quartilemethod: "linear"` = `Lib.interp(sorted, q)` with position `q*N − 0.5` (clamped to the ends, linear between neighbours). **This is not numpy's default** (`(N−1)*q`): for `[1,2,3,4]` Plotly gives q1 = 1.5, q3 = 3.5; numpy gives 1.75 and 3.25.
- **Whiskers:** lowest point ≥ q1 − 1.5·IQR and highest point ≤ q3 + 1.5·IQR (Plotly's fence rule). All points are drawn anyway (`boxpoints: "all"`).
- **Violin bandwidth is Silverman's rule, not Scott's:** `1.059 · min(sample_sd, IQR/1.349) · N^(−1/5)`, floored at `span/100`; zero span → bandwidth 0 (zero-width violin). **Soft span is `[min − 2·bw, max + 2·bw]`** (not 3·bw). Density is sampled at `n = ceil(dist/(bw/3))` steps. Each violin is scaled so its own max density equals the full half-width (scalemode `width`, one scalegroup per trace name).
- **Geometry:** category spacing 1; box and violin half-width 0.35 (gap 0.3); points `x = i + 0.35·(−1.5 + 0.3·(2u − 1))` (`pointpos −1.5`, `jitter 0.3`), `u` from `random.Random(group_index)` so the picture is stable between redraws (Plotly's own jitter is random, so exact positions cannot match, only the layout).

**Interfaces:**
- Produces: `interp(sorted_vals, q) -> float`; `@dataclass BoxStats(n, q1, med, q3, lo_whisker, hi_whisker, mean)`; `box_stats(vals) -> Optional[BoxStats]` (None for n = 0); `silverman_bandwidth(vals) -> float`; `@dataclass ViolinShape(ts, half_widths, bandwidth)` and `violin_shape(vals, half_width=0.35) -> Optional[ViolinShape]` (n = 1 or zero span → a degenerate shape `ts=[v,v]`, widths `[0,0]`); `jitter_x(index, n, half_width=0.35) -> List[float]`.

- [ ] **Step 1: Failing tests:**
  - `interp([1,2,3,4], 0.25) == 1.5`, `0.75 → 3.5`, `0.5 → 2.5`; `[1,2,3,4,5]` → q1 1.75, med 3, q3 4.25.
  - `box_stats([1,2,3,4,100])`: q1 1.75, q3 28.0, `hi_whisker == 4`, `lo_whisker == 1`; `box_stats([])` None; `box_stats([7])` all 7.
  - `silverman_bandwidth([1,2,3,4,5]) ≈ 1.2136` (abs 1e-4); constant list → 0; and the span/100 floor engages for `[0,0,0,0,10]`.
  - `violin_shape([1,2,3,4,5])`: `ts[0] ≈ 1 − 2·1.2136`, `ts[-1] ≈ 5 + 2·1.2136`, `max(half_widths) == 0.35`, symmetric density peak near 3; the sample count equals `ceil(dist/(bw/3)) + 1`.
  - Densities from `violin_shape` match Plotly's `makeKDE` outputs (TS-pinned, 5 sample points on a 7-value list) to rel 1e-9.
  - `jitter_x` stays within `[i − 0.525 − 0.105, i − 0.525 + 0.105]` and is identical on two calls.
- [ ] **Step 2: Run to fail. Step 3: Implement** (numpy allowed, but loops over the python floats the way Plotly does so sums agree). **Step 4: Pass. Step 5: Commit** `stats: box and violin maths`.

### Task 5: View state and QSettings persistence

**Files:**
- Create: `ctwa/stats/view_state.py`, `tests/test_stats_view_state.py`

**Interfaces:**
- Produces `@dataclass ViewState` with defaults equal to the page's: `chart_type="box"`, `y_metric="alpha_combined_raw"`, `group_by="Model"`, `x_axis="Period (s)"`, `color_by=None`, `log_x=False`, `log_y=False`, `period_log=True`, `show_mean=False`, `show_pairs=False`, `period_source="src"`, `alpha_series: List[str]=["combined_raw"]`, `lit_builder: List[str]=[]`, `lit_alpha: List[str]=list(LIT_MATERIALS)`, `theory_ids: List[int]=[]`, `filters: FilterState`.
- `ALPHA_SERIES = ("combined_raw", "phase_raw", "combined_cal", "phase_cal")`.
- `save_view(settings: QSettings, v: ViewState) -> None`, `load_view(settings) -> ViewState`, `sanitize(v, rows, presets) -> ViewState`.
- **QSettings keys** (all under group `statistics/`; scalars stored as str/bool, lists and sets as JSON strings; `hidden_ids` and selection are never stored):
  `chartType`, `yMetric`, `groupBy`, `xAxis`, `colorBy` (`""` = None), `logX`, `logY`, `periodLog`, `showMean`, `showPairs`, `periodSource`, `alphaSeries`, `litBuilder`, `litAlpha`, `theoryIds`, `filter/excludeModels`, `filter/excludePeriods`, `filter/excludeSources`, `filter/excludeResponses`, `filter/excludeGas`, `filter/excludeModes`, `filter/rowKind`, `filter/cal`, `filter/periodRange` (`"lo,hi"` or `""` when not narrowed), `filter/a1Range` (same), `filter/dateFrom`, `filter/dateTo` (ISO `YYYY-MM-DD` or `""`), `ui/filtersCollapsed`, `ui/splitter` (JSON list of 2 ints).
- `sanitize`: drops excluded values not present in `rows`; intersects `period_range`/`a1_range` with the current domain (empty intersection → None); drops theory ids not in `presets`; enforces the page's rule that `show_pairs` implies `alpha_series` contains `phase_raw` and `phase_cal`; replaces an unknown `y_metric`/`x_axis`/`group_by`/`chart_type` with the default.

- [ ] **Step 1: Failing tests** (a `QSettings` on a temp `IniFormat` file):
  - Round trip of a fully non-default state equals the original (including empty color_by, a date range, a narrowed period range).
  - Defaults load from an empty file; `hidden_ids` is not written.
  - **Review Focus 4:** a file with `logX="banana"`, `excludeModels="{not json"`, `periodRange="5"`, `chartType="pie"`, `splitter="[1]"` loads without raising and gives defaults for exactly those keys, keeping the valid ones.
  - **Review Focus 2:** `sanitize` with saved range `(2000, 3000)` against rows whose domain is `(70, 300)` → `None`; range `(100, 5000)` → `(100, 300)`; unknown excluded model removed; unknown preset id removed; `show_pairs=True` adds both phase series.
- [ ] **Step 2: Run to fail. Step 3: Implement** (no Qt import in `view_state.py` beyond the `QSettings` type used in annotations under `TYPE_CHECKING`; functions only call `.value/.setValue`). **Step 4: Pass. Step 5: Commit** `stats: view state and settings`.

### Task 6: Chart spec types and the chart-builder spec

**Files:**
- Create: `ctwa/stats/specs.py`, `tests/test_stats_specs_builder.py`

**Interfaces:**
- Produces dataclasses:
  - `Series(name, color, x, y, ids: List[Optional[int]], hover: List[str], mode: str, symbol="o", filled=True, size=7, width=1.0, dash="solid", opacity=1.0, legend=True, legendgroup=None, yerr: Optional[List[float]]=None, segments=False)`: `mode` is `"markers" | "lines" | "lines+markers"`; `segments=True` means x/y hold pairs of points with `NaN` gaps (the raw↔calibrated connectors); `dash` is `solid|dash|dot|dashdot`; `symbol` is a pyqtgraph symbol (`o s d + x t`).
  - `RefLine(y, label, color, dash, width)`.
  - `Group(name, color, values, ids)`.
  - `HeatSpec(labels, matrix, text)`.
  - `ChartSpec(kind, title, xlabel, ylabel, xlog, ylog, series, ref_lines, categories: List[Tuple[str, str]] (name, tick text `"{name}\nn = {n}"`), groups: List[Group], heat: Optional[HeatSpec], height)`, `kind` in `"xy" | "box" | "violin" | "bar" | "heatmap"`.
  - `TheoryInfo(defined: bool, dr: Optional[float], mixed: List[float])`.
- Produces functions:
  - `build_builder_spec(rows, view, presets) -> Optional[ChartSpec]`, `rows` already filtered. `None` when no rows.
  - `theory_info(rows, view) -> TheoryInfo` (`defined` only when `y_metric in {raw_phase_phi, raw_lag_dt}` and `x_axis in {Period (s), Frequency (Hz)}`).
  - `lit_ref_lines(names) -> List[RefLine]`, `preset_ref_lines(presets, ids) -> List[RefLine]`.

**Decisions:** scatter/line series per `color_by` group (or one `"All"`), colour `color_for(group)`; points need non-null x and y; line sorts by x, marker 6, width 2; scatter marker 8, plus one dotted width-1.5 trend line per group from min x to max x when `linear_fit` exists (no legend entry). Box/violin/bar: groups in first-appearance order of the filtered list, rows with group None dropped, `ticktext = "{group}\nn = {count of non-null y}"`, title `"{yLabel} by {groupBy}"`; bar `y = mean (0 if empty)`, `yerr = std_pop (0 if n ≤ 1)`. Scatter/line title `"{yLabel} vs {xAxis}"`, height 500. Reference lines (literature: dash width 1.5, label right-aligned on the plot; presets dotted width 2, label `"{material} {T}°C"`) appear **only** when the Y metric `is_alpha`; for alpha Y the theory curves are never drawn. Theory series: dashed width 2, colour `COLORS[(i+5) % 10]` with the page's `COLORS` list, name `"{material} {T}°C (α={alpha})"`, 160 log-grid points over the positive x values (needs `xmax > xmin`), only when `theory_info.defined` and `dr` known. Hover text: `"{model} | {round10}s (or —) | {test_date} | #{id}\n{xAxis}: {fmt_g(x,5)}\n{yLabel}: {fmt_g(y,5)}"`. `ids` hold the analysis id for scatter/line points; box/violin/bar groups keep `ids` in `Group` but the renderer never emits them (the page gives them no click).

- [ ] **Step 1: Failing tests** (fixture + 3 presets):
  - Box on defaults: categories order, tick texts with `n = …` equal TS-pinned literals; group colours equal `material_color`.
  - Bar: `y` mean and `yerr` population std per group equal TS pins; empty group → 0 and 0; single point → 0 error.
  - Scatter `Period (s)` vs `φ` with `color_by="Model"`: one trend `Series` per group with ≥ 3 points (slope/intercept pinned), none for a group with 2; points with a null x are dropped; hover string of the first point equals a TS literal.
  - Line: points sorted by x.
  - `y_metric="alpha_phase_raw"` with `lit_builder=["Al","Abs"]` gives 2 ref lines with the exact colours/values from `LITERATURE`; non-alpha Y gives none.
  - Theory: `raw_phase_phi` vs `Period (s)` with one preset → one dashed series of 160 points whose first/last y equal `theoretical_phase(alpha, dr, x)`; vs `Temperature (°C)` → `TheoryInfo.defined False`, no series; mixed Δr → `mixed == [6.0, 8.14]` and `dr == 8.14`.
  - `log_x/log_y` flags copied to the spec; empty rows → None.
  - `period_source="resp"`: the row with null `period_t_resp` is dropped from `Period (s)` x and from `Period (exact)` groups.
- [ ] **Step 2: Run to fail. Step 3: Implement. Step 4: Pass. Step 5: Commit** `stats: builder chart spec`.

### Task 7: Specs for α-vs-period, heat-loss, phase, temperature, correlation

**Files:**
- Modify: `ctwa/stats/specs.py`
- Create: `tests/test_stats_specs_sections.py`

**Interfaces:**
- Produces:
  - `build_alpha_period_spec(rows, view) -> Optional[ChartSpec]`; `None` when no rows or `alpha_series` empty. Title `"{series labels joined ' / '} vs Period — by Model"`, labels from `ALPHA_SERIES` (`α Combined (raw)`, `α Phase (raw)`, `α Combined (cal)`, `α Phase (cal)`), xlabel `Period (s)`, ylabel `α (mm²/s)`, `xlog=view.period_log`, `ylog=view.log_y`, ref lines from `view.lit_alpha`, height `max(460, 440 + ceil(models/3) * n_series * 20)`.
  - `build_heat_loss_specs(rows, view) -> List[ChartSpec]` (3 box charts: `ln term by Model`, `A₁/A₂ Ratio by Model`, `α phase/α comb by Model`; y log by `log_y`; reference line y=1 `#888` dashed, label `Ideal` only on the third).
  - `build_phase_specs(rows, view) -> List[ChartSpec]` (`Raw Phase φ vs Period`, `Raw Time Lag Δt vs Period`, per-model lines+markers size 6 width 1 sorted by period; x log by `period_log`, y by `log_y`).
  - `build_temp_specs(rows, view) -> List[ChartSpec]`: `[]` unless ≥ 2 distinct temperatures; titles `α Combined (raw) vs Temperature`, `α Phase (raw) vs Temperature`; linear axes (ignores logs); all five literature lines; non-positive α excluded.
  - `build_corr_spec(rows, view) -> Optional[ChartSpec]` (`None` for < 3 rows; kind `heatmap`, title `Correlation Matrix (Pearson r)`, text `f"{v:.2f}"`).
  - `corr_pair_to_builder(row_label, col_label) -> Optional[Tuple[str, Optional[str]]]`: the page's `CORR_TO_BUILDER` rule: returns `(y_key, x_axis)`; if the column label has no X, the row label's X is used with the column as Y; neither → None; diagonal → None.

**Decisions:** per model colour `color_for(model)`; per series symbol/dash as the page: plain mode = `lines+markers` size 7 width 1; with `show_mean` or `show_pairs` runs become `markers` only, and with `show_mean` opacity 0.4 and `legend=False` (the mean series carries `legendgroup=model` so one legend click hides both); pair symbols `{phase_raw: ("o", hollow), phase_cal: ("o", filled), combined_raw: ("d", hollow), combined_cal: ("d", filled)}` else symbol index `["o","s","d","+","x"][si]`; dash `[solid, dash, dot, dashdot][si % 4]`. Mean series: x/y from `bin_by_period` (per model and series), squares size 10, `yerr = sd` (shown only where n ≥ 2, else 0), name `"{name} — mean ± std"`, hover `"{model}\nT ≈ {x:.0f} s\n{label}: mean {y:.4g} ± sd mm²/s\nn = {n}"`. Pairs: one `segments=True` series per model, width 1.5, opacity 0.55, no legend, no hover. Run hover: `"{run_label_text} · {test_date}\nT = {x:.0f} s\n{label} = {fmt_g(y,4)} mm²/s"`. Series name is the model, or `"{model} ({series label})"` when more than one series is selected.

- [ ] **Step 1: Failing tests** (fixture; expected values TS-pinned):
  - Alpha chart, one series, plain: per-model point lists sorted by period equal pins; `lines+markers`.
  - `show_mean=True`: raw series opacity 0.4, `legend False`; mean series values equal `bin_by_period` pins incl. `yerr == [0, sd, …]`.
  - `show_pairs=True` with phase raw+cal selected: connector `segments` count equals `pair_segments`; symbols match the table.
  - Heat-loss: third spec's α ratio values `alpha_phase_raw/alpha_combined_raw` only when both > 0; ref line `y == 1` and the `Ideal` label only on the third.
  - Phase specs honour `period_log=False` → `xlog False`; temp specs: `[]` for a single-temperature fixture subset, two specs otherwise, no point with α ≤ 0.
  - Corr spec text of cell (0,1) equals the TS-formatted `toFixed(2)`; `corr_pair_to_builder("φ","α comb raw")` → None (neither has X); `("Δt","φ")` → `("raw_phase_phi", "Raw Δt (s)")`; `("A₁","A₁")` → None.
- [ ] **Step 2: Run to fail. Step 3: Implement. Step 4: Pass. Step 5: Commit** `stats: section chart specs`.

### Task 8: `ChartView` base widget (theme, axes, hover, click, lasso, legend bar, export)

**Files:**
- Create: `ctwa/ui/statistics/__init__.py`, `ctwa/ui/statistics/chart_view.py`, `ctwa/ui/statistics/legend_bar.py`, `tests/test_statistics_chart_view.py`

**Interfaces:**
- Produces `class ChartView(QWidget)`:
  - signals `point_clicked = Signal(int)`, `selection_made = Signal(list)` (analysis ids), `selection_cleared = Signal()`;
  - `set_spec(spec: ChartSpec | None)`, `set_tool(tool: str)` (`"pan" | "lasso" | "box"`), `reset_view()`, `selected_ids() -> List[int]`, `export_png(path)`, `export_svg(path)`, `plot_item() -> pg.PlotItem` (for tests), `series_visible(name) -> bool`.
  - A toolbar row (Pan, Lasso, Box select, Reset view, PNG, SVG) styled with `theme`, a `pg.PlotWidget` below it, a `LegendBar` under the plot.
- `LegendBar(QWidget)`: `set_entries(List[Tuple[name, color, legendgroup]])`, signal `toggled(name, visible)`, `isolated(name)`. Click toggles an entry (and every entry sharing its `legendgroup`); double-click isolates it; a second double-click shows all. Replaces pyqtgraph's `LegendItem` (which has no click toggling). Horizontal, wraps, sits below the plot like Plotly's `y=-0.2`.
- Drawing (shared helpers, used by Tasks 9–10): themed frame (white `theme.P.raised` background, light grid `#eceff3`, mirrored axes lines `#cfd5dd`, title bold 15 px via `PlotItem.setTitle`, axis labels `theme.TEXT_AXIS`); `set_categories(ticks)` via `AxisItem.setTicks` with two-line ticks; `add_ref_lines(ref_lines)` using `InfiniteLine` plus a `TextItem` anchored at the right edge of the view box and re-anchored on range change; log mode via `setLogMode` after **masking** non-positive values on that axis (`mask_for_log(xs, ys, xlog, ylog) -> (xs, ys, kept_idx)`, a module-level pure function).
- Interactions: every marker is a `ScatterPlotItem` with `data = analysis id`; hovering shows `QToolTip.showText(QCursor.pos(), hover)`; in Pan mode a click on a marker emits `point_clicked(id)` only when the id is not None. Lasso: drag with the left button draws a translucent `QGraphicsPolygonItem`; on release every visible marker whose **view coordinates** (log10 where the axis is log) fall inside (`points_in_polygon`) is selected, selected markers get an accent ring (`theme.P.accent_strong`), `selection_made(ids)` fires (a lasso that catches nothing fires `selection_cleared`). Box tool = the same with a rectangle polygon. A click on empty space in lasso/box mode clears. Hidden (legend-toggled-off) series are neither selectable nor drawn.
- Export: `export_png` uses `pg.exporters.ImageExporter` at `width = 3 * widget width`, white background, light theme colours; `export_svg` uses `SVGExporter`. File names are suggested by `slugify(title)` (lowercase, non-alphanumerics → `-`), done in the tab (Task 12) with `QFileDialog`.

- [ ] **Step 1: Failing tests** (offscreen; build specs by hand):
  - **Review Focus 3:** an xy spec with `ylog=True` and y values `[−1, 0, 2, 4]` renders without raising, the scatter item holds exactly 2 points, and `mask_for_log` returns kept indices `[2, 3]`; with all values ≤ 0 the chart shows no points and no exception.
  - Categories: a box-kind spec with two categories gives bottom-axis ticks equal to the spec's tick texts.
  - `point_clicked`: simulate `sigClicked` of the marker for point 2 → emits that id; a `None` id emits nothing.
  - Lasso: a polygon around markers 1 and 2 of 4 → `selection_made([id1, id2])`; on a log-y spec the polygon is interpreted in log coordinates (points chosen by their displayed position); a tiny polygon around empty space → `selection_cleared`.
  - `LegendBar`: click hides the series and every entry sharing its `legendgroup`; double-click isolates; hidden series' markers are not selectable.
  - `export_png` writes a file whose width is 3× the widget width; `export_svg` writes a file starting with `<svg`; both leave the view unchanged.
  - Ref line: an `InfiniteLine` at the spec's y and its label's text equals the spec label.
- [ ] **Step 2: Run to fail. Step 3: Implement. Step 4: Pass. Step 5: Commit** `statistics ui: chart view, legend bar, export`.

### Task 9: Box, violin and bar rendering

**Files:**
- Create: `ctwa/ui/statistics/dist_items.py`
- Modify: `ctwa/ui/statistics/chart_view.py` (dispatch `kind` to the draw functions)
- Create: `tests/test_statistics_dist_items.py`

**Interfaces:**
- Produces: `draw_box(plot, spec) -> List[pg.GraphicsObject]`, `draw_violin(plot, spec)`, `draw_bar(plot, spec)`, each returning the items added (so `set_spec` can clear them). Items: `BoxItem(QGraphicsObject)` (rectangle q1..q3 filled with the group colour at 50 % alpha, median line, whiskers with caps, group-colour pen), `ViolinItem(QGraphicsObject)` (closed polygon from `violin_shape`, same fill), points as a `ScatterPlotItem` (size 6, group colour, alpha 0.8) at `jitter_x` positions, bars as `pg.BarGraphItem(width=0.7)` with `pg.ErrorBarItem` (population std from the spec, cap width 0.12 in x units).
- X range `(-0.5, n-0.5)`; the Y range is padded 5 % beyond data/whiskers/violin span; for log Y the group stats are computed on the **original** values and drawn at log10 positions (box positions are transformed, not recomputed).
- No click ids are attached to box/violin/bar items and their points are not lasso-selectable (the page offers click and lasso only on scatter/line, α and phase charts).

- [ ] **Step 1: Failing tests:**
  - `draw_box` on groups `[1,2,3,4,5]` and `[1,2,3,4,100]`: item geometry exposes q1/med/q3/whiskers equal to Task 4 values (1.75/3/4.25 and 1.75/3/28 with whisker 4); a group with no values draws nothing and does not raise.
  - Point scatter has one point per value, all x within the jitter band of its category.
  - `draw_violin`: polygon's max half-width is 0.35 and equals at the density peak; a one-value group draws a zero-width line; polygon x extent never exceeds ±0.35 around the category.
  - `draw_bar`: bar heights equal the spec's `y`, error bar `top/bottom` equal `yerr` (population std), and a group with n ≤ 1 has zero error.
  - Log-Y box: a positive-only group positions the median at `log10(median)`.
- [ ] **Step 2: Run to fail. Step 3: Implement. Step 4: Pass. Step 5: Commit** `statistics ui: box, violin, bar`.

### Task 10: XY series, mean/pairs overlays, and the correlation heatmap

**Files:**
- Create: `ctwa/ui/statistics/xy_items.py`, `ctwa/ui/statistics/heatmap.py`
- Modify: `ctwa/ui/statistics/chart_view.py` (dispatch)
- Create: `tests/test_statistics_xy_items.py`

**Interfaces:**
- Produces `draw_xy(view, spec) -> None`: for each `Series` a `PlotDataItem` line (when `mode` has `lines`; pen colour, width, Qt dash style from `dash`, opacity) and a `ScatterPlotItem` (when `markers`; `symbol`, `size`; hollow = `pen=color, brush=None`, filled = both; opacity), error bars through `pg.ErrorBarItem` (cap width scaled to 5 px; `yerr` of 0 draws nothing), `segments=True` drawn as a `PlotDataItem` with `connect="pairs"`. Legend entries come from the series with `legend=True` into `LegendBar`.
- Produces `draw_heatmap(view, spec)`: `pg.ImageItem` with a lookup table built from Plotly's `RdBu` stops `[0 rgb(5,10,172), .35 rgb(106,137,247), .5 rgb(190,190,190), .6 rgb(220,170,132), .7 rgb(230,145,90), 1 rgb(178,10,28)]` over `z ∈ [−1, 1]` (so 0 maps to the grey middle), 2 px gaps drawn as white grid lines, one `TextItem` per cell showing `spec.heat.text` (text colour white when |r| > 0.6, else dark), y axis reversed, x tick labels rotated −40° (a rotated `QGraphicsTextItem` per tick, since `AxisItem` cannot rotate), a colour bar (`pg.ColorBarItem`, label `r`). Signal `ChartView.cell_clicked = Signal(str, str)` (row label, column label).

- [ ] **Step 1: Failing tests:**
  - A markers+lines series: one `PlotDataItem` and one `ScatterPlotItem` with the spec's point count; hollow series has no brush fill; dash `dot` maps to `Qt.DotLine`.
  - `yerr` produces an `ErrorBarItem` with those heights; zeros produce none.
  - `segments=True` series with 2 pairs separated by a NaN gap draws 2 separate segments.
  - Mean+pairs overlay: legend entries equal the spec's legend-visible series only; a legend click on the model entry hides raw and mean series together.
  - Heatmap: image shape `(10, 10)`; the LUT colour at `r = 0` equals `(190,190,190)` within 1 and at `r = 1` equals `(178,10,28)`, at `r = −1` `(5,10,172)`; 100 text items with the spec's strings; clicking cell (3,5) emits `cell_clicked("A₁/A₂", "Δt")` order (row label first as in `CORR_TO_BUILDER`'s `y`, column label `x`).
- [ ] **Step 2: Run to fail. Step 3: Implement. Step 4: Pass. Step 5: Commit** `statistics ui: xy series and heatmap`.

### Task 11: Filter panel and chart controls

**Files:**
- Create: `ctwa/ui/statistics/filter_panel.py`, `ctwa/ui/statistics/controls.py`, `tests/test_statistics_controls.py`

**Interfaces:**
- Produces `class FilterPanel(QWidget)`: `set_rows(rows)` (rebuilds the option lists), `set_state(FilterState)`, `state() -> FilterState`, signal `changed()`. Contents in the page's order and wording: **Models** (checkbox list; label text `Models`), **Periods** (list labelled `"{n} s"`, restricted to the range; text `No periods in range` when empty), **Range** (two-handle period slider with step 10 and spin boxes), **A₁** range (step from `a1_step`), **Rows** combo (`Originals only` / `Calibrated copies only` / `Both`) with hint `rowKindHint` and a warning label with `rowKindWarn` shown for non-originals, **Calibration** combo (`All`, `Calibrated`, `Uncalibrated`), `Power source device`, `Power response device`, `Gas atmosphere`, `Analysis Mode` lists, **Date Range** (`From` / `To` `QDateEdit`s with a "no limit" checkbox each), active-filter chips (`active_filters`, each with a clear button) and a `Reset all filters` button (keeps hidden ids). Lists are `QListWidget` with checkable items (checked = included, so the stored form stays the excluded set); the panel scrolls.
- Produces `class ChartControls(QWidget)`: `set_view(ViewState)`, `apply_to(ViewState)`, signal `changed()`. Controls: **Chart Type** (`Box, Violin, Bar (mean ± std), Scatter, Line`), **Y-Axis Metric**, **Group by** (shown for box/violin/bar), **X-Axis** and **Color by** (shown for scatter/line; Color by has `None` + group options), chips `Log X`, `Log Y`, `Log period axis`, `Mean ± std` (hint `meanStdHint`), `Raw → calibrated` (hint `rawCalPairsHint`; turning it on adds the phase raw/cal series like the page), `Show literature reference lines` with the 5 material chips, `Series:` chips for the α chart (`α Combined (raw)` …), `Theory curves (presets)` chips from `presets` (`"{material} {T}°C (α={alpha})"`, α shown mm²/s), the `Period source` segmented control (`Source`/`Response`, hint `periodSourceHint`) and the theory messages (`theoryNotDefined`, `Curves drawn with Δr = {x} mm`, `theoryMixedDr` + list of Δr).

- [ ] **Step 1: Failing tests** (offscreen): `FilterPanel.state()` after unchecking one model/period equals the expected `FilterState` and emits `changed` once; `set_state` then `state()` round-trips; the warning label is hidden for originals and visible for `copies`/`all`; period list excludes values outside the slider range; the chip for a narrowed range disappears after its clear button; `Reset all filters` keeps `hidden_ids`; `ChartControls` shows `Group by` only for box/violin/bar and `X-Axis` only for scatter/line; switching `Raw → calibrated` on adds both phase series to `alpha_series`; `apply_to` after `set_view` returns an equal `ViewState`.
- [ ] **Step 2: Run to fail. Step 3: Implement** (block signals while repopulating so a rebuild never emits `changed`). **Step 4: Pass. Step 5: Commit** `statistics ui: filters and controls`.

### Task 12: `StatisticsTab`: assembly, sections, summary, CSV, hide, open run

**Files:**
- Create: `ctwa/ui/statistics/summary_table.py`, `ctwa/ui/statistics/tab.py`, `tests/test_statistics_tab.py`

**Interfaces:**
- Produces `class StatisticsTab(QWidget)`:
  - `__init__(loader: ResultsLoader, settings: QSettings, parent=None)`;
  - signal `open_analysis = Signal(int)`;
  - `set_rows(rows, presets)`; the tab also connects `loader.rows_changed`/`presets_changed`/`failed` and calls `loader.refresh()` the first time it is shown.
  - Layout: a left `FilterPanel` (collapsible below 1100 px width; `ui/filtersCollapsed`), a right scroll area with a section-links bar (`1. Chart Builder` … `7. Summary Statistics by Model`, scroll to the section) and the seven sections with the `en.ts` headings and hints (`alphaVsPeriodHint`, `pointHint`, `corrHint`), a header `Statistics` with `description`, a `Download Statistics (CSV)` button, and a selection bar (`"{n} points selected"`, `Hide from this view`, clear) plus a `"{n} hidden"` badge with a `show` link. Section 5 only when `build_temp_specs` is non-empty, section 6 only for ≥ 3 filtered rows. Empty states: no rows → `No analyses found. Run some analyses first.`; filtered empty → `No analyses match these filters.` with `Reset all filters`.
  - Pipeline: `rows → prepare_rows → apply_filters → specs → ChartView.set_spec`, triggered through a 150 ms single-shot debounce on any control/filter change.
  - `StatisticsSummary(QTableWidget)`: one row per model with a colour dot, `n`, then mean/std/min/max for the 4 α series (`fmt_stat`), first column frozen; the CSV button writes `summary_statistics.csv` through a `QFileDialog.getSaveFileName` (injectable `save_path_provider` for tests).
  - Interactions: builder, α and phase charts forward `point_clicked(id)` to `open_analysis(id)`; lasso selection fills the selection bar; `Hide from this view` adds ids to `FilterState.hidden_ids` (never persisted); correlation `cell_clicked` runs `corr_pair_to_builder` and switches the builder to scatter, scrolls to section 1, or shows `The chart builder has no X axis for either of these two.` in a label for 4 s. Each chart has PNG/SVG buttons (`ChartView`) using `slugify(title)` as the suggested file name.
  - Settings: `load_view`/`sanitize` on first rows; `save_view` after every change (debounced with the redraw).
  - A `refresh_failed` strip shows the loader's error text (`failed(kind, message)`), the charts keep the last rows.

- [ ] **Step 1: Failing tests** (offscreen; a stub loader with the signals `rows_changed`, `presets_changed`, `failed` and recorded `refresh()` calls; fixture rows):
  - **Review Focus 1:** after `set_rows(fixture)` the header shows the count of originals only, the copy row is in no chart spec, and switching Rows to `Both` shows the warning.
  - **Review Focus 2:** settings with a saved period range outside the new domain: `set_rows` shows charts (not the empty message), the range chip is absent.
  - **Review Focus 5:** hide two ids → they vanish from every chart and the badge reads `2 hidden`; `set_rows` with new data where one of them is gone → badge reads `1 hidden`, the selection is cleared, nothing raises; `open_analysis` emitted with `7` for a builder point click with no receiver connected causes no error; a click on a box point emits nothing.
  - Sections: single-temperature fixture hides section 5; 2 rows hide section 6; no rows shows the no-data text; filtered-empty shows the no-match text and the reset button restores charts.
  - Persistence: changing chart type to `scatter` and closing/reopening with the same `QSettings` file restores it; hidden ids are not restored.
  - Corr click on (`"Δt"`, `"φ"`) sets chart type scatter, y `raw_phase_phi`, x `Raw Δt (s)`; on (`"φ"`, `"α comb raw"`) shows the not-plottable message and changes nothing.
  - `Download Statistics (CSV)` writes exactly `summary_csv(filtered rows)` to the injected path.
  - Budget: with 600 synthetic rows the full pipeline (all specs) finishes in < 1.0 s; five rapid control changes trigger a single rebuild.
- [ ] **Step 2: Run to fail. Step 3: Implement. Step 4: Pass** (`-k statistics`). **Step 5: Commit** `statistics ui: tab`.

### Task 13: Wiring, packaging, full suite, screenshots

**Files:**
- Modify: `ctwa/app.py` (one delimited block), `keithley_suite.spec` (`hiddenimports`), `tests/test_main_window_tabs.py` (only the expected tab list)
- Create: `tests/test_statistics_wiring.py`, `tests/test_statistics_screenshots.py`

**Interfaces:**
- The block in `MainWindow`, placed right after the `tabs.addTab(self.analysis_tab, "Analysis")` line:

```python
# --- Statistics tab (Plan 5) ---
from ctwa.ui.statistics.tab import StatisticsTab
self.statistics_tab = StatisticsTab(getattr(self, "results_loader", None), self.settings)
tabs.addTab(self.statistics_tab, "Statistics")
_show_history = getattr(getattr(self, "results_tab", None), "show_history", None)
if callable(_show_history):          # Plan 3 merged and exposing show_history(int id)
    self.statistics_tab.open_analysis.connect(_show_history)
# --- end Statistics tab ---
```
  When `results_loader` is missing the tab shows `Results are not available.` and nothing else. (Plan 3 owns `show_history(int)`; if its method is named otherwise, only this one connect line changes.)
- `keithley_suite.spec`: add `ctwa.stats`, `ctwa.stats.model`, `.filters`, `.aggregate`, `.dist`, `.specs`, `.view_state`, `ctwa.ui.statistics`, and `.chart_view`, `.legend_bar`, `.dist_items`, `.xy_items`, `.heatmap`, `.filter_panel`, `.controls`, `.summary_table`, `.tab`; and `pyqtgraph.exporters`.
- `tests/test_statistics_screenshots.py`: skipped unless `CTWA_SHOT_DIR` is set; builds a window offscreen with the fixture rows (plus enough synthetic rows to fill the charts), and saves `grab()` PNGs `statistics_box.png`, `statistics_violin.png`, `statistics_scatter_trend.png`, `statistics_alpha_period.png`, `statistics_heatmap.png`.

- [ ] **Step 1: Failing tests** in `tests/test_statistics_wiring.py`: `MainWindow` (simulation mode, as `test_main_window_tabs.py` builds it) has a tab titled `Statistics` after `Analysis`; with a fake `results_tab` exposing `show_history`, emitting `open_analysis(5)` calls it with `5`; without one, emitting does nothing and raises nothing; `hiddenimports` in the spec contains every new module (parse the spec text); `git diff desktop-analysis -- ctwa/app.py` contains exactly one added hunk bounded by the two marker comments (test reads the file and checks the block's markers appear once each).
- [ ] **Step 2: Run to fail. Step 3: Implement the block and spec edits.** Update the expected tab list in `tests/test_main_window_tabs.py` (tab order is otherwise unchanged).
- [ ] **Step 4: Verify:**
  - `QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m pytest tests -q` (the **full** suite, once, as Plan 5's acceptance) is green, including `test_equivalence_with_original_windows.py`.
  - `git diff --stat desktop-analysis` touches nothing under `ctwa/instruments/` or `keithley*_driver.py` and `ctwa/app.py` only inside the block.
  - `CTWA_SHOT_DIR=/private/tmp/claude-501/-Users-omervered/35e79076-53f0-40ac-a750-a4dd8ddf2241/scratchpad QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m pytest tests/test_statistics_screenshots.py -q` writes the five PNGs there; open each and check by eye: box with all points beside the boxes and `n = …` ticks, violin shapes, scatter with dotted trend lines per group, α-vs-period with legend below, the 10 × 10 heatmap with numbers in every cell.
- [ ] **Step 5: Commit** `statistics: wire into the main window`. Report the five PNG paths and the final test count; do not merge.
