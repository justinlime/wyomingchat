"""Minimal Wyoming protocol framing helpers used by the local STT and TTS clients."""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from typing import Any, BinaryIO

from .constants import APP_VERSION


@dataclass(slots=True)
class WyomingEvent:
    """Represent a single Wyoming protocol event with optional JSON data and binary payload."""

    type: str
    data: dict[str, Any] = field(default_factory=dict)
    payload: bytes | None = None

    # Usage: create the JSON header dictionary that will be serialized for transport.
    # Parameters: none.
    # Return: a dictionary containing the event type and JSON data section.
    def to_header_dict(self) -> dict[str, Any]:
        """Return the header dictionary used when encoding the event."""

        return {"type": self.type, "data": dict(self.data)}

    @classmethod
    # Usage: construct a WyomingEvent from a parsed JSON header and optional payload bytes.
    # Parameters: payload - the decoded header dictionary; body - optional payload bytes.
    # Return: a new WyomingEvent instance.
    def from_parts(cls, payload: dict[str, Any], body: bytes | None = None) -> "WyomingEvent":
        """Create a WyomingEvent from previously decoded header and payload pieces."""

        return cls(type=str(payload["type"]), data=dict(payload.get("data", {})), payload=body)


# Usage: encode a WyomingEvent into the wire format expected by Wyoming services.
# Parameters: event - the WyomingEvent that should be serialized.
# Return: bytes ready to be sent over a TCP connection.
def encode_event(event: WyomingEvent) -> bytes:
    """Serialize a WyomingEvent into the protocol's header-plus-body wire format."""

    event_dict = event.to_header_dict()
    event_dict["version"] = APP_VERSION

    data_dict = event_dict.pop("data", None)
    data_bytes = b""
    if data_dict:
        data_bytes = json.dumps(data_dict, ensure_ascii=False).encode("utf-8")
        event_dict["data_length"] = len(data_bytes)

    payload_bytes = event.payload or b""
    if payload_bytes:
        event_dict["payload_length"] = len(payload_bytes)

    header_bytes = json.dumps(event_dict, ensure_ascii=False).encode("utf-8") + b"\n"
    return header_bytes + data_bytes + payload_bytes


# Usage: decode a single WyomingEvent from a binary file-like object such as a socket makefile.
# Parameters: reader - a binary object supporting readline and read.
# Return: a WyomingEvent when a full event is available, or None on EOF.
def decode_event(reader: BinaryIO) -> WyomingEvent | None:
    """Read and decode one Wyoming event from a binary stream."""

    json_line = reader.readline()
    if not json_line:
        return None

    header = json.loads(json_line)
    data_length = int(header.get("data_length", 0) or 0)
    payload_length = int(header.get("payload_length", 0) or 0)

    data: dict[str, Any] = dict(header.get("data", {}))
    if data_length > 0:
        data_bytes = read_exactly(reader, data_length)
        data.update(json.loads(data_bytes.decode("utf-8")))

    payload: bytes | None = None
    if payload_length > 0:
        payload = read_exactly(reader, payload_length)

    return WyomingEvent(type=str(header["type"]), data=data, payload=payload)


# Usage: read a fixed number of bytes from a binary stream, retrying until the count is satisfied or EOF occurs.
# Parameters: reader - a binary object supporting read; length - the exact byte count required.
# Return: the requested bytes, or raises EOFError if the stream ends too early.
def read_exactly(reader: BinaryIO, length: int) -> bytes:
    """Read an exact number of bytes from a binary stream."""

    buffer = bytearray()
    while len(buffer) < length:
        chunk = reader.read(length - len(buffer))
        if not chunk:
            raise EOFError(f"Expected {length} bytes but the stream ended early")
        buffer.extend(chunk)

    return bytes(buffer)


# Usage: decode a Wyoming event from raw bytes during tests without opening sockets.
# Parameters: raw_bytes - a complete encoded event payload.
# Return: the decoded WyomingEvent instance.
def decode_event_bytes(raw_bytes: bytes) -> WyomingEvent:
    """Decode a Wyoming event directly from an in-memory bytes buffer."""

    decoded_event = decode_event(io.BytesIO(raw_bytes))
    if decoded_event is None:
        raise EOFError("No Wyoming event bytes were available for decoding")

    return decoded_event
