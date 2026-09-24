"""Calorimetric Thermal Wave Analysis Program."""

import os

# pyqtgraph picks a Qt binding when first imported. PySide6 is the one this
# program is written for; say so, so an installed PyQt5 or PyQt6 is never used.
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")
