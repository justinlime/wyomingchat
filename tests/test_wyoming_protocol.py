"""Tests for minimal Wyoming protocol encoding and decoding."""

from __future__ import annotations

from wyomingchat.wyoming_protocol import WyomingEvent, decode_event_bytes, encode_event


# Usage: verify that an event containing JSON data and binary payload round-trips through the wire format.
# Parameters: none.
# Return: None.
def test_wyoming_event_round_trip_with_payload() -> None:
    """Ensure a Wyoming event with a payload round-trips correctly."""

    original = WyomingEvent(
        type="audio-chunk",
        data={"rate": 16000, "width": 2, "channels": 1},
        payload=b"\x01\x02\x03\x04",
    )

    decoded = decode_event_bytes(encode_event(original))

    assert decoded.type == original.type
    assert decoded.data == original.data
    assert decoded.payload == original.payload


# Usage: verify that an event without a payload still round-trips correctly through the protocol helpers.
# Parameters: none.
# Return: None.
def test_wyoming_event_round_trip_without_payload() -> None:
    """Ensure a Wyoming event without a payload round-trips correctly."""

    original = WyomingEvent(type="transcript", data={"text": "hello"})

    decoded = decode_event_bytes(encode_event(original))

    assert decoded.type == "transcript"
    assert decoded.data == {"text": "hello"}
    assert decoded.payload is None
