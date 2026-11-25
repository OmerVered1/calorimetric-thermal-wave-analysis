"""A destroyed Calibration widget / WriteQueue must never receive a late timer, deferred delete or signal
(regression: PresetsSection chips scheduled with deleteLater, section freed by the cyclic GC before the
event loop ran -> segfault in a LATER test's processEvents)."""
from __future__ import annotations

import gc
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from ctwa.ui.calibration.calibration_tab import CalibrationTab  # noqa: E402
from ctwa.ui.calibration.presets_section import PresetsSection  # noqa: E402
from ctwa.ui.calibration.state import CalibrationState  # noqa: E402
from ctwa.ui.calibration.writes import WriteQueue  # noqa: E402
from tests.calibration_fakes import FakeLoader, get_app, make_rows  # noqa: E402

SS = {"id": 1, "material_name": "Stainless Steel", "temperature_c": 800, "alpha_mm2s": 5.829, "note": None}


@pytest.fixture
def qapp():
    return get_app()


def test_presets_section_destroyed_after_chip_rebuild(qapp):
    def build():
        loader = FakeLoader()
        state = CalibrationState()
        state.set_rows(make_rows())
        state.set_presets([SS])
        sec = PresetsSection(state, WriteQueue(loader), lambda t, k: None)
        state.set_presets([])          # chips removed -> old widgets scheduled for deletion
        return sec
    build()
    gc.collect()
    QTest.qWait(50)


def test_tab_lifecycle_then_events_past_timer_delays(qapp):
    loader = FakeLoader(make_rows(), [SS])
    tab = CalibrationTab(loader, confirm=lambda *a: True)
    tab.show()
    loader.rows_changed.emit(loader.rows())
    loader.presets_changed.emit([SS])
    tab.on_shown()
    QTest.qWait(30)
    loader.presets_changed.emit([])
    tab.close()
    tab.deleteLater()
    del tab, loader
    gc.collect()
    QTest.qWait(200)
