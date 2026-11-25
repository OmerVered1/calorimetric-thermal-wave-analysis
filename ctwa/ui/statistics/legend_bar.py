"""Clickable legend under a chart: click toggles an entry (and its legend group), double-click isolates it."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLayout, QSizePolicy, QWidget

from ctwa import theme

__all__ = ["LegendBar"]


class _Flow(QLayout):
    """Left-to-right layout that wraps onto new rows (Qt's flow-layout example)."""

    def __init__(self, parent=None, hspace: int = 14, vspace: int = 2):
        super().__init__(parent)
        self._items: list = []
        self._h, self._v = hspace, vspace

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._layout(QRect(0, 0, w, 0), False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _layout(self, rect, apply):
        m = self.contentsMargins()
        top = rect.y()
        rect = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, row_h = rect.x(), rect.y(), 0
        for it in self._items:
            sz = it.sizeHint()
            if x + sz.width() > rect.right() and row_h > 0:
                x, y, row_h = rect.x(), y + row_h + self._v, 0
            if apply:
                it.setGeometry(QRect(QPoint(x, y), sz))
            x += sz.width() + self._h
            row_h = max(row_h, sz.height())
        return y + row_h - top + m.bottom()


class _Entry(QWidget):
    def __init__(self, bar: "LegendBar", name: str, color: str):
        super().__init__(bar)
        self.bar, self.name = bar, name
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)
        self.dot = theme.swatch(color, 9)
        self.label = QLabel(name)
        self.label.setTextFormat(Qt.PlainText)
        self.label.setStyleSheet("font-size: %dpx; background: transparent;" % theme.TEXT_SMALL)
        self.label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.dot.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self.dot)
        lay.addWidget(self.label)
        self._swallow = False

    def paint_state(self, visible: bool) -> None:
        self.setWindowOpacity(1.0)
        self.label.setStyleSheet("font-size: %dpx; background: transparent; color: %s;" % (
            theme.TEXT_SMALL, theme.P.text if visible else theme.P.text_faint))
        self.dot.setVisible(True)
        self.dot.setStyleSheet("background: %s; border-radius: 4px;" % (
            self.property("color") if visible else theme.P.border))

    def mouseReleaseEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        if self._swallow:
            self._swallow = False
            return
        self.bar._click(self.name)

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._swallow = True
            self.bar._double_click(self.name)


class LegendBar(QWidget):
    toggled = Signal(str, bool)
    isolated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: List[Tuple[str, str, Optional[str]]] = []
        self._widgets: Dict[str, _Entry] = {}
        self._visible: Dict[str, bool] = {}
        self._before: Dict[str, bool] = {}
        self._before_name: Optional[str] = None
        self._flow = _Flow(self)
        self._flow.setContentsMargins(8, 4, 8, 4)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    # ------------------------------------------------------------------ entries
    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        h = self._flow.heightForWidth(self.width())
        if h != self.minimumHeight():
            self.setMinimumHeight(h)          # the plot above gives way, so a wrapped legend is never clipped

    def set_entries(self, entries: List[Tuple[str, str, Optional[str]]]) -> None:
        for w in self._widgets.values():
            self._flow.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        self._widgets.clear()
        seen = set()
        self._entries = []
        for name, color, group in entries:
            if name in seen:
                continue
            seen.add(name)
            self._entries.append((name, color, group))
            w = _Entry(self, name, color)
            w.setProperty("color", color)
            self._widgets[name] = w
            self._flow.addWidget(w)
            w.show()
        self._visible = {n: self._visible.get(n, True) for n, _, _ in self._entries}
        self._refresh()
        self.setVisible(bool(self._entries))
        self.updateGeometry()

    def entry_widget(self, name: str) -> QWidget:
        return self._widgets[name]

    def is_visible(self, name: str) -> bool:
        return self._visible.get(name, True)

    def hidden_names(self) -> List[str]:
        return [n for n, v in self._visible.items() if not v]

    def hidden_groups(self) -> List[str]:
        return sorted({g for n, _, g in self._entries if g is not None and not self._visible.get(n, True)})

    def _group_of(self, name: str) -> Optional[str]:
        for n, _, g in self._entries:
            if n == name:
                return g
        return None

    def _members(self, name: str) -> List[str]:
        g = self._group_of(name)
        if g is None:
            return [name]
        return [n for n, _, gg in self._entries if gg == g]

    def _refresh(self) -> None:
        for n, w in self._widgets.items():
            w.paint_state(self._visible.get(n, True))

    # ------------------------------------------------------------------ interaction
    def _click(self, name: str) -> None:
        self._before = dict(self._visible)
        self._before_name = name
        new = not self._visible.get(name, True)
        for n in self._members(name):
            self._visible[n] = new
        self._refresh()
        self.toggled.emit(name, new)

    def _double_click(self, name: str) -> None:
        if self._before_name == name and set(self._before) == set(self._visible):
            self._visible = dict(self._before)          # undo the toggle the first click of the pair made
        self._before_name = None
        members = set(self._members(name))
        already = (all(self._visible.get(n, True) for n in members)
                   and all(not v for n, v in self._visible.items() if n not in members))
        for n in self._visible:
            self._visible[n] = True if already else (n in members)
        self._refresh()
        self.isolated.emit(name)

    def click_entry(self, name: str) -> None:
        """Programmatic single click (tests, keyboard)."""
        self._click(name)

    def show_all(self) -> None:
        for n in self._visible:
            self._visible[n] = True
        self._refresh()
