"""Summary inline editing (Results tab, Task 8): offscreen, FakeLoader records what would be sent."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLineEdit  # noqa: E402

from results_fakes import FakeLoader  # noqa: E402
from ctwa.ui.results.summary_edit import ANALYSIS_MODES  # noqa: E402
from ctwa.ui.results.summary_tab import SummaryTab  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def row(i, **kw):
    r = {"id": i, "model_name": "Steel", "test_date": "%02d/11/2026" % i, "temperature_c": 766,
         "analysis_mode": "Auto", "period_t": 600.0, "use_calibration": True, "amplitude_a1": 12.5,
         "alpha_combined_raw": 8.5123e-6, "alpha_phase_raw": 8.4e-6, "ln_term": 0.5, "raw_phase_phi": 0.2,
         "calibration_model": "sqrt:1,2", "calibration_ref_ids": "12,15", "period_t_resp": None}
    r.update(kw)
    return r


ROWS = [row(1), row(2), row(3)]


@pytest.fixture
def env(qapp, tmp_path):
    made = []

    def _make(rows=ROWS):
        loader = FakeLoader(rows)
        tab = SummaryTab(loader, QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat))
        tab.resize(1100, 600)
        tab.show()
        tab.apply_preset("all")
        QApplication.processEvents()
        msgs = []
        tab.message.connect(msgs.append)
        logins = []
        tab.login_needed.connect(lambda: logins.append(1))
        made.append(tab)
        return tab, loader, msgs, logins
    yield _make
    for t in made:
        t.close()


def dclick(tab, rid, key):
    """press, release, double-click, release: what a user's double-click sends."""
    view, rect = tab.cell_rect(rid, key)
    vp, p = view.viewport(), QPointF(rect.center())
    for typ in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick,
                QEvent.MouseButtonRelease):
        down = Qt.NoButton if typ == QEvent.MouseButtonRelease else Qt.LeftButton
        QApplication.sendEvent(vp, QMouseEvent(typ, p, vp.mapToGlobal(p), Qt.LeftButton, down, Qt.NoModifier))
    QApplication.processEvents()


def type_into(w, text):
    w.setText(text)


def enter(w):
    QTest.keyClick(w, Qt.Key_Return)


def test_double_click_edits_only_the_change(env):
    tab, loader, msgs, _ = env()
    dclick(tab, 2, "temperature_c")
    assert tab.editing_id() == 2
    w = tab.editor_widget("temperature_c")
    assert isinstance(w, QLineEdit) and w.text() == "766"
    type_into(w, "770")
    enter(w)
    assert loader.updates() == [("update", 2, {"temperature_c": 770.0})]


def test_alpha_editor_shows_stored_raw_value(env):
    tab, *_ = env()
    dclick(tab, 2, "alpha_phase_raw")
    assert tab.editor_widget("alpha_combined_raw").text() == "0.0000085123"   # String(8.5123e-6), as the webapp
    assert tab.editor_widget("alpha_phase_raw").text() == "0.0000084"


@pytest.mark.parametrize("key", ["id", "calibration_model", "calibration_ref_ids"])
def test_read_only_cells_never_open(env, key):
    tab, *_ = env()
    dclick(tab, 2, key)
    assert tab.editing_id() is None


def test_calibration_checkbox_and_mode_combo(env):
    tab, loader, *_ = env([row(1, analysis_mode="AutoHybrid2")])
    dclick(tab, 1, "use_calibration")
    cb = tab.editor_widget("use_calibration")
    assert isinstance(cb, QCheckBox) and cb.isChecked()
    mode = tab.editor_widget("analysis_mode")
    assert isinstance(mode, QComboBox) and mode.isEditable()
    assert [mode.itemText(i) for i in range(mode.count())] == ANALYSIS_MODES + ["AutoHybrid2"]
    cb.setChecked(False)
    mode.setCurrentIndex(mode.findText("Manual"))
    assert tab.commit_edit() == {"use_calibration": False, "analysis_mode": "Manual"}


def test_mode_list_without_extra_value(env):
    tab, *_ = env()
    tab.begin_edit(1)
    mode = tab.editor_widget("analysis_mode")
    assert [mode.itemText(i) for i in range(mode.count())] == ANALYSIS_MODES


def test_empty_and_garbage_numbers_become_null(env):
    tab, loader, *_ = env([row(1, period_t_resp=600.45)])
    tab.begin_edit(1)
    tab.editor_widget("amplitude_a1").setText("")
    tab.editor_widget("period_t").setText("abc")
    tab.editor_widget("period_t_resp").setText("601.5 s")
    assert tab.commit_edit() == {"amplitude_a1": None, "period_t": None, "period_t_resp": 601.5}


def test_ln_corrected_row_saves_only_the_edited_field(env):
    bad = row(1, ln_term=1, amplitude_a1=1.0, amplitude_a2=2.0, r1_mm=5.0, r2_mm=10.0, alpha_combined_raw=3e-6)
    tab, loader, *_ = env([bad])
    assert tab.model.display_row(1)["alpha_combined_raw"] is None     # displayed corrected
    tab.begin_edit(1)
    assert tab.editor_widget("alpha_combined_raw").text() == "0.000003"   # the stored value
    tab.editor_widget("temperature_c").setText("767")
    assert tab.commit_edit() == {"temperature_c": 767.0}


def test_escape_and_unchanged_enter_send_nothing(env):
    tab, loader, *_ = env()
    tab.begin_edit(2)
    tab.editor_widget("temperature_c").setText("999")
    QTest.keyClick(tab.editor_widget("temperature_c"), Qt.Key_Escape)
    assert tab.editing_id() is None and loader.updates() == []
    tab.begin_edit(2)
    enter(tab.editor_widget("temperature_c"))
    assert tab.editing_id() is None and loader.updates() == []


def test_edit_button_and_save_cancel_buttons(env):
    tab, loader, *_ = env()
    view, rect = tab.edit_button_rect(2)
    QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
    QApplication.processEvents()
    assert tab.editing_id() == 2
    b = tab._delegate.buttons
    assert (b.save.text(), b.cancel.text()) == ("Save", "Cancel")
    tab.editor_widget("temperature_c").setText("700")
    b.save.click()
    assert loader.updates() == [("update", 2, {"temperature_c": 700.0})]
    assert not tab.editor_widget("temperature_c").isEnabled() and not b.save.isEnabled()
    loader.write_failed.emit("update", 1, "offline", "no route")
    b.cancel.click()
    assert tab.editing_id() is None


def test_discard_prompt_only_with_changes(env, monkeypatch):
    tab, loader, *_ = env()
    asked = []
    monkeypatch.setattr(tab, "_confirm_discard", lambda i: asked.append(i) or False)
    tab.begin_edit(2)
    tab.begin_edit(3)
    assert asked == [] and tab.editing_id() == 3
    tab.editor_widget("temperature_c").setText("1")
    tab.begin_edit(1)
    assert asked == [3] and tab.editing_id() == 3
    monkeypatch.setattr(tab, "_confirm_discard", lambda i: True)
    tab.begin_edit(1)
    assert tab.editing_id() == 1 and loader.updates() == []


def test_refresh_during_edit_keeps_the_editor(env):
    tab, loader, msgs, _ = env()
    tab.begin_edit(2, "temperature_c")
    tab.editor_widget("temperature_c").setText("771")
    loader.set_rows([r for r in ROWS if r["id"] != 3])      # a row above is deleted: the table is rebuilt
    QApplication.processEvents()
    assert tab.editing_id() == 2
    w = tab.editor_widget("temperature_c")
    assert w is not None and w.text() == "771" and w.isVisible()
    assert tab.commit_edit() == {"temperature_c": 771.0}
    assert loader.updates() == [("update", 2, {"temperature_c": 771.0})]


def test_refresh_without_layout_change_keeps_focus_and_text(env):
    tab, loader, *_ = env()
    tab.begin_edit(2, "temperature_c")
    w = tab.editor_widget("temperature_c")
    w.setText("771")
    loader.set_rows([dict(r) for r in ROWS])
    assert tab.editor_widget("temperature_c") is w and w.text() == "771"


def test_row_removed_elsewhere_closes_the_editor(env):
    tab, loader, msgs, _ = env()
    tab.begin_edit(2)
    loader.set_rows([r for r in ROWS if r["id"] != 2])
    assert tab.editing_id() is None and msgs == ["#2 was removed elsewhere"]


def test_save_success_closes_with_message(env):
    tab, loader, msgs, _ = env()
    tab.begin_edit(2)
    tab.editor_widget("temperature_c").setText("771")
    tab.commit_edit()
    loader.set_rows([row(1), row(2, temperature_c=771.0), row(3)])
    assert tab.editing_id() is None and msgs == ["Saved #2"]


def test_an_unrelated_refresh_does_not_close_a_pending_save(env):
    tab, loader, msgs, _ = env()
    tab.begin_edit(2)
    tab.editor_widget("temperature_c").setText("771")
    tab.commit_edit()
    loader.set_rows([dict(r) for r in ROWS])     # a refresh that does not contain the change yet
    assert tab.editing_id() == 2 and msgs == []
    loader.write_done.emit("update", 1, None)
    assert tab.editing_id() is None and msgs == ["Saved #2"]


def test_failed_save_keeps_the_editor_and_the_text(env):
    tab, loader, msgs, logins = env()
    tab.begin_edit(2)
    tab.editor_widget("temperature_c").setText("771")
    tab.commit_edit()
    loader.write_failed.emit("update", 1, "offline", "no route")
    assert tab.editing_id() == 2 and msgs == ["Could not save #2: no route"] and logins == []
    w = tab.editor_widget("temperature_c")
    assert w.text() == "771" and w.isEnabled()
    assert tab.commit_edit() == {"temperature_c": 771.0}     # a retry sends the same change
    loader.write_failed.emit("update", 2, "login", "Not logged in")
    loader.failed.emit("login", "Not logged in")             # the real loader emits both
    assert logins == [1] and tab.editing_id() == 2
    assert msgs[-1] == "Could not save #2: Not logged in"


def test_two_quick_enters_send_one_update(env):
    tab, loader, *_ = env()
    tab.begin_edit(2)
    w = tab.editor_widget("temperature_c")
    w.setText("771")
    enter(w)
    enter(w)
    assert len(loader.updates()) == 1


def test_refresh_that_changed_another_field_is_not_reverted(env):
    tab, loader, *_ = env()
    tab.begin_edit(2)
    tab.editor_widget("temperature_c").setText("771")
    loader.set_rows([row(1), row(2, period_t=650.0), row(3)])      # someone else changed period_t
    assert tab.commit_edit() == {"temperature_c": 771.0}
    assert loader.updates() == [("update", 2, {"temperature_c": 771.0})]


def test_read_error_during_save_does_not_end_it(env):
    tab, loader, msgs, _ = env()
    tab.begin_edit(2)
    tab.editor_widget("temperature_c").setText("771")
    tab.commit_edit()
    loader.failed.emit("server", "refresh failed")
    assert tab.editing_id() == 2 and msgs == []
    assert not tab._delegate.buttons.save.isEnabled()
    assert tab.commit_edit() == {} and len(loader.updates()) == 1
    loader.write_done.emit("update", 1, None)
    assert tab.editing_id() is None and msgs == ["Saved #2"] and len(loader.updates()) == 1


def test_login_write_failure_reports_once(env):
    tab, loader, msgs, logins = env()
    tab.begin_edit(2)
    tab.editor_widget("temperature_c").setText("771")
    tab.commit_edit()
    loader.write_failed.emit("update", 1, "login", "Not logged in")
    loader.failed.emit("login", "Not logged in")
    assert msgs == ["Could not save #2: Not logged in"] and logins == [1]
