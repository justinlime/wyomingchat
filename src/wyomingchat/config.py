"""Configuration models for Wyoming Voice Bridge."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .constants import (
    DEFAULT_MIC_GATE_THRESHOLD_PERCENT,
    DEFAULT_MIC_GAIN,
    DEFAULT_STOP_SILENCE_MS,
    DEFAULT_STT_HOST,
    DEFAULT_STT_PORT,
    DEFAULT_TTS_GAIN,
    DEFAULT_TTS_HOST,
    DEFAULT_TTS_PORT,
    DEFAULT_VIRTUAL_MIC_DESCRIPTION,
    DEFAULT_VIRTUAL_MIC_NODE_NAME,
    MAX_MIC_GAIN,
    MAX_STOP_SILENCE_MS,
    MAX_TTS_GAIN,
    MIN_STOP_SILENCE_MS,
)


# Usage: coerce an arbitrary value into a non-empty string while falling back to a default on invalid input.
# Parameters: value - the raw value that should become a string; default - the fallback string to use when the value is missing or blank.
# Return: a normalized string guaranteed to be non-empty.
def coerce_str(value: Any, default: str) -> str:
    """Return a normalized non-empty string with a safe fallback."""

    normalized = str(value).strip() if value is not None else ""
    return normalized or default


# Usage: coerce an arbitrary value into an integer while falling back to a default on invalid input.
# Parameters: value - the raw value that should become an integer; default - the fallback integer when conversion fails.
# Return: a validated integer value.
def coerce_int(value: Any, default: int) -> int:
    """Return an integer parsed from a raw value, or the provided default on failure."""

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# Usage: coerce an arbitrary value into a boolean while treating common false-like strings as False.
# Parameters: value - the raw value that should become a boolean; default - the fallback boolean when the value is missing.
# Return: a normalized boolean value.
def coerce_bool(value: Any, default: bool) -> bool:
    """Return a boolean parsed from a raw value with safe string handling."""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().casefold()
        if lowered in {"0", "false", "no", "off", ""}:
            return False
        if lowered in {"1", "true", "yes", "on"}:
            return True
    return bool(value)


# Usage: coerce an arbitrary value into a float while falling back to a default on invalid input.
# Parameters: value - the raw value that should become a float; default - the fallback float when conversion fails.
# Return: a validated float value.
def coerce_float(value: Any, default: float) -> float:
    """Return a float parsed from a raw value, or the provided default on failure."""

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# Usage: coerce an arbitrary value into a TCP port number while rejecting values outside the valid 1-65535 range.
# Parameters: value - the raw value that should become a TCP port; default - the fallback port when conversion fails or the value is out of range.
# Return: a validated TCP port number.
def coerce_port(value: Any, default: int) -> int:
    """Return a valid TCP port number parsed from a raw value, or the default on failure."""

    parsed_port = coerce_int(value, default)
    if 1 <= parsed_port <= 65535:
        return parsed_port
    return default


# Usage: coerce an arbitrary value into a percentage while clamping it into the inclusive 0-100 slider range.
# Parameters: value - the raw value that should become a percentage; default - the fallback percentage when conversion fails.
# Return: an integer percentage constrained to the 0-100 range.
def coerce_percentage(value: Any, default: int) -> int:
    """Return a percentage parsed from a raw value and clamped to the 0-100 range."""

    parsed_percentage = coerce_int(value, default)
    return max(0, min(100, parsed_percentage))


@dataclass(slots=True)
class ServiceEndpoint:
    """Represent a network endpoint for a Wyoming-compatible service."""

    host: str
    port: int

    # Usage: serialize a service endpoint for JSON persistence.
    # Parameters: none.
    # Return: a JSON-compatible dictionary with host and port values.
    def to_dict(self) -> dict[str, Any]:
        """Convert the endpoint into a JSON-compatible dictionary."""

        return {"host": self.host, "port": self.port}

    @classmethod
    # Usage: build a service endpoint from a partially populated JSON dictionary.
    # Parameters: payload - dictionary data read from disk; default_host - fallback host; default_port - fallback port.
    # Return: a validated ServiceEndpoint with sensible defaults when keys are missing.
    def from_dict(
        cls,
        payload: dict[str, Any] | None,
        default_host: str,
        default_port: int,
    ) -> "ServiceEndpoint":
        """Create a ServiceEndpoint from persisted JSON data."""

        payload = payload if isinstance(payload, dict) else {}
        return cls(
            host=coerce_str(payload.get("host"), default_host),
            port=coerce_port(payload.get("port"), default_port),
        )


@dataclass(slots=True)
class AudioSelection:
    """Store the user's selected input and output audio device identifiers."""

    input_device_id: str | None = None
    output_device_ids: list[str] = field(default_factory=list)

    # Usage: serialize selected audio devices for JSON persistence.
    # Parameters: none.
    # Return: a JSON-compatible dictionary with input and output device ids.
    def to_dict(self) -> dict[str, Any]:
        """Convert the selection into a JSON-compatible dictionary."""

        return {
            "input_device_id": self.input_device_id,
            "output_device_ids": list(self.output_device_ids),
        }

    @classmethod
    # Usage: build an AudioSelection from JSON configuration data.
    # Parameters: payload - dictionary data read from disk, which may be missing keys.
    # Return: an AudioSelection with normalized output device ids.
    def from_dict(cls, payload: dict[str, Any] | None) -> "AudioSelection":
        """Create an AudioSelection from persisted JSON data."""

        payload = payload if isinstance(payload, dict) else {}
        raw_outputs = payload.get("output_device_ids", [])
        if not isinstance(raw_outputs, list):
            raw_outputs = []
        output_ids = [str(item) for item in raw_outputs if str(item).strip()]
        input_device_id = payload.get("input_device_id")
        return cls(
            input_device_id=str(input_device_id) if input_device_id else None,
            output_device_ids=output_ids,
        )


@dataclass(slots=True)
class TtsVoiceConfig:
    """Store the Wyoming TTS voice fields the user selected for synthesis."""

    name: str = ""
    language: str = ""
    speaker: str = ""

    # Usage: report whether any voice-selection field has been configured by the user.
    # Parameters: none.
    # Return: True when at least one of name, language, or speaker is non-empty.
    def is_configured(self) -> bool:
        """Return whether this voice selection contains any explicit voice preference."""

        return any(part for part in (self.name.strip(), self.language.strip(), self.speaker.strip()))

    # Usage: build the Wyoming request payload fragment used inside synthesize events.
    # Parameters: none.
    # Return: a dictionary containing only non-empty voice fields, or None when no voice is selected.
    def to_request_payload(self) -> dict[str, str] | None:
        """Return the Wyoming voice payload for synthesis requests, or None when unset."""

        payload = {
            key: value
            for key, value in {
                "name": self.name.strip(),
                "language": self.language.strip(),
                "speaker": self.speaker.strip(),
            }.items()
            if value
        }
        return payload or None

    # Usage: create a compact user-facing label for the currently selected or discovered voice option.
    # Parameters: none.
    # Return: a readable label containing the voice name plus optional language and speaker details.
    def to_display_label(self) -> str:
        """Return a readable label for UI voice selectors and status messages."""

        base_name = self.name.strip() or "Default server voice"
        details = [part for part in (self.language.strip(), self.speaker.strip()) if part]
        if not details:
            return base_name
        return f"{base_name} ({' / '.join(details)})"

    # Usage: serialize the selected voice for JSON persistence.
    # Parameters: none.
    # Return: a JSON-compatible dictionary containing the selected voice fields.
    def to_dict(self) -> dict[str, Any]:
        """Convert the voice selection into a JSON-compatible dictionary."""

        return {
            "name": self.name,
            "language": self.language,
            "speaker": self.speaker,
        }

    @classmethod
    # Usage: build a TtsVoiceConfig from JSON configuration data or another loose mapping.
    # Parameters: payload - dictionary data read from disk, which may be missing some voice fields.
    # Return: a normalized TtsVoiceConfig with blank strings for missing fields.
    def from_dict(cls, payload: dict[str, Any] | None) -> "TtsVoiceConfig":
        """Create a TtsVoiceConfig from persisted JSON data."""

        payload = payload if isinstance(payload, dict) else {}
        return cls(
            name=coerce_str(payload.get("name"), ""),
            language=coerce_str(payload.get("language"), ""),
            speaker=coerce_str(payload.get("speaker"), ""),
        )


# Usage: build a user-facing label for one selectable TTS voice while preferring bare speaker names when a single voice exposes multiple speakers.
# Parameters: voice - the selectable voice option being rendered; available_voices - the full set of currently selectable voice options shown in the same UI control.
# Return: a concise display label that keeps multi-speaker voice options readable without changing the Wyoming request payload.
def build_tts_voice_display_label(voice: TtsVoiceConfig, available_voices: list[TtsVoiceConfig]) -> str:
    """Return a readable UI label for one selectable TTS voice option."""

    matching_speaker_variants = [
        option
        for option in available_voices
        if option.name.strip() == voice.name.strip() and option.speaker.strip()
    ]
    distinct_speaker_names = {option.speaker.strip().casefold() for option in matching_speaker_variants}
    if voice.speaker.strip() and len(distinct_speaker_names) > 1:
        speaker_label = voice.speaker.strip()
        if voice.language.strip():
            return f"{speaker_label} ({voice.language.strip()})"
        return speaker_label

    return voice.to_display_label()


@dataclass(slots=True)
class VirtualMicrophoneConfig:
    """Store the virtual microphone settings for the current platform strategy.

    On Linux the node_name and description fields configure the managed
    PipeWire loopback pair. On Windows the cable_device_id field records which
    virtual audio cable playback endpoint TTS audio is routed into; the
    paired microphone endpoint is then selectable by other applications.
    """

    enabled: bool = False
    node_name: str = DEFAULT_VIRTUAL_MIC_NODE_NAME
    description: str = DEFAULT_VIRTUAL_MIC_DESCRIPTION
    cable_device_id: str | None = None

    # Usage: serialize virtual microphone settings for JSON persistence.
    # Parameters: none.
    # Return: a JSON-compatible dictionary with the virtual microphone settings.
    def to_dict(self) -> dict[str, Any]:
        """Convert the virtual microphone configuration into a JSON-compatible dictionary."""

        return {
            "enabled": self.enabled,
            "node_name": self.node_name,
            "description": self.description,
            "cable_device_id": self.cable_device_id,
        }

    @classmethod
    # Usage: build a VirtualMicrophoneConfig from JSON configuration data.
    # Parameters: payload - dictionary data read from disk, which may be partially populated.
    # Return: a VirtualMicrophoneConfig with normalized fields and safe defaults.
    def from_dict(cls, payload: dict[str, Any] | None) -> "VirtualMicrophoneConfig":
        """Create a VirtualMicrophoneConfig from persisted JSON data."""

        payload = payload if isinstance(payload, dict) else {}
        raw_cable_device_id = payload.get("cable_device_id")
        return cls(
            enabled=coerce_bool(payload.get("enabled"), False),
            node_name=coerce_str(payload.get("node_name"), DEFAULT_VIRTUAL_MIC_NODE_NAME),
            description=coerce_str(payload.get("description"), DEFAULT_VIRTUAL_MIC_DESCRIPTION),
            cable_device_id=(
                str(raw_cable_device_id).strip()
                if raw_cable_device_id is not None and str(raw_cable_device_id).strip()
                else None
            ),
        )


@dataclass(slots=True)
class AppConfig:
    """Represent the complete persisted application configuration."""

    stt_endpoint: ServiceEndpoint = field(
        default_factory=lambda: ServiceEndpoint(DEFAULT_STT_HOST, DEFAULT_STT_PORT)
    )
    tts_endpoint: ServiceEndpoint = field(
        default_factory=lambda: ServiceEndpoint(DEFAULT_TTS_HOST, DEFAULT_TTS_PORT)
    )
    tts_voice: TtsVoiceConfig = field(default_factory=TtsVoiceConfig)
    mic_gate_threshold_percent: int = DEFAULT_MIC_GATE_THRESHOLD_PERCENT
    mic_gain: float = DEFAULT_MIC_GAIN
    tts_gain: float = DEFAULT_TTS_GAIN
    stop_silence_ms: int = DEFAULT_STOP_SILENCE_MS
    audio: AudioSelection = field(default_factory=AudioSelection)
    virtual_microphone: VirtualMicrophoneConfig = field(default_factory=VirtualMicrophoneConfig)
    last_transcript: str = ""

    # Usage: serialize the full app configuration for disk persistence.
    # Parameters: none.
    # Return: a JSON-compatible dictionary containing all persisted settings.
    def to_dict(self) -> dict[str, Any]:
        """Convert the application configuration into a JSON-compatible dictionary."""

        return {
            "stt_endpoint": self.stt_endpoint.to_dict(),
            "tts_endpoint": self.tts_endpoint.to_dict(),
            "tts_voice": self.tts_voice.to_dict(),
            "mic_gate_threshold_percent": self.mic_gate_threshold_percent,
            "mic_gain": self.mic_gain,
            "tts_gain": self.tts_gain,
            "stop_silence_ms": self.stop_silence_ms,
            "audio": self.audio.to_dict(),
            "virtual_microphone": self.virtual_microphone.to_dict(),
            "last_transcript": self.last_transcript,
        }

    @classmethod
    # Usage: build the full application configuration from JSON data loaded from disk.
    # Parameters: payload - dictionary data read from disk, which may be missing sections.
    # Return: a complete AppConfig filled with defaults where necessary.
    def from_dict(cls, payload: dict[str, Any] | None) -> "AppConfig":
        """Create an AppConfig from persisted JSON data."""

        payload = payload if isinstance(payload, dict) else {}
        legacy_virtual_mic = payload.get("virtual_microphone")
        return cls(
            stt_endpoint=ServiceEndpoint.from_dict(
                payload.get("stt_endpoint"),
                default_host=DEFAULT_STT_HOST,
                default_port=DEFAULT_STT_PORT,
            ),
            tts_endpoint=ServiceEndpoint.from_dict(
                payload.get("tts_endpoint"),
                default_host=DEFAULT_TTS_HOST,
                default_port=DEFAULT_TTS_PORT,
            ),
            tts_voice=TtsVoiceConfig.from_dict(payload.get("tts_voice")),
            mic_gate_threshold_percent=coerce_percentage(
                payload.get("mic_gate_threshold_percent"),
                DEFAULT_MIC_GATE_THRESHOLD_PERCENT,
            ),
            mic_gain=max(
                1.0,
                min(MAX_MIC_GAIN, coerce_float(payload.get("mic_gain"), DEFAULT_MIC_GAIN)),
            ),
            tts_gain=max(
                1.0,
                min(MAX_TTS_GAIN, coerce_float(payload.get("tts_gain"), DEFAULT_TTS_GAIN)),
            ),
            stop_silence_ms=max(
                MIN_STOP_SILENCE_MS,
                min(MAX_STOP_SILENCE_MS, coerce_int(payload.get("stop_silence_ms"), DEFAULT_STOP_SILENCE_MS)),
            ),
            audio=AudioSelection.from_dict(payload.get("audio")),
            virtual_microphone=VirtualMicrophoneConfig.from_dict(legacy_virtual_mic),
            last_transcript=coerce_str(payload.get("last_transcript"), ""),
        )


# Usage: construct a default application configuration without reading disk state.
# Parameters: none.
# Return: a new AppConfig populated with project default values.
def build_default_config() -> AppConfig:
    """Return a fresh configuration object using built-in defaults."""

    return AppConfig()
