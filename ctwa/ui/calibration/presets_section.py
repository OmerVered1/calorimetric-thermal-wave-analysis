"""Known-alpha presets: chips to click, a form to add one (Plan 4, Task 5).

Writes go through the tab's WriteQueue (INSERT / DELETE on alpha_presets, no update); the presets
themselves arrive in `state.presets` (the tab feeds them from the loader)."""
from __future__ import annotations

import math
from typing import Callable, List, Optional

from PySide6.QtCore import QStringListModel, Qt
from PySide6.QtWidgets import (QCompleter, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout, QWidget)

from ctwa import theme
from ctwa.analysis.calibration_logic import all_materials, num
from ctwa.analysis.jsmath import js_number_to_string
from ctwa.analysis.references import LIT_MATERIALS, LITERATURE
from ctwa.ui.calibration.common import FlowLayout, failure_text, note_label, parse_number
from ctwa.ui.calibration.state import CalibrationState
from ctwa.ui.calibration.texts import TEXT
from ctwa.ui.calibration.writes import WriteOp, WriteQueue


class PresetsSection(QWidget):
    def __init__(self, state: CalibrationState, queue: WriteQueue,
                 on_message: Callable[[str, str], None], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._state, self._queue, self._on_message = state, queue, on_message
        self.load_error = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(theme.set_role(QLabel(TEXT["presetsHeading"]), "section"))
        lay.addWidget(note_label(TEXT["presetsNote"]))

        self.error_label = theme.set_role(QLabel(""), "danger")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        lay.addWidget(self.error_label)
        self.empty_label = note_label(TEXT["noPresets"], "muted")
        lay.addWidget(self.empty_label)
        self.chip_host = QWidget()
        self.chip_flow = FlowLayout(self.chip_host)
        lay.addWidget(self.chip_host)
        self.chips: List[QPushButton] = []
        self.delete_buttons: List[QPushButton] = []

        form = QHBoxLayout()
        form.setSpacing(8)
        self.material = QLineEdit()
        self.material.setPlaceholderText("Stainless Steel")
        self._completer_model = QStringListModel(self)
        completer = QCompleter(self._completer_model, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.material.setCompleter(completer)
        self.temp = QLineEdit()
        self.temp.setPlaceholderText("800")
        self.alpha = QLineEdit()
        self.alpha.setPlaceholderText("5.829")
        self.literature = QComboBox()
        self.literature.addItem(TEXT["litPreset"])
        self.literature.addItems(LIT_MATERIALS)
        self.note = QLineEdit()
        self.note.setPlaceholderText(TEXT["presetNotePlaceholder"])
        for label, w in ((TEXT["presetMaterial"], self.material), (TEXT["presetTemp"], self.temp),
                         (TEXT["presetAlpha"], self.alpha)):
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(theme.set_role(QLabel(label), "faint"))
            col.addWidget(w)
            form.addLayout(col, 1)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(theme.set_role(QLabel(TEXT["litPreset"]), "faint"))
        col.addWidget(self.literature)
        form.addLayout(col)
        lay.addLayout(form)
        row = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(theme.set_role(QLabel(TEXT["presetNote"]), "faint"))
        col.addWidget(self.note)
        row.addLayout(col, 1)
        self.save_button = QPushButton(TEXT["addPreset"])
        theme.set_role(self.save_button, "primary")
        row.addWidget(self.save_button, 0, Qt.AlignBottom)
        lay.addLayout(row)

        self.literature.currentIndexChanged.connect(self._on_literature)
        self.save_button.clicked.connect(self.save)
        state.changed.connect(self.refresh)
        queue.busy_changed.connect(self._sync_busy)
        self.refresh()

    # ---- showing ----
    def set_load_error(self, message: str) -> None:
        self.load_error = message or ""
        self.error_label.setText("%s: %s" % (TEXT["presetsLoadFailed"], message) if message else "")
        self.error_label.setVisible(bool(message))
        self.refresh()

    def refresh(self) -> None:
        self._completer_model.setStringList(all_materials(self._state.rows))
        presets = self._state.presets
        # rebuild the chips only when the list changed
        key = [(p["id"], p.get("material_name"), p.get("temperature_c"), p.get("alpha_mm2s"), p.get("note"))
               for p in presets]
        if key != getattr(self, "_chip_key", None):
            self._chip_key = key
            self._rebuild(presets)
        self.empty_label.setVisible(not presets and not self.load_error)

    def _rebuild(self, presets: List[dict]) -> None:
        while self.chip_flow.count():
            item = self.chip_flow.takeAt(0)
            w = item.widget()
            if w is not None:
                # Detach and delete now: a deleteLater() on a child that is still owned by this section can
                # outlive the section when the cyclic GC frees it first, and the late DeferredDelete event
                # then crashes whatever event loop runs next.
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self.chips, self.delete_buttons = [], []
        for p in presets:
            chip = theme.set_role(QFrame(), "card")
            h = QHBoxLayout(chip)
            h.setContentsMargins(8, 2, 4, 2)
            h.setSpacing(4)
            b = QPushButton("%s @ %s °C → %s mm²/s" % (
                p["material_name"], num(p["temperature_c"], 0), num(p["alpha_mm2s"], 3)))
            theme.set_role(b, "quiet")
            b.setToolTip(p.get("note") or "")
            b.clicked.connect(lambda _=False, p=p: self._state.apply_preset(p))
            x = QPushButton("×")
            theme.set_role(x, "danger")
            x.setToolTip(TEXT["delete"])
            x.setFixedWidth(26)
            x.clicked.connect(lambda _=False, i=p["id"], m=p["material_name"]: self.delete(i, m))
            h.addWidget(b)
            h.addWidget(x)
            self.chip_flow.addWidget(chip)
            self.chips.append(b)
            self.delete_buttons.append(x)
        self._sync_busy()
        self.chip_host.updateGeometry()

    def _sync_busy(self, *_args) -> None:
        busy = self._queue.busy
        self.save_button.setDisabled(busy)
        for x in self.delete_buttons:
            x.setDisabled(busy)

    # ---- actions ----
    def _on_literature(self, index: int) -> None:
        if index <= 0:
            return
        name = self.literature.itemText(index)
        self.alpha.setText(js_number_to_string(LITERATURE[name]))
        if not self.material.text().strip():
            self.material.setText(name)
        self.literature.blockSignals(True)
        self.literature.setCurrentIndex(0)
        self.literature.blockSignals(False)

    def save(self) -> None:
        if self._queue.busy:
            return
        material = self.material.text().strip()
        temp = parse_number(self.temp.text())
        alpha = parse_number(self.alpha.text())
        if not material:
            self._on_message(TEXT["errPresetMaterial"], "error")
            return
        if not math.isfinite(temp):
            self._on_message(TEXT["errPresetTemp"], "error")
            return
        if not alpha > 0 or not math.isfinite(alpha):
            self._on_message(TEXT["errAlphaRequired"], "error")
            return
        row = {"material_name": material, "temperature_c": temp, "alpha_mm2s": alpha,
               "note": self.note.text().strip() or None}
        self._queue.run([WriteOp("preset_insert", None, row, material)], self._saved)

    def _saved(self, summary) -> None:
        if summary.failures or summary.aborted:
            self._on_message("%s: %s" % (TEXT["saveFailed"], failure_text(summary)), "error")
            return
        for w in (self.material, self.temp, self.alpha, self.note):
            w.clear()

    def delete(self, preset_id: int, name: str = "") -> None:
        if self._queue.busy:
            return
        self._queue.run([WriteOp("preset_delete", preset_id, None, name or "#%s" % preset_id)], self._deleted)

    def _deleted(self, summary) -> None:
        if summary.failures or summary.aborted:
            self._on_message("%s: %s" % (TEXT["saveFailed"], failure_text(summary)), "error")
