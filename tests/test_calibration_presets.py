"""PresetsSection (Plan 4, Task 5): chips, add form, validation, delete, busy."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from ctwa.ui.calibration.presets_section import PresetsSection  # noqa: E402
from ctwa.ui.calibration.state import CalibrationState  # noqa: E402
from ctwa.ui.calibration.texts import TEXT  # noqa: E402
from ctwa.ui.calibration.writes import WriteQueue  # noqa: E402
from tests.calibration_fakes import FakeLoader, get_app, make_rows, wait_until  # noqa: E402

SS = {"id": 1, "material_name": "Stainless Steel", "temperature_c": 800, "alpha_mm2s": 5.829, "note": None}


@pytest.fixture
def qapp():
    return get_app()


@pytest.fixture
def env(qapp):
    loader = FakeLoader()
    state = CalibrationState()
    state.set_rows(make_rows())
    state.set_presets([SS])
    queue = WriteQueue(loader)
    msgs = []
    sec = PresetsSection(state, queue, lambda t, k: msgs.append((t, k)))
    return loader, state, queue, sec, msgs


def fill(sec, material="Al₂O₃", temp="150", alpha="8", note=""):
    sec.material.setText(material)
    sec.temp.setText(temp)
    sec.alpha.setText(alpha)
    sec.note.setText(note)


def test_chip_text_and_click_applies_preset(env):
    loader, state, queue, sec, msgs = env
    assert sec.chips[0].text() == "Stainless Steel @ 800 °C → 5.829 mm²/s"
    assert sec.empty_label.isHidden()
    sec.chips[0].click()
    assert state.mark_alpha == "5.829" and state.mark_filter_material == "Stainless Steel"
    assert state.mark_filter_temp == ""


def test_empty_text_and_load_error(env):
    _, state, _, sec, _ = env
    state.set_presets([])
    assert not sec.empty_label.isHidden() and sec.chips == []
    sec.set_load_error("boom")
    assert sec.error_label.text() == TEXT["presetsLoadFailed"] + ": boom"
    assert sec.empty_label.isHidden()


def test_save_queues_one_insert_and_clears_form(env):
    loader, state, queue, sec, msgs = env
    fill(sec, "  Al₂O₃ ", "150", "8", "")
    sec.save_button.click()
    assert wait_until(lambda: not queue.busy)
    assert loader.ops == [("preset_insert", {"material_name": "Al₂O₃", "temperature_c": 150.0,
                                             "alpha_mm2s": 8.0, "note": None})]
    assert sec.material.text() == sec.temp.text() == sec.alpha.text() == sec.note.text() == ""
    assert msgs == []


def test_note_is_trimmed(env):
    loader, _, queue, sec, _ = env
    fill(sec, note="  Cengel A-3 ")
    sec.save_button.click()
    assert wait_until(lambda: not queue.busy)
    assert loader.ops[0][1]["note"] == "Cengel A-3"


@pytest.mark.parametrize("kw,msg", [
    (dict(material="   "), "errPresetMaterial"),
    (dict(temp="abc"), "errPresetTemp"),
    (dict(temp=""), "errPresetTemp"),
    (dict(alpha="0"), "errAlphaRequired"),
    (dict(alpha="-1"), "errAlphaRequired"),
    (dict(alpha="x"), "errAlphaRequired"),
])
def test_validation_queues_nothing(env, kw, msg):
    loader, _, queue, sec, msgs = env
    fill(sec, **kw)
    sec.save_button.click()
    assert loader.ops == [] and not queue.busy
    assert msgs == [(TEXT[msg], "error")]
    assert sec.material.text() != "" or kw.get("material") is not None   # form kept


def test_failed_save_keeps_form_and_reports(env):
    loader, _, queue, sec, msgs = env
    loader.fail_at = {0: ("server", "boom")}
    fill(sec)
    sec.save_button.click()
    assert wait_until(lambda: msgs)
    assert msgs[0][1] == "error" and "boom" in msgs[0][0]
    assert sec.alpha.text() == "8"


def test_literature_combo(env):
    _, _, _, sec, _ = env
    sec.literature.setCurrentText("Stainless Steel")
    assert sec.alpha.text() == "4" and sec.material.text() == "Stainless Steel"
    assert sec.literature.currentIndex() == 0
    sec.material.setText("Mine")
    sec.literature.setCurrentText("Al₂O₃")
    assert sec.alpha.text() == "8" and sec.material.text() == "Mine"


def test_delete_queues_one_preset_delete(env):
    loader, _, queue, sec, _ = env
    sec.delete_buttons[0].click()
    assert wait_until(lambda: not queue.busy)
    assert loader.ops == [("preset_delete", 1)]


def test_buttons_disabled_while_busy(env):
    loader, _, queue, sec, _ = env
    loader.hang_at = {0}
    fill(sec)
    sec.save_button.click()
    assert queue.busy
    assert not sec.save_button.isEnabled() and not sec.delete_buttons[0].isEnabled()
    sec.save_button.click()
    sec.delete_buttons[0].click()
    assert len(loader.ops) == 1
