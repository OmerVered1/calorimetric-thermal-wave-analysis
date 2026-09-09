"""Work out a calorimeter's signals by watching its traffic.

The vendored `sniffer` package already carries the whole engine for this —
framing inference, counter-aware channel grouping, and a ranked sweep of every
byte offset and encoding for series that look like measurements. What was
missing was a way to drive it from this app and turn the result into a saved
profile. That is all this module does.

Kept free of Qt on purpose: the wizard dialog is a thin shell over these
functions, and the interesting logic stays testable without a display, a
capture driver, or an instrument.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence

from sniffer.fields import Candidate, FieldScan, scan_channel
from sniffer.framer import Channel, FlowAnalysis, analyze_flow
from sniffer.profile import DeviceProfile, SignalSpec, user_profile_dir
from sniffer.reassembly import StreamChunk


# A capture long enough that a ~1 Hz poll loop cycles through every channel
# several times; scan_channel needs a handful of samples per channel before it
# will score a series at all.
DEFAULT_CAPTURE_S = 30.0


@dataclass
class DiscoveredChannel:
    """One request the client sends, and what its replies might mean."""

    channel: Channel
    scan: FieldScan

    @property
    def signature_hex(self) -> str:
        return self.channel.signature_hex

    @property
    def count(self) -> int:
        return self.channel.count

    @property
    def best(self) -> Optional[Candidate]:
        return self.scan.candidates[0] if self.scan.candidates else None

    def describe(self) -> str:
        period = self.channel.median_period()
        rate = f", every {period:.1f}s" if period else ""
        return f"{self.signature_hex}  ({self.count} replies{rate})"


@dataclass
class Discovery:
    """Everything one capture session worked out."""

    analysis: Optional[FlowAnalysis]
    channels: List[DiscoveredChannel] = field(default_factory=list)
    packets_seen: int = 0
    chunks_seen: int = 0
    warnings: List[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.channels)


def analyse_chunks(chunks: Sequence[StreamChunk]) -> Discovery:
    """Turn reassembled stream chunks into ranked per-channel candidates."""
    if not chunks:
        return Discovery(
            analysis=None,
            warnings=["no traffic was captured"],
        )

    analysis = analyze_flow(chunks)
    discovered = [
        DiscoveredChannel(channel=ch, scan=scan_channel(ch.payloads))
        for ch in analysis.channels
    ]

    warnings = list(analysis.warnings)
    for d in discovered:
        for w in d.scan.warnings:
            warnings.append(f"{d.signature_hex}: {w}")
    if discovered and not any(d.scan.candidates for d in discovered):
        warnings.append(
            "replies were captured but none of them decode as a changing "
            "numeric field — the values may be constant during this capture, "
            "or the payload may not be numeric"
        )

    return Discovery(
        analysis=analysis,
        channels=discovered,
        chunks_seen=len(chunks),
        warnings=warnings,
    )


def capture_discovery(
    host: str,
    port: int,
    interface: Optional[str],
    seconds: float = DEFAULT_CAPTURE_S,
    progress: Optional[Callable[[float, int], bool]] = None,
) -> Discovery:
    """Capture for `seconds`, then analyse what came back.

    `progress(elapsed, packets)` is called about five times a second; return
    False from it to stop early. Every failure is reported in `Discovery.error`
    rather than raised, because every one of them is a thing the user can act
    on (wrong interface, no Npcap, not running as admin).
    """
    try:
        from sniffer.capture import PacketPump, capture_readiness
    except Exception as e:
        return Discovery(analysis=None, error=f"packet capture unavailable: {e}")

    readiness = capture_readiness()
    if not readiness.ok:
        detail = readiness.detail
        if readiness.remedy:
            detail += f" — {readiness.remedy}"
        return Discovery(analysis=None, error=f"capture not available: {detail}")

    pump = PacketPump(host, device_port=port, interface=interface)
    try:
        pump.start()
    except Exception as e:
        return Discovery(analysis=None, error=f"capture failed to start: {e}")

    chunks: List[StreamChunk] = []
    started = time.monotonic()
    try:
        while True:
            elapsed = time.monotonic() - started
            if elapsed >= seconds:
                break
            chunks.extend(pump.poll())
            if pump.error:
                return Discovery(analysis=None, packets_seen=pump.packets_seen,
                                 error=pump.error)
            if progress is not None and progress(elapsed, pump.packets_seen) is False:
                break
            time.sleep(0.2)
        chunks.extend(pump.poll())
    finally:
        pump.stop()

    result = analyse_chunks(chunks)
    result.packets_seen = pump.packets_seen
    if pump.packets_seen == 0:
        result.error = (
            f"no packets captured on '{interface or 'the default interface'}' — "
            f"wrong adapter, or nothing is talking to {host} right now"
        )
    elif not chunks:
        result.error = (
            f"{pump.packets_seen} packets captured but none carried payload — "
            "the connection may be idle, or this is the wrong port"
        )
    return result


# ----- turning choices into a profile ---------------------------------------


@dataclass
class SignalChoice:
    """One row the user filled in: which field of which channel means what."""

    channel_index: int
    candidate: Candidate
    name: str
    unit: str
    scale: float = 1.0
    bias: float = 0.0


def profile_from_choices(
    profile_name: str,
    discovery: Discovery,
    choices: Sequence[SignalChoice],
    device_port: int,
    mac: str = "",
    notes: str = "",
) -> DeviceProfile:
    """Assemble a saveable profile from the wizard's picks.

    The channel's own mask travels with each signal, so a request carrying a
    transaction counter still matches: that is the difference between a profile
    that decodes and one that silently sees nothing.
    """
    if discovery.analysis is None:
        raise ValueError("nothing was discovered to build a profile from")
    if not choices:
        raise ValueError("no signals were chosen")

    signals: List[SignalSpec] = []
    for choice in choices:
        channel = discovery.channels[choice.channel_index].channel
        name = choice.name.strip()
        if not name:
            raise ValueError("every chosen signal needs a name")
        signals.append(
            SignalSpec(
                name=name,
                unit=choice.unit.strip(),
                signature=channel.signature,
                mask=list(channel.mask),
                offset=choice.candidate.offset,
                encoding=choice.candidate.encoding,
                scale=choice.scale,
                bias=choice.bias,
            )
        )

    duplicates = {s.name for s in signals if [x.name for x in signals].count(s.name) > 1}
    if duplicates:
        raise ValueError(f"signal names must be unique; repeated: {sorted(duplicates)}")

    analysis = discovery.analysis
    return DeviceProfile(
        name=profile_name.strip(),
        device_port=device_port,
        request_framing=analysis.request_spec,
        response_framing=(
            analysis.response_spec if analysis.interaction == "server_push" else None
        ),
        interaction=analysis.interaction,
        signals=signals,
        mac=mac,
        notes=notes,
    )


def save_profile(profile: DeviceProfile):
    """Write a profile to the user's profile directory and return its path.

    A user profile with the same name shadows the bundled one, which is how a
    corrected profile survives an app update.
    """
    directory = user_profile_dir()
    directory.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if (c.isalnum() or c in " -_") else "_" for c in profile.name)
    path = directory / f"{safe.strip() or 'profile'}.json"
    profile.save(path)
    return path
