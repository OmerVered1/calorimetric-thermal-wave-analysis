"""Finding instruments. Slow by nature, so never called on the UI thread.

A VISA scan asks every backend and, on a lab network, every responder on the
LAN; the 6430's serial auto-detect tries each port at each baud rate with a
timeout apiece. The original windows ran both on the UI thread, which is why
their connect dialogs froze on open. These functions stay plain and blocking;
the dialog runs them in a worker thread.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .capabilities import Capabilities

log = logging.getLogger(__name__)

KEITHLEY_USB_VENDOR = "05E6"


@dataclass(frozen=True)
class Found:
    address: str          # what gets passed to connect()
    label: str            # what the user sees
    likely: bool = False  # looks like the model being connected


def list_visa(caps: Capabilities) -> List[Found]:
    """Every VISA resource, the ones that look like ``caps`` first."""
    try:
        import pyvisa
    except ImportError:
        return []
    resources: Tuple[str, ...] = ()
    for backend in (None, "@py"):
        try:
            rm = pyvisa.ResourceManager() if backend is None else pyvisa.ResourceManager(backend)
            resources = tuple(rm.list_resources())
            rm.close()
            break
        except Exception as exc:  # no backend installed, or it errored
            log.debug("VISA backend %s failed: %s", backend or "default", exc)
    number = caps.model.rstrip("AB").lower()
    found = []
    for r in resources:
        upper = r.upper()
        if upper.startswith("ASRL") and "/DEV/CU." in upper and "USB" not in upper:
            continue  # macOS Bluetooth/debug pseudo-ports: never an SMU
        likely = number in r.lower() or KEITHLEY_USB_VENDOR in upper
        found.append(Found(address=r, label=_visa_label(r), likely=likely))
    found.sort(key=lambda f: (not f.likely, f.address))
    return found


def _visa_label(resource: str) -> str:
    upper = resource.upper()
    if upper.startswith("USB"):
        parts = resource.split("::")
        serial = parts[3] if len(parts) > 3 else ""
        vendor = " · Keithley" if KEITHLEY_USB_VENDOR in upper else ""
        return f"USB{vendor}  {serial}".rstrip()
    if upper.startswith("TCPIP"):
        host = resource.split("::")[1] if "::" in resource else resource
        return f"LAN  {host}"
    if upper.startswith("GPIB"):
        addr = resource.split("::")[1] if "::" in resource else resource
        return f"GPIB  address {addr}"
    if upper.startswith("ASRL"):
        return f"Serial  {resource.split('::')[0][4:]}"
    return resource


def list_serial() -> List[Found]:
    try:
        import serial.tools.list_ports
    except ImportError:
        return []
    out = []
    for p in serial.tools.list_ports.comports():
        if p.device.startswith("/dev/cu.") and "usb" not in p.device.lower():
            continue  # same pseudo-ports as above
        desc = p.description if p.description and p.description != "n/a" else ""
        out.append(Found(address=p.device, label=f"{p.device}  {desc}".strip(),
                         likely="usb" in (p.description or "").lower()
                         or "serial" in (p.description or "").lower()))
    out.sort(key=lambda f: (not f.likely, f.address))
    return out


def autodetect_6430(timeout: float = 1.0) -> Optional[Tuple[str, int]]:
    from keithley6430_driver import Keithley6430

    return Keithley6430.auto_detect(timeout=timeout)


def visa_address_for_ip(ip: str) -> str:
    return f"TCPIP::{ip.strip()}::inst0::INSTR"
