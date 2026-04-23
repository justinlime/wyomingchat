# Wyoming Voice Bridge

Wyoming Voice Bridge is a Linux desktop application that keeps a microphone open locally, detects speech automatically, streams that speech to a local Wyoming STT service, and then plays back a Wyoming TTS response. Everything is intended to stay on the user's machine or local network.

## Current interaction model

- The microphone stays open while the app is running.
- The app only starts an STT session when it is idle and voice activity is detected.
- A short pre-roll buffer and trailing-silence hangover are used so speech is less likely to be clipped at the beginning or end.
- While transcription or TTS playback is active, the app ignores additional microphone audio for STT.
- TTS output can be routed to normal playback devices and optionally to a PipeWire-managed virtual microphone sink.

## Requirements

- Linux with PipeWire
- Python 3.11+
- Local Wyoming-compatible STT and TTS services
- Nix with flakes enabled for the primary run/install workflow

## Primary run workflow: Nix

The preferred way to run this project is through its Nix flake.

```bash
nix run .#
```

Useful alternatives:

```bash
nix build .#
nix profile install .#
```

Notes:

- `nix run .#` launches the packaged `wyoming-voice-bridge` application directly.
- `nix build .#` builds the default package without launching it.
- `nix profile install .#` installs the package into your user profile for repeat testing.
- The flake is the primary supported way to run the project locally.

## Development commands

```bash
uv run pytest
python3 -m compileall src tests
```

## Configuration overview

The UI currently lets you configure:

- STT host and port
- TTS host and port
- Microphone input device used for always-on monitoring
- One or more playback outputs for synthesized audio
- PipeWire virtual microphone node name and description

## PipeWire virtual microphone

The app can write a PipeWire loopback configuration that creates two linked virtual devices:

- a **virtual sink** that Wyoming Voice Bridge can target for TTS playback
- a **virtual source** that desktop applications can choose as a microphone

The virtual microphone path is intended to carry only Wyoming Voice Bridge's TTS output. It does
not forward the user's live microphone audio into that virtual source.

In the UI:

1. Enable the virtual microphone section.
2. Choose a PipeWire node name and description.
3. Click **Write PipeWire Config**.
4. Restart PipeWire services:

```bash
systemctl --user restart pipewire pipewire-pulse wireplumber
```

5. Reopen the app and refresh devices.
6. Select the created **virtual sink/output** in **Playback outputs** if you want TTS audio routed into the virtual microphone path.
7. In other applications, choose the created **virtual source/microphone** as the input device.

## Notes and limitations

- The app currently uses a conservative Silero-based voice activity detector with buffering, probability thresholds, and PCM normalization to reduce false triggers and clipped speech.
- Qt Multimedia capture and playback are used for audio I/O, with PipeWire metadata discovery handled through `pw-dump` when available.
- Virtual microphone creation currently writes a PipeWire loopback configuration but does not restart PipeWire automatically.
- The application is intended for local Wyoming services and Linux desktop environments.
