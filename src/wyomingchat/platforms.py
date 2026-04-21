"""Platform detection helpers shared across the Wyoming Voice Bridge codebase."""

from __future__ import annotations

import sys


# Usage: report whether the process is running on Windows.
# Parameters: none.
# Return: True when the host platform is Windows, otherwise False.
def is_windows() -> bool:
    """Return whether the current platform is Windows."""

    return sys.platform == "win32"


# Usage: report whether the process is running on Linux.
# Parameters: none.
# Return: True when the host platform is Linux, otherwise False.
def is_linux() -> bool:
    """Return whether the current platform is Linux."""

    return sys.platform.startswith("linux")


# Usage: report whether the process is running on macOS.
# Parameters: none.
# Return: True when the host platform is macOS, otherwise False.
def is_macos() -> bool:
    """Return whether the current platform is macOS."""

    return sys.platform == "darwin"


# Usage: report whether the managed PipeWire virtual microphone feature is available.
# Parameters: none.
# Return: True only on Linux where PipeWire can create the loopback sink/source pair.
def pipewire_virtual_mic_supported() -> bool:
    """Return whether the managed virtual microphone feature is available.

    The feature depends on PipeWire and is only available on Linux. Other
    platforms do not expose a programmatic way to create a loopback
    sink/source pair without third-party drivers, so the feature is
    intentionally disabled there while remaining fully functional on Linux.
    """

    return is_linux()


# Usage: determine which virtual-microphone strategy applies on the current platform.
# Parameters: none.
# Return: "pipewire" on Linux, "cable" on Windows, or None where no strategy applies.
def virtual_mic_mode() -> str | None:
    """Return the virtual-microphone strategy for the current platform.

    Linux uses PipeWire loopback devices managed directly by the app.
    Windows cannot create audio devices programmatically, so the app routes
    TTS into a user-installed virtual audio cable (VB-CABLE or Voicemeeter,
    both free donationware) whose paired microphone endpoint other
    applications can select.
    """

    if is_linux():
        return "pipewire"
    if is_windows():
        return "cable"
    return None


# Usage: produce a short human-readable platform name for status messages.
# Parameters: none.
# Return: a string such as "Windows", "macOS", or "Linux".
def platform_label() -> str:
    """Return a short human-readable name for the current platform."""

    if is_windows():
        return "Windows"
    if is_macos():
        return "macOS"
    if is_linux():
        return "Linux"
    return sys.platform
