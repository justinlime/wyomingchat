"""Application controller that orchestrates configuration, always-on audio monitoring, STT, and TTS."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .audio import AudioCaptureStream, AudioDeviceCatalog, MultiOutputPlayer
from .audio_types import AudioFormatSpec, describe_audio_format
from .clients import SpeechToTextSession, TextToSpeechSession, TtsVoiceQuerySession
from .config import AppConfig, ServiceEndpoint, TtsVoiceConfig, build_default_config
from .constants import (
    STATE_ERROR,
    STATE_IDLE,
    STATE_LISTENING,
    STATE_SPEAKING,
    STATE_SYNTHESIZING,
    STATE_TRANSCRIBING,
)
from .pipewire import build_virtual_microphone_sink_node_name, install_virtual_microphone_config
from .routing import build_tts_output_device_ids
from .storage import JsonConfigStore
from .vad import (
    OpenMicVoiceDetector,
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
        self._voice_detector: OpenMicVoiceDetector | None = None
        self._capture_format_spec: AudioFormatSpec | None = None
        self._stt_audio_format_spec: AudioFormatSpec | None = None
        self._available_tts_voices: list[TtsVoiceConfig] = []
        self._tts_voice_query_generation = 0
        self._stt_generation = 0
        self._tts_generation = 0
        self._latest_final_transcript = ""
        self._pending_tts_text: str | None = None
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
    # Return: the filesystem path of the PipeWire config file that was written.
    def install_virtual_microphone_from_config(self) -> Path:
        """Create or update the user's PipeWire virtual microphone configuration file."""

        virtual_mic = self._config.virtual_microphone
        config_path = install_virtual_microphone_config(
            node_name=virtual_mic.node_name,
            description=virtual_mic.description,
        )
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

        if stop_capture:
            self._capture.stop_capture()
            self._capture_format_spec = None
            self._stt_audio_format_spec = None
            self.monitoring_changed.emit(False)
            self.microphone_level_changed.emit(0)
            self.microphone_gate_changed.emit(False)

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
        self.status_changed.emit("Requesting speech synthesis...")
        self._tts_session = TextToSpeechSession(
            endpoint=self._config.tts_endpoint,
            text=text,
            voice=self._config.tts_voice,
            on_audio_start=lambda format_spec, generation=tts_generation: self._tts_audio_start_received.emit(generation, format_spec),
            on_audio_chunk=lambda audio_chunk, generation=tts_generation: self._tts_audio_chunk_received.emit(generation, audio_chunk),
            on_error=lambda message, generation=tts_generation: self._tts_error_received.emit(generation, message),
            on_complete=lambda generation=tts_generation: self._tts_complete_received.emit(generation),
        )
        try:
            self._tts_session.start()
        except Exception as exc:  # noqa: BLE001 - surface any startup failure to the user.
            self._tts_session = None
            self._handle_error(f"Failed to start synthesis: {exc}")

    # Usage: resolve the Qt playback output id for the managed PipeWire virtual-microphone sink when virtual mic routing is enabled.
    # Parameters: none.
    # Return: the persisted Qt output-device id for the managed virtual microphone sink, or None when it is disabled or unavailable.
    def _resolve_virtual_microphone_output_id(self) -> str | None:
        """Return the playback output id for the managed virtual microphone sink when it can be found."""

        virtual_microphone = self._config.virtual_microphone
        if not virtual_microphone.enabled:
            return None

        return self._catalog.find_output_device_id_by_pipewire_node_name(
            build_virtual_microphone_sink_node_name(virtual_microphone.node_name)
        )

    # Usage: prepare output sinks when the active TTS session announces the PCM audio format.
    # Parameters: generation - the TTS session generation that produced the format; format_spec - the raw PCM format of the incoming synthesized audio.
    # Return: None.
    def _handle_tts_audio_start(self, generation: int, format_spec: AudioFormatSpec) -> None:
        """Create output sinks for the incoming TTS audio stream from the active session only."""

        if generation != self._tts_generation:
            return

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

        self._set_state(STATE_SPEAKING)
        self.status_changed.emit("Playing synthesized audio...")

    # Usage: forward each synthesized PCM chunk from the active TTS session to the playback helper.
    # Parameters: generation - the TTS session generation that produced the chunk; chunk - raw PCM bytes received from the Wyoming TTS server.
    # Return: None.
    def _handle_tts_audio_chunk(self, generation: int, chunk: bytes) -> None:
        """Write streamed TTS audio chunks from the active session to the playback sinks."""

        if generation != self._tts_generation:
            return

        self._player.write_audio(chunk)

    # Usage: finalize TTS cleanup after the active synthesis worker completes and let playback drain naturally.
    # Parameters: generation - the TTS session generation that completed.
    # Return: None.
    def _handle_tts_complete(self, generation: int) -> None:
        """Mark the active TTS request complete and let playback drain if needed."""

        if generation != self._tts_generation:
            return

        self._tts_session = None
        self._player.finish_stream()
        if self._state == STATE_SYNTHESIZING:
            self._set_state(STATE_IDLE)
            self.status_changed.emit("Open microphone is active and waiting for speech")

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

    # Usage: forward a TTS error from the active session only, ignoring stale callbacks from older sessions.
    # Parameters: generation - the TTS session generation that produced the error; message - the human-readable error message.
    # Return: None.
    def _handle_tts_error(self, generation: int, message: str) -> None:
        """Forward a TTS error from the active session only."""

        if generation != self._tts_generation:
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
