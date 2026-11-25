"""StatisticsTab: the page's Statistics screen, drawn natively.

rows -> prepare_rows -> apply_filters -> chart specs -> ChartView.set_spec, rebuilt through a 150 ms single-shot
debounce on any control or filter change. Settings (chart choices and filters, never the hidden points) live in
QSettings; hidden points and the selection are session-only.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Dict, List, Optional, Sequence

from PySide6.QtCore import QPoint, QSettings, Qt, QTimer, Signal
from PySide6.QtWidgets import (QFileDialog, QMessageBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
                               QSplitter, QVBoxLayout, QWidget)

from ctwa import theme
from ctwa.stats.aggregate import summary_csv, summary_rows
from ctwa.stats.filters import FilterState, apply_filters
from ctwa.stats.model import prepare_rows
from ctwa.stats.specs import (build_alpha_period_spec, build_builder_spec, build_corr_spec, build_heat_loss_specs,
                              build_phase_specs, build_temp_specs, corr_pair_to_builder, theory_info)
from ctwa.stats.view_state import ViewState, load_view, sanitize, save_view
from ctwa.ui.statistics.chart_view import ChartView
from ctwa.ui.statistics.controls import ChartControls
from ctwa.ui.statistics.filter_panel import FilterPanel
from ctwa.ui.statistics.summary_table import StatisticsSummary

__all__ = ["StatisticsTab"]

DEBOUNCE_MS = 150
NARROW_PX = 1100
PAIR_MESSAGE_MS = 4000

TITLES = {
    "builder": "1. Chart Builder", "alpha": "2. α vs Period — by Model", "heat": "3. Heat-Loss Indicators",
    "phase": "4. Phase Lag Analysis", "temp": "5. Temperature Dependence", "corr": "6. Correlation Matrix",
    "summary": "7. Summary Statistics by Model"}
SHORT = {"builder": "Chart Builder", "alpha": "α vs Period", "heat": "Heat-Loss Indicators",
         "phase": "Phase Lag Analysis", "temp": "Temperature Dependence", "corr": "Correlation Matrix",
         "summary": "Summary Statistics by Model"}
HINTS = {"alpha": "Ideal: α constant across periods. Drift indicates frequency-dependent artifacts.",
         "corr": "Click a cell to plot that pair as a scatter in the chart builder."}
POINT_HINT = ("Click a point to open that run. To hide outliers, choose Lasso or Box Select in the chart toolbar and "
              "circle them; nothing is deleted.")
ORDER = ("builder", "alpha", "heat", "phase", "temp", "corr", "summary")


class _Section(QFrame):
    """A titled card the section links can scroll to."""

    def __init__(self, title: str, hint: str = ""):
        super().__init__()
        theme.set_role(self, "card")
        self._title, self._hint = title, hint
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(14, 12, 14, 12)
        self.layout_.setSpacing(10)
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(1)
        t = QLabel(title)
        theme.set_role(t, "heading")
        col.addWidget(t)
        if hint:
            h = QLabel(hint)
            h.setWordWrap(True)
            theme.set_role(h, "faint")
            col.addWidget(h)
        head.addLayout(col, 1)
        self.actions = QHBoxLayout()
        head.addLayout(self.actions)
        self.layout_.addLayout(head)

    def title(self) -> str:
        return self._title

    def hint(self) -> str:
        return self._hint

    def add(self, w) -> None:
        self.layout_.addWidget(w)


def _label(text: str = "", role: Optional[str] = None, wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(wrap)
    if role:
        theme.set_role(lab, role)
    return lab


class _ChartGrid(QWidget):
    """Charts side by side while each keeps at least CHART_MIN_PX, wrapping onto new rows below that."""
    CHART_MIN_PX = 520

    def __init__(self, charts: Sequence[ChartView]):
        super().__init__()
        self._charts = list(charts)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(10)
        self._cols = 0
        self.setMinimumWidth(self.CHART_MIN_PX // 2)
        self._place(len(self._charts))

    def _place(self, cols: int) -> None:
        if cols == self._cols:
            return
        self._cols = cols
        for i, c in enumerate(self._charts):
            self._grid.addWidget(c, i // cols, i % cols)
        for k in range(len(self._charts)):
            self._grid.setColumnStretch(k, 1 if k < cols else 0)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._place(max(1, min(len(self._charts), self.width() // self.CHART_MIN_PX)))


class StatisticsTab(QWidget):
    open_analysis = Signal(int)

    def __init__(self, loader, settings: QSettings, parent=None,
                 save_path_provider: Optional[Callable[[], str]] = None):
        super().__init__(parent)
        self._loader = loader
        self._settings = settings
        self._save_path_provider = save_path_provider or self._ask_save_path
        self._raw: List[Dict[str, Any]] = []
        self._rows: List[Dict[str, Any]] = []
        self._filtered: List[Dict[str, Any]] = []
        self._presets: List[Dict[str, Any]] = []
        self._loaded = False
        self._requested = False
        self._picked: List[int] = []
        self._owner: Optional[ChartView] = None
        self._view = load_view(settings)
        self.rebuild_count = 0
        self._dirty = False

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self._rebuild)

        self.controls = ChartControls()
        self.panel = FilterPanel()
        self._build_ui()
        self._wire()
        self.controls.set_view(self._view)
        self.panel.set_state(self._view.filters)
        self._show_state("none")

        if loader is not None:
            loader.rows_changed.connect(self._on_rows)
            loader.presets_changed.connect(self._on_presets)
            loader.failed.connect(self._on_failed)
            cached = getattr(loader, "rows", None)
            if callable(cached) and cached():
                presets = getattr(loader, "presets", None)
                self.set_rows(cached(), presets() if callable(presets) else None)

    # ================================================================== layout
    def _build_ui(self) -> None:
        title = _label("Statistics", "title")
        desc = _label("Charts and statistics across all saved analyses, filtered as you choose.", "muted")
        self.csv_button = QPushButton("Download Statistics (CSV)")
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(title)
        col.addWidget(desc)
        head.addLayout(col, 1)
        head.addWidget(self.csv_button, 0, Qt.AlignTop)

        # ---- left: period source + filters
        self.left = QWidget()
        ll = QVBoxLayout(self.left)
        ll.setContentsMargins(8, 8, 0, 0)
        ll.setSpacing(6)
        ll.addWidget(self.controls.source_box)
        ll.addWidget(self.panel, 1)
        self.left.setMinimumWidth(260)

        # ---- right: status row, strip, sections, message
        self.count_label = _label("", "section")
        self.hidden_badge = QFrame()
        theme.set_role(self.hidden_badge, "card")
        hb = QHBoxLayout(self.hidden_badge)
        hb.setContentsMargins(8, 1, 8, 1)
        self.hidden_label = _label("")
        self.show_hidden_button = QPushButton("show")
        theme.set_role(self.show_hidden_button, "quiet")
        hb.addWidget(self.hidden_label)
        hb.addWidget(self.show_hidden_button)
        self.hidden_badge.hide()
        self.filters_toggle = QPushButton("Filters")
        theme.set_role(self.filters_toggle, "quiet")
        self.filters_toggle.hide()
        self.links = QHBoxLayout()
        self.links.setSpacing(4)
        self._links: Dict[str, QPushButton] = {}
        status = QHBoxLayout()
        status.addWidget(self.filters_toggle)
        status.addWidget(self.count_label)
        status.addWidget(_label("analyses selected", "muted"))
        status.addWidget(self.hidden_badge)
        status.addStretch(1)
        self.header_row = QWidget()
        hl = QVBoxLayout(self.header_row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(4)
        hl.addLayout(status)
        hl.addLayout(self.links)
        self.refresh_failed = _label("", "warn", True)
        self.refresh_failed.hide()
        self.pair_message = _label("", "warn", True)
        self.pair_message.hide()
        self._pair_timer = QTimer(self)
        self._pair_timer.setSingleShot(True)
        self._pair_timer.setInterval(PAIR_MESSAGE_MS)
        self._pair_timer.timeout.connect(self.pair_message.hide)

        self.message = _label("", "muted")
        self.message.setAlignment(Qt.AlignCenter)
        self.reset_button = QPushButton("Reset all filters")
        theme.set_role(self.reset_button, "primary")
        self.message_box = QWidget()
        mb = QVBoxLayout(self.message_box)
        mb.addStretch(1)
        mb.addWidget(self.message)
        mb.addWidget(self.reset_button, 0, Qt.AlignHCenter)
        mb.addStretch(2)

        self.builder_chart = ChartView()
        self.alpha_chart = ChartView()
        self.heat_charts = [ChartView() for _ in range(3)]
        self.phase_charts = [ChartView() for _ in range(2)]
        self.temp_charts = [ChartView() for _ in range(2)]
        self.corr_chart = ChartView()
        self.summary = StatisticsSummary()
        self.alpha_hint = self.controls.alpha_hint
        self.sections: Dict[str, _Section] = {k: _Section(TITLES[k], HINTS.get(k, "")) for k in ORDER}

        s = self.sections
        s["builder"].add(self.controls.builder_box)
        s["builder"].add(self.builder_chart)
        self.builder_hint = _label(POINT_HINT, "faint", True)
        s["builder"].add(self.builder_hint)
        s["alpha"].actions.addWidget(self.controls.alpha_actions)
        s["alpha"].add(self.controls.alpha_box)
        s["alpha"].add(self.alpha_chart)
        s["alpha"].add(self.alpha_hint)
        s["alpha"].add(_label(POINT_HINT, "faint", True))
        s["heat"].add(self._row(self.heat_charts))
        s["phase"].actions.addWidget(self.controls.phase_actions)
        s["phase"].add(self._row(self.phase_charts))
        s["temp"].add(self._row(self.temp_charts))
        s["corr"].add(self.corr_chart)
        self.corr_chart.setMaximumWidth(760)
        s["summary"].add(self.summary)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 8, 12)
        cl.setSpacing(14)
        for k in ORDER:
            cl.addWidget(s[k])
        cl.addStretch(1)
        self._content = content
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setWidget(content)

        for k in ORDER:
            b = QPushButton(SHORT[k])
            theme.set_role(b, "quiet")
            b.clicked.connect(lambda _=False, k=k: self.scroll_to(k))
            self.links.addWidget(b)
            self._links[k] = b
        self.links.addStretch(1)

        self.right = QWidget()
        rl = QVBoxLayout(self.right)
        rl.setContentsMargins(8, 8, 0, 0)
        rl.setSpacing(6)
        rl.addWidget(self.header_row)
        rl.addWidget(self.refresh_failed)
        rl.addWidget(self.pair_message)
        rl.addWidget(self.scroll, 1)
        rl.addWidget(self.message_box, 1)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.left)
        self.splitter.addWidget(self.right)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes(self._view.splitter or [320, 1000])
        self.splitter.setChildrenCollapsible(False)

        # ---- selection bar
        self.selection_bar = QFrame()
        theme.set_role(self.selection_bar, "toolbar")
        sb = QHBoxLayout(self.selection_bar)
        sb.setContentsMargins(12, 6, 12, 6)
        self.selection_label = _label("", "section")
        self.hide_button = QPushButton("Hide from this view")
        theme.set_role(self.hide_button, "primary")
        self.clear_selection_button = QPushButton("Clear")
        sb.addWidget(self.selection_label)
        sb.addStretch(1)
        sb.addWidget(self.hide_button)
        sb.addWidget(self.clear_selection_button)
        self.selection_bar.hide()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 0)
        lay.setSpacing(4)
        lay.addLayout(head)
        lay.addWidget(self.splitter, 1)
        lay.addWidget(self.selection_bar)

        # the controls widget only owned the boxes until they were placed
        self.controls.hide()
        self.controls.setParent(self)

    @staticmethod
    def _row(charts: Sequence[ChartView]) -> QWidget:
        return _ChartGrid(charts)

    def _wire(self) -> None:
        self.controls.changed.connect(self._on_controls)
        self.panel.changed.connect(self._on_panel)
        self.csv_button.clicked.connect(self._download_csv)
        self.reset_button.clicked.connect(self._reset_all)
        self.hide_button.clicked.connect(self._hide_picked)
        self.clear_selection_button.clicked.connect(self._clear_picked)
        self.show_hidden_button.clicked.connect(self._show_hidden)
        self.filters_toggle.clicked.connect(self._toggle_filters)
        self.splitter.splitterMoved.connect(self._on_split)
        for chart in (self.builder_chart, self.alpha_chart, *self.phase_charts):
            chart.point_clicked.connect(lambda i: self.open_analysis.emit(int(i)))
            chart.selection_made.connect(lambda ids, c=chart: self._on_selection(c, ids))
            chart.selection_cleared.connect(lambda c=chart: self._on_selection_cleared(c))
        self.corr_chart.cell_clicked.connect(self._on_cell)

    # ================================================================== public
    def view(self) -> ViewState:
        return replace(self._view, filters=self._view.filters.copy())

    def filtered_rows(self) -> List[Dict[str, Any]]:
        return list(self._filtered)

    def link_buttons(self) -> List[QPushButton]:
        return [b for k, b in self._links.items() if not b.isHidden()]

    def flush(self) -> None:
        """Run a pending (debounced) rebuild now."""
        if self._timer.isActive():
            self._timer.stop()
            self._rebuild()

    def set_filters(self, st: FilterState) -> None:
        self._view.filters = st.copy()
        self.panel.set_state(st)
        self._schedule()

    def set_presets(self, presets: Sequence[Dict[str, Any]]) -> None:
        self._presets = list(presets)
        self.controls.set_presets(self._presets)
        self._view = sanitize(self._view, self._rows, self._presets)
        self.controls.set_view(self._view)
        if self._loaded:
            self._schedule()

    def set_rows(self, rows: Sequence[Dict[str, Any]], presets: Optional[Sequence[Dict[str, Any]]] = None) -> None:
        if self._loader is None:
            return
        if presets is not None:
            self._presets = list(presets)
            self.controls.set_presets(self._presets)
        self._raw = list(rows)
        self._rows = prepare_rows(self._raw)
        self._loaded = True
        present = {r.get("id") for r in self._raw}
        hidden = {i for i in self._view.filters.hidden_ids if i in present}
        v = sanitize(self._view, self._rows, self._presets)
        v.filters.hidden_ids = hidden
        self._view = v
        self._picked, self._owner = [], None
        self._update_selection_bar()
        self.refresh_failed.hide()
        self.panel.set_rows(self._rows)
        self.panel.set_state(v.filters)
        self.controls.set_view(v)
        self._timer.stop()
        self._rebuild()

    def scroll_to(self, name: str) -> None:
        self._content.layout().activate()
        self.scroll.verticalScrollBar().setValue(self.sections[name].mapTo(self._content, QPoint(0, 0)).y())

    # ================================================================== pipeline
    def build_specs(self) -> Dict[str, Any]:
        rows, v = self._filtered, self._view
        return {
            "builder": build_builder_spec(rows, v, self._presets),
            "alpha": build_alpha_period_spec(rows, v),
            "heat": build_heat_loss_specs(rows, v),
            "phase": build_phase_specs(rows, v),
            "temp": build_temp_specs(rows, v),
            "corr": build_corr_spec(rows, v),
            "summary": summary_rows(rows),
        }

    def _schedule(self) -> None:
        self._timer.start()

    def _rebuild(self) -> None:
        if self._requested and not self.isVisible():     # a hidden tab rebuilds once, when it is shown
            self._dirty = True
            return
        self._dirty = False
        self.rebuild_count += 1
        v = self._view
        self._filtered = apply_filters(self._rows, v.filters)
        total = len(self._rows)
        self.count_label.setText("%d / %d" % (len(self._filtered), total))
        present = {r.get("id") for r in self._rows}
        n_hidden = len(v.filters.hidden_ids & present)
        self.hidden_label.setText("%d hidden" % n_hidden)
        self.hidden_badge.setVisible(n_hidden > 0)
        try:
            save_view(self._settings, v)
        except Exception:      # a failing settings backend must not stop the charts
            pass
        if not self._loaded or total == 0:
            self.message.setText("Loading…" if not self._loaded else "No analyses found. Run some analyses first.")
            self._show_state("none")
            return
        if not self._filtered:
            self.message.setText("No analyses match these filters.")
            for c in self._all_charts():
                c.set_spec(None)
            self._show_state("nomatch")
            return
        specs = self.build_specs()
        self.controls.set_theory_info(theory_info(self._filtered, v))
        self._set(self.builder_chart, specs["builder"])
        self._set(self.alpha_chart, specs["alpha"])
        for c, sp in zip(self.heat_charts, specs["heat"] + [None] * 3):
            self._set(c, sp)
        for c, sp in zip(self.phase_charts, specs["phase"] + [None] * 2):
            self._set(c, sp)
        for c, sp in zip(self.temp_charts, specs["temp"] + [None] * 2):
            self._set(c, sp)
        self._set(self.corr_chart, specs["corr"])
        self.summary.set_summary(specs["summary"])
        self._show_state("ok")
        self.sections["temp"].setVisible(bool(specs["temp"]))
        self._links["temp"].setVisible(bool(specs["temp"]))
        self.sections["corr"].setVisible(specs["corr"] is not None)
        self._links["corr"].setVisible(specs["corr"] is not None)
        self.builder_hint.setVisible(v.chart_type in ("scatter", "line"))

    @staticmethod
    def _set(chart: ChartView, spec) -> None:
        chart.set_spec(spec)
        if spec is not None:
            chart.setMinimumHeight(spec.height + 70)

    def _all_charts(self) -> List[ChartView]:
        return [self.builder_chart, self.alpha_chart, *self.heat_charts, *self.phase_charts, *self.temp_charts,
                self.corr_chart]

    def _show_state(self, state: str) -> None:
        ok = state == "ok"
        has_rows = state in ("ok", "nomatch")
        self.left.setVisible(has_rows)
        self.header_row.setVisible(has_rows)
        self.scroll.setVisible(ok)
        self.message_box.setVisible(not ok)
        self.reset_button.setVisible(state == "nomatch")
        self.csv_button.setVisible(has_rows)
        if self._loader is None:
            self.message.setText("Results are not available.")
        self._fit_filters()

    # ================================================================== events from controls / panel
    def _on_controls(self) -> None:
        self._view = self.controls.apply_to(self._view)
        self._schedule()

    def _on_panel(self) -> None:
        self._view.filters = self.panel.state()
        self._schedule()

    def _on_rows(self, rows) -> None:
        self.set_rows(rows)

    def _on_presets(self, presets) -> None:
        self.set_presets(presets)

    def _on_failed(self, kind: str, message: str) -> None:
        self.refresh_failed.setText("Could not refresh the results (%s): %s" % (kind, message))
        self.refresh_failed.show()

    def _reset_all(self) -> None:
        self._view.filters = FilterState()          # the page also clears the hidden points here
        self.panel.set_state(self._view.filters)
        self._timer.stop()
        self._rebuild()

    # ---- selection and hiding
    def _on_selection(self, chart: ChartView, ids: List[int]) -> None:
        for other in (self.builder_chart, self.alpha_chart, *self.phase_charts):
            if other is not chart:
                other.clear_selection()
        self._owner, self._picked = chart, list(ids)
        self._update_selection_bar()

    def _on_selection_cleared(self, chart: ChartView) -> None:
        if chart is self._owner:
            self._owner, self._picked = None, []
            self._update_selection_bar()

    def _update_selection_bar(self) -> None:
        n = len(self._picked)
        self.selection_label.setText("%d points selected" % n)
        self.selection_bar.setVisible(n > 0)

    def _clear_picked(self) -> None:
        owner = self._owner
        self._owner, self._picked = None, []
        if owner is not None:
            owner.clear_selection()
        self._update_selection_bar()

    def _hide_picked(self) -> None:
        if not self._picked:
            return
        self._view.filters.hidden_ids = set(self._view.filters.hidden_ids) | set(self._picked)
        self._owner, self._picked = None, []
        self._update_selection_bar()
        self.panel.set_state(self._view.filters)
        self._timer.stop()
        self._rebuild()

    def _show_hidden(self) -> None:
        self._view.filters.hidden_ids = set()
        self.panel.set_state(self._view.filters)
        self._timer.stop()
        self._rebuild()

    # ---- correlation click
    def _on_cell(self, row_label: str, col_label: str) -> None:
        pair = corr_pair_to_builder(row_label, col_label)
        if row_label == col_label:
            return
        if pair is None:
            self.pair_message.setText("The chart builder has no X axis for either of these two.")
            self.pair_message.show()
            self._pair_timer.start()
            return
        y, x = pair
        self._view = replace(self._view, y_metric=y, x_axis=x, chart_type="scatter")
        self.controls.set_view(self._view)
        self._timer.stop()
        self._rebuild()
        self.scroll_to("builder")

    # ---- CSV
    def _ask_save_path(self) -> str:
        path, _ = QFileDialog.getSaveFileName(self, "Download Statistics (CSV)", "summary_statistics.csv",
                                              "CSV (*.csv)")
        return path

    def _download_csv(self) -> None:
        path = self._save_path_provider()
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(summary_csv(self._filtered))
        except Exception as e:
            QMessageBox.warning(self, "Download Statistics", "Could not save the file:\n%s" % e)

    # ---- layout state
    def _on_split(self, *_) -> None:
        self._view.splitter = [int(s) for s in self.splitter.sizes()]
        self._save()

    def _toggle_filters(self) -> None:
        self._view.filters_collapsed = not self._view.filters_collapsed
        self._fit_filters()
        self._save()

    def _save(self) -> None:
        try:
            save_view(self._settings, self._view)
        except Exception:
            pass

    def _fit_filters(self) -> None:
        narrow = self.width() < NARROW_PX
        self.filters_toggle.setVisible(narrow and self.header_row.isVisibleTo(self))
        if self.header_row.isVisibleTo(self) or self.left.isVisibleTo(self):
            self.left.setVisible(not (narrow and self._view.filters_collapsed) and self._loaded
                                 and bool(self._rows))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit_filters()

    def showEvent(self, ev):
        super().showEvent(ev)
        if not self._requested and self._loader is not None:
            self._requested = True
            self._loader.refresh()
        if self._dirty:
            self._timer.stop()
            self._rebuild()
