"""Tests for minimal Wyoming protocol encoding and decoding."""

from __future__ import annotations

from wyomingchat.wyoming_protocol import WyomingEvent, decode_event, decode_event_bytes, encode_event


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


class _BrokenReader:
    """Raise ValueError on read operations so tests can simulate a socket reader being invalidated mid-stream."""

    # Usage: simulate a broken file-like object whose readline method fails after the socket closes.
    # Parameters: none.
    # Return: never returns because it always raises ValueError.
    def readline(self) -> bytes:
        """Raise ValueError to emulate a broken reader.readline call."""

        raise ValueError("reader closed")

    # Usage: simulate a broken file-like object whose read method fails after the socket closes.
    # Parameters: size - ignored requested byte count.
    # Return: never returns because it always raises ValueError.
    def read(self, size: int) -> bytes:
        """Raise ValueError to emulate a broken reader.read call."""

        del size
        raise ValueError("reader closed")


# Usage: verify that broken socket readers become EOFError instead of uncaught ValueError exceptions in worker threads.
# Parameters: none.
# Return: None.
def test_decode_event_translates_broken_reader_value_errors_into_eof() -> None:
    """Ensure decode_event converts broken-reader ValueError exceptions into EOFError."""

    try:
        decode_event(_BrokenReader())
    except EOFError:
        pass
    else:
        raise AssertionError("decode_event should translate ValueError into EOFError")
