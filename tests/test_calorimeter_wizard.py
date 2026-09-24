import os
import struct

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from calorimeter_discovery import analyse_chunks  # noqa: E402
from calorimeter_setups import SetupStore  # noqa: E402
from calorimeter_wizard import (  # noqa: E402
    COL_NAME,
    COL_UNIT,
    COL_USE,
    CalorimeterSetupDialog,
)
from sniffer.reassembly import C2S, S2C, FlowKey, StreamChunk  # noqa: E402


FLOW = FlowKey("10.0.0.9", 51000, 1210)
CMDS = [
    bytes.fromhex("0001000a0001"),
    bytes.fromhex("000100080004"),
    bytes.fromhex("000100080005"),
]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _traffic(cycles=40):
    chunks, ts = [], 1000.0
    for c in range(cycles):
        for i, cmd in enumerate(CMDS):
            value = [32.2, 766.7, 20.2][i] + c * 0.01
            chunks.append(StreamChunk(ts=ts, flow=FLOW, direction=C2S,
                                      data=cmd, stream_offset=0))
            chunks.append(StreamChunk(ts=ts + 0.01, flow=FLOW, direction=S2C,
                                      data=cmd + struct.pack(">f", value),
                                      stream_offset=0))
            ts += 0.3
    return chunks


@pytest.fixture
def dialog(app, tmp_path):
    store = SetupStore(tmp_path / "setups.json")
    d = CalorimeterSetupDialog(store=store)
    # Inject a discovery rather than capturing — no scapy, no instrument here.
    d._on_capture_done(analyse_chunks(_traffic()))
    return d


def test_capture_result_fills_one_row_per_channel(dialog):
    assert dialog.table.rowCount() == 3


def test_save_is_enabled_only_after_a_successful_capture(app, tmp_path):
    d = CalorimeterSetupDialog(store=SetupStore(tmp_path / "s.json"))
    from PySide6.QtWidgets import QDialogButtonBox
    assert not d._buttons.button(QDialogButtonBox.Save).isEnabled()
    d._on_capture_done(analyse_chunks(_traffic()))
    assert d._buttons.button(QDialogButtonBox.Save).isEnabled()


def test_capture_error_is_surfaced_and_blocks_saving(app, tmp_path):
    from calorimeter_discovery import Discovery
    from PySide6.QtWidgets import QDialogButtonBox
    d = CalorimeterSetupDialog(store=SetupStore(tmp_path / "s.json"))
    d._on_capture_done(Discovery(analysis=None, error="no packets captured"))
    assert "no packets" in d.warnings_label.text()
    assert not d._buttons.button(QDialogButtonBox.Save).isEnabled()
    assert d.table.rowCount() == 0


def test_rows_default_to_the_best_ranked_field(dialog):
    for row in range(dialog.table.rowCount()):
        combo = dialog.table.cellWidget(row, 2)
        assert combo.currentData().offset == 6
        assert combo.currentData().encoding == "f32be"


def test_preview_column_shows_recent_values(dialog):
    text = dialog.table.item(dialog.table.rowCount() - 1, 5).text()
    assert text.strip(), "expected a preview of decoded values"


def test_unticked_rows_are_not_collected(dialog):
    for row in range(dialog.table.rowCount()):
        dialog.table.cellWidget(row, COL_USE).setChecked(row == 0)
        dialog.table.item(row, COL_NAME).setText(f"sig{row}")
    assert len(dialog._collect_choices()) == 1


def test_saving_writes_both_a_profile_and_a_setup(dialog, tmp_path, monkeypatch):
    written = {}

    def fake_save_profile(profile):
        written["profile"] = profile
        return tmp_path / "written.json"

    monkeypatch.setattr("calorimeter_wizard.save_profile", fake_save_profile)
    monkeypatch.setattr("calorimeter_wizard.QMessageBox.information",
                        lambda *a, **k: None)

    dialog.setup_name.setText("Bench")
    dialog.profile_name.setText("Alexsys Drop")
    dialog.host_edit.setText("10.0.0.9")
    names = ["heat_flow", "sample_temperature", "external_temperature"]
    units = ["mW", "degC", "degC"]
    for row in range(3):
        dialog.table.cellWidget(row, COL_USE).setChecked(True)
        dialog.table.item(row, COL_NAME).setText(names[row])
        dialog.table.item(row, COL_UNIT).setText(units[row])

    dialog._on_save()

    assert dialog.saved_setup is not None
    assert dialog.saved_setup.name == "Bench"
    assert dialog.saved_setup.profile_name == "Alexsys Drop"
    assert dialog.saved_setup.host == "10.0.0.9"
    assert {s.name for s in written["profile"].signals} == set(names)
    # And it landed in the store on disk
    assert SetupStore(dialog._store.path).names() == ["Bench"]


def test_saving_without_a_name_is_refused(dialog, monkeypatch):
    warned = []
    monkeypatch.setattr("calorimeter_wizard.QMessageBox.warning",
                        lambda *a, **k: warned.append(a))
    dialog.profile_name.setText("P")
    dialog._on_save()
    assert warned and dialog.saved_setup is None


def test_saving_with_no_ticked_signals_is_refused(dialog, monkeypatch):
    warned = []
    monkeypatch.setattr("calorimeter_wizard.QMessageBox.warning",
                        lambda *a, **k: warned.append(a))
    dialog.setup_name.setText("Bench")
    dialog.profile_name.setText("P")
    for row in range(dialog.table.rowCount()):
        dialog.table.cellWidget(row, COL_USE).setChecked(False)
    dialog._on_save()
    assert warned and dialog.saved_setup is None


def test_duplicate_signal_names_are_refused_with_a_message(dialog, monkeypatch):
    warned = []
    monkeypatch.setattr("calorimeter_wizard.QMessageBox.warning",
                        lambda *a, **k: warned.append(a))
    dialog.setup_name.setText("Bench")
    dialog.profile_name.setText("P")
    for row in range(3):
        dialog.table.cellWidget(row, COL_USE).setChecked(True)
        dialog.table.item(row, COL_NAME).setText("same")
    dialog._on_save()
    assert warned and dialog.saved_setup is None
