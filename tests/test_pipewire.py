"""Tests for PipeWire helper functions used by the app."""

from __future__ import annotations

from wyomingchat.pipewire import (
    build_virtual_microphone_config,
    build_virtual_microphone_sink_node_name,
    escape_pipewire_string,
    sanitize_pipewire_node_name,
)


# Usage: verify that user-provided node names are normalized into PipeWire-safe identifiers.
# Parameters: none.
# Return: None.
def test_sanitize_pipewire_node_name_replaces_unsafe_characters() -> None:
    """Ensure unsafe PipeWire node-name characters are replaced predictably."""

    assert sanitize_pipewire_node_name("Wyoming Voice Bridge Mic") == "Wyoming_Voice_Bridge_Mic"
    assert sanitize_pipewire_node_name("!!!") == "wyoming_voice_bridge_mic"


# Usage: verify that the managed virtual microphone sink node name stays in sync with the PipeWire config naming convention.
# Parameters: none.
# Return: None.
def test_build_virtual_microphone_sink_node_name_uses_sanitized_source_name() -> None:
    """Ensure the managed sink node name always derives from the sanitized source node name."""

    assert build_virtual_microphone_sink_node_name("Bridge Mic") == "Bridge_Mic_sink"
    assert build_virtual_microphone_sink_node_name("!!!") == "wyoming_voice_bridge_mic_sink"


# Usage: verify that user-provided PipeWire description text is flattened and escaped before being embedded into config.
# Parameters: none.
# Return: None.
def test_escape_pipewire_string_flattens_control_whitespace_and_quotes() -> None:
    """Ensure PipeWire string escaping removes line breaks and escapes quotes safely."""

    escaped = escape_pipewire_string('Bridge "Mic"\nName')

    assert "\n" not in escaped
    assert '\\"Mic\\"' in escaped
    assert escaped.endswith("Name")


# Usage: verify that the generated PipeWire config creates a sink/source pair so the app can target the sink while other apps see a microphone-like source.
# Parameters: none.
# Return: None.
def test_build_virtual_microphone_config_contains_expected_properties() -> None:
    """Ensure the generated virtual microphone config contains the expected loopback sink/source properties."""

    config = build_virtual_microphone_config("bridge-mic", "Bridge Mic")

    assert 'name = libpipewire-module-loopback' in config
    assert 'node.name = "bridge-mic_sink"' in config
    assert 'node.description = "Bridge Mic Output"' in config
    assert 'media.class = Audio/Sink' in config
    assert 'node.name = "bridge-mic"' in config
    assert 'node.description = "Bridge Mic"' in config
    assert 'media.class = Audio/Source' in config
