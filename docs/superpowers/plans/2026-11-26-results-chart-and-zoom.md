# Results Chart + Dual-Axis Zoom Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Analysis tab's ④ Results step shows the real analysis chart. That's the Plotly figure the analysis already builds, saves as `graph_image` and the webapp shows: fitted sines when smoothing is on, the peaks used, the lag marks. Every analysis chart also gets usable zoom on the response axis.

**Design (Omer approved, 26 Nov 2026):**
- **Omer's report:** "the smooth to single sine didn't really work, I don't see the peaks selected in the chart and the chart won't let me zoom in the response plot".
- **Root cause, found by reading the code:**
  - The pipeline does smooth (`ctwa/analysis/pipeline.py:86`), and `analyze_run` builds the figure (`ctwa/analysis/runner.py` → `build_analysis_plot`). But ④ draws the raw synced curves and never shows that figure.
  - Both `AnalysisTab` (`_build_plot`) and `FigureView` (`ctwa/ui/results/figure_view.py:316`) call `self._vb2.setMouseEnabled(False, False)` on the response view box.
- **④ Results:** the top pane shows a `FigureView` drawing the result's plot dict instead of the shared plot. If the plot is `None`, or `FigureView` falls back to bars, keep today's shared plot zoomed to the region.
- **Zoom, on the shared Analysis plot (②③④ fallback) and in `FigureView` (④ and Results › History):**
  - Wheel or drag **inside the plot** zooms or pans time and both signals together. The response follows the source's y change through a linear map.
  - Wheel or drag on the **right axis** changes only the response; on the **left axis**, only the source. Either one re-learns the map.
  - Programmatic fits (autoRange, `_fit_y`, drawing a figure) also re-learn the map.
  - Clicks on the plot must still reach the region and the markers.

## Global Constraints
- **Branch:** `desktop-analysis`. Commit per task; message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. No push. Never add stray `* 2.*` copies. No subagents. Nothing left running when done.
- **Untouchable:** `ctwa/analysis/` (maths and figure building), the saved row, `ctwa/instruments/`.
- **Tests:** only the touched area's: `tests/test_analysis_tab.py`, the FigureView/History tests (find them: `grep -l FigureView tests/*.py`), `tests/test_main_window_tabs.py`, plus a new `tests/test_dual_axis.py`. Python 3.9, `QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m pytest <files> -q`.

## Review Focus
1. A wheel event inside the plot is still handled by the main view box (time zoom works), not swallowed by the response view box on top. Pinned in Task 1.
2. Dragging the region or a marker still works with the new view box. Pinned in Task 1 (existing marker/region tests stay green).
3. Showing a second result (Analyze again) replaces the figure; going back from ④ shows the shared plot again. Pinned in Task 2.
4. A smoothed analysis shows the smoothed traces, i.e. the figure's traces, not the raw curves. Pinned in Task 2, with the golden smooth case if one exists (`tests/golden/analysis/*smooth*`).
5. History's existing figure tests stay green with the new view box. Pinned in Task 1.

---

### Task 1: `ctwa/ui/dual_axis.py` + use it in both plots
**Produces:**
- `ResponseViewBox(pg.ViewBox)`: mouse enabled on y only. `wheelEvent(ev, axis=None)` / `mouseDragEvent(ev, axis=None)` ignore the event when `axis is None` (from inside the plot, so it reaches the main view box underneath), and handle it normally when it comes from its axis. It accepts no mouse buttons for clicks (as `_vb2` does today).
- `link_y_zoom(main: pg.ViewBox, second: pg.ViewBox) -> object`: a handle that keeps `y2 = a·y1 + b`. On `main.sigRangeChangedManually` with both x and y in the mask, it sets `second`'s y range from the map. On any other range change of either box, not caused by its own sync, it re-learns `a, b` from the current ranges.
- Both `AnalysisTab._build_plot` and `FigureView` use `ResponseViewBox` for the response axis and `link_y_zoom`. The main view box gets the left axis's wheel/drag only for y. That's pyqtgraph's default via `AxisItem.linkToView`; check that a left-axis wheel gives a y-only mask.
- [ ] Tests (`tests/test_dual_axis.py`, a plain `PlotWidget` with two curves on two axes):
  - a simulated wheel inside the plot changes the main x and y ranges, and the second box's y range scales by the same factor;
  - a wheel event sent through the right axis changes only the second box's y range;
  - through the left axis, only the main y range;
  - `second.wheelEvent(ev)` with `axis=None` leaves its range unchanged and ignores the event.
  - Existing analysis-tab and History tests stay green.
- [ ] Commit.

### Task 2: ④ Results shows the analysis figure
**Files:** `ctwa/ui/analysis_tab.py` (the top pane becomes a `QStackedWidget`: shared plot | `self.result_figure = FigureView()`), and tests in `tests/test_analysis_tab.py`.
- On `_on_finished`, keep the plot dict. In `go("results")`, if there's a plot dict, call `self.result_figure.show_graph(json.dumps(plot), row_like)` and show the figure page. `row_like` = what `FigureView`'s bar fallback needs; pass the results' α fields the way History does. If it drew bars or nothing, show the shared plot zoomed as today.
- Leaving ④ shows the shared plot. A cleared result clears the figure.
- `AnalysisTab.result_figure_shown() -> bool` (for tests).
- [ ] Tests:
  - after an AutoFit golden analysis, ④ shows the figure (mode `figure`, `curve_count() >= 2`);
  - with smoothing on (a golden smooth case), the figure's source trace values equal the plot dict's smoothed trace;
  - back to region shows the shared plot;
  - a second analysis replaces the figure;
  - plot `None` → shared plot.
- [ ] Commit.
