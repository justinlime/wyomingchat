"""Helpers for locating XDG configuration and state paths for the application."""

from __future__ import annotations

import os
from pathlib import Path

from .constants import CONFIG_DIR_NAME, CONFIG_FILE_NAME, LOG_FILE_NAME


# Usage: resolve the base XDG config directory for the current user.
# Parameters: none.
# Return: a Path pointing at the directory that should contain app configuration.
def get_config_home() -> Path:
    """Return the user's XDG config home directory."""

    configured_path = os.environ.get("XDG_CONFIG_HOME")
    if configured_path:
        return Path(configured_path)

    return Path.home() / ".config"


# Usage: resolve the base XDG state directory for the current user.
# Parameters: none.
# Return: a Path pointing at the directory that should contain app state and logs.
def get_state_home() -> Path:
    """Return the user's XDG state home directory."""

    configured_path = os.environ.get("XDG_STATE_HOME")
    if configured_path:
        return Path(configured_path)

    return Path.home() / ".local" / "state"


# Usage: resolve the application-specific configuration directory.
# Parameters: none.
# Return: a Path pointing at the Wyoming Voice Bridge config directory.
def get_app_config_dir() -> Path:
    """Return the directory that stores persistent application configuration."""

    return get_config_home() / CONFIG_DIR_NAME


# Usage: resolve the application-specific state directory.
# Parameters: none.
# Return: a Path pointing at the Wyoming Voice Bridge state directory.
def get_app_state_dir() -> Path:
    """Return the directory that stores logs and transient application state."""

    return get_state_home() / CONFIG_DIR_NAME


# Usage: resolve the JSON configuration file path used by the app.
# Parameters: none.
# Return: a Path pointing at the persistent config file.
def get_config_file_path() -> Path:
    """Return the full path to the configuration JSON file."""

    return get_app_config_dir() / CONFIG_FILE_NAME


# Usage: resolve the default log file path used by the app.
# Parameters: none.
# Return: a Path pointing at the app log file.
def get_log_file_path() -> Path:
    """Return the full path to the application log file."""

    return get_app_state_dir() / LOG_FILE_NAME


# Usage: create the app's XDG config and state directories before reading or writing files.
# Parameters: none.
# Return: a tuple containing the created config directory and state directory Paths.
def ensure_app_directories() -> tuple[Path, Path]:
    """Create and return the application's config and state directories."""

    config_dir = get_app_config_dir()
    state_dir = get_app_state_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    return config_dir, state_dir
