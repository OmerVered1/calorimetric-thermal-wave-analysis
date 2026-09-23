"""
Keithley 2450 SourceMeter Driver
================================
Safe, robust driver for controlling the Keithley 2450 SMU via PyVISA.
Includes comprehensive safety features to protect the expensive instrument.

Author: Control Program
Date: 2026
"""

import pyvisa
import time
import logging
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
    TWO_WIRE = "2"
    FOUR_WIRE = "4"


@dataclass
class SafetyLimits:
    """Safety limits for instrument operation"""
    max_voltage: float = 200.0     # Maximum voltage limit (V)
    max_current: float = 1.0       # Maximum current limit (A)
    min_voltage: float = -200.0    # Minimum voltage limit (V)
    min_current: float = -1.0      # Minimum current limit (A)
    compliance_voltage: float = 210.0  # Default voltage compliance (V)
    compliance_current: float = 1.05   # Default current compliance (A)
    power_limit: float = 22.0      # Maximum power (W)


@dataclass
class MeasurementResult:
    """Container for measurement results"""
    voltage: float
    current: float
    resistance: Optional[float] = None
    timestamp: Optional[float] = None
    source_value: Optional[float] = None
    source_function: Optional[str] = None


class Keithley2450Error(Exception):
    """Custom exception for Keithley 2450 errors"""
    pass


class Keithley2450:
    """
    Keithley 2450 SourceMeter Unit Driver
    
    Features:
    - Safe operation with configurable limits
    - Source voltage/current with compliance protection
    - Measure voltage, current, resistance
    - IV sweep measurements
    - Built-in safety checks and error handling
    """
    
    # Instrument absolute limits (do not exceed)
    ABSOLUTE_MAX_VOLTAGE = 210.0  # V
    ABSOLUTE_MAX_CURRENT = 1.05   # A
    ABSOLUTE_MAX_POWER = 22.0     # W
    
    def __init__(self, resource_name: Optional[str] = None, 
                 safety_limits: Optional[SafetyLimits] = None,
                 simulate: bool = False,
                 simulation_resistance: float = 1000.0):
        """
        Initialize Keithley 2450 driver.
        
        Args:
            resource_name: VISA resource string (e.g., "USB0::0x05E6::0x2450::04096331::INSTR")
            safety_limits: Custom safety limits (uses defaults if None)
            simulate: If True, run in simulation mode without real hardware
            simulation_resistance: Resistance value (ohms) to simulate in simulation mode
        """
        self.resource_name = resource_name
        self.safety_limits = safety_limits or SafetyLimits()
        self.simulate = simulate
        self.simulation_resistance = simulation_resistance  # Configurable simulation resistance
        self._rm: Optional[pyvisa.ResourceManager] = None
        self._inst: Optional[pyvisa.Resource] = None
        self._connected = False
        self._output_enabled = False
        self._source_function = SourceFunction.VOLTAGE
        self._source_value = 0.0
        self._sense_function = 'CURR'  # Track which measurement function is active
        
        # Validate safety limits against absolute limits
        self._validate_safety_limits()
    
    def _validate_safety_limits(self):
        """Validate that safety limits don't exceed instrument absolute limits"""
        if abs(self.safety_limits.max_voltage) > self.ABSOLUTE_MAX_VOLTAGE:
            raise Keithley2450Error(
                f"Safety voltage limit {self.safety_limits.max_voltage}V exceeds "
                f"instrument maximum {self.ABSOLUTE_MAX_VOLTAGE}V"
            )
        if abs(self.safety_limits.max_current) > self.ABSOLUTE_MAX_CURRENT:
            raise Keithley2450Error(
                f"Safety current limit {self.safety_limits.max_current}A exceeds "
                f"instrument maximum {self.ABSOLUTE_MAX_CURRENT}A"
            )
    
    @staticmethod
    def list_available_instruments() -> List[str]:
        """List all available VISA instruments"""
        try:
            # Try NI-VISA first (sees USB devices), fall back to pyvisa-py
            try:
                rm = pyvisa.ResourceManager()  # Uses system VISA (NI-VISA)
            except:
                rm = pyvisa.ResourceManager('@py')  # Fallback to pyvisa-py
            
            resources = rm.list_resources()
            logger.info(f"Found resources: {resources}")
            rm.close()
            return list(resources)
        except Exception as e:
            logger.error(f"Error listing instruments: {e}")
            return []
    
    @staticmethod
    def find_keithley_2450() -> List[str]:
        """Find Keithley 2450 instruments specifically"""
        keithley_resources = []
        try:
            rm = pyvisa.ResourceManager()
            for resource in rm.list_resources():
                # Keithley 2450 USB ID: 0x05E6 (vendor), 0x2450 (product)
                if "0x05E6" in resource.upper() and "2450" in resource:
                    keithley_resources.append(resource)
                elif "KEITHLEY" in resource.upper() and "2450" in resource:
                    keithley_resources.append(resource)
            rm.close()
        except Exception as e:
            logger.error(f"Error finding Keithley 2450: {e}")
        return keithley_resources
    
    def connect(self, resource_name: Optional[str] = None) -> bool:
        """
        Connect to the Keithley 2450.
        
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
            raise Keithley2450Error("No resource name specified")
        
        try:
            self._rm = pyvisa.ResourceManager()
            self._inst = self._rm.open_resource(self.resource_name)
            
            # Configure communication
            self._inst.timeout = 10000  # 10 second timeout
            self._inst.read_termination = '\n'
            self._inst.write_termination = '\n'
            
            # IMPORTANT: Ensure device is in SCPI mode (not TSP mode)
            # This command works in both modes
            try:
                self._inst.write("*LANG SCPI")
                time.sleep(0.3)  # Give device time to switch modes
                logger.info("Set device to SCPI command mode")
            except Exception as e:
                logger.warning(f"Could not set SCPI mode: {e}")
            
            # Verify it's a Keithley 2450 (query directly, not through _query which checks _connected)
            idn = self._inst.query("*IDN?").strip()
            if "2450" not in idn:
                self._inst.close()
                self._rm.close()
                raise Keithley2450Error(f"Connected device is not a Keithley 2450: {idn}")
            
            logger.info(f"Connected to: {idn}")
            self._connected = True
            
            # Initialize to safe state
            self._initialize_safe_state()
            
            return True
            
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self._connected = False
            raise Keithley2450Error(f"Failed to connect: {e}")
    
    def disconnect(self):
        """Safely disconnect from the instrument"""
        try:
            if self._connected and not self.simulate:
                # Turn off output before disconnecting
                self.output_off()
                
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
            self._output_enabled = False
    
    def _initialize_safe_state(self):
        """Initialize instrument to a safe state"""
        if self.simulate:
            return
            
        try:
            # Turn off output
            self._write("OUTP OFF")
            self._output_enabled = False
            
            # Reset to defaults
            self._write("*RST")
            time.sleep(0.5)
            
            # Clear error queue
            self._write("*CLS")
            
            # Set to voltage source mode with 0V
            self._write("SOUR:FUNC VOLT")
            self._write("SOUR:VOLT 0")
            
            # Set default compliance
            self._write(f"SOUR:VOLT:ILIM {self.safety_limits.compliance_current}")
            
            logger.info("Instrument initialized to safe state")
            
        except Exception as e:
            logger.error(f"Failed to initialize safe state: {e}")
            raise
    
    def _check_connected(self):
        """Check if connected, raise error if not"""
        if not self._connected:
            raise Keithley2450Error("Not connected to instrument")
    
    def _write(self, command: str):
        """Write command to instrument with logging"""
        if self.simulate:
            logger.debug(f"SIM WRITE: {command}")
            self._simulate_write(command)
            return
        self._check_connected()
        logger.debug(f"WRITE: {command}")
        self._inst.write(command)
    
    def _simulate_write(self, command: str):
        """Parse and track simulation state from write commands"""
        import re
        cmd_upper = command.upper()
        
        # Track source voltage value
        if 'SOUR:VOLT' in cmd_upper and '?' not in cmd_upper:
            match = re.search(r'SOUR:VOLT\s+([\-\d\.eE\+]+)', command, re.IGNORECASE)
            if match:
                self._source_value = float(match.group(1))
                self._source_function = SourceFunction.VOLTAGE
                logger.debug(f"SIM: Source voltage set to {self._source_value}")
        
        # Track source current value
        elif 'SOUR:CURR' in cmd_upper and '?' not in cmd_upper:
            match = re.search(r'SOUR:CURR\s+([\-\d\.eE\+]+)', command, re.IGNORECASE)
            if match:
                self._source_value = float(match.group(1))
                self._source_function = SourceFunction.CURRENT
                logger.debug(f"SIM: Source current set to {self._source_value}")
        
        # Track sense function
        elif 'SENS:FUNC' in cmd_upper:
            if 'VOLT' in cmd_upper:
                self._sense_function = 'VOLT'
                logger.debug("SIM: Sense function set to VOLT")
            elif 'CURR' in cmd_upper:
                self._sense_function = 'CURR'
                logger.debug("SIM: Sense function set to CURR")
        
        # Track output state
        elif 'OUTP ON' in cmd_upper or 'OUTP 1' in cmd_upper:
            self._output_enabled = True
            logger.debug("SIM: Output enabled")
        elif 'OUTP OFF' in cmd_upper or 'OUTP 0' in cmd_upper:
            self._output_enabled = False
            logger.debug("SIM: Output disabled")
    
    def _query(self, command: str) -> str:
        """Query instrument with logging"""
        if self.simulate:
            logger.debug(f"SIM QUERY: {command}")
            return self._simulate_query(command)
        self._check_connected()
        logger.debug(f"QUERY: {command}")
        response = self._inst.query(command).strip()
        logger.debug(f"RESPONSE: {response}")
        return response
    
    def _simulate_query(self, command: str) -> str:
        """Return simulated responses for testing with realistic I-V behavior"""
        import random
        
        if "*IDN?" in command:
            return f"KEITHLEY INSTRUMENTS,MODEL 2450,04096331,1.7.0b (SIM R={self.simulation_resistance}Ω)"
        
        elif "READ?" in command or "MEAS?" in command:
            # What measurement to return depends on SENS:FUNC setting
            sense_func = getattr(self, '_sense_function', 'CURR')  # Default to current
            
            if self._source_function == SourceFunction.VOLTAGE:
                # Sourcing voltage
                v = self._source_value
                base_resistance = self.simulation_resistance
                effective_r = base_resistance
                
                if sense_func == 'CURR':
                    # Measuring current (I = V/R)
                    if abs(v) > 1e-9:
                        current = v / effective_r
                        noise = random.gauss(0, abs(current) * 0.001 + 1e-9)
                        current += noise
                    else:
                        current = random.gauss(0, 1e-10)
                    return f"{current:.12e}"
                else:
                    # Measuring voltage (return source voltage with measurement noise)
                    noise = random.gauss(0, abs(v) * 0.0001 + 1e-6)
                    return f"{v + noise:.9e}"
            else:
                # Sourcing current
                i = self._source_value
                base_resistance = self.simulation_resistance
                effective_r = base_resistance
                
                if sense_func == 'VOLT':
                    # Measuring voltage (V = I*R)
                    voltage = i * effective_r
                    noise = random.gauss(0, abs(voltage) * 0.001 + 1e-6)
                    return f"{voltage + noise:.9e}"
                else:
                    # Measuring current (return source current with noise)
                    noise = random.gauss(0, abs(i) * 0.0001 + 1e-9)
                    return f"{i + noise:.12e}"
        
        elif "SOUR:VOLT?" in command:
            return str(self._source_value)
        elif "SOUR:CURR?" in command:
            return str(self._source_value)
        elif "OUTP?" in command:
            return "1" if self._output_enabled else "0"
        return "0"
    
    def get_identification(self) -> str:
        """Get instrument identification string"""
        return self._query("*IDN?")
    
    def reset(self):
        """Reset instrument to defaults"""
        self._write("*RST")
        time.sleep(0.5)
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
        while True:
            error = self._query("SYST:ERR?")
            if error.startswith("0,") or error.startswith("+0,"):
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
        
        # Safety check: verify source value is within limits before enabling
        if self._source_function == SourceFunction.VOLTAGE:
            if not (self.safety_limits.min_voltage <= self._source_value <= self.safety_limits.max_voltage):
                raise Keithley2450Error(
                    f"Cannot enable output: source voltage {self._source_value}V "
                    f"outside safety limits [{self.safety_limits.min_voltage}, {self.safety_limits.max_voltage}]V"
                )
        else:
            if not (self.safety_limits.min_current <= self._source_value <= self.safety_limits.max_current):
                raise Keithley2450Error(
                    f"Cannot enable output: source current {self._source_value}A "
                    f"outside safety limits [{self.safety_limits.min_current}, {self.safety_limits.max_current}]A"
                )
        
        self._write("OUTP ON")
        self._output_enabled = True
        logger.info("Output ENABLED")
        return True
    
    def output_off(self):
        """Turn output OFF (safe operation)"""
        try:
            self._write("OUTP OFF")
        except:
            pass  # Always try to turn off, even if there's an error
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
        response = self._query("OUTP?")
        return response == "1" or response.upper() == "ON"
    
    # === SOURCE CONFIGURATION ===
    
    def set_source_voltage(self, voltage: float, compliance_current: Optional[float] = None):
        """
        Configure voltage source mode.
        
        Args:
            voltage: Source voltage in Volts
            compliance_current: Current limit in Amps (uses safety default if None)
        """
        # Safety validation
        if not (self.safety_limits.min_voltage <= voltage <= self.safety_limits.max_voltage):
            raise Keithley2450Error(
                f"Voltage {voltage}V outside safety limits "
                f"[{self.safety_limits.min_voltage}, {self.safety_limits.max_voltage}]V"
            )
        
        compliance = compliance_current or self.safety_limits.compliance_current
        if abs(compliance) > self.safety_limits.max_current:
            raise Keithley2450Error(
                f"Compliance current {compliance}A exceeds safety limit {self.safety_limits.max_current}A"
            )
        
        self._write("SOUR:FUNC VOLT")
        self._write(f"SOUR:VOLT:ILIM {compliance}")
        self._write(f"SOUR:VOLT {voltage}")
        
        self._source_function = SourceFunction.VOLTAGE
        self._source_value = voltage
        self._current_compliance = compliance  # Store for power limit checks
        
        logger.info(f"Voltage source configured: {voltage}V, compliance: {compliance}A")
    
    def set_source_current(self, current: float, compliance_voltage: Optional[float] = None):
        """
        Configure current source mode.
        
        Args:
            current: Source current in Amps
            compliance_voltage: Voltage limit in Volts (uses safety default if None)
        """
        # Safety validation
        if not (self.safety_limits.min_current <= current <= self.safety_limits.max_current):
            raise Keithley2450Error(
                f"Current {current}A outside safety limits "
                f"[{self.safety_limits.min_current}, {self.safety_limits.max_current}]A"
            )
        
        compliance = compliance_voltage or self.safety_limits.compliance_voltage
        if abs(compliance) > self.safety_limits.max_voltage:
            raise Keithley2450Error(
                f"Compliance voltage {compliance}V exceeds safety limit {self.safety_limits.max_voltage}V"
            )
        
        self._write("SOUR:FUNC CURR")
        self._write(f"SOUR:CURR:VLIM {compliance}")
        self._write(f"SOUR:CURR {current}")
        
        self._source_function = SourceFunction.CURRENT
        self._source_value = current
        self._voltage_compliance = compliance  # Store for power limit checks
        
        logger.info(f"Current source configured: {current}A, compliance: {compliance}V")
    
    def set_voltage(self, voltage: float):
        """
        Set source voltage value with safety validation.
        Use this during sweeps after initial configuration.
        
        Args:
            voltage: Voltage in Volts
            
        Raises:
            Keithley2450Error: If voltage exceeds safety limits
        """
        # SAFETY CHECK - Always validate before sending to device
        if not (self.safety_limits.min_voltage <= voltage <= self.safety_limits.max_voltage):
            raise Keithley2450Error(
                f"SAFETY STOP: Voltage {voltage}V outside safety limits "
                f"[{self.safety_limits.min_voltage}, {self.safety_limits.max_voltage}]V"
            )
        
        # Power check (V * I_compliance)
        if hasattr(self, '_current_compliance'):
            potential_power = abs(voltage * self._current_compliance)
            if potential_power > self.safety_limits.power_limit:
                raise Keithley2450Error(
                    f"SAFETY STOP: Potential power {potential_power:.2f}W exceeds limit {self.safety_limits.power_limit}W"
                )
        
        self._write(f"SOUR:VOLT {voltage}")
        self._source_value = voltage
        logger.debug(f"Voltage set to: {voltage}V")
    
    def set_current(self, current: float):
        """
        Set source current value with safety validation.
        Use this during sweeps after initial configuration.
        
        Args:
            current: Current in Amps
            
        Raises:
            Keithley2450Error: If current exceeds safety limits
        """
        # SAFETY CHECK - Always validate before sending to device
        if not (self.safety_limits.min_current <= current <= self.safety_limits.max_current):
            raise Keithley2450Error(
                f"SAFETY STOP: Current {current}A outside safety limits "
                f"[{self.safety_limits.min_current}, {self.safety_limits.max_current}]A"
            )
        
        # Power check (I * V_compliance)
        if hasattr(self, '_voltage_compliance'):
            potential_power = abs(current * self._voltage_compliance)
            if potential_power > self.safety_limits.power_limit:
                raise Keithley2450Error(
                    f"SAFETY STOP: Potential power {potential_power:.2f}W exceeds limit {self.safety_limits.power_limit}W"
                )
        
        self._write(f"SOUR:CURR {current}")
        self._source_value = current
        logger.debug(f"Current set to: {current}A")
    
    def get_source_value(self) -> float:
        """Get current source value"""
        if self._source_function == SourceFunction.VOLTAGE:
            return float(self._query("SOUR:VOLT?"))
        else:
            return float(self._query("SOUR:CURR?"))
    
    # === MEASUREMENT FUNCTIONS ===
    
    def set_measure_function(self, function: MeasureFunction):
        """Set the measurement function"""
        self._write(f"SENS:FUNC '{function.value}'")
        logger.info(f"Measure function set to: {function.name}")
    
    def set_sense_mode(self, mode: SenseMode):
        """Set 2-wire or 4-wire sensing"""
        self._write(f"SENS:{'VOLT' if self._source_function == SourceFunction.CURRENT else 'CURR'}:RSEN {mode.value}")
        logger.info(f"Sense mode set to: {mode.name}")
    
    # ---- Settings the 2450 window used to send as raw SCPI ----------------
    #
    # These were written straight from the GUI with smu._write(...), bypassing
    # the driver. They move here so the single merged window can reach them
    # through the common SMU interface. Each emits exactly the command sequence
    # the GUI sent, which is what every measurement so far was taken with.

    def set_remote_sense(self, four_wire: bool):
        """4-wire (remote) sensing on BOTH current and voltage.

        Unlike set_sense_mode, which touches only the measured function: the
        GUI set both, because 4-wire wiring read as 2-wire gives wildly wrong
        I and R readings, and the SMU otherwise keeps whatever mode a previous
        sweep or session left behind.
        """
        state = "ON" if four_wire else "OFF"
        self._write(f"SENS:CURR:RSEN {state}")
        self._write(f"SENS:VOLT:RSEN {state}")

    def set_measure_range(self, function: MeasureFunction, range_value: float):
        """Fixed measurement range (does not by itself switch auto-range off)."""
        self._write(f"SENS:{function.value}:RANG {range_value}")

    def set_measure_range_auto(self, function: MeasureFunction, auto: bool = True):
        self._write(f"SENS:{function.value}:RANG:AUTO {'ON' if auto else 'OFF'}")

    def set_nplc(self, nplc: float, function: Optional[MeasureFunction] = None):
        """Integration time in power-line cycles; both functions unless given."""
        if function:
            self._write(f"SENS:{function.value}:NPLC {nplc}")
        else:
            self._write(f"SENS:CURR:NPLC {nplc}")
            self._write(f"SENS:VOLT:NPLC {nplc}")

    def set_high_capacitance(self, enabled: bool):
        self._write(f"SOUR:VOLT:HCAP {'ON' if enabled else 'OFF'}")

    def set_auto_zero(self, state: str = "ON"):
        """ "ON", "OFF" or "ONCE"."""
        self._write(f"SENS:AZER {state}")

    def measure_voltage(self) -> float:
        """Measure voltage"""
        self._write("SENS:FUNC 'VOLT'")
        return float(self._query("READ?"))
    
    def measure_current(self) -> float:
        """Measure current"""
        self._write("SENS:FUNC 'CURR'")
        return float(self._query("READ?"))
    
    def measure_resistance(self) -> float:
        """Measure resistance (4-wire auto)"""
        self._write("SENS:FUNC 'RES'")
        return float(self._query("READ?"))
    
    def measure_all(self) -> MeasurementResult:
        """Measure voltage, current, and calculate resistance"""
        voltage = self.measure_voltage()
        current = self.measure_current()
        
        # Calculate resistance (avoid division by zero)
        resistance = None
        if abs(current) > 1e-12:
            resistance = voltage / current
        
        return MeasurementResult(
            voltage=voltage,
            current=current,
            resistance=resistance,
            timestamp=time.time(),
            source_value=self._source_value,
            source_function=self._source_function.name
        )
    
    def read_buffer(self, count: int = 1) -> List[float]:
        """Read values from buffer"""
        self._write(f"TRAC:TRIG:COUN {count}")
        self._write("TRAC:CLE")
        self._write("INIT")
        self._write("*WAI")
        data = self._query(f"TRAC:DATA? 1, {count}")
        return [float(x) for x in data.split(',')]
    
    # === SWEEP FUNCTIONS ===
    
    def voltage_sweep(self, start: float, stop: float, points: int, 
                      compliance_current: Optional[float] = None,
                      delay: float = 0.05) -> List[MeasurementResult]:
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
                raise Keithley2450Error(
                    f"Sweep voltage {v}V outside safety limits "
                    f"[{self.safety_limits.min_voltage}, {self.safety_limits.max_voltage}]V"
                )
        
        if points < 2:
            raise Keithley2450Error("Sweep must have at least 2 points")
        if points > 2500:
            raise Keithley2450Error("Maximum 2500 points in sweep")
        
        compliance = compliance_current or self.safety_limits.compliance_current
        
        results = []
        step = (stop - start) / (points - 1)
        
        logger.info(f"Starting voltage sweep: {start}V to {stop}V, {points} points")
        
        try:
            self.set_source_voltage(start, compliance)
            self._write("SENS:FUNC 'CURR'")
            
            if not self._output_enabled:
                self.output_on()
            
            for i in range(points):
                voltage = start + i * step
                self._write(f"SOUR:VOLT {voltage}")
                time.sleep(delay)
                
                current = float(self._query("READ?"))
                
                resistance = None
                if abs(current) > 1e-12:
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
                      delay: float = 0.05) -> List[MeasurementResult]:
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
                raise Keithley2450Error(
                    f"Sweep current {i}A outside safety limits "
                    f"[{self.safety_limits.min_current}, {self.safety_limits.max_current}]A"
                )
        
        if points < 2:
            raise Keithley2450Error("Sweep must have at least 2 points")
        if points > 2500:
            raise Keithley2450Error("Maximum 2500 points in sweep")
        
        compliance = compliance_voltage or self.safety_limits.compliance_voltage
        
        results = []
        step = (stop - start) / (points - 1)
        
        logger.info(f"Starting current sweep: {start}A to {stop}A, {points} points")
        
        try:
            self.set_source_current(start, compliance)
            self._write("SENS:FUNC 'VOLT'")
            
            if not self._output_enabled:
                self.output_on()
            
            for i in range(points):
                current = start + i * step
                self._write(f"SOUR:CURR {current}")
                time.sleep(delay)
                
                voltage = float(self._query("READ?"))
                
                resistance = None
                if abs(current) > 1e-12:
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
        self._write(f"SYST:BEEP {frequency}, {duration}")
    
    def get_terminal(self) -> str:
        """Get which terminals are active (FRONT or REAR)"""
        return self._query("ROUT:TERM?")
    
    def set_terminal(self, terminal: str):
        """Set active terminals ('FRONT' or 'REAR')"""
        if terminal.upper() not in ['FRONT', 'REAR']:
            raise Keithley2450Error("Terminal must be 'FRONT' or 'REAR'")
        self._write(f"ROUT:TERM {terminal}")
    
    def local_mode(self):
        """Return to local (front panel) control"""
        self._write("SYST:LOC")
    
    def remote_mode(self):
        """Set to remote control mode"""
        self._write("SYST:REM")
    
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
    for inst in Keithley2450.list_available_instruments():
        print(f"  {inst}")
    
    print("\nLooking for Keithley 2450...")
    k2450_list = Keithley2450.find_keithley_2450()
    if k2450_list:
        print(f"Found: {k2450_list}")
    else:
        print("No Keithley 2450 found. Running in simulation mode...")
        
        with Keithley2450(simulate=True) as smu:
            smu.connect()
            print(f"ID: {smu.get_identification()}")
            smu.set_source_voltage(1.0, compliance_current=0.01)
            smu.output_on()
            print(f"Output state: {smu.output_enabled}")
            smu.output_off()


if __name__ == "__main__":
    quick_test()
