import pytest

from signal_units import color_for_index, unit_options


def _labels(unit):
    return [label for label, _fn in unit_options(unit)]


def _convert(unit, target, value):
    for label, fn in unit_options(unit):
        if label == target:
            return fn(value)
    raise AssertionError(f"{target} not offered for base {unit}")


# ----- the base unit always leads, unchanged ---------------------------------

@pytest.mark.parametrize("unit", ["mW", "°C", "V", "A", "Ω", "bar", ""])
def test_base_unit_is_first_and_is_identity(unit):
    options = unit_options(unit)
    assert options[0][0] == unit
    assert options[0][1](42.5) == 42.5


# ----- known families --------------------------------------------------------

def test_power_family_from_milliwatts():
    assert _labels("mW") == ["mW", "µW", "W", "kW"]
    assert _convert("mW", "µW", 1.0) == pytest.approx(1000.0)
    assert _convert("mW", "W", 1000.0) == pytest.approx(1.0)
    assert _convert("mW", "kW", 1e6) == pytest.approx(1.0)


def test_power_family_from_watts_reorders_around_the_base():
    assert _labels("W")[0] == "W"
    assert set(_labels("W")) == {"µW", "mW", "W", "kW"}
    assert _convert("W", "mW", 2.0) == pytest.approx(2000.0)


def test_temperature_family_is_affine_not_multiplicative():
    assert _labels("°C") == ["°C", "K", "°F"]
    assert _convert("°C", "K", 0.0) == pytest.approx(273.15)
    assert _convert("°C", "°F", 100.0) == pytest.approx(212.0)


def test_resistance_and_current_families():
    assert _convert("Ω", "kΩ", 1000.0) == pytest.approx(1.0)
    assert _convert("A", "mA", 0.5) == pytest.approx(500.0)


# ----- unknown units ---------------------------------------------------------

def test_unknown_unit_gets_no_conversions():
    assert _labels("bar") == ["bar"]


def test_blank_unit_is_offered_as_a_single_dimensionless_entry():
    assert _labels("") == [""]


def test_unknown_unit_is_not_silently_renamed():
    """A wizard-typed unit must appear on the axis exactly as written."""
    assert unit_options("counts/s")[0][0] == "counts/s"


# ----- colors ----------------------------------------------------------------

def test_colors_are_stable_and_cycle():
    first = color_for_index(0)
    assert color_for_index(0) == first
    assert color_for_index(1) != first


def test_color_index_wraps_without_error():
    assert color_for_index(999).startswith("#")
