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
    # |I| at or below which R = V/I is not computed (zero-crossings of a sweep
    # give garbage spikes). 1e-9 A is what the 2602B/2611A/2450 windows used;
    # the 6430 window used 1e-18 A, because sub-nanoamp currents are what a
    # 6430 is for.
    current_noise_floor: float = 1e-9
    # Smallest current compliance the source fields accept, and how many
    # decimals they show. 1 mA / 4 on every original window but the 6430's,
    # which went to 1 pA / 6 for sub-femtoamp work.
    min_current_compliance: float = 1e-3
    current_decimals: int = 4
    notes: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def dual_channel(self) -> bool:
        return len(self.channels) > 1

    def source_limits(self, function: str):
        """Field limits for sourcing ``"Voltage"`` or ``"Current"``:
        (value_min, value_max, value_decimals,
         compliance_min, compliance_max, compliance_decimals)."""
        if function == "Voltage":
            return (-self.max_voltage, self.max_voltage, 4,
                    self.min_current_compliance, self.max_current, self.current_decimals)
        return (-self.max_current, self.max_current, self.current_decimals,
                0.1, self.max_voltage, 4)
