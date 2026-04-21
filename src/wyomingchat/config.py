"""Configuration models for Wyoming Voice Bridge."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .constants import (
    DEFAULT_PREFERRED_TRIGGER,
    DEFAULT_SHORTCUT_DESCRIPTION,
    DEFAULT_STT_HOST,
    DEFAULT_STT_PORT,
    DEFAULT_TTS_HOST,
    DEFAULT_TTS_PORT,
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


# Usage: coerce an arbitrary value into a TCP port number while rejecting values outside the valid 1-65535 range.
# Parameters: value - the raw value that should become a TCP port; default - the fallback port when conversion fails or the value is out of range.
# Return: a validated TCP port number.
def coerce_port(value: Any, default: int) -> int:
    """Return a valid TCP port number parsed from a raw value, or the default on failure."""

    parsed_port = coerce_int(value, default)
    if 1 <= parsed_port <= 65535:
        return parsed_port
    return default


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
class ShortcutConfig:
    """Store the user's preferred global shortcut details."""

    preferred_trigger: str = DEFAULT_PREFERRED_TRIGGER
    description: str = DEFAULT_SHORTCUT_DESCRIPTION
    trigger_description: str | None = None
    enabled: bool = True

    # Usage: serialize global shortcut preferences for JSON persistence.
    # Parameters: none.
    # Return: a JSON-compatible dictionary with shortcut settings.
    def to_dict(self) -> dict[str, Any]:
        """Convert the shortcut configuration into a JSON-compatible dictionary."""

        return {
            "preferred_trigger": self.preferred_trigger,
            "description": self.description,
            "trigger_description": self.trigger_description,
            "enabled": self.enabled,
        }

    @classmethod
    # Usage: build a ShortcutConfig from JSON configuration data.
    # Parameters: payload - dictionary data read from disk, which may be partially populated.
    # Return: a ShortcutConfig with normalized text fields and defaults.
    def from_dict(cls, payload: dict[str, Any] | None) -> "ShortcutConfig":
        """Create a ShortcutConfig from persisted JSON data."""

        payload = payload if isinstance(payload, dict) else {}
        preferred_trigger = coerce_str(payload.get("preferred_trigger"), DEFAULT_PREFERRED_TRIGGER)
        description = coerce_str(payload.get("description"), DEFAULT_SHORTCUT_DESCRIPTION)
        trigger_description = payload.get("trigger_description")
        return cls(
            preferred_trigger=preferred_trigger,
            description=description,
            trigger_description=str(trigger_description).strip() if trigger_description else None,
            enabled=coerce_bool(payload.get("enabled"), True),
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
    audio: AudioSelection = field(default_factory=AudioSelection)
    shortcut: ShortcutConfig = field(default_factory=ShortcutConfig)
    last_transcript: str = ""

    # Usage: serialize the full app configuration for disk persistence.
    # Parameters: none.
    # Return: a JSON-compatible dictionary containing all persisted settings.
    def to_dict(self) -> dict[str, Any]:
        """Convert the application configuration into a JSON-compatible dictionary."""

        return {
            "stt_endpoint": self.stt_endpoint.to_dict(),
            "tts_endpoint": self.tts_endpoint.to_dict(),
            "audio": self.audio.to_dict(),
            "shortcut": self.shortcut.to_dict(),
            "last_transcript": self.last_transcript,
        }

    @classmethod
    # Usage: build the full application configuration from JSON data loaded from disk.
    # Parameters: payload - dictionary data read from disk, which may be missing sections.
    # Return: a complete AppConfig filled with defaults where necessary.
    def from_dict(cls, payload: dict[str, Any] | None) -> "AppConfig":
        """Create an AppConfig from persisted JSON data."""

        payload = payload if isinstance(payload, dict) else {}
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
            audio=AudioSelection.from_dict(payload.get("audio")),
            shortcut=ShortcutConfig.from_dict(payload.get("shortcut")),
            last_transcript=coerce_str(payload.get("last_transcript"), ""),
        )


# Usage: construct a default application configuration without reading disk state.
# Parameters: none.
# Return: a new AppConfig populated with project default values.
def build_default_config() -> AppConfig:
    """Return a fresh configuration object using built-in defaults."""

    return AppConfig()
