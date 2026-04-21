"""Application controller that orchestrates configuration, audio, shortcuts, STT, and TTS."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .audio import AudioCaptureStream, AudioDeviceCatalog, AudioFormatSpec, MultiOutputPlayer
from .clients import SpeechToTextSession, TextToSpeechSession
from .config import AppConfig, build_default_config
from .constants import (
    STATE_ERROR,
    STATE_IDLE,
    STATE_LISTENING,
    STATE_SPEAKING,
    STATE_SYNTHESIZING,
    STATE_TRANSCRIBING,
)
from .shortcuts import GlobalShortcutPortal
from .storage import JsonConfigStore


class BridgeController(QObject):
    """Coordinate the end-to-end push-to-talk voice bridge workflow."""

    state_changed = Signal(str)
    status_changed = Signal(str)
    partial_transcript_changed = Signal(str)
    final_transcript_changed = Signal(str)
    error_changed = Signal(str)
    configuration_loaded = Signal(object)
    configuration_saved = Signal(str)
    devices_changed = Signal()
    shortcut_registered = Signal(str)
    shortcut_error = Signal(str)
    shortcut_availability_changed = Signal(bool)
    listening_changed = Signal(bool)

    _stt_partial_received = Signal(int, str)
    _stt_final_received = Signal(int, str)
    _stt_error_received = Signal(int, str)
    _stt_complete_received = Signal(int)
    _tts_audio_start_received = Signal(int, object)
    _tts_audio_chunk_received = Signal(int, bytes)
    _tts_error_received = Signal(int, str)
    _tts_complete_received = Signal(int)

    # Usage: create the bridge controller and wire together the persistence, audio, and shortcut services.
    # Parameters: store - configuration persistence service; catalog - audio device catalog; capture - microphone capture helper; player - multi-output playback helper; shortcut_portal - XDG shortcut portal wrapper; parent - optional QObject parent.
    # Return: None.
    def __init__(
        self,
        store: JsonConfigStore,
        catalog: AudioDeviceCatalog,
        capture: AudioCaptureStream,
        player: MultiOutputPlayer,
        shortcut_portal: GlobalShortcutPortal,
        parent: QObject | None = None,
    ) -> None:
        """Initialize the bridge controller and connect all component signals."""

        super().__init__(parent)
        self._store = store
        self._catalog = catalog
        self._capture = capture
        self._player = player
        self._shortcut_portal = shortcut_portal
        self._config = build_default_config()
        self._state = STATE_IDLE
        self._stt_session: SpeechToTextSession | None = None
        self._tts_session: TextToSpeechSession | None = None
        self._stt_generation = 0
        self._tts_generation = 0
        self._latest_final_transcript = ""
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

    # Usage: connect signals emitted by the audio, playback, shortcut, and worker callback bridges.
    # Parameters: none.
    # Return: None.
    def _connect_components(self) -> None:
        """Connect component signals to controller handlers."""

        self._catalog.devices_changed.connect(self.devices_changed.emit)
        self._capture.audio_chunk.connect(self._handle_audio_chunk)
        self._capture.error_occurred.connect(self._handle_error)
        self._player.error_occurred.connect(self._handle_error)
        self._player.playback_finished.connect(self._handle_playback_finished)
        self._shortcut_portal.shortcut_pressed.connect(self.start_listening)
        self._shortcut_portal.shortcut_released.connect(self.stop_listening)
        self._shortcut_portal.binding_changed.connect(self._handle_shortcut_registered)
        self._shortcut_portal.binding_failed.connect(self._handle_shortcut_error)
        self._shortcut_portal.availability_changed.connect(self._handle_shortcut_availability_changed)

        self._stt_partial_received.connect(self._apply_partial_transcript)
        self._stt_final_received.connect(self._apply_final_transcript)
        self._stt_error_received.connect(self._handle_stt_error)
        self._stt_complete_received.connect(self._handle_stt_complete)
        self._tts_audio_start_received.connect(self._handle_tts_audio_start)
        self._tts_audio_chunk_received.connect(self._handle_tts_audio_chunk)
        self._tts_error_received.connect(self._handle_tts_error)
        self._tts_complete_received.connect(self._handle_tts_complete)

    # Usage: load configuration from disk and notify the UI with the resulting AppConfig.
    # Parameters: none.
    # Return: the AppConfig that was loaded.
    def load_configuration(self) -> AppConfig:
        """Load configuration from disk and emit it to the UI."""

        self._config = self._store.load()
        self.configuration_loaded.emit(self._config)
        self.status_changed.emit(f"Loaded configuration from {self._store.config_path}")
        return self._config

    # Usage: save a UI-edited configuration, make it active, and notify listeners.
    # Parameters: config - the AppConfig collected from the current UI form state.
    # Return: the Path where configuration was written.
    def save_configuration(self, config: AppConfig) -> Path:
        """Persist the provided configuration and make it the active controller config."""

        self._config = config
        saved_path = self._store.save(config)
        self.configuration_saved.emit(str(saved_path))
        self.status_changed.emit(f"Saved configuration to {saved_path}")
        return saved_path

    # Usage: trigger a new portal shortcut registration using the currently active configuration.
    # Parameters: none.
    # Return: None.
    def register_shortcut_from_config(self) -> None:
        """Register the configured push-to-talk shortcut through the desktop portal."""

        if not self._config.shortcut.enabled:
            self._shortcut_portal.shutdown()
            self.status_changed.emit("Global shortcut support is disabled in configuration")
            return

        self.status_changed.emit("Registering global shortcut through the desktop portal...")
        self._shortcut_portal.register_shortcut(
            preferred_trigger=self._config.shortcut.preferred_trigger,
            description=self._config.shortcut.description,
        )

    # Usage: refresh cached audio device metadata after the user requests an updated device list.
    # Parameters: none.
    # Return: None.
    def refresh_devices(self) -> None:
        """Refresh cached audio metadata and notify the UI about device changes."""

        self._catalog.refresh_pipewire_metadata()
        self.devices_changed.emit()
        self.status_changed.emit("Refreshed audio device metadata")

    # Usage: begin a new push-to-talk interaction by opening STT streaming and microphone capture.
    # Parameters: none.
    # Return: None.
    def start_listening(self) -> None:
        """Start microphone capture and stream audio to the configured STT service."""

        if self._state == STATE_LISTENING:
            return

        self._abort_current_activity()
        self.error_changed.emit("")
        self.partial_transcript_changed.emit("")
        self.final_transcript_changed.emit("")
        self._latest_final_transcript = ""

        try:
            capture_plan = self._capture.resolve_capture_plan(
                self._config.audio.input_device_id,
                AudioFormatSpec(),
            )
            self._stt_generation += 1
            stt_generation = self._stt_generation
            self._stt_session = SpeechToTextSession(
                endpoint=self._config.stt_endpoint,
                audio_format=capture_plan.format_spec,
                on_partial=lambda text, generation=stt_generation: self._stt_partial_received.emit(generation, text),
                on_final=lambda text, generation=stt_generation: self._stt_final_received.emit(generation, text),
                on_error=lambda message, generation=stt_generation: self._stt_error_received.emit(generation, message),
                on_complete=lambda generation=stt_generation: self._stt_complete_received.emit(generation),
            )
            self._stt_session.start()
            self._capture.start_capture(capture_plan)
        except Exception as exc:  # noqa: BLE001 - surface any startup failure to the user.
            self._abort_current_activity()
            self._handle_error(f"Failed to start listening: {exc}")
            return

        self._set_state(STATE_LISTENING)
        self.status_changed.emit("Listening... hold the shortcut and speak")
        self.listening_changed.emit(True)

    # Usage: finish the current push-to-talk capture session and wait for the final transcript.
    # Parameters: none.
    # Return: None.
    def stop_listening(self) -> None:
        """Stop microphone capture and wait for the final STT result."""

        if self._state != STATE_LISTENING:
            return

        self._capture.stop_capture()
        if self._stt_session is not None:
            self._stt_session.finish()
        self._set_state(STATE_TRANSCRIBING)
        self.status_changed.emit("Finishing transcription...")
        self.listening_changed.emit(False)

    # Usage: cleanly shut down background services when the application exits.
    # Parameters: none.
    # Return: None.
    def shutdown(self) -> None:
        """Stop active sessions and release background resources."""

        self._abort_current_activity()
        self._shortcut_portal.shutdown()

    # Usage: stop any active STT, TTS, capture, or playback activity and invalidate stale worker callbacks.
    # Parameters: none.
    # Return: None.
    def _abort_current_activity(self) -> None:
        """Immediately stop any active capture, transcription, synthesis, or playback."""

        self._stt_generation += 1
        self._tts_generation += 1
        self._capture.stop_capture()
        if self._stt_session is not None:
            self._stt_session.close()
            self._stt_session = None
        if self._tts_session is not None:
            self._tts_session.close()
            self._tts_session = None
        self._player.stop_stream()
        self.listening_changed.emit(False)
        self._set_state(STATE_IDLE)

    # Usage: forward one captured microphone chunk to the active STT session.
    # Parameters: chunk - raw PCM microphone audio.
    # Return: None.
    def _handle_audio_chunk(self, chunk: bytes) -> None:
        """Send each captured microphone chunk to the active STT session."""

        if self._stt_session is not None:
            self._stt_session.send_audio_chunk(chunk)

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

    # Usage: apply the final STT transcript from the active session, persist it in config, and start TTS when text is present.
    # Parameters: generation - the STT session generation that produced the transcript; text - the final transcript returned by the STT server.
    # Return: None.
    def _apply_final_transcript(self, generation: int, text: str) -> None:
        """Apply the final transcript from the active STT session and start synthesis when text is available."""

        if generation != self._stt_generation:
            return

        normalized_text = text.strip()
        self._latest_final_transcript = normalized_text
        self.partial_transcript_changed.emit(normalized_text)
        self.final_transcript_changed.emit(normalized_text)
        self._config.last_transcript = normalized_text
        self._store.save(self._config)

        if not normalized_text:
            self.status_changed.emit("No speech was transcribed")
            self._set_state(STATE_IDLE)
            return

        self._start_tts(normalized_text)

    # Usage: react after the active STT worker has fully completed, stop any lingering capture, and decide whether the app should return to idle.
    # Parameters: generation - the STT session generation that completed.
    # Return: None.
    def _handle_stt_complete(self, generation: int) -> None:
        """Finalize STT cleanup after the active session worker has exited."""

        if generation != self._stt_generation:
            return

        self._capture.stop_capture()
        self.listening_changed.emit(False)
        self._stt_session = None
        if self._tts_session is None and not self._latest_final_transcript:
            self._set_state(STATE_IDLE)
            self.status_changed.emit("Ready")

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
            on_audio_start=lambda format_spec, generation=tts_generation: self._tts_audio_start_received.emit(generation, format_spec),
            on_audio_chunk=lambda chunk, generation=tts_generation: self._tts_audio_chunk_received.emit(generation, chunk),
            on_error=lambda message, generation=tts_generation: self._tts_error_received.emit(generation, message),
            on_complete=lambda generation=tts_generation: self._tts_complete_received.emit(generation),
        )
        try:
            self._tts_session.start()
        except Exception as exc:  # noqa: BLE001 - surface any startup failure to the user.
            self._tts_session = None
            self._handle_error(f"Failed to start synthesis: {exc}")

    # Usage: prepare output sinks when the active TTS session announces the PCM audio format.
    # Parameters: generation - the TTS session generation that produced the format; format_spec - the raw PCM format of the incoming synthesized audio.
    # Return: None.
    def _handle_tts_audio_start(self, generation: int, format_spec: AudioFormatSpec) -> None:
        """Create output sinks for the incoming TTS audio stream from the active session only."""

        if generation != self._tts_generation:
            return

        started_outputs = self._player.start_stream(self._config.audio.output_device_ids, format_spec)
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
            self.status_changed.emit("Ready")

    # Usage: return the application to idle after all playback sinks have drained and stopped.
    # Parameters: none.
    # Return: None.
    def _handle_playback_finished(self) -> None:
        """Return the controller to idle after playback finishes."""

        if self._state in {STATE_SPEAKING, STATE_SYNTHESIZING}:
            self._set_state(STATE_IDLE)
            self.status_changed.emit("Ready")

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

    # Usage: surface a terminal error to the UI and abort the active workflow.
    # Parameters: message - the human-readable error to show the user.
    # Return: None.
    def _handle_error(self, message: str) -> None:
        """Abort active work and expose a human-readable error message."""

        normalized_message = str(message).strip()
        if not normalized_message:
            return

        self._abort_current_activity()
        self._set_state(STATE_ERROR)
        self.error_changed.emit(normalized_message)
        self.status_changed.emit(normalized_message)

    # Usage: update config state and UI when the portal successfully binds the push-to-talk shortcut.
    # Parameters: trigger_description - the user-facing shortcut description returned by the portal backend.
    # Return: None.
    def _handle_shortcut_registered(self, trigger_description: str) -> None:
        """Persist and emit the final trigger text after portal registration succeeds."""

        self._config.shortcut.trigger_description = trigger_description
        self._store.save(self._config)
        self.shortcut_registered.emit(trigger_description)
        self.status_changed.emit(f"Global shortcut registered: {trigger_description}")

    # Usage: forward a global shortcut registration error to the UI without stopping audio features.
    # Parameters: message - the error reported by the portal worker.
    # Return: None.
    def _handle_shortcut_error(self, message: str) -> None:
        """Emit a shortcut-specific error message for portal registration failures."""

        self.shortcut_error.emit(message)
        self.status_changed.emit(message)

    # Usage: forward portal availability changes to the UI so it can show support status.
    # Parameters: available - whether a portal worker is currently active and listening.
    # Return: None.
    def _handle_shortcut_availability_changed(self, available: bool) -> None:
        """Emit the portal availability state for UI display."""

        self.shortcut_availability_changed.emit(available)

    # Usage: set and broadcast the current high-level controller state.
    # Parameters: state - the new high-level state string.
    # Return: None.
    def _set_state(self, state: str) -> None:
        """Update the controller state and emit a state-changed signal when it changes."""

        if self._state == state:
            return

        self._state = state
        self.state_changed.emit(state)
