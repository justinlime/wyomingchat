READ-ONLY CODE REVIEW — "speech to text timeouts a lot now"
Repo: /home/justinlime/code/wyomingchat
Files examined: src/wyomingchat/clients.py, src/wyomingchat/controller.py,
                src/wyomingchat/streaming.py, src/wyomingchat/vad.py,
                src/wyomingchat/audio.py, src/wyomingchat/constants.py,
                src/wyomingchat/config.py, src/wyomingchat/wyoming_protocol.py,
                src/wyomingchat/ui.py, tests/test_clients.py
No files were modified. Tests run: 12 passed (test_clients.py, test_wyoming_protocol.py).

================================================================================
EXECUTIVE SUMMARY
================================================================================

The client architecture puts a FIXED 10-second socket timeout on every single
blocking network operation of the STT session (connect, each readline, each
sendall), and a separate 10-second budget on the reader thread's wait-for-connect.
The recent changes (per-sentence streaming TTS, stop-time tail dispatch, 2.5s
stop silence, 600ms pre-roll) all push the STT server's per-utterance processing
later and longer while simultaneously opening N concurrent TTS connections
during the STT session (including at the exact moment STT finalization begins).
Any server-side stall >10s — most plausibly CPU/queue contention with the
concurrent TTS sessions on the same host, or simply a long utterance finalizing
on a slow machine — surfaces as a user-visible STT timeout. In addition there is
a genuine race in the reader/writer handshake that can produce a spurious
"STT send failed: [Errno 9] Bad file descriptor" timeout even when the server is
healthy, and a per-utterance resource leak: TTS sessions still in flight are
discarded without close() when the next utterance starts.

================================================================================
(1) EVERY ERROR STRING IN clients.py THAT CAN SURFACE AS AN "STT TIMEOUT"
================================================================================

All STT socket timeouts come from the 10.0 default passed to connect()
(clients.py:140) → socket.create_connection(..., timeout=10.0) (clients.py:143)
and socket.settimeout(10.0) (clients.py:144). socket.timeout is a subclass of
OSError, so every one of the OSError handlers below catches it. In Python 3.10+
the message text is "timed out".

A. "STT send failed: {exc}" — clients.py:387 (from SpeechToTextSession._write_loop, clients.py:361-392)
   Triggered when:
   - connect() (clients.py:368) raises. socket.create_connection blocks up to
     10s on the TCP handshake; if the host does not complete it, it raises
     socket.timeout → "STT send failed: timed out". Also ConnectionRefused /
     gaierror (DNS, not bounded by the 10s) / ConnectionReset.
   - send_event() → socket.sendall (clients.py:383) raises when the server stops
     reading and the kernel send buffer fills for >10s → "STT send failed:
     timed out", or BrokenPipe/ConnectionReset if the server closed.
   - RACE (see Q2): the writer finishes connecting after the reader already gave
     up and closed the shared socket → sendall on the closed fd raises
     OSError "[Errno 9] Bad file descriptor" → "STT send failed: [Errno 9] Bad
     file descriptor". This is a spurious "timeout" with a healthy server.

B. "STT receive failed: {exc}" — clients.py:439 (from _read_loop, clients.py:395-445)
   Triggered when _finish_requested is NOT set and receive_event() (clients.py:404
   → decode_event → reader.readline(), clients.py:89/172) blocks for >10s with no
   data, or the read raises EOF/OSError mid-stream. "STT receive failed: timed out"
   is the classic "speech to text timeout" the user sees. The server being silent
   >10s can be caused by (a) the server's transcription queue stalling under CPU
   load from concurrent TTS synthesis, (b) a long utterance finalizing slowly,
   or (c) the server having its own per-session inactivity timeout.

C. "STT receive failed after audio-stop: {exc}" — clients.py:434-435
   Triggered when _finish_requested IS set (audio-stop already sent, clients.py:279-291)
   and the server takes >10s to emit the final transcript (or close). The fallback
   _handle_missing_final_after_finish (clients.py:345-356) then:
     - if partial chunks exist → uses "".join(partials) as the final transcript,
       NO error shown — a SILENT truncation that looks like STT "giving up";
     - if no partials (short utterance) → reports the error verbatim:
       "STT receive failed after audio-stop: timed out".
   With the 2.5s stop silence, finalization happens after a long utterance; a slow
   finalize (>10s) hits this exact path.

D. "STT connection closed before a final transcript was received" — clients.py:410
   EOF (receive_event returns None) AFTER audio-stop with no final transcript.
   Same fallback as C: partials → silent truncation, else this error surfaces.
   Server-side session timeouts (server closes instead of sending final) produce
   this.

E. "STT connection closed before transcription completed" — clients.py:411
   EOF while still streaming (before finish) — server crashed, rejected the
   audio stream, or enforced its own max-utterance limit.

F. Non-STT strings that also surface in the UI during an utterance (TTS/voice):
   - "TTS receive failed: {exc}" — clients.py:656 (TextToSpeechSession._read_loop).
     "TTS receive failed: timed out" after 10s of no audio from the TTS server.
   - "TTS voice query failed: {exc}" — clients.py:540.
   - "TTS voice query completed without an info response" — clients.py:538.
   Controller-level: "Failed to start transcription: {exc}" (controller.py:569),
   "Failed to start synthesis: {exc}" (controller.py:671).

Note the timeout is PER BLOCKING OPERATION, not a total session budget — a server
that is merely slow (not dead) for >10s at any single point triggers it. There is
no configurable STT timeout anywhere (constants.py/config.py have no such knob).

================================================================================
(2) CAN A PREVIOUS STT SESSION'S THREADS STILL BE BLOCKED WHEN A NEW SESSION
    STARTS, AND WHAT HAPPENS?
================================================================================

YES — the writer thread can stay blocked for up to 10s, and the reader can too.

- socket.create_connection (clients.py:143) is NOT interruptible via
  WyomingTcpConnection.close() (clients.py:195-210): during the connect the
  socket is local to the socket module, so closing self._socket (which is None
  at that moment) does nothing. SpeechToTextSession.close() (clients.py:293-307)
  sets _completed and closes the connection, and wait_closed(1.0)
  (clients.py:308-316) joins each thread for at most 1s — so the controller
  proceeds with the old writer thread still inside connect() for up to 10 more
  seconds. Both the old writer AND the old reader (blocked on
  self._connected.wait(timeout=10.0), clients.py:399 — close() never sets
  _connected, so the reader cannot be woken early) linger for up to 10s.

- What happens when a new session starts: _start_stt_session
  (controller.py:536-574) creates a brand-new SpeechToTextSession and starts its
  own writer/reader threads. The stale session's callbacks are generation-filtered
  (controller.py:622-633 _handle_stt_error, controller.py:621-650
  _handle_stt_complete check `generation != self._stt_generation`), so the stale
  error is suppressed and no bogus error is shown — but the old threads and an
  in-flight TCP connect coexist with the new session. On a slow/flaky server,
  several aborted utterances can each leave a 10s-stuck connect running
  concurrently, stacking connections against the server.

- Silent-return race in _read_loop (clients.py:399-402): the reader's 10s wait
  budget starts at thread spawn, in parallel with the writer's connect(). If the
  connect succeeds late (e.g. DNS took a couple of seconds, or the server accept
  queue is slow — both plausible when TTS sessions are hogging the server) the
  reader may time out its wait, return silently, and in its finally close the
  connection and fire on_complete. _completed is NOT set in this path, so the
  writer, when connect() eventually returns, sees _completed==False, proceeds to
  drain the queue and send_event() on a socket whose read side was closed →
  OSError → "STT send failed: [Errno 9] Bad file descriptor" (clients.py:387).
  Net effect: the session fails as a "timeout" even though the server accepted
  the connection fine. This is a genuine concurrency bug, not just load.

================================================================================
(3) DOES STARTING N CONCURRENT TTS SESSIONS WHILE STT IS STILL FINALIZING DELAY
    OR STARVE THE STT SOCKET?
================================================================================

YES — indirectly, and the recent changes maximize the overlap.

Per-utterance connection count: 1 STT connection + one new TextToSpeechSession
(thread + TCP connection) per confirmed sentence. Sessions are spawned from
three places, all during the STT session:
  - _apply_partial_transcript as partials confirm sentences (controller.py:593,
    handler starts at controller.py:575-600);
  - the stop-time tail dispatch — chunker.finish + _start_sentence_synthesis for
    the un-bounded tail — fired in the SAME _handle_audio_chunk that sends
    audio-stop and puts the controller into TRANSCRIBING (controller.py:520-531);
  - _handle_stt_complete for anything still uncommitted (controller.py:636-639).
A 3-sentence utterance therefore runs 4 concurrent connections, and the tail TTS
requests begin at the exact moment the STT server is doing its most expensive
work (finalizing a long utterance).

Mechanisms of starvation:
  1. Server-side CPU/queue contention. If STT and TTS run on the same host
     (typical single wyoming-server deployment — defaults are 127.0.0.1:10300
     for STT and 10200 for TTS, frequently the same binary/process), CPU-bound
     TTS synthesis (kokoro/piper) delays STT partial/final emission. Because the
     STT read has a hard 10s per-read timeout (clients.py:144, 404), a >10s
     stall surfaces as "STT receive failed: timed out". Before streaming
     synthesis, TTS started only AFTER the STT session fully closed
     (old _handle_stt_complete flow), so the STT server never competed with TTS
     work — consistent with "never happened before".
  2. Listen-backlog / accept serialization. If the server handles connections
     serially or with a small pool, 3 TTS connections queued ahead of the STT
     connection stall the STT handshake → writer's connect() times out
     ("STT send failed: timed out", clients.py:387) and/or the reader's
     _connected.wait(10.0) expires (clients.py:399).
  3. The 2.5s stop silence (constants.py:31-34) and 600ms pre-roll
     (constants.py:41, vad.py) lengthen utterances and buffered audio per
     session, lengthening STT finalization — precisely the window where the tail
     TTS dispatch (controller.py:530-531) adds the most load.

So yes: concurrent TTS sessions can starve the STT socket, and the fixed 10s
client-side timeouts convert that starvation into the reported "timeouts".

================================================================================
(4) RESOURCE LEAKS (THREADS, SOCKETS) ACCUMULATING PER UTTERANCE
================================================================================

LEAK 1 — HIGH: In-flight TTS sessions are discarded without close() when the
next utterance starts. _start_stt_session resets
self._synthesis_sessions = [] and self._sentence_units = []
(controller.py:545-548) with no close()/wait_closed(), unlike
_abort_current_activity which does close+wait each one (controller.py:443-446).
Normally the previous TTS sessions have already completed, but nothing enforces
it: if the TTS server is slow, a sentence session still blocked in receive_event
(clients.py:651, up to 10s) is orphaned with its socket open. Under sustained
speech with a slow TTS server, orphaned TTS connections accumulate with
utterance rate × sentences-per-utterance, adding load that pushes STT over its
10s timeout on later sessions. The orphaned daemon threads do eventually die at
the socket timeout, so it is bounded (≤10s per connection) but compounding.

LEAK 2 — MEDIUM: Stale callbacks from orphaned TTS sessions operate against the
new utterance. _synthesis_aborted is reset to False at the start of the new
session (controller.py:549), so _handle_sentence_audio_chunk
(controller.py:729-742), _handle_sentence_audio_start (controller.py:703-710)
and _handle_sentence_error (controller.py:762-768) from old-session threads are
no longer gated. Old audio keeps getting appended to unreferenced units (wasted
memory/CPU), and _handle_sentence_error can call _handle_error → abort the
CURRENT utterance (controller.py:766-768, 431-450) if all current units are
failed — a cascading failure where an old session's error kills the new
utterance.

LEAK 3 — MEDIUM: STT writer/reader threads linger up to 10s after abort when the
connect is stuck (see Q2). Bounded per session, but on a flaky server each
failed utterance leaves a live connect for up to 10s overlapping the next
utterance's connect.

LEAK 4 — LOW: partial-fallback masking. After any post-finish timeout/EOF with
partials present, the session "completes" with the concatenated partial text
(clients.py:345-356) — silently truncated transcripts that look like STT
"timing out" without an error, making the regression harder to diagnose.

The STT session itself is properly cleaned up on both paths (reader finally
closes the connection and reports complete once, clients.py:439-445; abort
path close()+wait_closed(), controller.py:438-442) — no unbounded STT leak. The
accumulating per-utterance leak is the orphaned TTS connections + stale
callbacks in LEAK 1/2.

================================================================================
FINDINGS SUMMARY (severity / file:line)
================================================================================
- HIGH   clients.py:144,404 — fixed 10s per-read socket timeout on STT turns
         any >10s server stall (incl. TTS-induced load) into a visible timeout.
- HIGH   controller.py:545-548 — next-utterance start drops in-flight TTS
         sessions without close()/wait_closed(); orphaned sockets/threads
         accumulate and degrade later sessions (LEAK 1).
- HIGH   controller.py:520-531 + 593 + 636-639 — N concurrent TTS sessions run
         during the STT session, including the tail dispatch exactly at
         finalization; starves a shared/co-located STT+TTS server past the 10s
         read timeout (Q3).
- MEDIUM clients.py:399-402 + 368-387 — reader give-up / writer late-connect
         race produces spurious "STT send failed: [Errno 9] Bad file descriptor"
         timeouts even when the server is healthy (Q2c).
- MEDIUM clients.py:143,308-316 — close() cannot interrupt an in-progress
         socket.create_connection; wait_closed(1.0) returns with threads stuck
         up to 10s; stacks on slow servers.
- MEDIUM controller.py:549,729-742,762-768 — orphaned TTS callbacks (audio
         chunks, errors) can run against the new utterance and even abort it.
- LOW    clients.py:345-356 — post-finish timeout silently falls back to partial
         text, truncating transcripts with no error shown.
- LOW    clients.py:144 — no configurable STT timeout; the 10s value is hardcoded
         and applied per-blocking-op, so long utterances on slow hardware are
         fragile by design.

Likely fix directions (NOT implemented — read-only review): close+join prior
TTS sessions in _start_stt_session (or only drop sessions that already
completed); make the STT read timeout configurable and larger for the
finalization phase; gate orphaned TTS callbacks by a session/unit generation;
and optionally cap concurrent streaming TTS connections.

================================================================================
VALIDATION
================================================================================
- Ran: .venv/bin/python -m pytest tests/test_clients.py tests/test_wyoming_protocol.py -q
  Result: 12 passed. (Controller tests could not run here: PySide6 import fails
  with "libglib-2.0.so.0: cannot open shared object file" in this environment;
  the nix dev shell lacks pytest.)
- No files were modified; no git operations performed.