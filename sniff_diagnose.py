"""Diagnose why sniff mode captures packets but decodes no samples.

Run on the PC that has the calorimeter traffic, as Administrator:

    python sniff_diagnose.py --host 192.168.1.50 --seconds 30
    python sniff_diagnose.py --list          # just show capture interfaces
    python sniff_diagnose.py --host X --iface "\\Device\\NPF_{GUID}"

Instruments every boundary of the same pipeline sniff mode uses, so the
output says WHICH layer drops the data rather than only that the end is
empty:

    scapy packet -> TCPReassembler chunk -> split_frames -> signature match
                 -> decode_field -> Sample

Prints raw hex, so if the framing assumption itself is wrong (the real
question when "traffic seen but doesn't match the profile") the bytes are
right there to re-derive it from.
"""

from __future__ import annotations

import argparse
import collections
import sys
import time

from calorimeter_reader import (
    C80_PORT,
    _SNIFF_PROFILE_BY_CALORIMETER,
    CALORIMETERS,
)
from sniffer.capture import PacketPump, capture_readiness, describe_interfaces
from sniffer.framer import TimedStream, split_frames
from sniffer.profile import load_profiles
from sniffer.reassembly import C2S, S2C, StreamChunk
from sniffer.fields import decode_field


def list_interfaces() -> None:
    print("Capture interfaces (name -- description -- ip):")
    for i in describe_interfaces():
        print(f"  {i.name}\n      desc={i.description!r} ip={i.ip!r} mac={i.mac!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", help="calorimeter IP (same value the app's Host field shows)")
    ap.add_argument("--iface", default=None, help="capture interface name (default: scapy's pick)")
    ap.add_argument("--port", type=int, default=C80_PORT)
    ap.add_argument("--calorimeter", default="Drop (Alexsys)", choices=list(CALORIMETERS))
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--max-hex", type=int, default=40, help="how many raw frames to print per direction")
    ap.add_argument("--list", action="store_true", help="list interfaces and exit")
    args = ap.parse_args()

    if args.list:
        list_interfaces()
        return 0
    if not args.host:
        ap.error("--host is required (or use --list)")

    r = capture_readiness()
    print(f"capture readiness: ok={r.ok} detail={r.detail!r} remedy={r.remedy!r}")
    if not r.ok:
        return 1

    profile_name = _SNIFF_PROFILE_BY_CALORIMETER[args.calorimeter]
    profile = {p.name: p for p in load_profiles()}.get(profile_name)
    if profile is None:
        print(f"FAIL: profile {profile_name!r} not found among "
              f"{[p.name for p in load_profiles()]}")
        return 1

    print(f"profile: {profile.name}  interaction={profile.interaction}  "
          f"device_port={profile.device_port}")
    print(f"request framing: mode={profile.request_framing.mode} "
          f"frame_len={profile.request_framing.frame_len}")
    print("signals it is looking for:")
    for s in profile.signals:
        print(f"  {s.name:22s} signature={s.signature.hex()} offset={s.offset} enc={s.encoding}")
    print()

    pump = PacketPump(args.host, device_port=args.port, interface=args.iface)
    print(f"bpf filter: {pump.bpf_filter!r}")
    print(f"interface : {args.iface or '(scapy default)'}")
    pump.start()
    print(f"capturing for {args.seconds:.0f}s ...\n")

    # ---- per-layer counters -------------------------------------------
    chunks_by_dir: dict[str, int] = collections.Counter()
    bytes_by_dir: dict[str, int] = collections.Counter()
    chunk_lens: dict[str, collections.Counter] = {C2S: collections.Counter(), S2C: collections.Counter()}
    req_frames: collections.Counter = collections.Counter()   # hex -> count
    matched: collections.Counter = collections.Counter()      # signal name -> count
    unmatched: collections.Counter = collections.Counter()    # request hex -> count
    responses: list[tuple[str, str]] = []                     # (request hex, response hex)
    gaps = 0

    # Mirror LiveDecoder's own pairing, but record everything it discards.
    carry = bytearray()
    pending_req: bytes | None = None
    resp = bytearray()

    def close_pending() -> None:
        nonlocal pending_req, resp
        if pending_req is None or not resp:
            return
        rq, rp = bytes(pending_req), bytes(resp)
        if len(responses) < args.max_hex:
            responses.append((rq.hex(), rp.hex()))
        specs = profile.signals_for(rq)
        if not specs:
            unmatched[rq.hex()] += 1
        for spec in specs:
            raw = decode_field([rp], spec.offset, spec.encoding)[0]
            if raw == raw:
                matched[spec.name] += 1
            else:
                matched[f"{spec.name} (NaN: response only {len(rp)}B)"] += 1
        resp.clear()

    deadline = time.time() + args.seconds
    try:
        while time.time() < deadline:
            for chunk in pump.poll():
                chunks_by_dir[chunk.direction] += 1
                bytes_by_dir[chunk.direction] += len(chunk.data)
                chunk_lens[chunk.direction][len(chunk.data)] += 1
                if chunk.gap_before:
                    gaps += 1

                if chunk.direction == S2C:
                    if pending_req is not None:
                        resp.extend(chunk.data)
                    continue

                if chunk.gap_before:
                    carry.clear()
                carry.extend(chunk.data)
                stream = TimedStream()
                stream.append(StreamChunk(ts=chunk.ts, flow=chunk.flow, direction=C2S,
                                          data=bytes(carry), stream_offset=0))
                frames = split_frames(stream, profile.request_framing)
                del carry[: sum(len(f.data) for f in frames)]
                for f in frames:
                    req_frames[f.data.hex()] += 1
                    close_pending()
                    pending_req = f.data
                    resp.clear()
            if pump.error:
                print(f"pump error: {pump.error}")
                break
            time.sleep(0.2)
    finally:
        pump.stop()

    close_pending()

    # ---- report --------------------------------------------------------
    print("=" * 72)
    print(f"LAYER 1  scapy         : {pump.packets_seen} packets seen, "
          f"{pump.packets_dropped} dropped")
    print(f"LAYER 2  reassembly    : {chunks_by_dir[C2S]} c2s chunks "
          f"({bytes_by_dir[C2S]}B), {chunks_by_dir[S2C]} s2c chunks "
          f"({bytes_by_dir[S2C]}B), {gaps} with gap_before")
    for d in (C2S, S2C):
        if chunk_lens[d]:
            sizes = ", ".join(f"{ln}B x{n}" for ln, n in sorted(chunk_lens[d].items()))
            print(f"           {d} segment sizes: {sizes}")
    print(f"LAYER 3  framing       : {sum(req_frames.values())} request frames "
          f"({len(req_frames)} distinct)")
    print(f"LAYER 4  signature     : {sum(matched.values())} decoded, "
          f"{sum(unmatched.values())} requests matched no signal")
    print("=" * 72)

    if pump.packets_seen == 0:
        print("\n=> Nothing captured. Wrong interface, or nothing is polling the host.")
        return 2
    if not chunks_by_dir:
        print("\n=> Packets captured but the reassembler emitted no chunks: every packet "
              "was payload-free (pure ACK/handshake), or the host IP does not match "
              "either endpoint. Check --host against the IPs above.")
        return 2

    if req_frames:
        print("\nDistinct request frames seen (hex x count) -- these are what the")
        print("signatures must match:")
        for hx, n in req_frames.most_common(args.max_hex):
            star = ""
            for s in profile.signals:
                if bytes.fromhex(hx) == s.signature:
                    star = f"   <== matches {s.name}"
            print(f"  {hx}  x{n}{star}")

    if unmatched:
        print("\nRequests that matched NO signal signature:")
        for hx, n in unmatched.most_common(args.max_hex):
            print(f"  {hx}  x{n}")

    if matched:
        print("\nSuccessfully decoded:")
        for name, n in matched.most_common():
            print(f"  {name}: {n}")

    if responses:
        print("\nRequest -> response pairs (raw hex, so framing can be re-derived):")
        for rq, rp in responses:
            print(f"  req {rq:<20s} resp[{len(rp)//2:>3d}B] {rp}")

    if not matched:
        print("\n=> Traffic decoded to zero samples. Compare the request hex above "
              "against the signatures printed at the top: if they differ, Calisto "
              "is not sending the commands the profile expects (different frame "
              "length, a transaction counter in the bytes, or a different protocol "
              "entirely) and the profile needs re-deriving from these bytes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
