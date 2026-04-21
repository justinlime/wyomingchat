"""Application controller that orchestrates configuration, always-on audio monitoring, STT, and TTS."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .audio import AudioCaptureStream, AudioDeviceCatalog, MultiOutputPlayer
from .audio_types import AudioFormatSpec, describe_audio_format
from .clients import SpeechToTextSession, TextToSpeechSession, TtsVoiceQuerySession
from .config import AppConfig, ServiceEndpoint, TtsVoiceConfig, build_default_config
from .constants import (
    DEFAULT_VAD_FRAME_MS,
    MAX_MIC_GAIN,
    MAX_STOP_SILENCE_MS,
    MAX_TTS_GAIN,
    MIN_STOP_SILENCE_MS,
    STATE_ERROR,
    STATE_IDLE,
    STATE_LISTENING,
    STATE_SPEAKING,
    STATE_SYNTHESIZING,
    STATE_TRANSCRIBING,
)
from .pipewire import build_virtual_microphone_sink_node_name, install_virtual_microphone_config
from .platforms import is_linux, virtual_mic_mode
from .routing import build_tts_output_device_ids
from .storage import JsonConfigStore
from .virtual_cable import output_device_pairs, select_cable_output_id
from .vad import (
    OpenMicVoiceDetector,
    amplify_pcm_chunk,
    build_stt_audio_format,
    convert_audio_chunk_for_stt,
    measure_pcm_level,
)

LOGGER = logging.getLogger(__name__)


class BridgeController(QObject):
    """Coordinate the end-to-end always-on voice bridge workflow."""

    state_changed = Signal(str)
    status_changed = Signal(str)
    partial_transcript_changed = Signal(str)
    final_transcript_changed = Signal(str)
    error_changed = Signal(str)
    configuration_loaded = Signal(object)
    configuration_saved = Signal(str)
    tts_voices_changed = Signal(object)
    devices_changed = Signal()
    monitoring_changed = Signal(bool)
    virtual_microphone_configured = Signal(str)
    listening_changed = Signal(bool)
    microphone_level_changed = Signal(int)
    microphone_gate_changed = Signal(bool)

    _tts_voice_query_result_received = Signal(int, object)
    _tts_voice_query_error_received = Signal(int, str)
    _tts_voice_query_complete_received = Signal(int)
    _tts_streaming_support_received = Signal(int, bool)
    _stt_partial_received = Signal(int, str)
    _stt_final_received = Signal(int, str)
    _stt_error_received = Signal(int, str)
    _stt_complete_received = Signal(int)
    _tts_audio_start_received = Signal(int, object)
    _tts_audio_chunk_received = Signal(int, bytes)
    _tts_error_received = Signal(int, str)
    _tts_complete_received = Signal(int)

    # Usage: create the bridge controller and wire together persistence, audio monitoring, and playback services.
    # Parameters: store - configuration persistence service; catalog - audio device catalog; capture - microphone capture helper; player - multi-output playback helper; parent - optional QObject parent.
    # Return: None.
    def __init__(
        self,
        store: JsonConfigStore,
        catalog: AudioDeviceCatalog,
        capture: AudioCaptureStream,
        player: MultiOutputPlayer,
        parent: QObject | None = None,
    ) -> None:
        """Initialize the bridge controller and connect all component signals."""

        super().__init__(parent)
        self._store = store
        self._catalog = catalog
        self._capture = capture
        self._player = player
        self._config = build_default_config()
        self._state = STATE_IDLE
        self._stt_session: SpeechToTextSession | None = None
        self._tts_session: TextToSpeechSession | None = None
        self._tts_voice_query_session: TtsVoiceQuerySession | None = None
        self._tts_streaming_supported = False
        self._voice_detector: OpenMicVoiceDetector | None = None
        self._capture_format_spec: AudioFormatSpec | None = None
        self._stt_audio_format_spec: AudioFormatSpec | None = None
        self._tts_format_spec: AudioFormatSpec | None = None
        self._available_tts_voices: list[TtsVoiceConfig] = []
        self._tts_voice_query_generation = 0
        self._stt_generation = 0
        self._tts_generation = 0
        self._tts_format_spec: AudioFormatSpec | None = None
        self._tts_chunk_ack: threading.Event | None = None
        self._pre_stream_chunks: list[bytes] = []
        self._tts_started_at = 0.0
        self._tts_first_chunk_written = False
        self._latest_final_transcript = ""
        self._pending_tts_text: str | None = None
        self._paused = False
        self._monitor_cooldown_until = 0.0
        self._connect_components()

    @property
    # Usage: access the most recently loaded or edited application configuration.
    # Parameters: none.
    # Return: the active AppConfig object held by the controller.
    def config(self) -> AppConfig:
        """Return the active application configuration."""

        return self._config

    @property
    # Usage: expose the current controller state for UI or test inspection.
    # Parameters: none.
    # Return: the current high-level state string such as idle, listening, or speaking.
    def state(self) -> str:
        """Return the current high-level application state."""

        return self._state

    # Usage: connect signals emitted by the audio, playback, and worker callback bridges.
    # Parameters: none.
    # Return: None.
    def _connect_components(self) -> None:
        """Connect component signals to controller handlers."""

        self._catalog.devices_changed.connect(self.devices_changed.emit)
        self._capture.audio_chunk.connect(self._handle_audio_chunk)
        self._capture.error_occurred.connect(self._handle_error)
        self._player.error_occurred.connect(self._handle_error)
        self._player.playback_finished.connect(self._handle_playback_finished)

        self._tts_voice_query_result_received.connect(self._apply_tts_voice_query_result)
        self._tts_voice_query_error_received.connect(self._handle_tts_voice_query_error)
        self._tts_voice_query_complete_received.connect(self._handle_tts_voice_query_complete)
        self._tts_streaming_support_received.connect(self._handle_tts_streaming_support)
        self._stt_partial_received.connect(self._apply_partial_transcript)
        self._stt_final_received.connect(self._apply_final_transcript)
        self._stt_error_received.connect(self._handle_stt_error)
        self._stt_complete_received.connect(self._handle_stt_complete)
        self._tts_audio_start_received.connect(self._handle_tts_audio_start)
        self._tts_audio_chunk_received.connect(self._handle_tts_audio_chunk)
        self._tts_error_received.connect(self._handle_tts_error)
        self._tts_complete_received.connect(self._handle_tts_complete)

    # Usage: load configuration from disk, emit it to the UI, and start the always-on microphone monitor.
    # Parameters: none.
    # Return: the AppConfig that was loaded.
    def load_configuration(self) -> AppConfig:
        """Load configuration from disk, emit it to the UI, and start microphone monitoring."""

        self._config = self._store.load()
        self.configuration_loaded.emit(self._config)
        self.status_changed.emit(f"Loaded configuration from {self._store.config_path}")
        self._restart_microphone_monitor()
        return self._config

    # Usage: save a UI-edited configuration, make it active, and restart always-on monitoring with the new settings.
    # Parameters: config - the AppConfig collected from the current UI form state.
    # Return: the Path where configuration was written.
    def save_configuration(self, config: AppConfig) -> Path:
        """Persist the provided configuration, make it active, and restart monitoring if needed."""

        self._config = config
        saved_path = self._store.save(config)
        self.configuration_saved.emit(str(saved_path))
        self.status_changed.emit(f"Saved configuration to {saved_path}")
        self._restart_microphone_monitor()
        return saved_path

    # Usage: write the managed PipeWire virtual microphone config from the current application settings.
    # Parameters: none.
    # Return: the filesystem path of the PipeWire config file that was written, or None when the
    #         platform does not support PipeWire virtual devices.
    def install_virtual_microphone_from_config(self) -> Path | None:
        """Create or update the user's PipeWire virtual microphone configuration file."""

        virtual_mic = self._config.virtual_microphone
        try:
            config_path = install_virtual_microphone_config(
                node_name=virtual_mic.node_name,
                description=virtual_mic.description,
            )
        except RuntimeError as exc:
            # Surface a clear, recoverable message instead of letting the failure
            # interrupt microphone monitoring or the Qt event loop.
            self.error_changed.emit(str(exc))
            self.status_changed.emit(str(exc))
            return None

        self.virtual_microphone_configured.emit(str(config_path))
        self.status_changed.emit(
            "Virtual microphone config written. Restart pipewire, pipewire-pulse, and wireplumber to load it."
        )
        return config_path

    # Usage: refresh cached audio device metadata after the user requests an updated device list.
    # Parameters: none.
    # Return: None.
    def refresh_devices(self) -> None:
        """Refresh cached audio metadata and notify the UI about device changes."""

        self._catalog.refresh_pipewire_metadata()
        self.devices_changed.emit()
        self.status_changed.emit("Refreshed audio device metadata")

    # Usage: query the configured Wyoming TTS endpoint for advertised voices and publish the result back to the UI.
    # Parameters: endpoint - optional TTS endpoint override taken from unsaved UI form fields; when omitted the active saved TTS endpoint is queried.
    # Return: None.
    def refresh_tts_voices(self, endpoint: ServiceEndpoint | None = None) -> None:
        """Query the Wyoming TTS service for selectable voices without interrupting microphone monitoring."""

        query_endpoint = endpoint or self._config.tts_endpoint
        self._tts_voice_query_generation += 1
        query_generation = self._tts_voice_query_generation
        # Reset streaming capability until the new query reports the actual
        # server support, so a failed query cannot reuse stale capabilities
        # from a previously queried endpoint.
        self._tts_streaming_supported = False

        if self._tts_voice_query_session is not None:
            self._tts_voice_query_session.close()
            self._tts_voice_query_session.wait_closed()
            self._tts_voice_query_session = None

        self.error_changed.emit("")
        self.status_changed.emit(
            f"Querying TTS voices from {query_endpoint.host}:{query_endpoint.port}..."
        )
        self._tts_voice_query_session = TtsVoiceQuerySession(
            endpoint=query_endpoint,
            on_result=lambda voices, generation=query_generation: self._tts_voice_query_result_received.emit(
                generation,
                voices,
            ),
            on_streaming_support=lambda supported, generation=query_generation: self._tts_streaming_support_received.emit(
                generation,
                supported,
            ),
            on_error=lambda message, generation=query_generation: self._tts_voice_query_error_received.emit(
                generation,
                message,
            ),
            on_complete=lambda generation=query_generation: self._tts_voice_query_complete_received.emit(
                generation
            ),
        )
        self._tts_voice_query_session.start()

    # Usage: apply a new microphone gate threshold immediately so the live meter and VAD start gate reflect the slider in real time.
    # Parameters: threshold_percent - the 0-100 gate threshold percentage currently chosen in the UI.
    # Return: None.
    def set_mic_gate_threshold_percent(self, threshold_percent: int) -> None:
        """Update the live microphone gate threshold without requiring the user to save and restart monitoring."""

        normalized_threshold = max(0, min(100, int(threshold_percent)))
        self._config.mic_gate_threshold_percent = normalized_threshold
        if self._voice_detector is not None:
            self._voice_detector.set_start_level_threshold(normalized_threshold / 100.0)

    # Usage: apply a new microphone boost multiplier immediately so the live meter, gate, and STT stream reflect the slider in real time.
    # Parameters: gain_multiplier - the linear boost multiplier (1.0x means no boost).
    # Return: None.
    def set_mic_gain(self, gain_multiplier: float) -> None:
        """Update the live microphone boost multiplier for the next audio chunks."""

        self._config.mic_gain = max(1.0, min(MAX_MIC_GAIN, float(gain_multiplier)))

    # Usage: apply a new TTS output boost multiplier immediately so the next synthesized chunks are louder.
    # Parameters: gain_multiplier - the linear output multiplier (1.0x means no boost).
    # Return: None.
    def set_tts_gain(self, gain_multiplier: float) -> None:
        """Update the live TTS output boost multiplier for the next audio chunks."""

        self._config.tts_gain = max(1.0, min(MAX_TTS_GAIN, float(gain_multiplier)))

    # Usage: pause or resume the always-on microphone bridge so the user can stop it listening when needed.
    # Parameters: paused - True stops listening immediately; False restarts the always-on monitor.
    # Return: None.
    def set_bridge_paused(self, paused: bool) -> None:
        """Stop or start the microphone monitor without quitting the application."""

        normalized_paused = bool(paused)
        if normalized_paused == self._paused:
            return

        self._paused = normalized_paused
        if normalized_paused:
            self._abort_current_activity(stop_capture=True)
            self.status_changed.emit("Bridge paused - the microphone is no longer being listened to")
        else:
            self.status_changed.emit("Resuming the open microphone monitor...")
            self._restart_microphone_monitor()

    # Usage: apply a new trailing-silence timeout immediately so natural mid-thought pauses do not split the utterance.
    # Parameters: silence_ms - the maximum silence duration in milliseconds before the utterance ends.
    # Return: None.
    def set_stop_silence_ms(self, silence_ms: int) -> None:
        """Update the live utterance-end silence timeout without restarting monitoring."""

        normalized_silence_ms = max(MIN_STOP_SILENCE_MS, min(MAX_STOP_SILENCE_MS, int(silence_ms)))
        self._config.stop_silence_ms = normalized_silence_ms
        if self._voice_detector is not None:
            self._voice_detector.set_stop_silence_frames(
                max(1, round(normalized_silence_ms / DEFAULT_VAD_FRAME_MS))
            )

    # Usage: cleanly shut down background services when the application exits.
    # Parameters: none.
    # Return: None.
    def shutdown(self) -> None:
        """Stop active sessions, playback, and microphone monitoring."""

        if self._tts_voice_query_session is not None:
            self._tts_voice_query_session.close()
            self._tts_voice_query_session.wait_closed()
            self._tts_voice_query_session = None
        self._abort_current_activity(stop_capture=True)

    # Usage: accept a completed voice-discovery result from the active query only and publish it to the UI.
    # Parameters: generation - the voice-query generation that produced the result; voices - the selectable voices parsed from the server info payload.
    # Return: None.
    def _apply_tts_voice_query_result(self, generation: int, voices: list[TtsVoiceConfig]) -> None:
        """Store and broadcast discovered TTS voices from the active voice query only."""

        if generation != self._tts_voice_query_generation:
            return

        self._available_tts_voices = list(voices)
        self.tts_voices_changed.emit(list(self._available_tts_voices))
        if self._available_tts_voices:
            self.status_changed.emit(
                f"Discovered {len(self._available_tts_voices)} selectable TTS voice option(s)"
            )
            return

        self.status_changed.emit(
            "The TTS server did not advertise selectable voices; synthesis will use the server default voice"
        )

    # Usage: surface a voice-query failure to the UI without aborting the currently running microphone/STT/TTS pipeline.
    # Parameters: generation - the voice-query generation that produced the failure; message - the human-readable error string.
    # Return: None.
    def _handle_tts_voice_query_error(self, generation: int, message: str) -> None:
        """Display the latest TTS voice-query error from the active query only."""

        if generation != self._tts_voice_query_generation:
            return

        self.error_changed.emit(message)
        self.status_changed.emit(message)

    # Usage: store the streaming-synthesis capability advertised by the active TTS voice query.
    # Parameters: generation - the voice-query generation that reported the capability; supported - True when the server advertises streaming synthesize support.
    # Return: None.
    def _handle_tts_streaming_support(self, generation: int, supported: bool) -> None:
        """Record whether the queried TTS endpoint supports streaming synthesis."""

        if generation != self._tts_voice_query_generation:
            return

        self._tts_streaming_supported = bool(supported)
        LOGGER.info("TTS endpoint streaming synthesis support: %s", self._tts_streaming_supported)

    # Usage: clear the active voice-query session reference when the latest query worker exits.
    # Parameters: generation - the voice-query generation that completed.
    # Return: None.
    def _handle_tts_voice_query_complete(self, generation: int) -> None:
        """Release the active voice-query session reference after the newest query exits."""

        if generation != self._tts_voice_query_generation:
            return

        self._tts_voice_query_session = None

    # Usage: restart the open microphone monitor using the currently selected input device and a fresh VAD state machine.
    # Parameters: none.
    # Return: None.
    def _restart_microphone_monitor(self) -> None:
        """Restart the always-on microphone monitor using the active configuration."""

        if self._paused:
            return

        previous_state = self._state
        self._abort_current_activity(stop_capture=True)
        self.error_changed.emit("")
        try:
            capture_plan = self._capture.resolve_capture_plan(
                self._config.audio.input_device_id,
                AudioFormatSpec(),
            )
            self._capture_format_spec = capture_plan.format_spec
            self._stt_audio_format_spec = build_stt_audio_format()
            LOGGER.info(
                "Resolved microphone capture plan: device=%s, capture_format=%s, stt_stream_format=%s",
                capture_plan.device.description(),
                describe_audio_format(self._capture_format_spec),
                describe_audio_format(self._stt_audio_format_spec),
            )
            self._voice_detector = OpenMicVoiceDetector(
                capture_plan.format_spec,
                start_level_threshold=self._config.mic_gate_threshold_percent / 100.0,
                stop_silence_frames=max(1, round(self._config.stop_silence_ms / DEFAULT_VAD_FRAME_MS)),
            )
            self._capture.start_capture(capture_plan)
            self.monitoring_changed.emit(True)
            self.microphone_level_changed.emit(0)
            self.microphone_gate_changed.emit(False)
            self._set_state(STATE_IDLE)
            self.status_changed.emit("Open microphone is active and waiting for speech")
        except Exception as exc:  # noqa: BLE001 - surface any startup failure to the user.
            self.monitoring_changed.emit(False)
            self._capture_format_spec = None
            self._stt_audio_format_spec = None
            self._voice_detector = None
            self._handle_error(f"Failed to start open microphone monitor: {exc}")
            return

        if previous_state == STATE_ERROR:
            self.error_changed.emit("")

    # Usage: stop active STT/TTS/playback work, optionally stop capture, and invalidate stale worker callbacks.
    # Parameters: stop_capture - when True, also stop the always-on microphone capture stream.
    # Return: None.
    def _abort_current_activity(self, stop_capture: bool = False) -> None:
        """Immediately stop active network/playback work and optionally stop microphone capture."""

        self._stt_generation += 1
        self._tts_generation += 1
        self._pending_tts_text = None
        self._tts_format_spec = None
        if self._tts_chunk_ack is not None:
            # Wake any reader thread blocked on the per-chunk backpressure ack.
            self._tts_chunk_ack.set()
        self._tts_chunk_ack = None
        self._pre_stream_chunks = []

        if stop_capture:
            # Stop the microphone first so the Qt device buffer cannot overflow
            # while we tear down network sessions below (blocking joins can
            # otherwise stall the GUI thread long enough to drop mic audio).
            self._capture.stop_capture()
            self._capture_format_spec = None
            self._stt_audio_format_spec = None
            self.monitoring_changed.emit(False)
            self.microphone_level_changed.emit(0)
            self.microphone_gate_changed.emit(False)

        if self._stt_session is not None:
            self._stt_session.close()
            self._stt_session.wait_closed()
            self._stt_session = None
        if self._tts_session is not None:
            self._tts_session.close()
            self._tts_session.wait_closed()
            self._tts_session = None

        self._player.stop_stream()
        if self._voice_detector is not None:
            self._voice_detector.reset()

        self.listening_changed.emit(False)
        if self._state != STATE_ERROR:
            self._set_state(STATE_IDLE)

    # Usage: consume one always-on microphone chunk, apply VAD while idle/listening, and drive STT session boundaries.
    # Parameters: chunk - raw PCM microphone audio from Qt capture.
    # Return: None.
    def _handle_audio_chunk(self, chunk: bytes) -> None:
        """Process one microphone chunk through the always-on VAD gate."""

        if self._voice_detector is None or not chunk:
            return
        if self._paused:
            return

        if self._capture_format_spec is not None and self._config.mic_gain > 1.0:
            chunk = amplify_pcm_chunk(chunk, self._capture_format_spec, self._config.mic_gain)

        chunk_level = 0.0
        if self._capture_format_spec is not None:
            chunk_level = measure_pcm_level(chunk, self._capture_format_spec)
        chunk_level_percent = int(round(chunk_level * 100.0))
        self.microphone_level_changed.emit(chunk_level_percent)
        self.microphone_gate_changed.emit((chunk_level * 100.0) >= self._config.mic_gate_threshold_percent)

        if time.monotonic() < self._monitor_cooldown_until:
            self._voice_detector.reset()
            return

        if self._state not in {STATE_ERROR, STATE_IDLE, STATE_LISTENING}:
            self._voice_detector.reset()
            return

        decision = self._voice_detector.process_audio_chunk(chunk)
        if decision.should_start_stream and self._state in {STATE_ERROR, STATE_IDLE}:
            if not self._start_stt_session():
                self._voice_detector.reset()
                return
            self._set_state(STATE_LISTENING)
            self.status_changed.emit("Speech detected. Streaming microphone audio to STT...")
            self.listening_changed.emit(True)

        if (
            self._stt_session is not None
            and self._capture_format_spec is not None
            and self._stt_audio_format_spec is not None
        ):
            for buffered_chunk in decision.audio_chunks:
                self._stt_session.send_audio_chunk(
                    convert_audio_chunk_for_stt(
                        buffered_chunk,
                        self._capture_format_spec,
                        self._stt_audio_format_spec,
                    )
                )

        if decision.should_stop_stream and self._stt_session is not None:
            self._stt_session.finish()
            self._set_state(STATE_TRANSCRIBING)
            self.status_changed.emit("Speech ended. Finalizing transcription...")
            self.listening_changed.emit(False)

    # Usage: create the next Wyoming STT session for a newly detected utterance and scope callbacks to its generation.
    # Parameters: none.
    # Return: True when the STT session started successfully, otherwise False.
    def _start_stt_session(self) -> bool:
        """Create and start the next Wyoming STT session for a detected utterance."""

        self.error_changed.emit("")
        self.partial_transcript_changed.emit("")
        self.final_transcript_changed.emit("")
        self._latest_final_transcript = ""
        self._pending_tts_text = None

        self._stt_generation += 1
        stt_generation = self._stt_generation
        try:
            stt_audio_format = self._stt_audio_format_spec or build_stt_audio_format()
            self._stt_session = SpeechToTextSession(
                endpoint=self._config.stt_endpoint,
                audio_format=stt_audio_format,
                on_partial=lambda text, generation=stt_generation: self._stt_partial_received.emit(generation, text),
                on_final=lambda text, generation=stt_generation: self._stt_final_received.emit(generation, text),
                on_error=lambda message, generation=stt_generation: self._stt_error_received.emit(generation, message),
                on_complete=lambda generation=stt_generation: self._stt_complete_received.emit(generation),
            )
            self._stt_session.start()
        except Exception as exc:  # noqa: BLE001 - surface any startup failure to the user.
            self._stt_session = None
            self._handle_error(f"Failed to start transcription: {exc}")
            return False

        return True

    # Usage: update the UI with the latest streaming transcript-chunk content from the active STT session only.
    # Parameters: generation - the STT session generation that produced the update; text - the current partial transcript text assembled by the STT worker.
    # Return: None.
    def _apply_partial_transcript(self, generation: int, text: str) -> None:
        """Apply and emit a streaming partial transcript update from the active STT session only."""

        if generation != self._stt_generation:
            return

        self.partial_transcript_changed.emit(text)
        if self._state in {STATE_LISTENING, STATE_TRANSCRIBING}:
            self.status_changed.emit("Receiving transcript updates...")

    # Usage: apply the final STT transcript from the active session, persist it, and queue TTS to start after STT fully closes.
    # Parameters: generation - the STT session generation that produced the transcript; text - the final transcript returned by the STT server.
    # Return: None.
    def _apply_final_transcript(self, generation: int, text: str) -> None:
        """Apply the final transcript from the active STT session and queue TTS when text is available."""

        if generation != self._stt_generation:
            return

        normalized_text = text.strip()
        self._latest_final_transcript = normalized_text
        self.partial_transcript_changed.emit(normalized_text)
        self.final_transcript_changed.emit(normalized_text)
        self._config.last_transcript = normalized_text
        self._store.save(self._config)

        if not normalized_text:
            self._pending_tts_text = None
            self.status_changed.emit("No speech was transcribed")
            return

        self._pending_tts_text = normalized_text
        self.status_changed.emit("Transcription complete. Preparing speech synthesis...")

    # Usage: react after the active STT worker has fully completed and decide whether TTS or idle should follow.
    # Parameters: generation - the STT session generation that completed.
    # Return: None.
    def _handle_stt_complete(self, generation: int) -> None:
        """Finalize STT cleanup after the active session worker has exited."""

        if generation != self._stt_generation:
            return

        self._stt_session = None
        self.listening_changed.emit(False)
        if self._pending_tts_text:
            queued_tts_text = self._pending_tts_text
            self._pending_tts_text = None
            self._start_tts(queued_tts_text)
            return

        self._set_state(STATE_IDLE)
        self.status_changed.emit("Open microphone is active and waiting for speech")

    # Usage: start a TTS request for the given transcript text and scope callbacks to the active synthesis session only.
    # Parameters: text - the transcript text that should be spoken aloud.
    # Return: None.
    def _start_tts(self, text: str) -> None:
        """Start a TTS request for the provided transcript text."""

        if self._tts_session is not None:
            return

        self._tts_generation += 1
        tts_generation = self._tts_generation
        self._set_state(STATE_SYNTHESIZING)
        self.status_changed.emit(
            "Requesting streaming speech synthesis..."
            if self._tts_streaming_supported
            else "Requesting speech synthesis..."
        )
        self._tts_chunk_ack = threading.Event()
        self._pre_stream_chunks = []
        self._tts_started_at = time.monotonic()
        self._tts_first_chunk_written = False
        self._tts_session = TextToSpeechSession(
            endpoint=self._config.tts_endpoint,
            text=text,
            voice=self._config.tts_voice,
            streaming=self._tts_streaming_supported,
            on_audio_start=lambda format_spec, generation=tts_generation: self._tts_audio_start_received.emit(generation, format_spec),
            on_audio_chunk=lambda audio_chunk, generation=tts_generation: self._emit_tts_chunk_with_backpressure(audio_chunk, generation),
            on_error=lambda message, generation=tts_generation: self._tts_error_received.emit(generation, message),
            on_complete=lambda generation=tts_generation: self._tts_complete_received.emit(generation),
        )
        try:
            self._tts_session.start()
        except Exception as exc:  # noqa: BLE001 - surface any startup failure to the user.
            self._tts_session = None
            self._handle_error(f"Failed to start synthesis: {exc}")

    # Usage: emit one TTS audio chunk from the reader thread and wait for the GUI thread to consume it before the next chunk is read.
    # Parameters: audio_chunk - the raw PCM bytes received from the Wyoming TTS server; generation - the TTS session generation.
    # Return: None.
    def _emit_tts_chunk_with_backpressure(self, audio_chunk: bytes, generation: int) -> None:
        """Queue one TTS chunk to the GUI thread with per-chunk backpressure.

        Without this, a fast-synthesizing server can flood the Qt event loop with
        queued chunk signals; if the GUI thread is ever busy, they pile up and are
        delivered in one burst at the end of the download, which makes playback
        appear to start only after the final chunk arrives.
        """

        self._tts_audio_chunk_received.emit(generation, audio_chunk)
        ack = self._tts_chunk_ack
        if ack is None:
            return
        ack.clear()
        deadline = time.monotonic() + 10.0
        while not ack.is_set():
            if self._tts_session is None or self._tts_session._completed.is_set():
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            ack.wait(timeout=min(0.05, remaining))

    # Usage: resolve the Qt playback output id used as the virtual microphone target for the current platform.
    # Parameters: none.
    # Return: the persisted Qt output-device id that TTS audio should be routed into, or None when the
    #         virtual microphone is disabled or its target device is unavailable.
    def _resolve_virtual_microphone_output_id(self) -> str | None:
        """Return the playback output id used as the virtual microphone target.

        On Linux this resolves the managed PipeWire loopback sink by node name.
        On Windows this resolves the selected (or auto-detected) virtual audio
        cable playback endpoint so other applications can pick the cable's
        paired microphone endpoint.
        """

        virtual_microphone = self._config.virtual_microphone
        if not virtual_microphone.enabled:
            return None

        if virtual_mic_mode() == "cable":
            resolved_cable_id = select_cable_output_id(
                virtual_microphone.cable_device_id,
                output_device_pairs(self._catalog.list_outputs()),
            )
            if resolved_cable_id is None:
                # Keep the user informed when the feature is enabled but no
                # usable cable endpoint is currently installed or selected.
                self.status_changed.emit(
                    "Virtual microphone enabled but no audio cable was found. "
                    "Install a free cable such as VB-CABLE (vb-audio.com/Cable) or Voicemeeter, "
                    "or select a cable playback endpoint manually, then refresh devices."
                )
            return resolved_cable_id

        if is_linux():
            return self._catalog.find_output_device_id_by_pipewire_node_name(
                build_virtual_microphone_sink_node_name(virtual_microphone.node_name)
            )

        # macOS and other platforms have no supported virtual-microphone target.
        return None

    # Usage: prepare output sinks when the active TTS session announces the PCM audio format.
    # Parameters: generation - the TTS session generation that produced the format; format_spec - the raw PCM format of the incoming synthesized audio.
    # Return: None.
    def _handle_tts_audio_start(self, generation: int, format_spec: AudioFormatSpec) -> None:
        """Create output sinks for the incoming TTS audio stream from the active session only."""

        if generation != self._tts_generation:
            return

        self._tts_format_spec = format_spec
        output_device_ids = build_tts_output_device_ids(
            self._config.audio.output_device_ids,
            self._resolve_virtual_microphone_output_id(),
        )
        if not output_device_ids:
            self._handle_error(
                "No playback targets are available for TTS output. Select a speaker output or make sure the managed virtual microphone sink is available."
            )
            return

        started_outputs = self._player.start_stream(output_device_ids, format_spec)
        if started_outputs <= 0:
            self._handle_error("No compatible playback device could be opened for TTS output")
            return

        # Flush any chunks that arrived before the stream opened so the very
        # first audio is never dropped or delayed.
        if self._pre_stream_chunks:
            for pending_chunk in self._pre_stream_chunks:
                self._player.write_audio(pending_chunk)
            self._pre_stream_chunks.clear()

        self._set_state(STATE_SPEAKING)
        self.status_changed.emit("Playing synthesized audio...")

    # Usage: forward each synthesized PCM chunk from the active TTS session to the playback helper, applying any configured output boost.
    # Parameters: generation - the TTS session generation that produced the chunk; chunk - raw PCM bytes received from the Wyoming TTS server.
    # Return: None.
    def _handle_tts_audio_chunk(self, generation: int, chunk: bytes) -> None:
        """Write streamed TTS audio chunks from the active session to the playback sinks."""

        if generation != self._tts_generation:
            if self._tts_chunk_ack is not None:
                self._tts_chunk_ack.set()
            return

        if self._tts_format_spec is not None and self._config.tts_gain > 1.0:
            chunk = amplify_pcm_chunk(chunk, self._tts_format_spec, self._config.tts_gain)

        if not self._player.is_streaming:
            # The stream is not open yet (audio-start not processed); keep the
            # chunk so it is played once playback begins instead of dropping it.
            self._pre_stream_chunks.append(chunk)
        else:
            if not self._tts_first_chunk_written and self._tts_started_at:
                self._tts_first_chunk_written = True
                LOGGER.info(
                    "First TTS audio chunk written %.0f ms after synthesis start",
                    (time.monotonic() - self._tts_started_at) * 1000.0,
                )
            self._player.write_audio(chunk)

        if self._tts_chunk_ack is not None:
            self._tts_chunk_ack.set()

    # Usage: finalize TTS cleanup after the active synthesis worker completes and let playback drain naturally.
    # Parameters: generation - the TTS session generation that completed.
    # Return: None.
    def _handle_tts_complete(self, generation: int) -> None:
        """Mark the active TTS request complete and let playback drain if needed."""

        if generation != self._tts_generation:
            return

        if self._tts_chunk_ack is not None:
            self._tts_chunk_ack.set()
        self._tts_session = None
        self._tts_format_spec = None
        self._tts_chunk_ack = None
        self._pre_stream_chunks = []
        self._player.finish_stream()
        if self._state == STATE_SYNTHESIZING:
            self._set_state(STATE_IDLE)
            self.status_changed.emit("Open microphone is active and waiting for speech")

    # Usage: forward a TTS error from the active session only, ignoring stale callbacks from older sessions.
    # Parameters: generation - the TTS session generation that produced the error; message - the human-readable error message.
    # Return: None.
    def _handle_tts_error(self, generation: int, message: str) -> None:
        """Forward a TTS error from the active session only."""

        if generation != self._tts_generation:
            return

        self._handle_error(message)

    # Usage: return the application to idle after all playback sinks have drained and stopped.
    # Parameters: none.
    # Return: None.
    def _handle_playback_finished(self) -> None:
        """Return the controller to idle after playback finishes."""

        if self._state in {STATE_SPEAKING, STATE_SYNTHESIZING}:
            self._monitor_cooldown_until = time.monotonic() + 0.35
            if self._voice_detector is not None:
                self._voice_detector.reset()
            self._set_state(STATE_IDLE)
            self.status_changed.emit("Open microphone is active and waiting for speech")

    # Usage: forward an STT error from the active session only, ignoring stale callbacks from older sessions.
    # Parameters: generation - the STT session generation that produced the error; message - the human-readable error message.
    # Return: None.
    def _handle_stt_error(self, generation: int, message: str) -> None:
        """Forward an STT error from the active session only."""

        if generation != self._stt_generation:
            return

        self._handle_error(message)

    # Usage: surface a terminal error to the UI and stop active work while keeping the app recoverable.
    # Parameters: message - the human-readable error to show the user.
    # Return: None.
    def _handle_error(self, message: str) -> None:
        """Abort active work and expose a human-readable error message."""

        normalized_message = str(message).strip()
        if not normalized_message:
            return

        self._abort_current_activity(stop_capture=False)
        self._set_state(STATE_ERROR)
        self.error_changed.emit(normalized_message)
        self.status_changed.emit(normalized_message)

    # Usage: set and broadcast the current high-level controller state.
    # Parameters: state - the new high-level state string.
    # Return: None.
    def _set_state(self, state: str) -> None:
        """Update the controller state and emit a state-changed signal when it changes."""

        if self._state == state:
            return

        self._state = state
        self.state_changed.emit(state)
