"""Qt Multimedia audio device discovery, capture, and playback helpers."""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from functools import partial

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtMultimedia import QAudio, QAudioDevice, QAudioFormat, QAudioSink, QAudioSource, QMediaDevices

from .audio_types import (
    AudioFormatSpec,
    PCM_SAMPLE_FORMAT_FLOAT32,
    PCM_SAMPLE_FORMAT_INT16,
    PCM_SAMPLE_FORMAT_INT32,
    PCM_SAMPLE_FORMAT_UINT8,
)
from .constants import DEFAULT_AUDIO_BUFFER_MS
from .pipewire import PipeWireNode, build_node_lookup, list_audio_nodes
from .routing import choose_available_output_device_ids


@dataclass(slots=True)
class AudioDeviceDescriptor:
    """Describe an audio input or output device shown in the user interface."""

    id: str
    name: str
    direction: str
    is_default: bool
    pipewire_node_id: int | None = None
    pipewire_node_name: str | None = None


@dataclass(slots=True)
class ResolvedAudioInput:
    """Hold the concrete Qt input device and PCM format selected for microphone capture."""

    device_id: str
    device: QAudioDevice
    qt_format: QAudioFormat
    format_spec: AudioFormatSpec


@dataclass(slots=True)
class ActiveOutput:
    """Track an active playback sink, its writable Qt I/O device, and any bytes awaiting retry."""

    descriptor: AudioDeviceDescriptor
    sink: QAudioSink
    io_device: object
    pending_bytes: bytearray


# Usage: convert a Qt QAudioDevice identifier into a stable, JSON-safe string.
# Parameters: device - the QAudioDevice whose id should be encoded.
# Return: a URL-safe base64 string that can be stored in config files.
def encode_device_id(device: QAudioDevice) -> str:
    """Return a stable, JSON-safe identifier for a Qt audio device."""

    raw_bytes = bytes(device.id())
    if not raw_bytes:
        return "default"

    return base64.urlsafe_b64encode(raw_bytes).decode("ascii")


# Usage: map an AudioFormatSpec sample-format name into the matching Qt sample format enum.
# Parameters: format_spec - the PCM format specification whose sample format should be converted.
# Return: a QAudioFormat.SampleFormat value used to configure Qt audio objects.
def qt_sample_format_from_audio_format_spec(format_spec: AudioFormatSpec) -> QAudioFormat.SampleFormat:
    """Translate an AudioFormatSpec sample format into the corresponding Qt enum value."""

    if format_spec.sample_format == PCM_SAMPLE_FORMAT_UINT8 or format_spec.width == 1:
        return QAudioFormat.SampleFormat.UInt8
    if format_spec.sample_format == PCM_SAMPLE_FORMAT_FLOAT32:
        return QAudioFormat.SampleFormat.Float
    if format_spec.sample_format == PCM_SAMPLE_FORMAT_INT32 or format_spec.width == 4:
        return QAudioFormat.SampleFormat.Int32
    return QAudioFormat.SampleFormat.Int16


# Usage: map a Qt sample format enum back to the lightweight sample-format name stored in AudioFormatSpec.
# Parameters: sample_format - the Qt sample format to inspect.
# Return: the normalized sample-format name used throughout the Python codebase.
def sample_format_name_from_qt_sample_format(sample_format: QAudioFormat.SampleFormat) -> str:
    """Translate Qt sample formats into the normalized AudioFormatSpec sample-format strings."""

    if sample_format == QAudioFormat.SampleFormat.UInt8:
        return PCM_SAMPLE_FORMAT_UINT8
    if sample_format == QAudioFormat.SampleFormat.Float:
        return PCM_SAMPLE_FORMAT_FLOAT32
    if sample_format == QAudioFormat.SampleFormat.Int32:
        return PCM_SAMPLE_FORMAT_INT32
    return PCM_SAMPLE_FORMAT_INT16


# Usage: map a Qt sample format enum back to a PCM sample width in bytes.
# Parameters: sample_format - the Qt sample format to inspect.
# Return: the sample width in bytes that best matches the Qt format.
def width_from_sample_format(sample_format: QAudioFormat.SampleFormat) -> int:
    """Translate Qt sample formats back into PCM sample widths."""

    if sample_format == QAudioFormat.SampleFormat.UInt8:
        return 1
    if sample_format in {QAudioFormat.SampleFormat.Int32, QAudioFormat.SampleFormat.Float}:
        return 4
    return 2


# Usage: construct a QAudioFormat from the project's AudioFormatSpec abstraction.
# Parameters: format_spec - the PCM format description to convert.
# Return: a configured QAudioFormat instance.
def build_qaudio_format(format_spec: AudioFormatSpec) -> QAudioFormat:
    """Create a QAudioFormat using the provided PCM format settings."""

    qt_format = QAudioFormat()
    qt_format.setSampleRate(format_spec.rate)
    qt_format.setChannelCount(format_spec.channels)
    qt_format.setSampleFormat(qt_sample_format_from_audio_format_spec(format_spec))
    return qt_format


# Usage: convert a QAudioFormat produced by Qt into the app's lightweight format spec.
# Parameters: qt_format - the Qt format object to inspect.
# Return: an AudioFormatSpec containing rate, width, channel count, and normalized sample-format name.
def build_format_spec(qt_format: QAudioFormat) -> AudioFormatSpec:
    """Create an AudioFormatSpec from a QAudioFormat instance."""

    return AudioFormatSpec(
        rate=qt_format.sampleRate(),
        width=width_from_sample_format(qt_format.sampleFormat()),
        channels=qt_format.channelCount(),
        sample_format=sample_format_name_from_qt_sample_format(qt_format.sampleFormat()),
    )


class AudioDeviceCatalog(QObject):
    """Monitor and expose audio input and output devices for the UI and controller."""

    devices_changed = Signal()

    # Usage: create a device catalog that listens for Qt multimedia device changes.
    # Parameters: parent - optional QObject parent used for Qt ownership.
    # Return: None.
    def __init__(self, parent: QObject | None = None) -> None:
        """Initialize the audio device catalog and connect Qt device change signals."""

        super().__init__(parent)
        self._media_devices = QMediaDevices(self)
        self._media_devices.audioInputsChanged.connect(self._handle_qt_devices_changed)
        self._media_devices.audioOutputsChanged.connect(self._handle_qt_devices_changed)
        self._pipewire_nodes: list[PipeWireNode] = []
        self._pipewire_lookup: dict[str, PipeWireNode] = {}
        self.refresh_pipewire_metadata()

    # Usage: refresh the optional PipeWire metadata used to enrich device labels and ids.
    # Parameters: none.
    # Return: None.
    def refresh_pipewire_metadata(self) -> None:
        """Refresh optional PipeWire CLI metadata for best-effort device matching."""

        self._pipewire_nodes = list_audio_nodes()
        self._pipewire_lookup = build_node_lookup(self._pipewire_nodes)

    # Usage: list all microphone-capable Qt audio input devices.
    # Parameters: none.
    # Return: a list of AudioDeviceDescriptor values for the UI.
    def list_inputs(self) -> list[AudioDeviceDescriptor]:
        """Return descriptors for all currently available audio input devices."""

        return [self._build_descriptor(device, direction="input") for device in QMediaDevices.audioInputs()]

    # Usage: list all speaker-capable Qt audio output devices.
    # Parameters: none.
    # Return: a list of AudioDeviceDescriptor values for the UI.
    def list_outputs(self) -> list[AudioDeviceDescriptor]:
        """Return descriptors for all currently available audio output devices."""

        return [self._build_descriptor(device, direction="output") for device in QMediaDevices.audioOutputs()]

    # Usage: resolve a PipeWire output node name back to the persisted Qt output-device id used by playback routing.
    # Parameters: node_name - the PipeWire node.name value that should be located among current Qt output devices.
    # Return: the persisted output device id when a matching Qt output can be identified, otherwise None.
    def find_output_device_id_by_pipewire_node_name(self, node_name: str) -> str | None:
        """Return the persisted output-device id that matches the supplied PipeWire node name."""

        normalized_node_name = str(node_name).strip().casefold()
        if not normalized_node_name:
            return None

        for descriptor in self.list_outputs():
            if (descriptor.pipewire_node_name or "").casefold() == normalized_node_name:
                return descriptor.id

        return None

    # Usage: resolve a persisted microphone device id back to a concrete Qt audio device.
    # Parameters: device_id - the stored device id, or None to use the system default input.
    # Return: the matching QAudioDevice, or the default input if no match is found.
    def find_input_device(self, device_id: str | None) -> QAudioDevice:
        """Return the requested input device or fall back to the default microphone."""

        devices = list(QMediaDevices.audioInputs())
        if device_id:
            for device in devices:
                if encode_device_id(device) == device_id:
                    return device

        default_device = QMediaDevices.defaultAudioInput()
        if not default_device.isNull():
            return default_device

        return devices[0] if devices else QAudioDevice()

    # Usage: resolve persisted output ids back to concrete Qt audio devices for playback.
    # Parameters: device_ids - the stored output ids selected by the user.
    # Return: a list of matching QAudioDevice instances, using the system default only when no explicit output ids were requested.
    def find_output_devices(self, device_ids: list[str]) -> list[QAudioDevice]:
        """Return the requested playback devices without leaking to an unrelated default output when explicit targets are missing."""

        available_devices = list(QMediaDevices.audioOutputs())
        devices_by_id = {encode_device_id(device): device for device in available_devices}
        default_device = QMediaDevices.defaultAudioOutput()
        default_output_id = encode_device_id(default_device) if not default_device.isNull() else None
        selected_output_ids = choose_available_output_device_ids(
            device_ids,
            list(devices_by_id),
            default_output_id,
        )
        return [devices_by_id[output_id] for output_id in selected_output_ids if output_id in devices_by_id]

    # Usage: refresh device metadata after Qt reports a change and notify the UI.
    # Parameters: none.
    # Return: None.
    def _handle_qt_devices_changed(self) -> None:
        """Update cached metadata and emit a devices-changed notification."""

        self.refresh_pipewire_metadata()
        self.devices_changed.emit()

    # Usage: convert a Qt audio device into a normalized UI-facing descriptor.
    # Parameters: device - the QAudioDevice to describe; direction - either "input" or "output".
    # Return: an AudioDeviceDescriptor containing the display name, persisted id, and PipeWire metadata.
    def _build_descriptor(self, device: QAudioDevice, direction: str) -> AudioDeviceDescriptor:
        """Create a normalized device descriptor from a Qt audio device."""

        description = device.description()
        lookup_key = description.casefold()
        matched_node = self._pipewire_lookup.get(lookup_key)
        return AudioDeviceDescriptor(
            id=encode_device_id(device),
            name=description,
            direction=direction,
            is_default=device.isDefault(),
            pipewire_node_id=matched_node.node_id if matched_node else None,
            pipewire_node_name=matched_node.name if matched_node else None,
        )


class AudioCaptureStream(QObject):
    """Capture raw PCM microphone data from a selected Qt audio input device."""

    audio_chunk = Signal(bytes)
    capture_started = Signal(object)
    capture_stopped = Signal()
    error_occurred = Signal(str)

    # Usage: create a capture helper tied to a device catalog for microphone resolution.
    # Parameters: catalog - the AudioDeviceCatalog used to resolve persisted input ids; parent - optional QObject parent.
    # Return: None.
    def __init__(self, catalog: AudioDeviceCatalog, parent: QObject | None = None) -> None:
        """Initialize microphone capture helpers."""

        super().__init__(parent)
        self._catalog = catalog
        self._source: QAudioSource | None = None
        self._io_device: object | None = None

    # Usage: determine the concrete device and PCM format that Qt will use for microphone capture.
    # Parameters: device_id - the persisted input id or None; requested_format - the preferred PCM format.
    # Return: a ResolvedAudioInput describing the final Qt device and PCM format.
    def resolve_capture_plan(
        self,
        device_id: str | None,
        requested_format: AudioFormatSpec,
    ) -> ResolvedAudioInput:
        """Resolve the microphone device and exact PCM format that will be captured."""

        device = self._catalog.find_input_device(device_id)
        qt_format = build_qaudio_format(requested_format)
        if not device.isNull() and not device.isFormatSupported(qt_format):
            nearest_format_callable = getattr(device, "nearestFormat", None)
            if callable(nearest_format_callable):
                qt_format = nearest_format_callable(qt_format)
            else:
                qt_format = device.preferredFormat()

        return ResolvedAudioInput(
            device_id=encode_device_id(device),
            device=device,
            qt_format=qt_format,
            format_spec=build_format_spec(qt_format),
        )

    # Usage: begin microphone capture using a previously resolved input plan.
    # Parameters: plan - the resolved device and PCM format that should be activated.
    # Return: the AudioFormatSpec that will be emitted with raw PCM chunks.
    def start_capture(self, plan: ResolvedAudioInput) -> AudioFormatSpec:
        """Start capturing microphone audio using the provided capture plan."""

        self.stop_capture()
        if plan.device.isNull():
            raise RuntimeError("No audio input device is available")

        self._source = QAudioSource(plan.device, plan.qt_format, self)
        bytes_per_second = max(plan.format_spec.rate * plan.format_spec.frame_bytes(), 1)
        self._source.setBufferSize(int(bytes_per_second * (DEFAULT_AUDIO_BUFFER_MS / 1000.0)))
        self._io_device = self._source.start()
        if self._io_device is None:
            self._source.deleteLater()
            self._source = None
            raise RuntimeError("Qt failed to start microphone capture")

        self._io_device.readyRead.connect(self._drain_audio)
        self.capture_started.emit(plan.format_spec)
        return plan.format_spec

    # Usage: stop an active microphone capture session and release the Qt audio objects.
    # Parameters: none.
    # Return: None.
    def stop_capture(self) -> None:
        """Stop microphone capture if it is currently running."""

        if self._source is None:
            return

        self._source.stop()
        if self._io_device is not None:
            try:
                self._io_device.readyRead.disconnect(self._drain_audio)
            except (RuntimeError, TypeError):
                pass

        self._io_device = None
        self._source.deleteLater()
        self._source = None
        self.capture_stopped.emit()

    # Usage: read newly available microphone bytes from the Qt capture device and forward them as a signal.
    # Parameters: none.
    # Return: None.
    def _drain_audio(self) -> None:
        """Read all available microphone audio and emit it as raw PCM bytes."""

        if self._io_device is None:
            return

        try:
            raw_bytes = bytes(self._io_device.readAll())
        except RuntimeError as exc:
            self.error_occurred.emit(str(exc))
            return

        if raw_bytes:
            self.audio_chunk.emit(raw_bytes)


class MultiOutputPlayer(QObject):
    """Play raw PCM audio to one or more selected Qt output devices."""

    playback_started = Signal(object)
    playback_finished = Signal()
    error_occurred = Signal(str)

    # Usage: create a playback helper that can write the same PCM stream to several outputs.
    # Parameters: catalog - the AudioDeviceCatalog used to resolve output ids; parent - optional QObject parent.
    # Return: None.
    def __init__(self, catalog: AudioDeviceCatalog, parent: QObject | None = None) -> None:
        """Initialize the multi-output audio player."""

        super().__init__(parent)
        self._catalog = catalog
        self._active_outputs: list[ActiveOutput] = []
        self._format_spec: AudioFormatSpec | None = None
        self._estimated_buffer_ms = 0.0
        self._last_estimate_update = time.monotonic()
        self._finishing = False
        self._drain_timer = QTimer(self)
        self._drain_timer.setSingleShot(True)
        self._drain_timer.timeout.connect(self.stop_stream)
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(20)
        self._flush_timer.timeout.connect(self._flush_pending_buffers)

    # Usage: start a new playback stream targeting the requested output devices.
    # Parameters: output_device_ids - persisted output ids selected by the user; format_spec - the PCM format of incoming audio.
    # Return: the number of playback sinks that were started successfully.
    def start_stream(self, output_device_ids: list[str], format_spec: AudioFormatSpec) -> int:
        """Start a new PCM playback stream on one or more selected outputs."""

        self.stop_stream()
        self._format_spec = format_spec
        self._estimated_buffer_ms = 0.0
        self._last_estimate_update = time.monotonic()
        self._finishing = False

        selected_devices = self._catalog.find_output_devices(output_device_ids)
        qt_format = build_qaudio_format(format_spec)

        for device in selected_devices:
            if device.isNull():
                continue

            playback_format = qt_format
            if not device.isFormatSupported(playback_format):
                nearest_format_callable = getattr(device, "nearestFormat", None)
                if callable(nearest_format_callable):
                    playback_format = nearest_format_callable(playback_format)
                if build_format_spec(playback_format) != format_spec:
                    self.error_occurred.emit(
                        f"Output '{device.description()}' does not support {format_spec.rate}Hz/{format_spec.channels}ch/{format_spec.width * 8}bit PCM"
                    )
                    continue

            sink = QAudioSink(device, playback_format, self)
            sink.stateChanged.connect(partial(self._handle_sink_state_changed, encode_device_id(device)))
            io_device = sink.start()
            if io_device is None:
                sink.deleteLater()
                self.error_occurred.emit(f"Qt failed to start playback on '{device.description()}'")
                continue

            descriptor = AudioDeviceDescriptor(
                id=encode_device_id(device),
                name=device.description(),
                direction="output",
                is_default=device.isDefault(),
            )
            self._active_outputs.append(
                ActiveOutput(
                    descriptor=descriptor,
                    sink=sink,
                    io_device=io_device,
                    pending_bytes=bytearray(),
                )
            )

        if self._active_outputs:
            self.playback_started.emit(format_spec)

        return len(self._active_outputs)

    # Usage: write one raw PCM chunk to every active output sink while buffering any short writes for retry.
    # Parameters: chunk - the PCM bytes received from the Wyoming TTS service.
    # Return: the number of bytes that were attempted for playback.
    def write_audio(self, chunk: bytes) -> int:
        """Write one PCM chunk to every active playback sink and preserve short-write tails."""

        if not chunk or not self._active_outputs or self._format_spec is None:
            return 0

        now = time.monotonic()
        elapsed_ms = (now - self._last_estimate_update) * 1000.0
        self._estimated_buffer_ms = max(0.0, self._estimated_buffer_ms - elapsed_ms)
        self._estimated_buffer_ms += self._format_spec.bytes_to_duration_ms(len(chunk))
        self._last_estimate_update = now

        has_pending_bytes = False
        for active_output in list(self._active_outputs):
            has_pending_bytes = self._write_to_output(active_output, chunk) or has_pending_bytes

        if has_pending_bytes and not self._flush_timer.isActive():
            self._flush_timer.start()

        return len(chunk)

    # Usage: mark the stream as complete, flush any buffered short writes, and then stop playback after queued audio drains.
    # Parameters: none.
    # Return: None.
    def finish_stream(self) -> None:
        """Schedule playback shutdown after buffered audio and pending writes are drained."""

        if not self._active_outputs:
            self.stop_stream()
            return

        self._finishing = True
        self._flush_pending_buffers()
        if any(active_output.pending_bytes for active_output in self._active_outputs):
            if not self._flush_timer.isActive():
                self._flush_timer.start()
            return

        self._schedule_drain_stop()

    # Usage: immediately stop all active playback sinks and release their Qt resources.
    # Parameters: none.
    # Return: None.
    def stop_stream(self) -> None:
        """Stop all playback sinks and reset the player state."""

        self._drain_timer.stop()
        self._flush_timer.stop()
        active_outputs = list(self._active_outputs)
        self._active_outputs.clear()
        self._format_spec = None
        self._estimated_buffer_ms = 0.0
        self._finishing = False

        for active_output in active_outputs:
            active_output.sink.stop()
            active_output.sink.deleteLater()

        if active_outputs:
            self.playback_finished.emit()

    # Usage: attempt to write pending and new PCM bytes to one active output while preserving any short-write remainder.
    # Parameters: active_output - the output sink that should receive bytes; chunk - the newest PCM bytes to append after any pending remainder.
    # Return: True when bytes remain pending for a later retry, otherwise False.
    def _write_to_output(self, active_output: ActiveOutput, chunk: bytes) -> bool:
        """Write bytes to one output sink and preserve any short-write remainder for retry."""

        combined_bytes = bytes(active_output.pending_bytes) + chunk
        active_output.pending_bytes.clear()
        if not combined_bytes:
            return False

        try:
            written = int(active_output.io_device.write(combined_bytes))
        except RuntimeError as exc:
            self.error_occurred.emit(
                f"Playback write failed for '{active_output.descriptor.name}': {exc}"
            )
            active_output.pending_bytes.extend(combined_bytes)
            return True

        if written < len(combined_bytes):
            active_output.pending_bytes.extend(combined_bytes[max(written, 0) :])
            return True

        return False

    # Usage: retry any previously short-written PCM bytes that still remain buffered per output sink.
    # Parameters: none.
    # Return: None.
    def _flush_pending_buffers(self) -> None:
        """Retry any PCM bytes that were previously left pending after short writes."""

        if not self._active_outputs:
            self._flush_timer.stop()
            return

        still_pending = False
        for active_output in self._active_outputs:
            if not active_output.pending_bytes:
                continue
            pending_snapshot = bytes(active_output.pending_bytes)
            active_output.pending_bytes.clear()
            still_pending = self._write_to_output(active_output, pending_snapshot) or still_pending

        if still_pending:
            if not self._flush_timer.isActive():
                self._flush_timer.start()
            return

        self._flush_timer.stop()
        if self._finishing:
            self._schedule_drain_stop()

    # Usage: stop playback after the currently queued PCM data is estimated to have reached the speakers.
    # Parameters: none.
    # Return: None.
    def _schedule_drain_stop(self) -> None:
        """Schedule playback shutdown after the currently queued audio is expected to drain."""

        # Keep the margin small so sentence-to-sentence chaining feels gapless while
        # still leaving room for scheduler jitter so the tail is never cut off.
        drain_delay = max(80, int(self._estimated_buffer_ms) + 100)
        self._drain_timer.start(drain_delay)

    # Usage: react to Qt playback state changes, primarily to surface sink errors while streaming.
    # Parameters: output_id - the persisted output id whose sink changed; state - the new QAudio state.
    # Return: None.
    def _handle_sink_state_changed(self, output_id: str, state: QAudio.State) -> None:
        """Handle playback state changes and surface non-benign sink errors."""

        if state != QAudio.State.StoppedState:
            return

        for active_output in self._active_outputs:
            if active_output.descriptor.id != output_id:
                continue
            if active_output.sink.error() != QAudio.Error.NoError and not self._finishing:
                self.error_occurred.emit(
                    f"Playback stopped unexpectedly on '{active_output.descriptor.name}'"
                )
            return
