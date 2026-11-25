"""Tests never touch the user's real application settings."""

import hashlib
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication


def _real_settings_files():
    """Where this OS keeps the app's real settings (the native location, ignoring any redirect)."""
    from ctwa.app import __organization__, __app_name__
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        pref = os.path.join(home, "Library", "Preferences")
        dom = __organization__.lower().replace(" ", "-")
        return [os.path.join(pref, f"com.{dom}.{__app_name__}.plist")]
    if sys.platform == "win32":
        return []   # the registry: checked through fileName() below
    return [os.path.join(home, ".config", __organization__, __app_name__ + ".conf")]


def _digest(path):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest(), os.path.getmtime(path)


def test_main_window_construction_does_not_touch_the_real_settings(tmp_path):
    from ctwa import app as appmod
    app = QApplication.instance() or QApplication([])
    before = {p: _digest(p) for p in _real_settings_files()}
    appmod.MainWindow._check_license_agreement = lambda self: True
    w = appmod.MainWindow()
    try:
        w.settings.setValue("isolation/probe", "x")
        w.settings.sync()
        name = w.settings.fileName()
        assert name not in _real_settings_files()
        assert "/Library/Preferences/" not in name.replace("\\", "/")
        assert w.runs_tab.settings.fileName() == name
        assert w.save_panel._settings.fileName() == name
    finally:
        w.close()
    app.processEvents()
    assert {p: _digest(p) for p in _real_settings_files()} == before


def test_a_qsettings_built_by_the_app_code_is_an_ini_file_in_a_scratch_folder():
    from ctwa.ui import runs_tab
    s = runs_tab.QSettings("Some Org", "Some App")
    assert s.format() == QSettings.IniFormat
    assert "/Library/Preferences/" not in s.fileName()
