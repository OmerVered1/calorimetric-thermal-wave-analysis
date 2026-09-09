import pytest

from calorimeter_reader import (
    CALORIMETERS,
    CalorimeterReader,
    CalorimeterSignal,
    SniffingCalorimeterReader,
    pretty_signal_label,
)


# ----- direct-connect reader -------------------------------------------------

def test_direct_reader_declares_its_channels():
    channels = CALORIMETERS["Drop (Alexsys)"]["channels"]
    r = CalorimeterReader(host="1.2.3.4", channels=channels)
    specs = r.signal_specs()
    assert [s.key for s in specs] == ["hf", "t", "ext_t"]
    assert [s.unit for s in specs] == ["mW", "°C", "°C"]
    assert specs[0].label == "Heat Flow"


def test_direct_reader_only_declares_channels_it_polls():
    channels = CALORIMETERS["C80 (Setaram)"]["channels"]
    r = CalorimeterReader(host="1.2.3.4", channels=channels)
    assert [s.key for s in r.signal_specs()] == ["hf", "t"]


def test_direct_reader_falls_back_for_an_unknown_channel_key():
    r = CalorimeterReader(host="1.2.3.4", channels={"zz": b"\x00" * 6})
    spec = r.signal_specs()[0]
    assert spec.key == "zz"
    assert spec.unit == ""


# ----- sniffing reader -------------------------------------------------------

def test_sniffing_reader_declares_signals_from_its_profile():
    r = SniffingCalorimeterReader(host="1.2.3.4", calorimeter_name="Drop (Alexsys)")
    specs = r.signal_specs()
    assert [s.key for s in specs] == [
        "heat_flow", "sample_temperature", "external_temperature"
    ]
    assert [s.label for s in specs] == [
        "Heat Flow", "Sample Temperature", "External Temperature"
    ]
    # "degC" in the profile JSON is normalised for display
    assert [s.unit for s in specs] == ["mW", "°C", "°C"]


def test_sniffing_reader_with_no_profile_declares_nothing_and_does_not_raise():
    r = SniffingCalorimeterReader(host="1.2.3.4", calorimeter_name="nonexistent")
    assert r.signal_specs() == []


def test_sniffing_reader_emits_profile_signal_names_not_legacy_keys():
    """The old _SNIFF_SIGNAL_TO_CHANNEL translation is gone: whatever the
    profile calls a signal is the key the plot and the CSV use."""
    r = SniffingCalorimeterReader(host="1.2.3.4", calorimeter_name="Drop (Alexsys)")
    keys = {s.key for s in r.signal_specs()}
    assert "hf" not in keys
    assert "heat_flow" in keys


# ----- label prettifying -----------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("heat_flow", "Heat Flow"),
    ("sample_temperature", "Sample Temperature"),
    ("t", "T"),
    ("HF", "HF"),                  # already-capitalised acronyms are preserved
    ("", ""),
])
def test_pretty_signal_label(raw, expected):
    assert pretty_signal_label(raw) == expected


def test_signal_is_hashable_and_comparable():
    a = CalorimeterSignal("hf", "Heat Flow", "mW")
    b = CalorimeterSignal("hf", "Heat Flow", "mW")
    assert a == b
    assert len({a, b}) == 1
