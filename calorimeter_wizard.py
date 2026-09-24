"""Dialog for building a calorimeter setup by watching the instrument's traffic.

The flow is one screen, top to bottom, because it is one decision made in three
steps and a wizard's Next buttons would only hide the earlier answers:

    1. where to look   — instrument, IP, capture adapter
    2. what was found  — one row per request the vendor software sends, with
                         the byte field that looks most like a measurement
    3. what it means   — a name and a unit per row, then Save

Everything here is presentation. The capture and the analysis live in
`calorimeter_discovery`, which has no Qt in it and is tested without one.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from calorimeter_discovery import (
    DEFAULT_CAPTURE_S,
    Discovery,
    SignalChoice,
    capture_discovery,
    profile_from_choices,
    save_profile,
)
from calorimeter_reader import (
    CALORIMETERS,
    C80_PORT,
    discover_calorimeter_ip,
    sniff_capture_readiness,
    sniff_list_interfaces,
)
from calorimeter_setups import CalorimeterSetup, SetupStore


COL_USE, COL_REQUEST, COL_FIELD, COL_NAME, COL_UNIT, COL_PREVIEW = range(6)


class _CaptureWorker(QThread):
    """Runs one capture off the GUI thread."""

    progress = Signal(float, int)
    done = Signal(object)

    def __init__(self, host, port, interface, seconds, parent=None):
        super().__init__(parent)
        self._args = (host, port, interface, seconds)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        host, port, interface, seconds = self._args

        def on_progress(elapsed, packets):
            self.progress.emit(elapsed, packets)
            return not self._cancelled

        try:
            result = capture_discovery(
                host, port, interface, seconds, progress=on_progress
            )
        except Exception as e:  # pragma: no cover - defensive
            result = Discovery(analysis=None, error=f"capture failed: {e}")
        self.done.emit(result)


class CalorimeterSetupDialog(QDialog):
    """Create or edit a named calorimeter setup, deriving its signals live."""

    def __init__(self, parent=None, store: Optional[SetupStore] = None,
                 setup: Optional[CalorimeterSetup] = None):
        super().__init__(parent)
        self.setWindowTitle("Calorimeter Setup")
        self.setMinimumWidth(860)

        self._store = store if store is not None else SetupStore()
        self._discovery: Optional[Discovery] = None
        self._worker: Optional[_CaptureWorker] = None
        self.saved_setup: Optional[CalorimeterSetup] = None

        self._build_ui()
        if setup is not None:
            self._load_setup(setup)

    # ----- construction --------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        outer.addWidget(self._build_where_group())
        outer.addWidget(self._build_capture_row())
        outer.addWidget(self._build_results_group(), stretch=1)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        self._buttons.accepted.connect(self._on_save)
        self._buttons.rejected.connect(self.reject)
        self._buttons.button(QDialogButtonBox.Save).setEnabled(False)
        outer.addWidget(self._buttons)

    def _build_where_group(self) -> QGroupBox:
        group = QGroupBox("1 · Where to look")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.setup_name = QLineEdit()
        self.setup_name.setPlaceholderText("e.g. Drop @ bench, argon 800C")
        form.addRow("Setup name", self.setup_name)

        self.cal_combo = QComboBox()
        for name in CALORIMETERS:
            self.cal_combo.addItem(name)
        form.addRow("Calorimeter", self.cal_combo)

        host_row = QHBoxLayout()
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("192.168.x.x — or Discover by MAC")
        host_row.addWidget(self.host_edit, stretch=1)
        discover_btn = QPushButton("Discover")
        discover_btn.setToolTip(
            "Look the instrument up in the ARP cache by its MAC address.\n"
            "Needs something to have talked to it recently — normally Calisto."
        )
        discover_btn.clicked.connect(self._on_discover)
        host_row.addWidget(discover_btn)
        form.addRow("Address", self._wrap(host_row))

        iface_row = QHBoxLayout()
        self.iface_combo = QComboBox()
        self.iface_combo.setToolTip(
            "Which adapter to capture on. Auto-detect matches by subnet and can\n"
            "pick the wrong one (a Bluetooth adapter, in practice) — if the\n"
            "capture below sees no packets, choose the real NIC by hand."
        )
        iface_row.addWidget(self.iface_combo, stretch=1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_interfaces)
        iface_row.addWidget(refresh_btn)
        form.addRow("Capture on", self._wrap(iface_row))
        self._refresh_interfaces()

        return group

    def _build_capture_row(self) -> QGroupBox:
        group = QGroupBox("2 · Watch the traffic")
        row = QHBoxLayout(group)

        row.addWidget(QLabel("Capture for"))
        self.seconds_spin = QDoubleSpinBox()
        self.seconds_spin.setRange(5.0, 300.0)
        self.seconds_spin.setValue(DEFAULT_CAPTURE_S)
        self.seconds_spin.setSuffix(" s")
        self.seconds_spin.setDecimals(0)
        row.addWidget(self.seconds_spin)

        self.capture_btn = QPushButton("Start capture")
        self.capture_btn.clicked.connect(self._on_capture)
        row.addWidget(self.capture_btn)

        self.progress = QProgressBar()
        self.progress.setProperty("role", "labelled")   # tall enough for its status text
        self.progress.setTextVisible(True)
        self.progress.setFormat("idle")
        row.addWidget(self.progress, stretch=1)

        note = QLabel("Calisto must be running and polling the instrument.")
        note.setProperty("role", "faint")
        row.addWidget(note)
        return group

    def _build_results_group(self) -> QGroupBox:
        group = QGroupBox("3 · What the traffic means")
        layout = QVBoxLayout(group)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Use", "Request", "Field", "Name", "Unit", "Recent values"]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_USE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_REQUEST, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_FIELD, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_UNIT, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_PREVIEW, QHeaderView.Stretch)
        layout.addWidget(self.table, stretch=1)

        self.warnings_label = QLabel()
        self.warnings_label.setWordWrap(True)
        self.warnings_label.setProperty("role", "warn")
        layout.addWidget(self.warnings_label)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Save signals as profile"))
        self.profile_name = QLineEdit()
        self.profile_name.setPlaceholderText("e.g. Alexsys Drop")
        self.profile_name.setToolTip(
            "Reusing the name of a bundled profile replaces it for this user,\n"
            "and the replacement survives app updates."
        )
        name_row.addWidget(self.profile_name, stretch=1)
        layout.addLayout(name_row)
        return group

    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        layout.setContentsMargins(0, 0, 0, 0)   # otherwise the row sits lower than its label
        w.setLayout(layout)
        return w

    # ----- populating -----------------------------------------------------

    def _load_setup(self, setup: CalorimeterSetup) -> None:
        self.setup_name.setText(setup.name)
        idx = self.cal_combo.findText(setup.calorimeter)
        if idx >= 0:
            self.cal_combo.setCurrentIndex(idx)
        self.host_edit.setText(setup.host)
        self.profile_name.setText(setup.profile_name)
        if setup.interface:
            found = self.iface_combo.findData(setup.interface)
            if found >= 0:
                self.iface_combo.setCurrentIndex(found)

    def _refresh_interfaces(self) -> None:
        current = self.iface_combo.currentData()
        self.iface_combo.clear()
        self.iface_combo.addItem("Auto-detect (may guess wrong)", None)
        try:
            for iface in sniff_list_interfaces():
                self.iface_combo.addItem(iface.label(), iface.name)
        except Exception as e:
            self.iface_combo.addItem(f"(could not list adapters: {e})", None)
        if current:
            found = self.iface_combo.findData(current)
            if found >= 0:
                self.iface_combo.setCurrentIndex(found)

    def _on_discover(self) -> None:
        name = self.cal_combo.currentText()
        mac = CALORIMETERS.get(name, {}).get("mac", "")
        ip, diag = discover_calorimeter_ip(mac)
        if ip:
            self.host_edit.setText(ip)
        else:
            QMessageBox.information(
                self, "Not found",
                f"Could not find {name} in the ARP cache.\n\n{diag}\n\n"
                "Open Calisto and let it talk to the instrument, then retry — "
                "or type the IP in by hand."
            )

    # ----- capture --------------------------------------------------------

    def _on_capture(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self.capture_btn.setText("Stopping…")
            return

        host = self.host_edit.text().strip()
        if not host:
            QMessageBox.warning(self, "No host", "Enter or discover the instrument's IP first.")
            return

        readiness = sniff_capture_readiness()
        if not readiness.ok:
            detail = readiness.detail
            if readiness.remedy:
                detail += f"\n\n{readiness.remedy}"
            QMessageBox.warning(self, "Cannot capture", detail)
            return

        seconds = float(self.seconds_spin.value())
        self.progress.setRange(0, int(seconds))
        self.progress.setValue(0)
        self.capture_btn.setText("Stop")
        self._set_inputs_enabled(False)

        self._worker = _CaptureWorker(
            host, C80_PORT, self.iface_combo.currentData(), seconds, parent=self
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_capture_done)
        self._worker.start()

    def _on_progress(self, elapsed: float, packets: int) -> None:
        self.progress.setValue(int(elapsed))
        self.progress.setFormat(f"{elapsed:.0f}s — {packets} packets")

    def _on_capture_done(self, discovery: Discovery) -> None:
        self._worker = None
        self.capture_btn.setText("Start capture")
        self._set_inputs_enabled(True)
        self.progress.setValue(self.progress.maximum())
        self.progress.setFormat(f"{discovery.packets_seen} packets")

        self._discovery = discovery
        if discovery.error:
            self.table.setRowCount(0)
            self.warnings_label.setText(discovery.error)
            self._buttons.button(QDialogButtonBox.Save).setEnabled(False)
            return

        self._populate_table(discovery)
        self.warnings_label.setText("\n".join(discovery.warnings))
        self._buttons.button(QDialogButtonBox.Save).setEnabled(bool(discovery.channels))

    def _set_inputs_enabled(self, on: bool) -> None:
        for w in (self.host_edit, self.iface_combo, self.cal_combo, self.seconds_spin):
            w.setEnabled(on)

    def _populate_table(self, discovery: Discovery) -> None:
        self.table.setRowCount(len(discovery.channels))
        for row, found in enumerate(discovery.channels):
            use = QCheckBox()
            use.setChecked(found.best is not None)
            use.setEnabled(found.best is not None)
            self.table.setCellWidget(row, COL_USE, use)

            req = QTableWidgetItem(found.describe())
            req.setFlags(req.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, COL_REQUEST, req)

            field_combo = QComboBox()
            for cand in found.scan.candidates[:12]:
                field_combo.addItem(
                    f"{cand.describe()}  (latest {cand.latest:.6g})", cand
                )
            if not found.scan.candidates:
                field_combo.addItem("no numeric field found", None)
                field_combo.setEnabled(False)
            field_combo.currentIndexChanged.connect(
                lambda _i, r=row: self._refresh_preview(r)
            )
            self.table.setCellWidget(row, COL_FIELD, field_combo)

            self.table.setItem(row, COL_NAME, QTableWidgetItem(""))
            self.table.setItem(row, COL_UNIT, QTableWidgetItem(""))

            preview = QTableWidgetItem("")
            preview.setFlags(preview.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, COL_PREVIEW, preview)
            self._refresh_preview(row)

    def _refresh_preview(self, row: int) -> None:
        combo = self.table.cellWidget(row, COL_FIELD)
        item = self.table.item(row, COL_PREVIEW)
        if combo is None or item is None:
            return
        cand = combo.currentData()
        if cand is None:
            item.setText("")
            return
        tail = cand.preview[-6:]
        item.setText("  ".join(f"{v:.6g}" for v in tail))

    # ----- saving ---------------------------------------------------------

    def _collect_choices(self) -> List[SignalChoice]:
        choices: List[SignalChoice] = []
        for row in range(self.table.rowCount()):
            use = self.table.cellWidget(row, COL_USE)
            if use is None or not use.isChecked():
                continue
            combo = self.table.cellWidget(row, COL_FIELD)
            cand = combo.currentData() if combo is not None else None
            if cand is None:
                continue
            name_item = self.table.item(row, COL_NAME)
            unit_item = self.table.item(row, COL_UNIT)
            choices.append(
                SignalChoice(
                    channel_index=row,
                    candidate=cand,
                    name=name_item.text() if name_item else "",
                    unit=unit_item.text() if unit_item else "",
                )
            )
        return choices

    def _on_save(self) -> None:
        setup_name = self.setup_name.text().strip()
        profile_name = self.profile_name.text().strip()
        if not setup_name:
            QMessageBox.warning(self, "Name needed", "Give the setup a name.")
            return
        if not profile_name:
            QMessageBox.warning(self, "Name needed", "Give the signal profile a name.")
            return
        if self._discovery is None:
            QMessageBox.warning(self, "Nothing captured", "Run a capture first.")
            return

        choices = self._collect_choices()
        if not choices:
            QMessageBox.warning(
                self, "No signals",
                "Tick at least one request and give it a name and a unit."
            )
            return

        cal_name = self.cal_combo.currentText()
        try:
            profile = profile_from_choices(
                profile_name,
                self._discovery,
                choices,
                device_port=C80_PORT,
                mac=CALORIMETERS.get(cal_name, {}).get("mac", ""),
                notes=f"Derived from a live capture for setup {setup_name!r}.",
            )
        except ValueError as e:
            QMessageBox.warning(self, "Cannot build profile", str(e))
            return

        try:
            path = save_profile(profile)
        except OSError as e:
            QMessageBox.warning(self, "Could not save profile", str(e))
            return

        setup = CalorimeterSetup(
            name=setup_name,
            calorimeter=cal_name,
            profile_name=profile.name,
            host=self.host_edit.text().strip(),
            interface=self.iface_combo.currentData() or "",
            port=C80_PORT,
        )
        try:
            self._store.save(setup)
        except OSError as e:
            QMessageBox.warning(self, "Could not save setup", str(e))
            return

        self.saved_setup = setup
        QMessageBox.information(
            self, "Saved",
            f"Setup {setup_name!r} saved.\nProfile written to:\n{path}"
        )
        self.accept()

    # ----- teardown -------------------------------------------------------

    def reject(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)
        super().reject()
