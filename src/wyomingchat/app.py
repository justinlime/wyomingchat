"""Qt application bootstrap for Wyoming Voice Bridge."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .audio import AudioCaptureStream, AudioDeviceCatalog, MultiOutputPlayer
from .constants import APP_NAME
from .controller import BridgeController
from .paths import ensure_app_directories, get_log_file_path
from .storage import JsonConfigStore
from .ui import MainWindow

LOGGER = logging.getLogger(__name__)


# Usage: configure file-based application logging before any long-lived controller or audio objects start emitting diagnostic messages.
# Parameters: none.
# Return: the Path to the log file receiving application log records.
def configure_application_logging() -> Path:
    """Initialize application logging and return the active log file path."""

    ensure_app_directories()
    log_path = get_log_file_path()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8")],
        force=True,
    )
    LOGGER.info("Application logging initialized at %s", log_path)
    return log_path


# Usage: create or reuse the global QApplication instance and apply app metadata used by desktop integration.
# Parameters: argv - the process argument list that should be passed to QApplication when creating a new instance.
# Return: the active QApplication instance.
def create_qt_application(argv: list[str]) -> QApplication:
    """Create or reuse the QApplication instance and configure desktop metadata."""

    application = QApplication.instance()
    if application is None:
        application = QApplication(argv)

    application.setApplicationName(APP_NAME)
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
    controller = BridgeController(
        store=store,
        catalog=catalog,
        capture=capture,
        player=player,
    )
    window = MainWindow(controller=controller, catalog=catalog)
    return controller, catalog, window


# Usage: bootstrap the full desktop application, show the main window, and enter the Qt event loop.
# Parameters: argv - optional process arguments, defaulting to sys.argv.
# Return: the integer process exit code from QApplication.exec().
def run(argv: list[str] | None = None) -> int:
    """Bootstrap and run the Wyoming Voice Bridge desktop application."""

    argv = argv or sys.argv
    configure_application_logging()
    application = create_qt_application(argv)
    controller, _catalog, window = build_application_components()
    controller.load_configuration()
    window.show()
    return application.exec()
