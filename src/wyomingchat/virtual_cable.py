"""Virtual audio cable detection and selection helpers for Windows.

Windows cannot create virtual audio devices programmatically (that requires a
signed kernel driver), but the app can route its TTS output into a
user-installed virtual audio cable. Other applications then select the cable's
microphone endpoint as their input, which reproduces the PipeWire virtual
microphone workflow without PipeWire.

Supported cable families are identified by well-known device-name patterns
(VB-CABLE and Voicemeeter) with a generic fallback so unrecognized virtual
cables can still be selected manually.
"""

from __future__ import annotations

from typing import Iterable, Protocol


class NamedOutput(Protocol):
    """Describe the minimal output-device surface used by cable selection."""

    id: str
    name: str


# Known playback-endpoint name fragments that identify virtual audio cables.
# Each entry maps a human-readable cable family to substrings matched against
# the playback device name (case-insensitive). More specific entries first.
#
# Both VB-CABLE and Voicemeeter are free donationware from VB-Audio; there is
# no maintained open-source local virtual audio cable for Windows today (the
# open-source "Scream" project is a network sound card, not a local cable).
CABLE_OUTPUT_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("VB-CABLE", ("cable input", "vb-audio")),
    ("Voicemeeter", ("voicemeeter input",)),
    # Generic fallback for other virtual cables that do not match a known brand.
    ("Virtual cable", ("virtual cable",)),
    ("Virtual cable", ("cable", "input")),
]


# Usage: identify which virtual audio cable family a playback device belongs to.
# Parameters: name - the playback device name reported by Qt.
# Return: the cable family label when the name matches a known pattern, otherwise None.
def classify_cable_output(name: str) -> str | None:
    """Return the cable family for a playback device name, or None when unknown."""

    normalized_name = str(name).strip().casefold()
    if not normalized_name:
        return None

    for family, fragments in CABLE_OUTPUT_PATTERNS:
        if all(fragment in normalized_name for fragment in fragments):
            return family

    return None


# Usage: derive the likely paired microphone endpoint name for a cable playback device.
# Parameters: name - the playback device name; family - the cable family from classify_cable_output.
# Return: the best-effort microphone endpoint name shown in the UI.
def cable_mic_name_for_output(name: str, family: str | None = None) -> str:
    """Return the likely paired microphone endpoint name for a cable output.

    Most cables pair "Input" (playback) with "Output" (microphone). This is
    best-effort and only used for UI display - the microphone endpoint itself
    is consumed by other applications, never opened by this app.
    """

    raw_name = str(name).strip()
    if not raw_name:
        return ""

    del family
    if "input" in raw_name.casefold():
        return raw_name.replace("Input", "Output").replace("input", "output")

    return raw_name


# Usage: choose the playback device id that TTS audio should be routed into as a virtual microphone.
# Parameters: configured_id - optional persisted cable output id selected by the user; outputs - available (device id, device name) pairs.
# Return: the output id to route TTS into, or None when no cable can be found.
def select_cable_output_id(
    configured_id: str | None,
    outputs: Iterable[tuple[str, str]],
) -> str | None:
    """Resolve the TTS routing target for the virtual microphone cable.

    A persisted explicit selection wins when the device is still available;
    otherwise the first detected known cable output is used so the feature
    works automatically right after a cable driver is installed.
    """

    available_outputs = [(str(device_id).strip(), str(name)) for device_id, name in outputs if str(device_id).strip()]

    normalized_configured_id = str(configured_id).strip() if configured_id else ""
    if normalized_configured_id:
        for device_id, _name in available_outputs:
            if device_id == normalized_configured_id:
                return device_id

    for device_id, name in available_outputs:
        if classify_cable_output(name) is not None:
            return device_id

    return None


# Usage: list known virtual audio cable playback endpoints among available outputs.
# Parameters: outputs - available (device id, device name) pairs.
# Return: a list of (device id, device name, cable family) tuples for detected cables.
def detect_cable_outputs(outputs: Iterable[tuple[str, str]]) -> list[tuple[str, str, str]]:
    """Return detected virtual cable playback endpoints with their cable family."""

    detected: list[tuple[str, str, str]] = []
    for device_id, name in outputs:
        family = classify_cable_output(name)
        if family is not None:
            detected.append((str(device_id).strip(), str(name), family))
    return detected


# Usage: verify a persisted cable device id is still present among available outputs.
# Parameters: configured_id - the persisted cable output id; outputs - available (device id, device name) pairs.
# Return: True when the id matches an available output, otherwise False.
def is_available_cable_output_id(configured_id: str | None, outputs: Iterable[tuple[str, str]]) -> bool:
    """Return whether the persisted cable output id is currently available."""

    normalized_configured_id = str(configured_id).strip() if configured_id else ""
    if not normalized_configured_id:
        return False

    return any(str(device_id).strip() == normalized_configured_id for device_id, _name in outputs)


# Usage: adapt catalog output descriptors into the (id, name) tuples used by cable helpers.
# Parameters: descriptors - AudioDeviceDescriptor values from the audio catalog.
# Return: a list of (id, name) tuples.
def output_device_pairs(descriptors: Iterable[NamedOutput]) -> list[tuple[str, str]]:
    """Convert catalog device descriptors into simple (id, name) pairs."""

    return [(str(descriptor.id), str(descriptor.name)) for descriptor in descriptors]
