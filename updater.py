"""
In-app updater for the Calorimetric Thermal Wave Analysis Program.

Hits the GitHub Releases API, compares the latest tag to the running
version, and if newer downloads the platform-appropriate asset and
launches it (the installer on Windows, opens the zip on macOS so the
user can drag the .app into Applications).

This is intentionally tiny and synchronous — the download uses Qt's
event loop to avoid freezing the UI but doesn't spin up worker threads.
"""

import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import webbrowser
from typing import Optional

from PyQt5.QtWidgets import QMessageBox, QApplication


_GITHUB_LATEST_API = (
    "https://api.github.com/repos/OmerVered1/calorimetric-thermal-wave-analysis/releases/latest"
)

_WINDOWS_ASSET = "CTWA-Windows-Setup.exe"
_MACOS_ASSET = "CTWA-macOS.zip"


def _parse_version(v: str) -> tuple:
    """Parse 'v2.0.3', 'v2.0.3-rc1', or '2.0.3' into a comparable tuple."""
    v = (v or "").lstrip("v").strip()
    out = []
    for part in v.split("."):
        digits = "".join(c for c in part if c.isdigit())
        out.append(int(digits) if digits else 0)
    while len(out) < 3:
        out.append(0)
    return tuple(out)


def _fetch_latest_release(timeout: float = 10.0) -> dict:
    req = urllib.request.Request(
        _GITHUB_LATEST_API,
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "calorimetric-thermal-wave-analysis-updater"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read())


def _platform_asset_name() -> Optional[str]:
    if sys.platform == "win32":
        return _WINDOWS_ASSET
    if sys.platform == "darwin":
        return _MACOS_ASSET
    return None


def _download_with_progress(url: str, dest_path: str, parent_widget=None) -> bool:
    """Download a URL to dest_path, showing a modal progress dialog."""
    from PyQt5.QtWidgets import QProgressDialog
    from PyQt5.QtCore import Qt

    progress = QProgressDialog("Downloading update…", "Cancel", 0, 100, parent_widget)
    progress.setWindowTitle("Updating")
    progress.setWindowModality(Qt.ApplicationModal)
    progress.setMinimumDuration(0)
    progress.setValue(0)
    QApplication.processEvents()

    cancelled = {"flag": False}

    def reporthook(blocks: int, block_size: int, total_size: int):
        if progress.wasCanceled():
            cancelled["flag"] = True
            raise IOError("Download cancelled by user")
        if total_size > 0:
            percent = min(100, int(blocks * block_size * 100 / total_size))
            progress.setValue(percent)
            QApplication.processEvents()

    try:
        urllib.request.urlretrieve(url, dest_path, reporthook=reporthook)
    except Exception:
        progress.close()
        if cancelled["flag"]:
            return False
        raise
    progress.close()
    return True


def check_for_updates(current_version: str,
                      parent_widget=None,
                      silent_if_uptodate: bool = False) -> None:
    """Check the GitHub Releases API and offer to install the latest version.

    Args:
        current_version: e.g. ``__version__`` of the calling module.
        parent_widget:  parent widget for any modal dialogs.
        silent_if_uptodate:  when True, suppresses the "you're up to date"
            dialog (useful for an at-startup check).
    """
    try:
        data = _fetch_latest_release()
    except Exception as e:
        if not silent_if_uptodate:
            QMessageBox.warning(parent_widget, "Update check failed",
                                f"Couldn't reach GitHub Releases:\n{e}")
        return

    latest_tag = data.get("tag_name") or ""
    release_url = data.get("html_url") or ""
    assets = data.get("assets") or []

    if not latest_tag:
        if not silent_if_uptodate:
            QMessageBox.information(parent_widget, "Update check",
                                    "Couldn't read the latest release tag.")
        return

    if _parse_version(latest_tag) <= _parse_version(current_version):
        if not silent_if_uptodate:
            QMessageBox.information(
                parent_widget, "Up to date",
                f"You're on the latest version (v{current_version})."
            )
        return

    asset_name = _platform_asset_name()
    asset_url = None
    if asset_name:
        for a in assets:
            if a.get("name") == asset_name:
                asset_url = a.get("browser_download_url")
                break

    box = QMessageBox(parent_widget)
    box.setIcon(QMessageBox.Information)
    box.setWindowTitle("Update available")
    box.setText(f"<b>Version {latest_tag} is available.</b><br>"
                f"You're currently on v{current_version}.")
    if asset_url:
        box.setInformativeText(
            "Download and run the installer now?<br><br>"
            "You'll need to close the running app while the installer overwrites it."
        )
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.Yes)
    else:
        box.setInformativeText(
            f"No automatic installer for this platform. Open the release page in your browser?"
        )
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    reply = box.exec_()
    if reply != QMessageBox.Yes:
        return

    if not asset_url:
        if release_url:
            webbrowser.open(release_url)
        return

    # Download the platform asset to a temp dir
    try:
        tmp_dir = tempfile.mkdtemp(prefix="kss_update_")
        dest = os.path.join(tmp_dir, asset_name)
        ok = _download_with_progress(asset_url, dest, parent_widget)
        if not ok:
            return
    except Exception as e:
        QMessageBox.critical(parent_widget, "Download failed", str(e))
        return

    # Launch the installer / hand off to the user
    if sys.platform == "win32":
        try:
            subprocess.Popen([dest], shell=False)
        except Exception as e:
            QMessageBox.critical(parent_widget, "Failed to launch installer",
                                 f"{e}\n\nThe installer is at:\n{dest}")
            return
        QMessageBox.information(
            parent_widget,
            "Installer started",
            f"{asset_name} is running.\n\n"
            "Close this app when prompted so the installer can replace its files."
        )
    elif sys.platform == "darwin":
        try:
            subprocess.run(["open", "-R", dest], check=False)
        except Exception as e:
            QMessageBox.critical(parent_widget, "Failed to open download",
                                 f"{e}\n\nThe download is at:\n{dest}")
            return
        QMessageBox.information(
            parent_widget,
            "Update downloaded",
            f"Downloaded to:\n{dest}\n\n"
            "Quit this app, then unzip and drag the new .app into Applications "
            "(replace the existing one)."
        )
