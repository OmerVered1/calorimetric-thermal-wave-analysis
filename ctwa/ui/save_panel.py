"""Save the analysis of the open run to the shared results table (same row as the webapp's).

The panel sits under the results of the Analysis tab. `set_result((LoadedRun, PipelineOptions,
AnalysisResults, plot))` pre-fills the form and enables Save; everything stays editable. The
plot (the graph saved with the row) is built in the analysis process: nothing here does maths.
`clear_result()` (a new run, a new Analyze or a failure) takes the result away and disables
Save; after a save or a queued save Save also stays disabled until a NEW result arrives, so one
result can never be saved twice.

Save mirrors the webapp's handleSave: same-date candidates -> find_duplicate -> insert, with
the duplicate dialog (Cancel / Save as new / Replace it). Every network call (candidate
select, insert, update) runs in a QThreadPool worker; results come back by queued signal, so
the GUI thread never waits on the network. Save is disabled while a save is in flight.

Failures: Offline -> the row is queued (UploadManager) and uploaded later. If the duplicate
check was the call that failed it is skipped, and it is NOT re-run when the queue flushes.
NotLoggedIn -> login dialog, then one retry; cancel (or a second NotLoggedIn) -> queued.
ServerError -> message shown, form kept, nothing queued (it would fail again)."""
from __future__ import annotations

import math
import os
import re
import urllib.parse
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from PySide6.QtCore import QObject, QRunnable, QSettings, QThreadPool, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

from ctwa.analysis.jsmath import js_to_precision
from ctwa.analysis.row import RowMeta, build_analysis_row, find_duplicate
from ctwa.cloud.client import NotLoggedIn, Offline, ServerError
from ctwa.ui.login_dialog import LoginDialog
from ctwa.ui.upload_manager import UploadManager

try:  # the app's own names, so the panel shares its settings
    from _version import __app_name__
except Exception:  # pragma: no cover
    __app_name__ = "CTWA"
_ORGANIZATION = "Omer Vered MSc Research"  # same as ctwa.app.__organization__
TABLE = "analyses"
QUEUED_MESSAGE = "Saved on this computer; will upload when online"
GAS_CHOICES = ("Ar", "Air")


# ---- pre-fill rules (pure functions) ----

def instrument_device(instrument: Optional[str]) -> str:
    """'Keithley Instruments Inc., Model 2602B, ...' -> 'Keithley 2602B'."""
    m = re.search(r"Model (\w+)", instrument or "")
    return "Keithley " + m.group(1) if m else ""


def calorimeter_device(calorimeter: Optional[str]) -> str:
    text = (calorimeter or "").strip()
    if not text:
        return ""
    if text.startswith("Drop") or "Alexsys" in text:
        return "Drop Calorimeter"
    if "C80" in text:
        return "C80"
    return text.split(" @")[0].strip()


def region_temperature(parsed, sel_min: float, sel_max: float) -> str:
    """Mean of the finite temperatures inside the region, one decimal; '' if there are none."""
    vals = [v for t, v in zip(parsed.time, parsed.temperature)
            if sel_min <= t <= sel_max and math.isfinite(v)]
    return "%.1f" % (sum(vals) / len(vals)) if vals else ""


def _fmt_alpha(v: Any) -> str:  # fmtAlpha of the webapp page
    if v is None:
        return "—"
    if v < 0:
        return "N/A"
    return js_to_precision(v * 1e6, 4) + " mm²/s"


def _fmt_fixed(v: Any) -> str:
    return "?" if v is None else "%.1f" % v


# ---- the worker ----

class _Signals(QObject):
    finished = Signal(object)  # dict: kind, state, ...


class _SaveJob(QRunnable):
    """One network attempt. kind: 'save' (check + insert), 'insert', 'update'."""

    def __init__(self, signals: _Signals, client, kind: str, build_row, row=None, target_id=None,
                 retried: bool = False) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._signals, self._client, self._kind = signals, client, kind
        self._build_row, self._row, self._target_id, self._retried = build_row, row, target_id, retried

    def run(self) -> None:
        out: Dict[str, Any] = {"kind": self._kind, "retried": self._retried,
                               "target_id": self._target_id, "row": self._row}
        try:
            if self._row is None:
                self._row = out["row"] = self._build_row()
            row = self._row
            if self._kind == "save":
                try:
                    cand = self._client.select(TABLE, {
                        "select": "id,test_date,model_name,analysis_mode,period_t,amplitude_a1,alpha_phase_raw",
                        "test_date": "eq." + row["test_date"],
                        "order": "created_at.desc"})
                except Offline:
                    # no duplicate check offline: queue the row as it is
                    out["state"] = "offline"
                    return
                match = find_duplicate(cand, row)
                if match is not None:
                    out["state"] = "duplicate"
                    out["match"] = match
                    return
            if self._kind == "update":
                done = self._client.update(TABLE, self._target_id, row)
                out["id"] = self._target_id
            else:
                done = self._client.insert(TABLE, row)
                out["id"] = done.get("id") if isinstance(done, dict) else None
            out["state"] = "ok"
        except Offline:
            out["state"] = "offline"
        except NotLoggedIn:
            out["state"] = "login"
        except ServerError as e:
            out["state"] = "error"
            out["message"] = str(e)
        except Exception as e:  # a bug must not leave the button disabled
            out["state"] = "error"
            out["message"] = "%s: %s" % (type(e).__name__, e)
        finally:
            try:
                self._signals.finished.emit(out)
            except RuntimeError:  # the panel was deleted while the call ran
                pass


class SavePanel(QWidget):
    saved = Signal(object)  # row id (int), or None when the row was queued

    def __init__(self, manager: UploadManager, settings: Optional[QSettings] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._manager = manager
        self._settings = settings if settings is not None else QSettings(_ORGANIZATION, __app_name__)
        self._closed = False
        self._signals = _Signals(self)
        self._signals.finished.connect(self._on_finished, Qt.QueuedConnection)
        self._run = self._opts = self._results = self._plot = None
        self._busy = False
        self._job: Dict[str, Any] = {}  # snapshot taken at click time

        self.sample_edit = QLineEdit()
        self.date_edit = QLineEdit()
        self.date_edit.setPlaceholderText("DD/MM/YYYY")
        self.time_edit = QLineEdit()
        self.time_edit.setPlaceholderText("HH:MM")
        self.source_device_edit = QLineEdit()
        self.response_device_edit = QLineEdit()
        self.temperature_edit = QLineEdit()
        self.temperature_edit.setPlaceholderText("°C")
        self.gas_combo = QComboBox()
        self.gas_combo.setEditable(True)
        self.gas_combo.addItems(GAS_CHOICES)
        self.gas_combo.currentTextChanged.connect(lambda _t: self._refresh_enabled())
        self.save_btn = QPushButton("Save to database")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._on_save_clicked)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Sample", self.sample_edit)
        form.addRow("Date", self.date_edit)
        form.addRow("Time", self.time_edit)
        form.addRow("Power source", self.source_device_edit)
        form.addRow("Response device", self.response_device_edit)
        form.addRow("Temperature (°C)", self.temperature_edit)
        form.addRow("Gas", self.gas_combo)
        row = QHBoxLayout()
        row.addWidget(self.save_btn)
        row.addWidget(self.status_label, 1)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addLayout(row)
        self._fields = (self.sample_edit, self.date_edit, self.time_edit, self.source_device_edit,
                        self.response_device_edit, self.temperature_edit, self.gas_combo)

    # ---- pre-fill ----
    @staticmethod
    def _experiment_key(run, field: str) -> Optional[str]:
        exp = run.header.get("experiment") if run is not None else None
        # quoted: a "/" in the name must not nest QSettings groups
        return "save/last/%s/%s" % (urllib.parse.quote(str(exp), safe=""), field) if exp else None

    def clear_result(self) -> None:
        """Slot for AnalysisTab.result_cleared: no result to save any more. What was typed
        (sample, gas, ...) stays; a save already in flight carries its own snapshot."""
        self._run = self._opts = self._results = self._plot = None
        if not self._busy:
            self.status_label.setText("")
        self._refresh_enabled()

    def set_result(self, payload: Tuple[Any, Any, Any, Any]) -> None:
        """Slot for AnalysisTab.result_ready."""
        self._run, self._opts, self._results, self._plot = payload
        h = self._run.header
        started = h.get("started")
        self.date_edit.setText(started.strftime("%d/%m/%Y") if isinstance(started, datetime) else "")
        self.time_edit.setText(started.strftime("%H:%M") if isinstance(started, datetime) else "")
        self.source_device_edit.setText(instrument_device(h.get("instrument")))  # type: ignore[arg-type]
        self.response_device_edit.setText(calorimeter_device(h.get("calorimeter")))  # type: ignore[arg-type]
        self.temperature_edit.setText(region_temperature(self._run.parsed, self._opts.sel_min, self._opts.sel_max))
        k = self._experiment_key(self._run, "sample")
        self.sample_edit.setText(str(self._settings.value(k, "")) if k else "")
        k = self._experiment_key(self._run, "gas")
        self.gas_combo.setCurrentText(str(self._settings.value(k, "Ar")) if k else "Ar")
        if not self._busy:  # a save in flight keeps Save disabled until its job ends
            self.status_label.setText("")
            self._refresh_enabled()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for w in self._fields:
            w.setEnabled(not busy)
        self._refresh_enabled()

    def _refresh_enabled(self) -> None:
        gas_ok = bool(self.gas_combo.currentText().strip())
        self.save_btn.setEnabled(not self._busy and self._results is not None and gas_ok)
        if self._results is not None and not self._busy and not gas_ok:
            self.status_label.setText("Enter the gas (for example Ar or Air).")
        elif gas_ok and self.status_label.text().startswith("Enter the gas"):
            self.status_label.setText("")

    # ---- save ----
    def _validated_meta(self) -> Optional[RowMeta]:
        sample = self.sample_edit.text().strip()
        date, time_ = self.date_edit.text().strip(), self.time_edit.text().strip()
        if not sample:
            self.status_label.setText("Enter the sample name.")
            return None
        try:
            # saved as DD/MM/YYYY and HH:MM whatever was typed ("1/2/2026", "9:5"): the
            # duplicate check and the Runs tab compare these texts
            date = datetime.strptime(date, "%d/%m/%Y").strftime("%d/%m/%Y")
            time_ = datetime.strptime(time_, "%H:%M").strftime("%H:%M")
        except ValueError:
            self.status_label.setText("Date must be DD/MM/YYYY and time HH:MM.")
            return None
        temp_text = self.temperature_edit.text().strip()
        temperature: Optional[float] = None
        if temp_text:
            try:
                temperature = float(temp_text)
            except ValueError:
                temperature = None
            if temperature is None or not math.isfinite(temperature):
                self.status_label.setText("Temperature must be a number.")
                return None
        p = self._opts.params
        return RowMeta(
            model_name=sample, test_date=date, test_time=time_, temperature=temperature,
            gas_atmosphere=self.gas_combo.currentText(),
            power_source_device=self.source_device_edit.text(),
            power_response_device=self.response_device_edit.text(),
            wave_type=self._opts.wave_type, analysis_mode=p.analysis_mode, r1=p.r1_mm, r2=p.r2_mm,
            use_calibration=p.use_calibration, system_lag=p.system_lag, input_mode="one",
            source_file_name=os.path.basename(self._run.path))

    def _on_save_clicked(self) -> None:
        if self._busy or self._results is None or self._closed:
            return
        self._manager.login_succeeded()  # an explicit save may ask for the login again
        meta = self._validated_meta()
        if meta is None:
            return
        run, results, plot = self._run, self._results, self._plot

        def build_row() -> dict:  # in the pool thread: no maths, the plot came from the analysis process
            return build_analysis_row(results, meta, plot)

        self._job = {"build_row": build_row, "results": results,
                     "sample": meta.model_name, "gas": meta.gas_atmosphere,
                     "sample_key": self._experiment_key(run, "sample"),
                     "gas_key": self._experiment_key(run, "gas")}
        self._start("save")

    def _start(self, kind: str, row=None, target_id=None, retried: bool = False) -> None:
        if self._closed:
            return
        self._set_busy(True)
        self.status_label.setText("Saving…")
        QThreadPool.globalInstance().start(_SaveJob(
            self._signals, self._manager.client, kind, self._job["build_row"], row, target_id, retried))

    def _on_finished(self, out: dict) -> None:
        state, row = out["state"], out.get("row")
        if state == "ok":
            self._remember_values()
            self._finish("Saved." if out["kind"] != "update" else "Replaced the existing analysis.", out.get("id"))
            self._manager.request_flush()
        elif state == "duplicate":
            self._set_busy(False)
            self.status_label.setText("")
            choice = self._ask_duplicate(out["match"])
            if choice == "new":
                self._start("insert", row=row)
            elif choice == "replace":
                self._start("update", row=row, target_id=out["match"]["id"])
        elif state == "offline" and out["kind"] == "update":
            # the queue only inserts: a queued replace would add a second row
            self._set_busy(False)
            self.status_label.setText("Couldn't replace while offline; try again when you're online.")
        elif state == "offline":
            self._queue(row)
        elif state == "login":
            if not out["retried"] and self._login():
                self._manager.login_succeeded()
                self._start(out["kind"] if out["kind"] != "save" else "insert", row=row,
                            target_id=out["target_id"], retried=True)
            elif out["kind"] == "update":  # the queue only inserts: never queue a replace
                self._set_busy(False)
                self.status_label.setText("Not replaced: you're not logged in.")
            else:
                self._queue(row)
        else:
            self._set_busy(False)
            self.status_label.setText("Save failed: %s" % out.get("message", "unknown error"))

    def _queue(self, row: dict) -> None:
        try:
            self._manager.enqueue(row)
        except (OSError, ValueError) as e:  # disk full / folder gone: the form stays for another try
            self._set_busy(False)
            self.status_label.setText("Couldn't keep the result for later: %s" % e)
            return
        self._remember_values()
        self._finish(QUEUED_MESSAGE, None)

    def _finish(self, message: str, row_id: Any) -> None:
        # this result is stored (or queued): it cannot be saved again. A newer result that
        # arrived while the save ran stays armed.
        if self._results is self._job.get("results"):
            self._run = self._opts = self._results = self._plot = None
        self._set_busy(False)
        self.status_label.setText(message)
        self.saved.emit(row_id)

    def _remember_values(self) -> None:
        j = self._job
        if j.get("sample_key") and j.get("sample"):
            self._settings.setValue(j["sample_key"], j["sample"])
        if j.get("gas_key") and j.get("gas"):
            self._settings.setValue(j["gas_key"], j["gas"])
        self._settings.sync()

    def shutdown(self) -> None:
        """Stop accepting new jobs (a running one finishes harmlessly)."""
        self._closed = True

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)

    # ---- dialogs (overridable in tests) ----
    def _login(self) -> bool:
        return LoginDialog(self._manager.client, self).exec() == QDialog.Accepted

    def _ask_duplicate(self, match: dict) -> str:
        """'cancel' | 'new' | 'replace' - the choices of the webapp's duplicate modal."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Similar analysis already saved")
        box.setText("An existing analysis matches this one (same sample, date, method, and "
                    "very close period & A₁):")
        box.setInformativeText("%s · %s · %s · #%s\nT = %s s · A₁ = %s mW · α = %s" % (
            match.get("model_name"), match.get("test_date", ""), match.get("analysis_mode"), match.get("id"),
            _fmt_fixed(match.get("period_t")), _fmt_fixed(match.get("amplitude_a1")),
            _fmt_alpha(match.get("alpha_phase_raw"))))
        replace = box.addButton("Replace it", QMessageBox.AcceptRole)
        new = box.addButton("Save as new", QMessageBox.ActionRole)
        cancel = box.addButton("Cancel", QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        clicked = box.clickedButton()
        return "replace" if clicked is replace else "new" if clicked is new else "cancel"
