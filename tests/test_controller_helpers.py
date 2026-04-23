"""Tests for small pure controller helpers that do not require a running Qt event loop."""

from __future__ import annotations

from wyomingchat.routing import build_tts_output_device_ids, choose_available_output_device_ids


# Usage: verify that virtual microphone routing appends the managed sink to user-selected speaker outputs without duplicating ids.
# Parameters: none.
# Return: None.
def test_build_tts_output_device_ids_appends_virtual_microphone_sink_once() -> None:
    """Ensure the managed virtual microphone sink is added exactly once after user-selected outputs."""

    output_ids = build_tts_output_device_ids(["speaker-1", "speaker-2", "speaker-1"], "virtual-mic-sink")

    assert output_ids == ["speaker-1", "speaker-2", "virtual-mic-sink"]


# Usage: verify that no blank or missing output identifiers leak into the final playback target list.
# Parameters: none.
# Return: None.
def test_build_tts_output_device_ids_ignores_blank_entries() -> None:
    """Ensure empty output identifiers are discarded when building playback routing targets."""

    output_ids = build_tts_output_device_ids(["", "speaker-1", "   "], None)

    assert output_ids == ["speaker-1"]


# Usage: verify that explicit playback targets never fall back to an unrelated default output when those targets are unavailable.
# Parameters: none.
# Return: None.
def test_choose_available_output_device_ids_returns_no_default_for_missing_explicit_targets() -> None:
    """Ensure stale or unavailable explicit output ids do not leak audio to the default speaker."""

    output_ids = choose_available_output_device_ids(
        requested_output_ids=["missing-speaker"],
        available_output_ids=["default-speaker", "virtual-mic-sink"],
        default_output_id="default-speaker",
    )

    assert output_ids == []


# Usage: verify that default playback fallback still works when the user has not selected any explicit outputs.
# Parameters: none.
# Return: None.
def test_choose_available_output_device_ids_uses_default_when_no_explicit_outputs_are_requested() -> None:
    """Ensure the system default output is still used only when the user has not requested explicit targets."""

    output_ids = choose_available_output_device_ids(
        requested_output_ids=[],
        available_output_ids=["default-speaker", "virtual-mic-sink"],
        default_output_id="default-speaker",
    )

    assert output_ids == ["default-speaker"]
