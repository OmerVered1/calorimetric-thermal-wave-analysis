"""The bundled Google Sans builds load, have their weights, and the numeric
family really has fixed-width digits — the reason it exists."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFontDatabase, QFontInfo, QFontMetricsF  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from ctwa import theme  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_bundled_families_load(app):
    assert theme.fonts() == (theme.UI_FAMILY, theme.NUMERIC_FAMILY)


@pytest.mark.parametrize("family", [theme.UI_FAMILY, theme.NUMERIC_FAMILY])
def test_every_weight_is_there(app, family):
    theme.fonts()
    assert {"Regular", "Medium", "SemiBold", "Bold"} <= set(QFontDatabase.styles(family))


@pytest.mark.parametrize("css, style", [(400, "Regular"), (theme.W_MEDIUM, "Medium"),
                                        (theme.W_SEMIBOLD, "SemiBold"), (700, "Bold")])
def test_stylesheet_weights_pick_the_right_face(app, css, style):
    theme.fonts()
    label = QLabel("x")
    label.setStyleSheet(f'font-family: "{theme.UI_FAMILY}"; font-weight: {css};')
    label.ensurePolished()
    assert QFontInfo(label.font()).styleName() == style


def test_numeric_digits_and_minus_share_one_width(app):
    metrics = QFontMetricsF(theme.numeric_font(24))
    widths = {round(metrics.horizontalAdvance(c), 3) for c in "0123456789-"}
    assert len(widths) == 1


def test_interface_digits_stay_proportional(app):
    """Only the numeric copy is tabular; body text keeps Google Sans's normal figures."""
    metrics = QFontMetricsF(theme.ui_font(24))
    assert metrics.horizontalAdvance("1") < metrics.horizontalAdvance("0")
