# Wyoming Voice Bridge

Wyoming Voice Bridge is a free, open-source desktop app that turns your microphone into a voice interface for local speech AI. It listens continuously, detects when you speak, sends your speech to a local Wyoming speech-to-text (STT) service, and plays the reply from a local Wyoming text-to-speech (TTS) service.

Everything runs on your own machine or local network. Your voice never leaves your home.

## Features

- Always-on listening with automatic speech detection
- Live transcript of everything you say
- Works with any Wyoming-compatible STT and TTS service (Rhasspy, Home Assistant, piper, and more)
- Plays replies through speakers, headphones, or a virtual microphone other apps can use
- Everything is configured in the app — no config files to edit

## Requirements

- **Linux** or **Windows 10/11**
- A microphone
- A Wyoming-compatible STT service and TTS service, running locally or on your network
- **Linux:** Nix (with flakes) or Python 3.11+
- **Windows:** nothing extra — the standalone EXE needs no other software

## Running the app

### Windows

**Standalone EXE (recommended)**

Download the single-file EXE and double-click it. You can copy it anywhere and run it — no Python or other software required.

**From source**

```powershell
uv sync
uv run wyoming-voice-bridge
```

### Linux

**Nix (recommended)**

```bash
nix run .#
```

**From source**

```bash
uv sync
uv run wyoming-voice-bridge
```

## Getting started

1. Open the **Services** tab and enter the address and port of your STT and TTS services.
2. Open the **Audio** tab and pick your microphone and the speakers or headphones you want replies to play through.
3. Click **Save Configuration**.
4. Talk. The app listens for speech, shows the transcript, and plays the spoken reply.

That's it. There is no push-to-talk — just speak normally.

## Virtual microphone

The **Virtual Mic** tab can route replies into a virtual microphone, so other applications (video calls, recording software, games) can use the assistant as an input device. The virtual microphone carries only the assistant's replies, never your live microphone.

- **Linux:** the app creates a PipeWire virtual microphone for you. Enable it, set a node name, click **Write PipeWire Config**, and restart PipeWire.
- **Windows:** install a free virtual audio cable such as [VB-CABLE](https://vb-audio.com/Cable/index.htm), then enable the virtual microphone in the app and pick the cable.

## Where settings are stored

| | Config | Logs |
|---|---|---|
| **Windows** | `%APPDATA%\wyoming-voice-bridge\config.json` | `%LOCALAPPDATA%\wyoming-voice-bridge\bridge.log` |
| **Linux** | `~/.config/wyoming-voice-bridge/config.json` | `~/.local/state/wyoming-voice-bridge/bridge.log` |

## Building the Windows EXE

```powershell
uv sync --extra packaging
uv run pyinstaller --noconfirm packaging/wyomingchat.spec
```

The result is a single self-contained `dist\WyomingVoiceBridge.exe`.

## Notes

- Only one voice interaction runs at a time. New speech is ignored while a reply is being transcribed or played.
- The app is intended for local Wyoming services and desktop use.
