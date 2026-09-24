import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from calorimeter_reader import CalorimeterSignal  # noqa: E402
import realtime_tab as rt  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tab(app):
    return rt.RealTimeTab()


DROP_SIGNALS = [
    CalorimeterSignal("heat_flow", "Heat Flow", "mW"),
    CalorimeterSignal("sample_temperature", "Sample Temperature", "°C"),
    CalorimeterSignal("external_temperature", "External Temperature", "°C"),
]


def test_defaults_match_the_legacy_three_channels(tab):
    assert [s.key for s in tab._cal_specs] == ["hf", "t", "ext_t"]
    # The first three palette colours, in order, so a signal keeps its colour.
    from signal_units import PALETTE
    assert [s.color for s in tab._cal_specs] == PALETTE[:3]


def test_setting_profile_signals_replaces_the_calorimeter_rows(tab):
    tab.set_calorimeter_signals(DROP_SIGNALS)
    assert [s.key for s in tab._cal_specs] == [
        "heat_flow", "sample_temperature", "external_temperature"
    ]
    # Keithley signals survive untouched
    assert [s.key for s in tab._specs[-4:]] == ["v", "i", "r", "p"]
    # Control rows and the values shown under them follow the new set
    assert set(tab._control_rows) == {s.key for s in tab._specs}
    assert set(tab._value_labels) == {s.key for s in tab._specs}


def test_old_keys_are_gone_after_a_profile_change(tab):
    tab.set_calorimeter_signals(DROP_SIGNALS)
    assert "hf" not in tab._series
    assert "heat_flow" in tab._series


def test_samples_under_profile_keys_are_plotted(tab):
    tab.set_calorimeter_signals(DROP_SIGNALS)
    tab.push_calorimeter_sample(1000.0, {"heat_flow": 32.27, "sample_temperature": 766.78})
    assert tab._series["heat_flow"].ys_base == [32.27]
    assert tab._series["sample_temperature"].ys_base == [766.78]


def test_unknown_reading_keys_are_dropped_not_misplotted(tab):
    tab.set_calorimeter_signals(DROP_SIGNALS)
    tab.push_calorimeter_sample(1000.0, {"who_is_this": 1.0})
    assert all(not s.ys_base for s in tab._series.values())


def test_legacy_keys_still_work_for_direct_connect(tab):
    """Direct connect declares hf/t/ext_t; those must still land."""
    tab.set_calorimeter_signals([
        CalorimeterSignal("hf", "Heat Flow", "mW"),
        CalorimeterSignal("t", "Sample Temperature", "°C"),
    ])
    tab.push_calorimeter_sample(1.0, {"hf": 5.0, "t": 25.0})
    assert tab._series["hf"].ys_base == [5.0]


def test_unchanged_signal_set_is_a_noop(tab):
    before = tab._series["hf"]
    tab.set_calorimeter_signals([
        CalorimeterSignal("hf", "Heat Flow", "mW"),
        CalorimeterSignal("t", "Sample Temperature", "°C"),
        CalorimeterSignal("ext_t", "External Temperature", "°C"),
    ])
    # Same Series objects, so buffered data and axis arrangement survive
    assert tab._series["hf"] is before


def test_switching_profiles_twice_leaves_no_orphan_curves(tab):
    tab.set_calorimeter_signals(DROP_SIGNALS)
    scene = tab._plot.plotItem.scene()
    tab.set_calorimeter_signals([CalorimeterSignal("only", "Only", "bar")])
    live = {id(s.view_box) for s in tab._series.values() if s.view_box is not None}
    orphans = [
        it for it in scene.items()
        if isinstance(it, rt.pg.ViewBox) and id(it) not in live
        and it is not tab._plot.plotItem.vb
    ]
    assert orphans == []


def test_unknown_unit_signal_gets_a_single_unit_entry(tab):
    tab.set_calorimeter_signals([CalorimeterSignal("flux", "Flux", "counts/s")])
    spec = tab._cal_specs[0]
    assert [u for u, _ in spec.units] == ["counts/s"]


def test_reference_reset_clears_the_shown_value(tab):
    """The stale-value bug: a value must not survive a buffer clear."""
    tab.push_calorimeter_sample(1000.0, {"hf": 32.27})
    assert tab._value_labels["hf"].text() == "32.27 mW"
    tab.set_reference_now("connect")
    assert tab._value_labels["hf"].text() == ""


def test_clearing_source_meter_values_leaves_the_calorimeter(tab):
    tab.push_calorimeter_sample(1000.0, {"hf": 32.27})
    tab.push_keithley_sample(1000.0, 1.0, 0.01, 100.0, 0.01)
    tab.clear_values(("v", "i", "r", "p"))
    assert tab._value_labels["v"].text() == ""
    assert tab._value_labels["hf"].text() == "32.27 mW"


def test_a_gap_breaks_the_trace_without_becoming_a_value(tab):
    """Pausing marks a gap: the line must not join across it, the shown value
    must stay the last real one, and the gap must never reach a saved CSV."""
    import math
    tab.push_keithley_sample(1000.0, 1.0, 0.01, 100.0, 0.01)
    tab.mark_gap(1001.0)
    tab.mark_gap(1001.5)   # a second mark at the same gap adds nothing
    tab.push_keithley_sample(1003.0, 1.2, 0.012, 100.0, 0.0144)
    s = tab._series["v"]
    assert sum(1 for y in s.ys_base if math.isnan(y)) == 1
    assert tab._value_labels["v"].text() == "1.2 V"
