TTS STREAMING PLAYBACK REVIEW — wyomingchat (read-only; no files modified)
==========================================================================
Scope: src/wyomingchat/clients.py, wyoming_protocol.py, controller.py, audio.py
Bug report: "TTS audio only plays after the final chunk is received, instead of
playing each chunk as it arrives."

Findings summary
----------------
The Wyoming protocol reader and framing are CLEAN: each audio-chunk event is
decoded and its callback invoked immediately per event, with no payload
accumulation and no deferral until audio-stop. PySide6 queued-signal delivery
preserves order (audio-start before chunks, chunks in order). The client mirrors
server pacing exactly (verified empirically over a real TCP loopback).

The reported symptom therefore does NOT originate in the reader or the framing.
It is caused by two genuine client-side weaknesses that can produce an
"all-at-the-end" burst:

  (A) Unbounded queued-signal accumulation: the tts-reader thread emits a signal
      per chunk with no backpressure; when the GUI thread is busy, every chunk
      piles up as a pending QMetaCallEvent and is delivered in a single burst
      the moment the GUI event loop frees up. If the GUI thread is busy for the
      whole TTS download, playback starts only after the burst (= "plays only
      after the final chunk is received"). [severity: medium]
  (B) Silent chunk drop at stream start: chunks are passed unconditionally to
      MultiOutputPlayer.write_audio, which returns 0 (dropping the chunk) when
      start_stream has not run yet. Ordering normally prevents this, but the
      drop path is a latent data-loss bug. [severity: medium]

If the Wyoming TTS server itself buffers the full synthesis and sends all
audio-chunk events at the end, the client cannot fix that; it already reflects
server pacing exactly.

Answers to the five review questions
------------------------------------
(1) Per-event callback delivery?
    YES — the reader invokes callbacks immediately per event.
    TextToSpeechSession._read_loop (clients.py:634-677) loops on
    receive_event() (clients.py:647), which decodes exactly one event, and
    invokes _on_audio_chunk(event.payload) at clients.py:666-668 the instant an
    audio-chunk event is decoded. Nothing is deferred until audio-stop
    (clients.py:670). Socket reads block only while waiting for the *next* event
    on the wire; they never accumulate events.
    Empirically verified with a real loopback server (see commandsRun): with
    chunks paced 0.2 s apart, callbacks arrived at 0.200/0.401/0.601/0.801/
    1.001 s; with chunks blasted back-to-back, callbacks arrived in one burst
    with 0.0 s gaps — i.e. the client exactly mirrors server pacing.

(2) Per-event payload buffering in decode_event/read_exactly?
    NO. decode_event (wyoming_protocol.py:65-92) reads exactly one header line
    via readline() (line 69), then exactly data_length bytes (line 84) and
    exactly payload_length bytes (line 89) via read_exactly (lines 95-111),
    which loops reader.read(length - len(buffer)) (line 101) until the exact
    count is met. Each call returns one complete, independently framed event.
    Leftover bytes of a pipelined next event remain in the socket makefile's
    internal buffer (created at clients.py:146) and are consumed by the next
    decode_event call — events are never merged or accumulated.

(3) Queued-signal reorder/delay; audio-start before chunks?
    Order: GUARANTEED. Delay: POSSIBLE, and is the burst mechanism above.
    The lambdas at controller.py:613-614 emit from the "tts-reader" thread while
    BridgeController lives in the GUI thread, so connections
    (controller.py:148-149) resolve to QueuedConnection. Qt delivers queued
    calls posted from the same thread to the same receiver in FIFO order;
    audio-start is emitted at clients.py:656-663 before the first chunk at
    clients.py:666-668, so audio-start is delivered before chunks and chunks are
    never reordered. Empirically verified with PySide6: received order was
    start, chunk x5, complete, in order.
    Delay: with the GUI thread blocked, all queued chunk signals are delivered
    back-to-back (0.0 s gaps) when the loop unblocks — verified empirically:
    with the GUI thread blocked 1 s, all 5 chunk slots ran in a burst 1 s after
    emission. This is exactly the reported "only plays after the final chunk"
    symptom whenever the GUI thread is busy for the duration of the download.

(4) Reader thread starvation?
    NO starvation path in the TTS client. TTS uses a single reader thread
    (clients.py:634); unlike STT (clients.py:396) there is no concurrent writer
    thread. sendall is called once before the read loop (clients.py:643-647) and
    the send lock in WyomingTcpConnection.send_event (clients.py:151-157) is
    uncontended. The GIL is released during blocking socket reads, so the GUI
    thread is not starved either. The reader cannot let chunks accumulate
    server-side; it reads as fast as the server sends. The actual risk is the
    inverse: the reader runs AHEAD of the GUI (no backpressure), queuing an
    unbounded number of chunk signals into the GUI event loop.

(5) Minimal fix to guarantee per-chunk streaming playback
    (i)  Stop dropping pre-start chunks: in _handle_tts_audio_chunk
         (controller.py:695-705), when the player has no active outputs yet
         (audio.py:475-478 returns 0 silently), append the chunk to a pending
         buffer instead of dropping it, and flush that buffer in
         _handle_tts_audio_start (controller.py:667-693) immediately after
         start_stream. This removes the silent-drop hazard and guarantees no
         audio is lost even if signal ordering is ever violated.
    (ii) Add bounded backpressure between the tts-reader thread and the GUI so
         chunks cannot pile up into an end-of-stream burst: simplest minimal
         form is a per-chunk acknowledgement — have the on_audio_chunk lambda
         (controller.py:614) make the reader wait on a threading.Event that
         _handle_tts_audio_chunk sets after write_audio returns. This paces
         socket reads to GUI consumption, so any accumulation is pushed back to
         the server via TCP backpressure and chunks are written to the sink
         incrementally instead of in a burst.
    (iii) If the TTS server itself buffers the full synthesis and sends all
         audio-chunk events at the end, no client change can make it stream; the
         client already mirrors server pacing exactly (verified). The fix then
         belongs server-side (or a streaming-capable Wyoming TTS backend).

Severity assessment
-------------------
- wyoming_protocol framing + TTS read loop: no defect (verified clean).
- controller.py:695-705 + audio.py:475-478 chunk-before-start silent drop:
  latent data-loss bug (medium) — normally masked by FIFO ordering.
- controller.py:613-614 + clients.py:666-668 unbounded queued-signal burst with
  no backpressure: matches the reported symptom whenever the GUI event loop is
  busy during the TTS download (medium).
- Server-side pacing: outside the client's control; reflected as-is.

Verification performed (all in /tmp, no repo files modified)
------------------------------------------------------------
- /tmp/wyoming_chunk_timing_check.py: real TCP loopback server + real
  WyomingTcpConnection/TextToSpeechSession. Paced server -> callbacks paced;
  blast server -> callbacks burst. Proves per-event delivery, no client
  accumulation.
- /tmp/qt_signal_order_check.py: PySide6 6.11 queued signals from a plain Python
  thread: FIFO order preserved (start, chunk x5, complete).
- /tmp/qt_burst_check.py: with the GUI thread blocked, queued chunk signals are
  delivered in a 0.0-gap burst when the loop unblocks — the reported mechanism.