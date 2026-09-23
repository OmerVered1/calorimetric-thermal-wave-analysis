"""One SMU interface over four different drivers.

The four drivers already agree on almost every method name. They disagree in a
few systematic ways, and this class absorbs every one of them so the window
never has to know which instrument is connected:

  * The TSP instruments (2602B, 2611A) take a trailing ``channel`` argument on
    nearly every call; the SCPI ones (2450, 6430) take none. Here every call
    accepts ``channel`` and it is dropped where the hardware has only one.
  * Range calls differ in argument order and encoding —
    ``set_measure_range(MeasureFunction.VOLTAGE, 2.0)`` on SCPI versus
    ``set_measure_range(2.0, "v", "a")`` on TSP.
  * Each driver module defines its *own* ``SenseMode`` enum, with different
    values, so the right one must come from the connected driver's module.
  * ``connect()`` takes a VISA resource on three models and a serial port plus
    baud rate on the 6430.
  * ``output_enabled`` is a method on TSP drivers and a property on SCPI ones.

Optional features (terminal select, guard mode, ...) raise ``NotSupported`` on
a model that lacks them rather than silently doing nothing, so a UI bug that
shows a control it should hide fails loudly in simulation, not quietly at the
bench.
"""

from __future__ import annotations

import importlib
from typing import Any, Optional

from . import registry
from .capabilities import Capabilities


class NotSupported(RuntimeError):
    """The connected model has no such feature."""


# model -> (driver module, driver class, calling convention)
_DRIVERS = {
    "2450": ("keithley2450_driver", "Keithley2450", "scpi"),
    "6430": ("keithley6430_driver", "Keithley6430", "scpi"),
    "2602B": ("keithley2602b_driver", "Keithley2602B", "tsp"),
    "2611A": ("keithley2611a_driver", "Keithley2611A", "tsp"),
}


class SMU:
    def __init__(self, caps: Capabilities, driver: Any, module: Any, convention: str):
        self.caps = caps
        self.driver = driver
        self._module = module
        self._tsp = convention == "tsp"

    # ----- construction --------------------------------------------------

    @classmethod
    def create(
        cls,
        model: str,
        *,
        simulate: bool = False,
        simulation_resistance: Optional[float] = None,
        safety_limits: Any = None,
    ) -> "SMU":
        caps = registry.get(model)
        module_name, class_name, convention = _DRIVERS[model]
        module = importlib.import_module(module_name)
        driver_cls = getattr(module, class_name)
        resistance = (
            simulation_resistance
            if simulation_resistance is not None
            else caps.default_simulation_resistance
        )
        driver = driver_cls(
            safety_limits=safety_limits,
            simulate=simulate,
            simulation_resistance=resistance,
        )
        return cls(caps, driver, module, convention)

    # ----- helpers -------------------------------------------------------

    def _ch(self, channel: str) -> dict:
        """Channel keyword for the driver call — or nothing, on SCPI."""
        channel = (channel or "a").lower()
        if channel not in self.caps.channels:
            raise NotSupported(
                f"{self.caps.display_name} has no channel {channel.upper()} "
                f"(channels: {', '.join(c.upper() for c in self.caps.channels)})"
            )
        return {"channel": channel} if self._tsp else {}

    def _require(self, flag: str, what: str) -> None:
        if not getattr(self.caps, flag):
            raise NotSupported(f"{self.caps.display_name} has no {what}")

    def _measure_function(self, quantity: str):
        mf = self._module.MeasureFunction
        return {"v": mf.VOLTAGE, "i": mf.CURRENT}[quantity]

    # ----- state ---------------------------------------------------------

    @property
    def model(self) -> str:
        return self.caps.model

    @property
    def simulate(self) -> bool:
        return bool(getattr(self.driver, "simulate", False))

    @property
    def connected(self) -> bool:
        return self.simulate or bool(getattr(self.driver, "_connected", False))

    @property
    def safety_limits(self):
        return self.driver.safety_limits

    # ----- connection ----------------------------------------------------

    def connect(self, address: Optional[str] = None, *, baud_rate: Optional[int] = None) -> bool:
        """VISA resource string, or serial port on the 6430."""
        if self.model == "6430":
            return self.driver.connect(address, baud_rate)
        return self.driver.connect(address)

    def disconnect(self) -> None:
        self.driver.disconnect()

    def identify(self) -> str:
        return self.driver.get_identification()

    def reset(self, channel: str = "a") -> None:
        self.driver.reset(**self._ch(channel))

    def clear_errors(self) -> None:
        self.driver.clear_errors()

    def get_errors(self):
        return self.driver.get_errors()

    def beep(self, *args, **kwargs):
        return self.driver.beep(*args, **kwargs)

    def local_mode(self) -> None:
        self.driver.local_mode()

    # ----- sourcing ------------------------------------------------------

    def set_source_voltage(self, voltage: float, compliance_current: Optional[float] = None,
                           channel: str = "a") -> None:
        self.driver.set_source_voltage(voltage, compliance_current=compliance_current,
                                       **self._ch(channel))

    def set_source_current(self, current: float, compliance_voltage: Optional[float] = None,
                           channel: str = "a") -> None:
        self.driver.set_source_current(current, compliance_voltage=compliance_voltage,
                                       **self._ch(channel))

    def set_voltage(self, voltage: float, channel: str = "a") -> None:
        self.driver.set_voltage(voltage, **self._ch(channel))

    def set_current(self, current: float, channel: str = "a") -> None:
        self.driver.set_current(current, **self._ch(channel))

    def get_source_value(self, channel: str = "a") -> float:
        return self.driver.get_source_value(**self._ch(channel))

    def output_on(self, channel: str = "a") -> None:
        self.driver.output_on(**self._ch(channel))

    def output_off(self, channel: str = "a") -> None:
        self.driver.output_off(**self._ch(channel))

    def output_enabled(self, channel: str = "a") -> bool:
        # A method taking a channel on TSP drivers; a plain property on SCPI.
        state = self.driver.output_enabled
        ch = self._ch(channel)
        return bool(state(**ch) if callable(state) else state)

    def all_outputs_off(self) -> None:
        """Every channel off. What a panic button and app exit should call."""
        for channel in self.caps.channels:
            try:
                self.output_off(channel)
            except Exception:
                pass

    # ----- measuring -----------------------------------------------------

    def measure_all(self, channel: str = "a"):
        return self.driver.measure_all(**self._ch(channel))

    def measure_voltage(self, channel: str = "a") -> float:
        return self.driver.measure_voltage(**self._ch(channel))

    def measure_current(self, channel: str = "a") -> float:
        return self.driver.measure_current(**self._ch(channel))

    def measure_resistance(self, channel: str = "a") -> float:
        return self.driver.measure_resistance(**self._ch(channel))

    def voltage_sweep(self, start, stop, points, compliance_current=None, delay=0.1,
                      channel: str = "a"):
        return self.driver.voltage_sweep(start, stop, points, compliance_current, delay,
                                         **self._ch(channel))

    def current_sweep(self, start, stop, points, compliance_voltage=None, delay=0.1,
                      channel: str = "a"):
        return self.driver.current_sweep(start, stop, points, compliance_voltage, delay,
                                         **self._ch(channel))

    # ----- measurement configuration ------------------------------------

    def configure_measure_range(self, quantity: str, value: Optional[float],
                                channel: str = "a") -> None:
        """``value=None`` means auto-range.

        A fixed range is set, then auto-range turned off — the two-step sequence
        every original window used. Setting a range does not on its own disable
        auto-range on these instruments.
        """
        quantity = quantity.lower()
        if quantity not in ("v", "i"):
            raise ValueError("quantity must be 'v' or 'i'")
        if self._tsp:
            ch = self._ch(channel)
            if value is None:
                self.driver.set_measure_range_auto(True, quantity, **ch)
            else:
                self.driver.set_measure_range(value, quantity, **ch)
                self.driver.set_measure_range_auto(False, quantity, **ch)
            return
        self._ch(channel)
        fn = self._measure_function(quantity)
        if value is None:
            self.driver.set_measure_range_auto(fn, True)
        else:
            self.driver.set_measure_range(fn, value)
            self.driver.set_measure_range_auto(fn, False)

    def set_nplc(self, nplc: float, channel: str = "a") -> None:
        self._require("nplc", "integration-time (NPLC) control")
        self.driver.set_nplc(nplc, **self._ch(channel))

    def set_remote_sense(self, four_wire: bool, channel: str = "a") -> None:
        """2-wire / 4-wire. On the 2450 this covers both I and V sense."""
        if self._tsp:
            mode = self._module.SenseMode.FOUR_WIRE if four_wire else self._module.SenseMode.TWO_WIRE
            self.driver.set_sense_mode(mode, **self._ch(channel))
        else:
            self._ch(channel)
            self.driver.set_remote_sense(four_wire)

    # ----- model-specific features --------------------------------------

    def set_terminal(self, terminal: str) -> None:
        self._require("terminal_select", "front/rear terminal switch")
        self.driver.set_terminal(terminal.upper())

    def set_high_capacitance(self, enabled: bool) -> None:
        self._require("high_capacitance", "high-capacitance mode")
        self.driver.set_high_capacitance(enabled)

    def set_auto_zero(self, state: str) -> None:
        self._require("auto_zero", "auto-zero control")
        self.driver.set_auto_zero(state.upper())

    def set_guard_mode(self, enabled: bool) -> None:
        self._require("guard_mode", "guard mode")
        self.driver.set_guard_mode(enabled)

    def set_output_off_mode(self, mode) -> None:
        self._require("output_off_mode", "output-off mode")
        self.driver.set_output_off_mode(mode)

    def __repr__(self) -> str:
        how = "simulated" if self.simulate else ("connected" if self.connected else "disconnected")
        return f"<SMU {self.caps.display_name} {how}>"
