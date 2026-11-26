"""Zoom for a plot with a source axis on the left and a response axis on the right.

Wheel or drag inside the plot moves time and both signals together (the response follows the
source's y change through a linear map). Wheel or drag on one axis changes only that axis's
signal, and the map is learned again from the ranges as they then are.
"""
from __future__ import annotations

from typing import Optional

import pyqtgraph as pg
from PySide6.QtCore import Qt


class ResponseViewBox(pg.ViewBox):
    """The response's view box: y only, and only for events that come from its own axis.

    It sits on top of the main view box. Events from inside the plot are ignored here so they
    reach the main view box underneath; clicks are not accepted at all (they reach the region
    and the markers)."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setMouseEnabled(False, True)

    def wheelEvent(self, ev, axis=None):
        if axis is None:
            ev.ignore()
            return
        super().wheelEvent(ev, axis=axis)

    def mouseDragEvent(self, ev, axis=None):
        if axis is None:
            ev.ignore()
            return
        super().mouseDragEvent(ev, axis=axis)


class YZoomLink:
    """Keeps y2 = a*y1 + b between two view boxes' y ranges.

    The map is learned from the y ranges as they are after every change that is not its own
    sync. A wheel or drag inside the plot changes the main range first and only then reports
    itself as manual, so the map in force before that change is the one before the last
    snapshot."""

    def __init__(self, main: pg.ViewBox, second: pg.ViewBox) -> None:
        self.main, self.second = main, second
        self._syncing = False
        self._hist: list = []     # snapshots (m_lo, m_hi, s_lo, s_hi), repeats dropped
        self.relearn()
        main.sigRangeChangedManually.connect(self._on_manual)
        main.sigRangeChanged.connect(self._on_changed)
        second.sigRangeChanged.connect(self._on_changed)

    def _snapshot(self) -> tuple:
        return tuple(self.main.viewRange()[1]) + tuple(self.second.viewRange()[1])

    @staticmethod
    def _as_map(snap: tuple) -> Optional[tuple]:
        m_lo, m_hi, s_lo, s_hi = snap
        if m_hi == m_lo:
            return None
        a = (s_hi - s_lo) / (m_hi - m_lo)
        return a, s_lo - a * m_lo

    def relearn(self) -> None:
        """Learn the map from the ranges as they are now."""
        snap = self._snapshot()
        if not self._hist or self._hist[-1] != snap:
            self._hist = (self._hist + [snap])[-4:]

    def _on_changed(self, *_a) -> None:
        if not self._syncing:
            self.relearn()

    def _on_manual(self, mask) -> None:
        try:
            both = bool(mask[0]) and bool(mask[1])
        except Exception:
            return
        if not both or self._syncing or not self._hist:
            return
        last = self._hist[-1]
        before = self._hist[-2] if len(self._hist) > 1 else last
        if before[:2] == last[:2]:    # the main range did not move: the current map still holds
            before = last
        use = self._as_map(before)
        if use is None:
            return
        a, b = use
        lo, hi = self.main.viewRange()[1]
        self._syncing = True
        try:
            self.second.setYRange(a * lo + b, a * hi + b, padding=0)
        finally:
            self._syncing = False
        self._hist = self._hist[:-1] + [self._snapshot()]


def link_y_zoom(main: pg.ViewBox, second: pg.ViewBox) -> YZoomLink:
    return YZoomLink(main, second)
