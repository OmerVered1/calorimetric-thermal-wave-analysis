"""History tab of the Results tab: every saved analysis in a sortable table, and beside it the selected
run's numbers, stored plot and full details (app/history/page.tsx)."""
from __future__ import annotations

from datetime import datetime
from functools import cmp_to_key
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QMessageBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QSplitter, QStackedLayout, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ctwa import theme
from ctwa.analysis.lag_fit import describe_lag_model
from ctwa.analysis.references import material_color
from ctwa.results.helpers import format_alpha
from ctwa.ui.results.figure_view import FigureView
from ctwa.ui.results.fmt import (HISTORY_SEARCH_FIELDS, compare_cells, js_str, js_to_fixed, matches_fields,
                                 next_sort, run_label_text)
from ctwa.ui.results.summary_logic import base_order
from ctwa.ui.results.undo_bar import UndoBar

__all__ = ["HistoryTab", "HISTORY_COLS"]

DASH = "—"
HISTORY_COLS = [
    ("id", "ID"), ("model_name", "Model"), ("test_date", "Date"), ("analysis_mode", "Mode"),
    ("r1_mm", "r₁"), ("r2_mm", "r₂"), ("alpha_combined_raw", "α comb (raw)"),
    ("alpha_phase_raw", "α phase (raw)"), ("use_calibration", "Cal"), ("temperature_c", "T (°C)"),
]
_TEXT_COLS = {"model_name", "test_date", "analysis_mode", "use_calibration"}


def _tpl(v: Any) -> str:
    """A JS template literal: `${v}` (null shows as "null")."""
    return "null" if v is None else js_str(v)


def _safe(v: Any, digits: int) -> str:
    """safe() of the page: null and 0 give "—", else toFixed."""
    if v is None or v == 0 or isinstance(v, bool):
        return DASH
    try:
        return js_to_fixed(float(v), digits)
    except (TypeError, ValueError):
        return DASH


def _created(v: Any) -> str:
    if not v:
        return DASH
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return str(v)
    return "%d/%d/%d, %d:%02d:%02d %s" % (d.month, d.day, d.year, (d.hour % 12) or 12, d.minute, d.second,
                                         "AM" if d.hour < 12 else "PM")


def cell_text(row: Dict[str, Any], key: str) -> str:
    v = row.get(key)
    if key in ("alpha_combined_raw", "alpha_phase_raw"):
        return format_alpha(v)
    if key == "use_calibration":
        return "✓" if v else "✗"
    if key == "temperature_c":
        return js_str(v) if v is not None else DASH
    return DASH if v is None else js_str(v)


def sorted_rows(rows: List[Dict[str, Any]], state: tuple) -> List[Dict[str, Any]]:
    key, direction = state
    if not key or not direction:
        return list(rows)
    sign = 1 if direction == "asc" else -1

    def cmp(a, b) -> int:
        c = compare_cells(a.get(key), b.get(key), key)
        return 0 if c != c else sign * ((c > 0) - (c < 0))
    return sorted(rows, key=cmp_to_key(cmp))   # stable, as Array.sort


def _ref_ids(row: Dict[str, Any]) -> List[str]:
    return [s.strip() for s in js_str(row.get("calibration_ref_ids")).split(",") if s.strip()]


def detail_pairs(r: Dict[str, Any]) -> Dict[str, str]:
    """The "Full Details" table, in the webapp's order."""
    d: Dict[str, str] = {}
    d["Created"] = _created(r.get("created_at"))
    d["Model"] = js_str(r.get("model_name"))
    d["Test Date"] = js_str(r.get("test_date"))
    d["Radii"] = "r₁=%smm, r₂=%smm" % (_tpl(r.get("r1_mm")), _tpl(r.get("r2_mm")))
    d["Temperature"] = "%s°C" % (js_str(r.get("temperature_c")) if r.get("temperature_c") is not None else "25")
    d["Gas Atmosphere"] = js_str(r.get("gas_atmosphere")) if r.get("gas_atmosphere") else DASH
    d["Source Period T"] = "%ss" % _safe(r.get("period_t"), 2)
    d["Response Period T"] = "%ss" % _safe(r.get("period_t_resp"), 2) if r.get("period_t_resp") is not None else DASH
    d["Source Frequency"] = "%sHz" % _safe(r.get("frequency_f"), 5)
    d["Response Frequency"] = ("%sHz" % _safe(r.get("frequency_f_resp"), 5)
                               if r.get("frequency_f_resp") is not None else DASH)
    d["Raw Δt"] = "%ss" % _safe(r.get("raw_lag_dt"), 2)
    d["α Combined (raw)"] = "%s mm²/s" % format_alpha(r.get("alpha_combined_raw"))
    d["α Phase (raw)"] = "%s mm²/s" % format_alpha(r.get("alpha_phase_raw"))
    if r.get("use_calibration"):
        d["System Lag"] = "%ss" % _safe(r.get("system_lag"), 1)
        d["Net Δt"] = "%ss" % _safe(r.get("net_lag_dt"), 2)
        d["α Combined (cal)"] = "%s mm²/s" % format_alpha(r.get("alpha_combined_cal"))
        d["α Phase (cal)"] = "%s mm²/s" % format_alpha(r.get("alpha_phase_cal"))
    ids = _ref_ids(r)
    if ids:
        via = "single reference" if len(ids) == 1 else "%d references" % len(ids)
        d["Calibrated via"] = "%s · %s" % (via, describe_lag_model(r.get("calibration_model")))
        d["reference(s)"] = ", ".join("#%s" % i for i in ids)
        if r.get("calibration_model"):
            d["Device-lag curve lag(P)"] = js_str(r.get("calibration_model"))
        if r.get("calibrated_from_id") is not None:
            d["Copy of run"] = "#%s" % js_str(r.get("calibrated_from_id"))
    if r.get("is_reference"):
        d["Known α (mm²/s)"] = "%s mm²/s" % _safe(r.get("reference_alpha_mm2s"), 3)
    return d


def _lag_text(r: Dict[str, Any]) -> str:
    if r.get("use_calibration"):
        lag = r.get("system_lag")
        return "Cal (Lag: %ss)" % (js_str(lag) if lag is not None else "0")
    return "No Cal"


class _Table(QTableWidget):
    step = Signal(int)

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key_Down, Qt.Key_Up):
            self.step.emit(1 if e.key() == Qt.Key_Down else -1)
            e.accept()
            return
        super().keyPressEvent(e)


def _ask_delete(title: str, message: str) -> bool:
    box = QMessageBox(QMessageBox.Warning, title, message)
    delete = box.addButton("Delete", QMessageBox.DestructiveRole)
    box.addButton("Cancel", QMessageBox.RejectRole)
    box.exec()
    return box.clickedButton() is delete


class HistoryTab(QWidget):
    """Delete flow (as the webapp's history page): confirm, hide the row at once, an Undo toast for
    ``delay_ms``, then ``loader.apply_delete``. Closing the tab (or ``flush_pending()``, which the app calls
    on quit) sends the pending deletes at once, as the webapp does when the page closes. A delete ends only
    by its own token-matched write_done / write_failed; the loader's read-error ``failed`` never does."""
    open_in_viewer = Signal(int)
    message = Signal(str)
    login_needed = Signal()

    def __init__(self, loader, parent: Optional[QWidget] = None,
                 confirm: Optional[Callable[[str, str], bool]] = None, delay_ms: int = 6000) -> None:
        super().__init__(parent)
        self._loader = loader
        self._confirm = confirm or _ask_delete
        self._delay_ms = delay_ms
        self._confirming = False
        self._sent: Dict[Any, Any] = {}              # id -> token (None while apply_delete is running)
        self._inflight: Dict[Any, Any] = {}          # token -> id
        self._done_seen: Dict[Any, int] = {}         # id -> refreshes that still listed it after write_done
        self._calling: Optional[Any] = None
        self._early: Optional[Any] = None
        self._rows: List[Dict[str, Any]] = []        # base order, with ln validity
        self._by_id: Dict[Any, Dict[str, Any]] = {}
        self._shown: List[Dict[str, Any]] = []       # what the table lists (search, sort, pending)
        self._pending: set = set()                   # hidden by a delete in progress
        self._selected: Optional[int] = None
        self._want: Optional[int] = None
        self._sort: tuple = (None, None)
        self._search = ""
        self._loaded = False
        self._failed_text = ""
        self._syncing = False
        self._detail: Dict[str, str] = {}
        self._kpis: List[str] = []
        self._build()
        loader.rows_changed.connect(self._on_rows)
        loader.failed.connect(self._on_failed)
        loader.graph_loaded.connect(self._on_graph)
        loader.write_done.connect(self._on_write_done)
        loader.write_failed.connect(self._on_write_failed)
        rows = loader.rows()
        if rows:
            self._on_rows(rows)
        else:
            self._refresh_view()

    # ---- construction ----
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self._stack = QStackedLayout()
        root.addLayout(self._stack, 1)
        self._msg = QLabel()
        self._msg.setAlignment(Qt.AlignCenter)
        theme.set_role(self._msg, "muted")
        self._stack.addWidget(self._msg)

        self._page = QWidget()
        page_lay = QVBoxLayout(self._page)
        page_lay.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Horizontal)
        page_lay.addWidget(split, 1)
        self._bottom = QVBoxLayout()
        self.error_label = QLabel()
        theme.set_role(self.error_label, "danger")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        self.undo_bar = UndoBar()
        self.undo_bar.undone.connect(self._on_undone)
        self.undo_bar.expired.connect(self._send)
        self._bottom.addWidget(self.error_label)
        self._bottom.addWidget(self.undo_bar)
        page_lay.addLayout(self._bottom)
        self._stack.addWidget(self._page)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 6, 0)
        head = QHBoxLayout()
        self.title = QLabel()
        theme.set_role(self.title, "heading")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search name, date, mode, °C or #id")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumWidth(220)
        self.search_edit.textChanged.connect(self.set_search)
        head.addWidget(self.title, 1)
        head.addWidget(self.search_edit)
        ll.addLayout(head)
        self.table = _Table(0, len(HISTORY_COLS))
        self.table.setHorizontalHeaderLabels([label for _, label in HISTORY_COLS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(theme.ROW_HEIGHT)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self.table.horizontalHeader().setSectionsClickable(True)
        self.table.horizontalHeader().sectionClicked.connect(lambda c: self.header_click(HISTORY_COLS[c][0]))
        self.table.itemSelectionChanged.connect(self._table_selection)
        self.table.step.connect(self._step)
        ll.addWidget(self.table, 1)
        split.addWidget(left)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.panel = QFrame()
        theme.set_role(self.panel, "card")
        pl = QVBoxLayout(self.panel)
        sub = QLabel("View Details")
        theme.set_role(sub, "faint")
        pl.addWidget(sub)
        title_row = QHBoxLayout()
        self._dot_holder = QHBoxLayout()
        self._dot = theme.swatch(theme.P.border, 10)
        self._dot_holder.addWidget(self._dot)
        self.run_label = QLabel()
        theme.set_role(self.run_label, "heading")
        self.run_label.setWordWrap(True)
        title_row.addLayout(self._dot_holder)
        title_row.addWidget(self.run_label, 1)
        pl.addLayout(title_row)
        self.sub_label = QLabel()
        theme.set_role(self.sub_label, "faint")
        pl.addWidget(self.sub_label)
        btns = QHBoxLayout()
        self.open_button = QPushButton("Open in Viewer")
        self.open_button.clicked.connect(self._open_clicked)
        self.delete_button = QPushButton("Delete")
        theme.set_role(self.delete_button, "danger")
        self.delete_button.setToolTip("Delete Result")
        self.delete_button.clicked.connect(self.delete_selected)
        btns.addWidget(self.open_button)
        btns.addWidget(self.delete_button)
        btns.addStretch(1)
        pl.addLayout(btns)
        grid = QHBoxLayout()
        self._kpi_labels: List[QLabel] = []
        self._kpi_values: List[QLabel] = []
        self._kpi_frames: List[QFrame] = []
        for i in range(4):
            f = QFrame()
            theme.set_role(f, "card")
            fl = QVBoxLayout(f)
            k = QLabel()
            theme.set_role(k, "stat-label")
            v = QLabel()
            theme.set_role(v, "heading")
            fl.addWidget(k)
            fl.addWidget(v)
            grid.addWidget(f)
            self._kpi_labels.append(k)
            self._kpi_values.append(v)
            self._kpi_frames.append(f)
        pl.addLayout(grid)
        pl.addWidget(self._faint("Select analysis to view"))
        self.combo = QComboBox()
        self.combo.currentIndexChanged.connect(self._combo_changed)
        pl.addWidget(self.combo)
        self.figure = FigureView()
        self.figure.setMinimumHeight(300)
        pl.addWidget(self.figure, 1)
        fd = QLabel("Full Details:")
        fd.setStyleSheet("font-weight: 600;")
        pl.addWidget(fd)
        self.details = QTableWidget(0, 2)
        self.details.horizontalHeader().hide()
        self.details.verticalHeader().hide()
        self.details.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.details.setSelectionMode(QAbstractItemView.NoSelection)
        self.details.setShowGrid(False)
        self.details.horizontalHeader().setStretchLastSection(True)
        self.details.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        pl.addWidget(self.details)
        scroll.setWidget(self.panel)
        split.addWidget(scroll)
        split.setSizes([680, 560])
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        self.scroll_area = scroll

    @staticmethod
    def _faint(text: str) -> QLabel:
        lab = QLabel(text)
        theme.set_role(lab, "faint")
        return lab

    # ---- public ----
    def selected_id(self) -> Optional[int]:
        return self._selected

    def select_id(self, id: Optional[int]) -> None:
        if not self._rows:
            self._want = id
            return
        if id is not None and id not in self._by_id:
            return
        self._select(id)

    def set_search(self, text: str) -> None:
        if text != self.search_edit.text():
            self.search_edit.setText(text)
            return
        self._search = text
        self._refresh_view()

    def detail_text(self) -> Dict[str, str]:
        return dict(self._detail)

    def kpis(self) -> List[str]:
        return list(self._kpis)

    def figure_view(self) -> FigureView:
        return self.figure

    def title_text(self) -> str:
        return self.title.text()

    def header_line(self) -> str:
        return self.sub_label.text()

    def message_text(self) -> str:
        return self._msg.text() if self._stack.currentWidget() is self._msg else ""

    def sort_state(self) -> tuple:
        return self._sort

    def header_click(self, key: str) -> None:
        self._sort = next_sort(self._sort, key)
        self._refresh_view()

    # ---- loader ----
    def _on_rows(self, rows: List[dict]) -> None:
        prev = [r.get("id") for r in self._shown]
        self._rows = base_order(rows)
        self._by_id = {}
        for r in self._rows:
            self._by_id.setdefault(r.get("id"), r)
        self._prune_pending()
        self._loaded = True
        self._failed_text = ""
        self._after_rows(prev)

    def _prune_pending(self) -> None:
        for id in list(self._pending):
            if id not in self._by_id:                # gone (deleted, or removed elsewhere)
                self._pending.discard(id)
                self.undo_bar.discard(id)            # nothing left to undo or send
                self._sent.pop(id, None)
                self._done_seen.pop(id, None)
            elif id in self._done_seen:              # deleted, yet a refresh still lists it
                self._done_seen[id] += 1
                if self._done_seen[id] >= 2:         # the second one is surely after the delete: show it
                    self._pending.discard(id)
                    self._sent.pop(id, None)
                    del self._done_seen[id]

    def _after_rows(self, prev_shown_ids: List[Any]) -> None:
        sel = self._selected
        want, self._want = self._want, None
        if sel is not None and sel not in self._by_id:
            sel = self._neighbour(sel, prev_shown_ids)
        if sel is None and self._rows:
            first = next((r.get("id") for r in self._rows if r.get("id") not in self._pending), None)
            sel = want if want in self._by_id else first
        self._refresh_view(select=sel)

    def _neighbour(self, gone: Any, order: List[Any]) -> Optional[int]:
        """The row after the one that went (else before it), among those still present."""
        if gone in order:
            i = order.index(gone)
            for j in order[i + 1:] + order[:i][::-1]:
                if j in self._by_id and j not in self._pending:
                    return j
        return None

    def _on_failed(self, kind: str, msg: str) -> None:
        # a read error: only a message; whatever is on screen stays (it never settles a delete)
        self._loaded = True
        self._failed_text = "Can't reach the database: %s" % msg
        self._refresh_view()

    def _on_graph(self, id: int, raw) -> None:
        if id != self._selected:
            return          # a slow graph of a row that is no longer selected
        row = self._by_id.get(id)
        if row is None:
            return
        self.figure.show_graph(raw, row)

    # ---- view ----
    def _visible_rows(self) -> List[Dict[str, Any]]:
        rows = [r for r in self._rows if r.get("id") not in self._pending]
        return sorted_rows([r for r in rows if matches_fields(r, self._search, HISTORY_SEARCH_FIELDS)], self._sort)

    def _refresh_view(self, select: Any = "keep") -> None:
        if select != "keep":
            self._selected_set(select)
        self._shown = self._visible_rows()
        total = len(self._rows) - len(self._pending & set(self._by_id))
        shown = len(self._shown)
        self.title.setText("All Analyses (%s%d total)" % ("%d / " % shown if shown < total else "", total))
        if not self._rows:
            self._msg.setText("No data" if self._loaded and not self._failed_text else
                              self._failed_text or "Loading…")
            self._stack.setCurrentWidget(self._msg)
            return
        self._stack.setCurrentWidget(self._page)
        self._fill_table()
        self._fill_combo()
        self._show_detail()

    def _fill_table(self) -> None:
        t = self.table
        self._syncing = True
        try:
            t.setRowCount(len(self._shown))
            for r, row in enumerate(self._shown):
                for c, (key, _) in enumerate(HISTORY_COLS):
                    it = QTableWidgetItem(cell_text(row, key))
                    it.setData(Qt.UserRole, row.get("id"))
                    align = Qt.AlignLeft if key in _TEXT_COLS else Qt.AlignRight
                    it.setData(Qt.TextAlignmentRole, int(align | Qt.AlignVCenter))
                    t.setItem(r, c, it)
            key, direction = self._sort
            hh = t.horizontalHeader()
            if key and direction:
                hh.setSortIndicator([k for k, _ in HISTORY_COLS].index(key),
                                    Qt.AscendingOrder if direction == "asc" else Qt.DescendingOrder)
            else:
                hh.setSortIndicator(-1, Qt.AscendingOrder)
            self._sync_table_selection()
        finally:
            self._syncing = False

    def _sync_table_selection(self) -> None:
        ids = [r.get("id") for r in self._shown]
        self._syncing = True
        try:
            if self._selected in ids:
                i = ids.index(self._selected)
                self.table.selectRow(i)
                self.table.scrollToItem(self.table.item(i, 0), QAbstractItemView.EnsureVisible)
            else:
                self.table.clearSelection()
        finally:
            self._syncing = False

    def _fill_combo(self) -> None:
        self.combo.blockSignals(True)
        self.combo.clear()
        for r in self._rows:
            self.combo.addItem("%s | %s | %s | %s" % (_tpl(r.get("model_name")), _tpl(r.get("test_date")),
                                                      _tpl(r.get("analysis_mode")), _lag_text(r)), r.get("id"))
        i = self.combo.findData(self._selected)
        self.combo.setCurrentIndex(i)
        self.combo.blockSignals(False)

    def _show_detail(self) -> None:
        r = self._by_id.get(self._selected)
        self.panel.setVisible(r is not None)
        if r is None:
            self._detail, self._kpis = {}, []
            return
        self._dot.setStyleSheet("background: %s; border-radius: 5px;" % material_color(r.get("model_name")))
        self.run_label.setText(run_label_text(r))
        self.sub_label.setText("%s · %s · %s" % (js_str(r.get("test_date")), js_str(r.get("analysis_mode")),
                                                 _lag_text(r)))
        cal = bool(r.get("use_calibration"))
        a_phase = format_alpha(r.get("alpha_phase_cal") if cal else r.get("alpha_phase_raw"))
        a_comb = format_alpha(r.get("alpha_combined_cal") if cal else r.get("alpha_combined_raw"))
        self._kpis = [a_phase, a_comb, _safe(r.get("period_t"), 1), _safe(r.get("raw_lag_dt"), 1)]
        names = ["α phase (%s)" % ("cal" if cal else "raw"), "α comb (%s)" % ("cal" if cal else "raw"),
                 "Source Period T", "Raw Δt"]
        units = ["mm²/s", "mm²/s", "s", "s"]
        for i in range(4):
            self._kpi_labels[i].setText(names[i])
            v = self._kpis[i]
            self._kpi_values[i].setText(v if v == DASH else "%s %s" % (v, units[i]))
            theme.set_prop(self._kpi_frames[i], tone="accent" if i == 0 else "")
        self._detail = detail_pairs(r)
        d = self.details
        d.setRowCount(len(self._detail))
        for i, (k, v) in enumerate(self._detail.items()):
            ki = QTableWidgetItem(k)
            ki.setForeground(self.palette().mid())
            d.setItem(i, 0, ki)
            d.setItem(i, 1, QTableWidgetItem(v))
        d.resizeColumnToContents(0)
        d.setFixedHeight(len(self._detail) * (d.verticalHeader().defaultSectionSize()) + 4)

    # ---- selection ----
    def _selected_set(self, id: Optional[int]) -> bool:
        """Change the selection; returns True when it changed (and the graph was requested)."""
        if id == self._selected:
            return False
        self._selected = id
        if id is not None:
            self.figure.show_loading()
            self._loader.request_graph(id)
        else:
            self.figure.clear()
        return True

    def _select(self, id: Optional[int]) -> None:
        if self._selected_set(id):
            self._show_detail()
            self._sync_combo()
            self._sync_table_selection()

    def _sync_combo(self) -> None:
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(self.combo.findData(self._selected))
        self.combo.blockSignals(False)

    def _table_selection(self) -> None:
        if self._syncing:
            return
        rows = self.table.selectionModel().selectedRows()
        if rows:
            self._select(self.table.item(rows[0].row(), 0).data(Qt.UserRole))

    def _combo_changed(self, i: int) -> None:
        if i >= 0:
            self._select(self.combo.itemData(i))

    def _step(self, d: int) -> None:
        ids = [r.get("id") for r in self._shown]
        if not ids:
            return
        i = ids.index(self._selected) if self._selected in ids else -1
        self._select(ids[max(0, min(len(ids) - 1, i + d))])

    def _open_clicked(self) -> None:
        if self._selected is not None:
            self.open_in_viewer.emit(self._selected)

    # ---- delete ----
    def pending_ids(self) -> List[int]:
        return sorted(self._pending)

    def error_text(self) -> str:
        return self.error_label.text()

    def _set_error(self, text: str) -> None:
        self.error_label.setText(text)
        self.error_label.setVisible(bool(text))

    def delete_selected(self) -> None:
        id = self._selected
        row = self._by_id.get(id)
        if row is None or id in self._pending or self._confirming:
            return
        self._confirming = True
        self.delete_button.setEnabled(False)
        try:
            ok = self._confirm("Delete this analysis?", '"%s" (ID %s) will be removed from the database '
                               'permanently.' % (js_str(row.get("model_name")), js_str(id)))
        finally:
            self._confirming = False
            self.delete_button.setEnabled(True)
        if not ok or id not in self._by_id or id in self._pending:    # the list may have changed meanwhile
            return
        ids = [r.get("id") for r in self._shown]
        neighbour = None
        if id in ids:
            i = ids.index(id)
            after, before = ids[i + 1:i + 2], (ids[i - 1:i] if i > 0 else [])
            neighbour = (after or before or [None])[0]
        self._set_error("")
        self._pending.add(id)
        self.undo_bar.add(id, self._delay_ms)
        self._refresh_view(select=neighbour)

    def flush_pending(self) -> None:
        """Send every delete still waiting out its Undo window, now."""
        self.undo_bar.flush()

    def _on_undone(self, id: int) -> None:
        self._pending.discard(id)
        self._refresh_view(select=id if id in self._by_id else "keep")

    def _send(self, id: int) -> None:
        if id in self._sent:                         # never twice
            return
        self._sent[id] = None
        self._calling, self._early = id, None
        try:
            token = self._loader.apply_delete(id)
        finally:
            self._calling = None
        if self._early is not None:                  # failed before the token came back; already settled
            self._early = None
            return
        self._sent[id] = token
        self._inflight[token] = id

    def _on_write_done(self, op: str, token: int, _result) -> None:
        id = self._inflight.pop(token, None) if op == "delete" else None
        if id is None:
            return
        self._sent.pop(id, None)
        if id in self._by_id:
            self._done_seen[id] = 0                  # stays hidden until a refresh no longer lists it

    def _on_write_failed(self, op: str, token: int, kind: str, msg: str) -> None:
        if op != "delete":
            return
        id = self._inflight.pop(token, None)
        if id is None and self._calling is not None and self._sent.get(self._calling, 0) is None:
            id, self._early = self._calling, self._calling     # the loader failed inside apply_delete
        if id is None:
            return
        self._sent.pop(id, None)
        self._pending.discard(id)
        text = "Failed to delete: %s" % msg
        self._set_error(text)
        self.message.emit(text)
        if kind == "login":
            self.login_needed.emit()
        self._refresh_view()

    def closeEvent(self, e) -> None:
        self.flush_pending()
        super().closeEvent(e)
