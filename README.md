# Wyoming Voice Bridge

Wyoming Voice Bridge is a desktop application that keeps a microphone open locally,
detects speech automatically, streams that speech to a local Wyoming STT service, and
then plays back a Wyoming TTS response. Everything is intended to stay on the user's
machine or local network.

The application runs on **Linux (primary, Nix-first)** and **Windows** (via a standalone
EXE or `uv`/pip installation).

## Current interaction model

- The microphone stays open while the app is running.
- The app only starts an STT session when it is idle and voice activity is detected.
- A short pre-roll buffer and trailing-silence hangover are used so speech is less likely
  to be clipped at the beginning or end.
- While transcription or TTS playback is active, the app ignores additional microphone
  audio for STT.
- TTS output can be routed to normal playback devices and, on Linux, optionally to a
  PipeWire-managed virtual microphone sink.

## Requirements

- **Linux:** PipeWire, Python 3.11+ (or Nix with flakes), local Wyoming-compatible STT
  and TTS services.
- **Windows:** Windows 10/11, Python 3.11+ (only when running from source; the EXE needs
  no Python), local Wyoming-compatible STT and TTS services.

## Primary run workflow: Nix (Linux)

The preferred way to run the project on Linux is through its Nix flake.

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
- The flake is the primary supported way to run the project locally on Linux.

## Running on Windows

### Option A: standalone EXE

Prebuilt releases (when published) or a locally built EXE run without any Python
installation. See [Building the Windows EXE](#building-the-windows-exe) below.

### Option B: run from source

```powershell
uv sync            # or: pip install .
uv run wyoming-voice-bridge
```

On Windows, configuration is stored in `%APPDATA%\wyoming-voice-bridge\config.json`
and logs in `%LOCALAPPDATA%\wyoming-voice-bridge\bridge.log` (the Linux equivalents are
the XDG config/state directories).

## Building the Windows EXE

The project includes a PyInstaller spec that produces a self-contained, one-folder
Windows application with no Python required at runtime.

```powershell
# On a Windows machine, inside the project directory:
uv sync --extra packaging
uv run pyinstaller --noconfirm packaging/wyomingchat.spec
```

The output lands in `dist\WyomingVoiceBridge\WyomingVoiceBridge.exe`. Run that file
directly; the adjacent `_internal` folder must stay next to the EXE (the one-folder
layout is used because Qt Multimedia loads its audio plugins at runtime).

Build details handled by `packaging/wyomingchat.spec`:

- Bundles the `ggml` Silero VAD model that `pysilero-vad` ships as package data.
- Collects the Qt platform plugin (`qwindows.dll`), the Qt Multimedia backend
  (`ffmpegmediaplugin.dll`), and other needed Qt plugins explicitly, so the app starts
  and captures/plays audio correctly.
- `console=False`, so no terminal window opens next to the GUI.
- Uses the app icon in `resources/wyomingchat.ico`.

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
- Microphone gate threshold (start speech above a background level)
- Microphone boost (1x-10x gain for quiet microphones)
- One or more playback outputs for synthesized audio
- Virtual microphone routing: PipeWire loopback (Linux) or virtual audio cable (Windows)
- PipeWire virtual microphone node name and description (Linux only)
- Streaming synthesis (default on): completed sentences are synthesized while you are still
  speaking the rest of the utterance, then played back in order after you stop

## PipeWire virtual microphone (Linux)

The app can write a PipeWire loopback configuration that creates two linked virtual
devices:

- a **virtual sink** that Wyoming Voice Bridge can target for TTS playback
- a **virtual source** that desktop applications can choose as a microphone

The virtual microphone path is intended to carry only Wyoming Voice Bridge's TTS output.
It does not forward the user's live microphone audio into that virtual source.

In the UI:

1. Enable the virtual microphone section.
2. Choose a PipeWire node name and description.
3. Click **Write PipeWire Config**.
4. Restart PipeWire services:

```bash
systemctl --user restart pipewire pipewire-pulse wireplumber
```

5. Reopen the app and refresh devices.
6. Select the created **virtual sink/output** in **Playback outputs** if you want TTS
   audio routed into the virtual microphone path.
7. In other applications, choose the created **virtual source/microphone** as the input
   device.

**Windows note:** the managed PipeWire virtual microphone requires PipeWire and is only available
on Linux. On Windows, use the **Virtual Microphone** section with a virtual audio cable instead
(see below).

## Virtual microphone on Windows (virtual audio cable)

Windows cannot create virtual audio devices programmatically - that requires a signed kernel
driver - so the app uses a **virtual audio cable** instead. A virtual audio cable installs a
pair of endpoints that reproduce the PipeWire loopback topology:

- a **playback endpoint** (for example `CABLE Input (VB-Audio Virtual Cable)`) that the app
  plays TTS into
- a **microphone endpoint** (for example `CABLE Output (VB-Audio Virtual Cable)`) that other
  applications can select as their microphone

The virtual microphone carries only the app's synthesized TTS output, never the user's live
microphone audio.

Setup:

1. Install a free virtual audio cable once. Recommended: **VB-CABLE** (free donationware -
   the driver downloads directly from vb-audio.com/Cable; the ~$5 webshop price is a
   voluntary donation that also unlocks extra cables) or **Voicemeeter** (free,
   vb-audio.com/Voicemeeter). The app also lets you pick any output device manually if your
   cable is not auto-detected.
2. Open the app's **Virtual Microphone** section, enable it, and pick the cable's playback
   endpoint (or leave **Auto-detect first installed cable** selected).
3. Click **Save Configuration**.
4. In other applications (video calls, recording software, games), select the cable's
   **microphone** endpoint as the input device - for example `CABLE Output` for VB-CABLE.

When enabled, the selected cable playback endpoint is automatically added to TTS routing on
top of your normal speaker outputs, so you hear responses and other apps receive them as a
microphone at the same time.

## Notes and limitations

- The app currently uses a conservative Silero-based voice activity detector with
  buffering, probability thresholds, and PCM normalization to reduce false triggers and
  clipped speech.
- Qt Multimedia capture and playback are used for audio I/O on both platforms. On Linux,
  PipeWire metadata discovery is handled through `pw-dump` when available.
- Virtual microphone creation currently writes a PipeWire loopback configuration but does
  not restart PipeWire automatically.
- The application is intended for local Wyoming services and desktop environments.
