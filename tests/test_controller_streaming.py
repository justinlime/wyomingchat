"""Tests for the controller's streaming sentence-synthesis flow."""

from __future__ import annotations

from wyomingchat import controller as controller_module
from wyomingchat.audio import AudioCaptureStream, AudioDeviceCatalog, MultiOutputPlayer
from wyomingchat.constants import STATE_LISTENING
from wyomingchat.controller import BridgeController
from wyomingchat.storage import JsonConfigStore
from wyomingchat.streaming import StreamingTranscriptChunker


class FakeTtsSession:
    """Record synthesis requests issued by the controller without touching the network."""

    created_sessions: list[dict] = []

    def __init__(self, endpoint, text, voice, **callbacks) -> None:
        self.text = text
        self.endpoint = endpoint
        self.started = False
        FakeTtsSession.created_sessions.append({"endpoint": endpoint, "text": text, "voice": voice})

    def start(self) -> None:
        self.started = True

    def close(self) -> None:
        pass

    def wait_closed(self, timeout: float = 1.0) -> None:
        del timeout
        pass


def build_controller(tmp_path) -> BridgeController:
    """Create a controller wired to stub services for flow testing."""

    store = JsonConfigStore(config_path=tmp_path / "config.json")
    catalog = AudioDeviceCatalog()
    controller = BridgeController(
        store=store,
        catalog=catalog,
        capture=AudioCaptureStream(catalog),
        player=MultiOutputPlayer(catalog),
    )
    controller._stt_generation = 1
    controller._chunker = StreamingTranscriptChunker()
    return controller


# Usage: verify that confirmed sentences from streaming partials each start a TTS synthesis request.
# Parameters: tmp_path - pytest fixture; monkeypatch - pytest fixture for swapping the TTS client.
# Return: None.
def test_partial_transcripts_dispatch_sentence_synthesis(tmp_path, monkeypatch) -> None:
    """Ensure each stable completed sentence triggers its own synthesis request."""

    FakeTtsSession.created_sessions = []
    monkeypatch.setattr(controller_module, "TextToSpeechSession", FakeTtsSession)

    controller = build_controller(tmp_path)
    controller._state = STATE_LISTENING

    controller._apply_partial_transcript(1, "Turn on the lights. Set the volume.")
    assert FakeTtsSession.created_sessions == []

    controller._apply_partial_transcript(1, "Turn on the lights. Set the volume. Thank you")
    assert [session["text"] for session in FakeTtsSession.created_sessions] == [
        "Turn on the lights.",
        "Set the volume.",
    ]


# Usage: verify that the transcript tail is synthesized when the STT session completes.
# Parameters: tmp_path - pytest fixture; monkeypatch - pytest fixture for swapping the TTS client.
# Return: None.
def test_stt_complete_synthesizes_tail_sentence(tmp_path, monkeypatch) -> None:
    """Ensure the un-bounded tail of the final transcript is synthesized at utterance end."""

    FakeTtsSession.created_sessions = []
    monkeypatch.setattr(controller_module, "TextToSpeechSession", FakeTtsSession)

    controller = build_controller(tmp_path)
    controller._state = STATE_LISTENING
    controller._apply_partial_transcript(1, "Turn on the lights. Set the volume.")
    controller._apply_partial_transcript(1, "Turn on the lights. Set the volume. Thank you")

    controller._pending_tts_text = "Turn on the lights. Set the volume. Thank you"
    controller._handle_stt_complete(1)

    texts = [session["text"] for session in FakeTtsSession.created_sessions]
    assert texts == [
        "Turn on the lights.",
        "Set the volume.",
        "Thank you",
    ]


# Usage: verify that disabling streaming synthesis restores the single whole-utterance request.
# Parameters: tmp_path - pytest fixture; monkeypatch - pytest fixture for swapping the TTS client.
# Return: None.
def test_stt_complete_without_streaming_uses_single_request(tmp_path, monkeypatch) -> None:
    """Ensure the legacy whole-text synthesis path is used when streaming is disabled."""

    FakeTtsSession.created_sessions = []
    monkeypatch.setattr(controller_module, "TextToSpeechSession", FakeTtsSession)

    controller = build_controller(tmp_path)
    controller._config.streaming_synthesis = False
    controller._state = STATE_LISTENING
    controller._apply_partial_transcript(1, "Turn on the lights. Set the volume.")

    controller._pending_tts_text = "Turn on the lights. Set the volume."
    controller._handle_stt_complete(1)

    assert [session["text"] for session in FakeTtsSession.created_sessions] == [
        "Turn on the lights. Set the volume."
    ]


# Usage: verify that the silence timeout slider updates the live detector immediately.
# Parameters: tmp_path - pytest fixture.
# Return: None.
def test_set_stop_silence_ms_updates_live_detector(tmp_path) -> None:
    """Ensure the config value and live VAD hangover both reflect the new timeout."""

    controller = build_controller(tmp_path)
    controller._voice_detector = controller_module.OpenMicVoiceDetector(
        controller_module.AudioFormatSpec(),
    )
    controller._voice_detector.set_stop_silence_frames(40)

    controller.set_stop_silence_ms(4000)

    assert controller.config.stop_silence_ms == 4000
    assert controller._voice_detector._stop_silence_frames == 125  # 4000ms / 32ms
