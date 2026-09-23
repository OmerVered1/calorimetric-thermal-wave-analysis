"""
Keithley 6430 Sub-Femtoamp Remote SourceMeter Driver
=====================================================
Safe, robust driver for controlling the Keithley 6430 via RS-232 (serial).
Includes auto-detection of COM port and baud rate, comprehensive safety
features, and sub-femtoamp current measurement support.

The Keithley 6430 communicates via RS-232 using SCPI commands.
It connects to the PC through a USB-to-RS232 adapter.

Author: Omer Vered / Control Program
Date: 2026
"""

import serial
import serial.tools.list_ports
import time
import logging
import re
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SourceFunction(Enum):
    """Source function modes"""
    VOLTAGE = "VOLT"
    CURRENT = "CURR"


class MeasureFunction(Enum):
    """Measurement function modes"""
    VOLTAGE = "VOLT"
    CURRENT = "CURR"
    RESISTANCE = "RES"


class SenseMode(Enum):
    """Sense mode (2-wire or 4-wire)"""
    TWO_WIRE = "OFF"
    FOUR_WIRE = "ON"


class OutputOffMode(Enum):
    """Output off state behavior"""
    NORMAL = "NORM"
    ZERO = "ZERO"
    HIGH_Z = "HIMP"
    GUARD = "GUAR"


@dataclass
class SafetyLimits:
    """Safety limits for Keithley 6430 operation"""
    max_voltage: float = 105.0       # Maximum voltage limit (V) - 6430 max is 105V
    max_current: float = 0.105       # Maximum current limit (A) - 6430 max is 105mA
    min_voltage: float = -105.0      # Minimum voltage limit (V)
    min_current: float = -0.105      # Minimum current limit (A)
    compliance_voltage: float = 105.0  # Default voltage compliance (V)
    compliance_current: float = 0.105  # Default current compliance (A)
    power_limit: float = 11.0         # Maximum power (W) - 6430 max is ~11W


@dataclass
class MeasurementResult:
    """Container for measurement results"""
    voltage: float
    current: float
    resistance: Optional[float] = None
    timestamp: Optional[float] = None
    source_value: Optional[float] = None
    source_function: Optional[str] = None


class Keithley6430Error(Exception):
    """Custom exception for Keithley 6430 errors"""
    pass


class Keithley6430:
    """
    Keithley 6430 Sub-Femtoamp Remote SourceMeter Driver

    Features:
    - RS-232 communication via USB-to-serial adapter
    - Auto-detection of COM port and baud rate
    - Sub-femtoamp current measurement (down to 0.4 fA with remote preamp)
    - Safe operation with configurable limits
    - Source voltage/current with compliance protection
    - Measure voltage, current, resistance
    - IV sweep measurements
    - Guard mode support
    - Built-in safety checks and error handling
    """

    # Instrument absolute limits (do not exceed)
    ABSOLUTE_MAX_VOLTAGE = 110.0   # V (with some headroom for compliance)
    ABSOLUTE_MAX_CURRENT = 0.105   # A (105 mA)
    ABSOLUTE_MAX_POWER = 11.55     # W

    # Common baud rates to try during auto-detection
    BAUD_RATES = [9600, 19200, 57600, 38400, 4800, 2400, 1200, 600, 300]

    # Current measurement ranges (ascending)
    CURRENT_RANGES = [
        (100e-15, "100 fA"),
        (1e-12,   "1 pA"),
        (10e-12,  "10 pA"),
        (100e-12, "100 pA"),
        (1e-9,    "1 nA"),
        (10e-9,   "10 nA"),
        (100e-9,  "100 nA"),
        (1e-6,    "1 µA"),
        (10e-6,   "10 µA"),
        (100e-6,  "100 µA"),
        (1e-3,    "1 mA"),
        (10e-3,   "10 mA"),
        (100e-3,  "100 mA"),
    ]

    # Voltage measurement ranges
    VOLTAGE_RANGES = [
        (0.2,   "200 mV"),
        (2.0,   "2 V"),
        (20.0,  "20 V"),
        (200.0, "200 V"),
    ]

    def __init__(self, port: Optional[str] = None,
                 baud_rate: int = 9600,
                 safety_limits: Optional[SafetyLimits] = None,
                 simulate: bool = False,
                 simulation_resistance: float = 1e9):
        """
        Initialize Keithley 6430 driver.

        Args:
            port: COM port (e.g., "COM3"). If None, auto-detection is used.
            baud_rate: RS-232 baud rate (default 9600)
            safety_limits: Custom safety limits (uses defaults if None)
            simulate: If True, run in simulation mode without real hardware
            simulation_resistance: Resistance value (ohms) for simulation
                                   (default 1 GΩ for sub-femtoamp testing)
        """
        self.port = port
        self.baud_rate = baud_rate
        self.safety_limits = safety_limits or SafetyLimits()
        self.simulate = simulate
        self.simulation_resistance = simulation_resistance
        self._serial: Optional[serial.Serial] = None
        self._connected = False
        self._output_enabled = False
        self._source_function = SourceFunction.VOLTAGE
        self._source_value = 0.0
        self._sense_function = 'CURR'
        self._current_compliance = self.safety_limits.compliance_current
        self._voltage_compliance = self.safety_limits.compliance_voltage

        # Validate safety limits against absolute limits
        self._validate_safety_limits()

    def _validate_safety_limits(self):
        """Validate that safety limits don't exceed instrument absolute limits"""
        if abs(self.safety_limits.max_voltage) > self.ABSOLUTE_MAX_VOLTAGE:
            raise Keithley6430Error(
                f"Safety voltage limit {self.safety_limits.max_voltage}V exceeds "
                f"instrument maximum {self.ABSOLUTE_MAX_VOLTAGE}V"
            )
        if abs(self.safety_limits.max_current) > self.ABSOLUTE_MAX_CURRENT:
            raise Keithley6430Error(
                f"Safety current limit {self.safety_limits.max_current}A exceeds "
                f"instrument maximum {self.ABSOLUTE_MAX_CURRENT}A"
            )

    @staticmethod
    def list_serial_ports() -> List[Dict[str, str]]:
        """
        List all available serial (COM) ports on the system.

        Returns:
            List of dicts with 'port', 'description', 'hwid' keys
        """
        ports = []
        for p in serial.tools.list_ports.comports():
            ports.append({
                'port': p.device,
                'description': p.description,
                'hwid': p.hwid
            })
            logger.info(f"Found port: {p.device} - {p.description}")
        return ports

    @staticmethod
    def auto_detect(timeout: float = 2.0) -> Optional[Tuple[str, int]]:
        """
        Auto-detect a Keithley 6430 on available COM ports.
        Tries all COM ports with common baud rates.

        Args:
            timeout: Timeout in seconds for each attempt

        Returns:
            Tuple of (port, baud_rate) if found, None otherwise
        """
        ports = serial.tools.list_ports.comports()
        if not ports:
            logger.warning("No serial ports found")
            return None

        logger.info(f"Scanning {len(ports)} serial ports for Keithley 6430...")

        for port_info in ports:
            port = port_info.device
            for baud in Keithley6430.BAUD_RATES:
                try:
                    logger.debug(f"Trying {port} at {baud} baud...")
                    ser = serial.Serial(
                        port=port,
                        baudrate=baud,
                        bytesize=serial.EIGHTBITS,
                        parity=serial.PARITY_NONE,
                        stopbits=serial.STOPBITS_ONE,
                        timeout=timeout,
                        xonxoff=False,
                        rtscts=False,
                        dsrdtr=False
                    )

                    # Flush any stale data
                    ser.reset_input_buffer()
                    ser.reset_output_buffer()
                    time.sleep(0.1)

                    # Send IDN query
                    ser.write(b"*IDN?\r\n")
                    time.sleep(0.5)

                    # Read response
                    response = ser.readline().decode('ascii', errors='ignore').strip()

                    ser.close()

                    if response and ("6430" in response or "KEITHLEY" in response.upper()):
                        logger.info(f"Found Keithley 6430 on {port} at {baud} baud: {response}")
                        return (port, baud)

                except (serial.SerialException, OSError, UnicodeDecodeError) as e:
                    logger.debug(f"Failed {port} at {baud}: {e}")
                    try:
                        ser.close()
                    except:
                        pass
                    continue

        logger.warning("Keithley 6430 not found on any serial port")
        return None

    def connect(self, port: Optional[str] = None, baud_rate: Optional[int] = None) -> bool:
        """
        Connect to the Keithley 6430 via RS-232.

        Args:
            port: COM port (e.g., "COM3"). Uses stored port or auto-detects if None.
            baud_rate: Baud rate. Uses stored value if None.

        Returns:
            True if connection successful
        """
        if self.simulate:
            logger.info("Running in SIMULATION mode - no hardware connected")
            self._connected = True
            return True

        if port:
            self.port = port
        if baud_rate:
            self.baud_rate = baud_rate

        # Auto-detect if no port specified
        if not self.port:
            logger.info("No port specified, attempting auto-detection...")
            result = self.auto_detect()
            if result:
                self.port, self.baud_rate = result
            else:
                raise Keithley6430Error(
                    "Could not auto-detect Keithley 6430. "
                    "Please specify the COM port manually."
                )

        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baud_rate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=5.0,
                write_timeout=5.0,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False
            )

            # Flush any stale data
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()
            time.sleep(0.3)

            # Verify it's a Keithley 6430
            self._serial.write(b"*IDN?\r\n")
            time.sleep(0.5)
            idn = self._serial.readline().decode('ascii', errors='ignore').strip()

            if not idn:
                self._serial.close()
                raise Keithley6430Error(
                    f"No response from device on {self.port} at {self.baud_rate} baud. "
                    "Check cable, baud rate, and that the instrument is powered on."
                )

            if "6430" not in idn and "KEITHLEY" not in idn.upper():
                self._serial.close()
                raise Keithley6430Error(
                    f"Connected device is not a Keithley 6430: {idn}"
                )

            logger.info(f"Connected to: {idn}")
            self._connected = True

            # Initialize to safe state
            self._initialize_safe_state()

            return True

        except serial.SerialException as e:
            logger.error(f"Serial connection failed: {e}")
            self._connected = False
            raise Keithley6430Error(f"Failed to connect to {self.port}: {e}")

    def disconnect(self):
        """Safely disconnect from the instrument"""
        try:
            if self._connected and not self.simulate:
                # Turn off output before disconnecting
                self.output_off()
                # Return to local mode
                try:
                    self._write(":SYST:LOC")
                except:
                    pass

            if self._serial and self._serial.is_open:
                self._serial.close()

        except Exception as e:
            logger.warning(f"Error during disconnect: {e}")
        finally:
            self._serial = None
            self._connected = False
            self._output_enabled = False

    def _initialize_safe_state(self):
        """Initialize instrument to a safe state"""
        if self.simulate:
            return

        try:
            # Turn off output
            self._write(":OUTP OFF")
            self._output_enabled = False

            # Reset to defaults
            self._write("*RST")
            time.sleep(1.0)  # 6430 can be slow to reset

            # Clear error queue
            self._write("*CLS")
            time.sleep(0.2)

            # Set to voltage source mode with 0V
            self._write(":SOUR:FUNC VOLT")
            self._write(":SOUR:VOLT:LEV 0")

            # Set default compliance
            self._write(f":SENS:CURR:PROT {self.safety_limits.compliance_current}")

            # Configure data format to return single reading
            self._write(":FORM:ELEM CURR")

            # Set remote sense off (2-wire) by default
            self._write(":SYST:RSEN OFF")

            # Auto zero on
            self._write(":SYST:AZER ON")

            logger.info("Instrument initialized to safe state")

        except Exception as e:
            logger.error(f"Failed to initialize safe state: {e}")
            raise

    def _check_connected(self):
        """Check if connected, raise error if not"""
        if not self._connected:
            raise Keithley6430Error("Not connected to instrument")

    def _write(self, command: str):
        """Write command to instrument with logging"""
        if self.simulate:
            logger.debug(f"SIM WRITE: {command}")
            self._simulate_write(command)
            return
        self._check_connected()
        logger.debug(f"WRITE: {command}")
        self._serial.write(f"{command}\r\n".encode('ascii'))
        time.sleep(0.05)  # Small delay for RS-232

    def _simulate_write(self, command: str):
        """Parse and track simulation state from write commands"""
        cmd_upper = command.upper()

        # Track source voltage value
        if 'SOUR:VOLT' in cmd_upper and '?' not in cmd_upper:
            match = re.search(r'SOUR:VOLT(?::LEV)?\s+([\-\d\.eE\+]+)', command, re.IGNORECASE)
            if match:
                self._source_value = float(match.group(1))
                self._source_function = SourceFunction.VOLTAGE
                logger.debug(f"SIM: Source voltage set to {self._source_value}")

        # Track source current value
        elif 'SOUR:CURR' in cmd_upper and '?' not in cmd_upper:
            match = re.search(r'SOUR:CURR(?::LEV)?\s+([\-\d\.eE\+]+)', command, re.IGNORECASE)
            if match:
                self._source_value = float(match.group(1))
                self._source_function = SourceFunction.CURRENT
                logger.debug(f"SIM: Source current set to {self._source_value}")

        # Track sense function
        elif 'SENS:FUNC' in cmd_upper:
            if 'VOLT' in cmd_upper:
                self._sense_function = 'VOLT'
            elif 'CURR' in cmd_upper:
                self._sense_function = 'CURR'

        # Track format element
        elif 'FORM:ELEM' in cmd_upper:
            if 'VOLT' in cmd_upper:
                self._sense_function = 'VOLT'
            elif 'CURR' in cmd_upper:
                self._sense_function = 'CURR'

        # Track output state
        elif 'OUTP ON' in cmd_upper or 'OUTP 1' in cmd_upper:
            self._output_enabled = True
        elif 'OUTP OFF' in cmd_upper or 'OUTP 0' in cmd_upper:
            self._output_enabled = False

    def _query(self, command: str) -> str:
        """Query instrument with logging"""
        if self.simulate:
            logger.debug(f"SIM QUERY: {command}")
            return self._simulate_query(command)
        self._check_connected()
        logger.debug(f"QUERY: {command}")

        # Flush input buffer before query
        self._serial.reset_input_buffer()
        self._serial.write(f"{command}\r\n".encode('ascii'))
        time.sleep(0.1)

        response = self._serial.readline().decode('ascii', errors='ignore').strip()
        logger.debug(f"RESPONSE: {response}")

        if not response:
            # Retry once
            time.sleep(0.3)
            response = self._serial.readline().decode('ascii', errors='ignore').strip()
            if not response:
                logger.warning(f"No response to query: {command}")

        return response

    def _simulate_query(self, command: str) -> str:
        """Return simulated responses for sub-femtoamp testing"""
        import random

        if "*IDN?" in command:
            return (f"KEITHLEY INSTRUMENTS INC.,MODEL 6430,"
                    f"1234567,C34 (SIM R={self.simulation_resistance:.0e}Ω)")

        elif "READ?" in command or "MEAS?" in command or "FETC?" in command:
            sense_func = getattr(self, '_sense_function', 'CURR')

            if self._source_function == SourceFunction.VOLTAGE:
                v = self._source_value
                R = self.simulation_resistance

                if sense_func == 'CURR':
                    # I = V/R with sub-femtoamp noise
                    if abs(v) > 1e-9:
                        current = v / R
                        # Add realistic noise for sub-femtoamp measurements
                        noise_floor = 0.4e-15  # 0.4 fA noise floor
                        noise = random.gauss(0, noise_floor + abs(current) * 0.001)
                        current += noise
                    else:
                        current = random.gauss(0, 0.4e-15)  # Sub-fA noise
                    return f"{current:.15e}"
                else:
                    noise = random.gauss(0, abs(v) * 0.0001 + 1e-6)
                    return f"{v + noise:.9e}"
            else:
                i = self._source_value
                R = self.simulation_resistance

                if sense_func == 'VOLT':
                    voltage = i * R
                    noise = random.gauss(0, abs(voltage) * 0.001 + 1e-6)
                    return f"{voltage + noise:.9e}"
                else:
                    noise = random.gauss(0, abs(i) * 0.0001 + 0.4e-15)
                    return f"{i + noise:.15e}"

        elif "SOUR:VOLT?" in command or "SOUR:VOLT:LEV?" in command:
            return str(self._source_value)
        elif "SOUR:CURR?" in command or "SOUR:CURR:LEV?" in command:
            return str(self._source_value)
        elif "OUTP?" in command:
            return "1" if self._output_enabled else "0"
        elif "SYST:ERR?" in command:
            return '+0,"No error"'
        return "0"

    def get_identification(self) -> str:
        """Get instrument identification string"""
        return self._query("*IDN?")

    def reset(self):
        """Reset instrument to defaults"""
        self._write("*RST")
        time.sleep(1.0)
        self._write("*CLS")
        self._output_enabled = False
        self._source_function = SourceFunction.VOLTAGE
        self._source_value = 0.0
        self._sense_function = 'CURR'
        logger.info("Instrument reset to defaults")

    def clear_errors(self):
        """Clear error queue"""
        self._write("*CLS")

    def get_errors(self) -> List[str]:
        """Get all errors from error queue"""
        if self.simulate:
            return []
        errors = []
        for _ in range(10):  # Max 10 errors to prevent infinite loop
            error = self._query(":SYST:ERR?")
            if not error or error.startswith("+0,") or error.startswith("0,"):
                break
            errors.append(error)
        return errors

    # === OUTPUT CONTROL ===

    def output_on(self) -> bool:
        """
        Turn output ON.

        Returns:
            True if output was enabled successfully
        """
        self._check_connected()

        # Safety check
        if self._source_function == SourceFunction.VOLTAGE:
            if not (self.safety_limits.min_voltage <= self._source_value <= self.safety_limits.max_voltage):
                raise Keithley6430Error(
                    f"Cannot enable output: source voltage {self._source_value}V "
                    f"outside safety limits [{self.safety_limits.min_voltage}, {self.safety_limits.max_voltage}]V"
                )
        else:
            if not (self.safety_limits.min_current <= self._source_value <= self.safety_limits.max_current):
                raise Keithley6430Error(
                    f"Cannot enable output: source current {self._source_value}A "
                    f"outside safety limits [{self.safety_limits.min_current}, {self.safety_limits.max_current}]A"
                )

        self._write(":OUTP ON")
        self._output_enabled = True
        logger.info("Output ENABLED")
        return True

    def output_off(self):
        """Turn output OFF (safe operation)"""
        try:
            self._write(":OUTP OFF")
        except:
            pass
        self._output_enabled = False
        logger.info("Output DISABLED")

    @property
    def output_enabled(self) -> bool:
        """Check if output is enabled"""
        return self._output_enabled

    def get_output_state(self) -> bool:
        """Query actual output state from instrument"""
        if self.simulate:
            return self._output_enabled
        response = self._query(":OUTP?")
        return response == "1" or response.upper() == "ON"

    def set_output_off_mode(self, mode: OutputOffMode):
        """
        Set the output off state behavior.

        Args:
            mode: OutputOffMode enum (NORMAL, ZERO, HIGH_Z, GUARD)
        """
        self._write(f":OUTP:SMOD {mode.value}")
        logger.info(f"Output off mode set to: {mode.name}")

    # === SOURCE CONFIGURATION ===

    def set_source_voltage(self, voltage: float, compliance_current: Optional[float] = None):
        """
        Configure voltage source mode.

        Args:
            voltage: Source voltage in Volts (±105V max)
            compliance_current: Current limit in Amps (uses safety default if None)
        """
        if not (self.safety_limits.min_voltage <= voltage <= self.safety_limits.max_voltage):
            raise Keithley6430Error(
                f"Voltage {voltage}V outside safety limits "
                f"[{self.safety_limits.min_voltage}, {self.safety_limits.max_voltage}]V"
            )

        compliance = compliance_current or self.safety_limits.compliance_current
        if abs(compliance) > self.safety_limits.max_current:
            raise Keithley6430Error(
                f"Compliance current {compliance}A exceeds safety limit {self.safety_limits.max_current}A"
            )

        self._write(":SOUR:FUNC VOLT")
        self._write(f":SOUR:VOLT:LEV {voltage}")
        # 6430 uses :SENS:CURR:PROT for current compliance
        self._write(f":SENS:CURR:PROT {compliance}")

        self._source_function = SourceFunction.VOLTAGE
        self._source_value = voltage
        self._current_compliance = compliance

        logger.info(f"Voltage source configured: {voltage}V, compliance: {compliance}A")

    def set_source_current(self, current: float, compliance_voltage: Optional[float] = None):
        """
        Configure current source mode.

        Args:
            current: Source current in Amps (±105mA max)
            compliance_voltage: Voltage limit in Volts (uses safety default if None)
        """
        if not (self.safety_limits.min_current <= current <= self.safety_limits.max_current):
            raise Keithley6430Error(
                f"Current {current}A outside safety limits "
                f"[{self.safety_limits.min_current}, {self.safety_limits.max_current}]A"
            )

        compliance = compliance_voltage or self.safety_limits.compliance_voltage
        if abs(compliance) > self.safety_limits.max_voltage:
            raise Keithley6430Error(
                f"Compliance voltage {compliance}V exceeds safety limit {self.safety_limits.max_voltage}V"
            )

        self._write(":SOUR:FUNC CURR")
        self._write(f":SOUR:CURR:LEV {current}")
        # 6430 uses :SENS:VOLT:PROT for voltage compliance
        self._write(f":SENS:VOLT:PROT {compliance}")

        self._source_function = SourceFunction.CURRENT
        self._source_value = current
        self._voltage_compliance = compliance

        logger.info(f"Current source configured: {current}A, compliance: {compliance}V")

    def set_voltage(self, voltage: float):
        """
        Set source voltage value with safety validation.
        Use during sweeps after initial configuration.
        """
        if not (self.safety_limits.min_voltage <= voltage <= self.safety_limits.max_voltage):
            raise Keithley6430Error(
                f"SAFETY STOP: Voltage {voltage}V outside safety limits "
                f"[{self.safety_limits.min_voltage}, {self.safety_limits.max_voltage}]V"
            )

        if hasattr(self, '_current_compliance'):
            potential_power = abs(voltage * self._current_compliance)
            if potential_power > self.safety_limits.power_limit:
                raise Keithley6430Error(
                    f"SAFETY STOP: Potential power {potential_power:.2f}W exceeds limit "
                    f"{self.safety_limits.power_limit}W"
                )

        self._write(f":SOUR:VOLT:LEV {voltage}")
        self._source_value = voltage

    def set_current(self, current: float):
        """
        Set source current value with safety validation.
        Use during sweeps after initial configuration.
        """
        if not (self.safety_limits.min_current <= current <= self.safety_limits.max_current):
            raise Keithley6430Error(
                f"SAFETY STOP: Current {current}A outside safety limits "
                f"[{self.safety_limits.min_current}, {self.safety_limits.max_current}]A"
            )

        if hasattr(self, '_voltage_compliance'):
            potential_power = abs(current * self._voltage_compliance)
            if potential_power > self.safety_limits.power_limit:
                raise Keithley6430Error(
                    f"SAFETY STOP: Potential power {potential_power:.2f}W exceeds limit "
                    f"{self.safety_limits.power_limit}W"
                )

        self._write(f":SOUR:CURR:LEV {current}")
        self._source_value = current

    def get_source_value(self) -> float:
        """Get current source value"""
        if self._source_function == SourceFunction.VOLTAGE:
            return float(self._query(":SOUR:VOLT:LEV?"))
        else:
            return float(self._query(":SOUR:CURR:LEV?"))

    def set_source_range(self, range_value: float):
        """Set source range"""
        if self._source_function == SourceFunction.VOLTAGE:
            self._write(f":SOUR:VOLT:RANG {range_value}")
        else:
            self._write(f":SOUR:CURR:RANG {range_value}")

    def set_source_range_auto(self, auto: bool = True):
        """Enable/disable source auto-ranging"""
        state = "ON" if auto else "OFF"
        if self._source_function == SourceFunction.VOLTAGE:
            self._write(f":SOUR:VOLT:RANG:AUTO {state}")
        else:
            self._write(f":SOUR:CURR:RANG:AUTO {state}")

    # === MEASUREMENT FUNCTIONS ===

    def set_measure_function(self, function: MeasureFunction):
        """Set the measurement function"""
        # 6430 uses double-quoted function names
        self._write(f':SENS:FUNC "{function.value}"')
        self._sense_function = function.value
        logger.info(f"Measure function set to: {function.name}")

    def set_sense_mode(self, mode: SenseMode):
        """Set 2-wire or 4-wire sensing"""
        self._write(f":SYST:RSEN {mode.value}")
        logger.info(f"Sense mode set to: {'4-Wire' if mode == SenseMode.FOUR_WIRE else '2-Wire'}")

    def set_remote_sense(self, four_wire: bool):
        """4-wire sensing. The 6430 has one system-wide setting, so this is
        set_sense_mode under the common interface's name."""
        self.set_sense_mode(SenseMode.FOUR_WIRE if four_wire else SenseMode.TWO_WIRE)

    def set_measure_range(self, function: MeasureFunction, range_value: float):
        """Set measurement range"""
        self._write(f":SENS:{function.value}:RANG {range_value}")

    def set_measure_range_auto(self, function: MeasureFunction, auto: bool = True):
        """Enable/disable measurement auto-ranging"""
        state = "ON" if auto else "OFF"
        self._write(f":SENS:{function.value}:RANG:AUTO {state}")

    def set_nplc(self, nplc: float, function: Optional[MeasureFunction] = None):
        """
        Set integration time in Number of Power Line Cycles (NPLC).
        Higher NPLC = less noise but slower measurements.

        Args:
            nplc: NPLC value (0.01 to 10)
            function: Which function (CURR/VOLT). If None, sets for current.
        """
        if function:
            self._write(f":SENS:{function.value}:NPLC {nplc}")
        else:
            self._write(f":SENS:CURR:NPLC {nplc}")
            self._write(f":SENS:VOLT:NPLC {nplc}")

    def set_auto_zero(self, state: str = "ON"):
        """
        Set auto-zero mode.

        Args:
            state: "ON", "OFF", or "ONCE"
        """
        self._write(f":SYST:AZER {state}")

    def measure_voltage(self) -> float:
        """Measure voltage"""
        self._write(":FORM:ELEM VOLT")
        self._sense_function = 'VOLT'
        return float(self._query(":READ?"))

    def measure_current(self) -> float:
        """Measure current (sub-femtoamp capable)"""
        self._write(":FORM:ELEM CURR")
        self._sense_function = 'CURR'
        return float(self._query(":READ?"))

    def measure_resistance(self) -> float:
        """Measure resistance"""
        self._write(":FORM:ELEM RES")
        self._sense_function = 'RES'
        return float(self._query(":READ?"))

    def measure_all(self) -> MeasurementResult:
        """Measure voltage, current, and calculate resistance"""
        voltage = self.measure_voltage()
        current = self.measure_current()

        resistance = None
        if abs(current) > 1e-18:  # Sub-femtoamp threshold
            resistance = voltage / current

        return MeasurementResult(
            voltage=voltage,
            current=current,
            resistance=resistance,
            timestamp=time.time(),
            source_value=self._source_value,
            source_function=self._source_function.name
        )

    def read_single(self) -> float:
        """Take a single reading with current format settings"""
        return float(self._query(":READ?"))

    # === SWEEP FUNCTIONS ===

    def voltage_sweep(self, start: float, stop: float, points: int,
                      compliance_current: Optional[float] = None,
                      delay: float = 0.1) -> List[MeasurementResult]:
        """
        Perform a voltage sweep and measure current.
        Optimal for sub-femtoamp current measurements.

        Args:
            start: Starting voltage (V)
            stop: Ending voltage (V)
            points: Number of points in sweep
            compliance_current: Current compliance limit (A)
            delay: Delay between points (s) - longer delays for low-current

        Returns:
            List of MeasurementResult objects
        """
        for v in [start, stop]:
            if not (self.safety_limits.min_voltage <= v <= self.safety_limits.max_voltage):
                raise Keithley6430Error(
                    f"Sweep voltage {v}V outside safety limits "
                    f"[{self.safety_limits.min_voltage}, {self.safety_limits.max_voltage}]V"
                )

        if points < 2:
            raise Keithley6430Error("Sweep must have at least 2 points")
        if points > 2500:
            raise Keithley6430Error("Maximum 2500 points in sweep")

        compliance = compliance_current or self.safety_limits.compliance_current

        results = []
        step = (stop - start) / (points - 1)

        logger.info(f"Starting voltage sweep: {start}V to {stop}V, {points} points")

        try:
            self.set_source_voltage(start, compliance)
            self._write(":FORM:ELEM CURR")
            self._sense_function = 'CURR'

            if not self._output_enabled:
                self.output_on()

            for i in range(points):
                voltage = start + i * step
                self._write(f":SOUR:VOLT:LEV {voltage}")
                self._source_value = voltage
                time.sleep(delay)

                current = float(self._query(":READ?"))

                resistance = None
                if abs(current) > 1e-18:
                    resistance = voltage / current

                results.append(MeasurementResult(
                    voltage=voltage,
                    current=current,
                    resistance=resistance,
                    timestamp=time.time(),
                    source_value=voltage,
                    source_function="VOLTAGE"
                ))

        except Exception as e:
            logger.error(f"Sweep error: {e}")
            self.output_off()
            raise

        logger.info(f"Voltage sweep complete: {len(results)} points")
        return results

    def current_sweep(self, start: float, stop: float, points: int,
                      compliance_voltage: Optional[float] = None,
                      delay: float = 0.1) -> List[MeasurementResult]:
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
        for c in [start, stop]:
            if not (self.safety_limits.min_current <= c <= self.safety_limits.max_current):
                raise Keithley6430Error(
                    f"Sweep current {c}A outside safety limits "
                    f"[{self.safety_limits.min_current}, {self.safety_limits.max_current}]A"
                )

        if points < 2:
            raise Keithley6430Error("Sweep must have at least 2 points")
        if points > 2500:
            raise Keithley6430Error("Maximum 2500 points in sweep")

        compliance = compliance_voltage or self.safety_limits.compliance_voltage

        results = []
        step = (stop - start) / (points - 1)

        logger.info(f"Starting current sweep: {start}A to {stop}A, {points} points")

        try:
            self.set_source_current(start, compliance)
            self._write(":FORM:ELEM VOLT")
            self._sense_function = 'VOLT'

            if not self._output_enabled:
                self.output_on()

            for i in range(points):
                current = start + i * step
                self._write(f":SOUR:CURR:LEV {current}")
                self._source_value = current
                time.sleep(delay)

                voltage = float(self._query(":READ?"))

                resistance = None
                if abs(current) > 1e-18:
                    resistance = voltage / current

                results.append(MeasurementResult(
                    voltage=voltage,
                    current=current,
                    resistance=resistance,
                    timestamp=time.time(),
                    source_value=current,
                    source_function="CURRENT"
                ))

        except Exception as e:
            logger.error(f"Sweep error: {e}")
            self.output_off()
            raise

        logger.info(f"Current sweep complete: {len(results)} points")
        return results

    # === UTILITY FUNCTIONS ===

    def beep(self, frequency: int = 2000, duration: float = 0.1):
        """Make the instrument beep"""
        self._write(f":SYST:BEEP {frequency}, {duration}")

    def set_guard_mode(self, enabled: bool):
        """
        Enable/disable guard mode for ultra-low current measurements.
        Guard should be connected via triax cable.
        """
        state = "ON" if enabled else "OFF"
        self._write(f":SENS:GUAR {state}")
        logger.info(f"Guard mode: {state}")

    def local_mode(self):
        """Return to local (front panel) control"""
        self._write(":SYST:LOC")

    def remote_mode(self):
        """Set to remote control mode"""
        self._write(":SYST:REM")

    def get_serial_info(self) -> Dict[str, Any]:
        """Get current serial connection info"""
        return {
            'port': self.port,
            'baud_rate': self.baud_rate,
            'connected': self._connected,
            'simulating': self.simulate
        }

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
    print("=== Keithley 6430 Sub-Femtoamp SourceMeter Driver ===\n")

    print("Available serial ports:")
    ports = Keithley6430.list_serial_ports()
    for p in ports:
        print(f"  {p['port']:8s} - {p['description']}")

    print("\nAuto-detecting Keithley 6430...")
    result = Keithley6430.auto_detect(timeout=1.5)

    if result:
        port, baud = result
        print(f"Found on {port} at {baud} baud!")

        with Keithley6430(port=port, baud_rate=baud) as smu:
            smu.connect()
            print(f"ID: {smu.get_identification()}")
            smu.set_source_voltage(1.0, compliance_current=0.001)
            smu.output_on()
            result = smu.measure_all()
            print(f"V={result.voltage:.6f}V, I={result.current:.6e}A")
            smu.output_off()
    else:
        print("Not found. Running simulation (1 GΩ resistance)...\n")

        with Keithley6430(simulate=True, simulation_resistance=1e9) as smu:
            smu.connect()
            print(f"ID: {smu.get_identification()}")
            smu.set_source_voltage(1.0, compliance_current=0.001)
            smu.output_on()
            result = smu.measure_all()
            print(f"V={result.voltage:.6f}V, I={result.current:.6e}A")
            if result.resistance:
                print(f"R={result.resistance:.6e}Ω")
            smu.output_off()
            print("\nSub-femtoamp noise test (0V source):")
            smu.set_source_voltage(0.0)
            smu.output_on()
            for i in range(5):
                current = smu.measure_current()
                print(f"  Reading {i+1}: {current:.4e} A ({current*1e15:.2f} fA)")
            smu.output_off()


if __name__ == "__main__":
    quick_test()
