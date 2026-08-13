# PyInstaller spec for building the Wyoming Voice Bridge desktop executable.
#
# Build with:
#   uv run --extra packaging pyinstaller --noconfirm packaging/wyomingchat.spec
#
# The onedir layout (EXE + adjacent folder) is used instead of onefile because
# Qt Multimedia relies on runtime-discovered plugins; onedir is the reliable
# layout for Qt applications.
#
# Output:
#   dist/WyomingVoiceBridge/WyomingVoiceBridge.exe   (Windows, no console window)
#   dist/WyomingVoiceBridge/wyoming-voice-bridge     (Linux binary)

from __future__ import annotations

import os
import sys as _sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

# Root of the repository (the directory that contains this spec file).
spec_dir = Path(SPECPATH)
project_root = spec_dir.parent

# PySide6 ships its Qt runtime plugins (platform, multimedia, etc.) inside the
# installed wheel. The first-party PySide6 hooks normally collect these, but in
# some build environments (and to be defensive against hook behavior changes)
# they can be missed - and without the platform plugin the app cannot start.
# Walk the plugin directory explicitly and bundle the needed plugin types as
# binaries. Debug variants (name ending in ``d.dll`` on Windows) are skipped.
def _collect_qt_plugins(qt_root: Path, dest_prefix: str) -> list[tuple[str, str]]:
    plugin_root = qt_root / "plugins"
    suffixes = (".dll", ".so", ".dylib")
    wanted_plugin_types = {
        "platforms",  # qwindows.dll / libqxcb.so - required for the app to start
        "multimedia",  # audio capture/playback backends
        "imageformats",
        "iconengines",
        "styles",
        "platforminputcontexts",
        "networkinformation",
    }
    entries: list[tuple[str, str]] = []
    for plugin_type in sorted(wanted_plugin_types):
        plugin_dir = plugin_root / plugin_type
        if not plugin_dir.is_dir():
            continue
        for entry in sorted(os.listdir(plugin_dir)):
            if not entry.endswith(suffixes):
                continue
            if entry.endswith("d.dll"):  # skip Windows debug plugin variants
                continue
            entries.append(
                (str(plugin_dir / entry), f"{dest_prefix}/plugins/{plugin_type}")
            )
    return entries


# pysilero-vad embeds its ggml Silero model (ggml-silero-*.bin) as package
# data with no PyInstaller hook of its own. Without this, the packaged EXE
# fails at runtime with a missing model file.
datas = collect_data_files("pysilero_vad")
binaries = collect_dynamic_libs("pysilero_vad")

# Qt plugins are located under the installed PySide6 package's Qt directory.
import PySide6  # noqa: E402

_pyside6_root = Path(os.path.dirname(PySide6.__file__))
_qt_root = _pyside6_root / "Qt"
# The PySide6 runtime hook maps QT_PLUGIN_PATH to <bundle>/PySide6/plugins on
# Windows and <bundle>/PySide6/Qt/plugins everywhere else.
_dest_prefix = "PySide6" if _sys.platform == "win32" else "PySide6/Qt"
binaries += _collect_qt_plugins(_qt_root, _dest_prefix)

icon_path = project_root / "resources" / "wyomingchat.ico"
if not icon_path.exists():
    # ImageMagick may be unavailable; fall back to the PNG for Linux builds.
    icon_path = project_root / "resources" / "wyomingchat_256.png"
if not icon_path.exists():
    icon_path = None

# PySide6 ships first-party PyInstaller hooks (bundled with PyInstaller) that
# pull in the Qt libraries and the Qt Multimedia backend plugins. Importing
# the Qt modules from the entry script makes those hooks fire automatically.
hiddenimports = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtMultimedia",
]

a = Analysis(
    [str(spec_dir / "launcher.py")],
    pathex=[str(project_root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Qt modules that the app never uses keep the bundle much smaller.
        "PySide6.QtBluetooth",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtGraphs",
        "PySide6.QtLocation",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtNetworkAuth",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtPositioning",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuick3D",
        "PySide6.QtRemoteObjects",
        "PySide6.QtSensors",
        "PySide6.QtSerialPort",
        "PySide6.QtSql",
        "PySide6.QtStateMachine",
        "PySide6.QtTest",
        "PySide6.QtWebChannel",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebSockets",
        "PySide6.QtXml",
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WyomingVoiceBridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path) if icon_path is not None else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="WyomingVoiceBridge",
)
