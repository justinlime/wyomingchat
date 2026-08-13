"""Tests for the controller's TTS output handling, bridge pause, and live tuning setters."""

from __future__ import annotations

from wyomingchat import controller as controller_module
from wyomingchat.audio import AudioCaptureStream, AudioDeviceCatalog, MultiOutputPlayer
from wyomingchat.controller import BridgeController
from wyomingchat.storage import JsonConfigStore


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
    return controller


# Usage: verify that the TTS boost scales synthesized audio before it reaches the player.
# Parameters: tmp_path - pytest fixture.
# Return: None.
def test_tts_gain_amplifies_streamed_chunks(tmp_path) -> None:
    """Ensure the TTS boost slider scales streamed synthesized audio before playback."""

    from array import array

    from wyomingchat.audio_types import AudioFormatSpec
    from wyomingchat.vad import measure_pcm_level

    controller = build_controller(tmp_path)
    controller._config.tts_gain = 2.0
    controller._tts_generation = 1
    controller._tts_format_spec = AudioFormatSpec(rate=16000, width=2, channels=1)

    captured: list[bytes] = []
    controller._player.write_audio = lambda chunk: captured.append(bytes(chunk))

    chunk = array("h", [1000] * 480).tobytes()
    controller._handle_tts_audio_chunk(1, chunk)

    assert round(measure_pcm_level(captured[0], controller._tts_format_spec), 3) == 0.061


# Usage: verify that the bridge can be paused and resumed, and stays paused across config loads.
# Parameters: tmp_path - pytest fixture.
# Return: None.
def test_set_bridge_paused_stops_and_resumes(tmp_path) -> None:
    """Ensure pausing stops listening and resuming restarts the monitor."""

    controller = build_controller(tmp_path)

    controller.set_bridge_paused(True)
    assert controller._paused is True

    # Saving/loading configuration while paused must not restart the monitor.
    controller.load_configuration()
    assert controller._paused is True

    controller.set_bridge_paused(False)
    assert controller._paused is False


# Usage: verify that the TTS boost setter clamps and persists.
# Parameters: tmp_path - pytest fixture.
# Return: None.
def test_set_tts_gain_clamps_to_supported_range(tmp_path) -> None:
    """Ensure the live TTS boost setter updates the active configuration."""

    controller = build_controller(tmp_path)

    controller.set_tts_gain(2.5)
    assert controller.config.tts_gain == 2.5

    controller.set_tts_gain(99.0)
    assert controller.config.tts_gain == 3.0


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
