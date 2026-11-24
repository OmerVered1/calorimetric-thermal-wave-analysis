"""Small widgets and helpers shared by the Calibration tab's sections."""
from __future__ import annotations

import math
from typing import Callable, List, Optional

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLayout, QLayoutItem, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from ctwa import theme
from ctwa.ui.calibration.texts import TEXT


def parse_number(text: str) -> float:
    """What the user typed as a number: NaN for blank or text, so `not (x > 0)` and
    `isfinite` catch it the way the webapp's Number() checks do."""
    t = (text or "").strip()
    if not t:
        return math.nan
    try:
        return float(t)
    except ValueError:
        return math.nan


def failure_text(summary) -> str:
    """One line for the failures of a WriteSummary (login abort first)."""
    parts: List[str] = list(summary.failures)
    if summary.aborted:
        if not parts:
            parts.append(summary.aborted or TEXT["loginNeeded"])
        parts.append(TEXT["writtenOf"].format(n=summary.done, m=summary.total))
    return " · ".join(parts)


class StepCard(QFrame):
    """A titled card with a status text on the right and a body layout."""

    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        theme.set_role(self, "card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(8)
        head = QHBoxLayout()
        self.title_label = theme.set_role(QLabel(title), "heading")
        self.status_label = theme.set_role(QLabel(""), "pill", tone="warn")
        self.status_label.hide()
        head.addWidget(self.title_label)
        head.addStretch(1)
        head.addWidget(self.status_label)
        outer.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        outer.addLayout(self.body)

    def set_status(self, text: str, done: bool) -> None:
        self.status_label.setText(text)
        self.status_label.setVisible(bool(text))
        theme.set_prop(self.status_label, tone="ok" if done else "warn")


class MessageBar(QLabel):
    """One line the tab shows after an action: kind "ok" | "error" | "warn" | "info"."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        theme.set_role(self, "pill", tone="accent")
        self.hide()
        self.kind = "info"

    def show_message(self, text: str, kind: str = "info") -> None:
        self.kind = kind
        self.setText(text)
        tone = {"ok": "ok", "error": "danger", "warn": "warn"}.get(kind, "accent")
        theme.set_prop(self, tone=tone)
        self.setVisible(bool(text))

    def clear_message(self) -> None:
        self.setText("")
        self.hide()


def link_button(text: str) -> QPushButton:
    b = QPushButton(text)
    theme.set_role(b, "quiet")
    b.setCursor(Qt.PointingHandCursor)
    return b


def note_label(text: str, role: str = "faint") -> QLabel:
    lab = theme.set_role(QLabel(text), role)
    lab.setWordWrap(True)
    return lab


class FlowLayout(QLayout):
    """Left-to-right layout that wraps (the Qt flow-layout example)."""

    def __init__(self, parent: Optional[QWidget] = None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: List[QLayoutItem] = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, i: int):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i: int):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._lay_out(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._lay_out(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _lay_out(self, rect: QRect, test_only: bool) -> int:
        x, y, line_h = rect.x(), rect.y(), 0
        sp = self.spacing()
        for item in self._items:
            w = item.sizeHint()
            if x + w.width() > rect.right() and line_h > 0:
                x = rect.x()
                y += line_h + sp
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), w))
            x += w.width() + sp
            line_h = max(line_h, w.height())
        return y + line_h - rect.y()
