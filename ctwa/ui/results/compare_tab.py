"""Compare tab of the Results tab (app/analyses-viewer/page.tsx): up to four saved runs overlaid, one metric
as a dot chart, and the parameters as a table or cards. Rows come from the loader; stored plots are
requested per run and drawn when they arrive."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QPushButton, QScrollArea, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ctwa import theme
from ctwa.results.helpers import with_ln_validity
from ctwa.ui.results.compare_charts import MetricChart, OverlayChart
from ctwa.ui.results.compare_logic import (METRICS, PARAM_ROWS, OverlayOptions, box_text, differing_rows,
                                          metric_value, overlay_run, param_value, run_colors)
from ctwa.ui.results.compare_picker import RunPicker
from ctwa.ui.results.fmt import label_of, run_label_text
from ctwa.ui.results.summary_logic import base_order

__all__ = ["CompareTab"]

PROMPT = "Select one or more analyses above to view and compare them."
NO_WAVEFORM_ANY = "None of the selected analyses has a stored waveform to overlay."
NO_WAVEFORM_NOTE = "No stored waveform (shown in table only): "
GRAPH_FAILED_NOTE = "Could not load the graph: "


def _dot_icon(color: str) -> QIcon:
    pm = QPixmap(10, 10)
    pm.fill(Qt.transparent)
    from PySide6.QtGui import QPainter
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen)
    p.drawEllipse(0, 0, 10, 10)
    p.end()
    return QIcon(pm)


def _toggle(text: str, on: bool) -> QPushButton:
    b = QPushButton(text.replace("&", "&&"))     # not a mnemonic
    b.setCheckable(True)
    b.setChecked(on)
    theme.set_role(b, "quiet")
    return b


class CompareTab(QWidget):
    def __init__(self, loader, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._loader = loader
        self._by_id: Dict[Any, Dict[str, Any]] = {}
        self._graphs: Dict[int, Optional[str]] = {}
        self._requested: Set[int] = set()
        self._failed: Set[int] = set()           # graph fetch failed (retried on the next request)
        self._no_waveform: List[str] = []
        self._build()
        loader.rows_changed.connect(self._on_rows)
        loader.graph_loaded.connect(self._on_graph)
        loader.failed.connect(self._on_failed)
        rows = loader.rows()
        if rows:
            self._on_rows(rows)
        self._update_all()

    # ---- construction ----
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        self._scroll, self._body = scroll, body    # keep the Python wrappers alive
        root = QVBoxLayout(body)
        root.setSpacing(12)
        self.banner = QFrame()
        bl0 = QHBoxLayout(self.banner)
        bl0.setContentsMargins(0, 0, 0, 0)
        self.banner_label = QLabel()
        self.banner_label.setWordWrap(True)
        theme.set_role(self.banner_label, "danger")
        bl0.addWidget(self.banner_label, 1)
        self.banner.hide()
        root.addWidget(self.banner)
        title = QLabel("Analyses Viewer")
        theme.set_role(title, "title")
        root.addWidget(title)
        self.picker = RunPicker()
        self.picker.ids_changed.connect(self._ids_changed)
        root.addWidget(self.picker)
        self._prompt = QLabel(PROMPT)
        theme.set_role(self._prompt, "muted")
        root.addWidget(self._prompt)

        self._charts = QWidget()
        cl = QVBoxLayout(self._charts)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(12)
        root.addWidget(self._charts)

        head = QLabel("Result Waveforms — Overlay")
        head.setStyleSheet("font-weight: 600;")
        cl.addWidget(head)
        bar = QFrame()
        theme.set_role(bar, "toolbar")
        bl = QHBoxLayout(bar)
        bl.addWidget(QLabel("Signal"))
        self.signal_buttons: Dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for key, label in (("source", "Source"), ("response", "Response"), ("both", "Both")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setChecked(key == "both")
            group.addButton(b)
            b.clicked.connect(self._update_overlay)
            self.signal_buttons[key] = b
        bl.addWidget(theme.segmented(*self.signal_buttons.values()))
        self.align_button = _toggle("Align to common start", True)
        self.norm_amp_button = _toggle("Normalize amplitude", False)
        self.norm_time_button = _toggle("Normalize time from start", False)
        self.guides_button = _toggle("Show amplitude & Δt guides", True)
        for b in (self.align_button, self.norm_amp_button, self.norm_time_button, self.guides_button):
            b.clicked.connect(self._update_overlay)
            bl.addWidget(b)
        bl.addStretch(1)
        cl.addWidget(bar)
        self.overlay = OverlayChart()
        cl.addWidget(self.overlay)
        self._overlay_msg = QLabel()
        theme.set_role(self._overlay_msg, "muted")
        cl.addWidget(self._overlay_msg)
        self._footnote = QLabel()
        self._footnote.setWordWrap(True)
        theme.set_role(self._footnote, "faint")
        cl.addWidget(self._footnote)

        mrow = QHBoxLayout()
        mrow.addWidget(QLabel("Compare parameter:"))
        self.metric_combo = QComboBox()
        for key, label, _ in METRICS:
            self.metric_combo.addItem(label, key)
        self.metric_combo.currentIndexChanged.connect(self._update_metric)
        mrow.addWidget(self.metric_combo)
        mrow.addStretch(1)
        cl.addLayout(mrow)
        self.metric_chart = MetricChart()
        cl.addWidget(self.metric_chart)

        trow = QHBoxLayout()
        self.table_button = QPushButton("Comparison table")
        self.cards_button = QPushButton("Cards")
        vgroup = QButtonGroup(self)
        vgroup.setExclusive(True)
        for b in (self.table_button, self.cards_button):
            b.setCheckable(True)
            vgroup.addButton(b)
            b.clicked.connect(self._update_params)
        self.table_button.setChecked(True)
        trow.addWidget(theme.segmented(self.table_button, self.cards_button))
        self.diff_check = QCheckBox()
        self.diff_check.toggled.connect(self._update_params)
        trow.addWidget(self.diff_check)
        trow.addStretch(1)
        cl.addLayout(trow)
        self.param_table = QTableWidget()
        self.param_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.param_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.param_table.verticalHeader().hide()
        self.param_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        cl.addWidget(self.param_table)
        self._cards = QWidget()
        self._cards_grid = QGridLayout(self._cards)
        cl.addWidget(self._cards)
        self._card_tables: List[QTableWidget] = []
        root.addStretch(1)

    # ---- public ----
    def set_ids(self, ids: List[int]) -> None:
        self.picker.set_ids(ids)

    def ids(self) -> List[int]:
        return self.picker.ids()

    def no_waveform(self) -> List[str]:
        return list(self._no_waveform)

    def table_texts(self) -> List[List[str]]:
        t = self.param_table
        return [[t.item(r, c).text() for c in range(t.columnCount())] for r in range(t.rowCount())]

    def differing(self) -> Set[str]:
        return differing_rows(self._rows())

    def view_mode(self) -> str:
        return "cards" if self.cards_button.isChecked() else "table"

    def options(self) -> OverlayOptions:
        sig = next(k for k, b in self.signal_buttons.items() if b.isChecked())
        return OverlayOptions(signal=sig, align=self.align_button.isChecked(),
                              norm_amp=self.norm_amp_button.isChecked(),
                              norm_time=self.norm_time_button.isChecked(), guides=self.guides_button.isChecked())

    def select_metric(self, key: str) -> None:
        i = self.metric_combo.findData(key)
        if i >= 0:
            self.metric_combo.setCurrentIndex(i)

    def metric_label(self) -> str:
        return self.metric_combo.currentText()

    def prompt_text(self) -> str:
        return self._prompt.text() if not self._prompt.isHidden() else ""

    def charts_visible(self) -> bool:
        return not self._charts.isHidden()

    def overlay_message(self) -> str:
        return self._overlay_msg.text() if not self._overlay_msg.isHidden() else ""

    def overlay_visible(self) -> bool:
        return not self.overlay.isHidden()

    def footnote_text(self) -> str:
        return self._footnote.text() if not self._footnote.isHidden() else ""

    def card_row_counts(self) -> List[int]:
        return [t.rowCount() for t in self._card_tables]

    # ---- data ----
    def _rows(self) -> List[Dict[str, Any]]:
        return [self._by_id[i] for i in self.picker.ids() if i in self._by_id]

    def _on_rows(self, rows: List[dict]) -> None:
        ordered = base_order(rows)
        self._by_id = {}
        for r in ordered:
            self._by_id.setdefault(r.get("id"), r)
        self._requested.clear()              # asked again below (plots already held are kept)
        self.banner.hide()
        self.picker.set_rows(ordered)
        self._request_missing()
        self._update_all()

    def _ids_changed(self, ids: List[int]) -> None:
        for i in list(self._requested):
            if i not in ids:
                self._requested.discard(i)
        for i in list(self._graphs):
            if i not in ids:
                del self._graphs[i]
        self._failed.intersection_update(ids)
        self._request_missing()
        self._update_all()

    def _request_missing(self) -> None:
        for i in self.picker.ids():
            if i not in self._requested and i not in self._graphs:
                self._requested.add(i)
                self._loader.request_graph(i)

    def _on_graph(self, id: int, raw) -> None:
        if id not in self.picker.ids():
            return                           # the run was removed while its plot was on the way
        if raw is None:                      # the fetch failed: note it, and ask again next time
            self._failed.add(id)
            self._requested.discard(id)
        else:
            self._failed.discard(id)
            self._graphs[id] = raw
        self._update_overlay()

    def _on_failed(self, kind: str, msg: str) -> None:
        if not self._by_id:
            return
        self.banner_label.setText("Can't reach the database: %s" % msg)
        self.banner.show()

    # ---- views ----
    def _update_all(self) -> None:
        has = bool(self.picker.ids())
        self._prompt.setVisible(not has)
        self._charts.setVisible(has)
        if has:
            self._update_overlay()
            self._update_metric()
            self._update_params()

    def _update_overlay(self, *_a) -> None:
        rows = self._rows()
        opts = self.options()
        runs, boxes, missing, loading, failed = [], [], [], False, []
        for i, row in enumerate(rows):
            boxes.append(box_text(row) if opts.guides else None)
            if row.get("id") in self._failed:
                runs.append(None)
                failed.append(label_of(row))
                continue
            if row.get("id") not in self._graphs:
                runs.append(None)
                loading = True
                continue
            try:
                run = overlay_run(row, self._graphs[row.get("id")], i, opts)
            except Exception:
                run = None
            if run is None:
                missing.append(label_of(row))
            runs.append(run)
        self._no_waveform = missing
        self.overlay.set_runs(runs, opts, boxes)
        drawn = bool(self.overlay.curve_names())
        self.overlay.setVisible(drawn)
        msg = "" if drawn else ("Loading…" if loading else NO_WAVEFORM_ANY if rows else "")
        self._overlay_msg.setText(msg)
        self._overlay_msg.setVisible(bool(msg))
        notes = ([NO_WAVEFORM_NOTE + ", ".join(missing)] if missing else []) + \
                ([GRAPH_FAILED_NOTE + ", ".join(failed)] if failed else [])
        self._footnote.setText("\n".join(notes))
        self._footnote.setVisible(bool(notes))

    def _update_metric(self, *_a) -> None:
        rows = self._rows()
        key = self.metric_combo.currentData()
        self.metric_chart.set_values([run_label_text(r) for r in rows], [metric_value(key, r) for r in rows],
                               [run_colors(i)[0] for i in range(len(rows))], self.metric_combo.currentText())

    def _update_params(self, *_a) -> None:
        rows = self._rows()
        diff = differing_rows(rows)
        self.diff_check.setText("Only rows that differ (%d)" % len(diff))
        self.diff_check.setVisible(len(rows) >= 2)
        cards = self.view_mode() == "cards"
        self.param_table.setVisible(not cards)
        self._cards.setVisible(cards)
        if cards:
            self._fill_cards(rows)
        else:
            self._fill_table(rows, diff)

    def _fill_table(self, rows: List[Dict[str, Any]], diff: Set[str]) -> None:
        only = self.diff_check.isChecked() and len(rows) >= 2
        params = [(l, g) for l, g in PARAM_ROWS if not only or l in diff]
        t = self.param_table
        t.clear()
        t.setColumnCount(1 + len(rows))
        t.setRowCount(len(params))
        t.setHorizontalHeaderItem(0, QTableWidgetItem("Parameter"))
        for c, r in enumerate(rows):
            h = QTableWidgetItem(run_label_text(r))
            h.setIcon(_dot_icon(run_colors(c)[0]))
            t.setHorizontalHeaderItem(c + 1, h)
        tint = QBrush(QColor(theme.P.accent_soft))
        for i, (label, _) in enumerate(params):
            cells = [label] + [param_value(label, r) for r in rows]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                it.setData(Qt.TextAlignmentRole, int((Qt.AlignLeft if c == 0 else Qt.AlignRight) | Qt.AlignVCenter))
                if label in diff:
                    it.setBackground(tint)
                t.setItem(i, c, it)
        t.resizeColumnsToContents()
        t.horizontalHeader().setStretchLastSection(True)
        t.setFixedHeight(t.horizontalHeader().height() + len(params) * t.verticalHeader().defaultSectionSize() + 4)

    def _fill_cards(self, rows: List[Dict[str, Any]]) -> None:
        while self._cards_grid.count():
            it = self._cards_grid.takeAt(0)
            if it.widget() is not None:
                it.widget().deleteLater()
        self._card_tables = []
        for n, r in enumerate(rows):
            card = QFrame()
            theme.set_role(card, "card")
            lay = QVBoxLayout(card)
            lab = QLabel(run_label_text(r))
            lab.setToolTip(label_of(r))
            lab.setStyleSheet("font-weight: 600;")
            lay.addWidget(lab)
            t = QTableWidget(len(PARAM_ROWS), 2)
            t.horizontalHeader().hide()
            t.verticalHeader().hide()
            t.setEditTriggers(QAbstractItemView.NoEditTriggers)
            t.setSelectionMode(QAbstractItemView.NoSelection)
            t.setShowGrid(False)
            t.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            for i, (label, _) in enumerate(PARAM_ROWS):
                a = QTableWidgetItem(label)
                a.setForeground(QBrush(QColor(theme.P.text_muted)))
                b = QTableWidgetItem(param_value(label, r))
                b.setData(Qt.TextAlignmentRole, int(Qt.AlignRight | Qt.AlignVCenter))
                t.setItem(i, 0, a)
                t.setItem(i, 1, b)
            t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            t.resizeColumnToContents(1)
            t.setFixedHeight(len(PARAM_ROWS) * t.verticalHeader().defaultSectionSize() + 4)
            lay.addWidget(t)
            self._cards_grid.addWidget(card, n // 2, n % 2)
            self._card_tables.append(t)
