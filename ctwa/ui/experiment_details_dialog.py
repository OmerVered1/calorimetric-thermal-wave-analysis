"""The form for an experiment's run details: shown by New (with a name) and by Edit details."""

from __future__ import annotations

from typing import Dict, Optional, Set, Tuple

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
                               QLineEdit, QMessageBox, QVBoxLayout, QWidget)

from ctwa.experiment_details import FIELDS
from ctwa.ui.save_panel import GAS_CHOICES


class ExperimentDetailsDialog(QDialog):
    """`name` is None for Edit details (no name field); otherwise the new experiment's name,
    refused when empty or already in `taken_names`."""

    def __init__(self, parent: Optional[QWidget], name: Optional[str], details: dict,
                 taken_names: Optional[Set[str]] = None) -> None:
        super().__init__(parent)
        self._taken = set(taken_names or ())
        self._has_name = name is not None
        self.setWindowTitle("New Experiment" if self._has_name else "Experiment details")
        form = QFormLayout()
        self.name_edit = QLineEdit(name or "")
        if self._has_name:
            form.addRow("Name", self.name_edit)
        self.edits: Dict[str, QWidget] = {}
        for key, label in FIELDS:
            value = "" if details.get(key) is None else str(details.get(key))
            if key == "gas":
                w: QWidget = QComboBox()
                w.setEditable(True)
                w.addItems(GAS_CHOICES)
                w.setCurrentText(value)
            else:
                w = QLineEdit(value)
            self.edits[key] = w
            form.addRow(label, w)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self._on_ok)
        self.buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(QLabel("Each run of this experiment carries these details into the Analysis tab."))
        lay.addWidget(self.buttons)

    def _on_ok(self) -> None:
        if self._has_name:
            name = self.name_edit.text().strip()
            if not name:
                QMessageBox.warning(self, "New Experiment", "Enter a name for the experiment.")
                return
            if name in self._taken:
                QMessageBox.warning(self, "New Experiment", "'%s' is already taken." % name)
                return
        self.accept()

    def values(self) -> Tuple[Optional[str], dict]:
        out = {}
        for key, w in self.edits.items():
            text = w.currentText() if isinstance(w, QComboBox) else w.text()
            out[key] = text.strip()
        return (self.name_edit.text().strip() if self._has_name else None), out
