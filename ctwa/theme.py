"""The look of the program, in one place.

Widgets say what they *are* (a primary button, a card, a status pill) through a
dynamic ``role`` property; this module decides what that looks like. Nothing
else in the program sets a colour.

Design language: a dense desktop instrument panel.

* Surfaces are layered by lightness, darkest furthest back: the window
  background, then panels (toolbar, tab pages, sidebars), then cards, then
  white for anything you type into or read data from (inputs, lists, tables,
  plots, menus). Two neighbouring surfaces of the same colour always get a
  1 px border between them.
* One accent, heater amber, spent on the primary action. A deeper amber marks
  keyboard focus and checked boxes, where the pale fill would be too faint to
  see on a light grey.
* Google Sans for everything, bundled so the program looks the same on every
  lab PC. Numbers use a copy with fixed-width digits ("CTWA Sans Tabular"),
  so readouts don't shift sideways as they change. See assets/fonts/README.md.
* Every clickable control has hover, pressed, keyboard-focus and disabled
  states, all instant: a stylesheet has no transitions.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractSpinBox, QApplication, QComboBox, QFrame,
    QHBoxLayout, QLineEdit, QSizePolicy, QTabBar, QWidget,
)


@dataclass(frozen=True)
class Palette:
    # Surfaces, back to front
    canvas: str = "#DCDDDF"        # window background, the most recessed
    panel: str = "#E9EAEC"         # toolbar, status bar, tab pages, dialogs
    card: str = "#F6F6F7"          # cards inside a panel
    raised: str = "#FFFFFF"        # inputs, lists, tables, plots, menus
    # Lines
    hairline: str = "#D3D5D8"      # card edges
    border: str = "#C3C6CA"        # controls and panels
    border_strong: str = "#A9ADB3" # hover, and the lower edge that makes a button look raised
    # Text
    text: str = "#1B1C1E"
    text_muted: str = "#595C61"
    text_faint: str = "#84878D"
    # Neutral overlays: darken whatever surface they sit on, so one hover
    # colour works on the canvas, a panel and a card alike.
    hover: str = "rgba(27, 28, 30, 0.06)"
    press: str = "rgba(27, 28, 30, 0.12)"
    # Unselected folder tabs: a step darker than what they sit on
    tab_chip: str = "rgba(27, 28, 30, 0.07)"
    tab_chip_hover: str = "rgba(27, 28, 30, 0.03)"
    tab_chip_press: str = "rgba(27, 28, 30, 0.13)"
    button_hover: str = "#F1F2F3"
    button_press: str = "#E1E3E6"
    # Heater amber
    accent: str = "#E0A040"
    accent_hover: str = "#D5932F"
    accent_pressed: str = "#C2821F"
    accent_edge: str = "#B07318"
    accent_text: str = "#241A08"
    accent_strong: str = "#9C6410"  # focus rings, checked boxes
    accent_soft: str = "#F4E2BF"    # selection
    accent_tint: str = "#FDF6E8"    # a selected card
    # Status
    ok: str = "#2E7543"
    ok_hover: str = "#296A3C"
    ok_soft: str = "#DCECDF"
    warn: str = "#8F5E0E"
    warn_soft: str = "#F4E5C6"
    danger: str = "#AF3A2C"
    danger_soft: str = "#F3DCD8"
    danger_edge: str = "#DDB4AD"
    # Plots: distinct and readable on white. Order is the series order.
    series: tuple = (
        "#C96442",  # clay       — heat flow
        "#3B6EA8",  # slate blue — sample T
        "#B8862B",  # ochre      — external T
        "#3F7A4F",  # moss       — voltage
        "#8A5A9E",  # plum       — current
        "#2F8C8C",  # teal       — resistance
        "#6F6D66",  # graphite   — power
        "#A64D79",  # berry
    )


P = Palette()

RADIUS = 4        # controls
RADIUS_CARD = 6   # cards and panels

# Type scale, in pixels. TEXT is the one to change: every other size, and the
# widths of fields and panels that hold text (see ``scaled``), follow it.
TEXT = 14                  # body: labels, inputs, buttons, lists, tables
TEXT_SMALL = TEXT - 2      # section titles, captions, status bar, plot ticks
TEXT_AXIS = TEXT - 1       # plot axis titles
TEXT_HEADING = TEXT + 1
TEXT_TITLE = TEXT + 3
TEXT_READOUT = 2 * TEXT    # the multimeter's big numbers
ROW_HEIGHT = TEXT + 12     # table rows

# The layout was drawn at 12 px text; widths that hold text grow with it.
_DESIGN_TEXT = 12


def scaled(px: int) -> int:
    """A width drawn for 12 px text, at the current text size."""
    return round(px * TEXT / _DESIGN_TEXT)

# Stylesheet font weights, on the CSS scale Qt 6 uses directly.
W_MEDIUM = 500
W_SEMIBOLD = 600

UI_FAMILY = "CTWA Sans"              # Google Sans, renamed as its trademark notice asks
NUMERIC_FAMILY = "CTWA Sans Tabular"  # the same, with fixed-width digits


def asset(name: str) -> str:
    """Absolute path to a bundled asset, in the forward-slash form Qt needs.

    Works from source and from a PyInstaller build, where data files live
    under sys._MEIPASS rather than next to this module. Qt refuses relative
    paths for application fonts, so this is always absolute.
    """
    from pathlib import Path

    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) / "ctwa" / "assets" if base else Path(__file__).resolve().parent / "assets"
    return (root / name).as_posix()


_fonts_loaded = None


def _load_fonts() -> bool:
    """Register the bundled font files once. False if any failed to load."""
    global _fonts_loaded
    if _fonts_loaded is None:
        from pathlib import Path

        files = sorted(Path(asset("fonts")).glob("*.ttf"))
        ok = bool(files)
        for f in files:
            if QFontDatabase.addApplicationFont(f.as_posix()) < 0:
                ok = False
        families = QFontDatabase.families()
        _fonts_loaded = ok and UI_FAMILY in families and NUMERIC_FAMILY in families
    return _fonts_loaded


def fonts():
    """Font families in use: (ui, numeric). The system's own only if the
    bundled ones failed to load, which would mean the assets folder is missing
    from a build."""
    if _load_fonts():
        return UI_FAMILY, NUMERIC_FAMILY
    if sys.platform == "darwin":
        return "Helvetica Neue", "Menlo"
    if sys.platform == "win32":
        return "Segoe UI", "Consolas"
    return "Sans Serif", "Monospace"


def stylesheet() -> str:
    ui, mono = fonts()   # "mono" here: the fixed-width-digit numeric family
    p = P
    return f"""
/* ---------- base ---------------------------------------------------- */
QWidget {{
    font-family: "{ui}";
    font-size: {TEXT}px;
    color: {p.text};
}}
QMainWindow {{ background: {p.canvas}; }}
QDialog {{ background: {p.panel}; }}
QToolTip {{
    background: {p.text}; color: {p.raised}; border: none;
    padding: 4px 6px; border-radius: 3px;
}}

/* ---------- text roles ---------------------------------------------- */
QLabel[role="title"]      {{ font-size: {TEXT_TITLE}px; font-weight: {W_SEMIBOLD}; }}
QLabel[role="heading"]    {{ font-size: {TEXT_HEADING}px; font-weight: {W_SEMIBOLD}; }}
QLabel[role="card-title"] {{ font-size: {TEXT}px; font-weight: {W_SEMIBOLD}; background: transparent; }}
QLabel[role="section"]    {{ font-size: {TEXT_SMALL}px; font-weight: {W_SEMIBOLD}; color: {p.text_muted}; }}
QLabel[role="muted"]      {{ color: {p.text_muted}; }}
QLabel[role="faint"]      {{ color: {p.text_faint}; font-size: {TEXT_SMALL}px; background: transparent; }}
QLabel[role="mono"]       {{ font-family: "{mono}"; }}
QLabel[role="ok"]         {{ color: {p.ok}; }}
QLabel[role="warn"]       {{ color: {p.warn}; }}
QLabel[role="danger"]     {{ color: {p.danger}; }}

/* status chips: source meter, calorimeter, recording */
QLabel[role="pill"] {{
    padding: 2px 8px; border-radius: 4px; font-size: {TEXT_SMALL}px; font-weight: {W_SEMIBOLD};
    background: {p.hover}; color: {p.text_muted};
}}
QLabel[role="pill"][tone="ok"]     {{ background: {p.ok_soft};     color: {p.ok}; }}
QLabel[role="pill"][tone="warn"]   {{ background: {p.warn_soft};   color: {p.warn}; }}
QLabel[role="pill"][tone="danger"] {{ background: {p.danger_soft}; color: {p.danger}; }}
QLabel[role="pill"][tone="accent"] {{ background: {p.accent_soft}; color: {p.accent_text}; }}

/* big numeric readouts and small figures */
QLabel[role="readout"] {{
    font-family: "{mono}"; font-size: {TEXT_READOUT}px; color: {p.text}; background: transparent;
}}
QLabel[role="readout-label"] {{
    font-size: {TEXT_SMALL}px; font-weight: {W_SEMIBOLD}; color: {p.text_muted}; background: transparent;
}}
QLabel[role="signal-value"] {{
    font-family: "{mono}"; font-size: {TEXT}px; color: {p.text}; background: transparent;
}}
QLabel[role="stat-label"] {{ font-size: {TEXT_SMALL}px; color: {p.text_muted}; background: transparent; }}
QLabel[role="stat-value"] {{ font-family: "{mono}"; font-size: {TEXT}px; background: transparent; }}
QLabel[role="stat-value"][tone="danger"] {{ color: {p.danger}; font-weight: {W_SEMIBOLD}; }}

/* ---------- surfaces ------------------------------------------------ */
QFrame[role="toolbar"] {{
    background: {p.panel}; border: none; border-bottom: 1px solid {p.border};
}}
QFrame[role="card"], QFrame[role="readout-card"] {{
    background: {p.card}; border: 1px solid {p.hairline}; border-radius: {RADIUS_CARD}px;
}}
QFrame[role="divider"] {{ background: {p.border}; max-width: 1px; min-width: 1px; border: none; }}
QFrame[role="swatch"] {{ border: none; border-radius: 4px; }}

QGroupBox {{
    background: {p.card}; border: 1px solid {p.hairline}; border-radius: {RADIUS_CARD}px;
    margin-top: 0px; padding: 26px 10px 8px 10px;
    font-size: {TEXT_SMALL}px; font-weight: {W_SEMIBOLD}; color: {p.text_muted};
}}
QGroupBox::title {{
    subcontrol-origin: padding; subcontrol-position: top left;
    left: 10px; top: 7px; padding: 0px;
}}
QGroupBox[role="plain"] {{ padding-top: 8px; }}

/* ---------- buttons ------------------------------------------------- */
QPushButton, QToolButton {{
    background: {p.raised}; color: {p.text};
    border: 1px solid {p.border}; border-bottom-color: {p.border_strong};
    border-radius: {RADIUS}px; padding: 3px 10px; min-height: 16px;
}}
QPushButton:hover, QToolButton:hover {{ background: {p.button_hover}; border-color: {p.border_strong}; }}
QPushButton:pressed, QToolButton:pressed, QToolButton:open {{
    background: {p.button_press};
    border-color: {p.border_strong}; border-bottom-color: {p.border};
    padding: 4px 10px 2px 10px;
}}
QPushButton:focus, QToolButton:focus {{ border: 2px solid {p.accent_strong}; padding: 2px 9px; }}
QPushButton:focus:pressed, QToolButton:focus:pressed {{ padding: 3px 9px 1px 9px; }}
QPushButton:disabled, QToolButton:disabled {{
    color: {p.text_faint}; background: {p.card}; border-color: {p.hairline};
}}
QToolButton::menu-indicator {{ image: none; width: 0px; }}

QPushButton[role="primary"] {{
    background: {p.accent}; color: {p.accent_text}; font-weight: {W_SEMIBOLD};
    border: 1px solid {p.accent_pressed}; border-bottom-color: {p.accent_edge};
}}
QPushButton[role="primary"]:hover   {{ background: {p.accent_hover}; }}
QPushButton[role="primary"]:pressed {{
    background: {p.accent_pressed}; border-color: {p.accent_edge}; border-bottom-color: {p.accent_pressed};
}}
QPushButton[role="primary"]:focus   {{ border: 2px solid {p.text}; }}
QPushButton[role="primary"]:disabled {{
    background: #EEDDBE; color: #9A8C74; border-color: #E4D2AF;
}}

QPushButton[role="danger"] {{ color: {p.danger}; }}
QPushButton[role="danger"]:hover {{ background: {p.danger_soft}; border-color: {p.danger_edge}; }}
QPushButton[role="danger"]:pressed {{ background: #EBCBC5; }}
QPushButton[role="danger"]:disabled {{ color: {p.text_faint}; background: {p.card}; border-color: {p.hairline}; }}

QPushButton[role="quiet"], QToolButton[role="quiet"] {{
    background: transparent; border: 1px solid transparent; color: {p.text_muted};
}}
QPushButton[role="quiet"]:hover, QToolButton[role="quiet"]:hover {{ background: {p.hover}; color: {p.text}; }}
QPushButton[role="quiet"]:pressed, QToolButton[role="quiet"]:pressed,
QToolButton[role="quiet"]:open {{ background: {p.press}; color: {p.text}; }}
QPushButton[role="quiet"]:focus, QToolButton[role="quiet"]:focus {{ border: 2px solid {p.accent_strong}; }}
QPushButton[role="quiet"]:disabled, QToolButton[role="quiet"]:disabled {{
    color: {p.text_faint}; background: transparent; border-color: transparent;
}}

/* output switch: reads as a state, not an action */
QPushButton[role="output"] {{ font-weight: {W_SEMIBOLD}; min-width: {scaled(84)}px; }}
QPushButton[role="output"][live="true"] {{
    background: {p.ok}; color: white; border-color: {p.ok_hover}; border-bottom-color: #1F4F2E;
}}
QPushButton[role="output"][live="true"]:hover   {{ background: {p.ok_hover}; }}
QPushButton[role="output"][live="true"]:pressed {{ background: #245C35; }}

/* segmented control: chips inside a recessed track */
QFrame[role="segmented"] {{
    background: {p.hover}; border: 1px solid {p.hairline}; border-radius: 5px;
}}
QPushButton[role="segment"] {{
    background: transparent; color: {p.text_muted};
    border: 1px solid transparent; border-radius: {RADIUS}px;
    padding: 1px 10px; min-height: 16px;
}}
QPushButton[role="segment"]:hover   {{ background: {p.hover}; color: {p.text}; }}
QPushButton[role="segment"]:pressed {{ background: {p.press}; padding: 2px 10px 0px 10px; }}
QPushButton[role="segment"]:checked {{
    background: {p.raised}; color: {p.text};
    border: 1px solid {p.border}; border-bottom-color: {p.border_strong};
}}
QPushButton[role="segment"]:focus   {{ border: 2px solid {p.accent_strong}; padding: 0px 9px; }}
QPushButton[role="segment"]:disabled {{ color: {p.text_faint}; background: transparent; border-color: transparent; }}

/* instrument picker cards */
QFrame[role="model-card"] {{
    background: {p.raised}; border: 1px solid {p.border}; border-bottom-color: {p.border_strong};
    border-radius: {RADIUS_CARD}px;
}}
QFrame[role="model-card"]:hover {{ border-color: {p.border_strong}; background: #FBFBFB; }}
QFrame[role="model-card"][pressed="true"] {{ background: {p.button_press}; }}
QFrame[role="model-card"][selected="true"] {{ border: 2px solid {p.accent}; background: {p.accent_tint}; }}
QFrame[role="model-card"]:focus {{ border: 2px solid {p.accent_strong}; }}
QFrame[role="model-card"]:disabled {{ background: {p.card}; border-color: {p.hairline}; }}

/* ---------- inputs -------------------------------------------------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit, QPlainTextEdit, QTextEdit {{
    background: {p.raised}; border: 1px solid {p.border}; border-radius: {RADIUS}px;
    padding: 2px 6px; min-height: 18px;
    selection-background-color: {p.accent_soft}; selection-color: {p.text};
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover,
QPlainTextEdit:hover, QTextEdit:hover {{ border-color: {p.border_strong}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {{ border: 2px solid {p.accent_strong}; padding: 1px 5px; }}
QComboBox:on {{ background: {p.button_press}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QPlainTextEdit:disabled, QTextEdit:disabled {{
    background: {p.card}; color: {p.text_faint}; border-color: {p.hairline};
}}
QLineEdit[readOnly="true"], QSpinBox[readOnly="true"], QDoubleSpinBox[readOnly="true"] {{
    background: {p.card}; color: {p.text_muted};
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox::down-arrow {{ image: url("{asset('chevron-down.svg')}"); width: 10px; height: 10px; }}
QComboBox::down-arrow:disabled {{ image: url("{asset('chevron-down-faint.svg')}"); }}
QComboBox QAbstractItemView {{
    background: {p.raised}; border: 1px solid {p.border}; padding: 2px; outline: none;
    selection-background-color: {p.accent_soft}; selection-color: {p.text};
}}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 0px; border: none; }}

QCheckBox, QRadioButton {{ spacing: 6px; background: transparent; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {p.text_faint}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px; height: 14px; border: 1px solid {p.border_strong}; background: {p.raised};
}}
QCheckBox::indicator {{ border-radius: 3px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {p.text_muted}; }}
QCheckBox::indicator:pressed, QRadioButton::indicator:pressed {{ background: {p.button_press}; }}
QCheckBox::indicator:focus, QRadioButton::indicator:focus {{
    border: 2px solid {p.accent_strong}; width: 12px; height: 12px;
}}
QCheckBox::indicator:checked {{
    background: {p.accent_strong}; border-color: {p.accent_strong}; image: url("{asset('check.svg')}");
}}
QCheckBox::indicator:checked:pressed {{ background: #86550C; }}
QRadioButton::indicator:checked {{ background: {p.raised}; border: 5px solid {p.accent_strong}; width: 6px; height: 6px; }}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    background: {p.card}; border-color: {p.hairline};
}}
QCheckBox::indicator:checked:disabled {{ background: {p.border}; border-color: {p.border}; }}

/* ---------- lists & tables ----------------------------------------- */
QListWidget, QTreeWidget, QTableWidget, QTableView {{
    background: {p.raised}; border: 1px solid {p.border}; border-radius: {RADIUS}px;
    outline: none; gridline-color: {p.hairline}; alternate-background-color: #F8F8F9;
}}
QListWidget:focus, QTableWidget:focus, QTableView:focus, QTreeWidget:focus {{ border-color: {p.accent_strong}; }}
QListWidget[role="flat"] {{ background: transparent; border: none; }}
QListWidget::item {{ padding: 3px 6px; border-radius: 3px; margin: 0px 2px; color: {p.text}; }}
QListWidget::item:hover {{ background: {p.hover}; }}
QListWidget::item:selected {{ background: {p.accent_soft}; color: {p.text}; }}
QListWidget::item:selected:!active {{ background: #EDE5D6; }}
QListWidget::item:disabled {{ color: {p.text_faint}; background: transparent; }}
QTableWidget::item, QTableView::item {{ padding: 0px 6px; }}
QTableWidget::item:selected, QTableView::item:selected {{ background: {p.accent_soft}; color: {p.text}; }}
QHeaderView {{ background: {p.card}; border: none; }}
QHeaderView::section {{
    background: {p.card}; color: {p.text_muted}; border: none;
    border-bottom: 1px solid {p.border}; border-right: 1px solid {p.hairline};
    padding: 3px 6px; font-size: {TEXT_SMALL}px; font-weight: {W_SEMIBOLD};
}}
QHeaderView::section:hover {{ background: {p.button_hover}; }}
QTableCornerButton::section {{ background: {p.card}; border: none; }}

/* ---------- tabs: folder tabs ----------------------------------------
   Unselected tabs are grey chips. The selected one takes the page's own
   colour and drops its lower edge, so it reads as the top of the page below.
   The chip colour is an overlay, so the same rules work on the window
   background (main tabs) and on a panel (tabs inside a page or a dialog). */
QTabWidget::pane {{
    background: {p.panel}; border: 1px solid {p.border};
    border-radius: {RADIUS_CARD}px; border-top-left-radius: 0px; top: -1px;
}}
QTabWidget QTabWidget::pane, QDialog QTabWidget::pane {{
    background: transparent; border: none; border-top: 1px solid {p.border}; border-radius: 0px;
}}
QTabWidget::tab-bar {{ left: 0px; }}
QTabBar {{ qproperty-drawBase: 0; background: transparent; }}
QTabBar::tab {{
    background: {p.tab_chip}; color: {p.text_muted};
    border: 1px solid {p.border}; border-bottom: none;
    border-top-left-radius: 5px; border-top-right-radius: 5px;
    padding: 4px 14px 5px 14px; margin: 3px 2px 0px 0px; min-height: 16px;
}}
QTabBar::tab:hover    {{ background: {p.tab_chip_hover}; color: {p.text}; }}
QTabBar::tab:pressed  {{ background: {p.tab_chip_press}; padding: 5px 14px 4px 14px; }}
QTabBar::tab:selected {{
    background: {p.panel}; color: {p.text}; font-weight: {W_SEMIBOLD};
    border: 1px solid {p.border}; border-bottom: 1px solid {p.panel};
    margin-top: 0px; padding-bottom: 7px;
}}
QTabBar::tab:focus    {{ border: 2px solid {p.accent_strong}; border-bottom: none; padding: 3px 13px 5px 13px; }}
QTabBar::tab:selected:focus {{ border-bottom: 1px solid {p.panel}; padding: 3px 13px 7px 13px; }}
QTabBar::tab:disabled {{ color: {p.text_faint}; }}

/* ---------- chrome -------------------------------------------------- */
QMenuBar {{ background: {p.panel}; border-bottom: 1px solid {p.border}; }}
QMenuBar::item {{ padding: 3px 8px; background: transparent; border-radius: 3px; }}
QMenuBar::item:selected {{ background: {p.hover}; }}
QMenuBar::item:pressed {{ background: {p.press}; }}
QMenu {{ background: {p.raised}; border: 1px solid {p.border}; border-radius: 5px; padding: 3px; }}
QMenu::item {{ padding: 4px 20px 4px 10px; border-radius: 3px; }}
QMenu::item:selected {{ background: {p.accent_soft}; color: {p.text}; }}
QMenu::item:disabled {{ color: {p.text_faint}; background: transparent; }}
QMenu::separator {{ height: 1px; background: {p.hairline}; margin: 3px 6px; }}

QStatusBar {{
    background: {p.panel}; border-top: 1px solid {p.border}; color: {p.text_muted};
    min-height: 22px;
}}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {p.text_muted}; font-size: {TEXT_SMALL}px; padding: 0px 4px; }}

QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 8px; }}
QSplitter::handle:vertical {{ height: 8px; }}
QSplitter::handle:hover {{ background: {p.hover}; }}

QProgressBar {{
    background: {p.hover}; border: none; border-radius: 3px;
    max-height: 6px; min-height: 6px;
}}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 3px; }}
QProgressBar[role="labelled"] {{
    max-height: 20px; min-height: 20px; border: 1px solid {p.border}; background: {p.raised};
    color: {p.text}; font-size: {TEXT_SMALL}px; text-align: center;
}}
QProgressBar[role="labelled"]::chunk {{ background: {p.accent_soft}; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget#qt_scrollarea_viewport {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0px; }}
QScrollBar::handle {{ background: rgba(27, 28, 30, 0.22); border-radius: 3px; margin: 2px; }}
QScrollBar::handle:vertical {{ min-height: 24px; }}
QScrollBar::handle:horizontal {{ min-width: 24px; }}
QScrollBar::handle:hover {{ background: rgba(27, 28, 30, 0.38); }}
QScrollBar::handle:pressed {{ background: rgba(27, 28, 30, 0.50); }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none; border: none; width: 0px; height: 0px;
}}

QGraphicsView {{ border: 1px solid {p.border}; background: {p.raised}; }}
"""


class _Interactions(QObject):
    """Two desktop behaviours a stylesheet cannot express.

    Focus rings only for the keyboard. Qt's :focus matches however focus
    arrived, so a clicked button would keep a ring until something else took
    focus. Clickable controls therefore take focus from Tab only; inputs you
    type into still take it from a click, as they must.

    A not-allowed cursor over disabled controls. Qt normally shows the nearest
    *enabled* ancestor's cursor over a disabled widget, ignoring the widget's
    own, so setting one on the widget has no effect. Disabled widgets still
    receive Enter and Leave, which is enough to swap an override cursor in and
    out while the mouse is over one.
    """

    _CLICKABLE = (QAbstractButton, QTabBar)
    _INTERACTIVE = (QAbstractButton, QTabBar, QComboBox, QAbstractSpinBox, QLineEdit)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._forbidden_over = None

    def eventFilter(self, obj, event):
        et = event.type()
        if et == QEvent.Polish and isinstance(obj, QWidget):
            if isinstance(obj, self._CLICKABLE) or (
                    isinstance(obj, QComboBox) and not obj.isEditable()):
                obj.setFocusPolicy(Qt.TabFocus)
        elif et == QEvent.Enter and isinstance(obj, QWidget):
            if isinstance(obj, self._INTERACTIVE) and not obj.isEnabled():
                self._set_forbidden(obj)
            else:
                self._clear_forbidden()
        elif obj is self._forbidden_over and et in (QEvent.Leave, QEvent.Hide, QEvent.EnabledChange):
            if et != QEvent.EnabledChange or obj.isEnabled():
                self._clear_forbidden()
        return False

    def _set_forbidden(self, widget):
        if self._forbidden_over is None:
            QApplication.setOverrideCursor(QCursor(Qt.ForbiddenCursor))
        self._forbidden_over = widget

    def _clear_forbidden(self):
        if self._forbidden_over is not None:
            self._forbidden_over = None
            QApplication.restoreOverrideCursor()


_applied = False
_interactions = None


def apply(app: QApplication) -> None:
    """Install fonts, palette, stylesheet and interaction behaviour. Once."""
    global _applied, _interactions
    if _applied:
        return
    _applied = True
    app.setStyle("Fusion")  # the same base on every OS; the stylesheet paints over it
    ui, _numeric = fonts()
    base = QFont(ui)
    base.setPixelSize(TEXT)
    app.setFont(base)
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(P.panel))
    pal.setColor(QPalette.Base, QColor(P.raised))
    pal.setColor(QPalette.AlternateBase, QColor("#F8F8F9"))
    pal.setColor(QPalette.Text, QColor(P.text))
    pal.setColor(QPalette.WindowText, QColor(P.text))
    pal.setColor(QPalette.Button, QColor(P.raised))
    pal.setColor(QPalette.ButtonText, QColor(P.text))
    pal.setColor(QPalette.Highlight, QColor(P.accent_soft))
    pal.setColor(QPalette.HighlightedText, QColor(P.text))
    pal.setColor(QPalette.PlaceholderText, QColor(P.text_faint))
    pal.setColor(QPalette.ToolTipBase, QColor(P.text))
    pal.setColor(QPalette.ToolTipText, QColor(P.raised))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet())
    _interactions = _Interactions(app)
    app.installEventFilter(_interactions)


def ui_font(size_px: int = TEXT, bold: bool = False) -> QFont:
    """The UI font at a pixel size — for the few places that set one directly."""
    f = QFont(fonts()[0])
    f.setPixelSize(size_px)
    if bold:
        f.setWeight(QFont.DemiBold)
    return f


def numeric_font(size_px: int = TEXT, bold: bool = False) -> QFont:
    """For numbers that change in place: tables, readouts, figures."""
    f = QFont(fonts()[1])
    f.setPixelSize(size_px)
    if bold:
        f.setWeight(QFont.DemiBold)
    return f


def set_role(widget: QWidget, role: str, **props) -> QWidget:
    """Tag a widget with a stylesheet role (and optional extra properties),
    then make Qt re-evaluate its style. Returns the widget for chaining."""
    widget.setProperty("role", role)
    for key, value in props.items():
        widget.setProperty(key, value)
    repolish(widget)
    return widget


def set_prop(widget: QWidget, **props) -> None:
    """Change a style-affecting property at run time (e.g. tone, live)."""
    for key, value in props.items():
        widget.setProperty(key, value)
    repolish(widget)


def repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def segmented(*buttons) -> QFrame:
    """Put checkable buttons side by side in one recessed track.

    The buttons keep their own signals; this only groups them visually. The
    checked one is drawn raised, like the selected tab.
    """
    track = set_role(QFrame(), "segmented")
    lay = QHBoxLayout(track)
    lay.setContentsMargins(1, 1, 1, 1)
    lay.setSpacing(1)
    for b in buttons:
        set_role(b, "segment")
        lay.addWidget(b)
    track.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    return track


def swatch(color: str, size: int = 8) -> QFrame:
    """A small colour dot tying a readout or a signal row to its trace."""
    dot = set_role(QFrame(), "swatch")
    dot.setFixedSize(size, size)
    dot.setStyleSheet(f"background: {color}; border-radius: {size // 2}px;")
    return dot


def configure_pyqtgraph() -> None:
    """Plot defaults that match the window and stay fast on long runs.

    Antialiasing stays on — it is what makes thin traces look clean — paired
    with clip-to-view and peak downsampling on every curve (see
    ``fast_curve``), which is where the real cost of an hours-long recording
    goes.
    """
    import pyqtgraph as pg

    pg.setConfigOptions(antialias=True, background=P.raised, foreground=P.text_muted)


def fast_curve(curve) -> None:
    """Make a PlotDataItem cheap to redraw however long the run gets.

    clipToView skips points outside the visible range; peak downsampling keeps
    the envelope (so a spike is never hidden) while drawing at most a few
    points per screen pixel. An 8-hour 1 Hz recording is ~29k points per
    series; without these, every new sample redraws all of them.
    """
    curve.setClipToView(True)
    curve.setDownsampling(auto=True, method="peak")


def pen(color: str, width: float = 1.6, dashed: bool = False):
    import pyqtgraph as pg
    p = pg.mkPen(color, width=width)
    if dashed:
        p.setStyle(Qt.DashLine)
    return p


def style_axis(axis) -> None:
    """Quiet axis line, muted Plex tick labels."""
    import pyqtgraph as pg

    axis.setPen(pg.mkPen(P.border))
    axis.setTextPen(pg.mkPen(P.text_muted))
    axis.setStyle(tickFont=numeric_font(TEXT_SMALL), tickTextOffset=4)
    axis.label.setFont(ui_font(TEXT_AXIS))


def style_plot(widget, title: str = None) -> None:
    """White plot area, quiet axes, muted labels — one look for every graph."""
    widget.setBackground(P.raised)
    item = widget.getPlotItem() if hasattr(widget, "getPlotItem") else widget
    for name in ("left", "bottom", "right", "top"):
        style_axis(item.getAxis(name))
    item.showGrid(x=True, y=True, alpha=0.15)
    if title:
        item.setTitle(title, color=P.text_muted, size=f"{TEXT_SMALL}px")


def legend(plot, **kwargs):
    """A plot legend in the program's text size."""
    return plot.addLegend(labelTextSize=f"{TEXT_SMALL}px", **kwargs)


def series_color(name: str) -> str:
    """Stable colour for a named quantity, shared by readouts and traces."""
    return {
        "Heat Flow": P.series[0], "Sample Temperature": P.series[1],
        "External Temperature": P.series[2], "Voltage": P.series[3],
        "Current": P.series[4], "Resistance": P.series[5], "Power": P.series[6],
    }.get(name, P.series[7])
