"""The look of the program, in one place.

Before this file the four instrument windows carried 187 inline setStyleSheet
calls between them, each hardcoding its own colours. Inline styles also beat a
global stylesheet in Qt, so nothing could be restyled centrally. Now the palette
lives here, one application stylesheet is built from it, and widgets say what
they *are* — a primary button, a muted label, a card — through a dynamic
``role`` property, never what colour they happen to be.

Design language: calm and warm, after the Claude desktop app. A warm off-white
canvas instead of stark white, near-black warm text, hairline borders, generous
spacing, rounded corners, a serif reserved for titles, and exactly one accent —
clay — spent only on the thing you are most likely to press next. Status
colours are desaturated so a green "connected" reads as information, not alarm.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

from PyQt5.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt5.QtWidgets import QApplication, QWidget


@dataclass(frozen=True)
class Palette:
    # Surfaces, back to front
    canvas: str = "#F9F8F4"        # window background — warm, not white
    sunken: str = "#F1EFE8"        # sidebars, headers, tab track
    card: str = "#FFFFFF"          # raised content
    # Lines
    hairline: str = "#E6E3DA"
    border: str = "#D9D5C9"        # inputs at rest
    # Text
    text: str = "#1F1E1B"
    text_muted: str = "#6F6D66"
    text_faint: str = "#A09E96"
    # The one accent
    accent: str = "#C96442"
    accent_hover: str = "#B5563A"
    accent_pressed: str = "#9E4A31"
    accent_soft: str = "#F6E6DE"   # focus rings, selected rows
    # Status, desaturated
    ok: str = "#3F7A4F"
    ok_soft: str = "#E4EFE6"
    warn: str = "#A8741A"
    warn_soft: str = "#F7EDD8"
    danger: str = "#B3412F"
    danger_soft: str = "#F6E1DC"
    # Plots: distinct, calm, readable on the canvas. Order is the series order.
    series: tuple = (
        "#C96442",  # clay      — heat flow
        "#3B6EA8",  # slate blue — sample T
        "#B8862B",  # ochre     — external T
        "#3F7A4F",  # moss      — voltage
        "#8A5A9E",  # plum      — current
        "#2F8C8C",  # teal      — resistance
        "#6F6D66",  # graphite  — power
        "#A64D79",  # berry
    )


P = Palette()

RADIUS = 8
RADIUS_LG = 12


def asset(name: str) -> str:
    """Path to a bundled icon, in the forward-slash form Qt stylesheets need.

    Works from source and from a PyInstaller build, where data files live
    under sys._MEIPASS rather than next to this module.
    """
    from pathlib import Path

    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) / "ctwa" / "assets" if base else Path(__file__).resolve().parent / "assets"
    return (root / name).as_posix()


def _pick(candidates, fallback):
    families = set(QFontDatabase().families())
    for name in candidates:
        if name in families:
            return name
    return fallback


def fonts():
    """Resolved font families for this machine: (ui, serif, mono)."""
    if sys.platform == "darwin":
        ui = _pick([".AppleSystemUIFont", "SF Pro Text", "Helvetica Neue"], "Helvetica Neue")
        mono = _pick(["SF Mono", "Menlo"], "Menlo")
    elif sys.platform == "win32":
        ui = _pick(["Segoe UI Variable Text", "Segoe UI"], "Segoe UI")
        mono = _pick(["Cascadia Mono", "Consolas"], "Consolas")
    else:
        ui = _pick(["Inter", "Cantarell", "DejaVu Sans"], "Sans Serif")
        mono = _pick(["JetBrains Mono", "DejaVu Sans Mono"], "Monospace")
    serif = _pick(["Iowan Old Style", "Charter", "Georgia", "Cambria", "Times New Roman"], "Georgia")
    return ui, serif, mono


def stylesheet(scale: float = 1.0) -> str:
    """The application stylesheet. ``scale`` shrinks every font size, for the
    window's responsive mode on small screens; 1.0 is full size."""
    return _scaled(_stylesheet(), scale)


def _scaled(css: str, scale: float) -> str:
    if abs(scale - 1.0) < 1e-3:
        return css
    return re.sub(r"font-size:\s*(\d+)px",
                  lambda m: f"font-size: {max(9, round(int(m.group(1)) * scale))}px", css)


def _stylesheet() -> str:
    ui, serif, mono = fonts()
    p = P
    return f"""
/* ---------- base ---------------------------------------------------- */
QWidget {{
    font-family: "{ui}";
    font-size: 13px;
    color: {p.text};
}}
QMainWindow, QDialog {{ background: {p.canvas}; }}
QToolTip {{
    background: {p.text}; color: {p.canvas}; border: none;
    padding: 6px 8px; border-radius: 6px;
}}

/* ---------- text roles ---------------------------------------------- */
QLabel[role="title"]    {{ font-family: "{serif}"; font-size: 22px; color: {p.text}; }}
QLabel[role="heading"]  {{ font-family: "{serif}"; font-size: 17px; color: {p.text}; }}
QLabel[role="section"]  {{ font-size: 12px; font-weight: 600; color: {p.text_muted}; }}
QLabel[role="muted"]    {{ color: {p.text_muted}; }}
QLabel[role="faint"]    {{ color: {p.text_faint}; font-size: 12px; }}
QLabel[role="mono"]     {{ font-family: "{mono}"; }}
QLabel[role="ok"]       {{ color: {p.ok}; }}
QLabel[role="warn"]     {{ color: {p.warn}; }}
QLabel[role="danger"]   {{ color: {p.danger}; }}

/* pill used for status: connected, simulated, disconnected */
QLabel[role="pill"] {{
    padding: 3px 10px; border-radius: 10px; font-size: 12px; font-weight: 600;
    background: {p.sunken}; color: {p.text_muted};
}}
QLabel[role="pill"][tone="ok"]     {{ background: {p.ok_soft};     color: {p.ok}; }}
QLabel[role="pill"][tone="warn"]   {{ background: {p.warn_soft};   color: {p.warn}; }}
QLabel[role="pill"][tone="danger"] {{ background: {p.danger_soft}; color: {p.danger}; }}
QLabel[role="pill"][tone="accent"] {{ background: {p.accent_soft}; color: {p.accent}; }}

/* big numeric readouts */
QLabel[role="readout"] {{
    font-family: "{mono}"; font-size: 30px; color: {p.text};
}}
QLabel[role="readout-unit"] {{ color: {p.text_muted}; font-size: 13px; }}

/* ---------- surfaces ------------------------------------------------ */
QFrame[role="card"] {{
    background: {p.card}; border: 1px solid {p.hairline}; border-radius: {RADIUS_LG}px;
}}
QFrame[role="header"] {{
    background: {p.canvas}; border: none; border-bottom: 1px solid {p.hairline};
}}
QFrame[role="divider"] {{ background: {p.hairline}; max-height: 1px; min-height: 1px; border: none; }}

QGroupBox {{
    background: {p.card}; border: 1px solid {p.hairline}; border-radius: {RADIUS_LG}px;
    margin-top: 14px; padding: 14px 12px 10px 12px;
    font-weight: 600; color: {p.text_muted};
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 12px; padding: 0 4px; font-size: 12px; color: {p.text_muted};
}}

/* ---------- buttons ------------------------------------------------- */
QPushButton, QToolButton {{
    background: {p.card}; color: {p.text};
    border: 1px solid {p.border}; border-radius: {RADIUS}px;
    padding: 6px 14px; min-height: 18px;
}}
QPushButton:hover, QToolButton:hover {{ background: {p.sunken}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {p.hairline}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {p.text_faint}; border-color: {p.hairline}; background: {p.canvas}; }}
QPushButton:checked {{ background: {p.text}; color: {p.canvas}; border-color: {p.text}; }}

QPushButton[role="primary"] {{
    background: {p.accent}; color: white; border: 1px solid {p.accent}; font-weight: 600;
}}
QPushButton[role="primary"]:hover   {{ background: {p.accent_hover}; border-color: {p.accent_hover}; }}
QPushButton[role="primary"]:pressed {{ background: {p.accent_pressed}; }}
QPushButton[role="primary"]:disabled {{ background: {p.accent_soft}; border-color: {p.accent_soft}; color: white; }}

QPushButton[role="quiet"] {{ background: transparent; border: 1px solid transparent; color: {p.text_muted}; }}
QPushButton[role="quiet"]:hover {{ background: {p.sunken}; color: {p.text}; }}

QPushButton[role="danger"] {{ color: {p.danger}; border-color: {p.danger_soft}; }}
QPushButton[role="danger"]:hover {{ background: {p.danger_soft}; }}

/* output switch: reads as a state, not an action */
QPushButton[role="output"] {{ font-weight: 600; min-width: 92px; }}
QPushButton[role="output"][live="true"] {{
    background: {p.ok}; color: white; border-color: {p.ok};
}}

/* segmented control (channel A/B, front/rear, 2/4-wire) */
QPushButton[role="segment"] {{ border-radius: 0; padding: 5px 14px; }}
QPushButton[role="segment"][edge="left"]  {{ border-top-left-radius: {RADIUS}px; border-bottom-left-radius: {RADIUS}px; }}
QPushButton[role="segment"][edge="right"] {{ border-top-right-radius: {RADIUS}px; border-bottom-right-radius: {RADIUS}px; border-left: none; }}
QPushButton[role="segment"][edge="mid"]   {{ border-left: none; }}
QPushButton[role="segment"]:checked {{ background: {p.text}; color: {p.canvas}; border-color: {p.text}; }}

QPushButton[role="segment"][edge="solo"] {{ border-radius: {RADIUS}px; }}

/* instrument picker cards */
QFrame[role="model-card"] {{
    background: {p.card}; border: 1px solid {p.hairline}; border-radius: {RADIUS_LG}px;
}}
QFrame[role="model-card"]:hover {{ border: 1px solid {p.border}; }}
QFrame[role="model-card"][selected="true"] {{ border: 2px solid {p.accent}; background: {p.card}; }}
QLabel[role="card-title"] {{ font-size: 14px; font-weight: 600; color: {p.text}; background: transparent; }}
QLabel[role="faint"] {{ background: transparent; }}

/* ---------- inputs -------------------------------------------------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit, QPlainTextEdit, QTextEdit {{
    background: {p.card}; border: 1px solid {p.border}; border-radius: {RADIUS}px;
    padding: 5px 8px; selection-background-color: {p.accent_soft}; selection-color: {p.text};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {{ border: 1px solid {p.accent}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background: {p.canvas}; color: {p.text_faint}; border-color: {p.hairline};
}}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url("{asset('chevron-down.svg')}"); width: 12px; height: 12px; }}
QComboBox::down-arrow:disabled {{ image: url("{asset('chevron-down-faint.svg')}"); }}
QComboBox QAbstractItemView {{
    background: {p.card}; border: 1px solid {p.hairline}; border-radius: {RADIUS}px;
    padding: 4px; outline: none; selection-background-color: {p.accent_soft}; selection-color: {p.text};
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 16px; border: none; }}

QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px; border: 1px solid {p.border}; background: {p.card};
}}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked {{
    background: {p.accent}; border-color: {p.accent}; image: url("{asset('check.svg')}");
}}
QCheckBox::indicator:hover {{ border-color: {p.text_faint}; }}
QCheckBox::indicator:disabled {{ background: {p.canvas}; border-color: {p.hairline}; }}
QRadioButton::indicator:checked {{ background: {p.card}; border: 5px solid {p.accent}; }}

/* ---------- lists & tables ----------------------------------------- */
QListWidget, QTreeWidget, QTableWidget, QTableView {{
    background: {p.card}; border: 1px solid {p.hairline}; border-radius: {RADIUS_LG}px;
    outline: none; gridline-color: {p.hairline};
    alternate-background-color: {p.canvas};
}}
QListWidget::item {{ padding: 8px 10px; border-radius: 6px; margin: 1px 4px; }}
QListWidget::item:hover {{ background: {p.sunken}; }}
QListWidget::item:selected {{ background: {p.accent_soft}; color: {p.text}; }}
QTableWidget::item:selected, QTableView::item:selected {{ background: {p.accent_soft}; color: {p.text}; }}
QHeaderView::section {{
    background: {p.canvas}; color: {p.text_muted}; border: none;
    border-bottom: 1px solid {p.hairline}; padding: 6px 8px; font-size: 12px; font-weight: 600;
}}
QTableCornerButton::section {{ background: {p.canvas}; border: none; }}

/* ---------- tabs: a quiet segmented track ---------------------------- */
QTabWidget::pane {{ border: none; top: -1px; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{
    background: transparent; color: {p.text_muted};
    padding: 7px 16px; margin: 4px 2px; border-radius: {RADIUS}px; border: none;
}}
QTabBar::tab:hover {{ color: {p.text}; background: {p.sunken}; }}
QTabBar::tab:selected {{ color: {p.text}; background: {p.card}; border: 1px solid {p.hairline}; }}

/* ---------- chrome -------------------------------------------------- */
QMenuBar {{ background: {p.canvas}; border-bottom: 1px solid {p.hairline}; }}
QMenuBar::item {{ padding: 5px 10px; background: transparent; border-radius: 6px; }}
QMenuBar::item:selected {{ background: {p.sunken}; }}
QMenu {{ background: {p.card}; border: 1px solid {p.hairline}; border-radius: {RADIUS}px; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p.accent_soft}; color: {p.text}; }}
QMenu::separator {{ height: 1px; background: {p.hairline}; margin: 4px 8px; }}

QStatusBar {{ background: {p.canvas}; border-top: 1px solid {p.hairline}; color: {p.text_muted}; }}
QStatusBar::item {{ border: none; }}

QSplitter::handle {{ background: {p.canvas}; }}
QSplitter::handle:horizontal {{ width: 6px; }}
QSplitter::handle:vertical {{ height: 6px; }}

QProgressBar {{
    background: {p.sunken}; border: none; border-radius: 4px; height: 8px;
    text-align: center; color: {p.text_muted}; font-size: 11px;
}}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 4px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {p.border}; border-radius: 4px; min-height: 28px; min-width: 28px; }}
QScrollBar::handle:hover {{ background: {p.text_faint}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none; border: none; width: 0; height: 0;
}}
QScrollArea {{ border: none; background: transparent; }}
"""


_current_scale = None


def apply(app: QApplication, scale: float = 1.0) -> None:
    """Install the palette and stylesheet on the application.

    Cheap to call repeatedly: re-styling the whole application is the expensive
    part (Qt re-polishes every widget), so it only happens when ``scale``
    actually changes.
    """
    global _current_scale
    if _current_scale is not None and abs(scale - _current_scale) < 1e-3:
        return
    _current_scale = scale
    app.setStyle("Fusion")  # consistent base on every OS; QSS paints over it
    ui, _serif, _mono = fonts()
    app.setFont(QFont(ui, max(8, round(10 * scale))))
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(P.canvas))
    pal.setColor(QPalette.Base, QColor(P.card))
    pal.setColor(QPalette.AlternateBase, QColor(P.canvas))
    pal.setColor(QPalette.Text, QColor(P.text))
    pal.setColor(QPalette.WindowText, QColor(P.text))
    pal.setColor(QPalette.Button, QColor(P.card))
    pal.setColor(QPalette.ButtonText, QColor(P.text))
    pal.setColor(QPalette.Highlight, QColor(P.accent_soft))
    pal.setColor(QPalette.HighlightedText, QColor(P.text))
    pal.setColor(QPalette.PlaceholderText, QColor(P.text_faint))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet(scale))


def ui_font(size_pt: float = 10, bold: bool = False) -> QFont:
    """The UI font at a given size — for the few places that set one directly."""
    f = QFont(fonts()[0], round(size_pt))
    f.setBold(bold)
    return f


def mono_font(size_pt: float = 10, bold: bool = False) -> QFont:
    f = QFont(fonts()[2], round(size_pt))
    f.setBold(bold)
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


def configure_pyqtgraph() -> None:
    """Plot defaults that match the window and stay fast on long runs.

    Antialiasing was on globally before. It is kept — it is what makes thin
    traces look clean — but paired with clip-to-view and peak downsampling on
    every curve (see ``fast_curve``), which is where the real cost of an
    hours-long recording goes.
    """
    import pyqtgraph as pg

    pg.setConfigOptions(antialias=True, background=P.canvas, foreground=P.text_muted)


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
    from PyQt5.QtCore import Qt
    p = pg.mkPen(color, width=width)
    if dashed:
        p.setStyle(Qt.DashLine)
    return p


def style_plot(widget, title: str = None) -> None:
    """Card-coloured plot area, quiet axes, muted labels — one look for every graph."""
    import pyqtgraph as pg

    widget.setBackground(P.card)
    item = widget.getPlotItem() if hasattr(widget, "getPlotItem") else widget
    for name in ("left", "bottom", "right", "top"):
        axis = item.getAxis(name)
        axis.setPen(pg.mkPen(P.hairline))
        axis.setTextPen(pg.mkPen(P.text_muted))
    item.showGrid(x=True, y=True, alpha=0.18)
    if title:
        item.setTitle(title, color=P.text_muted, size="11pt")


def series_color(name: str) -> str:
    """Stable colour for a named quantity, shared by readouts and traces."""
    return {
        "Heat Flow": P.series[0], "Sample Temperature": P.series[1],
        "External Temperature": P.series[2], "Voltage": P.series[3],
        "Current": P.series[4], "Resistance": P.series[5], "Power": P.series[6],
    }.get(name, P.series[7])
