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


# Usage: verify the Log tab records INFO entries, deduplicates error mirrors, and honors the visibility filters.
# Parameters: tmp_path - pytest fixture providing a temp directory; qapp - module-level Qt app fixture.
# Return: None.
def test_log_tab_shows_info_and_filters_entries(tmp_path, qapp) -> None:
    """Ensure info entries appear and the Info/Errors checkboxes filter the log pane."""

    controller, window = build_window(tmp_path)
    controller.status_changed.emit("bridge started")
    controller.error_changed.emit("boom")
    # The controller emits failures through both channels; the duplicate INFO
    # copy that immediately follows the ERROR must not be logged twice.
    controller.status_changed.emit("boom")

    text = window._error_edit.toPlainText()
    assert "bridge started" in text
    assert text.count("boom") == 1

    # Hide errors: only the info line remains.
    window._show_error_log_checkbox.setChecked(False)
    text = window._error_edit.toPlainText()
    assert "bridge started" in text
    assert "boom" not in text

    # Hide info too: the pane is empty.
    window._show_info_log_checkbox.setChecked(False)
    assert window._error_edit.toPlainText() == ""

    window.close()


# Usage: verify the Errors tab appends timestamped log entries instead of replacing the previous error.
# Parameters: tmp_path - pytest fixture providing a temp directory; qapp - module-level Qt app fixture.
# Return: None.
def test_error_log_appends_errors_with_timestamps(tmp_path, qapp) -> None:
    """Ensure the error tab behaves as a scrollable log with a working clear action."""

    controller, window = build_window(tmp_path)
    controller.error_changed.emit("first failure")
    controller.error_changed.emit("second failure")

    log_text = window._error_edit.toPlainText()
    assert "first failure" in log_text
    assert "second failure" in log_text
    assert log_text.index("first failure") < log_text.index("second failure")

    # Routine empty error clears must not pollute the log.
    controller.error_changed.emit("")
    assert window._error_edit.toPlainText() == log_text

    # The clear button resets the log for the next session of troubleshooting.
    window._clear_error_log_button.click()
    assert window._error_edit.toPlainText() == ""

    window.close()


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


# Usage: verify that tooltip wrapping produces compact wrapped rich text.
# Parameters: none.
# Return: None.
def test_wrap_tooltip_text_wraps_and_escapes() -> None:
    """Ensure the tooltip helper wraps long text and escapes markup."""

    from wyomingchat.ui import wrap_tooltip_text

    result = wrap_tooltip_text("word " * 60)
    assert result.startswith("<p style='white-space: pre-wrap'>")
    assert "\n" in result

    escaped = wrap_tooltip_text("<script>alert('x')</script>")
    assert "&lt;" in escaped
    assert "<script>" not in escaped


# Usage: verify the Pause Bridge button toggles the controller's listening state.
# Parameters: tmp_path - pytest fixture providing a temp directory; qapp - module-level Qt app fixture.
# Return: None.
def test_pause_bridge_button_toggles_listening(tmp_path, qapp) -> None:
    """Ensure the action button pauses and resumes the bridge."""

    controller, window = build_window(tmp_path)

    assert window._pause_bridge_button.text() == "Pause Bridge"
    window._pause_bridge_button.click()
    assert window._pause_bridge_button.text() == "Resume Bridge"
    assert controller._paused is True

    window._pause_bridge_button.click()
    assert window._pause_bridge_button.text() == "Pause Bridge"
    assert controller._paused is False

    window.close()
