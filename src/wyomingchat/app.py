"""Qt application bootstrap for Wyoming Voice Bridge."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .audio import AudioCaptureStream, AudioDeviceCatalog, MultiOutputPlayer
from .constants import APP_ID, APP_NAME
from .controller import BridgeController
from .shortcuts import GlobalShortcutPortal
from .storage import JsonConfigStore
from .ui import MainWindow


# Usage: create or reuse the global QApplication instance and apply app metadata used by desktop integration.
# Parameters: argv - the process argument list that should be passed to QApplication when creating a new instance.
# Return: the active QApplication instance.
def create_qt_application(argv: list[str]) -> QApplication:
    """Create or reuse the QApplication instance and configure desktop metadata."""

    application = QApplication.instance()
    if application is None:
        application = QApplication(argv)

    application.setApplicationName(APP_NAME)
    application.setDesktopFileName(APP_ID)
    application.setOrganizationDomain("github.io")
    application.setOrganizationName("Wyoming Voice Bridge")
    return application


# Usage: create the fully wired controller and all of its supporting services.
# Parameters: none.
# Return: a tuple containing the controller, audio catalog, and main window.
def build_application_components() -> tuple[BridgeController, AudioDeviceCatalog, MainWindow]:
    """Create the controller, service objects, and main window for the app."""

    store = JsonConfigStore()
    catalog = AudioDeviceCatalog()
    capture = AudioCaptureStream(catalog)
    player = MultiOutputPlayer(catalog)
    shortcut_portal = GlobalShortcutPortal()
    controller = BridgeController(
        store=store,
        catalog=catalog,
        capture=capture,
        player=player,
        shortcut_portal=shortcut_portal,
    )
    window = MainWindow(controller=controller, catalog=catalog)
    return controller, catalog, window


# Usage: bootstrap the full desktop application, show the main window, and enter the Qt event loop.
# Parameters: argv - optional process arguments, defaulting to sys.argv.
# Return: the integer process exit code from QApplication.exec().
def run(argv: list[str] | None = None) -> int:
    """Bootstrap and run the Wyoming Voice Bridge desktop application."""

    argv = argv or sys.argv
    application = create_qt_application(argv)
    controller, _catalog, window = build_application_components()
    controller.load_configuration()
    window.show()
    controller.register_shortcut_from_config()
    return application.exec()
