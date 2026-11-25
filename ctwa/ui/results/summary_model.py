"""Qt model and proxy of the Summary table: 28 columns (a check column, then SUMMARY_COLS), the
webapp's base order, filters and its own 3-state sort (compare_cells), a selection that survives."""
from __future__ import annotations

from functools import cmp_to_key
from typing import Any, Callable, Dict, List, Optional, Set

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor

from ctwa.analysis.references import material_color
from ctwa.results.helpers import sort_key_test_date
from ctwa.ui.results.fmt import compare_cells
from ctwa.ui.results.summary_logic import SUMMARY_COLS, base_order, filter_rows, format_cell

__all__ = ["SummaryModel", "SummaryProxy", "ID_ROLE"]

ID_ROLE = Qt.UserRole + 1
_ALIGN_R = int(Qt.AlignRight | Qt.AlignVCenter)
_ALIGN_L = int(Qt.AlignLeft | Qt.AlignVCenter)


class SummaryModel(QAbstractTableModel):
    selection_changed = Signal()
    hidden_changed = Signal()
    rows_refreshed = Signal()   # same ids in the same order, values may differ

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._stored: List[Dict[str, Any]] = []
        self._display: List[Dict[str, Any]] = []
        self._index: Dict[Any, int] = {}
        self._selected: Set[int] = set()
        self._hidden: Set[int] = set()
        self._shown_provider: Optional[Callable[[], List[int]]] = None

    # ---- rows ----
    def set_rows(self, rows: List[Dict[str, Any]]) -> None:
        rows = list(rows)
        stored = sorted(rows, key=lambda r: sort_key_test_date(r.get("test_date")), reverse=True)
        display = base_order(rows)
        same_order = [r.get("id") for r in stored] == [r.get("id") for r in self._stored]
        if not same_order:
            self.beginResetModel()
        self._stored, self._display = stored, display
        self._index = {}
        for i, r in enumerate(stored):
            self._index.setdefault(r.get("id"), i)
        if not same_order:
            self.endResetModel()
        elif stored:
            self.dataChanged.emit(self.index(0, 0), self.index(len(stored) - 1, self.columnCount() - 1))
            self.rows_refreshed.emit()
        gone = self._selected - set(self._index)
        if gone:
            self._selected -= gone
            self.selection_changed.emit()
        self._hidden &= set(self._index)

    def row_by_id(self, id) -> Optional[Dict[str, Any]]:
        i = self._index.get(id)
        return self._stored[i] if i is not None else None

    def display_row(self, id) -> Dict[str, Any]:
        i = self._index.get(id)
        return self._display[i] if i is not None else {}

    def row_of(self, id) -> int:
        return self._index.get(id, -1)

    def ids(self) -> List[int]:
        return [r.get("id") for r in self._stored]

    def stored_rows(self) -> List[Dict[str, Any]]:
        return list(self._stored)

    def display_rows(self) -> List[Dict[str, Any]]:
        return list(self._display)

    def display_rows_ref(self) -> List[Dict[str, Any]]:
        return self._display

    def distinct_models(self) -> List[str]:
        return sorted({str(r.get("model_name")) for r in self._stored if r.get("model_name") is not None})

    def distinct_modes(self) -> List[str]:
        return sorted({str(r.get("analysis_mode")) for r in self._stored if r.get("analysis_mode") is not None})

    # ---- selection ----
    def selected_ids(self) -> Set[int]:
        return set(self._selected)

    def set_selected(self, id, on: bool) -> None:
        if id not in self._index or (id in self._selected) == bool(on):
            return
        (self._selected.add if on else self._selected.discard)(id)
        r = self._index[id]
        self.dataChanged.emit(self.index(r, 0), self.index(r, 0), [Qt.CheckStateRole])
        self.selection_changed.emit()

    def set_shown_provider(self, fn: Callable[[], List[int]]) -> None:
        self._shown_provider = fn

    def set_all_shown(self, on: bool) -> None:
        """Select (or clear) the rows that pass the filters; others keep their state."""
        ids = self._shown_provider() if self._shown_provider else [i for i in self.ids() if i not in self._hidden]
        for i in ids:
            self.set_selected(i, on)

    def clear_selection(self) -> None:
        for i in list(self._selected):
            self.set_selected(i, False)

    def pending_hide(self, ids: Set[int]) -> None:
        self._hidden = set(ids)
        self.hidden_changed.emit()

    def hidden_ids(self) -> Set[int]:
        return set(self._hidden)

    # ---- QAbstractTableModel ----
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._stored)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else 1 + len(SUMMARY_COLS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return "" if section == 0 else SUMMARY_COLS[section - 1].label
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == 0:
            f |= Qt.ItemIsUserCheckable
        return f

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._stored)):
            return None
        r, c = index.row(), index.column()
        if role == ID_ROLE:
            return self._stored[r].get("id")
        if c == 0:
            if role == Qt.CheckStateRole:
                return Qt.Checked if self._stored[r].get("id") in self._selected else Qt.Unchecked
            return None
        col = SUMMARY_COLS[c - 1]
        if role == Qt.DisplayRole:
            return format_cell(col.key, self._display[r])
        if role == Qt.EditRole:
            return self._stored[r].get(col.key)
        if role == Qt.DecorationRole and col.key == "model_name":
            return QColor(material_color(self._stored[r].get("model_name")))
        if role == Qt.TextAlignmentRole:
            return _ALIGN_R if col.numeric else _ALIGN_L
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if index.isValid() and index.column() == 0 and role == Qt.CheckStateRole:
            self.set_selected(self._stored[index.row()].get("id"), value in (Qt.Checked, 2))
            return True
        return False


class SummaryProxy(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._f: Dict[str, Any] = dict(model="All", mode="All", cal="All", ids=None, query="")
        self._key: Optional[str] = None
        self._dir: Optional[str] = None
        self._rank: List[int] = []
        self.setDynamicSortFilter(True)

    def setSourceModel(self, model) -> None:
        old = self.sourceModel()
        if old is not None:
            for sig in (old.modelReset, old.rows_refreshed, old.hidden_changed):
                try:
                    sig.disconnect(self._source_changed)
                except (RuntimeError, TypeError):
                    pass
        super().setSourceModel(model)
        if model is not None:
            model.set_shown_provider(self.shown_ids)
            model.modelReset.connect(self._source_changed)
            model.rows_refreshed.connect(self._source_changed)
            model.hidden_changed.connect(self._source_changed)
        self._source_changed()

    # ---- filters and sort ----
    def set_filters(self, model: str = "All", mode: str = "All", cal: str = "All",
                    ids: Optional[Set[int]] = None, query: str = "") -> None:
        self._refilter(lambda: self._f.update(model=model, mode=mode, cal=cal,
                                              ids=None if ids is None else set(ids), query=query))

    def _refilter(self, change) -> None:
        if hasattr(self, "beginFilterChange"):   # Qt 6.9+: invalidateFilter() is deprecated
            self.beginFilterChange()
            change()
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:
            change()
            self.invalidateFilter()

    def set_sort(self, key: Optional[str], direction: Optional[str]) -> None:
        self._key, self._dir = (key, direction) if key and direction else (None, None)
        self._source_changed()

    def sort_state(self) -> tuple:
        return (self._key, self._dir)

    def _source_changed(self, *_a) -> None:
        src = self.sourceModel()
        n = src.rowCount() if src is not None else 0
        order = list(range(n))
        if self._key is not None and src is not None:
            key = self._key
            sign = 1 if self._dir == "asc" else -1
            stored = src.stored_rows()

            def cmp(i: int, j: int) -> int:
                c = compare_cells(stored[i].get(key), stored[j].get(key), key)
                return 0 if c != c else (c > 0) - (c < 0)
            order = sorted(order, key=cmp_to_key(lambda i, j: sign * cmp(i, j)))   # stable, as Array.sort
        rank = [0] * n
        for pos, i in enumerate(order):
            rank[i] = pos
        self._rank = rank
        self.invalidate()
        self.sort(0, Qt.AscendingOrder)

    def lessThan(self, left, right) -> bool:
        # the order is precomputed in _source_changed (base order or compare_cells); this only reads it
        a, b = left.row(), right.row()
        if a < len(self._rank) and b < len(self._rank):
            return self._rank[a] < self._rank[b]
        return a < b

    def filterAcceptsRow(self, source_row: int, parent) -> bool:
        src = self.sourceModel()
        if src is None:
            return False
        disp = src.display_rows_ref()[source_row]
        if disp.get("id") in src.hidden_ids():
            return False
        return bool(filter_rows([disp], **self._f))

    # ---- what is shown ----
    def shown_ids(self) -> List[int]:
        return [self.index(r, 0).data(ID_ROLE) for r in range(self.rowCount())]

    def shown_rows(self) -> List[Dict[str, Any]]:
        src = self.sourceModel()
        return [src.display_row(i) for i in self.shown_ids()]

    def distinct_models(self) -> List[str]:
        return self.sourceModel().distinct_models()

    def distinct_modes(self) -> List[str]:
        return self.sourceModel().distinct_modes()

    def set_all_shown(self, on: bool) -> None:
        self.sourceModel().set_all_shown(on)
