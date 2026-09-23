"""The common SMU interface, against all four drivers in simulation.

The equivalence tests matter most. The 2450 and 6430 windows used to send some
settings as raw SCPI straight from the GUI. Those commands now come from driver
methods behind the facade, and every measurement taken so far was made with the
GUI's exact sequence — so the facade must reproduce it byte for byte.
"""

import pytest

from ctwa.instruments import registry
from ctwa.instruments.smu import SMU, NotSupported

ALL = list(registry.MODEL_ORDER)


def recorder(smu):
    """Capture every command the driver writes, while still simulating."""
    sent = []
    real = smu.driver._write

    def spy(command):
        sent.append(command)
        return real(command)

    smu.driver._write = spy
    return sent


@pytest.fixture(params=ALL)
def smu(request):
    s = SMU.create(request.param, simulate=True)
    s.connect()
    return s


# ----- every model, one interface --------------------------------------------


def test_every_model_constructs_and_connects_in_simulation(smu):
    assert smu.simulate and smu.connected
    assert smu.identify()


def test_source_and_measure_through_the_same_calls(smu):
    smu.set_source_voltage(0.5, compliance_current=0.01)
    smu.output_on()
    assert smu.output_enabled()
    result = smu.measure_all()
    assert result is not None
    smu.output_off()
    assert not smu.output_enabled()


def test_every_channel_a_model_declares_is_usable(smu):
    for ch in smu.caps.channels:
        smu.set_source_voltage(0.1, compliance_current=0.01, channel=ch)
        smu.output_off(channel=ch)


def test_a_channel_the_model_lacks_is_refused(smu):
    if smu.caps.dual_channel:
        pytest.skip("has channel B")
    with pytest.raises(NotSupported, match="no channel B"):
        smu.output_on(channel="b")


def test_all_outputs_off_covers_every_channel(smu):
    for ch in smu.caps.channels:
        smu.set_source_voltage(0.1, compliance_current=0.01, channel=ch)
        smu.output_on(channel=ch)
    smu.all_outputs_off()
    assert not any(smu.output_enabled(channel=ch) for ch in smu.caps.channels)


def test_ranges_configure_on_every_model(smu):
    smu.configure_measure_range("v", smu.caps.voltage_ranges[0].value)
    smu.configure_measure_range("i", smu.caps.current_ranges[-1].value)
    smu.configure_measure_range("v", None)
    smu.set_remote_sense(True)
    smu.set_remote_sense(False)
    smu.set_nplc(1.0)


# ----- capabilities are honest ------------------------------------------------

FEATURES = {
    "terminal_select": ("set_terminal", ("FRONT",)),
    "high_capacitance": ("set_high_capacitance", (True,)),
    "auto_zero": ("set_auto_zero", ("ON",)),
    "guard_mode": ("set_guard_mode", (True,)),
}


@pytest.mark.parametrize("flag", list(FEATURES))
def test_declared_features_work_and_undeclared_ones_refuse(smu, flag):
    method, args = FEATURES[flag]
    if getattr(smu.caps, flag):
        getattr(smu, method)(*args)
    else:
        with pytest.raises(NotSupported):
            getattr(smu, method)(*args)


def test_registry_limits_match_the_drivers_own_safety_limits(smu):
    assert smu.caps.max_voltage == smu.safety_limits.max_voltage
    assert smu.caps.max_current == smu.safety_limits.max_current


# ----- byte-for-byte equivalence with what the old windows sent ---------------


def test_2450_four_wire_sets_both_current_and_voltage_sense():
    """The fix that stopped 4-wire wiring reading as 2-wire."""
    s = SMU.create("2450", simulate=True); s.connect()
    sent = recorder(s)
    s.set_remote_sense(True)
    assert sent == ["SENS:CURR:RSEN ON", "SENS:VOLT:RSEN ON"]
    sent.clear()
    s.set_remote_sense(False)
    assert sent == ["SENS:CURR:RSEN OFF", "SENS:VOLT:RSEN OFF"]


def test_2450_fixed_range_matches_the_old_window():
    s = SMU.create("2450", simulate=True); s.connect()
    sent = recorder(s)
    s.configure_measure_range("v", 20)
    s.configure_measure_range("i", 1e-3)
    s.configure_measure_range("v", None)
    assert sent == [
        "SENS:VOLT:RANG 20", "SENS:VOLT:RANG:AUTO OFF",
        "SENS:CURR:RANG 0.001", "SENS:CURR:RANG:AUTO OFF",
        "SENS:VOLT:RANG:AUTO ON",
    ]


def test_2450_sweep_settings_match_the_old_window():
    s = SMU.create("2450", simulate=True); s.connect()
    sent = recorder(s)
    s.set_nplc(1.0)
    s.set_high_capacitance(True)
    s.set_auto_zero("once")
    assert sent == [
        "SENS:CURR:NPLC 1.0", "SENS:VOLT:NPLC 1.0",
        "SOUR:VOLT:HCAP ON",
        "SENS:AZER ONCE",
    ]


def test_6430_fixed_range_matches_the_old_window():
    s = SMU.create("6430", simulate=True); s.connect()
    sent = recorder(s)
    s.configure_measure_range("v", 2)
    s.configure_measure_range("i", 1e-12)
    s.configure_measure_range("i", None)
    assert sent == [
        ":SENS:VOLT:RANG 2", ":SENS:VOLT:RANG:AUTO OFF",
        ":SENS:CURR:RANG 1e-12", ":SENS:CURR:RANG:AUTO OFF",
        ":SENS:CURR:RANG:AUTO ON",
    ]


def test_6430_four_wire_is_the_single_system_setting():
    s = SMU.create("6430", simulate=True); s.connect()
    sent = recorder(s)
    s.set_remote_sense(True)
    assert sent == [":SYST:RSEN ON"]   # what the old 6430 window sent


@pytest.mark.parametrize("model", ["2602B", "2611A"])
def test_tsp_range_calls_match_the_old_window_sequence(model):
    """TSP windows called the driver directly, so compare driver calls."""
    s = SMU.create(model, simulate=True); s.connect()
    calls = []
    for name in ("set_measure_range", "set_measure_range_auto"):
        real = getattr(s.driver, name)
        setattr(s.driver, name, lambda *a, _n=name, _r=real, **k: (calls.append((_n, a, k)), _r(*a, **k)))
    s.configure_measure_range("v", 20, channel="a")
    s.configure_measure_range("i", None, channel="a")
    assert calls == [
        ("set_measure_range", (20, "v"), {"channel": "a"}),
        ("set_measure_range_auto", (False, "v"), {"channel": "a"}),
        ("set_measure_range_auto", (True, "i"), {"channel": "a"}),
    ]


def test_2602b_channel_b_reaches_the_driver_as_channel_b():
    s = SMU.create("2602B", simulate=True); s.connect()
    seen = []
    real = s.driver.set_source_voltage
    s.driver.set_source_voltage = lambda *a, **k: (seen.append(k.get("channel")), real(*a, **k))
    s.set_source_voltage(0.1, compliance_current=0.01, channel="b")
    assert seen == ["b"]


def test_unknown_model_is_a_clear_error():
    with pytest.raises(ValueError, match="unknown SMU model"):
        SMU.create("2400", simulate=True)


# ----- safety limits never cross models ---------------------------------------


@pytest.mark.parametrize("model", ALL)
def test_each_model_starts_from_its_own_limits(model):
    limits = SMU.default_limits(model)
    caps = registry.get(model)
    assert limits.max_voltage == caps.max_voltage
    assert limits.max_current == caps.max_current


def test_limits_saved_on_a_2602b_are_clamped_for_a_6430():
    """3 A from a 2602B config must not reach a 105 mA instrument."""
    big = SMU.default_limits("2602B")
    clamped = SMU.clamp_limits("6430", big)
    assert clamped.max_current == pytest.approx(0.105)
    assert clamped.min_current == pytest.approx(-0.105)
    assert type(clamped).__module__ == "keithley6430_driver"


def test_clamping_keeps_limits_that_are_already_tighter():
    tight = SMU.default_limits("2450")
    tight.max_voltage = 5.0
    tight.min_voltage = -5.0
    out = SMU.clamp_limits("2450", tight)
    assert out.max_voltage == 5.0 and out.min_voltage == -5.0


@pytest.mark.parametrize("model", ALL)
def test_a_driver_accepts_its_own_clamped_limits(model):
    s = SMU.create(model, simulate=True,
                   safety_limits=SMU.clamp_limits(model, SMU.default_limits("2602B")))
    s.connect()
    assert s.connected
