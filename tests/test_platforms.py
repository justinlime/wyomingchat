"""Tests for platform detection and cross-platform path resolution."""

from __future__ import annotations

import sys

import pytest

from wyomingchat import paths
from wyomingchat.platforms import (
    is_linux,
    pipewire_virtual_mic_supported,
    platform_label,
)


# Usage: verify that the platform-label helper always returns a non-empty string.
# Parameters: none.
# Return: None.
def test_platform_label_returns_readable_name() -> None:
    """Ensure the platform label helper always produces a usable string."""

    assert isinstance(platform_label(), str)
    assert platform_label().strip()


# Usage: verify that the virtual-microphone capability flag only enables on Linux.
# Parameters: monkeypatch - pytest fixture for patching the detected platform.
# Return: None.
def test_pipewire_virtual_mic_only_supported_on_linux(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure the PipeWire virtual microphone feature is gated to Linux."""

    assert pipewire_virtual_mic_supported() is is_linux()
    monkeypatch.setattr(sys, "platform", "win32")
    assert pipewire_virtual_mic_supported() is False


# Usage: verify that XDG_CONFIG_HOME is honored before any platform fallback.
# Parameters: monkeypatch - pytest fixture for patching environment and platform.
# Return: None.
def test_config_home_honors_xdg_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure an explicit XDG_CONFIG_HOME wins on every platform."""

    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/xdg-config")
    assert paths.get_config_home() == paths.Path("/tmp/xdg-config")


# Usage: verify that XDG_STATE_HOME is honored before any platform fallback.
# Parameters: monkeypatch - pytest fixture for patching environment and platform.
# Return: None.
def test_state_home_honors_xdg_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure an explicit XDG_STATE_HOME wins on every platform."""

    monkeypatch.setenv("XDG_STATE_HOME", "/tmp/xdg-state")
    assert paths.get_state_home() == paths.Path("/tmp/xdg-state")


# Usage: verify that Windows uses the roaming AppData directory for configuration.
# Parameters: monkeypatch - pytest fixture for patching environment and platform.
# Return: None.
def test_config_home_uses_appdata_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure Windows configuration lands in the roaming %APPDATA% directory."""

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("APPDATA", r"C:\\Users\\alice\\AppData\\Roaming")

    assert paths.get_config_home() == paths.Path(r"C:\\Users\\alice\\AppData\\Roaming")


# Usage: verify that Windows uses the local AppData directory for state and logs.
# Parameters: monkeypatch - pytest fixture for patching environment and platform.
# Return: None.
def test_state_home_uses_local_appdata_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure Windows state and logs land in the local %LOCALAPPDATA% directory."""

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\\Users\\alice\\AppData\\Local")

    assert paths.get_state_home() == paths.Path(r"C:\\Users\\alice\\AppData\\Local")


# Usage: verify that Windows falls back to a home-directory AppData path when APPDATA is unset.
# Parameters: monkeypatch - pytest fixture for patching environment and platform.
# Return: None.
def test_config_home_falls_back_when_appdata_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure Windows config resolution still works without the APPDATA variable."""

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)

    assert paths.get_config_home() == paths.Path.home() / "AppData" / "Roaming"


# Usage: verify that the app config file path is derived from the config home on any platform.
# Parameters: monkeypatch - pytest fixture for patching environment and platform.
# Return: None.
def test_config_file_path_derives_from_platform_config_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure get_config_file_path follows the resolved config directory."""

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("APPDATA", r"C:\\Users\\alice\\AppData\\Roaming")

    expected = paths.Path(r"C:\\Users\\alice\\AppData\\Roaming") / "wyoming-voice-bridge" / "config.json"
    assert paths.get_config_file_path() == expected
