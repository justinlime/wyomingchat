"""Tests for PipeWire helpers on platforms where PipeWire is unavailable."""

from __future__ import annotations

import sys

import pytest

from wyomingchat.pipewire import install_virtual_microphone_config, read_pw_dump


# Usage: verify that pw-dump inspection is skipped entirely on non-Linux platforms.
# Parameters: monkeypatch - pytest fixture for patching the detected platform.
# Return: None.
def test_read_pw_dump_returns_empty_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure pw-dump is never executed on platforms without PipeWire."""

    monkeypatch.setattr(sys, "platform", "win32")

    assert read_pw_dump() == []


# Usage: verify that installing the virtual microphone config fails cleanly on Windows.
# Parameters: monkeypatch - pytest fixture for patching the detected platform.
# Return: None.
def test_install_virtual_microphone_config_raises_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure the managed virtual microphone cannot be installed off-Linux."""

    monkeypatch.setattr(sys, "platform", "win32")

    with pytest.raises(RuntimeError, match="only available on Linux"):
        install_virtual_microphone_config("bridge-mic", "Bridge Mic")
