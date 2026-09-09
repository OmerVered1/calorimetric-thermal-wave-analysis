"""Named calorimeter setups: which instrument, where it is, how to watch it.

A *setup* is site configuration — the IP the instrument currently answers on
and the network adapter its traffic passes through. A *profile*
(`sniffer.profile.DeviceProfile`) is protocol configuration — what the request
bytes mean and what units the replies are in. They are kept apart on purpose:

  * a profile is true of every Alexsys Drop everywhere, so it can be shared,
    and it round-trips with the OmerVered1/lan-signal-sniffer repo the
    `sniffer/` package is vendored from;
  * a setup is true only of this bench and this PC — a Windows capture
    interface is a GUID that means nothing on another machine.

So this file stores setups next to the user's profiles in application data,
deliberately not in Documents where the experiment store lives: Documents is
the folder that gets copied between machines, and a copied interface GUID is
worse than an absent one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from sniffer.profile import user_profile_dir


DEFAULT_PORT = 1210


def setups_path() -> Path:
    """Where the setup store lives: beside the user's calorimeter profiles."""
    return user_profile_dir().parent / "calorimeter_setups.json"


@dataclass
class CalorimeterSetup:
    """One saved way of watching one calorimeter.

    `host` and `interface` may be blank, which means "work it out at connect
    time" — ARP discovery for the host, scapy's subnet guess for the
    interface. Blank is a meaningful, supported value rather than an
    incomplete setup: the IP is DHCP-assigned and does move.
    """

    name: str
    calorimeter: str        # key into calorimeter_reader.CALORIMETERS
    profile_name: str       # matches a DeviceProfile.name from load_profiles()
    host: str = ""
    interface: str = ""
    port: int = DEFAULT_PORT
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "calorimeter": self.calorimeter,
            "profile_name": self.profile_name,
            "host": self.host,
            "interface": self.interface,
            "port": self.port,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CalorimeterSetup":
        name = str(d.get("name") or "").strip()
        if not name:
            raise ValueError("setup has no name")
        return cls(
            name=name,
            calorimeter=str(d.get("calorimeter") or ""),
            profile_name=str(d.get("profile_name") or ""),
            host=str(d.get("host") or ""),
            interface=str(d.get("interface") or ""),
            port=int(d.get("port") or DEFAULT_PORT),
            notes=str(d.get("notes") or ""),
        )


class SetupStore:
    """JSON-backed store of named setups.

    Mirrors ExperimentStore's shape so the two feel the same in the UI. Every
    read path is forgiving: a truncated or hand-edited file costs the user
    their setups, but it must never stop the app from starting, because the
    app is also the only way to record an experiment already in progress.
    """

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path is not None else setups_path()
        self._setups: Dict[str, CalorimeterSetup] = {}
        self.load()

    # ----- persistence --------------------------------------------------

    def load(self) -> None:
        self._setups = {}
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError:
            return
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return
        for entry in (data.get("setups") or []) if isinstance(data, dict) else []:
            try:
                setup = CalorimeterSetup.from_dict(entry)
            except (ValueError, TypeError, AttributeError):
                continue
            self._setups[setup.name] = setup

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"setups": [s.to_dict() for s in self._setups.values()]}
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    # ----- queries ------------------------------------------------------

    def names(self) -> List[str]:
        return sorted(self._setups.keys(), key=str.lower)

    def get(self, name: str) -> Optional[CalorimeterSetup]:
        return self._setups.get(name)

    # ----- mutations ----------------------------------------------------

    def save(self, setup: CalorimeterSetup) -> None:
        self._setups[setup.name] = setup
        self._write()

    def delete(self, name: str) -> None:
        if name in self._setups:
            del self._setups[name]
            self._write()

    def rename(self, old: str, new: str) -> bool:
        """Rename, refusing to clobber an existing setup. True if it happened."""
        new = new.strip()
        if old not in self._setups or not new:
            return False
        if new != old and new in self._setups:
            return False
        setup = self._setups.pop(old)
        setup.name = new
        self._setups[new] = setup
        self._write()
        return True
