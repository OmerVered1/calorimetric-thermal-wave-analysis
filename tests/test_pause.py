"""Pause and resume a running experiment on a simulated instrument.

Chosen behaviour: while paused the output is off and no points are taken; the
calorimeter polls on its own so its trace keeps moving; Resume continues from
the next point on the same schedule, shifted by the time spent paused.
"""

import logging
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

STEP = 0.2   # seconds between points


@pytest.fixture(scope="module")
def app():
    logging.disable(logging.CRITICAL)
    for n in ("warning", "critical", "information"):
        setattr(QMessageBox, n, staticmethod(lambda *a, **k: None))
    return QApplication.instance() or QApplication([])


class FakeCalorimeter:
    """Records who is polling: the sweep (paused polling) or the reader itself."""

    def __init__(self):
        self.events = []

    def pause_polling(self):
        self.events.append("sweep polls")

    def resume_polling(self):
        self.events.append("reader polls")

    def poll_once(self):
        return {}

    def stop(self):
        pass

    def wait(self, *_):
        return True


@pytest.fixture
def window(app, tmp_path):
    from ctwa import app as appmod
    appmod.MainWindow._check_license_agreement = lambda self: True
    w = appmod.MainWindow()
    w.auto_save_enabled = False
    w.auto_save_path = str(tmp_path)   # a sweep always writes its live CSV
    w.connect_instrument("2602B", simulate=True, simulation_resistance=100.0)
    w.source_settings.mode.setCurrentText("Linear Sweep")
    w.sweep_list.start_val.setValue(0.0)
    w.sweep_list.stop_val.setValue(1.0)
    w.sweep_list.num_points.setValue(10)
    w.timing_settings.delay.setValue(0.0)
    w.timing_settings.step_size.setValue(STEP)
    w.timing_settings.auto_delay_check.setChecked(True)
    yield w
    w.stop_sweep()
    pump(app, 0.3)
    w.calorimeter_reader = None
    w.close()


def pump(app, seconds, until=None):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.01)
    return until() if until is not None else True


def test_pause_holds_output_off_takes_no_points_then_resumes_on_schedule(app, window):
    w = window
    cal = FakeCalorimeter()
    w.calorimeter_reader = cal
    w.start_sweep()
    assert pump(app, 5, until=lambda: len(w.measurement_data) >= 3)

    w.toggle_pause()
    assert pump(app, 1, until=lambda: w.pause_btn.text() == "Resume" and
                w._paused_since is not None), "the sweep thread never reported pausing"
    count = len(w.measurement_data)
    pump(app, 1.0)
    assert len(w.measurement_data) == count, "points were taken while paused"
    assert not w.smu.output_enabled("a"), "output stayed on while paused"
    assert cal.events[-1] == "reader polls", "the calorimeter was left unpolled while paused"

    w.toggle_pause()
    assert pump(app, 1, until=lambda: w.smu.output_enabled("a")), "output did not come back on"
    assert pump(app, 10, until=lambda: w.start_btn.isEnabled()), "the sweep did not finish after resuming"

    pts = w.measurement_data
    assert [p.index for p in pts] == list(range(1, 11)), "points were lost or repeated"
    gaps = [b.timestamp - a.timestamp for a, b in zip(pts, pts[1:])]
    pause_gap = max(gaps)
    assert pause_gap >= 0.9, "the pause should show as a gap in the timestamps"
    after = gaps[gaps.index(pause_gap) + 1:]
    assert after and all(g > STEP * 0.6 for g in after), \
        f"points after Resume rushed to catch up: {[round(g, 3) for g in after]}"
    assert cal.events[-1] == "reader polls"   # handed back when the sweep ended
    assert w.start_btn.isEnabled() and not w.pause_btn.isEnabled()


def test_stop_while_paused_ends_the_sweep(app, window):
    w = window
    w.start_sweep()
    assert pump(app, 5, until=lambda: len(w.measurement_data) >= 2)
    w.toggle_pause()
    assert pump(app, 1, until=lambda: w._paused_since is not None)
    w.stop_sweep()
    # "Finished" is the last thing the sweep thread signals; wait for the
    # window to have handled it, not merely for the thread to have ended.
    assert pump(app, 2, until=lambda: w.start_btn.isEnabled()), \
        "after Stop while paused the window stayed in its running state"
    assert not w.running
    assert not w.smu.output_enabled("a")
    assert w.pause_btn.text() == "Pause" and not w.pause_btn.isEnabled()
    assert w.progress_label.text().startswith("Stopped:")


def test_controls_show_on_experiments_and_real_time_only(app, window):
    w = window
    w.show()
    for i in range(w.main_tabs.count()):
        w.main_tabs.setCurrentIndex(i)
        app.processEvents()
        expected = w.main_tabs.tabText(i) in ("Experiments", "Real Time")
        assert w.start_btn.isVisible() == expected, w.main_tabs.tabText(i)
        assert w.pause_btn.isVisible() == expected


def test_a_sweep_that_fails_before_its_first_point_still_resets_the_window(app, window):
    w = window
    w.smu.set_nplc = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("instrument went away"))
    w.start_sweep()
    assert pump(app, 3, until=lambda: w.start_btn.isEnabled()), "the window stayed in its running state"
    assert "instrument went away" in w.status.currentMessage()
