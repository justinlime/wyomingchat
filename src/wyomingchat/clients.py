"""Wyoming TCP client implementations for speech-to-text and text-to-speech."""

from __future__ import annotations

import queue
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from .audio_types import AudioFormatSpec
from .config import ServiceEndpoint, TtsVoiceConfig
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


# Usage: flatten a Wyoming info payload into concrete selectable TTS voice combinations for the UI.
# Parameters: info_payload - the decoded data dictionary from an `info` Wyoming event.
# Return: a sorted list of unique TtsVoiceConfig values combining advertised voice names, languages, and speakers.
def parse_tts_voices_from_info(info_payload: dict[str, Any]) -> list[TtsVoiceConfig]:
    """Return concrete selectable TTS voices advertised by a Wyoming server info payload."""

    raw_tts_services = info_payload.get("tts", [])
    if not isinstance(raw_tts_services, list):
        return []

    discovered: list[TtsVoiceConfig] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for raw_service in raw_tts_services:
        if not isinstance(raw_service, dict):
            continue

        fallback_service_name = str(raw_service.get("name", "")).strip()
        raw_voice_entries = raw_service.get("voices", [])
        if not isinstance(raw_voice_entries, list) or not raw_voice_entries:
            raw_voice_entries = raw_service.get("models", [])
        if not isinstance(raw_voice_entries, list) or not raw_voice_entries:
            raw_voice_entries = [raw_service]

        for raw_voice in raw_voice_entries:
            if not isinstance(raw_voice, dict):
                continue

            voice_name = str(raw_voice.get("name", "")).strip() or fallback_service_name
            raw_languages = raw_voice.get("languages", raw_service.get("languages", []))
            raw_speakers = raw_voice.get("speakers", [])

            languages = [str(language).strip() for language in raw_languages if str(language).strip()]
            if not languages:
                languages = [""]

            speaker_names: list[str] = []
            if isinstance(raw_speakers, list):
                for raw_speaker in raw_speakers:
                    if isinstance(raw_speaker, dict):
                        speaker_name = str(raw_speaker.get("name", "")).strip()
                    else:
                        speaker_name = str(raw_speaker).strip()
                    if speaker_name:
                        speaker_names.append(speaker_name)
            if not speaker_names:
                speaker_names = [""]

            for language in languages:
                for speaker_name in speaker_names:
                    voice = TtsVoiceConfig(name=voice_name, language=language, speaker=speaker_name)
                    if not voice.is_configured():
                        continue
                    voice_key = (voice.name, voice.language, voice.speaker)
                    if voice_key in seen_keys:
                        continue
                    seen_keys.add(voice_key)
                    discovered.append(voice)

    return sorted(
        discovered,
        key=lambda voice: (
            voice.name.casefold(),
            voice.language.casefold(),
            voice.speaker.casefold(),
        ),
    )


# Usage: build the event data dictionary for a Wyoming synthesize request with an optional selected voice.
# Parameters: text - the text that should be synthesized; voice - the optional voice selection that should be requested from the TTS server.
# Return: a dictionary suitable for the `synthesize` Wyoming event data field.
def build_tts_synthesize_event_data(text: str, voice: TtsVoiceConfig | None = None) -> dict[str, Any]:
    """Return the Wyoming event data used for a single-shot TTS synthesize request."""

    request_data: dict[str, Any] = {"text": text}
    if voice is not None:
        voice_payload = voice.to_request_payload()
        if voice_payload is not None:
            request_data["voice"] = voice_payload
    return request_data


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

    # Usage: half-close the TCP socket for writing after the client finishes sending request events but still expects a response.
    # Parameters: none.
    # Return: None.
    def shutdown_write(self) -> None:
        """Shutdown the socket write side while keeping the read side open when possible."""

        if self._socket is None:
            return

        try:
            self._socket.shutdown(socket.SHUT_WR)
        except OSError:
            pass

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

    # Usage: create a speech-to-text session for one detected utterance.
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
        self._finish_requested = threading.Event()
        self._connected = threading.Event()
        self._complete_reported = threading.Event()
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
        self._write_queue.put(WyomingEvent(type="audio-start", data=build_audio_metadata(self._audio_format)))

    # Usage: enqueue one microphone PCM chunk for transmission to the STT server.
    # Parameters: chunk - the raw PCM bytes captured from the microphone.
    # Return: None.
    def send_audio_chunk(self, chunk: bytes) -> None:
        """Queue one microphone audio chunk for STT transmission."""

        if self._closing.is_set() or self._completed.is_set() or not chunk:
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

        if self._closing.is_set() or self._completed.is_set():
            return

        self._closing.set()
        self._finish_requested.set()
        self._write_queue.put(WyomingEvent(type="audio-stop", data={}))
        self._write_queue.put(None)

    # Usage: force-close the STT session, prevent any new network writes, and release socket resources.
    # Parameters: none.
    # Return: None.
    def close(self) -> None:
        """Abort the STT session regardless of its current stage."""

        if self._completed.is_set():
            return

        self._completed.set()
        self._closing.set()
        self._drain_write_queue()
        self._write_queue.put(None)
        self._connection.close()

    # Usage: wait briefly for the STT worker threads to stop after close or finish has been requested.
    # Parameters: timeout - the maximum number of seconds to wait for both worker threads combined.
    # Return: None.
    def wait_closed(self, timeout: float = 1.0) -> None:
        """Join the STT worker threads for a short bounded period."""

        deadline = time.monotonic() + max(timeout, 0.0)
        for thread in (self._writer_thread, self._reader_thread):
            if thread is None or not thread.is_alive():
                continue
            remaining = max(0.0, deadline - time.monotonic())
            thread.join(timeout=remaining)

    # Usage: remove queued events that should never be sent once the session is being aborted.
    # Parameters: none.
    # Return: None.
    def _drain_write_queue(self) -> None:
        """Discard queued writer events without blocking the caller."""

        try:
            while True:
                self._write_queue.get_nowait()
        except queue.Empty:
            return

    # Usage: deliver a final STT transcript exactly once and mark the session as completed.
    # Parameters: text - the final transcript text that should be forwarded to the controller.
    # Return: None.
    def _complete_with_final_text(self, text: str) -> None:
        """Forward the final transcript to the controller and mark the STT session as completed."""

        if self._completed.is_set():
            return

        self._on_final(text)
        self._completed.set()

    # Usage: conclude a finished STT session when the server stops sending events without an explicit final transcript.
    # Parameters: reason - human-readable context describing why the session ended before a final transcript event arrived.
    # Return: None.
    def _handle_missing_final_after_finish(self, reason: str) -> None:
        """Fallback to partial transcript text after audio-stop or surface an error when no transcript exists."""

        if self._completed.is_set():
            return

        if self._partial_chunks:
            self._complete_with_final_text("".join(self._partial_chunks))
            return

        self._report_error(reason)

    # Usage: open the STT connection and send queued Wyoming events from a background thread.
    # Parameters: none.
    # Return: None.
    def _write_loop(self) -> None:
        """Open the STT socket and drain the writer queue without blocking the GUI thread."""

        close_connection = False
        try:
            if self._completed.is_set():
                return

            self._connection.connect()
            self._connected.set()
            if self._completed.is_set():
                close_connection = True
                return

            while not self._completed.is_set():
                event = self._write_queue.get()
                if event is None or self._completed.is_set():
                    if self._finish_requested.is_set() and not self._completed.is_set():
                        self._connection.shutdown_write()
                    else:
                        close_connection = True
                    return
                self._connection.send_event(event)
        except OSError as exc:
            close_connection = True
            self._connected.set()
            if not self._completed.is_set():
                self._report_error(f"STT send failed: {exc}")
        finally:
            if close_connection:
                self._connection.close()

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
                    if self._finish_requested.is_set():
                        self._handle_missing_final_after_finish(
                            "STT connection closed before a final transcript was received"
                        )
                    elif not self._completed.is_set():
                        self._report_error("STT connection closed before transcription completed")
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
                    self._complete_with_final_text(final_text)
                    break

                if event.type == "transcript-stop":
                    self._complete_with_final_text("".join(self._partial_chunks))
                    break
        except (EOFError, OSError) as exc:
            if self._completed.is_set():
                pass
            elif self._finish_requested.is_set():
                self._handle_missing_final_after_finish(f"STT receive failed after audio-stop: {exc}")
            else:
                self._report_error(f"STT receive failed: {exc}")
        finally:
            self._connection.close()
            self._report_complete_once()

    # Usage: forward a terminal session error to the controller only once.
    # Parameters: message - the human-readable error string to surface.
    # Return: None.
    def _report_error(self, message: str) -> None:
        """Emit a terminal STT error message if the session has not already finished."""

        if self._completed.is_set():
            return

        self._completed.set()
        self._callbacks.on_error(message)

    # Usage: invoke the completion callback exactly once no matter which worker thread exits first.
    # Parameters: none.
    # Return: None.
    def _report_complete_once(self) -> None:
        """Emit the session-complete callback exactly once."""

        if self._complete_reported.is_set():
            return

        self._complete_reported.set()
        self._callbacks.on_complete()


class TtsVoiceQuerySession:
    """Request Wyoming server capability info and extract selectable TTS voices."""

    # Usage: create a background describe/info query that asks a Wyoming server which TTS voices it supports.
    # Parameters: endpoint - the Wyoming TTS service address; on_result - callback receiving discovered selectable voices; on_error - callback for terminal query failures; on_complete - callback invoked exactly once when the worker exits.
    # Return: None.
    def __init__(
        self,
        endpoint: ServiceEndpoint,
        on_result: Callable[[list[TtsVoiceConfig]], None],
        on_error: Callable[[str], None],
        on_complete: Callable[[], None],
    ) -> None:
        """Initialize a voice-discovery query session."""

        self._endpoint = endpoint
        self._on_result = on_result
        self._callbacks = ClientCallbacks(on_error=on_error, on_complete=on_complete)
        self._connection = WyomingTcpConnection(endpoint)
        self._reader_thread: threading.Thread | None = None
        self._completed = threading.Event()
        self._complete_reported = threading.Event()

    # Usage: begin the describe/info query in a background thread so the Qt GUI remains responsive.
    # Parameters: none.
    # Return: None.
    def start(self) -> None:
        """Start the background voice-discovery worker thread."""

        self._reader_thread = threading.Thread(target=self._read_loop, name="tts-voice-query", daemon=True)
        self._reader_thread.start()

    # Usage: abort an in-flight voice query and close its socket resources.
    # Parameters: none.
    # Return: None.
    def close(self) -> None:
        """Abort the voice-discovery session and release any open socket resources."""

        self._completed.set()
        self._connection.close()

    # Usage: wait briefly for the background describe/info query to stop after close has been requested.
    # Parameters: timeout - the maximum number of seconds to wait for the worker thread.
    # Return: None.
    def wait_closed(self, timeout: float = 1.0) -> None:
        """Join the voice-discovery worker thread for a short bounded period."""

        if self._reader_thread is None or not self._reader_thread.is_alive():
            return

        self._reader_thread.join(timeout=max(timeout, 0.0))

    # Usage: connect to the server, send a Wyoming `describe` request, and return the discovered TTS voices.
    # Parameters: none.
    # Return: None.
    def _read_loop(self) -> None:
        """Query the Wyoming server for info and forward parsed TTS voice options."""

        try:
            if self._completed.is_set():
                return

            self._connection.connect()
            if self._completed.is_set():
                return

            self._connection.send_event(WyomingEvent(type="describe", data={}))
            while not self._completed.is_set():
                event = self._connection.receive_event()
                if event is None:
                    break

                if event.type != "info":
                    continue

                self._on_result(parse_tts_voices_from_info(event.data))
                self._completed.set()
                return

            if not self._completed.is_set():
                self._callbacks.on_error("TTS voice query completed without an info response")
                self._completed.set()
        except (EOFError, OSError) as exc:
            if not self._completed.is_set():
                self._callbacks.on_error(f"TTS voice query failed: {exc}")
                self._completed.set()
        finally:
            self._connection.close()
            self._report_complete_once()

    # Usage: invoke the completion callback exactly once when the voice-discovery worker exits.
    # Parameters: none.
    # Return: None.
    def _report_complete_once(self) -> None:
        """Emit the session-complete callback exactly once."""

        if self._complete_reported.is_set():
            return

        self._complete_reported.set()
        self._callbacks.on_complete()


class TextToSpeechSession:
    """Submit text to a Wyoming TTS server and stream back raw PCM audio."""

    # Usage: create a text-to-speech session for one synthesized reply.
    # Parameters: endpoint - the Wyoming TTS service address; text - the text that should be synthesized; voice - the optional Wyoming voice selection to request; on_audio_start - callback with the returned PCM format; on_audio_chunk - callback for streamed audio bytes; on_error - callback for terminal errors; on_complete - callback when synthesis finishes.
    # Return: None.
    def __init__(
        self,
        endpoint: ServiceEndpoint,
        text: str,
        voice: TtsVoiceConfig | None,
        on_audio_start: Callable[[AudioFormatSpec], None],
        on_audio_chunk: Callable[[bytes], None],
        on_error: Callable[[str], None],
        on_complete: Callable[[], None],
    ) -> None:
        """Initialize a Wyoming text-to-speech session."""

        self._endpoint = endpoint
        self._text = text
        self._voice = voice if voice is not None and voice.is_configured() else None
        self._on_audio_start = on_audio_start
        self._on_audio_chunk = on_audio_chunk
        self._callbacks = ClientCallbacks(on_error=on_error, on_complete=on_complete)
        self._connection = WyomingTcpConnection(endpoint)
        self._reader_thread: threading.Thread | None = None
        self._completed = threading.Event()
        self._complete_reported = threading.Event()

    # Usage: begin synthesis in a background thread so network setup never blocks the Qt GUI thread.
    # Parameters: none.
    # Return: None.
    def start(self) -> None:
        """Start the background TTS worker thread without blocking the GUI thread."""

        self._reader_thread = threading.Thread(target=self._read_loop, name="tts-reader", daemon=True)
        self._reader_thread.start()

    # Usage: close the TTS session, prevent any new synthesis request from being sent, and release socket resources.
    # Parameters: none.
    # Return: None.
    def close(self) -> None:
        """Abort the TTS session and release any open connection resources."""

        self._completed.set()
        self._connection.close()

    # Usage: wait briefly for the TTS worker thread to stop after close has been requested.
    # Parameters: timeout - the maximum number of seconds to wait for the worker thread.
    # Return: None.
    def wait_closed(self, timeout: float = 1.0) -> None:
        """Join the TTS worker thread for a short bounded period."""

        if self._reader_thread is None or not self._reader_thread.is_alive():
            return

        self._reader_thread.join(timeout=max(timeout, 0.0))

    # Usage: connect to the remote TTS service and read audio events until synthesis completes.
    # Parameters: none.
    # Return: None.
    def _read_loop(self) -> None:
        """Open the TTS socket inside the worker thread and forward streamed audio callbacks."""

        try:
            if self._completed.is_set():
                return

            self._connection.connect()
            if self._completed.is_set():
                return

            self._connection.send_event(
                WyomingEvent(
                    type="synthesize",
                    data=build_tts_synthesize_event_data(self._text, self._voice),
                )
            )
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
            self._report_complete_once()

    # Usage: invoke the completion callback exactly once when the TTS worker exits.
    # Parameters: none.
    # Return: None.
    def _report_complete_once(self) -> None:
        """Emit the session-complete callback exactly once."""

        if self._complete_reported.is_set():
            return

        self._complete_reported.set()
        self._callbacks.on_complete()
