# Wyoming Voice Bridge

Wyoming Voice Bridge is a Linux desktop application that connects a local microphone, local Wyoming speech-to-text service, and local Wyoming text-to-speech service into a single push-to-talk workflow.

This repository now contains a full greenfield implementation that matches the project brief in `AGENTS.md`:

- PySide6 desktop UI
- Wayland-friendly global push-to-talk integration through the XDG Global Shortcuts portal
- Wyoming protocol STT and TTS clients
- PipeWire-aware audio device discovery support
- Multi-output playback selection
- Persistent JSON configuration stored in the XDG config directory

## Current architecture

The app is organized into focused modules:

- `wyomingchat.config` — configuration models and JSON serialization
- `wyomingchat.storage` — XDG config persistence
- `wyomingchat.pipewire` — optional PipeWire CLI inspection helpers
- `wyomingchat.audio` — Qt Multimedia capture/playback and device discovery
- `wyomingchat.wyoming_protocol` — Wyoming event framing and parsing
- `wyomingchat.clients` — Wyoming STT and TTS TCP clients
- `wyomingchat.shortcuts` — XDG Global Shortcuts portal integration over D-Bus
- `wyomingchat.controller` — bridge orchestration and application state
- `wyomingchat.ui` — Qt main window

## Requirements

- Linux desktop session
- Wayland session recommended
- A working session D-Bus
- `xdg-desktop-portal` plus a backend that implements the Global Shortcuts portal
- PipeWire-enabled audio stack for best results
- Local Wyoming STT and TTS services reachable by TCP
- Python 3.11+
- `uv` for dependency management

## Quick start

### Most Linux distributions

```bash
uv sync
uv run wyoming-voice-bridge
```

### NixOS

The flake now exposes a default package that bundles Python, PySide6, and the Qt runtime libraries needed to launch Wyoming Voice Bridge on NixOS.

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
- The flake is now intended for install/test workflows rather than a project development shell.

## Desktop entry for portal registration

Global shortcut portals expect the application to have a matching desktop file. This repository includes one at:

```text
resources/io.github.justinlime.WyomingVoiceBridge.desktop
```

For local development, copy it into your user applications directory and adjust the `Exec=` line if needed:

```bash
mkdir -p ~/.local/share/applications
cp resources/io.github.justinlime.WyomingVoiceBridge.desktop ~/.local/share/applications/
```

After that, restart the application and use the **Register Shortcut** button in the UI.

## Development commands

```bash
uv run pytest
python3 -m compileall src tests
```

## Notes and limitations

- The app uses Qt Multimedia for capture and playback, which on current Linux systems is typically backed by PulseAudio or PipeWire, and is intended for PipeWire-backed systems.
- PipeWire CLI inspection is optional; the application still works if `pw-dump` is unavailable.
- Global shortcuts depend on compositor and portal backend support.
- The TTS stage uses Wyoming streaming audio playback, but submits text as a single synthesis request after the final transcript arrives.
