"""Qt user interface for configuring and operating Wyoming Voice Bridge."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .audio import AudioDeviceCatalog
from .config import (
    AppConfig,
    AudioSelection,
    ServiceEndpoint,
    TtsVoiceConfig,
    VirtualMicrophoneConfig,
    build_tts_voice_display_label,
)
from .constants import APP_NAME
from .controller import BridgeController
from .platforms import platform_label, virtual_mic_mode
from .virtual_cable import cable_mic_name_for_output, detect_cable_outputs, output_device_pairs


class MainWindow(QMainWindow):
    """Provide the desktop configuration and status surface for the voice bridge."""

    # Usage: construct the main application window and wire it to the controller and audio catalog.
    # Parameters: controller - the orchestration layer that performs save, monitoring, STT, TTS, and PipeWire actions; catalog - the audio device catalog used to populate device selectors.
    # Return: None.
    def __init__(self, controller: BridgeController, catalog: AudioDeviceCatalog) -> None:
        """Initialize the main window and all of its widgets."""

        super().__init__()
        self._controller = controller
        self._catalog = catalog
        self._loaded_config = AppConfig()
        self._available_tts_voices: list[TtsVoiceConfig] = []
        self.setWindowTitle(APP_NAME)
        self.resize(900, 680)
        self.setMinimumSize(780, 580)
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
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        layout.addWidget(self._build_status_header())

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_service_tab(), "Services")
        self._tabs.addTab(self._build_audio_tab(), "Audio")
        self._tabs.addTab(self._build_microphone_tab(), "Microphone")
        self._tabs.addTab(self._build_virtual_mic_tab(), "Virtual Mic")
        layout.addWidget(self._tabs)

        layout.addWidget(self._build_actions_row())
        layout.addWidget(self._build_session_pane(), stretch=1)

        self._status_bar = QStatusBar(self)
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Ready")

    # Usage: build the compact status header with state, live mic level, gate, and monitoring indicators.
    # Parameters: none.
    # Return: a QWidget row containing the live status indicators.
    def _build_status_header(self) -> QWidget:
        """Create the compact always-visible status header row."""

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(4, 0, 4, 0)
        header_layout.setSpacing(12)

        self._state_label = QLabel("State: idle")
        self._state_label.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(self._state_label)

        self._mic_level_bar = QProgressBar()
        self._mic_level_bar.setRange(0, 100)
        self._mic_level_bar.setValue(0)
        self._mic_level_bar.setFormat("%p%")
        self._mic_level_bar.setMinimumWidth(120)
        self._mic_level_bar.setMaximumWidth(180)
        self._mic_level_value_label = QLabel("0%")
        header_layout.addWidget(self._mic_level_bar)
        header_layout.addWidget(self._mic_level_value_label)

        self._mic_gate_state_label = QLabel("Gate closed")
        header_layout.addWidget(self._mic_gate_state_label)

        header_layout.addStretch(1)

        self._monitoring_status_label = QLabel("Open microphone: inactive")
        header_layout.addWidget(self._monitoring_status_label)

        return header

    # Usage: build the tab containing STT and TTS service address fields.
    # Parameters: none.
    # Return: a QWidget page containing the service endpoint form.
    def _build_service_tab(self) -> QWidget:
        """Create the service endpoint configuration tab."""

        page = QWidget()
        layout = QFormLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setVerticalSpacing(10)

        self._stt_host_edit = QLineEdit()
        self._stt_port_spin = QSpinBox()
        self._stt_port_spin.setRange(1, 65535)
        self._tts_host_edit = QLineEdit()
        self._tts_port_spin = QSpinBox()
        self._tts_port_spin.setRange(1, 65535)
        self._tts_voice_combo = QComboBox()
        self._refresh_tts_voices_button = QPushButton("Query Voices")
        self._refresh_tts_voices_button.clicked.connect(self._handle_refresh_tts_voices_clicked)
        self._refresh_tts_voices_button.setToolTip(
            "Send a Wyoming describe/info request to the configured TTS server and pick a specific voice when the server advertises one."
        )

        tts_voice_row = QWidget()
        tts_voice_layout = QHBoxLayout(tts_voice_row)
        tts_voice_layout.setContentsMargins(0, 0, 0, 0)
        tts_voice_layout.addWidget(self._tts_voice_combo, stretch=1)
        tts_voice_layout.addWidget(self._refresh_tts_voices_button)

        layout.addRow("STT host", self._stt_host_edit)
        layout.addRow("STT port", self._stt_port_spin)
        layout.addRow("TTS host", self._tts_host_edit)
        layout.addRow("TTS port", self._tts_port_spin)
        layout.addRow("TTS voice", tts_voice_row)
        return page

    # Usage: build the tab containing microphone and playback selectors.
    # Parameters: none.
    # Return: a QWidget page containing the audio device widgets.
    def _build_audio_tab(self) -> QWidget:
        """Create the audio device selection tab."""

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        form = QFormLayout()
        self._input_combo = QComboBox()
        form.addRow("Open microphone input", self._input_combo)
        layout.addLayout(form)

        layout.addWidget(QLabel("Playback outputs (check any you want TTS audio to play through)"))
        self._output_list = QListWidget()
        self._output_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._output_list.setMaximumHeight(200)
        layout.addWidget(self._output_list)

        hint = QLabel(
            "Tip: choose your real speakers or headphones here. The virtual microphone target is added automatically when enabled."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        layout.addWidget(hint)
        return page

    # Usage: build the tab containing the microphone noise gate controls.
    # Parameters: none.
    # Return: a QWidget page containing the gate threshold slider.
    def _build_microphone_tab(self) -> QWidget:
        """Create the microphone gate configuration tab."""

        page = QWidget()
        layout = QFormLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setVerticalSpacing(12)

        self._mic_gate_slider = QSlider(Qt.Orientation.Horizontal)
        self._mic_gate_slider.setRange(0, 100)
        self._mic_gate_slider.setSingleStep(1)
        self._mic_gate_slider.valueChanged.connect(self._handle_mic_gate_slider_changed)
        self._mic_gate_value_label = QLabel("0%")

        slider_row = QWidget()
        slider_layout = QHBoxLayout(slider_row)
        slider_layout.setContentsMargins(0, 0, 0, 0)
        slider_layout.addWidget(self._mic_gate_slider, stretch=1)
        slider_layout.addWidget(self._mic_gate_value_label)

        hint = QLabel(
            "Increase the gate if quiet background sounds or button taps keep triggering the app. "
            "Watch the live mic level in the header while the room is quiet, then set the gate slightly above that background level."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")

        layout.addRow("Start speech above", slider_row)
        layout.addRow(hint)
        return page

    # Usage: build the tab containing virtual microphone settings for the current platform.
    # Parameters: none.
    # Return: a QWidget page containing the virtual microphone form.
    def _build_virtual_mic_tab(self) -> QWidget:
        """Create the virtual microphone configuration tab for this platform."""

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self._virtual_mic_status_label = QLabel(
            "Virtual microphone: not configured"
            if virtual_mic_mode() is not None
            else "Virtual microphone: not supported on this platform"
        )
        layout.addWidget(self._virtual_mic_status_label)

        mic_mode = virtual_mic_mode()
        form = QFormLayout()
        if mic_mode == "pipewire":
            self._build_pipewire_virtual_mic_form(form)
        elif mic_mode == "cable":
            self._build_cable_virtual_mic_form(form)
        else:
            unsupported_note = QLabel(
                f"The virtual microphone feature is not supported on {platform_label()}. "
                f"Select a normal speaker or headphone output for synthesized speech instead."
            )
            unsupported_note.setWordWrap(True)
            form.addRow(unsupported_note)
        layout.addLayout(form)
        layout.addStretch(1)
        return page

    # Usage: build the Linux/PipeWire virtual microphone form fields and actions.
    # Parameters: layout - the QFormLayout that should receive the PipeWire widgets.
    # Return: None.
    def _build_pipewire_virtual_mic_form(self, layout: QFormLayout) -> None:
        """Create the PipeWire loopback configuration form used on Linux."""

        self._virtual_mic_enabled_checkbox = QCheckBox("Manage a PipeWire virtual microphone sink")
        self._virtual_mic_node_name_edit = QLineEdit()
        self._virtual_mic_description_edit = QLineEdit()
        self._install_virtual_mic_button = QPushButton("Write PipeWire Config")
        self._install_virtual_mic_button.clicked.connect(self._handle_install_virtual_mic_clicked)
        self._install_virtual_mic_button.setToolTip(
            "Writes a PipeWire loopback config creating a playback sink and a linked microphone-like source. "
            "The virtual mic carries only the app's TTS output. "
            "Restart pipewire, pipewire-pulse, and wireplumber after writing the config."
        )

        layout.addRow("Enabled", self._virtual_mic_enabled_checkbox)
        layout.addRow("PipeWire node name", self._virtual_mic_node_name_edit)
        layout.addRow("Description", self._virtual_mic_description_edit)
        layout.addRow("Install/update", self._install_virtual_mic_button)

    # Usage: build the Windows virtual audio cable form fields and actions.
    # Parameters: layout - the QFormLayout that should receive the cable widgets.
    # Return: None.
    def _build_cable_virtual_mic_form(self, layout: QFormLayout) -> None:
        """Create the virtual audio cable routing form used on Windows."""

        self._virtual_mic_enabled_checkbox = QCheckBox("Route synthesized TTS into a virtual audio cable as a microphone")
        self._virtual_cable_combo = QComboBox()
        self._refresh_cables_button = QPushButton("Refresh Cables")
        self._refresh_cables_button.clicked.connect(self._handle_refresh_cables_clicked)
        self._refresh_cables_button.setToolTip("Re-scan audio devices after installing or updating a virtual audio cable driver.")
        self._virtual_cable_combo.setToolTip(
            "Install a free virtual audio cable once (VB-CABLE at vb-audio.com/Cable or Voicemeeter), "
            "then pick its playback endpoint. Other apps can then select the cable's microphone endpoint."
        )

        cable_row = QWidget()
        cable_layout = QHBoxLayout(cable_row)
        cable_layout.setContentsMargins(0, 0, 0, 0)
        cable_layout.addWidget(self._virtual_cable_combo, stretch=1)
        cable_layout.addWidget(self._refresh_cables_button)

        layout.addRow("Enabled", self._virtual_mic_enabled_checkbox)
        layout.addRow("Cable playback endpoint", cable_row)

    # Usage: refresh audio device metadata and repopulate the virtual cable selector.
    # Parameters: none.
    # Return: None.
    def _handle_refresh_cables_clicked(self) -> None:
        """Refresh detected virtual audio cables after the user installs or updates a cable driver."""

        self._loaded_config = self.collect_config_from_form()
        self._controller.refresh_devices()

    # Usage: build the row containing save and refresh actions.
    # Parameters: none.
    # Return: a QWidget row containing the action buttons.
    def _build_actions_row(self) -> QWidget:
        """Create the save and refresh action buttons."""

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 0, 4, 0)

        self._save_button = QPushButton("Save Configuration")
        self._save_button.clicked.connect(self._handle_save_clicked)
        self._refresh_devices_button = QPushButton("Refresh Devices")
        self._refresh_devices_button.clicked.connect(self._handle_refresh_clicked)

        layout.addWidget(self._save_button)
        layout.addWidget(self._refresh_devices_button)
        layout.addStretch(1)
        return row

    # Usage: build the transcript and error display pane at the bottom of the window.
    # Parameters: none.
    # Return: a QTabWidget containing read-only transcript and error pages.
    def _build_session_pane(self) -> QTabWidget:
        """Create the session transcript and error tabs."""

        pane = QTabWidget()

        self._partial_transcript_edit = QPlainTextEdit()
        self._partial_transcript_edit.setReadOnly(True)
        pane.addTab(self._partial_transcript_edit, "Partial transcript")

        self._final_transcript_edit = QPlainTextEdit()
        self._final_transcript_edit.setReadOnly(True)
        pane.addTab(self._final_transcript_edit, "Final transcript")

        self._error_edit = QPlainTextEdit()
        self._error_edit.setReadOnly(True)
        pane.addTab(self._error_edit, "Errors")

        return pane

    # Usage: connect controller output signals to UI update handlers.
    # Parameters: none.
    # Return: None.
    def _connect_controller_signals(self) -> None:
        """Connect controller signals to the UI update handlers."""

        self._controller.configuration_loaded.connect(self.load_from_config)
        self._controller.tts_voices_changed.connect(self._handle_tts_voices_changed)
        self._controller.devices_changed.connect(self._refresh_device_widgets)
        self._controller.state_changed.connect(self._handle_state_changed)
        self._controller.status_changed.connect(self._handle_status_changed)
        self._controller.partial_transcript_changed.connect(self._handle_partial_transcript_changed)
        self._controller.final_transcript_changed.connect(self._handle_final_transcript_changed)
        self._controller.error_changed.connect(self._handle_error_changed)
        self._controller.monitoring_changed.connect(self._handle_monitoring_changed)
        self._controller.virtual_microphone_configured.connect(self._handle_virtual_microphone_configured)
        self._controller.microphone_level_changed.connect(self._handle_microphone_level_changed)
        self._controller.microphone_gate_changed.connect(self._handle_microphone_gate_changed)

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
        self._refresh_tts_voice_combo(config.tts_voice)
        self._set_mic_gate_threshold(config.mic_gate_threshold_percent)
        self._virtual_mic_enabled_checkbox.setChecked(config.virtual_microphone.enabled)
        mic_mode = virtual_mic_mode()
        if mic_mode == "pipewire":
            self._virtual_mic_node_name_edit.setText(config.virtual_microphone.node_name)
            self._virtual_mic_description_edit.setText(config.virtual_microphone.description)
            self._virtual_mic_status_label.setText(
                "Virtual microphone: enabled in configuration"
                if config.virtual_microphone.enabled
                else "Virtual microphone: not configured"
            )
        elif mic_mode == "cable":
            self._populate_virtual_cable_combo(config.virtual_microphone.cable_device_id)
            if config.virtual_microphone.enabled:
                self._virtual_mic_status_label.setText(
                    "Virtual microphone: enabled (TTS routes into the selected cable)"
                )
            else:
                self._virtual_mic_status_label.setText("Virtual microphone: not configured")
        else:
            self._virtual_mic_status_label.setText(
                "Virtual microphone: not supported on this platform"
            )
        self._final_transcript_edit.setPlainText(config.last_transcript)
        self._refresh_device_widgets()

    # Usage: populate the virtual audio cable selector with detected cables and a manual fallback.
    # Parameters: selected_id - the persisted cable output device id that should remain selected when available.
    # Return: None.
    def _populate_virtual_cable_combo(self, selected_id: str | None) -> None:
        """Rebuild the virtual cable endpoint combo from the current catalog state."""

        output_pairs = output_device_pairs(self._catalog.list_outputs())
        detected = detect_cable_outputs(output_pairs)
        selected_output_id = selected_id or self._virtual_cable_combo.currentData()

        self._virtual_cable_combo.blockSignals(True)
        self._virtual_cable_combo.clear()
        self._virtual_cable_combo.addItem("Auto-detect first installed cable", None)

        for device_id, name, family in detected:
            mic_name = cable_mic_name_for_output(name, family)
            self._virtual_cable_combo.addItem(
                f'{family}: "{name}" -> mic "{mic_name}"',
                device_id,
            )

        detected_ids = {device_id for device_id, _name, _family in detected}
        for device_id, name in output_pairs:
            if device_id in detected_ids:
                continue
            self._virtual_cable_combo.addItem(f'"{name}" (manual selection)', device_id)

        if selected_output_id is not None:
            matched_index = self._virtual_cable_combo.findData(selected_output_id)
            if matched_index >= 0:
                self._virtual_cable_combo.setCurrentIndex(matched_index)

        self._virtual_cable_combo.blockSignals(False)

    # Usage: rebuild the input and output device widgets using the latest catalog state and current config selections.
    # Parameters: none.
    # Return: None.
    def _refresh_device_widgets(self) -> None:
        """Refresh microphone and playback device widgets from the audio catalog."""

        self._populate_input_devices(self._loaded_config.audio.input_device_id)
        self._populate_output_devices(self._loaded_config.audio.output_device_ids)

    # Usage: rebuild the TTS voice combo box using the latest discovered server voices while preserving the current or saved selection.
    # Parameters: selected_voice - the voice that should remain selected when possible.
    # Return: None.
    def _refresh_tts_voice_combo(self, selected_voice: TtsVoiceConfig) -> None:
        """Populate the TTS voice selector from discovered voices and the saved configuration."""

        target_voice = selected_voice if isinstance(selected_voice, TtsVoiceConfig) else TtsVoiceConfig()
        self._tts_voice_combo.blockSignals(True)
        self._tts_voice_combo.clear()
        self._tts_voice_combo.addItem("Use server default voice", None)

        available_voices = list(self._available_tts_voices)
        if target_voice.is_configured() and target_voice not in available_voices:
            available_voices.append(target_voice)

        for voice in available_voices:
            self._tts_voice_combo.addItem(
                build_tts_voice_display_label(voice, available_voices),
                voice.to_dict(),
            )

        if target_voice.is_configured():
            for index in range(self._tts_voice_combo.count()):
                item_payload = self._tts_voice_combo.itemData(index)
                if TtsVoiceConfig.from_dict(item_payload) == target_voice:
                    self._tts_voice_combo.setCurrentIndex(index)
                    break
        else:
            self._tts_voice_combo.setCurrentIndex(0)

        self._tts_voice_combo.blockSignals(False)

    # Usage: convert the currently selected TTS voice combo-box value back into a configuration object.
    # Parameters: none.
    # Return: a TtsVoiceConfig describing the current voice selection, or an empty selection when using the server default voice.
    def _collect_selected_tts_voice(self) -> TtsVoiceConfig:
        """Return the currently selected TTS voice choice from the combo box."""

        return TtsVoiceConfig.from_dict(self._tts_voice_combo.currentData())

    # Usage: set the visible mic-gate slider and label to a specific threshold percentage without triggering duplicate UI updates.
    # Parameters: threshold_percent - the 0-100 gate threshold that should be displayed.
    # Return: None.
    def _set_mic_gate_threshold(self, threshold_percent: int) -> None:
        """Display the supplied microphone gate threshold percentage in the slider row."""

        normalized_threshold = max(0, min(100, int(threshold_percent)))
        self._mic_gate_slider.blockSignals(True)
        self._mic_gate_slider.setValue(normalized_threshold)
        self._mic_gate_slider.blockSignals(False)
        self._mic_gate_value_label.setText(f"{normalized_threshold}%")

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

    # Usage: collect a fresh AppConfig from the current form values before saving or managing PipeWire config.
    # Parameters: none.
    # Return: an AppConfig built from the visible widget state.
    def collect_config_from_form(self) -> AppConfig:
        """Build an AppConfig instance from the current UI form values."""

        mic_mode = virtual_mic_mode()
        if mic_mode == "cable":
            cable_device_id = self._virtual_cable_combo.currentData()
            cable_device_id = str(cable_device_id).strip() if cable_device_id else None
            pipewire_node_name = ""
            pipewire_description = ""
        else:
            cable_device_id = None
            pipewire_node_name = self._virtual_mic_node_name_edit.text().strip()
            pipewire_description = self._virtual_mic_description_edit.text().strip()

        return AppConfig(
            stt_endpoint=ServiceEndpoint(
                host=self._stt_host_edit.text().strip() or "127.0.0.1",
                port=self._stt_port_spin.value(),
            ),
            tts_endpoint=ServiceEndpoint(
                host=self._tts_host_edit.text().strip() or "127.0.0.1",
                port=self._tts_port_spin.value(),
            ),
            tts_voice=self._collect_selected_tts_voice(),
            mic_gate_threshold_percent=self._mic_gate_slider.value(),
            audio=AudioSelection(
                input_device_id=self._input_combo.currentData(),
                output_device_ids=self._collect_output_device_ids(),
            ),
            virtual_microphone=VirtualMicrophoneConfig(
                enabled=self._virtual_mic_enabled_checkbox.isChecked(),
                node_name=pipewire_node_name,
                description=pipewire_description,
                cable_device_id=cable_device_id,
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

    # Usage: query the TTS endpoint from the current form values for advertised Wyoming voice options.
    # Parameters: none.
    # Return: None.
    def _handle_refresh_tts_voices_clicked(self) -> None:
        """Ask the controller to query the current TTS endpoint for selectable voices."""

        self._loaded_config = self.collect_config_from_form()
        self._controller.refresh_tts_voices(
            ServiceEndpoint(
                host=self._tts_host_edit.text().strip() or "127.0.0.1",
                port=self._tts_port_spin.value(),
            )
        )

    # Usage: update the visible percentage label as the user drags the microphone gate slider.
    # Parameters: value - the newly selected 0-100 gate threshold percentage.
    # Return: None.
    def _handle_mic_gate_slider_changed(self, value: int) -> None:
        """Reflect the latest microphone gate threshold value in the UI immediately."""

        normalized_value = max(0, min(100, int(value)))
        self._mic_gate_value_label.setText(f"{normalized_value}%")
        self._controller.set_mic_gate_threshold_percent(normalized_value)

    # Usage: persist the current form values and write the managed PipeWire virtual microphone config file.
    # Parameters: none.
    # Return: None.
    def _handle_install_virtual_mic_clicked(self) -> None:
        """Save the current form state and install the managed PipeWire virtual microphone config."""

        self._virtual_mic_enabled_checkbox.setChecked(True)
        config = self.collect_config_from_form()
        self._loaded_config = config
        self._controller.save_configuration(config)
        self._controller.install_virtual_microphone_from_config()

    # Usage: update the status bar when the controller emits a new human-readable status message.
    # Parameters: message - the status text that should be shown in the status bar.
    # Return: None.
    def _handle_status_changed(self, message: str) -> None:
        """Display the latest controller status in the window status bar."""

        self._status_bar.showMessage(message)

    # Usage: accept a fresh list of discovered TTS voices from the controller and keep the current UI selection when possible.
    # Parameters: voices - the selectable voice options returned by the Wyoming TTS server.
    # Return: None.
    def _handle_tts_voices_changed(self, voices: list[TtsVoiceConfig]) -> None:
        """Refresh the TTS voice selector after the controller finishes a voice query."""

        self._available_tts_voices = list(voices)
        selected_voice = self._collect_selected_tts_voice()
        self._refresh_tts_voice_combo(selected_voice)

    # Usage: update the state label when the controller transitions between high-level states.
    # Parameters: state - the new high-level state string.
    # Return: None.
    def _handle_state_changed(self, state: str) -> None:
        """Reflect the controller's high-level state in the header area."""

        self._state_label.setText(f"State: {state}")

    # Usage: display whether the open microphone monitor is currently active.
    # Parameters: active - whether the controller's always-on microphone capture is running.
    # Return: None.
    def _handle_monitoring_changed(self, active: bool) -> None:
        """Display the current always-on microphone monitoring state."""

        self._monitoring_status_label.setText(
            f"Open microphone: {'active' if active else 'inactive'}"
        )

    # Usage: update the live microphone level meter from the controller's latest normalized input level.
    # Parameters: level_percent - the current microphone level expressed as an integer percentage from 0 to 100.
    # Return: None.
    def _handle_microphone_level_changed(self, level_percent: int) -> None:
        """Refresh the live microphone level meter and percentage label."""

        normalized_level = max(0, min(100, int(level_percent)))
        self._mic_level_bar.setValue(normalized_level)
        self._mic_level_value_label.setText(f"{normalized_level}%")

    # Usage: update the text indicator that shows whether the current microphone level is above the configured gate threshold.
    # Parameters: gate_open - True when the current mic level is at or above the gate threshold, otherwise False.
    # Return: None.
    def _handle_microphone_gate_changed(self, gate_open: bool) -> None:
        """Display whether the live microphone level is currently opening the gate."""

        self._mic_gate_state_label.setText("Gate open" if gate_open else "Gate closed")

    # Usage: update the virtual microphone status label after the controller writes the PipeWire config file.
    # Parameters: config_path - the filesystem path of the config file that was written.
    # Return: None.
    def _handle_virtual_microphone_configured(self, config_path: str) -> None:
        """Display the location of the managed PipeWire virtual microphone config file."""

        self._virtual_mic_status_label.setText(f"Virtual microphone: configured at {config_path}")

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

    # Usage: stop background workers cleanly when the main window is being closed.
    # Parameters: event - the Qt close event emitted by the window manager.
    # Return: None.
    def closeEvent(self, event: QCloseEvent) -> None:
        """Shut down controller resources before the window closes."""

        self._controller.shutdown()
        super().closeEvent(event)
