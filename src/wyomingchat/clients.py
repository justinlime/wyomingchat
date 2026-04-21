"""Wyoming TCP client implementations for speech-to-text and text-to-speech."""

from __future__ import annotations

import queue
import socket
import threading
from dataclasses import dataclass
from typing import Callable

from .audio import AudioFormatSpec
from .config import ServiceEndpoint
from .wyoming_protocol import WyomingEvent, decode_event, encode_event


@dataclass(slots=True)
class ClientCallbacks:
    """Group callback hooks used by worker-style Wyoming client sessions."""

    on_error: Callable[[str], None]
    on_complete: Callable[[], None]


# Usage: build the shared Wyoming audio metadata dictionary sent with audio-start and audio-chunk events.
# Parameters: format_spec - the raw PCM format that describes the stream; timestamp - optional stream timestamp in milliseconds.
# Return: a dictionary suitable for use as Wyoming event data.
def build_audio_metadata(format_spec: AudioFormatSpec, timestamp: int | None = None) -> dict[str, int]:
    """Return a Wyoming audio metadata dictionary for the supplied PCM format."""

    metadata = {
        "rate": format_spec.rate,
        "width": format_spec.width,
        "channels": format_spec.channels,
    }
    if timestamp is not None:
        metadata["timestamp"] = timestamp
    return metadata


class WyomingTcpConnection:
    """Manage a blocking TCP connection that sends and receives Wyoming events."""

    # Usage: create a connection object for a specific Wyoming TCP endpoint.
    # Parameters: endpoint - the host and port of the remote Wyoming service.
    # Return: None.
    def __init__(self, endpoint: ServiceEndpoint) -> None:
        """Initialize a Wyoming TCP connection wrapper."""

        self._endpoint = endpoint
        self._socket: socket.socket | None = None
        self._reader = None
        self._send_lock = threading.Lock()

    # Usage: open the TCP socket and create the binary reader used for event decoding.
    # Parameters: timeout - the socket timeout in seconds applied to connect and I/O operations.
    # Return: None.
    def connect(self, timeout: float = 10.0) -> None:
        """Open the underlying TCP socket to the Wyoming service."""

        self._socket = socket.create_connection((self._endpoint.host, self._endpoint.port), timeout=timeout)
        self._socket.settimeout(timeout)
        self._reader = self._socket.makefile("rb")

    # Usage: send one Wyoming event over the active TCP socket.
    # Parameters: event - the WyomingEvent that should be serialized and transmitted.
    # Return: None.
    def send_event(self, event: WyomingEvent) -> None:
        """Serialize and send a Wyoming event over the TCP socket."""

        if self._socket is None:
            raise RuntimeError("The Wyoming TCP connection is not open")

        with self._send_lock:
            self._socket.sendall(encode_event(event))

    # Usage: report whether the underlying TCP socket has been opened successfully.
    # Parameters: none.
    # Return: True when the socket exists, otherwise False.
    def is_connected(self) -> bool:
        """Return whether the underlying TCP socket is currently open."""

        return self._socket is not None and self._reader is not None

    # Usage: receive one Wyoming event from the active TCP connection.
    # Parameters: none.
    # Return: the decoded WyomingEvent, or None if the stream reached EOF.
    def receive_event(self) -> WyomingEvent | None:
        """Receive and decode one Wyoming event from the TCP socket."""

        if self._reader is None:
            raise RuntimeError("The Wyoming TCP connection is not open")

        return decode_event(self._reader)

    # Usage: close the TCP socket and any file objects created for decoding.
    # Parameters: none.
    # Return: None.
    def close(self) -> None:
        """Close the Wyoming TCP connection and release socket resources."""

        if self._reader is not None:
            try:
                self._reader.close()
            except OSError:
                pass
            self._reader = None

        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None


class SpeechToTextSession:
    """Stream microphone audio to a Wyoming STT server and receive transcript updates."""

    # Usage: create a speech-to-text session for one microphone capture cycle.
    # Parameters: endpoint - the Wyoming STT service address; audio_format - the PCM format that will be streamed; on_partial - callback for transcript-chunk updates; on_final - callback for the final transcript; on_error - callback for terminal errors; on_complete - callback when the session finishes.
    # Return: None.
    def __init__(
        self,
        endpoint: ServiceEndpoint,
        audio_format: AudioFormatSpec,
        on_partial: Callable[[str], None],
        on_final: Callable[[str], None],
        on_error: Callable[[str], None],
        on_complete: Callable[[], None],
    ) -> None:
        """Initialize a Wyoming speech-to-text session."""

        self._endpoint = endpoint
        self._audio_format = audio_format
        self._on_partial = on_partial
        self._on_final = on_final
        self._callbacks = ClientCallbacks(on_error=on_error, on_complete=on_complete)
        self._connection = WyomingTcpConnection(endpoint)
        self._write_queue: queue.Queue[WyomingEvent | None] = queue.Queue()
        self._writer_thread: threading.Thread | None = None
        self._reader_thread: threading.Thread | None = None
        self._completed = threading.Event()
        self._closing = threading.Event()
        self._connected = threading.Event()
        self._partial_chunks: list[str] = []

    # Usage: start the reader and writer worker threads without blocking the Qt GUI thread on network setup.
    # Parameters: none.
    # Return: None.
    def start(self) -> None:
        """Start background workers for the STT session and queue initial events."""

        self._reader_thread = threading.Thread(target=self._read_loop, name="stt-reader", daemon=True)
        self._writer_thread = threading.Thread(target=self._write_loop, name="stt-writer", daemon=True)
        self._reader_thread.start()
        self._writer_thread.start()
        self._write_queue.put(WyomingEvent(type="transcribe", data={}))
        self._write_queue.put(
            WyomingEvent(type="audio-start", data=build_audio_metadata(self._audio_format))
        )

    # Usage: enqueue one microphone PCM chunk for transmission to the STT server.
    # Parameters: chunk - the raw PCM bytes captured from the microphone.
    # Return: None.
    def send_audio_chunk(self, chunk: bytes) -> None:
        """Queue one microphone audio chunk for STT transmission."""

        if self._closing.is_set() or not chunk:
            return

        self._write_queue.put(
            WyomingEvent(
                type="audio-chunk",
                data=build_audio_metadata(self._audio_format),
                payload=chunk,
            )
        )

    # Usage: indicate that the microphone stream has ended and flush an audio-stop event.
    # Parameters: none.
    # Return: None.
    def finish(self) -> None:
        """Signal the end of microphone audio for the current STT session."""

        if self._closing.is_set():
            return

        self._closing.set()
        self._write_queue.put(WyomingEvent(type="audio-stop", data={}))
        self._write_queue.put(None)

    # Usage: force-close the STT session and release its socket resources.
    # Parameters: none.
    # Return: None.
    def close(self) -> None:
        """Close the STT session regardless of its current stage."""

        self._closing.set()
        self._write_queue.put(None)
        self._connection.close()

    # Usage: open the STT connection and send queued Wyoming events from a background thread.
    # Parameters: none.
    # Return: None.
    def _write_loop(self) -> None:
        """Open the STT socket and drain the writer queue without blocking the GUI thread."""

        try:
            self._connection.connect()
            self._connected.set()
            while True:
                event = self._write_queue.get()
                if event is None:
                    return
                self._connection.send_event(event)
        except OSError as exc:
            self._connected.set()
            self._report_error(f"STT send failed: {exc}")
            self.close()

    # Usage: receive transcript events from the remote STT service until a final result or error occurs.
    # Parameters: none.
    # Return: None.
    def _read_loop(self) -> None:
        """Wait for the socket to connect and then read transcript events from the STT service."""

        try:
            self._connected.wait(timeout=10.0)
            if not self._connection.is_connected() or self._completed.is_set():
                return

            while not self._completed.is_set():
                event = self._connection.receive_event()
                if event is None:
                    break

                if event.type == "transcript-start":
                    self._partial_chunks.clear()
                    continue

                if event.type == "transcript-chunk":
                    chunk_text = str(event.data.get("text", ""))
                    if chunk_text:
                        self._partial_chunks.append(chunk_text)
                        self._on_partial("".join(self._partial_chunks))
                    continue

                if event.type == "transcript":
                    final_text = str(event.data.get("text", ""))
                    self._on_final(final_text)
                    self._completed.set()
                    break

                if event.type == "transcript-stop":
                    if self._partial_chunks:
                        self._on_final("".join(self._partial_chunks))
                    self._completed.set()
                    break
        except (EOFError, OSError) as exc:
            if not self._closing.is_set():
                self._report_error(f"STT receive failed: {exc}")
        finally:
            self._connection.close()
            self._callbacks.on_complete()

    # Usage: forward a terminal session error to the controller only once.
    # Parameters: message - the human-readable error string to surface.
    # Return: None.
    def _report_error(self, message: str) -> None:
        """Emit a terminal STT error message if the session has not already finished."""

        if self._completed.is_set():
            return

        self._completed.set()
        self._callbacks.on_error(message)


class TextToSpeechSession:
    """Submit text to a Wyoming TTS server and stream back raw PCM audio."""

    # Usage: create a text-to-speech session for one synthesized reply.
    # Parameters: endpoint - the Wyoming TTS service address; text - the text that should be synthesized; on_audio_start - callback with the returned PCM format; on_audio_chunk - callback for streamed audio bytes; on_error - callback for terminal errors; on_complete - callback when synthesis finishes.
    # Return: None.
    def __init__(
        self,
        endpoint: ServiceEndpoint,
        text: str,
        on_audio_start: Callable[[AudioFormatSpec], None],
        on_audio_chunk: Callable[[bytes], None],
        on_error: Callable[[str], None],
        on_complete: Callable[[], None],
    ) -> None:
        """Initialize a Wyoming text-to-speech session."""

        self._endpoint = endpoint
        self._text = text
        self._on_audio_start = on_audio_start
        self._on_audio_chunk = on_audio_chunk
        self._callbacks = ClientCallbacks(on_error=on_error, on_complete=on_complete)
        self._connection = WyomingTcpConnection(endpoint)
        self._reader_thread: threading.Thread | None = None
        self._completed = threading.Event()

    # Usage: begin synthesis in a background thread so network setup never blocks the Qt GUI thread.
    # Parameters: none.
    # Return: None.
    def start(self) -> None:
        """Start the background TTS worker thread without blocking the GUI thread."""

        self._reader_thread = threading.Thread(target=self._read_loop, name="tts-reader", daemon=True)
        self._reader_thread.start()

    # Usage: close the TTS session and release socket resources.
    # Parameters: none.
    # Return: None.
    def close(self) -> None:
        """Close the TTS session and release any open connection resources."""

        self._completed.set()
        self._connection.close()

    # Usage: connect to the remote TTS service and read audio events until synthesis completes.
    # Parameters: none.
    # Return: None.
    def _read_loop(self) -> None:
        """Open the TTS socket inside the worker thread and forward streamed audio callbacks."""

        try:
            self._connection.connect()
            self._connection.send_event(WyomingEvent(type="synthesize", data={"text": self._text}))
            while not self._completed.is_set():
                event = self._connection.receive_event()
                if event is None:
                    break

                if event.type == "audio-start":
                    self._on_audio_start(
                        AudioFormatSpec(
                            rate=int(event.data.get("rate", 22050)),
                            width=int(event.data.get("width", 2)),
                            channels=int(event.data.get("channels", 1)),
                        )
                    )
                    continue

                if event.type == "audio-chunk" and event.payload:
                    self._on_audio_chunk(event.payload)
                    continue

                if event.type == "audio-stop":
                    self._completed.set()
                    break
        except (EOFError, OSError) as exc:
            if not self._completed.is_set():
                self._callbacks.on_error(f"TTS receive failed: {exc}")
        finally:
            self._connection.close()
            self._callbacks.on_complete()
