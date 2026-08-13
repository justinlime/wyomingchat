"""Tests for virtual audio cable detection and selection helpers."""

from __future__ import annotations

from wyomingchat.virtual_cable import (
    cable_mic_name_for_output,
    classify_cable_output,
    detect_cable_outputs,
    is_available_cable_output_id,
    output_device_pairs,
    select_cable_output_id,
)


# Usage: verify that known VB-CABLE playback endpoints are recognized.
# Parameters: none.
# Return: None.
def test_classify_vb_cable_output() -> None:
    """Ensure VB-CABLE playback endpoints are detected by name."""

    assert classify_cable_output("CABLE Input (VB-Audio Virtual Cable)") == "VB-CABLE"
    # An unnamed cable-shaped endpoint still counts as a generic virtual cable.
    assert classify_cable_output("CABLE Input") == "Virtual cable"


# Usage: verify that Voicemeeter playback endpoints are recognized.
# Parameters: none.
# Return: None.
def test_classify_voicemeeter_output() -> None:
    """Ensure Voicemeeter playback endpoints are detected."""

    assert classify_cable_output("VoiceMeeter Input (VB-Audio VoiceMeeter VAIO)") == "Voicemeeter"


# Usage: verify that ordinary speaker outputs are never classified as cables.
# Parameters: none.
# Return: None.
def test_classify_regular_output_is_not_a_cable() -> None:
    """Ensure normal speaker and headphone outputs are not mistaken for cables."""

    assert classify_cable_output("Speakers (Realtek High Definition Audio)") is None
    assert classify_cable_output("") is None


# Usage: verify that the paired microphone endpoint name is derived from the playback endpoint.
# Parameters: none.
# Return: None.
def test_cable_mic_name_derivation() -> None:
    """Ensure the paired microphone display name is derived predictably."""

    assert (
        cable_mic_name_for_output("CABLE Input (VB-Audio Virtual Cable)")
        == "CABLE Output (VB-Audio Virtual Cable)"
    )
    assert cable_mic_name_for_output("VoiceMeeter Input") == "VoiceMeeter Output"


# Usage: verify that a persisted explicit selection wins over auto-detection.
# Parameters: none.
# Return: None.
def test_select_cable_output_id_prefers_configured_device() -> None:
    """Ensure a persisted cable id that is still available wins the selection."""

    outputs = [
        ("speaker-1", "Speakers (Realtek)"),
        ("cable-1", "CABLE Input (VB-Audio Virtual Cable)"),
    ]
    assert select_cable_output_id("cable-1", outputs) == "cable-1"


# Usage: verify that auto-detection picks the first known cable when nothing is configured.
# Parameters: none.
# Return: None.
def test_select_cable_output_id_auto_detects_first_cable() -> None:
    """Ensure a known cable is auto-selected when no explicit id is persisted."""

    outputs = [
        ("speaker-1", "Speakers (Realtek)"),
        ("cable-1", "CABLE Input (VB-Audio Virtual Cable)"),
        ("voicemeeter-1", "VoiceMeeter Input (VB-Audio VoiceMeeter VAIO)"),
    ]
    assert select_cable_output_id(None, outputs) == "cable-1"


# Usage: verify that a stale configured id falls back to auto-detection.
# Parameters: none.
# Return: None.
def test_select_cable_output_id_falls_back_when_configured_id_missing() -> None:
    """Ensure auto-detection still applies when the persisted device disappeared."""

    outputs = [("speaker-1", "Speakers (Realtek)"), ("cable-1", "CABLE Input (VB-Audio Virtual Cable)")]
    assert select_cable_output_id("stale-cable-id", outputs) == "cable-1"


# Usage: verify that no cable yields no routing target.
# Parameters: none.
# Return: None.
def test_select_cable_output_id_returns_none_without_cable() -> None:
    """Ensure the routing target is None when no cable is installed."""

    outputs = [("speaker-1", "Speakers (Realtek)")]
    assert select_cable_output_id(None, outputs) is None
    assert select_cable_output_id("stale-id", outputs) is None


# Usage: verify that detected cables are reported with their family label.
# Parameters: none.
# Return: None.
def test_detect_cable_outputs_lists_known_cables_only() -> None:
    """Ensure detect_cable_outputs returns only recognized cable endpoints."""

    outputs = [
        ("speaker-1", "Speakers (Realtek)"),
        ("cable-1", "CABLE Input (VB-Audio Virtual Cable)"),
    ]
    assert detect_cable_outputs(outputs) == [("cable-1", "CABLE Input (VB-Audio Virtual Cable)", "VB-CABLE")]


# Usage: verify that the availability check only accepts current device ids.
# Parameters: none.
# Return: None.
def test_is_available_cable_output_id_matches_only_current_devices() -> None:
    """Ensure the persisted id availability check is exact."""

    outputs = [("cable-1", "CABLE Input (VB-Audio Virtual Cable)")]
    assert is_available_cable_output_id("cable-1", outputs) is True
    assert is_available_cable_output_id("stale-id", outputs) is False
    assert is_available_cable_output_id(None, outputs) is False


# Usage: verify that descriptor adaptation preserves ids and names.
# Parameters: none.
# Return: None.
def test_output_device_pairs_adapts_descriptors() -> None:
    """Ensure catalog descriptors convert to plain (id, name) pairs."""

    class FakeDescriptor:
        def __init__(self, device_id: str, name: str) -> None:
            self.id = device_id
            self.name = name

    descriptors = [FakeDescriptor("cable-1", "CABLE Input (VB-Audio Virtual Cable)")]
    assert output_device_pairs(descriptors) == [("cable-1", "CABLE Input (VB-Audio Virtual Cable)")]
