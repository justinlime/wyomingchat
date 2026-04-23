# Wyoming Voice Bridge — Project Draft

## Overview

Wyoming Voice Bridge is a lightweight, open-source Linux desktop application that keeps an
always-on local microphone monitor running, detects speech automatically, and bridges that speech
to locally hosted Wyoming-compatible STT and TTS services. The application is written in Python,
uses Qt for the desktop interface, and is designed for modern Linux desktops with PipeWire.

The project is **Nix-first** for local execution and testing. The primary way to run the project is
through `flake.nix`, using commands such as `nix run .#`, `nix build .#`, and
`nix profile install .#`.

---

## Purpose

The goal of Wyoming Voice Bridge is to provide a simple local voice interface that:

- Continuously monitors a selected microphone without sending every sound to STT
- Uses local voice activity detection to decide when a real utterance has started and ended
- Streams detected speech to a local Wyoming STT service
- Sends the resulting transcript to a local Wyoming TTS service
- Plays the generated response through user-selected outputs and optionally into a PipeWire-backed virtual microphone path

All processing is intended to stay on the user's own hardware or local network.

---

## How It Works (Non-Technical Summary)

When the application is running, it keeps the selected microphone open and listens locally for
speech activity. Background sounds should be ignored unless they look enough like real speech to
cross the voice detection thresholds.

When speech is detected while the app is idle, the application starts a Wyoming STT session and
streams microphone audio to it in real time. A short amount of buffered audio from just before the
detection point is also included so the beginning of the utterance is less likely to be clipped.

Once the application decides the user has stopped speaking, it finalizes the STT stream, receives
the transcript, and forwards that text to a Wyoming TTS service. The generated audio is then
played back immediately through the configured output devices.

While a transcription or TTS response is already in progress, the application does not start a new
STT session. Only one voice interaction should be active at a time.

---

## Key Features

- **Always-on microphone monitoring** — The app keeps a microphone stream open while running so it
  can react quickly when speech begins.

- **Voice activity detection (VAD)** — Local speech detection is used to avoid sending random room
  noise to STT and to reduce clipped speech at the start or end of an utterance.

- **Single active interaction** — The application should allow only one STT/TTS interaction at a
  time so overlapping transcription and playback pipelines do not compete with each other.

- **Local STT integration** — Streams microphone audio to Wyoming-compatible speech-to-text
  services and receives transcript updates back from them.

- **Local TTS integration** — Sends transcripts to Wyoming-compatible text-to-speech services and
  plays streamed audio responses locally.

- **Flexible audio routing** — Uses Qt audio I/O together with PipeWire-aware device discovery so
  users can choose microphone and playback devices.

- **PipeWire virtual microphone support** — Can manage a PipeWire loopback configuration that
  exposes a playback sink for the app and a linked source that other applications can select as a
  microphone. The virtual microphone should carry the app's TTS output only, not the user's live
  microphone audio.

- **Simple configuration UI** — A Qt-based desktop interface lets users configure service
  endpoints, audio routing, and virtual microphone settings without editing files by hand.

---

## Configuration Options

Through the graphical interface, users can set:

- The network address and port for the STT service
- The network address and port for the TTS service
- Which microphone to use for always-on monitoring
- Which audio output device(s) to use for playback
- The PipeWire node name and description for the managed virtual microphone sink

---

## Design Philosophy

Wyoming Voice Bridge is built around a few guiding principles:

1. **Local first.** Voice data should remain on the user's own machine or local network.
2. **Simple operation.** The app should feel automatic and responsive without requiring push-to-talk.
3. **Composability.** By speaking the Wyoming protocol, the app should work with many local STT and
   TTS backends.
4. **Practical Linux integration.** The app should fit naturally into PipeWire-based Linux desktop
   environments and support useful routing setups such as virtual microphones.
5. **Nix-first reproducibility.** The main supported way to run and test the project should remain
   the Nix flake so developers and testers get a reproducible environment.

---

## Protocol

This project uses the **Wyoming protocol** — an open, lightweight protocol designed specifically
for local voice AI services. It is used throughout the Rhasspy and Home Assistant voice ecosystem,
which makes Wyoming Voice Bridge naturally compatible with a wide range of existing self-hosted
speech services.

---

## Project Status

The project is still in an early implementation phase. The main active development goals are:

- refining the always-on open-microphone workflow
- improving voice activity detection behavior
- keeping the STT/TTS pipeline strictly single-session
- expanding PipeWire routing support, including virtual microphone workflows
- keeping the Nix flake as the primary run and test path

Contributions, feedback, and ideas are welcome.
