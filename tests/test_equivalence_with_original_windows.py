"""The merged window must send exactly what each original window sent.

tests/golden/original_windows.json holds the command streams recorded from the
four per-model programs of keithley-smu-control v3.6.0 (see
equivalence_scenarios.py). Every measurement taken so far was made through those
programs, so matching them command for command is the guarantee that a new run
is taken the same way as an old one.
"""

import json
import logging
import os
import pathlib
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

import equivalence_scenarios as S  # noqa: E402

GOLDEN = json.loads((pathlib.Path(__file__).parent / "golden" / "original_windows.json").read_text())
CASES = [(m, s) for m in ("2450", "6430", "2602B", "2611A") for s in S.SCENARIOS]


@pytest.fixture(scope="module")
def app():
    logging.disable(logging.CRITICAL)
    for n in ("warning", "critical", "information"):
        setattr(QMessageBox, n, staticmethod(lambda *a, **k: None))
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("model,scenario", CASES)
def test_merged_window_sends_what_the_original_sent(app, model, scenario):
    from ctwa import app as merged
    merged.MainWindow._check_license_agreement = lambda self: True
    w = merged.MainWindow()
    w.auto_save_enabled = False
    w.connect_instrument(model, simulate=True, simulation_resistance=1000.0)
    try:
        got = S.run(app, w, w.smu.driver, model, scenario)
    finally:
        w.close()
        app.processEvents()
    assert got == GOLDEN[model][scenario]
