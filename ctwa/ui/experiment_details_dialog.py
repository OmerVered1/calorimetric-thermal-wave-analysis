"""The form for an experiment's run details: shown by New (with a name) and by Edit details."""

from __future__ import annotations

from typing import Dict, Iterable, Optional, Set, Tuple

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QLabel,
                               QLineEdit, QMessageBox, QVBoxLayout, QWidget)

from ctwa.ui.details_form import DetailsForm, presets_for


class ExperimentDetailsDialog(QDialog):
    """`name` is None for Edit details (no name field); otherwise the new experiment's name,
    refused when empty or already in `taken_names`."""

    def __init__(self, parent: Optional[QWidget], name: Optional[str], details: dict,
                 taken_names: Optional[Set[str]] = None, settings=None,
                 sample_names: Iterable[str] = ()) -> None:
        super().__init__(parent)
        self._taken = set(taken_names or ())
        self._has_name = name is not None
        self.setWindowTitle("New Experiment" if self._has_name else "Experiment details")
        form = QFormLayout()
        self.name_edit = QLineEdit(name or "")
        if self._has_name:
            form.addRow("Name", self.name_edit)
        self.form = DetailsForm()
        self.form.set_values(details)
        if settings is not None or sample_names:
            for key in ("sample", "power_source", "response_device"):
                self.form.set_presets(key, presets_for(key, settings, sample_names))
        self.edits: Dict[str, QWidget] = self.form.fields
        form.addRow(self.form)
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
        return (self.name_edit.text().strip() if self._has_name else None), self.form.values()
