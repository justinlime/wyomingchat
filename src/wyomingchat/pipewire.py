"""Optional PipeWire inspection and virtual-device helpers used by the app."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import (
    DEFAULT_VIRTUAL_MIC_CONFIG_FILE_NAME,
    DEFAULT_VIRTUAL_MIC_DESCRIPTION,
    DEFAULT_VIRTUAL_MIC_NODE_NAME,
)
from .platforms import pipewire_virtual_mic_supported


@dataclass(slots=True)
class PipeWireNode:
    """Describe a PipeWire audio node discovered through pw-dump."""

    node_id: int
    media_class: str
    name: str
    description: str
    nickname: str
    raw_properties: dict[str, Any]


# Usage: check whether a required PipeWire helper executable is available on PATH.
# Parameters: executable - the command name to look up.
# Return: True when the executable exists on PATH, otherwise False.
def command_exists(executable: str) -> bool:
    """Return whether an executable is available on the user's PATH."""

    return shutil.which(executable) is not None


# Usage: execute pw-dump and capture its JSON output for parsing.
# Parameters: none.
# Return: the parsed top-level JSON list produced by pw-dump, or an empty list on failure.
def read_pw_dump() -> list[dict[str, Any]]:
    """Run pw-dump and parse its JSON output (PipeWire/Linux only)."""

    if not pipewire_virtual_mic_supported():
        return []

    if not command_exists("pw-dump"):
        return []

    try:
        completed = subprocess.run(
            ["pw-dump"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return []

    if not isinstance(payload, list):
        return []

    return [item for item in payload if isinstance(item, dict)]


# Usage: convert pw-dump objects into a simplified list of audio source and sink nodes.
# Parameters: none.
# Return: a list of PipeWireNode values suitable for device metadata lookups.
def list_audio_nodes() -> list[PipeWireNode]:
    """Return a simplified list of audio nodes discovered via pw-dump."""

    nodes: list[PipeWireNode] = []
    for item in read_pw_dump():
        info = item.get("info") or {}
        props = info.get("props") or {}
        media_class = str(props.get("media.class", ""))
        if not media_class.startswith("Audio/"):
            continue

        node_id = int(item.get("id", -1))
        name = str(props.get("node.name", ""))
        description = str(props.get("node.description", ""))
        nickname = str(props.get("node.nick", ""))
        nodes.append(
            PipeWireNode(
                node_id=node_id,
                media_class=media_class,
                name=name,
                description=description,
                nickname=nickname,
                raw_properties=dict(props),
            )
        )

    return nodes


# Usage: build a lookup table that helps match Qt audio device descriptions to PipeWire nodes.
# Parameters: nodes - the list of PipeWireNode values that should be indexed.
# Return: a dictionary mapping lower-cased names and descriptions to PipeWireNode objects.
def build_node_lookup(nodes: list[PipeWireNode]) -> dict[str, PipeWireNode]:
    """Create a text lookup for best-effort matching between Qt and PipeWire devices."""

    lookup: dict[str, PipeWireNode] = {}
    for node in nodes:
        for candidate in {node.name, node.description, node.nickname}:
            if candidate:
                lookup[candidate.casefold()] = node

    return lookup


# Usage: normalize a user-facing PipeWire node name into a safe identifier that works in PipeWire config files.
# Parameters: node_name - the raw node name entered by the user.
# Return: a sanitized PipeWire node name containing only letters, digits, underscore, dash, or dot.
def sanitize_pipewire_node_name(node_name: str) -> str:
    """Return a PipeWire-safe node name with a stable fallback."""

    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(node_name).strip())
    normalized = normalized.strip("._-")
    return normalized or DEFAULT_VIRTUAL_MIC_NODE_NAME


# Usage: derive the managed PipeWire sink node name that should receive synthesized TTS audio for a virtual microphone.
# Parameters: node_name - the user-facing virtual microphone node name configured by the app.
# Return: the sanitized PipeWire sink node name created alongside the linked microphone source.
def build_virtual_microphone_sink_node_name(node_name: str) -> str:
    """Return the managed PipeWire sink node name paired with the configured virtual microphone source."""

    return f"{sanitize_pipewire_node_name(node_name)}_sink"


# Usage: locate the user-level PipeWire config file written by the virtual microphone helper.
# Parameters: none.
# Return: the path where the app should write its PipeWire virtual microphone configuration.
def get_virtual_microphone_config_path() -> Path:
    """Return the PipeWire config file path used for the managed virtual microphone."""

    return Path.home() / ".config" / "pipewire" / "pipewire.conf.d" / DEFAULT_VIRTUAL_MIC_CONFIG_FILE_NAME


# Usage: escape a user-provided string so it remains a single safe PipeWire config string value.
# Parameters: value - the raw text that should be embedded inside a quoted PipeWire config string.
# Return: a sanitized string with control whitespace flattened and quotes/backslashes escaped.
def escape_pipewire_string(value: str) -> str:
    """Return a PipeWire-safe string literal payload for user-provided text."""

    normalized = " ".join(str(value).split())
    return normalized.replace("\\", "\\\\").replace('"', '\\"')


# Usage: build a PipeWire loopback configuration that exposes an app-targetable sink and a microphone-like source carrying the same audio.
# Parameters: node_name - the PipeWire node name for the microphone-like source; description - the user-facing node description shown by PipeWire clients.
# Return: the full PipeWire configuration file content that creates the virtual microphone loopback pair.
def build_virtual_microphone_config(node_name: str, description: str) -> str:
    """Return the PipeWire config content for a managed sink-to-source virtual microphone pair."""

    safe_node_name = sanitize_pipewire_node_name(node_name)
    raw_description = str(description).strip() or DEFAULT_VIRTUAL_MIC_DESCRIPTION
    safe_description = escape_pipewire_string(raw_description)
    sink_node_name = build_virtual_microphone_sink_node_name(node_name)
    sink_description = escape_pipewire_string(f"{raw_description} Output")
    return (
        "context.modules = [\n"
        "  {\n"
        "    name = libpipewire-module-loopback\n"
        "    args = {\n"
        "      capture.props = {\n"
        f'        node.name = "{sink_node_name}"\n'
        f'        node.description = "{sink_description}"\n'
        '        media.class = Audio/Sink\n'
        '        audio.position = [ FL FR ]\n'
        "      }\n"
        "      playback.props = {\n"
        f'        node.name = "{safe_node_name}"\n'
        f'        node.description = "{safe_description}"\n'
        '        media.class = Audio/Source\n'
        '        audio.position = [ FL FR ]\n'
        "      }\n"
        "    }\n"
        "  }\n"
        "]\n"
    )


# Usage: write the managed PipeWire virtual microphone config into the user's pipewire.conf.d directory.
# Parameters: node_name - the requested PipeWire node name; description - the requested human-readable description.
# Return: the filesystem path that was written so the caller can report it back to the user.
# Raises: RuntimeError when the current platform does not support PipeWire virtual devices.
def install_virtual_microphone_config(node_name: str, description: str) -> Path:
    """Write the managed PipeWire virtual microphone configuration file and return its path."""

    if not pipewire_virtual_mic_supported():
        raise RuntimeError(
            "The managed virtual microphone requires PipeWire and is only available on Linux. "
            "On this platform, route TTS to a normal speaker or headphone output instead."
        )

    config_path = get_virtual_microphone_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        build_virtual_microphone_config(node_name=node_name, description=description),
        encoding="utf-8",
    )
    return config_path
