"""Shared application constants used across the Wyoming Voice Bridge codebase."""

APP_NAME = "Wyoming Voice Bridge"
APP_ID = "io.github.justinlime.WyomingVoiceBridge"
APP_VERSION = "0.1.0"
CONFIG_DIR_NAME = "wyoming-voice-bridge"
CONFIG_FILE_NAME = "config.json"
LOG_FILE_NAME = "bridge.log"

DEFAULT_STT_HOST = "127.0.0.1"
DEFAULT_STT_PORT = 10300
DEFAULT_TTS_HOST = "127.0.0.1"
DEFAULT_TTS_PORT = 10200

DEFAULT_AUDIO_RATE = 16_000
DEFAULT_AUDIO_WIDTH = 2
DEFAULT_AUDIO_CHANNELS = 1
DEFAULT_AUDIO_BUFFER_MS = 40
DEFAULT_MIC_GATE_THRESHOLD_PERCENT = 4
DEFAULT_MIC_GAIN = 1.0
MAX_MIC_GAIN = 10.0

# How long the user must stay silent before the utterance is considered finished.
# Natural pauses mid-thought are often 1.5-2.5s, so the default is deliberately
# generous to avoid splitting long speech into separate STT sessions.
MIN_STOP_SILENCE_MS = 500
DEFAULT_STOP_SILENCE_MS = 2500
MAX_STOP_SILENCE_MS = 6000

DEFAULT_VAD_SAMPLE_RATE = 16_000
DEFAULT_VAD_FRAME_MS = 32
DEFAULT_VAD_PRE_ROLL_MS = 600
DEFAULT_VAD_SPEECH_PAD_MS = 160
DEFAULT_VAD_PAUSE_BUFFER_MS = 480
DEFAULT_VAD_START_WINDOW_FRAMES = 6
DEFAULT_VAD_START_TRIGGER_FRAMES = 4
DEFAULT_VAD_START_SPEECH_THRESHOLD = 0.55
DEFAULT_VAD_CONTINUE_SPEECH_THRESHOLD = 0.4
DEFAULT_VAD_STOP_SILENCE_FRAMES = 40

DEFAULT_VIRTUAL_MIC_NODE_NAME = "wyoming_voice_bridge_mic"
DEFAULT_VIRTUAL_MIC_DESCRIPTION = "Wyoming Voice Bridge Mic"
DEFAULT_VIRTUAL_MIC_CONFIG_FILE_NAME = "10-wyoming-voice-bridge-virtual-mic.conf"

STATE_IDLE = "idle"
STATE_LISTENING = "listening"
STATE_TRANSCRIBING = "transcribing"
STATE_SYNTHESIZING = "synthesizing"
STATE_SPEAKING = "speaking"
STATE_ERROR = "error"
