"""No grey text (Omer, Nov 2026); only switched-off things stay grey."""

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ctwa import theme  # noqa: E402

P = theme.P


def test_text_is_black_and_disabled_stays_grey():
    QApplication.instance() or QApplication([])  # the stylesheet loads fonts
    assert P.text_muted == P.text_faint == P.text
    assert P.text_disabled != P.text

    css = theme.stylesheet()
    blocks = re.findall(r"([^{}]+)\{([^{}]*)\}", css)
    disabled = [(sel, decl) for sel, decl in blocks if ":disabled" in sel]
    assert disabled, "no :disabled rules found"
    for sel, decl in disabled:
        m = re.search(r"(?<![-\w])color:\s*([^;]+);", decl)
        if not m:
            continue
        colour = m.group(1).strip()
        # the primary button keeps its own warm disabled colours; every other
        # disabled text is the shared grey
        if 'role="primary"' not in sel:
            assert colour == P.text_disabled, (sel.strip(), colour)

    # no non-disabled rule paints text in the old greys
    for sel, decl in blocks:
        if ":disabled" in sel:
            continue
        for old in ("#595C61", "#84878D"):
            assert old.lower() not in decl.lower(), (sel.strip(), old)


def test_placeholder_text_is_black():
    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    assert app.palette().color(QPalette.PlaceholderText).name().lower() == P.text.lower()
