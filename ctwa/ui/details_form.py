"""The run-details form: preset dropdowns for sample / power source / response device.

Shared by the New dialog and the Run details box in the experiment Settings tab."""

from __future__ import annotations

from typing import Dict, Iterable, List

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QComboBox, QFormLayout, QLineEdit, QWidget

from ctwa import theme
from ctwa.experiment_details import FIELDS, FILL_IN_NEW, RESPONSE_PRESETS, SOURCE_PRESETS
from ctwa.ui.save_panel import GAS_CHOICES

__all__ = ["PresetCombo", "DetailsForm", "remembered", "remember", "presets_for",
           "TEMPERATURE_HINT", "MAX_REMEMBERED"]

TEMPERATURE_HINT = "leave blank = automatic"
MAX_REMEMBERED = 30
_PRESET_FIELDS = ("sample", "power_source", "response_device")


def _key(field: str) -> str:
    return "experiment/presets/%s" % field


def remembered(settings, field: str) -> List[str]:
    """Typed values remembered for a field, most recent first."""
    raw = settings.value(_key(field), [])
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        raw = [raw]
    return [str(v) for v in raw if str(v).strip()]


def remember(settings, details: dict) -> None:
    """Put the sample / power source / response device of `details` at the front of their lists."""
    for field in _PRESET_FIELDS:
        value = str((details or {}).get(field) or "").strip()
        if not value or value == FILL_IN_NEW:
            continue
        items = [value] + [v for v in remembered(settings, field) if v != value]
        settings.setValue(_key(field), items[:MAX_REMEMBERED])


def presets_for(field: str, settings, sample_names: Iterable[str] = ()) -> List[str]:
    """Built-in presets, then (for sample) the database names, then remembered values."""
    builtin = {"power_source": SOURCE_PRESETS, "response_device": RESPONSE_PRESETS}.get(field, ())
    names = [str(n).strip() for n in sample_names] if field == "sample" else []
    out: List[str] = []
    for v in list(builtin) + names + (remembered(settings, field) if settings is not None else []):
        if v and v != FILL_IN_NEW and v not in out:
            out.append(v)
    return out


class PresetCombo(QComboBox):
    """Editable dropdown: presets, then `Fill in new…`, which clears the field for typing."""

    edited = Signal()

    def __init__(self, presets: Iterable[str] = (), parent=None) -> None:
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self._presets: List[str] = []
        self.set_presets(presets)
        self.activated.connect(self._on_activated)
        self.lineEdit().textEdited.connect(lambda _t: self.edited.emit())

    def set_presets(self, presets: Iterable[str]) -> None:
        text = self.value()
        self._presets = [p for p in presets if p != FILL_IN_NEW]
        self.blockSignals(True)
        self.clear()
        self.addItems(self._presets + [FILL_IN_NEW])
        self.setEditText(text)
        self.blockSignals(False)

    def _on_activated(self, index: int) -> None:
        if self.itemText(index) == FILL_IN_NEW:
            self.setEditText("")
            self.lineEdit().setFocus()
        self.edited.emit()

    def value(self) -> str:
        t = self.currentText().strip()
        return "" if t == FILL_IN_NEW else t

    def set_value(self, text: str) -> None:
        self.setEditText(text or "")


class DetailsForm(QWidget):
    """One row per FIELDS entry. `changed` fires on user edits only."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.fields: Dict[str, QWidget] = {}
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        for key, label in FIELDS:
            w: QWidget
            if key in _PRESET_FIELDS:
                w = PresetCombo(presets_for(key, None))
                w.edited.connect(self.changed)
            elif key == "gas":
                w = QComboBox()
                w.setEditable(True)
                w.addItems(GAS_CHOICES)
                w.activated.connect(lambda _i: self.changed.emit())
                w.lineEdit().textEdited.connect(lambda _t: self.changed.emit())
            else:
                w = QLineEdit()
                w.textEdited.connect(lambda _t: self.changed.emit())
                if key == "temperature_c":
                    w.setPlaceholderText(TEMPERATURE_HINT)
                    pal = w.palette()  # the one deliberate grey text (not in the global stylesheet)
                    pal.setColor(QPalette.PlaceholderText, QColor(theme.P.text_disabled))
                    w.setPalette(pal)
            self.fields[key] = w
            form.addRow(label, w)

    def set_presets(self, field: str, values: List[str]) -> None:
        w = self.fields.get(field)
        if isinstance(w, PresetCombo):
            w.set_presets(values)

    def values(self) -> dict:
        out = {}
        for key, w in self.fields.items():
            if isinstance(w, PresetCombo):
                out[key] = w.value()
            elif isinstance(w, QComboBox):
                out[key] = w.currentText().strip()
            else:
                out[key] = w.text().strip()
        return out

    def set_values(self, details: dict) -> None:
        """Show these values (a missing key -> blank); emits nothing."""
        self.blockSignals(True)
        try:
            for key, w in self.fields.items():
                v = (details or {}).get(key)
                text = "" if v is None else str(v)
                if isinstance(w, QComboBox):
                    w.setEditText(text)
                else:
                    w.setText(text)
        finally:
            self.blockSignals(False)
