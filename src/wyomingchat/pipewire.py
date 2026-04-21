"""Optional PipeWire inspection helpers used to enrich audio device discovery."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any


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
    """Run pw-dump and parse its JSON output."""

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
        if media_class not in {"Audio/Source", "Audio/Sink"}:
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
