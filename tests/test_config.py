"""Tests for configuration model serialization and persistence."""

from __future__ import annotations

from pathlib import Path

from wyomingchat.config import AppConfig, AudioSelection, ServiceEndpoint, ShortcutConfig
from wyomingchat.storage import JsonConfigStore


# Usage: verify that AppConfig serialization preserves nested endpoint, audio, and shortcut values.
# Parameters: none.
# Return: None.
def test_app_config_round_trip_serialization() -> None:
    """Ensure AppConfig round-trips through dictionaries without losing values."""

    original = AppConfig(
        stt_endpoint=ServiceEndpoint(host="stt.local", port=12000),
        tts_endpoint=ServiceEndpoint(host="tts.local", port=13000),
        audio=AudioSelection(input_device_id="mic-1", output_device_ids=["spk-1", "spk-2"]),
        shortcut=ShortcutConfig(
            preferred_trigger="Super+space",
            description="Talk now",
            trigger_description="Meta+Space",
            enabled=True,
        ),
        last_transcript="hello world",
    )

    restored = AppConfig.from_dict(original.to_dict())
    assert restored == original


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
        audio=AudioSelection(input_device_id="default-mic", output_device_ids=["default-speaker"]),
        shortcut=ShortcutConfig(preferred_trigger="Ctrl+Alt+space", description="Push to talk"),
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
        '{"stt_endpoint": {"host": "", "port": "99999"}, "tts_endpoint": {"port": "abc"}, "shortcut": {"enabled": "false"}}',
        encoding="utf-8",
    )
    store = JsonConfigStore(config_path=config_path)

    loaded = store.load()

    assert loaded.stt_endpoint.host == "127.0.0.1"
    assert loaded.stt_endpoint.port == 10300
    assert loaded.tts_endpoint.port == 10200
    assert loaded.shortcut.enabled is False
