"""
Keithley 2611A Single-Channel SourceMeter Driver
==================================================
Safe, robust driver for controlling the Keithley 2611A single-channel SMU via PyVISA.
Uses TSP (Test Script Processor) commands — the native Lua-based scripting language
shared across the Series 2600/2600A/2600B instruments.

Connects over LAN (LXI Class C, VISA/VXI-11 resource string, e.g.
"TCPIP::192.168.1.100::inst0::INSTR"), as well as GPIB, USB, and RS-232 —
any PyVISA-reachable transport works since the TSP command set is identical.

Author: Omer Vered
Date: 2026
"""

import pyvisa
import time
import logging
import re
import random
from typing import Optional, List, Dict
from dataclasses import dataclass
from enum import Enum

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SourceFunction(Enum):
    """Source function modes"""
    VOLTAGE = "DCVOLTS"
    CURRENT = "DCAMPS"


class MeasureFunction(Enum):
    """Measurement function modes"""
    VOLTAGE = "v"
    CURRENT = "i"
    RESISTANCE = "r"


class SenseMode(Enum):
    """Sense mode (2-wire or 4-wire)"""
    TWO_WIRE = "LOCAL"
    FOUR_WIRE = "REMOTE"


class OutputOffMode(Enum):
    """What the output does when it is turned off (smua.source.offmode)"""
    NORMAL = "OUTPUT_NORMAL"
    ZERO = "OUTPUT_ZERO"
    HIGH_Z = "OUTPUT_HIGH_Z"


# smua.measure.autozero, keyed by the "ON" / "OFF" / "ONCE" the SCPI models use
AUTO_ZERO_STATES = {"ON": "AUTOZERO_AUTO", "OFF": "AUTOZERO_OFF", "ONCE": "AUTOZERO_ONCE"}


@dataclass
class SafetyLimits:
    """
    Safety limits for instrument operation.

    Defaults are conservative relative to the 2611A's published envelope
    (±200V / ±1.5A, corner points ±20.2V@±1.515A and ±202V@±101mA).
    A single power_limit can't represent that two-corner envelope exactly,
    so power_limit defaults to the tighter (high-voltage-corner) figure —
    raise it explicitly if you need the full 1.5A at low voltage.

    Verify against your own unit's datasheet/rating label before relying on
    these for real hardware — this software limit is a secondary guard on
    top of the instrument's own compliance settings, not a substitute for them.
    """
    max_voltage: float = 200.0      # Maximum voltage limit (V)
    max_current: float = 1.5        # Maximum current limit (A)
    min_voltage: float = -200.0     # Minimum voltage limit (V)
    min_current: float = -1.5       # Minimum current limit (A)
    compliance_voltage: float = 200.0   # Default voltage compliance (V)
    compliance_current: float = 0.1     # Default current compliance (A)
    power_limit: float = 20.0       # Conservative power limit (W)


@dataclass
class ChannelState:
    """State tracking for the single SMU channel"""
    output_enabled: bool = False
    source_function: SourceFunction = SourceFunction.VOLTAGE
    source_value: float = 0.0
    sense_mode: SenseMode = SenseMode.TWO_WIRE
    measure_function: str = "i"  # default: measure current
    current_compliance: float = 0.1
    voltage_compliance: float = 200.0


@dataclass
class MeasurementResult:
    """Container for measurement results"""
    voltage: float
    current: float
    resistance: Optional[float] = None
    timestamp: Optional[float] = None
    source_value: Optional[float] = None
    source_function: Optional[str] = None
    channel: Optional[str] = None


class Keithley2611AError(Exception):
    """Custom exception for Keithley 2611A errors"""
    pass


class Keithley2611A:
    """
    Keithley 2611A Single-Channel SourceMeter Unit Driver

    Features:
    - Single channel (smua) via TSP (Test Script Processor) native command interface
    - LAN (LXI/VXI-11), GPIB, USB, RS-232 — anything PyVISA can open
    - Safe operation with configurable limits
    - Source voltage/current with compliance protection
    - Measure voltage, current, resistance
    - IV sweep measurements
    - Built-in safety checks and error handling
    - Simulation mode for testing without hardware
    """

    # Instrument absolute limits (do not exceed) — see SafetyLimits docstring
    ABSOLUTE_MAX_VOLTAGE = 200.0    # V
    ABSOLUTE_MAX_CURRENT = 1.5      # A
    ABSOLUTE_MAX_POWER = 20.0       # W (conservative single-figure envelope bound)

    VALID_CHANNELS = ("a",)

    def __init__(self, resource_name: Optional[str] = None,
                 safety_limits: Optional[SafetyLimits] = None,
                 simulate: bool = False,
                 simulation_resistance: float = 1000.0):
        """
        Initialize Keithley 2611A driver.

        Args:
            resource_name: VISA resource string, e.g.
                "TCPIP::192.168.1.100::inst0::INSTR" (LAN),
                "GPIB0::26::INSTR", or "USB0::0x05E6::0x2611::...::INSTR"
            safety_limits: Custom safety limits (uses defaults if None)
            simulate: If True, run in simulation mode without real hardware
            simulation_resistance: Resistance value (ohms) to simulate in simulation mode
        """
        self.resource_name = resource_name
        self.safety_limits = safety_limits or SafetyLimits()
        self.simulate = simulate
        self.simulation_resistance = simulation_resistance
        self._rm: Optional[pyvisa.ResourceManager] = None
        self._inst: Optional[pyvisa.Resource] = None
        self._connected = False

        # Single-channel state
        self._channels: Dict[str, ChannelState] = {
            "a": ChannelState(),
        }

        # Validate safety limits against absolute limits
        self._validate_safety_limits()

    def _validate_safety_limits(self):
        """Validate that safety limits don't exceed instrument absolute limits"""
        if abs(self.safety_limits.max_voltage) > self.ABSOLUTE_MAX_VOLTAGE:
            raise Keithley2611AError(
                f"Safety voltage limit {self.safety_limits.max_voltage}V exceeds "
                f"instrument maximum {self.ABSOLUTE_MAX_VOLTAGE}V"
            )
        if abs(self.safety_limits.max_current) > self.ABSOLUTE_MAX_CURRENT:
            raise Keithley2611AError(
                f"Safety current limit {self.safety_limits.max_current}A exceeds "
                f"instrument maximum {self.ABSOLUTE_MAX_CURRENT}A"
            )

    def _validate_channel(self, channel: str):
        """Validate channel parameter"""
        if channel not in self.VALID_CHANNELS:
            raise Keithley2611AError(
                f"Invalid channel '{channel}'. The 2611A only has channel 'a'"
            )

    def _smu(self, channel: str = "a") -> str:
        """Get TSP SMU identifier string for the channel"""
        self._validate_channel(channel)
        return f"smu{channel}"

    def _ch(self, channel: str = "a") -> ChannelState:
        """Get channel state"""
        self._validate_channel(channel)
        return self._channels[channel]

    # === CONNECTION ===

    @staticmethod
    def list_available_instruments() -> List[str]:
        """List all available VISA instruments"""
        try:
            try:
                rm = pyvisa.ResourceManager()
            except:
                rm = pyvisa.ResourceManager('@py')
            resources = rm.list_resources()
            logger.info(f"Found resources: {resources}")
            rm.close()
            return list(resources)
        except Exception as e:
            logger.error(f"Error listing instruments: {e}")
            return []

    @staticmethod
    def find_keithley_2611a() -> List[str]:
        """Find Keithley 2611A instruments specifically (GPIB/USB — LAN instruments aren't VISA-discoverable, enter the IP directly)"""
        keithley_resources = []
        try:
            rm = pyvisa.ResourceManager()
            for resource in rm.list_resources():
                if "0x05E6" in resource.upper() and "2611" in resource:
                    keithley_resources.append(resource)
                elif "KEITHLEY" in resource.upper() and "2611" in resource:
                    keithley_resources.append(resource)
            rm.close()
        except Exception as e:
            logger.error(f"Error finding Keithley 2611A: {e}")
        return keithley_resources

    def connect(self, resource_name: Optional[str] = None) -> bool:
        """
        Connect to the Keithley 2611A.

        Args:
            resource_name: VISA resource string (uses stored resource if None)

        Returns:
            True if connection successful
        """
        if self.simulate:
            logger.info("Running in SIMULATION mode - no hardware connected")
            self._connected = True
            return True

        if resource_name:
            self.resource_name = resource_name

        if not self.resource_name:
            raise Keithley2611AError("No resource name specified")

        try:
            self._rm = pyvisa.ResourceManager()
            self._inst = self._rm.open_resource(self.resource_name)

            # Configure communication
            self._inst.timeout = 10000  # 10 second timeout
            self._inst.read_termination = '\n'
            self._inst.write_termination = '\n'

            # Verify it's a Keithley 2611A (*IDN? works in TSP mode)
            idn = self._inst.query("*IDN?").strip()
            if "2611" not in idn:
                self._inst.close()
                self._rm.close()
                raise Keithley2611AError(f"Connected device is not a Keithley 2611A: {idn}")

            logger.info(f"Connected to: {idn}")
            self._connected = True

            # Initialize to safe state
            self._initialize_safe_state()

            return True

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self._connected = False
            raise Keithley2611AError(f"Failed to connect: {e}")

    def disconnect(self):
        """Safely disconnect from the instrument"""
        try:
            if self._connected and not self.simulate:
                self.output_off("a")

            if self._inst:
                self._inst.close()
            if self._rm:
                self._rm.close()

        except Exception as e:
            logger.warning(f"Error during disconnect: {e}")
        finally:
            self._inst = None
            self._rm = None
            self._connected = False
            for ch in self._channels.values():
                ch.output_enabled = False

    def _initialize_safe_state(self):
        """Initialize the channel to a safe state"""
        if self.simulate:
            return

        try:
            self._write("smua.reset()")
            time.sleep(0.3)

            self._write("smua.source.output = smua.OUTPUT_OFF")
            self._write("smua.source.func = smua.OUTPUT_DCVOLTS")
            self._write("smua.source.levelv = 0")
            self._write(f"smua.source.limiti = {self.safety_limits.compliance_current}")

            # Clear error queue
            self._write("errorqueue.clear()")

            logger.info("Channel initialized to safe state")

        except Exception as e:
            logger.error(f"Failed to initialize safe state: {e}")
            raise

    def _check_connected(self):
        """Check if connected, raise error if not"""
        if not self._connected:
            raise Keithley2611AError("Not connected to instrument")

    # === COMMUNICATION ===

    def _write(self, command: str):
        """Write TSP command to instrument"""
        if self.simulate:
            logger.debug(f"SIM WRITE: {command}")
            self._simulate_write(command)
            return
        self._check_connected()
        logger.debug(f"WRITE: {command}")
        self._inst.write(command)

    def _query(self, command: str) -> str:
        """
        Query instrument using TSP print() mechanism.

        For TSP, queries use print() to return values. The command should
        be a print() statement, e.g., "print(smua.measure.v())"
        """
        if self.simulate:
            logger.debug(f"SIM QUERY: {command}")
            return self._simulate_query(command)
        self._check_connected()
        logger.debug(f"QUERY: {command}")
        # TSP uses print() to output values — write then read
        if command == "*IDN?":
            # *IDN? is SCPI-compatible even in TSP mode
            response = self._inst.query(command).strip()
        else:
            self._inst.write(command)
            response = self._inst.read().strip()
        logger.debug(f"RESPONSE: {response}")
        return response

    def _simulate_write(self, command: str):
        """Parse TSP commands and track simulation state"""
        cmd = command.strip()
        ch = "a"

        # Track source function: smua.source.func = smua.OUTPUT_DCVOLTS
        match = re.match(r'smua\.source\.func\s*=\s*smua\.(OUTPUT_DCVOLTS|OUTPUT_DCAMPS)', cmd)
        if match:
            func = SourceFunction.VOLTAGE if match.group(1) == "OUTPUT_DCVOLTS" else SourceFunction.CURRENT
            self._channels[ch].source_function = func
            logger.debug(f"SIM: source function set to {func.name}")
            return

        # Track source voltage: smua.source.levelv = 1.0
        match = re.match(r'smua\.source\.levelv\s*=\s*([\-\d\.eE\+]+)', cmd)
        if match:
            val = float(match.group(1))
            self._channels[ch].source_value = val
            self._channels[ch].source_function = SourceFunction.VOLTAGE
            logger.debug(f"SIM: source voltage set to {val}")
            return

        # Track source current: smua.source.leveli = 0.001
        match = re.match(r'smua\.source\.leveli\s*=\s*([\-\d\.eE\+]+)', cmd)
        if match:
            val = float(match.group(1))
            self._channels[ch].source_value = val
            self._channels[ch].source_function = SourceFunction.CURRENT
            logger.debug(f"SIM: source current set to {val}")
            return

        # Track current compliance: smua.source.limiti = 0.1
        match = re.match(r'smua\.source\.limiti\s*=\s*([\-\d\.eE\+]+)', cmd)
        if match:
            self._channels[ch].current_compliance = float(match.group(1))
            return

        # Track voltage compliance: smua.source.limitv = 200
        match = re.match(r'smua\.source\.limitv\s*=\s*([\-\d\.eE\+]+)', cmd)
        if match:
            self._channels[ch].voltage_compliance = float(match.group(1))
            return

        # Track output state: smua.source.output = smua.OUTPUT_ON
        match = re.match(r'smua\.source\.output\s*=\s*smua\.(OUTPUT_ON|OUTPUT_OFF)', cmd)
        if match:
            self._channels[ch].output_enabled = (match.group(1) == "OUTPUT_ON")
            logger.debug(f"SIM: output {'ON' if self._channels[ch].output_enabled else 'OFF'}")
            return

        # Track sense mode: smua.sense = smua.SENSE_REMOTE
        match = re.match(r'smua\.sense\s*=\s*smua\.(SENSE_LOCAL|SENSE_REMOTE)', cmd)
        if match:
            self._channels[ch].sense_mode = SenseMode.FOUR_WIRE if match.group(1) == "SENSE_REMOTE" else SenseMode.TWO_WIRE
            return

        # Track reset
        if re.match(r'smua\.reset\(\)', cmd):
            self._channels[ch] = ChannelState()
            logger.debug("SIM: channel reset")
            return

    def _simulate_query(self, command: str) -> str:
        """Return simulated responses for testing with realistic I-V behavior"""
        cmd = command.strip()
        ch = "a"

        if "*IDN?" in cmd:
            return f"Keithley Instruments Inc., Model 2611A, 4301578, 3.3.3 (SIM R={self.simulation_resistance}Ω)"

        # Measure voltage: print(smua.measure.v())
        if re.match(r'print\(smua\.measure\.v\(\)\)', cmd):
            return self._simulate_measurement(ch, "v")

        # Measure current: print(smua.measure.i())
        if re.match(r'print\(smua\.measure\.i\(\)\)', cmd):
            return self._simulate_measurement(ch, "i")

        # Measure resistance: print(smua.measure.r())
        if re.match(r'print\(smua\.measure\.r\(\)\)', cmd):
            return self._simulate_measurement(ch, "r")

        # Measure IV: print(smua.measure.iv()) — returns "current\tvoltage"
        if re.match(r'print\(smua\.measure\.iv\(\)\)', cmd):
            i_str = self._simulate_measurement(ch, "i")
            v_str = self._simulate_measurement(ch, "v")
            return f"{i_str}\t{v_str}"

        # Source queries: print(smua.source.levelv)
        if re.match(r'print\(smua\.source\.levelv\)', cmd):
            return str(self._channels[ch].source_value)

        if re.match(r'print\(smua\.source\.leveli\)', cmd):
            return str(self._channels[ch].source_value)

        # Output state query: print(smua.source.output)
        if re.match(r'print\(smua\.source\.output\)', cmd):
            return "1" if self._channels[ch].output_enabled else "0"

        # Error queue: print(errorqueue.next())
        if "errorqueue" in cmd:
            return "0\tQueue Is Empty\t0\t0"

        return "0"

    def _simulate_measurement(self, channel: str, meas_type: str) -> str:
        """Generate realistic simulated measurement"""
        ch_state = self._channels[channel]
        v = ch_state.source_value
        effective_r = self.simulation_resistance

        if meas_type == "v":
            if ch_state.source_function == SourceFunction.VOLTAGE:
                noise = random.gauss(0, abs(v) * 0.0001 + 1e-6)
                return f"{v + noise:.9e}"
            else:
                # Sourcing current, measuring voltage: V = I*R
                voltage = v * effective_r
                noise = random.gauss(0, abs(voltage) * 0.001 + 1e-6)
                return f"{voltage + noise:.9e}"

        elif meas_type == "i":
            if ch_state.source_function == SourceFunction.VOLTAGE:
                # Sourcing voltage, measuring current: I = V/R
                if abs(v) > 1e-9:
                    current = v / effective_r
                    noise = random.gauss(0, abs(current) * 0.001 + 1e-9)
                    current += noise
                else:
                    current = random.gauss(0, 1e-10)
                return f"{current:.12e}"
            else:
                noise = random.gauss(0, abs(v) * 0.0001 + 1e-9)
                return f"{v + noise:.12e}"

        elif meas_type == "r":
            noise = random.gauss(0, effective_r * 0.001)
            return f"{effective_r + noise:.6e}"

        return "0"

    # === IDENTIFICATION & UTILITY ===

    def get_identification(self) -> str:
        """Get instrument identification string"""
        return self._query("*IDN?")

    def reset(self, channel: Optional[str] = None):
        """Reset the channel to defaults"""
        self._write("smua.reset()")
        self._channels["a"] = ChannelState()
        time.sleep(0.3)
        self._write("errorqueue.clear()")
        logger.info("Channel reset to defaults")

    def clear_errors(self):
        """Clear error queue"""
        self._write("errorqueue.clear()")

    def get_errors(self) -> List[str]:
        """Get all errors from error queue"""
        if self.simulate:
            return []
        errors = []
        while True:
            response = self._query("print(errorqueue.next())")
            # TSP error format: code\tmessage\tseverity\tnode
            parts = response.split('\t')
            if len(parts) >= 2 and parts[0].strip() == "0":
                break
            errors.append(response)
            if len(errors) > 50:  # Safety limit
                break
        return errors

    # === OUTPUT CONTROL ===

    def output_on(self, channel: str = "a") -> bool:
        """
        Turn output ON.

        Returns:
            True if output was enabled successfully
        """
        self._check_connected()
        self._validate_channel(channel)
        ch_state = self._ch(channel)

        # Safety check: verify source value is within limits before enabling
        if ch_state.source_function == SourceFunction.VOLTAGE:
            if not (self.safety_limits.min_voltage <= ch_state.source_value <= self.safety_limits.max_voltage):
                raise Keithley2611AError(
                    f"Cannot enable output: source voltage {ch_state.source_value}V "
                    f"outside safety limits [{self.safety_limits.min_voltage}, {self.safety_limits.max_voltage}]V"
                )
        else:
            if not (self.safety_limits.min_current <= ch_state.source_value <= self.safety_limits.max_current):
                raise Keithley2611AError(
                    f"Cannot enable output: source current {ch_state.source_value}A "
                    f"outside safety limits [{self.safety_limits.min_current}, {self.safety_limits.max_current}]A"
                )

        self._write("smua.source.output = smua.OUTPUT_ON")
        ch_state.output_enabled = True
        logger.info("Output ENABLED")
        return True

    def output_off(self, channel: str = "a"):
        """Turn output OFF (safe operation)"""
        try:
            self._write("smua.source.output = smua.OUTPUT_OFF")
        except:
            pass  # Always try to turn off, even if there's an error
        self._channels["a"].output_enabled = False
        logger.info("Output DISABLED")

    def output_enabled(self, channel: str = "a") -> bool:
        """Check if output is enabled"""
        return self._ch(channel).output_enabled

    def get_output_state(self, channel: str = "a") -> bool:
        """Query actual output state from instrument"""
        if self.simulate:
            return self._channels["a"].output_enabled
        response = self._query("print(smua.source.output)")
        return response.strip() == "1"

    # === SOURCE CONFIGURATION ===

    def set_source_voltage(self, voltage: float, compliance_current: Optional[float] = None,
                           channel: str = "a"):
        """
        Configure voltage source mode.

        Args:
            voltage: Source voltage in Volts
            compliance_current: Current limit in Amps (uses safety default if None)
        """
        # Safety validation
        if not (self.safety_limits.min_voltage <= voltage <= self.safety_limits.max_voltage):
            raise Keithley2611AError(
                f"Voltage {voltage}V outside safety limits "
                f"[{self.safety_limits.min_voltage}, {self.safety_limits.max_voltage}]V"
            )

        compliance = compliance_current or self.safety_limits.compliance_current
        if abs(compliance) > self.safety_limits.max_current:
            raise Keithley2611AError(
                f"Compliance current {compliance}A exceeds safety limit {self.safety_limits.max_current}A"
            )

        self._write("smua.source.func = smua.OUTPUT_DCVOLTS")
        self._write(f"smua.source.limiti = {compliance}")
        self._write(f"smua.source.levelv = {voltage}")

        ch_state = self._ch(channel)
        ch_state.source_function = SourceFunction.VOLTAGE
        ch_state.source_value = voltage
        ch_state.current_compliance = compliance

        logger.info(f"Voltage source configured: {voltage}V, compliance: {compliance}A")

    def set_source_current(self, current: float, compliance_voltage: Optional[float] = None,
                           channel: str = "a"):
        """
        Configure current source mode.

        Args:
            current: Source current in Amps
            compliance_voltage: Voltage limit in Volts (uses safety default if None)
        """
        # Safety validation
        if not (self.safety_limits.min_current <= current <= self.safety_limits.max_current):
            raise Keithley2611AError(
                f"Current {current}A outside safety limits "
                f"[{self.safety_limits.min_current}, {self.safety_limits.max_current}]A"
            )

        compliance = compliance_voltage or self.safety_limits.compliance_voltage
        if abs(compliance) > self.safety_limits.max_voltage:
            raise Keithley2611AError(
                f"Compliance voltage {compliance}V exceeds safety limit {self.safety_limits.max_voltage}V"
            )

        self._write("smua.source.func = smua.OUTPUT_DCAMPS")
        self._write(f"smua.source.limitv = {compliance}")
        self._write(f"smua.source.leveli = {current}")

        ch_state = self._ch(channel)
        ch_state.source_function = SourceFunction.CURRENT
        ch_state.source_value = current
        ch_state.voltage_compliance = compliance

        logger.info(f"Current source configured: {current}A, compliance: {compliance}V")

    def set_voltage(self, voltage: float, channel: str = "a"):
        """
        Set source voltage value with safety validation.
        Use this during sweeps after initial configuration.
        """
        if not (self.safety_limits.min_voltage <= voltage <= self.safety_limits.max_voltage):
            raise Keithley2611AError(
                f"SAFETY STOP: Voltage {voltage}V outside safety limits "
                f"[{self.safety_limits.min_voltage}, {self.safety_limits.max_voltage}]V"
            )

        # Power check
        ch_state = self._ch(channel)
        potential_power = abs(voltage * ch_state.current_compliance)
        if potential_power > self.safety_limits.power_limit:
            raise Keithley2611AError(
                f"SAFETY STOP: Potential power {potential_power:.2f}W exceeds limit {self.safety_limits.power_limit}W"
            )

        self._write(f"smua.source.levelv = {voltage}")
        ch_state.source_value = voltage
        logger.debug(f"Voltage set to: {voltage}V")

    def set_current(self, current: float, channel: str = "a"):
        """
        Set source current value with safety validation.
        Use this during sweeps after initial configuration.
        """
        if not (self.safety_limits.min_current <= current <= self.safety_limits.max_current):
            raise Keithley2611AError(
                f"SAFETY STOP: Current {current}A outside safety limits "
                f"[{self.safety_limits.min_current}, {self.safety_limits.max_current}]A"
            )

        # Power check
        ch_state = self._ch(channel)
        potential_power = abs(current * ch_state.voltage_compliance)
        if potential_power > self.safety_limits.power_limit:
            raise Keithley2611AError(
                f"SAFETY STOP: Potential power {potential_power:.2f}W exceeds limit {self.safety_limits.power_limit}W"
            )

        self._write(f"smua.source.leveli = {current}")
        ch_state.source_value = current
        logger.debug(f"Current set to: {current}A")

    def get_source_value(self, channel: str = "a") -> float:
        """Get current source value"""
        ch_state = self._ch(channel)
        if ch_state.source_function == SourceFunction.VOLTAGE:
            return float(self._query("print(smua.source.levelv)"))
        else:
            return float(self._query("print(smua.source.leveli)"))

    # === MEASUREMENT FUNCTIONS ===

    def set_measure_function(self, function: MeasureFunction, channel: str = "a"):
        """Set the measurement function"""
        # TSP doesn't require explicit measure function selection —
        # you call the specific measure method directly. Track for simulation.
        self._ch(channel).measure_function = function.value
        logger.info(f"Measure function set to: {function.name}")

    def set_sense_mode(self, mode: SenseMode, channel: str = "a"):
        """Set 2-wire or 4-wire sensing"""
        tsp_mode = "smua.SENSE_REMOTE" if mode == SenseMode.FOUR_WIRE else "smua.SENSE_LOCAL"
        self._write(f"smua.sense = {tsp_mode}")
        self._ch(channel).sense_mode = mode
        logger.info(f"Sense mode set to: {mode.name}")

    def set_output_off_mode(self, mode: OutputOffMode, channel: str = "a"):
        """Set what the output does when turned off: NORMAL, ZERO or HIGH_Z.
        smua.reset() leaves it at NORMAL."""
        smu = self._smu(channel)
        self._write(f"{smu}.source.offmode = {smu}.{mode.value}")
        logger.info(f"Output off mode set to: {mode.name}")

    def set_auto_zero(self, state: str = "ON", channel: str = "a"):
        """Set auto-zero: "ON" (automatic, the reset default), "OFF" or "ONCE"."""
        smu = self._smu(channel)
        try:
            tsp_state = AUTO_ZERO_STATES[state.upper()]
        except KeyError:
            raise Keithley2611AError(f"Auto zero must be ON, OFF or ONCE, not {state!r}") from None
        self._write(f"{smu}.measure.autozero = {smu}.{tsp_state}")
        logger.info(f"Auto zero set to: {state.upper()}")

    def set_nplc(self, nplc: float, channel: str = "a"):
        """
        Set Number of Power Line Cycles for measurement integration.

        Args:
            nplc: NPLC value (0.001 to 25)
        """
        if not 0.001 <= nplc <= 25:
            raise Keithley2611AError(f"NPLC value {nplc} outside valid range [0.001, 25]")
        self._write(f"smua.measure.nplc = {nplc}")
        logger.info(f"NPLC set to: {nplc}")

    def set_measure_range(self, range_val: float, measure_type: str = "i", channel: str = "a"):
        """
        Set measurement range.

        Args:
            range_val: Range value (e.g., 0.1 for 100mA range)
            measure_type: 'v' for voltage, 'i' for current
        """
        self._write(f"smua.measure.range{measure_type} = {range_val}")
        logger.info(f"Measure range ({measure_type}) set to: {range_val}")

    def set_measure_range_auto(self, auto: bool = True, measure_type: str = "i", channel: str = "a"):
        """
        Enable/disable auto-range for measurements.

        Args:
            auto: True to enable auto-range
            measure_type: 'v' for voltage, 'i' for current
        """
        val = "smua.AUTORANGE_ON" if auto else "smua.AUTORANGE_OFF"
        self._write(f"smua.measure.autorange{measure_type} = {val}")
        logger.info(f"Auto-range ({measure_type}): {'ON' if auto else 'OFF'}")

    def measure_voltage(self, channel: str = "a") -> float:
        """Measure voltage"""
        return float(self._query("print(smua.measure.v())"))

    def measure_current(self, channel: str = "a") -> float:
        """Measure current"""
        return float(self._query("print(smua.measure.i())"))

    def measure_resistance(self, channel: str = "a") -> float:
        """Measure resistance"""
        return float(self._query("print(smua.measure.r())"))

    def measure_all(self, channel: str = "a") -> MeasurementResult:
        """Measure voltage, current, and calculate resistance"""
        # Use iv() to get both in one call (more efficient)
        response = self._query("print(smua.measure.iv())")
        parts = response.split('\t')
        if len(parts) >= 2:
            current = float(parts[0])
            voltage = float(parts[1])
        else:
            # Fallback: separate measurements
            voltage = self.measure_voltage(channel)
            current = self.measure_current(channel)

        # Calculate resistance
        resistance = None
        if abs(current) > 1e-12:
            resistance = voltage / current

        ch_state = self._ch(channel)
        return MeasurementResult(
            voltage=voltage,
            current=current,
            resistance=resistance,
            timestamp=time.time(),
            source_value=ch_state.source_value,
            source_function=ch_state.source_function.name,
            channel="a",
        )

    # === SWEEP FUNCTIONS ===

    def voltage_sweep(self, start: float, stop: float, points: int,
                      compliance_current: Optional[float] = None,
                      delay: float = 0.05,
                      channel: str = "a") -> List[MeasurementResult]:
        """
        Perform a voltage sweep and measure current.

        Args:
            start: Starting voltage (V)
            stop: Ending voltage (V)
            points: Number of points in sweep
            compliance_current: Current compliance limit (A)
            delay: Delay between points (s)

        Returns:
            List of MeasurementResult objects
        """
        # Safety validation
        for v in [start, stop]:
            if not (self.safety_limits.min_voltage <= v <= self.safety_limits.max_voltage):
                raise Keithley2611AError(
                    f"Sweep voltage {v}V outside safety limits "
                    f"[{self.safety_limits.min_voltage}, {self.safety_limits.max_voltage}]V"
                )

        if points < 2:
            raise Keithley2611AError("Sweep must have at least 2 points")
        if points > 2500:
            raise Keithley2611AError("Maximum 2500 points in sweep")

        compliance = compliance_current or self.safety_limits.compliance_current

        results = []
        step = (stop - start) / (points - 1)

        logger.info(f"Starting voltage sweep: {start}V to {stop}V, {points} points")

        try:
            self.set_source_voltage(start, compliance, channel)

            if not self._channels["a"].output_enabled:
                self.output_on(channel)

            for i in range(points):
                voltage = start + i * step
                self._write(f"smua.source.levelv = {voltage}")
                self._channels["a"].source_value = voltage
                time.sleep(delay)

                current = float(self._query("print(smua.measure.i())"))

                resistance = None
                if abs(current) > 1e-12:
                    resistance = voltage / current

                results.append(MeasurementResult(
                    voltage=voltage,
                    current=current,
                    resistance=resistance,
                    timestamp=time.time(),
                    source_value=voltage,
                    source_function="VOLTAGE",
                    channel="a",
                ))

        except Exception as e:
            logger.error(f"Sweep error: {e}")
            self.output_off(channel)
            raise

        logger.info(f"Voltage sweep complete: {len(results)} points")
        return results

    def current_sweep(self, start: float, stop: float, points: int,
                      compliance_voltage: Optional[float] = None,
                      delay: float = 0.05,
                      channel: str = "a") -> List[MeasurementResult]:
        """
        Perform a current sweep and measure voltage.

        Args:
            start: Starting current (A)
            stop: Ending current (A)
            points: Number of points in sweep
            compliance_voltage: Voltage compliance limit (V)
            delay: Delay between points (s)

        Returns:
            List of MeasurementResult objects
        """
        # Safety validation
        for i in [start, stop]:
            if not (self.safety_limits.min_current <= i <= self.safety_limits.max_current):
                raise Keithley2611AError(
                    f"Sweep current {i}A outside safety limits "
                    f"[{self.safety_limits.min_current}, {self.safety_limits.max_current}]A"
                )

        if points < 2:
            raise Keithley2611AError("Sweep must have at least 2 points")
        if points > 2500:
            raise Keithley2611AError("Maximum 2500 points in sweep")

        compliance = compliance_voltage or self.safety_limits.compliance_voltage

        results = []
        step = (stop - start) / (points - 1)

        logger.info(f"Starting current sweep: {start}A to {stop}A, {points} points")

        try:
            self.set_source_current(start, compliance, channel)

            if not self._channels["a"].output_enabled:
                self.output_on(channel)

            for i in range(points):
                current = start + i * step
                self._write(f"smua.source.leveli = {current}")
                self._channels["a"].source_value = current
                time.sleep(delay)

                voltage = float(self._query("print(smua.measure.v())"))

                resistance = None
                if abs(current) > 1e-12:
                    resistance = voltage / current

                results.append(MeasurementResult(
                    voltage=voltage,
                    current=current,
                    resistance=resistance,
                    timestamp=time.time(),
                    source_value=current,
                    source_function="CURRENT",
                    channel="a",
                ))

        except Exception as e:
            logger.error(f"Sweep error: {e}")
            self.output_off(channel)
            raise

        logger.info(f"Current sweep complete: {len(results)} points")
        return results

    # === UTILITY FUNCTIONS ===

    def beep(self, frequency: int = 2000, duration: float = 0.1):
        """Make the instrument beep"""
        self._write(f"beeper.beep({duration}, {frequency})")

    def local_mode(self):
        """Return to local (front panel) control"""
        self._write("display.clear()")
        if self._inst and not self.simulate:
            try:
                self._inst.write("localnode.prompts = 1")
            except:
                pass

    def remote_mode(self):
        """Set to remote control mode"""
        if self._inst and not self.simulate:
            try:
                self._inst.write("localnode.prompts = 0")
            except:
                pass

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensure safe disconnect"""
        self.disconnect()
        return False


# Convenience function for quick testing
def quick_test():
    """Quick test of driver functionality"""
    print("Available instruments:")
    for inst in Keithley2611A.list_available_instruments():
        print(f"  {inst}")

    print("\nLooking for Keithley 2611A...")
    k2611a_list = Keithley2611A.find_keithley_2611a()
    if k2611a_list:
        print(f"Found: {k2611a_list}")
    else:
        print("No Keithley 2611A found on GPIB/USB. Running in simulation mode...")
        print("(For LAN, connect directly with resource_name='TCPIP::<ip>::inst0::INSTR')")

        with Keithley2611A(simulate=True) as smu:
            smu.connect()
            print(f"ID: {smu.get_identification()}")

            smu.set_source_voltage(1.0, compliance_current=0.01)
            smu.output_on()
            result = smu.measure_all()
            print(f"V={result.voltage:.6f} V, I={result.current:.9f} A, R={result.resistance:.1f} Ω")
            smu.output_off()

            print("\n--- Voltage Sweep ---")
            results = smu.voltage_sweep(0, 5, 6, compliance_current=0.1, delay=0.01)
            for r in results:
                print(f"  V={r.voltage:.2f}V, I={r.current:.6f}A")
            smu.output_off()

            print("\nAll tests passed!")


if __name__ == "__main__":
    quick_test()
