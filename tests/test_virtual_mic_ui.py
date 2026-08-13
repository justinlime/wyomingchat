"""Smoke tests for the virtual microphone UI in both platform modes."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from wyomingchat import ui as ui_module
from wyomingchat import controller as controller_module
from wyomingchat.audio import AudioCaptureStream, AudioDeviceCatalog, MultiOutputPlayer
from wyomingchat.controller import BridgeController
from wyomingchat.storage import JsonConfigStore


@pytest.fixture(scope="module")
def qapp():
    """Provide a shared QApplication instance for widget smoke tests."""

    application = QtWidgets.QApplication.instance()
    if application is None:
        application = QtWidgets.QApplication([])
    yield application


def build_window(tmp_path) -> tuple[BridgeController, object]:
    """Create a fully wired controller and main window for smoke testing."""

    store = JsonConfigStore(config_path=tmp_path / "config.json")
    catalog = AudioDeviceCatalog()
    capture = AudioCaptureStream(catalog)
    player = MultiOutputPlayer(catalog)
    controller = BridgeController(store=store, catalog=catalog, capture=capture, player=player)
    window = ui_module.MainWindow(controller=controller, catalog=catalog)
    return controller, window


# Usage: verify the Linux/PipeWire virtual microphone form still builds and round-trips config.
# Parameters: tmp_path - pytest fixture providing a temp directory; qapp - module-level Qt app fixture.
# Return: None.
def test_pipewire_virtual_mic_form_builds_and_round_trips(tmp_path, qapp) -> None:
    """Ensure the PipeWire form constructs and collects configuration values."""

    controller, window = build_window(tmp_path)
    controller.load_configuration()
    window.load_from_config(controller.config)

    config = window.collect_config_from_form()
    assert config.virtual_microphone.enabled is False
    assert config.virtual_microphone.node_name == "wyoming_voice_bridge_mic"
    assert config.virtual_microphone.cable_device_id is None

    window.close()


# Usage: verify the Windows virtual audio cable form builds and round-trips cable_device_id.
# Parameters: tmp_path - pytest fixture providing a temp directory; qapp - module-level Qt app fixture.
# Return: None.
def test_cable_virtual_mic_form_builds_and_round_trips(tmp_path, qapp, monkeypatch) -> None:
    """Ensure the Windows cable form constructs and collects the selected cable id."""

    monkeypatch.setattr(ui_module, "virtual_mic_mode", lambda: "cable")

    controller, window = build_window(tmp_path)
    controller.load_configuration()
    window.load_from_config(controller.config)

    # No real cable exists in the test environment, so the combo contains at
    # most manual fallback entries; auto-detect must be the default selection.
    assert window._virtual_cable_combo.currentData() is None

    config = window.collect_config_from_form()
    assert config.virtual_microphone.cable_device_id is None

    # Selecting a manual fallback entry persists its device id.
    manual_index = window._virtual_cable_combo.findText("(manual selection)")
    if manual_index >= 0:
        window._virtual_cable_combo.setCurrentIndex(manual_index)
        config = window.collect_config_from_form()
        assert config.virtual_microphone.cable_device_id is not None

    window.close()


# Usage: verify that enabling the cable feature without an installed cable surfaces a helpful hint.
# Parameters: tmp_path - pytest fixture providing a temp directory; qapp - module-level Qt app fixture.
# Return: None.
def test_cable_enabled_without_cable_emits_hint(tmp_path, qapp, monkeypatch) -> None:
    """Ensure the user is told how to get a cable when the feature cannot resolve one."""

    monkeypatch.setattr(ui_module, "virtual_mic_mode", lambda: "cable")
    monkeypatch.setattr(controller_module, "virtual_mic_mode", lambda: "cable")

    controller, window = build_window(tmp_path)
    controller.load_configuration()
    window.load_from_config(controller.config)

    status_messages: list[str] = []
    controller.status_changed.connect(status_messages.append)

    controller.config.virtual_microphone.enabled = True
    controller.config.virtual_microphone.cable_device_id = None

    resolved = controller._resolve_virtual_microphone_output_id()

    assert resolved is None
    assert any("no audio cable was found" in message for message in status_messages)
    assert any("VB-CABLE" in message for message in status_messages)

    window.close()
