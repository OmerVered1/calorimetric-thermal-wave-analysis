"""Inline editing of one Summary row: the edit session and the delegate that draws the editors.

The typed values live in EditSession, not in the model or the widgets, so a background refresh (which
may rebuild the table and its editors) cannot lose them."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QEvent, QModelIndex, QObject, QRect, Qt, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLineEdit, QPushButton, QStyle,
                               QStyledItemDelegate, QStyleOptionButton, QWidget)

from ctwa import theme
from ctwa.ui.results.fmt import js_str
from ctwa.ui.results.summary_logic import SUMMARY_COLS, build_update
from ctwa.ui.results.summary_model import ID_ROLE

__all__ = ["ANALYSIS_MODES", "EditSession", "SummaryDelegate", "initial_values", "mode_choices"]

ANALYSIS_MODES = ["Auto", "AutoHybrid", "AutoFFT", "AutoFit", "Manual"]
_EDITABLE = {c.key: c for c in SUMMARY_COLS if c.editable}
BUTTON_X = 36          # where the Edit button starts inside the check column
BUTTON_W = 64


@dataclass
class EditSession:
    row_id: int
    values: Dict[str, Any]          # what the editors hold: str for text and numbers, bool for use_calibration
    focus_key: Optional[str] = None
    saving: bool = False
    token: Optional[int] = None
    sent: Dict[str, Any] = field(default_factory=dict)
    initial: Dict[str, Any] = field(default_factory=dict)   # the values when the edit began

    def changes(self, stored: Dict[str, Any]) -> Dict[str, Any]:
        """Only fields the user changed since the edit began (and that differ from the row now), so a
        refresh that changed another field meanwhile is never overwritten with the old value."""
        touched = {k: v for k, v in self.values.items() if v != self.initial.get(k)}
        return build_update(stored, touched)


def initial_values(stored: Dict[str, Any]) -> Dict[str, Any]:
    """The stored raw values as the editors show them (String(v ?? ''), so alpha is in m²/s)."""
    out: Dict[str, Any] = {}
    for key in _EDITABLE:
        v = stored.get(key)
        out[key] = bool(v) if key == "use_calibration" else js_str(v)
    return out


def mode_choices(current: Any) -> List[str]:
    cur = js_str(current)
    return ANALYSIS_MODES + ([cur] if cur and cur not in ANALYSIS_MODES else [])


class _SaveCancel(QWidget):
    def __init__(self, on_save: Callable[[], None], on_cancel: Callable[[], None], parent: QWidget) -> None:
        super().__init__(parent)
        self.setAutoFillBackground(True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 1, 2, 1)
        lay.setSpacing(4)
        self.save = QPushButton("Save")
        theme.set_role(self.save, "primary")
        self.cancel = QPushButton("Cancel")
        self.save.clicked.connect(lambda: on_save())
        self.cancel.clicked.connect(lambda: on_cancel())
        for b in (self.save, self.cancel):
            b.setFocusPolicy(Qt.NoFocus)
            lay.addWidget(b)


class SummaryDelegate(QStyledItemDelegate):
    edit_requested = Signal(int, str)   # row id, focus key (empty for the Edit button)

    def __init__(self, session: Callable[[], Optional[EditSession]], stored: Callable[[int], Optional[dict]],
                 on_save: Callable[[], None], on_cancel: Callable[[], None], parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._session, self._stored = session, stored
        self._on_save, self._on_cancel = on_save, on_cancel
        self.editors: Dict[str, QWidget] = {}
        self.buttons: Optional[_SaveCancel] = None
        self.key_handler: Optional[Callable[[str], None]] = None   # "enter" | "escape"

    # ---- which cells are being edited ----
    def _editing(self, index: QModelIndex) -> Optional[EditSession]:
        s = self._session()
        if s is not None and index.data(ID_ROLE) == s.row_id:
            return s
        return None

    @staticmethod
    def _key(index: QModelIndex) -> Optional[str]:
        return SUMMARY_COLS[index.column() - 1].key if index.column() > 0 else None

    def button_rect(self, cell: QRect) -> QRect:
        return QRect(cell.left() + BUTTON_X, cell.top() + 2, BUTTON_W, max(10, cell.height() - 4))

    # ---- painting and clicks ----
    def paint(self, painter, option, index) -> None:
        s = self._editing(index)
        if s is not None and (index.column() == 0 or self._key(index) in _EDITABLE):
            painter.fillRect(option.rect, option.palette.base())   # the editor widget covers it
            return
        super().paint(painter, option, index)
        if index.column() == 0:
            opt = QStyleOptionButton()
            opt.rect = self.button_rect(option.rect)
            opt.text = "Edit"
            opt.state = QStyle.State_Enabled | QStyle.State_Raised
            style = option.widget.style() if option.widget is not None else None
            if style is not None:
                style.drawControl(QStyle.CE_PushButton, opt, painter, option.widget)

    def editorEvent(self, event, model, option, index) -> bool:
        if self._editing(index) is not None:
            return False
        if (index.column() == 0 and event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton
                and self.button_rect(option.rect).contains(event.position().toPoint())):
            self.edit_requested.emit(int(index.data(ID_ROLE)), "")
            return True
        return super().editorEvent(event, model, option, index)

    # ---- editors ----
    def createEditor(self, parent, option, index):
        s = self._editing(index)
        if s is None:
            return None
        if index.column() == 0:
            w = _SaveCancel(self._on_save, self._on_cancel, parent)
            self.buttons = w
            w.save.setEnabled(not s.saving)
            w.save.setText("…" if s.saving else "Save")
            return w
        key = self._key(index)
        if key not in _EDITABLE:
            return None
        if key == "use_calibration":
            w = QCheckBox(parent)
            w.setAutoFillBackground(True)
            w.setChecked(bool(s.values.get(key)))
            w.toggled.connect(lambda on, k=key: s.values.__setitem__(k, bool(on)))
            ev = w
        elif key == "analysis_mode":
            w = QComboBox(parent)
            w.setEditable(True)
            w.addItems(mode_choices(self._stored(s.row_id).get(key) if self._stored(s.row_id) else ""))
            w.setCurrentText(str(s.values.get(key, "")))
            w.editTextChanged.connect(lambda t, k=key: s.values.__setitem__(k, t))
            w.lineEdit().installEventFilter(self)
            ev = w
        else:
            w = QLineEdit(parent)
            w.setText(str(s.values.get(key, "")))
            if _EDITABLE[key].numeric:
                w.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            w.textChanged.connect(lambda t, k=key: s.values.__setitem__(k, t))
            ev = w
        w.installEventFilter(self)
        self.editors[key] = w
        w.destroyed.connect(lambda _o=None, k=key, ref=w: self.editors.pop(k, None) if self.editors.get(k) is ref else None)
        return ev

    def setEditorData(self, editor, index) -> None:   # the session is the source, never the model
        return

    def setModelData(self, editor, model, index) -> None:   # saving goes through the loader
        return

    def updateEditorGeometry(self, editor, option, index) -> None:
        editor.setGeometry(option.rect)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.KeyPress and self.key_handler is not None:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.key_handler("enter")
                return True
            if event.key() == Qt.Key_Escape:
                self.key_handler("escape")
                return True
        return False   # no commit-on-focus-out or tab handling: editors are persistent

    def forget_editors(self) -> None:
        self.editors.clear()
        self.buttons = None

    def set_saving(self, saving: bool) -> None:
        for w in self.editors.values():
            w.setEnabled(not saving)
        if self.buttons is not None:
            self.buttons.save.setEnabled(not saving)
            self.buttons.save.setText("…" if saving else "Save")
