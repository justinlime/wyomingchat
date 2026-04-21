"""Command-line entry point for launching the Wyoming Voice Bridge desktop app."""

from __future__ import annotations

from .app import run


# Usage: provide the console-script entry point used by uv and installed package launchers.
# Parameters: none.
# Return: the integer exit code produced by the Qt application.
def main() -> int:
    """Run the desktop application and return its exit code."""

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
