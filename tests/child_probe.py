"""Functions run inside a spawned child by test_analysis_runner (no Qt import here)."""
import os
import sys


def modules(_=None):
    import ctwa.analysis.runner  # noqa: F401
    return "PySide6" in sys.modules, "pyqtgraph" in sys.modules, "ctwa.app" in sys.modules


def pid(_=None):
    return os.getpid()
