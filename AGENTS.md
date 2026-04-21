# Wyoming Voice Bridge — Project Draft

## Overview

Wyoming Voice Bridge is a lightweight, open-source desktop application for Linux that brings
together local speech recognition and speech synthesis into a single, easy-to-use tool. Built
with privacy in mind, it communicates exclusively with locally hosted AI services — nothing is
sent to the cloud. The application is written in Go and designed to run natively on modern Linux
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
which transcribes what the user said into text.

That text is then forwarded to a local Text-to-Speech (TTS) service, which generates a spoken
audio response. The application receives that audio and plays it back through whichever speakers
or audio devices the user has selected — with support for routing to multiple outputs
simultaneously if desired.

The entire interaction — from holding the button to hearing the response — is handled locally
and privately.

---

## Key Features

- **Push-to-talk input** — Audio capture only happens while the button is held, keeping
  interactions intentional and preventing accidental recording.

- **Local STT integration** — Connects to any Wyoming-compatible speech-to-text service running
  on the user's network or machine.

- **Local TTS integration** — Connects to any Wyoming-compatible text-to-speech service and
  streams audio responses back to the user in real time.

- **Flexible audio routing** — Uses PipeWire, the modern Linux audio system, to direct
  microphone input from a chosen device and send audio output to one or more selected playback
  devices.

- **Simple configuration UI** — A clean, minimal desktop interface (built with the Gio UI
  library) lets users configure all connection settings and audio devices in one place without
  editing any configuration files.

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
establishing the foundational codebase, implementing Wyoming protocol communication, wiring up
PipeWire audio, and building out the configuration interface.

Contributions, feedback, and ideas are welcome as the project takes shape.
