"""Password dialog for the webapp. The login call runs off the GUI thread.

The password lives only in the line edit, is handed to client.login once, and is
cleared right after the call; it is never logged or stored here (the client keeps the
token it gets back)."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout, QWidget)

from ctwa.cloud.client import NotLoggedIn, Offline, ServerError

WRONG_PASSWORD = "Incorrect password"
OFFLINE_MESSAGE = "Cannot connect to the server. Check the internet connection and try again."


class _Signals(QObject):
    finished = Signal(str)  # "" = logged in, else the message to show


class _LoginJob(QRunnable):
    def __init__(self, client, password: str, signals: _Signals) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._client, self._password, self._signals = client, password, signals

    def run(self) -> None:
        password, self._password = self._password, ""
        message = ""
        try:
            self._client.login(password)
        except NotLoggedIn:
            message = WRONG_PASSWORD
        except Offline:
            message = OFFLINE_MESSAGE
        except ServerError as e:
            message = "Server error: %s" % e
        except Exception as e:
            message = "Login failed (%s)" % type(e).__name__
        finally:
            del password
        self._signals.finished.emit(message)


class LoginDialog(QDialog):
    def __init__(self, client, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Log in to the results database")
        self._client = client
        self._pool = QThreadPool(self)
        self._signals = _Signals(self)
        self._signals.finished.connect(self._on_finished, Qt.QueuedConnection)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("Password")
        self.password_edit.returnPressed.connect(self._submit)
        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.ok_btn = QPushButton("Log in")
        self.ok_btn.setDefault(True)
        self.ok_btn.clicked.connect(self._submit)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.ok_btn)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Enter the webapp password to save results."))
        lay.addWidget(self.password_edit)
        lay.addWidget(self.error_label)
        lay.addLayout(buttons)

    def _submit(self) -> None:
        password = self.password_edit.text()
        if not password or not self.ok_btn.isEnabled():
            return
        self.password_edit.clear()
        self.error_label.setText("")
        self._set_busy(True)
        self._pool.start(_LoginJob(self._client, password, self._signals))

    def _set_busy(self, busy: bool) -> None:
        self.ok_btn.setEnabled(not busy)
        self.password_edit.setEnabled(not busy)

    def _on_finished(self, message: str) -> None:
        self._set_busy(False)
        if message:
            self.error_label.setText(message)
            self.password_edit.setFocus()
        else:
            self.accept()

    def done(self, result: int) -> None:
        self.password_edit.clear()
        super().done(result)
