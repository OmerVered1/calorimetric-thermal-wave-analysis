"""The source-meter half of the connect dialog: choose the model, then how.

This replaces the launcher. Where there used to be a separate program per
instrument, you now pick the instrument here, and the connection options below
change to fit it — an instrument list for USB/GPIB, an address with history for
LAN, a port list and baud rate for the 6430's RS-232.

Scanning happens on a worker thread. The original dialogs scanned on the UI
thread and froze for about a second every time they opened (longer on a busy
lab network, and tens of seconds for a serial auto-detect).
"""

from __future__ import annotations

from typing import Callable, List, Optional

from PySide6.QtCore import QObject, QSettings, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QInputDialog,
    QMessageBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ctwa import theme
from ctwa.instruments import discovery, registry
from ctwa.instruments.capabilities import LAN, SERIAL, VISA, Capabilities

_LAST_MODEL_KEY = "connection/last_model"
_LAN_HISTORY_KEY = "connection/lan_ip_history"
_LAN_HISTORY_MAX = 5
_BAUD_RATES = ("9600", "19200", "38400", "57600", "115200")


class _Job(QObject):
    done = Signal(object)

    def __init__(self, fn: Callable):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            result = self._fn()
        except Exception as exc:  # reported, never raised into Qt
            result = exc
        self.done.emit(result)


_live_threads = set()


def run_in_background(owner: QObject, fn: Callable, on_done: Callable) -> QThread:
    """Run ``fn`` on a worker thread and deliver its result on the UI thread.

    The thread is owned by the application, not by ``owner``. A VISA scan or a
    serial auto-detect cannot be interrupted, so if the dialog that started it
    is closed first, a thread owned by the dialog would be destroyed while still
    running — which makes Qt abort the whole program. Here the thread outlives
    the dialog, and its result is simply dropped if ``owner`` is gone.
    """
    from PySide6.QtCore import QCoreApplication
    import shiboken6

    thread = QThread(QCoreApplication.instance())
    job = _Job(fn)
    job.moveToThread(thread)
    thread.started.connect(job.run)

    def deliver(result):
        if shiboken6.isValid(owner):
            on_done(result)

    job.done.connect(deliver)
    job.done.connect(thread.quit)
    job.done.connect(job.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.finished.connect(lambda: _live_threads.discard(thread))
    thread._job = job  # keep it alive for the thread's lifetime
    _live_threads.add(thread)
    thread.start()
    return thread


def wait_for_background(timeout_ms: int = 3000) -> None:
    """Called at exit, so no scan is still running when Qt tears down."""
    for thread in list(_live_threads):
        thread.wait(timeout_ms)


class ChoiceCard(QFrame):
    """A selectable card: a name over its one-line summary.

    A frame rather than a push button: Qt sizes a QPushButton from its own
    text, so labels laid out inside one get clipped whatever height is asked
    for — the first version of this dialog showed four empty boxes.

    Behaves like a button: pressed while the mouse is down, activates on
    release over it, and takes focus from Tab (Space or Return picks it).
    """

    clicked = Signal()

    def __init__(self, title: str, summary: str, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.TabFocus)
        theme.set_role(self, "model-card", selected="false", pressed="false")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(2)
        lay.addWidget(theme.set_role(QLabel(title), "card-title"))
        text = theme.set_role(QLabel(summary), "faint")
        text.setWordWrap(True)
        lay.addWidget(text)

    def set_selected(self, on: bool):
        theme.set_prop(self, selected="true" if on else "false")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            theme.set_prop(self, pressed="true")
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            theme.set_prop(self, pressed="false")
            if self.rect().contains(event.position().toPoint()):
                self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.clicked.emit()
        else:
            super().keyPressEvent(event)


class ModelCard(ChoiceCard):
    """A source meter model and its one-line summary."""

    def __init__(self, caps: Capabilities, parent=None):
        super().__init__(caps.display_name, caps.summary, parent)
        self.caps = caps


class SMUConnectPanel(QWidget):
    """Emits ``connect_requested(model, address, simulate, resistance, baud)``."""

    connect_requested = Signal(str, object, bool, object, object)

    def __init__(self, settings: Optional[QSettings] = None, parent=None):
        super().__init__(parent)
        self.settings = settings or QSettings()
        self._threads: List[QThread] = []
        self._scan_serial = 0
        self._build()
        last = self.settings.value(_LAST_MODEL_KEY, registry.MODEL_ORDER[0])
        self.select_model(last if last in registry.MODELS else registry.MODEL_ORDER[0])

    # ----- layout -------------------------------------------------------

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 0)
        outer.setSpacing(8)

        outer.addWidget(theme.set_role(QLabel("Instrument"), "section"))
        grid = QGridLayout()
        grid.setSpacing(6)
        self._cards = {}
        for i, model in enumerate(registry.MODEL_ORDER):
            card = ModelCard(registry.get(model))
            card.clicked.connect(lambda m=model: self.select_model(m))
            self._cards[model] = card
            grid.addWidget(card, i // 2, i % 2)
        outer.addLayout(grid)

        # transport selector — only shown when a model has more than one
        self._transport_row = QWidget()
        tr = QHBoxLayout(self._transport_row)
        tr.setContentsMargins(0, 4, 0, 0)
        tr.setSpacing(0)
        tr.addWidget(theme.set_role(QLabel("Connection"), "section"))
        tr.addStretch()
        self._transport_buttons = {}
        self._transport_group = QButtonGroup(self)
        self._transport_group.setExclusive(True)
        for key, text in ((VISA, "USB / GPIB"), (LAN, "LAN"), (SERIAL, "RS-232")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.clicked.connect(lambda _c=False, k=key: self._show_transport(k))
            self._transport_group.addButton(b)
            self._transport_buttons[key] = b
        tr.addWidget(theme.segmented(*self._transport_buttons.values()))
        outer.addWidget(self._transport_row)

        self._stack = QStackedWidget()
        self._pages = {VISA: self._build_visa_page(), LAN: self._build_lan_page(),
                       SERIAL: self._build_serial_page()}
        for page in self._pages.values():
            self._stack.addWidget(page)
        outer.addWidget(self._stack, stretch=1)

        self._error = theme.set_role(QLabel(""), "danger")
        self._error.setWordWrap(True)
        self._error.hide()
        outer.addWidget(self._error)

        # footer: simulate on the left, connect on the right
        foot = QHBoxLayout()
        foot.setSpacing(6)
        self.simulate_btn = QPushButton("Simulate")
        self.simulate_btn.setToolTip("Run without hardware, against a simulated resistor.")
        self.simulate_btn.clicked.connect(self._simulate)
        foot.addWidget(self.simulate_btn)
        foot.addWidget(theme.set_role(QLabel("with a load of"), "muted"))
        self.sim_resistance = QDoubleSpinBox()
        self.sim_resistance.setRange(1, 1e12)
        self.sim_resistance.setDecimals(0)
        self.sim_resistance.setSuffix(" Ω")
        self.sim_resistance.setToolTip("Resistance the simulated instrument sees.")
        self.sim_resistance.setMinimumWidth(theme.scaled(110))
        foot.addWidget(self.sim_resistance)
        foot.addStretch()
        self.connect_btn = theme.set_role(QPushButton("Connect"), "primary")
        self.connect_btn.setDefault(True)
        self.connect_btn.clicked.connect(self._connect)
        foot.addWidget(self.connect_btn)
        outer.addLayout(foot)

    def _list_page(self, empty_hint: str, refresh_text: str, on_refresh) -> tuple:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        head = QHBoxLayout()
        status = theme.set_role(QLabel(""), "faint")
        head.addWidget(status)
        head.addStretch()
        refresh = theme.set_role(QPushButton(refresh_text), "quiet")
        refresh.clicked.connect(on_refresh)
        head.addWidget(refresh)
        lay.addLayout(head)
        lst = QListWidget()
        lst.setMinimumHeight(120)
        lst.itemDoubleClicked.connect(lambda _i: self._connect())
        lay.addWidget(lst, stretch=1)
        hint = theme.set_role(QLabel(empty_hint), "faint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return page, lst, status, refresh, hint

    def _build_visa_page(self):
        page, self.visa_list, self.visa_status, self.visa_refresh, self.visa_hint = self._list_page(
            "Nothing listed? Check the USB cable and that a VISA runtime (NI-VISA or "
            "Keysight IO) is installed.", "Scan again", self.scan)
        return page

    def _build_lan_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(theme.set_role(QLabel("IP address"), "muted"))
        self.ip_entry = QComboBox()
        self.ip_entry.setEditable(True)
        self.ip_entry.lineEdit().setPlaceholderText("e.g. 192.168.0.2")
        self.ip_entry.lineEdit().returnPressed.connect(self._connect)
        for ip in self._lan_history():
            self.ip_entry.addItem(ip)
        self.ip_entry.setCurrentText(self._lan_history()[0] if self._lan_history() else "")
        lay.addWidget(self.ip_entry)
        hint = theme.set_role(QLabel(
            "Recent addresses are remembered. A direct cable to the instrument usually "
            "needs your network adapter on the same subnet."), "faint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch()
        return page

    def _build_serial_page(self):
        page, self.serial_list, self.serial_status, self.serial_refresh, self.serial_hint = self._list_page(
            "A USB-to-serial adapter shows up here once its driver is installed.",
            "Scan again", self.scan)
        row = QHBoxLayout()
        row.addWidget(theme.set_role(QLabel("Baud rate"), "muted"))
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(_BAUD_RATES)
        row.addWidget(self.baud_combo)
        row.addStretch()
        self.autodetect_btn = QPushButton("Find it for me")
        self.autodetect_btn.setToolTip("Try every port and baud rate. Takes a little while.")
        self.autodetect_btn.clicked.connect(self._autodetect)
        row.addWidget(self.autodetect_btn)
        page.layout().insertLayout(2, row)
        return page

    # ----- model & transport ---------------------------------------------

    @property
    def model(self) -> str:
        return self._model

    @property
    def caps(self) -> Capabilities:
        return registry.get(self._model)

    def select_model(self, model: str):
        self._model = model
        for key, card in self._cards.items():
            card.set_selected(key == model)
        caps = self.caps
        for key, button in self._transport_buttons.items():
            button.setVisible(key in caps.transports)
        self._transport_row.setVisible(True)
        self.sim_resistance.setValue(caps.default_simulation_resistance)
        self._show_transport(caps.transports[0])
        self._clear_error()
        self.settings.setValue(_LAST_MODEL_KEY, model)

    def _show_transport(self, key: str):
        self._transport = key
        self._transport_buttons[key].setChecked(True)
        self._stack.setCurrentWidget(self._pages[key])
        if key == LAN:
            self.ip_entry.setFocus()
        else:
            self.scan()

    # ----- scanning -------------------------------------------------------

    def scan(self):
        """Refresh the list for the current transport, off the UI thread."""
        if self._transport == LAN:
            return
        self._scan_serial += 1
        token = self._scan_serial
        caps = self.caps
        if self._transport == SERIAL:
            lst, status, button = self.serial_list, self.serial_status, self.serial_refresh
            fn = discovery.list_serial
        else:
            lst, status, button = self.visa_list, self.visa_status, self.visa_refresh
            fn = lambda: discovery.list_visa(caps)
        status.setText("Looking for instruments…")
        button.setEnabled(False)

        def done(result, lst=lst, status=status, button=button, token=token):
            if token != self._scan_serial:
                return  # a newer scan superseded this one
            button.setEnabled(True)
            lst.clear()
            if isinstance(result, Exception):
                status.setText(f"Scan failed: {result}")
                return
            for found in result:
                item = QListWidgetItem(found.label)
                item.setData(Qt.UserRole, found.address)
                item.setToolTip(found.address)
                lst.addItem(item)
            if result:
                lst.setCurrentRow(0)
                status.setText(f"{len(result)} found")
            else:
                status.setText("None found")
                # Say so in the list itself, where the eye already is. The item
                # carries no address, so it can never be connected to.
                empty = QListWidgetItem("No instruments found. Check the cable, then Scan again.")
                empty.setFlags(Qt.NoItemFlags)
                lst.addItem(empty)

        self._threads.append(run_in_background(self, fn, done))

    def _autodetect(self):
        self.autodetect_btn.setEnabled(False)
        self.serial_status.setText("Trying every port and baud rate…")

        def done(result):
            self.autodetect_btn.setEnabled(True)
            if isinstance(result, Exception) or not result:
                self.serial_status.setText("No 6430 answered.")
                return
            port, baud = result
            self.serial_status.setText(f"Found on {port} at {baud} baud")
            self.baud_combo.setCurrentText(str(baud))
            for i in range(self.serial_list.count()):
                if self.serial_list.item(i).data(Qt.UserRole) == port:
                    self.serial_list.setCurrentRow(i)
                    break
            else:
                item = QListWidgetItem(port)
                item.setData(Qt.UserRole, port)
                self.serial_list.addItem(item)
                self.serial_list.setCurrentItem(item)

        self._threads.append(run_in_background(self, discovery.autodetect_6430, done))

    # ----- actions ---------------------------------------------------------

    def _selected(self, lst: QListWidget) -> Optional[str]:
        item = lst.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _connect(self):
        self._clear_error()
        if self._transport == LAN:
            ip = self.ip_entry.currentText().strip()
            if not ip:
                return self.show_error("Enter the instrument's IP address.")
            self._connect_lan(ip)
        elif self._transport == SERIAL:
            port = self._selected(self.serial_list)
            if not port:
                return self.show_error("Choose a serial port.")
            self.connect_requested.emit(self._model, port, False, None,
                                        int(self.baud_combo.currentText()))
        else:
            address = self._selected(self.visa_list)
            if not address:
                return self.show_error("Choose an instrument from the list.")
            self.connect_requested.emit(self._model, address, False, None, None)

    # ----- LAN, with the 2611A window's unreachable-instrument fix -----------

    def _connect_lan(self, ip: str):
        """Check the address answers (in the background) before connecting."""
        import network_setup

        self.connect_btn.setEnabled(False)
        self.connect_btn.setText("Checking…")

        def reached(ok):
            self.connect_btn.setEnabled(True)
            self.connect_btn.setText("Connect")
            if ok is True or self._offer_network_fix(ip):
                self._remember_ip(ip)
                self.connect_requested.emit(self._model, discovery.visa_address_for_ip(ip),
                                            False, None, None)

        self._threads.append(run_in_background(self, lambda: network_setup.is_reachable(ip), reached))

    def _offer_network_fix(self, ip: str) -> bool:
        """Carried over from the 2611A window. A direct cable to an instrument
        with a static IP often fails because this PC's adapter sits on another
        subnet (typically auto-assigned 169.254.x.x)."""
        reply = QMessageBox.question(
            self, "Instrument unreachable",
            f"Can't reach {ip} on the network.\n\n"
            "This usually happens when the instrument is on a dedicated LAN cable "
            "with a static IP and your network adapter is on a different subnet "
            "(auto-assigned 169.254.x.x).\n\n"
            "Try to add an address on that subnet to one of your network adapters?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return False
        return self._auto_configure_network(ip)

    def _auto_configure_network(self, target_ip: str) -> bool:
        """Add a secondary IP to an adapter so it can reach target_ip. Existing
        addresses are left untouched. Windows only — elsewhere, instructions."""
        import sys
        import network_setup

        if sys.platform != "win32":
            QMessageBox.information(
                self, "Manual setup required",
                f"Automatic set-up is only available on Windows.\n\n"
                f"Give your network adapter a static IP in the same /24 subnet as "
                f"{target_ip} (the same first three numbers).")
            return False
        adapters = network_setup.list_windows_adapters()
        if not adapters:
            QMessageBox.warning(self, "No adapters found", "Could not list network adapters.")
            return False
        labels = [f"{a['Name']}  ({a.get('IPAddress') or 'no IP'})" for a in adapters]
        choice, ok = QInputDialog.getItem(
            self, "Select adapter", "Which network adapter is connected to the instrument?",
            labels, 0, False)
        if not ok:
            return False
        adapter = adapters[labels.index(choice)]
        suggested = network_setup.suggest_secondary_ip(target_ip)
        QMessageBox.information(
            self, "Administrator approval needed",
            f"Windows will now ask for administrator approval to add {suggested} "
            f"to '{adapter['Name']}'. Click Yes on that prompt.")
        success, msg = network_setup.add_secondary_ip_windows(adapter["Name"], suggested)
        if not success:
            QMessageBox.critical(self, "Set-up failed", msg)
            return False
        if network_setup.is_reachable(target_ip):
            QMessageBox.information(self, "Network configured", f"{msg}\n\n{target_ip} is now reachable.")
            return True
        QMessageBox.warning(
            self, "Still unreachable",
            f"{msg}\n\nBut {target_ip} still isn't responding. Check the instrument's "
            "LAN cable and the IP set on its front panel.")
        return False

    def _simulate(self):
        self._clear_error()
        self.connect_requested.emit(self._model, None, True, self.sim_resistance.value(), None)

    def show_error(self, text: str):
        self._error.setText(text)
        self._error.show()

    def _clear_error(self):
        self._error.hide()

    # ----- LAN history --------------------------------------------------------

    def _lan_history(self) -> List[str]:
        raw = self.settings.value(_LAN_HISTORY_KEY, "")
        return [ip for ip in str(raw).split(",") if ip] if raw else []

    def _remember_ip(self, ip: str):
        history = [ip] + [x for x in self._lan_history() if x != ip]
        self.settings.setValue(_LAN_HISTORY_KEY, ",".join(history[:_LAN_HISTORY_MAX]))
