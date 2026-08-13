"""Tests for the controller's TTS output handling, bridge pause, and live tuning setters."""

from __future__ import annotations

import pytest

from wyomingchat import controller as controller_module
from wyomingchat.audio import AudioCaptureStream, AudioDeviceCatalog, MultiOutputPlayer
from wyomingchat.config import AppConfig, ServiceEndpoint
from wyomingchat.controller import BridgeController
from wyomingchat.storage import JsonConfigStore


@pytest.fixture(scope="module")
def qapp():
    """Provide a shared QApplication instance for widget/signal tests."""

    from PySide6.QtWidgets import QApplication

    application = QApplication.instance()
    if application is None:
        application = QApplication([])
    yield application


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
    controller._player._active_outputs = [object()]  # simulate an open stream

    chunk = array("h", [1000] * 480).tobytes()
    controller._handle_tts_audio_chunk(1, chunk)

    assert round(measure_pcm_level(captured[0], controller._tts_format_spec), 3) == 0.061


# Usage: verify that chunks arriving before the stream opens are buffered, not dropped.
# Parameters: tmp_path - pytest fixture.
# Return: None.
def test_tts_chunks_before_stream_start_are_buffered(tmp_path) -> None:
    """Ensure pre-stream audio is retained and played once playback opens."""

    from array import array

    from wyomingchat.audio_types import AudioFormatSpec
    from wyomingchat.vad import measure_pcm_level

    controller = build_controller(tmp_path)
    controller._config.tts_gain = 1.5
    controller._tts_generation = 1
    controller._tts_format_spec = AudioFormatSpec(rate=16000, width=2, channels=1)

    chunk = array("h", [1000] * 480).tobytes()
    controller._handle_tts_audio_chunk(1, chunk)

    assert len(controller._pre_stream_chunks) == 1
    assert round(measure_pcm_level(bytes(controller._pre_stream_chunks[0]), controller._tts_format_spec), 3) == round(
        1500 / 32767, 3
    )


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


# Usage: verify that the server's streaming capability is recorded and passed to new TTS sessions.
# Parameters: tmp_path - pytest fixture.
# Return: None.
def test_tts_streaming_support_flag_flows_into_tts_sessions(tmp_path) -> None:
    """Ensure the server's streaming capability is recorded and passed to new TTS sessions."""

    controller = build_controller(tmp_path)

    # Ignore stale results from older generations.
    controller._handle_tts_streaming_support(controller._tts_voice_query_generation - 1, True)
    assert controller._tts_streaming_supported is False

    controller._handle_tts_streaming_support(controller._tts_voice_query_generation, True)
    assert controller._tts_streaming_supported is True

    controller._handle_tts_streaming_support(controller._tts_voice_query_generation, False)
    assert controller._tts_streaming_supported is False


# Usage: verify that the discovered streaming capability survives an app restart through persisted config.
# Parameters: tmp_path - pytest fixture.
# Return: None.
def test_tts_streaming_support_persists_across_restart(tmp_path) -> None:
    """Ensure a restart restores streaming synthesis without requiring a fresh voice query."""

    controller = build_controller(tmp_path)
    controller._handle_tts_streaming_support(controller._tts_voice_query_generation, True)
    assert controller._tts_streaming_supported is True

    # The discovery handler persisted the flag to disk; a fresh controller
    # simulating an app restart must restore it from the saved config.
    restarted = build_controller(tmp_path)
    restarted.load_configuration()
    assert restarted._tts_streaming_supported is True


# Usage: verify that saving the form config preserves the streaming flag when the TTS endpoint is unchanged.
# Parameters: tmp_path - pytest fixture.
# Return: None.
def test_save_configuration_preserves_streaming_flag_for_unchanged_endpoint(tmp_path) -> None:
    """Ensure a form save with the same TTS endpoint keeps the discovered capability."""

    controller = build_controller(tmp_path)
    controller._tts_streaming_supported = True
    controller._config.tts_streaming_supported = True

    form_config = AppConfig()
    form_config.tts_endpoint = controller._config.tts_endpoint
    controller.save_configuration(form_config)

    assert controller._tts_streaming_supported is True
    assert controller._config.tts_streaming_supported is True


# Usage: verify that saving the form config resets the streaming flag when the TTS endpoint changes.
# Parameters: tmp_path - pytest fixture.
# Return: None.
def test_save_configuration_resets_streaming_flag_on_endpoint_change(tmp_path) -> None:
    """Ensure a form save pointing at a different TTS server requires a fresh voice query."""

    controller = build_controller(tmp_path)
    controller._tts_streaming_supported = True
    controller._config.tts_streaming_supported = True

    changed_config = AppConfig()
    changed_config.tts_endpoint = ServiceEndpoint(host="10.0.0.9", port=10200)
    controller.save_configuration(changed_config)

    assert controller._tts_streaming_supported is False
    assert controller._config.tts_streaming_supported is False


# Usage: verify that streamed TTS chunks reach the player incrementally, not in a burst at the end.
# Parameters: tmp_path - pytest fixture; qapp - module-level Qt app fixture.
# Return: None.
def test_tts_chunks_stream_incrementally(tmp_path, qapp) -> None:
    """Ensure a paced Wyoming TTS server results in paced playback writes."""

    import socket
    import threading
    import time as time_module

    from wyomingchat.audio_types import AudioFormatSpec
    from wyomingchat.config import ServiceEndpoint
    from wyomingchat.wyoming_protocol import encode_event

    # Loopback TTS server: stream 10 chunks of 250 ms audio, one every 150 ms.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def serve() -> None:
        connection, _ = listener.accept()
        reader = connection.makefile("rb")
        reader.readline()  # synthesize event header (data only; ignore body)
        audio_format = AudioFormatSpec(rate=16000, width=2, channels=1)
        connection.sendall(
            encode_event(
                __import__("wyomingchat.wyoming_protocol", fromlist=["WyomingEvent"]).WyomingEvent(
                    type="audio-start",
                    data={"rate": audio_format.rate, "width": audio_format.width, "channels": audio_format.channels},
                )
            )
        )
        chunk = b"\x00\x00" * 2000  # 62.5 ms of silence
        for _ in range(10):
            connection.sendall(
                encode_event(
                    __import__("wyomingchat.wyoming_protocol", fromlist=["WyomingEvent"]).WyomingEvent(
                        type="audio-chunk", data={}, payload=chunk
                    )
                )
            )
            time_module.sleep(0.15)
        connection.sendall(encode_event(__import__("wyomingchat.wyoming_protocol", fromlist=["WyomingEvent"]).WyomingEvent(type="audio-stop", data={})))
        connection.close()
        listener.close()

    server_thread = threading.Thread(target=serve, daemon=True)
    server_thread.start()

    controller = build_controller(tmp_path)
    controller._config.tts_endpoint = ServiceEndpoint(host="127.0.0.1", port=port)
    controller._config.audio.output_device_ids = ["fake-output"]

    write_times: list[float] = []
    controller._player.start_stream = lambda _output_ids, _fmt: 1
    controller._player.write_audio = lambda chunk: write_times.append(time_module.monotonic())

    class _FakeSink:
        def stop(self) -> None:
            pass

        def deleteLater(self) -> None:
            pass

        def bufferSize(self) -> int:
            return 0

        def bytesFree(self) -> int:
            return 0

    controller._player._active_outputs = [
        __import__("types").SimpleNamespace(
            sink=_FakeSink(),
            io_device=object(),
            pending_bytes=bytearray(),
            descriptor=__import__("types").SimpleNamespace(id="fake", name="fake"),
        )
    ]

    started_at = time_module.monotonic()
    controller._start_tts("hello world")

    # Pump the Qt event loop until the TTS session completes or 10s elapse.
    deadline = time_module.monotonic() + 10.0
    while controller._tts_session is not None and time_module.monotonic() < deadline:
        qapp.processEvents()
        time_module.sleep(0.01)

    elapsed = (time_module.monotonic() - started_at) * 1000.0
    assert controller._tts_session is None, f"TTS session did not complete (elapsed {elapsed:.0f} ms)"
    assert len(write_times) >= 5, f"expected paced chunks, got {len(write_times)}"

    # The server paced chunks over ~1.5 s; if writes were delivered in a burst at
    # the end, the spread would be near zero. Require a meaningful spread.
    spread_ms = (write_times[-1] - write_times[0]) * 1000.0
    assert spread_ms >= 700.0, f"chunks arrived in a burst (spread {spread_ms:.0f} ms)"

    server_thread.join(timeout=2)
