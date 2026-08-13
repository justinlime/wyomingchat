"""Tests for Wyoming client helpers used by the bridge controller."""

from __future__ import annotations

from wyomingchat.audio_types import AudioFormatSpec
from wyomingchat.clients import (
    SpeechToTextSession,
    TextToSpeechSession,
    build_tts_synthesize_event_data,
    parse_tts_streaming_supported_from_info,
    parse_tts_voices_from_info,
)
from wyomingchat.config import ServiceEndpoint, TtsVoiceConfig
from wyomingchat.wyoming_protocol import WyomingEvent


class FakeWyomingConnection:
    """Provide a controllable Wyoming connection stub for testing STT session read/write behavior."""

    # Usage: create a fake connection with a predefined sequence of events returned by receive_event.
    # Parameters: received_events - ordered Wyoming events or None values returned to the reader loop.
    # Return: None.
    def __init__(self, received_events: list[WyomingEvent | None] | None = None) -> None:
        """Initialize the fake connection with optional queued receive events."""

        self._received_events = list(received_events or [])
        self.sent_events: list[WyomingEvent] = []
        self.connected = False
        self.closed = False
        self.shutdown_write_called = False

    # Usage: emulate opening the underlying Wyoming TCP connection.
    # Parameters: timeout - ignored test timeout value.
    # Return: None.
    def connect(self, timeout: float = 10.0) -> None:
        """Mark the fake connection as connected."""

        del timeout
        self.connected = True

    # Usage: emulate sending one Wyoming event over the fake connection.
    # Parameters: event - the Wyoming event that should be recorded.
    # Return: None.
    def send_event(self, event: WyomingEvent) -> None:
        """Record one sent Wyoming event for later assertions."""

        self.sent_events.append(event)

    # Usage: emulate reading one Wyoming event from the fake connection.
    # Parameters: none.
    # Return: the next queued event value, or None when the queue is exhausted.
    def receive_event(self) -> WyomingEvent | None:
        """Return the next queued Wyoming event from the fake connection."""

        if not self._received_events:
            return None
        return self._received_events.pop(0)

    # Usage: report whether the fake connection is currently considered open.
    # Parameters: none.
    # Return: True when the fake connection is open, otherwise False.
    def is_connected(self) -> bool:
        """Return whether the fake connection should be treated as connected."""

        return self.connected and not self.closed

    # Usage: emulate half-closing the write side of the socket after the client finishes sending audio.
    # Parameters: none.
    # Return: None.
    def shutdown_write(self) -> None:
        """Record that the fake connection write side was shut down."""

        self.shutdown_write_called = True

    # Usage: emulate closing the full connection.
    # Parameters: none.
    # Return: None.
    def close(self) -> None:
        """Mark the fake connection as fully closed."""

        self.closed = True
        self.connected = False


# Usage: build a minimal STT session for unit tests while allowing its Wyoming connection to be swapped with a fake.
# Parameters: on_final - callback that receives the session's final transcript text; on_error - callback that receives terminal errors.
# Return: a SpeechToTextSession configured with a small default PCM format and no-op partial/complete callbacks.
def build_test_stt_session(
    on_final,
    on_error,
) -> SpeechToTextSession:
    """Return a SpeechToTextSession configured for isolated unit tests."""

    return SpeechToTextSession(
        endpoint=ServiceEndpoint(host="127.0.0.1", port=10300),
        audio_format=AudioFormatSpec(rate=16000, width=2, channels=1),
        on_partial=lambda text: None,
        on_final=on_final,
        on_error=on_error,
        on_complete=lambda: None,
    )


# Usage: verify that a Wyoming TTS program using the modern `voices` field expands into concrete selectable voice options.
# Parameters: none.
# Return: None.
def test_parse_tts_voices_from_info_reads_tts_program_voices() -> None:
    """Ensure Wyoming TTS programs advertising `voices` populate concrete selectable options."""

    voices = parse_tts_voices_from_info(
        {
            "tts": [
                {
                    "name": "kokoro-server",
                    "voices": [
                        {
                            "name": "Hank",
                            "languages": ["en-US"],
                        },
                        {
                            "name": "Victor",
                            "languages": ["en-US"],
                        },
                        {
                            "name": "Spy",
                            "languages": ["en-US"],
                        },
                    ],
                }
            ]
        }
    )

    assert voices == [
        TtsVoiceConfig(name="Hank", language="en-US", speaker=""),
        TtsVoiceConfig(name="Spy", language="en-US", speaker=""),
        TtsVoiceConfig(name="Victor", language="en-US", speaker=""),
    ]


# Usage: verify that a Wyoming TTS voice with multiple speakers expands into one selectable option per speaker.
# Parameters: none.
# Return: None.
def test_parse_tts_voices_from_info_flattens_voice_speakers() -> None:
    """Ensure a multi-speaker Wyoming voice becomes one selectable option per speaker."""

    voices = parse_tts_voices_from_info(
        {
            "tts": [
                {
                    "name": "fatterqwen",
                    "voices": [
                        {
                            "name": "fatterqwen",
                            "speakers": [{"name": "Hank"}, {"name": "Victor"}, {"name": "Spy"}],
                        }
                    ],
                }
            ]
        }
    )

    assert voices == [
        TtsVoiceConfig(name="fatterqwen", language="", speaker="Hank"),
        TtsVoiceConfig(name="fatterqwen", language="", speaker="Spy"),
        TtsVoiceConfig(name="fatterqwen", language="", speaker="Victor"),
    ]


# Usage: verify that older model-shaped info payloads still expand into concrete selectable voice combinations.
# Parameters: none.
# Return: None.
def test_parse_tts_voices_from_info_flattens_legacy_models_and_speakers() -> None:
    """Ensure older model-shaped TTS payloads remain supported for backward compatibility."""

    voices = parse_tts_voices_from_info(
        {
            "tts": [
                {
                    "models": [
                        {
                            "name": "kokoro",
                            "languages": ["en", "es"],
                            "speakers": [{"name": "bella"}, {"name": "adam"}],
                        },
                        {
                            "name": "piper",
                            "languages": ["en-US"],
                        },
                    ]
                }
            ]
        }
    )

    assert voices == [
        TtsVoiceConfig(name="kokoro", language="en", speaker="adam"),
        TtsVoiceConfig(name="kokoro", language="en", speaker="bella"),
        TtsVoiceConfig(name="kokoro", language="es", speaker="adam"),
        TtsVoiceConfig(name="kokoro", language="es", speaker="bella"),
        TtsVoiceConfig(name="piper", language="en-US", speaker=""),
    ]


# Usage: verify that voice discovery remains backward compatible with direct model-shaped payloads emitted by simpler or older servers.
# Parameters: none.
# Return: None.
def test_parse_tts_voices_from_info_accepts_direct_model_shape() -> None:
    """Ensure direct model-shaped TTS payloads still produce selectable voices."""

    voices = parse_tts_voices_from_info(
        {
            "tts": [
                {
                    "name": "piper",
                    "languages": ["en-US"],
                    "speakers": [{"name": "amy"}],
                }
            ]
        }
    )

    assert voices == [TtsVoiceConfig(name="piper", language="en-US", speaker="amy")]


# Usage: verify that the STT writer thread half-closes the socket after audio-stop so the reader can still receive the final transcript.
# Parameters: none.
# Return: None.
def test_stt_write_loop_shutdowns_write_side_without_closing_connection() -> None:
    """Ensure the STT writer does not fully close the shared connection immediately after audio-stop."""

    session = build_test_stt_session(on_final=lambda text: None, on_error=lambda message: None)
    fake_connection = FakeWyomingConnection()
    session._connection = fake_connection
    session._write_queue.put(WyomingEvent(type="transcribe", data={}))
    session._write_queue.put(
        WyomingEvent(type="audio-start", data={"rate": 16000, "width": 2, "channels": 1})
    )
    session.finish()

    session._write_loop()

    assert [event.type for event in fake_connection.sent_events] == [
        "transcribe",
        "audio-start",
        "audio-stop",
    ]
    assert fake_connection.shutdown_write_called is True
    assert fake_connection.closed is False


# Usage: verify that transcript-stop without any transcript chunks still produces an explicit empty final result instead of silently idling.
# Parameters: none.
# Return: None.
def test_stt_read_loop_emits_empty_final_on_transcript_stop_without_chunks() -> None:
    """Ensure transcript-stop with no chunks still finalizes the STT session explicitly."""

    final_texts: list[str] = []
    errors: list[str] = []
    session = build_test_stt_session(on_final=final_texts.append, on_error=errors.append)
    fake_connection = FakeWyomingConnection([WyomingEvent(type="transcript-stop", data={})])
    fake_connection.connected = True
    session._connection = fake_connection
    session._connected.set()

    session._read_loop()

    assert final_texts == [""]
    assert errors == []


# Usage: verify that the STT reader falls back to the last partial transcript when the server closes after audio-stop without a final transcript event.
# Parameters: none.
# Return: None.
def test_stt_read_loop_uses_partial_transcript_when_server_closes_after_finish() -> None:
    """Ensure a graceful post-finish EOF still produces the best available transcript instead of stalling silently."""

    final_texts: list[str] = []
    errors: list[str] = []
    session = build_test_stt_session(on_final=final_texts.append, on_error=errors.append)
    session.finish()
    fake_connection = FakeWyomingConnection(
        [
            WyomingEvent(type="transcript-start", data={}),
            WyomingEvent(type="transcript-chunk", data={"text": "repeat phrase"}),
            None,
        ]
    )
    fake_connection.connected = True
    session._connection = fake_connection
    session._connected.set()

    session._read_loop()

    assert final_texts == ["repeat phrase"]
    assert errors == []


# Usage: build a minimal TTS session for unit tests while allowing its Wyoming connection to be swapped with a fake.
# Parameters: text - the text to synthesize; streaming - whether the session should use the streaming synthesize protocol; received_events - events the fake connection returns to the reader loop.
# Return: a TextToSpeechSession configured with no-op audio/complete callbacks and an error recorder.
def build_test_tts_session(
    text: str = "hello world",
    streaming: bool = False,
    received_events: list[WyomingEvent | None] | None = None,
):
    """Return a TextToSpeechSession configured for isolated unit tests."""

    audio_starts: list[AudioFormatSpec] = []
    audio_chunks: list[bytes] = []
    errors: list[str] = []
    completions: list[bool] = []

    session = TextToSpeechSession(
        endpoint=ServiceEndpoint(host="127.0.0.1", port=10301),
        text=text,
        voice=None,
        on_audio_start=audio_starts.append,
        on_audio_chunk=audio_chunks.append,
        on_error=errors.append,
        on_complete=lambda: completions.append(True),
        streaming=streaming,
    )
    session._connection = FakeWyomingConnection(received_events)
    return session, audio_starts, audio_chunks, errors, completions


# Usage: verify that a Wyoming info payload advertising streaming synthesis support is detected.
# Parameters: none.
# Return: None.
def test_parse_tts_streaming_supported_from_info_detects_advertised_support() -> None:
    """Ensure the streaming-synthesis capability flag is read from TTS programs."""

    assert parse_tts_streaming_supported_from_info(
        {
            "tts": [
                {
                    "name": "kokoro-server",
                    "supports_synthesize_streaming": True,
                    "voices": [],
                }
            ]
        }
    ) is True


# Usage: verify that an info payload without the streaming flag is treated as non-streaming.
# Parameters: none.
# Return: None.
def test_parse_tts_streaming_supported_from_info_defaults_to_false() -> None:
    """Ensure older info payloads without the flag fall back to single-shot synthesis."""

    assert parse_tts_streaming_supported_from_info({"tts": [{"name": "piper", "voices": []}]}) is False
    assert parse_tts_streaming_supported_from_info({}) is False
    assert parse_tts_streaming_supported_from_info({"tts": "not-a-list"}) is False


# Usage: verify that a streaming TTS session sends the full streaming synthesize event sequence.
# Parameters: none.
# Return: None.
def test_tts_streaming_session_sends_streaming_event_sequence() -> None:
    """Ensure streaming sessions send synthesize-start/chunk/stop with the back-compat synthesize event."""

    session, _, _, _, _ = build_test_tts_session(
        text="hello world",
        streaming=True,
        received_events=[
            WyomingEvent(type="audio-start", data={"rate": 16000, "width": 2, "channels": 1}),
            WyomingEvent(type="audio-stop", data={}),
            WyomingEvent(type="synthesize-stopped", data={}),
        ],
    )
    session._connection.connected = True

    session._read_loop()

    assert [event.type for event in session._connection.sent_events] == [
        "synthesize-start",
        "synthesize-chunk",
        "synthesize",
        "synthesize-stop",
    ]
    assert session._connection.sent_events[0].data == {}
    assert session._connection.sent_events[1].data == {"text": "hello world"}
    assert session._connection.sent_events[2].data == {"text": "hello world"}
    assert session._connection.sent_events[3].data == {}


# Usage: verify that a streaming TTS session survives multiple audio groups and terminates on synthesize-stopped.
# Parameters: none.
# Return: None.
def test_tts_streaming_session_handles_multiple_audio_streams() -> None:
    """Ensure streaming sessions continue past per-sentence audio-stop events until synthesize-stopped."""

    session, audio_starts, audio_chunks, errors, completions = build_test_tts_session(
        streaming=True,
        received_events=[
            WyomingEvent(type="audio-start", data={"rate": 16000, "width": 2, "channels": 1}),
            WyomingEvent(type="audio-chunk", data={}, payload=b"first"),
            WyomingEvent(type="audio-stop", data={}),
            WyomingEvent(type="audio-start", data={"rate": 16000, "width": 2, "channels": 1}),
            WyomingEvent(type="audio-chunk", data={}, payload=b"second"),
            WyomingEvent(type="audio-stop", data={}),
            WyomingEvent(type="synthesize-stopped", data={}),
        ],
    )
    session._connection.connected = True

    session._read_loop()

    assert session._completed.is_set()
    assert [chunk for chunk in audio_chunks] == [b"first", b"second"]
    assert len(audio_starts) == 1, "only the first audio-start should be forwarded to playback"
    assert errors == []
    assert completions == [True]


# Usage: verify that a streaming TTS session forwards the selected voice on synthesize-start and the back-compat synthesize event.
# Parameters: none.
# Return: None.
def test_tts_streaming_session_includes_selected_voice() -> None:
    """Ensure the streaming handshake carries the voice selection where the protocol expects it."""

    session, _, _, _, _ = build_test_tts_session(text="hi", streaming=True)
    session._voice = TtsVoiceConfig(name="kokoro", language="en", speaker="bella")
    session._connection.connected = True

    session._read_loop()

    assert session._connection.sent_events[0].data == {
        "voice": {"name": "kokoro", "language": "en", "speaker": "bella"}
    }
    assert session._connection.sent_events[2].data["voice"] == {
        "name": "kokoro",
        "language": "en",
        "speaker": "bella",
    }


# Usage: verify that a single-shot TTS session still terminates on the first audio-stop.
# Parameters: none.
# Return: None.
def test_tts_single_shot_session_terminates_on_first_audio_stop() -> None:
    """Ensure non-streaming sessions keep the original audio-stop completion behavior."""

    session, audio_starts, audio_chunks, errors, completions = build_test_tts_session(
        streaming=False,
        received_events=[
            WyomingEvent(type="audio-start", data={"rate": 22050, "width": 2, "channels": 1}),
            WyomingEvent(type="audio-chunk", data={}, payload=b"data"),
            WyomingEvent(type="audio-stop", data={}),
        ],
    )
    session._connection.connected = True

    session._read_loop()

    assert session._completed.is_set()
    assert [event.type for event in session._connection.sent_events] == ["synthesize"]
    assert audio_starts == [AudioFormatSpec(rate=22050, width=2, channels=1)]
    assert audio_chunks == [b"data"]
    assert errors == []
    assert completions == [True]


# Usage: verify that synthesize requests include the selected Wyoming voice payload only when a voice is configured.
# Parameters: none.
# Return: None.
def test_build_tts_synthesize_event_data_includes_selected_voice() -> None:
    """Ensure synthesize request data forwards the selected voice fields to the server."""

    event_data = build_tts_synthesize_event_data(
        "hello world",
        TtsVoiceConfig(name="kokoro", language="en", speaker="bella"),
    )

    assert event_data == {
        "text": "hello world",
        "voice": {"name": "kokoro", "language": "en", "speaker": "bella"},
    }


# Usage: verify that synthesize requests omit the voice payload when the user has not selected a specific voice.
# Parameters: none.
# Return: None.
def test_build_tts_synthesize_event_data_omits_empty_voice_selection() -> None:
    """Ensure synthesize request data falls back to the server default voice when unset."""

    event_data = build_tts_synthesize_event_data("hello world", TtsVoiceConfig())

    assert event_data == {"text": "hello world"}
