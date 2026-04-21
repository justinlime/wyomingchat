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

SHORTCUT_ID_PUSH_TO_TALK = "push-to-talk"
DEFAULT_SHORTCUT_DESCRIPTION = "Hold to speak with Wyoming Voice Bridge"
DEFAULT_PREFERRED_TRIGGER = "Super+space"

STATE_IDLE = "idle"
STATE_LISTENING = "listening"
STATE_TRANSCRIBING = "transcribing"
STATE_SYNTHESIZING = "synthesizing"
STATE_SPEAKING = "speaking"
STATE_ERROR = "error"
