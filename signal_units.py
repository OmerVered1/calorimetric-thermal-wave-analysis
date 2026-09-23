"""Unit menus and plot colors for signals that are not known until run time.

The Real Time tab used to hardcode one unit list per signal, which worked
while the three calorimeter channels were fixed in code. Profiles are now
user-editable, so a signal can arrive carrying any unit string at all — and
the honest answer for a unit we do not recognise is to show it exactly as
written and offer no conversions, rather than guess a family and silently
mis-scale a measurement.
"""

from __future__ import annotations

from typing import Callable, List, Tuple


# Multiplicative families, as {unit: how many reference units one of it is}.
# Converting between two members is just a ratio, so the base unit can be any
# member of the family rather than a fixed one.
_MULTIPLICATIVE: List[dict] = [
    {"µW": 1e-6, "mW": 1e-3, "W": 1.0, "kW": 1e3},
    {"µV": 1e-6, "mV": 1e-3, "V": 1.0, "kV": 1e3},
    {"nA": 1e-9, "µA": 1e-6, "mA": 1e-3, "A": 1.0},
    {"mΩ": 1e-3, "Ω": 1.0, "kΩ": 1e3, "MΩ": 1e6},
    {"mJ": 1e-3, "J": 1.0, "kJ": 1e3},
    {"s": 1.0, "min": 60.0, "h": 3600.0},
]

# Temperature is affine, so it cannot be expressed as a ratio.
_TEMPERATURE = ("°C", "K", "°F")


def _identity(x: float) -> float:
    return x


def _ratio(factor: float) -> Callable[[float], float]:
    return lambda x: x * factor


def _temperature_options(base: str) -> List[Tuple[str, Callable[[float], float]]]:
    """Conversions among °C/K/°F, expressed relative to `base`."""
    to_c = {
        "°C": lambda x: x,
        "K": lambda x: x - 273.15,
        "°F": lambda x: (x - 32.0) * 5.0 / 9.0,
    }[base]
    from_c = {
        "°C": lambda x: x,
        "K": lambda x: x + 273.15,
        "°F": lambda x: x * 9.0 / 5.0 + 32.0,
    }

    ordered = [base] + [u for u in _TEMPERATURE if u != base]
    options: List[Tuple[str, Callable[[float], float]]] = []
    for unit in ordered:
        conv = from_c[unit]
        options.append((unit, (lambda c, f=conv, t=to_c: f(t(c)))))
    return options


def unit_options(unit: str) -> List[Tuple[str, Callable[[float], float]]]:
    """Unit menu for a signal whose raw values are in `unit`.

    Returns (label, base→display) pairs with `unit` itself first and its
    transform the identity, so a caller can always take entry 0 and get the
    value untouched. An unrecognised unit yields exactly one entry.
    """
    unit = (unit or "").strip()

    if unit in _TEMPERATURE:
        return _temperature_options(unit)

    for family in _MULTIPLICATIVE:
        if unit in family:
            base = family[unit]
            ordered = [unit] + [u for u in family if u != unit]
            return [(u, _ratio(base / family[u])) for u in ordered]

    return [(unit, _identity)]


# Distinct enough to tell apart on one plot, and dark enough to read on the
# white plot background. Order matters: it is what fixes a signal's color.
# The program's plot palette (ctwa/theme.py): distinct, calm, readable on the
# light canvas. Order is what fixes a signal's colour between sessions.
PALETTE: List[str] = [
    "#C96442",  # clay       — heat flow
    "#3B6EA8",  # slate blue — sample T
    "#B8862B",  # ochre      — external T
    "#3F7A4F",  # moss
    "#8A5A9E",  # plum
    "#2F8C8C",  # teal
    "#6F6D66",  # graphite
    "#A64D79",  # berry
]


def color_for_index(index: int) -> str:
    """Plot color for the n-th signal, wrapping when there are more than the
    palette holds. Index-based rather than name-based so the same profile
    always paints the same way between sessions."""
    return PALETTE[index % len(PALETTE)]
