"""
Keithley 2602B Dual-Channel SourceMeter Driver
================================================
Safe, robust driver for controlling the Keithley 2602B dual-channel SMU via PyVISA.
Uses TSP (Test Script Processor) commands — the native Lua-based scripting language
of the 2600B series instruments.

Supports dual independent channels (smua/smub) with per-channel safety limits.

Author: Omer Vered
Date: 2026
"""

import pyvisa
import time
import logging
import re
import random
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import dataclass, field
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
    """What the output does when it is turned off (smuX.source.offmode)"""
    NORMAL = "OUTPUT_NORMAL"
    ZERO = "OUTPUT_ZERO"
    HIGH_Z = "OUTPUT_HIGH_Z"


# smuX.measure.autozero, keyed by the "ON" / "OFF" / "ONCE" the SCPI models use
AUTO_ZERO_STATES = {"ON": "AUTOZERO_AUTO", "OFF": "AUTOZERO_OFF", "ONCE": "AUTOZERO_ONCE"}


@dataclass
class SafetyLimits:
    """Safety limits for instrument operation"""
    max_voltage: float = 40.0       # Maximum voltage limit (V)
    max_current: float = 3.0        # Maximum current limit (A) — DC
    min_voltage: float = -40.0      # Minimum voltage limit (V)
    min_current: float = -3.0       # Minimum current limit (A)
    compliance_voltage: float = 40.0    # Default voltage compliance (V)
    compliance_current: float = 1.0     # Default current compliance (A)
    power_limit: float = 40.4       # Maximum power per channel (W)


@dataclass
class ChannelState:
    """Per-channel state tracking"""
    output_enabled: bool = False
    source_function: SourceFunction = SourceFunction.VOLTAGE
    source_value: float = 0.0
    sense_mode: SenseMode = SenseMode.TWO_WIRE
    measure_function: str = "i"  # default: measure current
    current_compliance: float = 1.0
    voltage_compliance: float = 40.0


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


class Keithley2602BError(Exception):
    """Custom exception for Keithley 2602B errors"""
    pass


class Keithley2602B:
    """
    Keithley 2602B Dual-Channel SourceMeter Unit Driver

    Features:
    - Dual independent channels (smua/smub)
    - TSP (Test Script Processor) native command interface
    - Safe operation with configurable per-channel limits
    - Source voltage/current with compliance protection
    - Measure voltage, current, resistance
    - IV sweep measurements
    - Built-in safety checks and error handling
    - Simulation mode for testing without hardware
    """

    # Instrument absolute limits (do not exceed)
    ABSOLUTE_MAX_VOLTAGE = 40.0    # V
    ABSOLUTE_MAX_CURRENT = 10.0    # A (pulse)
    ABSOLUTE_MAX_CURRENT_DC = 3.0  # A (DC continuous)
    ABSOLUTE_MAX_POWER = 40.4      # W per channel

    VALID_CHANNELS = ("a", "b")

    def __init__(self, resource_name: Optional[str] = None,
                 safety_limits: Optional[SafetyLimits] = None,
                 simulate: bool = False,
                 simulation_resistance: float = 1000.0):
        """
        Initialize Keithley 2602B driver.

        Args:
            resource_name: VISA resource string (e.g., "GPIB0::26::INSTR" or "USB0::0x05E6::0x2602::...")
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

        # Per-channel state
        self._channels: Dict[str, ChannelState] = {
            "a": ChannelState(),
            "b": ChannelState(),
        }

        # Validate safety limits against absolute limits
        self._validate_safety_limits()

    def _validate_safety_limits(self):
        """Validate that safety limits don't exceed instrument absolute limits"""
        if abs(self.safety_limits.max_voltage) > self.ABSOLUTE_MAX_VOLTAGE:
            raise Keithley2602BError(
                f"Safety voltage limit {self.safety_limits.max_voltage}V exceeds "
                f"instrument maximum {self.ABSOLUTE_MAX_VOLTAGE}V"
            )
        if abs(self.safety_limits.max_current) > self.ABSOLUTE_MAX_CURRENT_DC:
            raise Keithley2602BError(
                f"Safety current limit {self.safety_limits.max_current}A exceeds "
                f"instrument DC maximum {self.ABSOLUTE_MAX_CURRENT_DC}A"
            )

    def _validate_channel(self, channel: str):
        """Validate channel parameter"""
        if channel not in self.VALID_CHANNELS:
            raise Keithley2602BError(
                f"Invalid channel '{channel}'. Must be 'a' or 'b'"
            )

    def _smu(self, channel: str) -> str:
        """Get TSP SMU identifier string for a channel"""
        self._validate_channel(channel)
        return f"smu{channel}"

    def _ch(self, channel: str) -> ChannelState:
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
    def find_keithley_2602b() -> List[str]:
        """Find Keithley 2602B instruments specifically"""
        keithley_resources = []
        try:
            rm = pyvisa.ResourceManager()
            for resource in rm.list_resources():
                if "0x05E6" in resource.upper() and "2602" in resource:
                    keithley_resources.append(resource)
                elif "KEITHLEY" in resource.upper() and "2602" in resource:
                    keithley_resources.append(resource)
            rm.close()
        except Exception as e:
            logger.error(f"Error finding Keithley 2602B: {e}")
        return keithley_resources

    def connect(self, resource_name: Optional[str] = None) -> bool:
        """
        Connect to the Keithley 2602B.

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
            raise Keithley2602BError("No resource name specified")

        try:
            self._rm = pyvisa.ResourceManager()
            self._inst = self._rm.open_resource(self.resource_name)

            # Configure communication
            self._inst.timeout = 10000  # 10 second timeout
            self._inst.read_termination = '\n'
            self._inst.write_termination = '\n'

            # Verify it's a Keithley 2602B (*IDN? works in TSP mode)
            idn = self._inst.query("*IDN?").strip()
            if "2602" not in idn:
                self._inst.close()
                self._rm.close()
                raise Keithley2602BError(f"Connected device is not a Keithley 2602B: {idn}")

            logger.info(f"Connected to: {idn}")
            self._connected = True

            # Initialize to safe state
            self._initialize_safe_state()

            return True

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self._connected = False
            raise Keithley2602BError(f"Failed to connect: {e}")

    def disconnect(self):
        """Safely disconnect from the instrument"""
        try:
            if self._connected and not self.simulate:
                # Turn off both outputs before disconnecting
                self.output_off("a")
                self.output_off("b")

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
        """Initialize both channels to a safe state"""
        if self.simulate:
            return

        try:
            # Reset both channels
            self._write("smua.reset()")
            self._write("smub.reset()")
            time.sleep(0.3)

            # Turn off both outputs
            self._write("smua.source.output = smua.OUTPUT_OFF")
            self._write("smub.source.output = smub.OUTPUT_OFF")

            # Set both channels to voltage source at 0V
            for ch in ("a", "b"):
                smu = self._smu(ch)
                self._write(f"{smu}.source.func = {smu}.OUTPUT_DCVOLTS")
                self._write(f"{smu}.source.levelv = 0")
                self._write(f"{smu}.source.limiti = {self.safety_limits.compliance_current}")

            # Clear error queue
            self._write("errorqueue.clear()")

            logger.info("Both channels initialized to safe state")

        except Exception as e:
            logger.error(f"Failed to initialize safe state: {e}")
            raise

    def _check_connected(self):
        """Check if connected, raise error if not"""
        if not self._connected:
            raise Keithley2602BError("Not connected to instrument")

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

        # Track source function: smua.source.func = smua.OUTPUT_DCVOLTS
        match = re.match(r'smu([ab])\.source\.func\s*=\s*smu[ab]\.(OUTPUT_DCVOLTS|OUTPUT_DCAMPS)', cmd)
        if match:
            ch = match.group(1)
            func = SourceFunction.VOLTAGE if match.group(2) == "OUTPUT_DCVOLTS" else SourceFunction.CURRENT
            self._channels[ch].source_function = func
            logger.debug(f"SIM: Channel {ch} source function set to {func.name}")
            return

        # Track source voltage: smua.source.levelv = 1.0
        match = re.match(r'smu([ab])\.source\.levelv\s*=\s*([\-\d\.eE\+]+)', cmd)
        if match:
            ch = match.group(1)
            val = float(match.group(2))
            self._channels[ch].source_value = val
            self._channels[ch].source_function = SourceFunction.VOLTAGE
            logger.debug(f"SIM: Channel {ch} source voltage set to {val}")
            return

        # Track source current: smua.source.leveli = 0.001
        match = re.match(r'smu([ab])\.source\.leveli\s*=\s*([\-\d\.eE\+]+)', cmd)
        if match:
            ch = match.group(1)
            val = float(match.group(2))
            self._channels[ch].source_value = val
            self._channels[ch].source_function = SourceFunction.CURRENT
            logger.debug(f"SIM: Channel {ch} source current set to {val}")
            return

        # Track current compliance: smua.source.limiti = 0.1
        match = re.match(r'smu([ab])\.source\.limiti\s*=\s*([\-\d\.eE\+]+)', cmd)
        if match:
            ch = match.group(1)
            self._channels[ch].current_compliance = float(match.group(2))
            return

        # Track voltage compliance: smua.source.limitv = 40
        match = re.match(r'smu([ab])\.source\.limitv\s*=\s*([\-\d\.eE\+]+)', cmd)
        if match:
            ch = match.group(1)
            self._channels[ch].voltage_compliance = float(match.group(2))
            return

        # Track output state: smua.source.output = smua.OUTPUT_ON
        match = re.match(r'smu([ab])\.source\.output\s*=\s*smu[ab]\.(OUTPUT_ON|OUTPUT_OFF)', cmd)
        if match:
            ch = match.group(1)
            self._channels[ch].output_enabled = (match.group(2) == "OUTPUT_ON")
            logger.debug(f"SIM: Channel {ch} output {'ON' if self._channels[ch].output_enabled else 'OFF'}")
            return

        # Track sense mode: smua.sense = smua.SENSE_REMOTE
        match = re.match(r'smu([ab])\.sense\s*=\s*smu[ab]\.(SENSE_LOCAL|SENSE_REMOTE)', cmd)
        if match:
            ch = match.group(1)
            self._channels[ch].sense_mode = SenseMode.FOUR_WIRE if match.group(2) == "SENSE_REMOTE" else SenseMode.TWO_WIRE
            return

        # Track reset
        match = re.match(r'smu([ab])\.reset\(\)', cmd)
        if match:
            ch = match.group(1)
            self._channels[ch] = ChannelState()
            logger.debug(f"SIM: Channel {ch} reset")
            return

    def _simulate_query(self, command: str) -> str:
        """Return simulated responses for testing with realistic I-V behavior"""
        cmd = command.strip()

        if "*IDN?" in cmd:
            return f"Keithley Instruments Inc., Model 2602B, 4301578, 3.3.3 (SIM R={self.simulation_resistance}Ω)"

        # Measure voltage: print(smua.measure.v())
        match = re.match(r'print\(smu([ab])\.measure\.v\(\)\)', cmd)
        if match:
            ch = match.group(1)
            return self._simulate_measurement(ch, "v")

        # Measure current: print(smua.measure.i())
        match = re.match(r'print\(smu([ab])\.measure\.i\(\)\)', cmd)
        if match:
            ch = match.group(1)
            return self._simulate_measurement(ch, "i")

        # Measure resistance: print(smua.measure.r())
        match = re.match(r'print\(smu([ab])\.measure\.r\(\)\)', cmd)
        if match:
            ch = match.group(1)
            return self._simulate_measurement(ch, "r")

        # Measure IV: print(smua.measure.iv()) — returns "current\tvoltage"
        match = re.match(r'print\(smu([ab])\.measure\.iv\(\)\)', cmd)
        if match:
            ch = match.group(1)
            i_str = self._simulate_measurement(ch, "i")
            v_str = self._simulate_measurement(ch, "v")
            return f"{i_str}\t{v_str}"

        # Source queries: print(smua.source.levelv)
        match = re.match(r'print\(smu([ab])\.source\.levelv\)', cmd)
        if match:
            return str(self._channels[match.group(1)].source_value)

        match = re.match(r'print\(smu([ab])\.source\.leveli\)', cmd)
        if match:
            return str(self._channels[match.group(1)].source_value)

        # Output state query: print(smua.source.output)
        match = re.match(r'print\(smu([ab])\.source\.output\)', cmd)
        if match:
            return "1" if self._channels[match.group(1)].output_enabled else "0"

        # Error queue: print(errorqueue.next())
        if "errorqueue" in cmd:
            return "0\tQueue Is Empty\t0\t0"

        return "0"

    def _simulate_measurement(self, channel: str, meas_type: str) -> str:
        """Generate realistic simulated measurement for a channel"""
        ch_state = self._channels[channel]
        v = ch_state.source_value
        base_r = self.simulation_resistance
        effective_r = base_r

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
        """
        Reset channel(s) to defaults.

        Args:
            channel: 'a', 'b', or None for both
        """
        if channel:
            self._validate_channel(channel)
            self._write(f"{self._smu(channel)}.reset()")
            self._channels[channel] = ChannelState()
        else:
            self._write("smua.reset()")
            self._write("smub.reset()")
            self._channels["a"] = ChannelState()
            self._channels["b"] = ChannelState()
        time.sleep(0.3)
        self._write("errorqueue.clear()")
        logger.info(f"Channel {'both' if not channel else channel} reset to defaults")

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
        Turn output ON for a channel.

        Args:
            channel: 'a' or 'b'

        Returns:
            True if output was enabled successfully
        """
        self._check_connected()
        self._validate_channel(channel)
        ch_state = self._ch(channel)
        smu = self._smu(channel)

        # Safety check: verify source value is within limits before enabling
        if ch_state.source_function == SourceFunction.VOLTAGE:
            if not (self.safety_limits.min_voltage <= ch_state.source_value <= self.safety_limits.max_voltage):
                raise Keithley2602BError(
                    f"Cannot enable output on channel {channel}: source voltage {ch_state.source_value}V "
                    f"outside safety limits [{self.safety_limits.min_voltage}, {self.safety_limits.max_voltage}]V"
                )
        else:
            if not (self.safety_limits.min_current <= ch_state.source_value <= self.safety_limits.max_current):
                raise Keithley2602BError(
                    f"Cannot enable output on channel {channel}: source current {ch_state.source_value}A "
                    f"outside safety limits [{self.safety_limits.min_current}, {self.safety_limits.max_current}]A"
                )

        self._write(f"{smu}.source.output = {smu}.OUTPUT_ON")
        ch_state.output_enabled = True
        logger.info(f"Channel {channel} output ENABLED")
        return True

    def output_off(self, channel: str = "a"):
        """Turn output OFF for a channel (safe operation)"""
        self._validate_channel(channel)
        smu = self._smu(channel)
        try:
            self._write(f"{smu}.source.output = {smu}.OUTPUT_OFF")
        except:
            pass  # Always try to turn off, even if there's an error
        self._channels[channel].output_enabled = False
        logger.info(f"Channel {channel} output DISABLED")

    def output_enabled(self, channel: str = "a") -> bool:
        """Check if output is enabled for a channel"""
        return self._ch(channel).output_enabled

    def get_output_state(self, channel: str = "a") -> bool:
        """Query actual output state from instrument"""
        self._validate_channel(channel)
        if self.simulate:
            return self._channels[channel].output_enabled
        response = self._query(f"print({self._smu(channel)}.source.output)")
        return response.strip() == "1"

    # === SOURCE CONFIGURATION ===

    def set_source_voltage(self, voltage: float, compliance_current: Optional[float] = None,
                           channel: str = "a"):
        """
        Configure voltage source mode for a channel.

        Args:
            voltage: Source voltage in Volts
            compliance_current: Current limit in Amps (uses safety default if None)
            channel: 'a' or 'b'
        """
        self._validate_channel(channel)

        # Safety validation
        if not (self.safety_limits.min_voltage <= voltage <= self.safety_limits.max_voltage):
            raise Keithley2602BError(
                f"Voltage {voltage}V outside safety limits "
                f"[{self.safety_limits.min_voltage}, {self.safety_limits.max_voltage}]V"
            )

        compliance = compliance_current or self.safety_limits.compliance_current
        if abs(compliance) > self.safety_limits.max_current:
            raise Keithley2602BError(
                f"Compliance current {compliance}A exceeds safety limit {self.safety_limits.max_current}A"
            )

        smu = self._smu(channel)
        self._write(f"{smu}.source.func = {smu}.OUTPUT_DCVOLTS")
        self._write(f"{smu}.source.limiti = {compliance}")
        self._write(f"{smu}.source.levelv = {voltage}")

        ch_state = self._ch(channel)
        ch_state.source_function = SourceFunction.VOLTAGE
        ch_state.source_value = voltage
        ch_state.current_compliance = compliance

        logger.info(f"Channel {channel} voltage source configured: {voltage}V, compliance: {compliance}A")

    def set_source_current(self, current: float, compliance_voltage: Optional[float] = None,
                           channel: str = "a"):
        """
        Configure current source mode for a channel.

        Args:
            current: Source current in Amps
            compliance_voltage: Voltage limit in Volts (uses safety default if None)
            channel: 'a' or 'b'
        """
        self._validate_channel(channel)

        # Safety validation
        if not (self.safety_limits.min_current <= current <= self.safety_limits.max_current):
            raise Keithley2602BError(
                f"Current {current}A outside safety limits "
                f"[{self.safety_limits.min_current}, {self.safety_limits.max_current}]A"
            )

        compliance = compliance_voltage or self.safety_limits.compliance_voltage
        if abs(compliance) > self.safety_limits.max_voltage:
            raise Keithley2602BError(
                f"Compliance voltage {compliance}V exceeds safety limit {self.safety_limits.max_voltage}V"
            )

        smu = self._smu(channel)
        self._write(f"{smu}.source.func = {smu}.OUTPUT_DCAMPS")
        self._write(f"{smu}.source.limitv = {compliance}")
        self._write(f"{smu}.source.leveli = {current}")

        ch_state = self._ch(channel)
        ch_state.source_function = SourceFunction.CURRENT
        ch_state.source_value = current
        ch_state.voltage_compliance = compliance

        logger.info(f"Channel {channel} current source configured: {current}A, compliance: {compliance}V")

    def set_voltage(self, voltage: float, channel: str = "a"):
        """
        Set source voltage value with safety validation.
        Use this during sweeps after initial configuration.
        """
        self._validate_channel(channel)

        if not (self.safety_limits.min_voltage <= voltage <= self.safety_limits.max_voltage):
            raise Keithley2602BError(
                f"SAFETY STOP: Voltage {voltage}V outside safety limits "
                f"[{self.safety_limits.min_voltage}, {self.safety_limits.max_voltage}]V"
            )

        # Power check
        ch_state = self._ch(channel)
        potential_power = abs(voltage * ch_state.current_compliance)
        if potential_power > self.safety_limits.power_limit:
            raise Keithley2602BError(
                f"SAFETY STOP: Potential power {potential_power:.2f}W exceeds limit {self.safety_limits.power_limit}W"
            )

        self._write(f"{self._smu(channel)}.source.levelv = {voltage}")
        ch_state.source_value = voltage
        logger.debug(f"Channel {channel} voltage set to: {voltage}V")

    def set_current(self, current: float, channel: str = "a"):
        """
        Set source current value with safety validation.
        Use this during sweeps after initial configuration.
        """
        self._validate_channel(channel)

        if not (self.safety_limits.min_current <= current <= self.safety_limits.max_current):
            raise Keithley2602BError(
                f"SAFETY STOP: Current {current}A outside safety limits "
                f"[{self.safety_limits.min_current}, {self.safety_limits.max_current}]A"
            )

        # Power check
        ch_state = self._ch(channel)
        potential_power = abs(current * ch_state.voltage_compliance)
        if potential_power > self.safety_limits.power_limit:
            raise Keithley2602BError(
                f"SAFETY STOP: Potential power {potential_power:.2f}W exceeds limit {self.safety_limits.power_limit}W"
            )

        self._write(f"{self._smu(channel)}.source.leveli = {current}")
        ch_state.source_value = current
        logger.debug(f"Channel {channel} current set to: {current}A")

    def get_source_value(self, channel: str = "a") -> float:
        """Get current source value for a channel"""
        self._validate_channel(channel)
        ch_state = self._ch(channel)
        smu = self._smu(channel)
        if ch_state.source_function == SourceFunction.VOLTAGE:
            return float(self._query(f"print({smu}.source.levelv)"))
        else:
            return float(self._query(f"print({smu}.source.leveli)"))

    # === MEASUREMENT FUNCTIONS ===

    def set_measure_function(self, function: MeasureFunction, channel: str = "a"):
        """Set the measurement function for a channel"""
        self._validate_channel(channel)
        # TSP doesn't require explicit measure function selection —
        # you call the specific measure method directly. Track for simulation.
        self._ch(channel).measure_function = function.value
        logger.info(f"Channel {channel} measure function set to: {function.name}")

    def set_sense_mode(self, mode: SenseMode, channel: str = "a"):
        """Set 2-wire or 4-wire sensing for a channel"""
        self._validate_channel(channel)
        smu = self._smu(channel)
        tsp_mode = f"{smu}.SENSE_REMOTE" if mode == SenseMode.FOUR_WIRE else f"{smu}.SENSE_LOCAL"
        self._write(f"{smu}.sense = {tsp_mode}")
        self._ch(channel).sense_mode = mode
        logger.info(f"Channel {channel} sense mode set to: {mode.name}")

    def set_output_off_mode(self, mode: OutputOffMode, channel: str = "a"):
        """Set what the output does when turned off: NORMAL, ZERO or HIGH_Z.
        smuX.reset() leaves it at NORMAL."""
        smu = self._smu(channel)
        self._write(f"{smu}.source.offmode = {smu}.{mode.value}")
        logger.info(f"Channel {channel} output off mode set to: {mode.name}")

    def set_auto_zero(self, state: str = "ON", channel: str = "a"):
        """Set auto-zero: "ON" (automatic, the reset default), "OFF" or "ONCE"."""
        smu = self._smu(channel)
        try:
            tsp_state = AUTO_ZERO_STATES[state.upper()]
        except KeyError:
            raise Keithley2602BError(f"Auto zero must be ON, OFF or ONCE, not {state!r}") from None
        self._write(f"{smu}.measure.autozero = {smu}.{tsp_state}")
        logger.info(f"Channel {channel} auto zero set to: {state.upper()}")

    def set_nplc(self, nplc: float, channel: str = "a"):
        """
        Set Number of Power Line Cycles for measurement integration.

        Args:
            nplc: NPLC value (0.001 to 25)
            channel: 'a' or 'b'
        """
        self._validate_channel(channel)
        if not 0.001 <= nplc <= 25:
            raise Keithley2602BError(f"NPLC value {nplc} outside valid range [0.001, 25]")
        smu = self._smu(channel)
        self._write(f"{smu}.measure.nplc = {nplc}")
        logger.info(f"Channel {channel} NPLC set to: {nplc}")

    def set_measure_range(self, range_val: float, measure_type: str = "i", channel: str = "a"):
        """
        Set measurement range.

        Args:
            range_val: Range value (e.g., 0.1 for 100mA range)
            measure_type: 'v' for voltage, 'i' for current
            channel: 'a' or 'b'
        """
        self._validate_channel(channel)
        smu = self._smu(channel)
        self._write(f"{smu}.measure.range{measure_type} = {range_val}")
        logger.info(f"Channel {channel} measure range ({measure_type}) set to: {range_val}")

    def set_measure_range_auto(self, auto: bool = True, measure_type: str = "i", channel: str = "a"):
        """
        Enable/disable auto-range for measurements.

        Args:
            auto: True to enable auto-range
            measure_type: 'v' for voltage, 'i' for current
            channel: 'a' or 'b'
        """
        self._validate_channel(channel)
        smu = self._smu(channel)
        val = f"{smu}.AUTORANGE_ON" if auto else f"{smu}.AUTORANGE_OFF"
        self._write(f"{smu}.measure.autorange{measure_type} = {val}")
        logger.info(f"Channel {channel} auto-range ({measure_type}): {'ON' if auto else 'OFF'}")

    def measure_voltage(self, channel: str = "a") -> float:
        """Measure voltage on a channel"""
        self._validate_channel(channel)
        return float(self._query(f"print({self._smu(channel)}.measure.v())"))

    def measure_current(self, channel: str = "a") -> float:
        """Measure current on a channel"""
        self._validate_channel(channel)
        return float(self._query(f"print({self._smu(channel)}.measure.i())"))

    def measure_resistance(self, channel: str = "a") -> float:
        """Measure resistance on a channel"""
        self._validate_channel(channel)
        return float(self._query(f"print({self._smu(channel)}.measure.r())"))

    def measure_all(self, channel: str = "a") -> MeasurementResult:
        """Measure voltage, current, and calculate resistance on a channel"""
        self._validate_channel(channel)
        smu = self._smu(channel)

        # Use iv() to get both in one call (more efficient)
        response = self._query(f"print({smu}.measure.iv())")
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
            channel=channel,
        )

    # === SWEEP FUNCTIONS ===

    def voltage_sweep(self, start: float, stop: float, points: int,
                      compliance_current: Optional[float] = None,
                      delay: float = 0.05,
                      channel: str = "a") -> List[MeasurementResult]:
        """
        Perform a voltage sweep and measure current on a channel.

        Args:
            start: Starting voltage (V)
            stop: Ending voltage (V)
            points: Number of points in sweep
            compliance_current: Current compliance limit (A)
            delay: Delay between points (s)
            channel: 'a' or 'b'

        Returns:
            List of MeasurementResult objects
        """
        self._validate_channel(channel)

        # Safety validation
        for v in [start, stop]:
            if not (self.safety_limits.min_voltage <= v <= self.safety_limits.max_voltage):
                raise Keithley2602BError(
                    f"Sweep voltage {v}V outside safety limits "
                    f"[{self.safety_limits.min_voltage}, {self.safety_limits.max_voltage}]V"
                )

        if points < 2:
            raise Keithley2602BError("Sweep must have at least 2 points")
        if points > 2500:
            raise Keithley2602BError("Maximum 2500 points in sweep")

        compliance = compliance_current or self.safety_limits.compliance_current

        results = []
        step = (stop - start) / (points - 1)
        smu = self._smu(channel)

        logger.info(f"Starting voltage sweep on channel {channel}: {start}V to {stop}V, {points} points")

        try:
            self.set_source_voltage(start, compliance, channel)

            if not self._channels[channel].output_enabled:
                self.output_on(channel)

            for i in range(points):
                voltage = start + i * step
                self._write(f"{smu}.source.levelv = {voltage}")
                self._channels[channel].source_value = voltage
                time.sleep(delay)

                current = float(self._query(f"print({smu}.measure.i())"))

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
                    channel=channel,
                ))

        except Exception as e:
            logger.error(f"Sweep error on channel {channel}: {e}")
            self.output_off(channel)
            raise

        logger.info(f"Voltage sweep complete on channel {channel}: {len(results)} points")
        return results

    def current_sweep(self, start: float, stop: float, points: int,
                      compliance_voltage: Optional[float] = None,
                      delay: float = 0.05,
                      channel: str = "a") -> List[MeasurementResult]:
        """
        Perform a current sweep and measure voltage on a channel.

        Args:
            start: Starting current (A)
            stop: Ending current (A)
            points: Number of points in sweep
            compliance_voltage: Voltage compliance limit (V)
            delay: Delay between points (s)
            channel: 'a' or 'b'

        Returns:
            List of MeasurementResult objects
        """
        self._validate_channel(channel)

        # Safety validation
        for i in [start, stop]:
            if not (self.safety_limits.min_current <= i <= self.safety_limits.max_current):
                raise Keithley2602BError(
                    f"Sweep current {i}A outside safety limits "
                    f"[{self.safety_limits.min_current}, {self.safety_limits.max_current}]A"
                )

        if points < 2:
            raise Keithley2602BError("Sweep must have at least 2 points")
        if points > 2500:
            raise Keithley2602BError("Maximum 2500 points in sweep")

        compliance = compliance_voltage or self.safety_limits.compliance_voltage

        results = []
        step = (stop - start) / (points - 1)
        smu = self._smu(channel)

        logger.info(f"Starting current sweep on channel {channel}: {start}A to {stop}A, {points} points")

        try:
            self.set_source_current(start, compliance, channel)

            if not self._channels[channel].output_enabled:
                self.output_on(channel)

            for i in range(points):
                current = start + i * step
                self._write(f"{smu}.source.leveli = {current}")
                self._channels[channel].source_value = current
                time.sleep(delay)

                voltage = float(self._query(f"print({smu}.measure.v())"))

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
                    channel=channel,
                ))

        except Exception as e:
            logger.error(f"Sweep error on channel {channel}: {e}")
            self.output_off(channel)
            raise

        logger.info(f"Current sweep complete on channel {channel}: {len(results)} points")
        return results

    # === UTILITY FUNCTIONS ===

    def beep(self, frequency: int = 2000, duration: float = 0.1):
        """Make the instrument beep"""
        self._write(f"beeper.beep({duration}, {frequency})")

    def local_mode(self):
        """Return to local (front panel) control"""
        self._write("display.clear()")
        # TSP: exit remote mode
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
    for inst in Keithley2602B.list_available_instruments():
        print(f"  {inst}")

    print("\nLooking for Keithley 2602B...")
    k2602b_list = Keithley2602B.find_keithley_2602b()
    if k2602b_list:
        print(f"Found: {k2602b_list}")
    else:
        print("No Keithley 2602B found. Running in simulation mode...")

        with Keithley2602B(simulate=True) as smu:
            smu.connect()
            print(f"ID: {smu.get_identification()}")

            # Test channel A
            print("\n--- Channel A ---")
            smu.set_source_voltage(1.0, compliance_current=0.01, channel="a")
            smu.output_on("a")
            result = smu.measure_all("a")
            print(f"V={result.voltage:.6f} V, I={result.current:.9f} A, R={result.resistance:.1f} Ω")
            smu.output_off("a")

            # Test channel B
            print("\n--- Channel B ---")
            smu.set_source_voltage(2.0, compliance_current=0.01, channel="b")
            smu.output_on("b")
            result = smu.measure_all("b")
            print(f"V={result.voltage:.6f} V, I={result.current:.9f} A, R={result.resistance:.1f} Ω")
            smu.output_off("b")

            # Quick sweep on channel A
            print("\n--- Voltage Sweep (Channel A) ---")
            results = smu.voltage_sweep(0, 5, 6, compliance_current=0.1, delay=0.01, channel="a")
            for r in results:
                print(f"  V={r.voltage:.2f}V, I={r.current:.6f}A")
            smu.output_off("a")

            print("\nAll tests passed!")


if __name__ == "__main__":
    quick_test()
