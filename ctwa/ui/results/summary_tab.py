"""The Summary page of the Results tab: stat cards, filters, a 27-column table with the first three
columns frozen, selection bar, CSV. Reads rows only from the shared ResultsLoader."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set

from PySide6.QtCore import QModelIndex, QSettings, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QMessageBox, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QPushButton, QStackedLayout,
                               QTableView, QToolButton, QVBoxLayout, QWidget)

from ctwa import theme
from ctwa.ui.results.fmt import next_sort
from ctwa.ui.results.summary_edit import EditSession, SummaryDelegate, initial_values
from ctwa.ui.results.summary_logic import (ALWAYS_SHOWN, PRESETS, SUMMARY_COLS, csv_bytes, filter_rows,
                                           hidden_for_preset, preset_of, summary_stats)
from ctwa.ui.results.summary_model import ID_ROLE, SummaryModel, SummaryProxy

__all__ = ["SummaryTab", "SummaryTable"]

HIDDEN_KEY = "results/summary/hidden"
DENSITY_KEY = "results/summary/density"
FROZEN = 3                     # check, ID, Model
MAX_COMPARE = 4
COL0_W = 36
COL0_EDIT_W = 150               # check box, Edit / Save + Cancel
_KEYS = [c.key for c in SUMMARY_COLS]
_PRESET_LABELS = (("key", "Key results"), ("cal", "Calibration"), ("all", "Everything"))
_HINT = "Double-click a cell to edit · Enter saves · Esc cancels"


class _MemSettings:
    """Stands in when no QSettings is given: nothing is written to disk."""
    def __init__(self) -> None:
        self._d: Dict[str, Any] = {}

    def value(self, key, default=None):
        return self._d.get(key, default)

    def setValue(self, key, value) -> None:
        self._d[key] = value


class SummaryTable(QTableView):
    """The table; its first FROZEN columns live in an overlay view that does not scroll sideways."""

    def __init__(self, proxy: SummaryProxy, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setModel(proxy)
        self.frozen = QTableView(self)
        self.frozen.setModel(proxy)
        for v in (self, self.frozen):
            v.setSelectionMode(QAbstractItemView.NoSelection)
            v.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
            v.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
            v.verticalHeader().hide()
            v.horizontalHeader().setSectionsClickable(True)
            v.horizontalHeader().setHighlightSections(False)
            v.setAlternatingRowColors(True)
            v.setShowGrid(False)
            v.setWordWrap(False)
            v.setTextElideMode(Qt.ElideRight)
        self.frozen.setFocusPolicy(Qt.NoFocus)
        self.frozen.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.frozen.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.frozen.setFrameShape(QFrame.NoFrame)
        for c in range(FROZEN, proxy.columnCount()):
            self.frozen.setColumnHidden(c, True)
        for c in range(proxy.columnCount()):
            self.horizontalHeader().setSectionResizeMode(c, QHeaderView.Interactive)
        # two views, one scroll position and one set of widths
        self.verticalScrollBar().valueChanged.connect(self._to_frozen)
        self.frozen.verticalScrollBar().valueChanged.connect(self._from_frozen)
        self.horizontalHeader().sectionResized.connect(self._section_resized)
        self.frozen.horizontalHeader().sectionResized.connect(self._frozen_section_resized)
        self.verticalHeader().sectionResized.connect(lambda *_: None)
        self._default_widths()
        self.update_frozen_geometry()

    def _default_widths(self) -> None:
        fm = self.fontMetrics()
        for c in range(self.model().columnCount()):
            if c == 0:
                w = COL0_W
            else:
                col = SUMMARY_COLS[c - 1]
                w = {"id": 60, "model_name": 170, "test_date": 100, "gas_atmosphere": 90,
                     "analysis_mode": 100, "calibration_model": 90}.get(
                    col.key, max(78, fm.horizontalAdvance(col.label) + 36))
            self.setColumnWidth(c, w)
            self.frozen.setColumnWidth(c, w)

    def set_col0_width(self, w: int) -> None:
        self.setColumnWidth(0, w)

    def set_row_height(self, h: int) -> None:
        for v in (self, self.frozen):
            v.verticalHeader().setDefaultSectionSize(h)
            v.verticalHeader().setMinimumSectionSize(min(h, 16))
            for r in range(v.model().rowCount()):
                v.setRowHeight(r, h)

    def frozen_width(self) -> int:
        return sum(self.columnWidth(c) for c in range(FROZEN))

    def update_frozen_geometry(self) -> None:
        self.frozen.setGeometry(self.frameWidth(), self.frameWidth(), self.frozen_width(),
                                self.viewport().height() + self.horizontalHeader().height())

    def _section_resized(self, c: int, _old: int, new: int) -> None:
        if c < FROZEN:
            if self.frozen.columnWidth(c) != new:
                self.frozen.setColumnWidth(c, new)
            self.update_frozen_geometry()

    def _frozen_section_resized(self, c: int, _old: int, new: int) -> None:
        if c < FROZEN and self.columnWidth(c) != new:
            self.setColumnWidth(c, new)

    def _to_frozen(self, v: int) -> None:
        if self.frozen.verticalScrollBar().value() != v:
            self.frozen.verticalScrollBar().setValue(v)

    def _from_frozen(self, v: int) -> None:
        if self.verticalScrollBar().value() != v:
            self.verticalScrollBar().setValue(v)

    def updateGeometries(self) -> None:
        super().updateGeometries()
        if hasattr(self, "frozen"):
            self.update_frozen_geometry()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.update_frozen_geometry()

    def wheelEvent(self, e) -> None:
        super().wheelEvent(e)

    def view_for_column(self, col: int) -> QTableView:
        return self.frozen if col < FROZEN else self

    def row_rect(self, proxy_index: QModelIndex):
        v = self.view_for_column(proxy_index.column())
        return v.visualRect(proxy_index)


class SummaryTab(QWidget):
    compare_requested = Signal(list)
    message = Signal(str)
    login_needed = Signal()

    def __init__(self, loader, settings: Optional[QSettings] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._loader = loader
        self._settings = settings if settings is not None else _MemSettings()
        self._loaded = False
        self._session: Optional[EditSession] = None
        self._reopening = False
        self._failed_text = ""
        self._id_filter: Optional[Set[int]] = None
        self._sort: tuple = (None, None)
        self._hidden: Set[str] = self._read_hidden()
        d = str(self._settings.value(DENSITY_KEY, "compact"))
        self._density = d if d in ("compact", "comfortable") else "compact"

        self.model = SummaryModel(self)
        self.proxy = SummaryProxy(self)
        self.proxy.setSourceModel(self.model)
        self._build()
        self._delegate = SummaryDelegate(lambda: self._session, self.model.row_by_id, self.commit_edit,
                                         self.cancel_edit, self)
        self._delegate.key_handler = self._on_edit_key
        self._delegate.edit_requested.connect(lambda i, k: self.begin_edit(i, k or None))
        for v in (self.table, self.table.frozen):
            v.setItemDelegate(self._delegate)
            v.doubleClicked.connect(self._cell_double_clicked)
        self.table.set_col0_width(COL0_EDIT_W)
        for sig in (self.proxy.layoutChanged, self.proxy.modelReset, self.proxy.rowsInserted,
                    self.proxy.rowsRemoved):
            sig.connect(self._reopen_editors)
        self.model.selection_changed.connect(self._selection_changed)
        self.proxy.layoutChanged.connect(self._shown_changed)
        self.proxy.modelReset.connect(self._shown_changed)
        self.proxy.rowsInserted.connect(self._shown_changed)
        self.proxy.rowsRemoved.connect(self._shown_changed)
        loader.rows_changed.connect(self._on_rows)
        loader.failed.connect(self._on_failed)
        loader.write_done.connect(self._on_write_done)
        loader.write_failed.connect(self._on_write_failed)
        self._apply_hidden()
        self._apply_density()
        rows = loader.rows()
        if rows:
            self._on_rows(rows)
        else:
            self._update_view()

    # ---- settings ----
    def _read_hidden(self) -> Set[str]:
        try:
            v = json.loads(str(self._settings.value(HIDDEN_KEY, "[]")))
            return {k for k in v if k in _KEYS and k not in ALWAYS_SHOWN} if isinstance(v, list) else set()
        except (ValueError, TypeError):
            return set()

    def _write_hidden(self) -> None:
        self._settings.setValue(HIDDEN_KEY, json.dumps(sorted(self._hidden)))

    # ---- construction ----
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("Results Summary")
        theme.set_role(title, "title")
        head.addWidget(title)
        head.addStretch(1)
        self.csv_button = QPushButton("Download CSV")
        self.csv_button.clicked.connect(self._download_all)
        head.addWidget(self.csv_button)
        root.addLayout(head)

        self.banner = QFrame()
        theme.set_role(self.banner, "card")
        bl = QHBoxLayout(self.banner)
        self.banner_label = QLabel()
        theme.set_role(self.banner_label, "danger")
        self.retry_button = QPushButton("Retry")
        self.retry_button.clicked.connect(self._retry)
        bl.addWidget(self.banner_label, 1)
        bl.addWidget(self.retry_button)
        self.banner.hide()
        root.addWidget(self.banner)

        cards = QHBoxLayout()
        self._card_values: Dict[str, QLabel] = {}
        for name in ("Total Analyses", "Unique Models", "Avg α (raw)", "Avg α (cal)"):
            f = QFrame()
            theme.set_role(f, "card")
            cl = QVBoxLayout(f)
            lab = QLabel(name)
            theme.set_role(lab, "stat-label")
            val = QLabel("—")
            theme.set_role(val, "heading")
            cl.addWidget(lab)
            cl.addWidget(val)
            cards.addWidget(f)
            self._card_values[name] = val
        root.addLayout(cards)
        self.caption = QLabel()
        theme.set_role(self.caption, "faint")
        root.addWidget(self.caption)

        bar = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search name, date, mode, °C or #id")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumWidth(220)
        self.search_edit.textChanged.connect(self._filters_changed)
        bar.addWidget(self.search_edit)
        self.model_combo = self._combo("Filter by Model")
        self.mode_combo = self._combo("Filter by Mode")
        self.cal_combo = QComboBox()
        self.cal_combo.addItem("Filter by Calibration: All", "All")
        self.cal_combo.addItem("Calibrated Only", "Calibrated Only")
        self.cal_combo.addItem("Non-Calibrated Only", "Non-Calibrated Only")
        self.cal_combo.currentIndexChanged.connect(self._filters_changed)
        for c in (self.model_combo, self.mode_combo, self.cal_combo):
            bar.addWidget(c)
        self._preset_buttons: Dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(False)
        btns = []
        for key, label in _PRESET_LABELS:
            b = QPushButton(label)
            b.setCheckable(True)
            b.clicked.connect(lambda _c=False, k=key: self.apply_preset(k))
            group.addButton(b)
            btns.append(b)
            self._preset_buttons[key] = b
        self.preset_group = group
        self.preset_bar = theme.segmented(*btns)
        self.preset_bar.setToolTip("Column set")
        bar.addWidget(self.preset_bar)
        self.columns_button = QToolButton()
        self.columns_button.setText("Columns")
        self.columns_button.setPopupMode(QToolButton.InstantPopup)
        self.columns_menu = QMenu(self.columns_button)
        self.columns_button.setMenu(self.columns_menu)
        self._column_actions: Dict[str, Any] = {}
        for c in SUMMARY_COLS:
            if c.key in ALWAYS_SHOWN:
                continue
            a = self.columns_menu.addAction(c.label)
            a.setCheckable(True)
            a.setChecked(c.key not in self._hidden)
            a.toggled.connect(lambda on, k=c.key: self._toggle_column(k, on))
            self._column_actions[c.key] = a
        self.columns_menu.addSeparator()
        self.show_all_action = self.columns_menu.addAction("Show all columns")
        self.show_all_action.triggered.connect(lambda: self.apply_preset("all"))
        bar.addWidget(self.columns_button)
        self.density_button = QPushButton()
        self.density_button.clicked.connect(self._toggle_density)
        bar.addWidget(self.density_button)
        bar.addStretch(1)
        root.addLayout(bar)

        info = QHBoxLayout()
        self.select_all = QCheckBox("Select all shown")
        self.select_all.clicked.connect(self._select_all_clicked)
        info.addWidget(self.select_all)
        self.info_label = QLabel()
        theme.set_role(self.info_label, "muted")
        info.addWidget(self.info_label)
        self.chip = QFrame()
        theme.set_role(self.chip, "card")
        chl = QHBoxLayout(self.chip)
        chl.setContentsMargins(8, 0, 2, 0)
        self.chip_label = QLabel()
        self.chip_clear = QToolButton()
        self.chip_clear.setText("×")
        self.chip_clear.setToolTip("Clear")
        self.chip_clear.clicked.connect(lambda: self.set_id_filter(None))
        chl.addWidget(self.chip_label)
        chl.addWidget(self.chip_clear)
        self.chip.hide()
        info.addWidget(self.chip)
        info.addStretch(1)
        root.addLayout(info)

        self.table = SummaryTable(self.proxy)
        self.message_label = QLabel()
        self.message_label.setAlignment(Qt.AlignCenter)
        theme.set_role(self.message_label, "muted")
        self._stack = QStackedLayout()
        self._stack.addWidget(self.table)
        self._stack.addWidget(self.message_label)
        root.addLayout(self._stack, 1)
        for h in (self.table.horizontalHeader(), self.table.frozen.horizontalHeader()):
            h.sectionClicked.connect(self._header_clicked)

        self.sel_bar = QFrame()
        theme.set_role(self.sel_bar, "toolbar")
        sl = QHBoxLayout(self.sel_bar)
        self.sel_label = QLabel()
        self.compare_button = QPushButton("Compare")
        theme.set_role(self.compare_button, "primary")
        self.compare_button.clicked.connect(self._compare)
        self.sel_csv_button = QPushButton("Download CSV")
        self.sel_csv_button.clicked.connect(self._download_selected)
        self.sel_clear = QPushButton("Clear")
        self.sel_clear.clicked.connect(self.model.clear_selection)
        sl.addWidget(self.sel_label)
        sl.addStretch(1)
        for w in (self.compare_button, self.sel_csv_button, self.sel_clear):
            sl.addWidget(w)
        self.sel_bar.hide()
        root.addWidget(self.sel_bar)

    def _combo(self, label: str) -> QComboBox:
        c = QComboBox()
        c.addItem("%s: All" % label, "All")
        c.currentIndexChanged.connect(self._filters_changed)
        return c

    # ---- public ----
    def set_search(self, text: str) -> None:
        self.search_edit.setText(text)

    def set_id_filter(self, ids: Optional[Set[int]]) -> None:
        self._id_filter = None if not ids else set(ids)
        if self._id_filter is None:
            self.chip.hide()
        else:
            self.chip_label.setText("%d runs from a link" % len(self._id_filter))
            self.chip.show()
        self._filters_changed()

    def selected_ids(self) -> List[int]:
        """Selected ids: those shown in table order, then any filtered out in the base order."""
        sel = self.model.selected_ids()
        shown = [i for i in self.proxy.shown_ids() if i in sel]
        rest = [i for i in self.model.ids() if i in sel and i not in set(shown)]
        return shown + rest

    def shown_count(self) -> int:
        return self.proxy.rowCount()

    def export_csv(self, path: str, selected_only: bool = False) -> int:
        if selected_only:
            sel = self.model.selected_ids()
            rows = [r for r in self.model.display_rows() if r.get("id") in sel]
        else:
            rows = self._filtered_base()
        with open(path, "wb") as f:
            f.write(csv_bytes(rows))
        return len(rows)

    def stat_texts(self) -> Dict[str, str]:
        return {k: v.text() for k, v in self._card_values.items()}

    def visible_column_keys(self) -> List[str]:
        return [c.key for i, c in enumerate(SUMMARY_COLS, start=1)
                if not self.table.isColumnHidden(i)]

    def hidden_keys(self) -> Set[str]:
        return set(self._hidden)

    def density(self) -> str:
        return self._density

    def apply_preset(self, name: str) -> None:
        self._hidden = set(hidden_for_preset(name))
        self._write_hidden()
        self._apply_hidden()

    # ---- state to view ----
    def _filter_args(self) -> Dict[str, Any]:
        return dict(model=self.model_combo.currentData() or "All", mode=self.mode_combo.currentData() or "All",
                    cal=self.cal_combo.currentData() or "All", ids=self._id_filter,
                    query=self.search_edit.text())

    def _filtered_base(self) -> List[Dict[str, Any]]:
        hid = self.model.hidden_ids()
        return [r for r in filter_rows(self.model.display_rows(), **self._filter_args()) if r.get("id") not in hid]

    def _filters_changed(self, *_a) -> None:
        self.proxy.set_filters(**self._filter_args())
        self._update_view()

    def _on_rows(self, rows: List[dict]) -> None:
        self.model.set_rows(rows)
        self._after_rows()
        self._loaded = True
        self._failed_text = ""
        self.banner.hide()
        self._refill_combo(self.model_combo, "Filter by Model", self.model.distinct_models())
        self._refill_combo(self.mode_combo, "Filter by Mode", self.model.distinct_modes())
        self.table.set_row_height(self._row_height())
        self.proxy.set_filters(**self._filter_args())
        self._update_view()

    def _refill_combo(self, combo: QComboBox, label: str, values: List[str]) -> None:
        cur = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("%s: All" % label, "All")
        for v in values:
            combo.addItem(v, v)
        i = combo.findData(cur)
        combo.setCurrentIndex(i if i >= 0 else 0)
        combo.blockSignals(False)

    def _on_failed(self, kind: str, msg: str) -> None:
        # a read error never ends a save: only the token-matched write_done / write_failed do
        self._loaded = True
        self._failed_text = "Can't reach the database: %s" % msg
        self.banner_label.setText(self._failed_text)
        self.banner.show()
        self._update_view()

    def _retry(self) -> None:
        self._loader.refresh()

    def _update_view(self) -> None:
        filtered = self._filtered_base()
        total = len([1 for r in self.model.display_rows() if r.get("id") not in self.model.hidden_ids()])
        st = summary_stats(filtered)
        vals = self._card_values
        vals["Total Analyses"].setText(str(st["total"]))
        vals["Unique Models"].setText(str(st["models"]))
        vals["Avg α (raw)"].setText(st["avg_raw"])
        vals["Avg α (cal)"].setText(st["avg_cal"])
        self.caption.setText("Statistics for the %d analyses shown (of %d)." % (len(filtered), total)
                             if len(filtered) != total else "")
        self.info_label.setText("Showing %d of %d results · %s" % (len(filtered), total, _HINT))
        if not self._loaded:
            self.message_label.setText("Loading…")
            self._stack.setCurrentWidget(self.message_label)
        elif not filtered:
            self.message_label.setText("No data")
            self._stack.setCurrentWidget(self.message_label)
        else:
            self._stack.setCurrentWidget(self.table)
        self._sync_select_all()
        self._selection_changed()
        self._sync_presets()

    def _shown_changed(self, *_a) -> None:
        self._sync_select_all()

    def _sync_select_all(self) -> None:
        shown = self.proxy.shown_ids()
        sel = self.model.selected_ids()
        self.select_all.setChecked(bool(shown) and all(i in sel for i in shown))

    def _select_all_clicked(self, on: bool) -> None:
        self.model.set_all_shown(bool(on))
        self._sync_select_all()

    def _selection_changed(self) -> None:
        n = len(self.model.selected_ids())
        self.sel_bar.setVisible(n > 0)
        self.sel_label.setText("%d analyses selected" % n)
        self.compare_button.setEnabled(n <= MAX_COMPARE)
        self.compare_button.setToolTip("Compare up to 4 at a time" if n > MAX_COMPARE else "")
        self._sync_select_all()

    # ---- columns, density, sort ----
    def _toggle_column(self, key: str, on: bool) -> None:
        (self._hidden.discard if on else self._hidden.add)(key)
        self._write_hidden()
        self._apply_hidden()

    def _apply_hidden(self) -> None:
        for i, c in enumerate(SUMMARY_COLS, start=1):
            self.table.setColumnHidden(i, c.key in self._hidden)
        for key, a in self._column_actions.items():
            a.blockSignals(True)
            a.setChecked(key not in self._hidden)
            a.blockSignals(False)
        self._sync_presets()

    def _sync_presets(self) -> None:
        cur = preset_of(self._hidden)
        for k, b in self._preset_buttons.items():
            b.setChecked(k == cur)

    def _row_height(self) -> int:
        return theme.ROW_HEIGHT if self._density == "compact" else theme.ROW_HEIGHT + 10

    def _apply_density(self) -> None:
        self.density_button.setText("Compact rows" if self._density == "comfortable" else "Comfortable rows")
        self.table.set_row_height(self._row_height())

    def _toggle_density(self) -> None:
        self._density = "comfortable" if self._density == "compact" else "compact"
        self._settings.setValue(DENSITY_KEY, self._density)
        self._apply_density()

    def _header_clicked(self, col: int) -> None:
        if col == 0:
            return
        self._sort = next_sort(self._sort, SUMMARY_COLS[col - 1].key)
        self.proxy.set_sort(*self._sort)
        for h in (self.table.horizontalHeader(), self.table.frozen.horizontalHeader()):
            if self._sort[0] is None:
                h.setSortIndicatorShown(False)
            else:
                h.setSortIndicatorShown(True)
                h.setSortIndicator(_KEYS.index(self._sort[0]) + 1,
                                   Qt.AscendingOrder if self._sort[1] == "asc" else Qt.DescendingOrder)

    # ---- actions ----
    def _compare(self) -> None:
        ids = self.selected_ids()
        if 0 < len(ids) <= MAX_COMPARE:
            self.compare_requested.emit(ids)

    def _download(self, selected_only: bool, default_name: str) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Download CSV", default_name, "CSV (*.csv)")
        if path:
            try:
                n = self.export_csv(path, selected_only)
                self.message.emit("Saved %d rows to %s" % (n, path))
            except OSError as e:
                self.message.emit("Could not write %s: %s" % (path, e))

    def _download_all(self) -> None:
        self._download(False, "angstrom_results_summary.csv")

    def _download_selected(self) -> None:
        self._download(True, "angstrom_results_selected.csv")


    # ---- inline editing (Task 8) ----
    def editing_id(self) -> Optional[int]:
        return self._session.row_id if self._session is not None else None

    def editor_widget(self, key: str):
        return self._delegate.editors.get(key)

    def edit_button_rect(self, row_id: int):
        """(view, rect in that view's viewport) of the row's Edit button, or None."""
        ids = self.proxy.shown_ids()
        if row_id not in ids:
            return None
        ix = self.proxy.index(ids.index(row_id), 0)
        view = self.table.frozen
        return view, self._delegate.button_rect(view.visualRect(ix))

    def cell_rect(self, row_id: int, key: str):
        ids = self.proxy.shown_ids()
        if row_id not in ids or key not in _KEYS:
            return None
        col = _KEYS.index(key) + 1
        view = self.table.view_for_column(col)
        return view, view.visualRect(self.proxy.index(ids.index(row_id), col))

    def _confirm_discard(self, row_id: int) -> bool:
        return QMessageBox.question(self, "Edit", "Discard changes to #%d?" % row_id,
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def begin_edit(self, row_id: int, focus_key: Optional[str] = None) -> None:
        stored = self.model.row_by_id(row_id)
        if stored is None:
            return
        s = self._session
        if s is not None:
            if s.saving:
                return
            if s.row_id == row_id:
                s.focus_key = focus_key or s.focus_key
                self._open_editors()
                self._focus_editor(focus_key)
                return
            cur = self.model.row_by_id(s.row_id)
            if cur is not None and s.changes(cur) and not self._confirm_discard(s.row_id):
                return
            self._end_edit()
        self._session = EditSession(row_id, initial_values(stored), focus_key, initial=initial_values(stored))
        self._open_editors()
        self._focus_editor(focus_key)

    def commit_edit(self) -> Dict[str, Any]:
        s = self._session
        if s is None or s.saving:
            return {}
        stored = self.model.row_by_id(s.row_id)
        if stored is None:
            self._end_edit()
            return {}
        changes = s.changes(stored)
        if not changes:
            self._end_edit()
            return {}
        s.saving, s.sent, s.token = True, dict(changes), None
        self._delegate.set_saving(True)
        s.token = self._loader.apply_update(s.row_id, changes)
        return changes

    def cancel_edit(self) -> None:
        if self._session is not None and not self._session.saving:
            self._end_edit()

    def _on_edit_key(self, which: str) -> None:
        (self.commit_edit if which == "enter" else self.cancel_edit)()

    def _cell_double_clicked(self, ix: QModelIndex) -> None:
        if ix.column() < 1:
            return
        col = SUMMARY_COLS[ix.column() - 1]
        rid = ix.data(ID_ROLE)
        if col.editable and rid is not None and not (self._session is not None and self._session.saving):
            self.begin_edit(int(rid), col.key)

    # editors follow the session's row by id
    def _editor_cols(self) -> List[int]:
        return [0] + [i for i, c in enumerate(SUMMARY_COLS, start=1)
                      if c.editable and not self.table.isColumnHidden(i)]

    def _session_proxy_row(self) -> int:
        s = self._session
        if s is None:
            return -1
        r = self.model.row_of(s.row_id)
        if r < 0:
            return -1
        ix = self.proxy.mapFromSource(self.model.index(r, 0))
        return ix.row() if ix.isValid() else -1

    def _open_editors(self) -> None:
        row = self._session_proxy_row()
        if row < 0:
            return
        for col in self._editor_cols():
            ix = self.proxy.index(row, col)
            view = self.table.view_for_column(col)
            if view.indexWidget(ix) is None:
                view.openPersistentEditor(ix)
        self._delegate.set_saving(bool(self._session.saving))

    def _close_editors(self) -> None:
        row = self._session_proxy_row()
        if row >= 0:
            for col in self._editor_cols():
                ix = self.proxy.index(row, col)
                view = self.table.view_for_column(col)
                if view.indexWidget(ix) is not None:
                    view.closePersistentEditor(ix)
        self._delegate.forget_editors()

    def _reopen_editors(self, *_a) -> None:
        if self._session is None or self._reopening:
            return
        self._reopening = True
        try:
            had_focus = self._focused_key()
            self._open_editors()
            if had_focus is not None and self._delegate.editors.get(had_focus) is not None:
                self._focus_editor(had_focus)
        finally:
            self._reopening = False

    def _focused_key(self) -> Optional[str]:
        w = QApplication.focusWidget()
        for k, e in self._delegate.editors.items():
            if w is e or (w is not None and e.isAncestorOf(w)):
                return k
        return None

    def _focus_editor(self, key: Optional[str]) -> None:
        w = self._delegate.editors.get(key) if key else None
        if w is not None:
            w.setFocus()
            if isinstance(w, QLineEdit):
                w.selectAll()

    def _end_edit(self) -> None:
        self._close_editors()
        self._session = None

    def _after_rows(self) -> None:
        s = self._session
        if s is None:
            return
        row = self.model.row_by_id(s.row_id)
        if row is None:
            self._end_edit()
            self.message.emit("#%d was removed elsewhere" % s.row_id)
            return
        if s.saving and all(row.get(k) == v for k, v in s.sent.items()):
            self._save_ok()
            return
        self._reopen_editors()

    def _save_ok(self) -> None:
        s = self._session
        if s is None:
            return
        self._end_edit()
        self.message.emit("Saved #%d" % s.row_id)

    def _save_failed(self, kind: str, msg: str) -> None:
        s = self._session
        if s is None or not s.saving:
            return
        s.saving = False
        self._delegate.set_saving(False)
        self.message.emit("Could not save #%d: %s" % (s.row_id, msg))
        if kind == "login":
            self.login_needed.emit()

    def _on_write_done(self, op: str, token: int, _result) -> None:
        s = self._session
        if s is not None and s.saving and op == "update" and s.token in (None, token):
            self._save_ok()

    def _on_write_failed(self, op: str, token: int, kind: str, msg: str) -> None:
        s = self._session
        # token is None while apply_update itself is still running (a closed loader fails at once)
        if s is not None and s.saving and op == "update" and s.token in (None, token):
            self._save_failed(kind, msg)
