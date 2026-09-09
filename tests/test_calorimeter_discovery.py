import math
import struct

import pytest

from calorimeter_discovery import (
    SignalChoice,
    analyse_chunks,
    profile_from_choices,
)
from sniffer.profile import LiveDecoder
from sniffer.reassembly import C2S, S2C, FlowKey, StreamChunk


FLOW = FlowKey("10.0.0.9", 51000, 1210)

# The three commands the Drop profile expects, and plausible live values.
DROP_CMDS = {
    "heat_flow": bytes.fromhex("0001000a0001"),
    "sample_temperature": bytes.fromhex("000100080004"),
    "external_temperature": bytes.fromhex("000100080005"),
}


def _traffic(cycles=40, counter=False, drift=0.01):
    """Synthetic poll loop: request, then a 6-byte echo + float32 reply.

    Values drift a little each cycle — scan_channel discards constants, so a
    fixed value would produce no candidates at all.
    """
    chunks = []
    ts = 1000.0
    seq = 0
    for c in range(cycles):
        for i, (_name, cmd) in enumerate(DROP_CMDS.items()):
            req = bytearray(cmd)
            if counter:
                # A 2-byte transaction counter in the first two bytes, the
                # shape that makes every request unique and defeats an
                # exact-match signature.
                req[0:2] = struct.pack(">H", seq & 0xFFFF)
                seq += 1
            req = bytes(req)
            value = [32.2 + i * 100, 766.7, 20.2][i % 3] + c * drift
            chunks.append(StreamChunk(ts=ts, flow=FLOW, direction=C2S,
                                      data=req, stream_offset=0))
            chunks.append(StreamChunk(ts=ts + 0.01, flow=FLOW, direction=S2C,
                                      data=req + struct.pack(">f", value),
                                      stream_offset=0))
            ts += 0.3
    return chunks


# ----- discovery -------------------------------------------------------------

def test_no_traffic_reports_a_warning_not_a_crash():
    d = analyse_chunks([])
    assert not d.ok
    assert "no traffic" in " ".join(d.warnings)


def test_discovers_one_channel_per_command():
    d = analyse_chunks(_traffic())
    assert d.ok
    assert len(d.channels) == 3
    assert {ch.channel.signature for ch in d.channels} == set(DROP_CMDS.values())


def test_each_channel_offers_the_real_field_as_a_candidate():
    d = analyse_chunks(_traffic())
    for ch in d.channels:
        offsets = {(c.offset, c.encoding) for c in ch.scan.candidates}
        assert (6, "f32be") in offsets


def test_the_real_field_outranks_the_echoed_request_bytes():
    """Bytes 0-5 are a constant echo; the measurement is what varies."""
    d = analyse_chunks(_traffic())
    for ch in d.channels:
        assert ch.best is not None
        assert ch.best.offset == 6
        assert ch.best.encoding == "f32be"


def test_channel_describe_mentions_reply_count_and_rate():
    d = analyse_chunks(_traffic())
    text = d.channels[0].describe()
    assert "replies" in text and "every" in text


# ----- the transaction-counter case -----------------------------------------

def test_a_counter_in_the_request_still_yields_three_channels():
    """Exact-signature matching collapses here; masking is what saves it."""
    d = analyse_chunks(_traffic(counter=True))
    assert len(d.channels) == 3


def test_a_counter_is_masked_out_and_reported():
    d = analyse_chunks(_traffic(counter=True))
    masks = [ch.channel.mask for ch in d.channels]
    assert all(m[0] is False and m[1] is False for m in masks)
    assert any("counter" in w for w in d.warnings)


def test_masked_signature_is_shown_with_dots():
    d = analyse_chunks(_traffic(counter=True))
    assert d.channels[0].signature_hex.startswith("....")


# ----- building a profile ----------------------------------------------------

def _choices(discovery):
    # Name each channel by the value range its best candidate previews.
    names = []
    for i, ch in enumerate(discovery.channels):
        latest = ch.best.latest
        if latest > 500:
            names.append(("sample_temperature", "degC"))
        elif latest > 100:
            names.append(("heat_flow_b", "mW"))
        elif latest > 25:
            names.append(("heat_flow", "mW"))
        else:
            names.append(("external_temperature", "degC"))
    return [
        SignalChoice(channel_index=i, candidate=ch.best, name=names[i][0],
                     unit=names[i][1])
        for i, ch in enumerate(discovery.channels)
    ]


def test_profile_round_trips_through_json(tmp_path):
    d = analyse_chunks(_traffic())
    p = profile_from_choices("Test Drop", d, _choices(d), device_port=1210)
    path = tmp_path / "p.json"
    p.save(path)
    from sniffer.profile import DeviceProfile
    back = DeviceProfile.load(path)
    assert [s.name for s in back.signals] == [s.name for s in p.signals]
    assert [s.offset for s in back.signals] == [6, 6, 6]


def test_built_profile_actually_decodes_the_traffic_it_came_from():
    """End to end: discovery -> profile -> LiveDecoder reads the same wire."""
    chunks = _traffic()
    d = analyse_chunks(chunks)
    profile = profile_from_choices("Test Drop", d, _choices(d), device_port=1210)

    decoded = []
    dec = LiveDecoder(profile)
    for s in dec.feed(chunks):
        decoded.append(s.values)
    final = dec.flush()
    if final is not None:
        decoded.append(final.values)

    assert decoded, "profile built from the capture decoded nothing"
    seen = {k for values in decoded for k in values}
    assert len(seen) == 3


def test_built_profile_decodes_traffic_that_carries_a_counter():
    """The case the current shipped Drop profile cannot handle."""
    chunks = _traffic(counter=True)
    d = analyse_chunks(chunks)
    profile = profile_from_choices("Counter Drop", d, _choices(d), device_port=1210)

    dec = LiveDecoder(profile)
    decoded = [s.values for s in dec.feed(chunks)]
    assert decoded, "masked signatures failed to match live requests"


def test_profile_rejects_duplicate_signal_names():
    d = analyse_chunks(_traffic())
    choices = [
        SignalChoice(channel_index=i, candidate=ch.best, name="same", unit="mW")
        for i, ch in enumerate(d.channels)
    ]
    with pytest.raises(ValueError, match="unique"):
        profile_from_choices("X", d, choices, device_port=1210)


def test_profile_rejects_a_blank_signal_name():
    d = analyse_chunks(_traffic())
    choices = [SignalChoice(0, d.channels[0].best, name="   ", unit="mW")]
    with pytest.raises(ValueError, match="name"):
        profile_from_choices("X", d, choices, device_port=1210)


def test_profile_rejects_no_choices():
    d = analyse_chunks(_traffic())
    with pytest.raises(ValueError, match="no signals"):
        profile_from_choices("X", d, [], device_port=1210)


def test_scale_and_bias_are_carried_into_the_signal():
    d = analyse_chunks(_traffic())
    choices = [SignalChoice(0, d.channels[0].best, "x", "mW", scale=2.0, bias=1.0)]
    p = profile_from_choices("X", d, choices, device_port=1210)
    assert p.signals[0].convert(3.0) == pytest.approx(7.0)
