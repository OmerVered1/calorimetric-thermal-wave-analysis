"""Help > About shows the CTWA logo (tools/make_icon.py writes the file)."""

import logging
import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QTextDocument  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402


def test_about_box_shows_the_logo(monkeypatch):
    logging.disable(logging.CRITICAL)
    app = QApplication.instance() or QApplication([])
    from ctwa import app as merged
    monkeypatch.setattr(merged.MainWindow, "_check_license_agreement", lambda self: True)
    shown = {}
    monkeypatch.setattr(QMessageBox, "about",
                        staticmethod(lambda parent, title, text: shown.update(text=text)))
    w = merged.MainWindow()
    try:
        w._show_about()
    finally:
        w.close()
        app.processEvents()

    src = re.search(r'<img src="([^"]+)"', shown["text"]).group(1)
    url = QUrl(src)
    assert url.isLocalFile() and os.path.isfile(url.toLocalFile())
    doc = QTextDocument()
    doc.setHtml(shown["text"])
    assert doc.resource(QTextDocument.ImageResource, url) is not None
