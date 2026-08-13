"""Tests for configuration model serialization and persistence."""

from __future__ import annotations

from pathlib import Path

from wyomingchat.config import (
    AppConfig,
    AudioSelection,
    ServiceEndpoint,
    TtsVoiceConfig,
    VirtualMicrophoneConfig,
    build_tts_voice_display_label,
)
from wyomingchat.storage import JsonConfigStore


# Usage: verify that AppConfig serialization preserves nested endpoint, audio, and virtual microphone values.
# Parameters: none.
# Return: None.
def test_app_config_round_trip_serialization() -> None:
    """Ensure AppConfig round-trips through dictionaries without losing values."""

    original = AppConfig(
        stt_endpoint=ServiceEndpoint(host="stt.local", port=12000),
        tts_endpoint=ServiceEndpoint(host="tts.local", port=13000),
        tts_voice=TtsVoiceConfig(name="kokoro", language="en", speaker="bella"),
        mic_gate_threshold_percent=12,
        audio=AudioSelection(input_device_id="mic-1", output_device_ids=["spk-1", "spk-2"]),
        virtual_microphone=VirtualMicrophoneConfig(
            enabled=True,
            node_name="wyoming_mic",
            description="Wyoming Voice Bridge Mic",
        ),
        last_transcript="hello world",
    )

    restored = AppConfig.from_dict(original.to_dict())
    assert restored == original


# Usage: verify that the TTS voice label helper prefers speaker-only labels when a single voice exposes multiple speakers.
# Parameters: none.
# Return: None.
def test_build_tts_voice_display_label_prefers_speaker_name_for_multi_speaker_voice() -> None:
    """Ensure multi-speaker voice options are shown using readable speaker labels."""

    available_voices = [
        TtsVoiceConfig(name="fatterqwen", speaker="Hank"),
        TtsVoiceConfig(name="fatterqwen", speaker="Victor"),
        TtsVoiceConfig(name="fatterqwen", speaker="Spy"),
    ]

    labels = [build_tts_voice_display_label(voice, available_voices) for voice in available_voices]

    assert labels == ["Hank", "Victor", "Spy"]


# Usage: verify that the JSON config store falls back to defaults when no config file exists.
# Parameters: none.
# Return: None.
def test_json_config_store_loads_defaults_for_missing_file(tmp_path: Path) -> None:
    """Ensure the config store returns default settings when the file is absent."""

    store = JsonConfigStore(config_path=tmp_path / "missing.json")
    config = store.load()
    assert isinstance(config, AppConfig)
    assert config.stt_endpoint.host == "127.0.0.1"
    assert config.tts_endpoint.host == "127.0.0.1"


# Usage: verify that the JSON config store writes and reloads the same values through disk persistence.
# Parameters: tmp_path - pytest temporary directory fixture used for isolated file output.
# Return: None.
def test_json_config_store_persists_and_reloads_configuration(tmp_path: Path) -> None:
    """Ensure the config store can save and later reload a configuration file."""

    config_path = tmp_path / "config.json"
    store = JsonConfigStore(config_path=config_path)
    original = AppConfig(
        stt_endpoint=ServiceEndpoint(host="10.0.0.5", port=10300),
        tts_endpoint=ServiceEndpoint(host="10.0.0.6", port=10200),
        tts_voice=TtsVoiceConfig(name="piper", language="en-US", speaker="amy"),
        mic_gate_threshold_percent=9,
        audio=AudioSelection(input_device_id="default-mic", output_device_ids=["default-speaker"]),
        virtual_microphone=VirtualMicrophoneConfig(
            enabled=True,
            node_name="voice_bridge_sink",
            description="Voice Bridge Sink",
        ),
        last_transcript="saved transcript",
    )

    saved_path = store.save(original)
    reloaded = store.load()

    assert saved_path == config_path
    assert reloaded == original


# Usage: verify that malformed persisted values fall back to defaults instead of crashing config loading.
# Parameters: tmp_path - pytest temporary directory fixture used for isolated file output.
# Return: None.
def test_json_config_store_falls_back_on_invalid_field_types(tmp_path: Path) -> None:
    """Ensure malformed persisted values fall back to defaults instead of raising exceptions."""

    config_path = tmp_path / "broken.json"
    config_path.write_text(
        '{"stt_endpoint": {"host": "", "port": "99999"}, "tts_endpoint": {"port": "abc"}, "tts_voice": {"name": 123, "speaker": null}, "mic_gate_threshold_percent": "999", "virtual_microphone": {"enabled": "true", "node_name": ""}}',
        encoding="utf-8",
    )
    store = JsonConfigStore(config_path=config_path)

    loaded = store.load()

    assert loaded.stt_endpoint.host == "127.0.0.1"
    assert loaded.stt_endpoint.port == 10300
    assert loaded.tts_endpoint.port == 10200
    assert loaded.tts_voice.name == "123"
    assert loaded.tts_voice.speaker == ""
    assert loaded.mic_gate_threshold_percent == 100
    assert loaded.virtual_microphone.enabled is True
    assert loaded.virtual_microphone.node_name == "wyoming_voice_bridge_mic"


# Usage: verify that the persisted cable device id survives a config round trip on Windows.
# Parameters: none.
# Return: None.
def test_virtual_microphone_cable_device_id_round_trips() -> None:
    """Ensure cable_device_id is preserved through serialization."""

    original = VirtualMicrophoneConfig(
        enabled=True,
        node_name="ignored-on-windows",
        description="ignored-on-windows",
        cable_device_id="cable-input-id-1",
    )

    restored = VirtualMicrophoneConfig.from_dict(original.to_dict())

    assert restored == original
    assert restored.cable_device_id == "cable-input-id-1"


# Usage: verify that the microphone boost multiplier survives a config round trip.
# Parameters: none.
# Return: None.
def test_mic_gain_round_trips_and_clamps() -> None:
    """Ensure mic_gain persists and is clamped to the supported range."""

    original = AppConfig()
    original.mic_gain = 3.5

    restored = AppConfig.from_dict(original.to_dict())
    assert restored.mic_gain == 3.5

    out_of_range = AppConfig.from_dict({"mic_gain": 50.0})
    assert out_of_range.mic_gain == 10.0


# Usage: verify that the streaming synthesis toggle survives a config round trip.
# Parameters: none.
# Return: None.
def test_streaming_synthesis_round_trips() -> None:
    """Ensure streaming_synthesis persists and defaults to enabled."""

    assert AppConfig().streaming_synthesis is True

    original = AppConfig()
    original.streaming_synthesis = False
    restored = AppConfig.from_dict(original.to_dict())
    assert restored.streaming_synthesis is False
