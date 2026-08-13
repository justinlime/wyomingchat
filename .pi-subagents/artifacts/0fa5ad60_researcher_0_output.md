I now have complete, cross-verified evidence from the local wyoming lib, the official protocol docs, the wyoming-piper server, and the Home Assistant client. Here is the full research report.

---

# Wyoming Streaming TTS Wire Format & Client Handshake — Research Findings

## 1. Exact event sequences for streaming synthesis

### Client → Server (in order)
| # | Event type | Data |
|---|---|---|
| 1 | `synthesize-start` | optional `voice` dict, optional `context` dict |
| 2..N | `synthesize-chunk` | `{"text": "..."}` (required) |
| N+1 | `synthesize` | `{"text": "<full accumulated text>", "voice": {...}}` — back-compat, spec-required |
| N+2 | `synthesize-stop` | no data |

### Server → Client (interleaved, then terminal)
- While text chunks are arriving, the server emits, per **completed sentence**: `audio-start` → `audio-chunk` ×M (PCM payload) → `audio-stop`.
- After it receives `synthesize-stop`: final pending sentence audio (`audio-start` → `audio-chunk`×M → `audio-stop`), and then **`synthesize-stopped`** as the very last event (no data).

**Position of `synthesize-stopped`:** it is sent **by the server, to the client**, after the final `audio-stop` and after the client's `synthesize-stop`. It is the terminal signal a client should wait for — **not** `audio-stop` (which may occur multiple times, once per sentence).

Evidence:
- Official protocol docs, local `wyoming-1.8.0.dist-info/METADATA` lines 228–238 (event list) and 391–410 (event flow diagram): `1. → synthesize-start (required); 2. → synthesize-chunk (required); 3. ← audio-start/audio-chunk/audio-stop; 4. → synthesize (backwards compatibility); 5. → synthesize-stop; 6. ← final audio-start/audio-chunk/audio-stop; 7. ← synthesize-stopped`.
- Same flow in rhasspy/wyoming `README.md` (master), "### Text to Speech / Streaming" and "Event Flow → Text to Speech / Streaming".
- Server implementation, wyoming-piper `wyoming_piper/handler.py` (main): `SynthesizeStart` branch sets `is_streaming=True`; `SynthesizeChunk` branch synthesizes each completed sentence via `_handle_synthesize` (which emits `audio-start`/`audio-chunk`/`audio-stop` per sentence); `SynthesizeStop` branch does `_handle_synthesize` for the final sentence, then `await self.write_event(SynthesizeStopped().event())`.
- Client implementation, Home Assistant `homeassistant/components/wyoming/tts.py` `_read_tts_audio`: loops reading events, breaks on `SynthesizeStopped.is_type(event.type)`; it never terminates on `audio-stop` in the streaming path.

**Wording caveat:** the METADATA bullet "5. `synthesize-stopped` - sent back to server after final audio" reads as if client→server, but the diagram in the same doc says `← synthesize-stopped`, and both reference implementations (piper writes it; HA reads it) confirm **server → client**.

## 2. Does the client need to advertise streaming? What is the handshake?

**There is no per-request "streaming" flag and no dedicated handshake event.** The server decides a request is streaming purely from the **first event being `synthesize-start`** rather than `synthesize`. In wyoming-piper, `SynthesizeStart` sets `self.is_streaming = True`, and any later `synthesize` event on that connection is ignored with the comment "only sent for compatibility reasons" (handler.py).

**However, the `describe` → `info` exchange is the capability-discovery handshake and is effectively mandatory for a correct client:**

- `describe` (client) → `info` (server) is listed as required in the protocol docs ("Service Description: 1. → describe (required); 2. ← info (required)").
- The `info` event's `tts[]` array contains `supports_synthesize_streaming: bool` per `TtsProgram` — local `wyoming/info.py` lines 107–114 (`TtsProgram`, `supports_synthesize_streaming: bool = False`). Same in wyoming 1.7.1 (`info.py` lines 113–114).
- Servers set it explicitly:
  - wyoming-piper ≥2.0.0: `supports_synthesize_streaming=(not args.no_streaming)` in `__main__.py` (`_piper_info` / `_omnivoice_info`).
  - wyoming-piper 1.6.x: `supports_synthesize_streaming=args.streaming` (opt-in via `--streaming`).
  - wyoming-piper <1.6.0: streaming did not exist; flag absent → defaults to `False`.
- Home Assistant **gates the whole streaming path on this flag**: `WyomingTtsProvider.async_supports_streaming_input()` returns `self._tts_service.supports_synthesize_streaming` (HA `components/wyoming/tts.py`); HA's base `TextToSpeechEntity` only uses streaming when the provider overrides it (HA `components/tts/entity.py` lines 73–76).

**Consequence of skipping the check:** wyoming-piper started with `--no-streaming` (or 1.6.x without `--streaming`) **silently ignores** `synthesize-start`/`synthesize-chunk`/`synthesize-stop` (`if self.cli_args.no_streaming: return True` in handler.py, and identical `if not self.cli_args.streaming: return True` in v1.6.3) — no audio, no error. A client that sends streaming events without checking the flag will hang forever.

**Where the dispatch lives:** the wyoming library's `wyoming/server.py` is a generic event loop (`AsyncEventHandler.run` reads events and calls `handle_event`); there is **no `ServerTts` base class** in the library, and the `rhasspy/wyoming-server` repo does not exist (404). The canonical server pattern is an `AsyncEventHandler` subclass that dispatches by event type — wyoming-piper's `PiperEventHandler` is the reference implementation.

## 3. Fallback when the server does not advertise `supports_synthesize_streaming`

- **Fall back to single-shot:** accumulate the entire text, send one `synthesize` event with `{"text": ..., "voice": {...}}`, and read `audio-start` → `audio-chunk`×N → `audio-stop` (terminate on `audio-stop`).
- This is exactly what HA does: its base `TextToSpeechEntity.async_stream_tts_audio` default implementation (HA `components/tts/entity.py` lines 101–113) joins all message chunks and calls `async_get_tts_audio` → single-shot `Synthesize`. The Wyoming provider only overrides that when the flag is true.
- Version-skew note for piper: <1.6.0 rejects streaming events entirely (`_LOGGER.warning("Unexpected event: %s", event)` — v1.5.0 handler); 1.6.0–1.6.3 require `--streaming`; ≥2.0.0 has streaming on by default (`--no-streaming` disables); 2.1.1 fixed a streaming bug.
- **Even in streaming mode, still send the back-compat `synthesize` event** (full text) immediately before `synthesize-stop`. The spec marks it required ("Original `synthesize` message must be sent for backwards compatibility"); wyoming-piper ignores it during a stream, but older/other servers may process it as a normal request, and it gives graceful degradation if the server only implements single-shot.

## 4. Exact wire format details

Frame format (local `wyoming/event.py`): one JSON header line followed by optional data bytes and optional binary payload:
```
{"type": "...", "data": {...}, "data_length": <int>, "payload_length": <int>, "version": "1.8.0"}\n
<data_length bytes of JSON, merged over header data>
<payload_length bytes of binary (PCM audio)>
```
(`async_write_event` event.py:112–139; empty data dicts are omitted entirely — so `synthesize-stop` on the wire is just `{"type": "synthesize-stop", "version": "..."}`.)

Event data shapes (local `wyoming/tts.py`):

| Event | Data | Notes |
|---|---|---|
| `synthesize-start` (tts.py:93–121) | `{"voice": {...}, "context": {...}}` (both optional) | `voice` omitted if none; empty `data` if neither |
| `synthesize-chunk` (tts.py:124–140) | `{"text": str}` | required |
| `synthesize-stop` (tts.py:143–156) | none | |
| `synthesize-stopped` (tts.py:159–171) | none | server→client, terminal |
| `synthesize` (tts.py:58–91) | `{"text": str, "voice": {...}}` | back-compat event during stream |

`SynthesizeVoice.to_dict()` (tts.py:31–42) — **name beats language**:
- name set → `{"name": ..., "speaker": ...}` (speaker only if set)
- else language set → `{"language": ...}`
- else `{}`
Quirk in `from_dict` (tts.py:44–55): a `{"language": ...}` dict is parsed into `SynthesizeVoice(name=voice["language"])` — language is stored in `name`.

Audio events (local `wyoming/audio.py`):
- `audio-start` (audio.py:88–119): `{"rate": int, "width": int, "channels": int, "timestamp": int?}`
- `audio-chunk` (audio.py:39–87): same data fields + **payload = raw PCM bytes** (payload_length)
- `audio-stop` (audio.py:120–141): `{"timestamp": int?}`

## 5. Additional client implementation requirements (from the reference clients)

1. **Full duplex required.** wyoming-piper synthesizes sentences as chunks arrive, so server audio events arrive *interleaved* between the client's text chunks. HA runs the writer as a background task (`config_entry.async_create_background_task(self._write_tts_message, ...)`) while the main coroutine reads (`async_stream_tts_audio`). A client that sends all chunks then reads will still work with piper (it buffers), but interleaving is the point of streaming and matches the reference client.
2. **Handle multiple audio streams.** Expect several `audio-start`/…/`audio-stop` groups before `synthesize-stopped`. HA builds its WAV header from the *first* `audio-start` only and thereafter just yields `audio-chunk` payloads, ignoring subsequent `audio-start`s and all `audio-stop`s; it terminates on `synthesize-stopped` (HA `wyoming/tts.py` `_read_tts_audio`).
3. **Writer order:** `SynthesizeStart(voice=...)` → `SynthesizeChunk(text=...)` per incoming chunk (accumulate full text) → `Synthesize(text=full, voice=...)` → `SynthesizeStop()` (HA `_write_tts_message`).

## 6. Local project context (wyomingchat)

- `src/wyomingchat/clients.py:573–668` — `TextToSpeechSession` currently sends a single `synthesize` event (lines 645–648) and terminates on `audio-stop` (lines 661–663). This is why the server's logs show non-streaming "Synthesize".
- `src/wyomingchat/clients.py:470–548` — `TtsVoiceQuerySession` already performs `describe` → `info` (line 536) and parses voices via `parse_tts_voices_from_info` (line 45), which currently ignores `tts[].supports_synthesize_streaming` — the flag is already in the received payload, just not read.
- `src/wyomingchat/clients.py:131+` — `WyomingTcpConnection` is full-duplex capable (send lock + separate reader file object), so a writer thread + reader thread design matches the reference clients.
- `src/wyomingchat/config.py:184–211` — `TtsVoiceConfig.to_request_payload()` builds the `{"name", "language", "speaker"}` voice dict; note the spec/wyoming lib semantics: prefer `name`+`speaker`, or `language` alone (see `SynthesizeVoice.to_dict` above).

---