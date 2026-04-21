"""Disk persistence for Wyoming Voice Bridge configuration."""

from __future__ import annotations

import json
from pathlib import Path

from .config import AppConfig, build_default_config
from .paths import ensure_app_directories, get_config_file_path


class JsonConfigStore:
    """Load and save the application configuration from the user's XDG config directory."""

    # Usage: create a configuration store with an optional custom file path for tests or alternate profiles.
    # Parameters: config_path - optional explicit path to the JSON config file.
    # Return: None.
    def __init__(self, config_path: Path | None = None) -> None:
        """Initialize the JSON config store."""

        self._config_path = config_path or get_config_file_path()

    @property
    # Usage: expose the backing config file path for diagnostics or UI messages.
    # Parameters: none.
    # Return: the Path used by this store for reading and writing configuration.
    def config_path(self) -> Path:
        """Return the filesystem path used by the config store."""

        return self._config_path

    # Usage: load configuration from disk while tolerating a missing or invalid file.
    # Parameters: none.
    # Return: an AppConfig loaded from disk or a default config when no valid file exists.
    def load(self) -> AppConfig:
        """Read configuration from disk, falling back to defaults on failure."""

        ensure_app_directories()
        if not self._config_path.exists():
            return build_default_config()

        try:
            payload = json.loads(self._config_path.read_text(encoding="utf-8"))
            return AppConfig.from_dict(payload)
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            return build_default_config()

    # Usage: write the provided configuration to disk in a stable JSON format.
    # Parameters: config - the AppConfig object that should be persisted.
    # Return: the Path that was written for convenience and confirmation.
    def save(self, config: AppConfig) -> Path:
        """Persist configuration to disk and return the written file path."""

        ensure_app_directories()
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(config.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return self._config_path
