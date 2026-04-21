# Wyoming Voice Bridge — Project Draft

## Overview

Wyoming Voice Bridge is a lightweight, open-source desktop application for Linux that brings
together local speech recognition and speech synthesis into a single, easy-to-use tool. Built
with privacy in mind, it communicates exclusively with locally hosted AI services — nothing is
sent to the cloud. The application is written in Python and designed to run natively on modern Linux
desktops using the Wayland display protocol.

---

## Purpose

The core goal of this project is to give users a simple, responsive way to interact with their
own locally hosted voice AI services. Rather than relying on proprietary assistants or cloud
APIs, Wyoming Voice Bridge acts as a bridge between the user's voice and self-hosted speech
services — keeping everything on the user's own hardware.

This makes the tool especially appealing to:

- Privacy-conscious users who want voice interaction without sending data to third parties
- Home automation enthusiasts running local AI stacks (such as Home Assistant with Wyoming add-ons)
- Developers and tinkerers experimenting with local speech AI pipelines
- Accessibility-focused users who want a customizable, offline-capable voice interface

---

## How It Works (Non-Technical Summary)

When the user holds down a designated button, the application begins listening through their
chosen microphone. That audio is streamed in real time to a local Speech-to-Text (STT) service,
which returns transcribed text back as a stream — meaning the application receives results
continuously as the user speaks, rather than waiting until they let go of the button.

That text is then forwarded to a local Text-to-Speech (TTS) service, which streams generated
audio back to the application in real time. Playback can begin as soon as the first audio
arrives, without waiting for the entire response to be produced first.

The entire interaction — from holding the button to hearing the response — is handled locally
and privately.

---

## Key Features

- **Push-to-talk input** — Audio capture only happens while the designated key is held, keeping
  interactions intentional and preventing accidental recording. The chosen key will be registered
  as a global shortcut with the desktop environment via the XDG Global Shortcuts portal — the
  modern standard for system-wide key bindings on Wayland — so the push-to-talk key works even
  when the application window is not in focus.

- **Local STT integration** — Streams microphone audio in real time to any Wyoming-compatible
  speech-to-text service, receiving transcribed text back as it becomes available rather than
  waiting for the full recording to complete.

- **Local TTS integration** — Connects to any Wyoming-compatible text-to-speech service and
  streams the generated audio response back in real time, allowing playback to begin before the
  full response has finished being produced.

- **Flexible audio routing** — Uses PipeWire, the modern Linux audio system, to direct
  microphone input from a chosen device and send audio output to one or more selected playback
  devices.

- **Simple configuration UI** — A clean, minimal desktop interface built with Qt, a mature and
  widely supported GUI framework with first-class Wayland support, lets users configure all
  connection settings and audio devices in one place without editing any configuration files.

- **Wayland-native** — Designed from the ground up to run on modern Linux desktops using the
  Wayland display protocol, without requiring legacy compatibility layers.

---

## Configuration Options

Through the graphical interface, users can set:

- The network address and port for their STT service
- The network address and port for their TTS service
- Which microphone to use for voice input
- Which audio output device(s) to use for playback (multiple selections supported)

These settings are intended to be straightforward enough for non-technical users while remaining
flexible enough for advanced home server setups.

---

## Design Philosophy

Wyoming Voice Bridge is built around a few guiding principles:

1. **Local first.** All processing happens on the user's own hardware or local network. No
   account, no subscription, no data leaving the home.

2. **Simplicity.** The interface should be approachable. Users should be able to get up and
   running with minimal friction.

3. **Composability.** By speaking the Wyoming protocol, this application can work with a
   growing ecosystem of local AI voice services — it isn't locked to any single backend.

4. **Lightweight.** The application itself should have a minimal footprint, acting purely as a
   coordination layer between the user, their audio hardware, and their AI services.

---

## Protocol

This project uses the **Wyoming protocol** — an open, lightweight protocol designed specifically
for local voice AI services. It is the same protocol used by Home Assistant's voice pipeline and
a variety of popular local STT and TTS add-ons, making Wyoming Voice Bridge naturally compatible
with a wide range of existing self-hosted setups.

---

## Project Status

This document represents the initial planning draft for Wyoming Voice Bridge. Development is in
the early stages, with the core architecture and feature set now defined. The next steps involve
establishing the foundational Python codebase — managed with UV, a modern and fast Python
package manager — implementing Wyoming protocol communication, wiring up PipeWire audio, and
building out the Qt configuration interface.

Contributions, feedback, and ideas are welcome as the project takes shape.
