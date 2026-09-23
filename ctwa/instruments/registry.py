"""The supported SMU models.

Ranges are copied from the four original per-model windows, which were the
tested source of truth for what each instrument accepts.
"""

from __future__ import annotations

from typing import Dict

from .capabilities import LAN, SERIAL, VISA, Capabilities, ranges

MODELS: Dict[str, Capabilities] = {
    "2450": Capabilities(
        model="2450",
        display_name="Keithley 2450",
        summary="SourceMeter · ±200 V, ±1 A · USB",
        channels=("a",),
        transports=(VISA,),
        max_voltage=200.0,
        max_current=1.0,
        voltage_ranges=ranges(("200 mV", 0.2), ("2 V", 2), ("20 V", 20), ("200 V", 200)),
        current_ranges=ranges(
            ("10 nA", 10e-9), ("100 nA", 100e-9), ("1 µA", 1e-6), ("10 µA", 10e-6),
            ("100 µA", 100e-6), ("1 mA", 1e-3), ("10 mA", 10e-3), ("100 mA", 100e-3),
            ("1 A", 1),
        ),
        terminal_select=True,
        high_capacitance=True,
        auto_zero=True,
    ),
    "6430": Capabilities(
        model="6430",
        display_name="Keithley 6430",
        summary="Sub-femtoamp SourceMeter · ±105 V, ±105 mA · RS-232",
        channels=("a",),
        transports=(SERIAL,),
        max_voltage=105.0,
        max_current=0.105,
        voltage_ranges=ranges(("200 mV", 0.2), ("2 V", 2), ("20 V", 20), ("200 V", 200)),
        current_ranges=ranges(
            ("100 fA", 100e-15), ("1 pA", 1e-12), ("10 pA", 10e-12), ("100 pA", 100e-12),
            ("1 nA", 1e-9), ("10 nA", 10e-9), ("100 nA", 100e-9), ("1 µA", 1e-6),
            ("10 µA", 10e-6), ("100 µA", 100e-6), ("1 mA", 1e-3), ("10 mA", 10e-3),
            ("100 mA", 100e-3),
        ),
        auto_zero=True,
        guard_mode=True,
        output_off_mode=True,
        default_simulation_resistance=1e9,
    ),
    "2602B": Capabilities(
        model="2602B",
        display_name="Keithley 2602B",
        summary="Dual-channel SourceMeter · ±40 V, ±3 A · USB / GPIB / LAN",
        channels=("a", "b"),
        transports=(VISA, LAN),
        max_voltage=40.0,
        max_current=3.0,
        voltage_ranges=ranges(("200 mV", 0.2), ("2 V", 2), ("20 V", 20), ("40 V", 40)),
        current_ranges=ranges(
            ("100 nA", 100e-9), ("1 µA", 1e-6), ("10 µA", 10e-6), ("100 µA", 100e-6),
            ("1 mA", 1e-3), ("10 mA", 10e-3), ("100 mA", 100e-3), ("1 A", 1), ("3 A", 3),
        ),
    ),
    "2611A": Capabilities(
        model="2611A",
        display_name="Keithley 2611A",
        summary="SourceMeter · ±200 V, ±1.5 A · LAN / GPIB / USB",
        channels=("a",),
        transports=(LAN, VISA),
        max_voltage=200.0,
        max_current=1.5,
        voltage_ranges=ranges(("200 mV", 0.2), ("2 V", 2), ("20 V", 20), ("200 V", 200)),
        current_ranges=ranges(
            ("100 nA", 100e-9), ("1 µA", 1e-6), ("10 µA", 10e-6), ("100 µA", 100e-6),
            ("1 mA", 1e-3), ("10 mA", 10e-3), ("100 mA", 100e-3), ("1 A", 1), ("1.5 A", 1.5),
        ),
    ),
}

# Order shown in the model picker.
MODEL_ORDER = ("2602B", "2611A", "2450", "6430")


def get(model: str) -> Capabilities:
    try:
        return MODELS[model]
    except KeyError:
        raise ValueError(f"unknown SMU model {model!r}; known: {', '.join(MODEL_ORDER)}") from None
