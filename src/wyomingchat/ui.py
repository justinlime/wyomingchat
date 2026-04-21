"""Qt user interface for configuring and operating Wyoming Voice Bridge."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .audio import AudioDeviceCatalog, AudioDeviceDescriptor
from .config import AppConfig, AudioSelection, ServiceEndpoint, ShortcutConfig
from .constants import APP_NAME, DEFAULT_SHORTCUT_DESCRIPTION
from .controller import BridgeController


class MainWindow(QMainWindow):
    """Provide the desktop configuration and control surface for the voice bridge."""

    # Usage: construct the main application window and wire it to the controller and audio catalog.
    # Parameters: controller - the orchestration layer that performs save, shortcut, STT, and TTS actions; catalog - the audio device catalog used to populate device selectors.
    # Return: None.
    def __init__(self, controller: BridgeController, catalog: AudioDeviceCatalog) -> None:
        """Initialize the main window and all of its widgets."""

        super().__init__()
        self._controller = controller
        self._catalog = catalog
        self._loaded_config = AppConfig()
        self.setWindowTitle(APP_NAME)
        self.resize(980, 760)
        self._build_window()
        self._connect_controller_signals()

    # Usage: create the complete widget tree used by the main window.
    # Parameters: none.
    # Return: None.
    def _build_window(self) -> None:
        """Build the main window's widget layout."""

        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setSpacing(12)

        self._state_label = QLabel("State: idle")
        self._shortcut_status_label = QLabel("Shortcut: not registered")
        self._portal_status_label = QLabel("Portal listener: inactive")
        layout.addWidget(self._state_label)
        layout.addWidget(self._shortcut_status_label)
        layout.addWidget(self._portal_status_label)

        layout.addWidget(self._build_service_group())
        layout.addWidget(self._build_audio_group())
        layout.addWidget(self._build_shortcut_group())
        layout.addWidget(self._build_manual_control_group())
        layout.addWidget(self._build_status_group(), stretch=1)

        self._status_bar = QStatusBar(self)
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Ready")

    # Usage: build the UI section containing STT and TTS service address fields.
    # Parameters: none.
    # Return: a QGroupBox containing the service endpoint form.
    def _build_service_group(self) -> QGroupBox:
        """Create the service endpoint configuration section."""

        group = QGroupBox("Wyoming Services")
        layout = QFormLayout(group)

        self._stt_host_edit = QLineEdit()
        self._stt_port_spin = QSpinBox()
        self._stt_port_spin.setRange(1, 65535)
        self._tts_host_edit = QLineEdit()
        self._tts_port_spin = QSpinBox()
        self._tts_port_spin.setRange(1, 65535)

        layout.addRow("STT host", self._stt_host_edit)
        layout.addRow("STT port", self._stt_port_spin)
        layout.addRow("TTS host", self._tts_host_edit)
        layout.addRow("TTS port", self._tts_port_spin)
        return group

    # Usage: build the UI section containing microphone and speaker selectors.
    # Parameters: none.
    # Return: a QGroupBox containing the audio device widgets.
    def _build_audio_group(self) -> QGroupBox:
        """Create the audio device selection section."""

        group = QGroupBox("Audio Devices")
        layout = QVBoxLayout(group)

        form = QFormLayout()
        self._input_combo = QComboBox()
        form.addRow("Microphone", self._input_combo)
        layout.addLayout(form)

        self._output_list = QListWidget()
        self._output_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        layout.addWidget(QLabel("Playback outputs"))
        layout.addWidget(self._output_list)

        button_row = QHBoxLayout()
        self._refresh_devices_button = QPushButton("Refresh Devices")
        self._refresh_devices_button.clicked.connect(self._handle_refresh_clicked)
        button_row.addWidget(self._refresh_devices_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        return group

    # Usage: build the UI section containing global shortcut configuration widgets.
    # Parameters: none.
    # Return: a QGroupBox containing shortcut fields and actions.
    def _build_shortcut_group(self) -> QGroupBox:
        """Create the global shortcut configuration section."""

        group = QGroupBox("Push-to-Talk Shortcut")
        layout = QFormLayout(group)

        self._shortcut_trigger_edit = QLineEdit()
        self._shortcut_description_edit = QLineEdit(DEFAULT_SHORTCUT_DESCRIPTION)
        self._shortcut_enabled_checkbox = QCheckBox("Enable global push-to-talk shortcut")
        self._shortcut_enabled_checkbox.setChecked(True)
        self._register_shortcut_button = QPushButton("Register Shortcut")
        self._register_shortcut_button.clicked.connect(self._handle_register_shortcut_clicked)

        layout.addRow("Preferred trigger", self._shortcut_trigger_edit)
        layout.addRow("Description", self._shortcut_description_edit)
        layout.addRow("Enabled", self._shortcut_enabled_checkbox)
        layout.addRow("Portal registration", self._register_shortcut_button)
        return group

    # Usage: build the section that exposes save controls and a manual push-to-talk fallback button.
    # Parameters: none.
    # Return: a QGroupBox containing save and manual control actions.
    def _build_manual_control_group(self) -> QGroupBox:
        """Create the action buttons for saving config and manual push-to-talk."""

        group = QGroupBox("Actions")
        layout = QHBoxLayout(group)

        self._save_button = QPushButton("Save Configuration")
        self._save_button.clicked.connect(self._handle_save_clicked)
        self._manual_ptt_button = QPushButton("Hold to Talk")
        self._manual_ptt_button.pressed.connect(self._handle_manual_ptt_pressed)
        self._manual_ptt_button.released.connect(self._handle_manual_ptt_released)

        layout.addWidget(self._save_button)
        layout.addWidget(self._manual_ptt_button)
        layout.addStretch(1)
        return group

    # Usage: build the transcript and error display widgets shown at the bottom of the window.
    # Parameters: none.
    # Return: a QGroupBox containing read-only transcript and error panes.
    def _build_status_group(self) -> QGroupBox:
        """Create the transcript and error display section."""

        group = QGroupBox("Session Status")
        layout = QVBoxLayout(group)

        self._partial_transcript_edit = QPlainTextEdit()
        self._partial_transcript_edit.setReadOnly(True)
        self._final_transcript_edit = QPlainTextEdit()
        self._final_transcript_edit.setReadOnly(True)
        self._error_edit = QPlainTextEdit()
        self._error_edit.setReadOnly(True)

        layout.addWidget(QLabel("Partial transcript"))
        layout.addWidget(self._partial_transcript_edit)
        layout.addWidget(QLabel("Final transcript"))
        layout.addWidget(self._final_transcript_edit)
        layout.addWidget(QLabel("Errors"))
        layout.addWidget(self._error_edit)
        return group

    # Usage: connect controller output signals to UI update handlers.
    # Parameters: none.
    # Return: None.
    def _connect_controller_signals(self) -> None:
        """Connect controller signals to the UI update handlers."""

        self._controller.configuration_loaded.connect(self.load_from_config)
        self._controller.devices_changed.connect(self._refresh_device_widgets)
        self._controller.state_changed.connect(self._handle_state_changed)
        self._controller.status_changed.connect(self._handle_status_changed)
        self._controller.partial_transcript_changed.connect(self._handle_partial_transcript_changed)
        self._controller.final_transcript_changed.connect(self._handle_final_transcript_changed)
        self._controller.error_changed.connect(self._handle_error_changed)
        self._controller.shortcut_registered.connect(self._handle_shortcut_registered)
        self._controller.shortcut_error.connect(self._handle_shortcut_error)
        self._controller.shortcut_availability_changed.connect(self._handle_shortcut_availability_changed)

    # Usage: populate the entire form with configuration values loaded from disk.
    # Parameters: config - the AppConfig that should be reflected in the UI.
    # Return: None.
    def load_from_config(self, config: AppConfig) -> None:
        """Load a configuration object into the visible form widgets."""

        self._loaded_config = config
        self._stt_host_edit.setText(config.stt_endpoint.host)
        self._stt_port_spin.setValue(config.stt_endpoint.port)
        self._tts_host_edit.setText(config.tts_endpoint.host)
        self._tts_port_spin.setValue(config.tts_endpoint.port)
        self._shortcut_trigger_edit.setText(config.shortcut.preferred_trigger)
        self._shortcut_description_edit.setText(config.shortcut.description)
        self._shortcut_enabled_checkbox.setChecked(config.shortcut.enabled)
        self._shortcut_status_label.setText(
            f"Shortcut: {config.shortcut.trigger_description or 'not registered'}"
        )
        self._final_transcript_edit.setPlainText(config.last_transcript)
        self._refresh_device_widgets()

    # Usage: rebuild the input and output device widgets using the latest catalog state and current config selections.
    # Parameters: none.
    # Return: None.
    def _refresh_device_widgets(self) -> None:
        """Refresh microphone and playback device widgets from the audio catalog."""

        self._populate_input_devices(self._loaded_config.audio.input_device_id)
        self._populate_output_devices(self._loaded_config.audio.output_device_ids)

    # Usage: fill the microphone combo box and restore the selected device when possible.
    # Parameters: selected_id - the previously selected microphone id, or None to select the default device.
    # Return: None.
    def _populate_input_devices(self, selected_id: str | None) -> None:
        """Populate the microphone selector using the current audio catalog."""

        current_selected_id = selected_id or self._input_combo.currentData()
        self._input_combo.blockSignals(True)
        self._input_combo.clear()

        for descriptor in self._catalog.list_inputs():
            label = descriptor.name
            if descriptor.is_default:
                label += " (default)"
            if descriptor.pipewire_node_id is not None:
                label += f" [PW {descriptor.pipewire_node_id}]"
            self._input_combo.addItem(label, descriptor.id)

        if current_selected_id is not None:
            matched_index = self._input_combo.findData(current_selected_id)
            if matched_index >= 0:
                self._input_combo.setCurrentIndex(matched_index)
        self._input_combo.blockSignals(False)

    # Usage: fill the playback output list and restore checked items for selected speakers.
    # Parameters: selected_ids - the list of persisted output ids that should remain checked.
    # Return: None.
    def _populate_output_devices(self, selected_ids: list[str]) -> None:
        """Populate the playback output list using the current audio catalog."""

        current_ids = set(selected_ids or self._collect_output_device_ids())
        self._output_list.clear()

        for descriptor in self._catalog.list_outputs():
            label = descriptor.name
            if descriptor.is_default:
                label += " (default)"
            if descriptor.pipewire_node_id is not None:
                label += f" [PW {descriptor.pipewire_node_id}]"
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setData(Qt.ItemDataRole.UserRole, descriptor.id)
            item.setCheckState(
                Qt.CheckState.Checked if descriptor.id in current_ids else Qt.CheckState.Unchecked
            )
            self._output_list.addItem(item)

    # Usage: gather all checked playback outputs from the list widget.
    # Parameters: none.
    # Return: a list of persisted output device ids selected by the user.
    def _collect_output_device_ids(self) -> list[str]:
        """Return the currently checked playback device identifiers."""

        output_ids: list[str] = []
        for index in range(self._output_list.count()):
            item = self._output_list.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                output_ids.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return output_ids

    # Usage: collect a fresh AppConfig from the current form values before saving or registering shortcuts.
    # Parameters: none.
    # Return: an AppConfig built from the visible widget state.
    def collect_config_from_form(self) -> AppConfig:
        """Build an AppConfig instance from the current UI form values."""

        return AppConfig(
            stt_endpoint=ServiceEndpoint(
                host=self._stt_host_edit.text().strip() or "127.0.0.1",
                port=self._stt_port_spin.value(),
            ),
            tts_endpoint=ServiceEndpoint(
                host=self._tts_host_edit.text().strip() or "127.0.0.1",
                port=self._tts_port_spin.value(),
            ),
            audio=AudioSelection(
                input_device_id=self._input_combo.currentData(),
                output_device_ids=self._collect_output_device_ids(),
            ),
            shortcut=ShortcutConfig(
                preferred_trigger=self._shortcut_trigger_edit.text().strip(),
                description=self._shortcut_description_edit.text().strip() or DEFAULT_SHORTCUT_DESCRIPTION,
                trigger_description=self._loaded_config.shortcut.trigger_description,
                enabled=self._shortcut_enabled_checkbox.isChecked(),
            ),
            last_transcript=self._final_transcript_edit.toPlainText(),
        )

    # Usage: save the current form values to disk and update the controller's active configuration.
    # Parameters: none.
    # Return: None.
    def _handle_save_clicked(self) -> None:
        """Persist the current form values through the controller."""

        config = self.collect_config_from_form()
        self._loaded_config = config
        self._controller.save_configuration(config)

    # Usage: refresh device metadata and immediately repopulate device widgets.
    # Parameters: none.
    # Return: None.
    def _handle_refresh_clicked(self) -> None:
        """Ask the controller to refresh device metadata and UI selections."""

        self._loaded_config = self.collect_config_from_form()
        self._controller.refresh_devices()

    # Usage: save the current form values and ask the controller to bind the configured portal shortcut.
    # Parameters: none.
    # Return: None.
    def _handle_register_shortcut_clicked(self) -> None:
        """Persist the current form state and request portal shortcut registration."""

        config = self.collect_config_from_form()
        self._loaded_config = config
        self._controller.save_configuration(config)
        self._controller.register_shortcut_from_config()

    # Usage: start a manual push-to-talk session when the user presses the fallback button.
    # Parameters: none.
    # Return: None.
    def _handle_manual_ptt_pressed(self) -> None:
        """Start listening when the manual hold-to-talk button is pressed."""

        self._controller.start_listening()

    # Usage: stop the manual push-to-talk session when the user releases the fallback button.
    # Parameters: none.
    # Return: None.
    def _handle_manual_ptt_released(self) -> None:
        """Stop listening when the manual hold-to-talk button is released."""

        self._controller.stop_listening()

    # Usage: update the status bar when the controller emits a new human-readable status message.
    # Parameters: message - the status text that should be shown in the status bar.
    # Return: None.
    def _handle_status_changed(self, message: str) -> None:
        """Display the latest controller status in the window status bar."""

        self._status_bar.showMessage(message)

    # Usage: update the state label when the controller transitions between high-level states.
    # Parameters: state - the new high-level state string.
    # Return: None.
    def _handle_state_changed(self, state: str) -> None:
        """Reflect the controller's high-level state in the header area."""

        self._state_label.setText(f"State: {state}")

    # Usage: display streaming transcript updates in the partial transcript text box.
    # Parameters: text - the current transcript-chunk aggregation to display.
    # Return: None.
    def _handle_partial_transcript_changed(self, text: str) -> None:
        """Display the latest streaming transcript in the partial transcript pane."""

        self._partial_transcript_edit.setPlainText(text)

    # Usage: display the final transcript in the dedicated final transcript text box.
    # Parameters: text - the final transcript returned by the STT service.
    # Return: None.
    def _handle_final_transcript_changed(self, text: str) -> None:
        """Display the final transcript in the final transcript pane."""

        self._final_transcript_edit.setPlainText(text)

    # Usage: display controller errors in the read-only error text pane.
    # Parameters: text - the error message to show.
    # Return: None.
    def _handle_error_changed(self, text: str) -> None:
        """Display the latest controller error message."""

        self._error_edit.setPlainText(text)

    # Usage: update the shortcut status label after the portal confirms the bound trigger text.
    # Parameters: trigger_description - the user-facing shortcut description returned by the portal backend.
    # Return: None.
    def _handle_shortcut_registered(self, trigger_description: str) -> None:
        """Display the final bound shortcut text after successful registration."""

        self._shortcut_status_label.setText(f"Shortcut: {trigger_description}")
        self._loaded_config.shortcut.trigger_description = trigger_description

    # Usage: append shortcut-specific portal failures to the error pane for visibility.
    # Parameters: message - the shortcut registration error message.
    # Return: None.
    def _handle_shortcut_error(self, message: str) -> None:
        """Display a shortcut registration failure in the error pane."""

        self._error_edit.setPlainText(message)

    # Usage: update the portal listener status label when the worker becomes active or inactive.
    # Parameters: available - whether the global shortcut worker is actively connected and listening.
    # Return: None.
    def _handle_shortcut_availability_changed(self, available: bool) -> None:
        """Display whether the global shortcut portal listener is currently active."""

        self._portal_status_label.setText(
            f"Portal listener: {'active' if available else 'inactive'}"
        )

    # Usage: stop background workers cleanly when the main window is being closed.
    # Parameters: event - the Qt close event emitted by the window manager.
    # Return: None.
    def closeEvent(self, event: QCloseEvent) -> None:
        """Shut down controller resources before the window closes."""

        self._controller.shutdown()
        super().closeEvent(event)
