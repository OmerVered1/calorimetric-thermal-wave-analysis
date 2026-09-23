"""What each SMU model can do, declared once.

The app used to be four programs, one per instrument, each hardcoding its own
instrument's quirks into its own window. Now there is one window, and it asks
the connected model what to show: a second output channel, a front/rear
terminal switch, guard mode, which measurement ranges exist. Nothing in the UI
should branch on a model *name* — only on these fields — so adding a fifth
instrument means one new entry in `registry.py` and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple

# Transport identifiers. The connect dialog offers the ones a model lists.
VISA = "visa"      # USB / GPIB / LAN through a VISA resource string
SERIAL = "serial"  # RS-232 through a COM port (6430)
LAN = "lan"        # raw IP address, turned into a VISA TCPIP resource


@dataclass(frozen=True)
class RangeOption:
    label: str       # what the user sees, e.g. "200 mV"
    value: float     # SI value sent to the instrument


def ranges(*pairs) -> Tuple[RangeOption, ...]:
    return tuple(RangeOption(label, value) for label, value in pairs)


@dataclass(frozen=True)
class Capabilities:
    model: str                     # registry key, e.g. "2602B"
    display_name: str              # "Keithley 2602B"
    summary: str                   # one line for the model picker
    channels: Tuple[str, ...]      # ("a",) or ("a", "b")
    transports: Tuple[str, ...]
    max_voltage: float
    max_current: float
    voltage_ranges: Tuple[RangeOption, ...]
    current_ranges: Tuple[RangeOption, ...]
    # Optional hardware features. The UI shows a control only when True.
    terminal_select: bool = False     # 2450 front/rear jacks
    high_capacitance: bool = False    # 2450 SOUR:VOLT:HCAP
    auto_zero: bool = False           # 2450 / 6430
    guard_mode: bool = False          # 6430 triax guard
    output_off_mode: bool = False     # 6430 behaviour when output turns off
    nplc: bool = True                 # integration time control
    default_simulation_resistance: float = 1000.0
    notes: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def dual_channel(self) -> bool:
        return len(self.channels) > 1
