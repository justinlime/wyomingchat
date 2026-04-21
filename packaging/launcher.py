"""Standalone PyInstaller entry point for Wyoming Voice Bridge.

The package's ``wyomingchat.__main__`` module relies on relative imports and
therefore cannot be executed as a standalone script. PyInstaller analyzes this
wrapper instead, which uses an absolute import so the whole ``wyomingchat``
package (and its dependencies such as pysilero-vad) is discovered.
"""

from __future__ import annotations

from wyomingchat.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
