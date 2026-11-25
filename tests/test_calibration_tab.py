"""CalibrationTab (Plan 4, Task 10): assembly, messages, load states, end-to-end flows."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QTimer, Qt  # noqa: E402

from ctwa.analysis.calibration import device_lag_from_reference  # noqa: E402
from ctwa.analysis.calibration_logic import num  # noqa: E402
from ctwa.ui.calibration.calibration_tab import CalibrationTab  # noqa: E402
from ctwa.ui.calibration.texts import TEXT  # noqa: E402
from tests.calibration_fakes import FakeLoader, get_app, make_row, make_rows, wait_until  # noqa: E402


@pytest.fixture
def qapp():
    return get_app()


def loaded(rows=None, confirm=None):
    loader = FakeLoader(rows if rows is not None else make_rows())
    loader.graphs = {99: "G"}
    tab = CalibrationTab(loader, confirm=confirm or (lambda *a: True))
    loader.rows_changed.emit(loader.rows())
    return loader, tab


def test_loading_then_cards(qapp):
    loader = FakeLoader(make_rows())
    tab = CalibrationTab(loader)
    assert not tab.loading_label.isHidden() and tab.loading_label.text() == "Loading..."
    assert tab.scroll.isHidden()
    loader.rows_changed.emit(loader.rows())
    assert tab.loading_label.isHidden() and not tab.scroll.isHidden()
    titles = [c.title_label.text() for c in (tab.reference_card, tab.target, tab.batch)]
    assert titles == ["1. Reference runs", "2. Calibrate a run", "3. Batch calibration"]
    assert tab.reference_card.status_label.text() == "5 references"
    assert tab.table.parent() is not None and tab.state is not None


def test_on_shown_refreshes_once(qapp):
    loader = FakeLoader(make_rows())
    tab = CalibrationTab(loader)
    tab.on_shown()
    tab.on_shown()
    assert loader.refreshes == 1


def test_login_failure_message(qapp):
    loader, tab = loaded()
    loader.failed.emit("login", "x")
    assert tab.messages.text() == "Not logged in. Use Settings → Webapp login…" and tab.messages.kind == "error"
    loader.failed.emit("server", "boom")
    assert tab.messages.text() == "boom"


def test_failed_during_write_not_shown(qapp):
    loader, tab = loaded()
    loader.hang_at = {0}
    tab.state.mark_ids = [99]
    tab.mark.alpha.setText("5")
    tab.mark.mark_button.click()
    assert tab.queue.busy
    loader.failed.emit("login", "x")
    assert tab.messages.text() == ""


def test_end_to_end_save(qapp):
    loader, tab = loaded()
    s = tab.state
    s.selected_ref_ids = [10, 11, 12, 13, 14]
    s.target_id = 99
    tab.target.save_button.click()
    assert wait_until(lambda: loader.ops and not tab.queue.busy and not tab.target.saving)
    assert [o[0] for o in loader.ops] == ["insert"]
    assert tab.messages.text() == TEXT["saved"]
    new = dict(loader.ops[0][1], id=500)
    loader.rows_list = make_rows() + [new]
    loader.rows_changed.emit(loader.rows())
    assert "%s (#500)" % TEXT["alreadyCalibrated"] in tab.target.copy_warn.text()


def test_mark_flow(qapp):
    loader, tab = loaded()
    tab.mark.alpha.setText("4")
    for i in range(tab.mark.list.count()):
        it = tab.mark.list.item(i)
        if it.data(Qt.UserRole) in (99, 100):
            it.setCheckState(Qt.Checked)
    tab.mark.mark_button.click()
    assert wait_until(lambda: len(loader.ops) == 2 and not tab.queue.busy)
    assert loader.ops == [("update", i, {"is_reference": True, "reference_alpha_mm2s": 4.0}) for i in (99, 100)]
    rows = [dict(r, is_reference=True, reference_alpha_mm2s=4.0) if r["id"] in (99, 100) else r
            for r in make_rows()]
    loader.rows_changed.emit(rows)
    assert set(tab.table.alpha_edits) == {10, 11, 12, 13, 14, 99, 100}
    shown = [tab.mark.list.item(i).data(Qt.UserRole) for i in range(tab.mark.list.count())]
    assert 99 not in shown and 100 not in shown


def test_method_toggle(qapp):
    loader, tab = loaded()
    tab.combined_button.click()
    assert tab.state.method == "combined" and tab.combined_button.isChecked()
    row = next(r for r in make_rows() if r["id"] == 10)
    item = tab.table.table.item(0, 6)
    assert item.text() == "%s s" % num(device_lag_from_reference(row, 5.829, "combined"))
    tab.phase_button.click()
    assert tab.state.method == "phase"


def test_gui_not_blocked_during_batch(qapp):
    rows = [r for r in make_rows() if r.get("is_reference")]
    rows += [make_row(1000 + i, period=400, raw_lag_dt=150) for i in range(30)]
    loader, tab = loaded(rows, confirm=lambda *a: True)
    s = tab.state
    s.selected_ref_ids = [10, 11, 12, 13, 14]
    s.lag_source = "direct"
    s.batch_material = "Stainless Steel"
    import time
    ticks = []
    t = QTimer()
    t.timeout.connect(lambda: ticks.append(time.monotonic()))
    t.start(20)
    tab.batch.save_button.click()
    assert wait_until(lambda: len(loader.ops) == 30 and not tab.queue.busy, 20)
    t.stop()
    gaps = [b - a for a, b in zip(ticks, ticks[1:])]
    # at most 2 missed 20 ms ticks (a little slack for a loaded machine)
    assert len(ticks) >= 5 and max(gaps) < 0.1, (len(ticks), max(gaps))
