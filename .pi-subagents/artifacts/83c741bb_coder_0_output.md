===============================================================================
READ-ONLY CODE REVIEW — Inter-sentence TTS pause regression ("streaming synthesis")
Repo: /home/justinlime/code/wyomingchat   (no files were modified)
===============================================================================

SCOPE READ
  controller.py (sentence-unit chaining, playback dispatch)
  audio.py       (MultiOutputPlayer drain/estimate logic)
  streaming.py   (transcript chunker)
  clients.py     (STT/TTS sessions, timeout strings)
  config.py / ui.py / tests referenced for defaults and intent.

------------------------------------------------------------------------------
(1) WHERE THE INTER-SENTENCE GAP COMES FROM — chaining logic
------------------------------------------------------------------------------

The controller synthesizes each sentence as a separate TextToSpeechSession
(controller.py:653-669, fired from _apply_partial_transcript controller.py:588-593,
_handle_audio_chunk controller.py:529-532, and _handle_stt_complete
controller.py:635-639) and plays each unit through a fresh MultiOutputPlayer
stream. Every boundary between unit N and unit N+1 pays this full chain:

  last audio of N -> drain timer margin -> stop_stream() (tear down sinks)
  -> playback_finished signal -> _handle_playback_finished -> start_stream()
  (new QAudioSink objects) -> write buffered audio -> (maybe) finish_stream()

Delay contributors, quantified:

  a) Drain-timer margin (FIXED ~100ms minimum per sentence)
     audio.py:28-33  _drain_delay_for() returns max(80, int(remaining_ms) + 100).
     The +100ms margin and 80ms floor are paid at EVERY sentence boundary
     because finish_stream() -> _schedule_drain_stop() (audio.py:592-597) runs
     per sentence (controller.py:753-756, 827-828).

  b) Sink teardown + restart (typically ~10-100ms, more if the device
     suspended during the gap)
     audio.py:518-527 stop_stream() stops and deleteLater()s every QAudioSink;
     audio.py:417-457 start_stream() creates new sinks and calls sink.start().
     On PipeWire/PulseAudio, sink start latency and any device
     suspend/resume latency add here. _handle_playback_finished
     (controller.py:838-849) -> _maybe_start_playback (controller.py:789-836)
     does this once per sentence.

  c) Wait-for-next-unit-format (THE "up to seconds" contributor)
     controller.py:804-807: _maybe_start_playback() returns early when the next
     unit's format_spec is None ("wait for the sentence's audio-start event").
     TTS sessions are opened CONCURRENTLY (one per sentence), but many Wyoming
     TTS servers (wyoming-piper et al.) serialize synthesize requests and/or
     pay per-request model warm-up. Sentence N+1's audio-start then arrives
     only after N's request finishes. If N's playback completes before N+1's
     synthesis, the gap equals N+1's remaining synthesis time: seconds.

  d) Qt event-loop + signal dispatch between playback_finished and the next
     start_stream: a few ms.

  e) BUG - duplicate tail synthesis adds a whole extra unit + extra boundary:
     see below (streaming.py:64-67 finish() trailing is not content-deduped;
     finish() is called twice: controller.py:530 and controller.py:636).

  f) Per-sentence re-scheduling of the drain: the estimate used by
     _schedule_drain_stop is frozen at the last write_audio (see (2)), so the
     +100ms margin is applied to a slightly stale value. Small (<20ms), but
     per-boundary.

Summary: with a concurrent-capable server the gap is ~110-250ms per boundary
(margin + sink restart + dispatch). With a serializing server, the gap becomes
the next sentence's remaining synthesis latency — the "up to seconds" the user
reports. The duplicate-tail bug (e) turns the final un-punctuated sentence into
TWO units, adding a full extra boundary plus a full duplicate playback.

------------------------------------------------------------------------------
(2) _estimated_buffer_ms vs _sink_buffered_ms — double-count / timing analysis
------------------------------------------------------------------------------

NO sum double-count is present in the current code. _drain_delay_for
(audio.py:28-33) uses max(estimated, sink_buffered) + 100ms, not their sum, and
tests explicitly pin this (tests/test_audio.py:71-93, e.g.
_drain_delay_for(500,500) == 600). The docstring at audio.py:24-27 records that
the sum form was already removed.

Residual accounting inaccuracies (all minor, all per-boundary):

  a) Stale estimate: _estimated_buffer_ms decays only inside write_audio
     (audio.py:479-485), keyed off _last_estimate_update. Between the final
     write_audio and _schedule_drain_stop (audio.py:592-597) the estimate is
     NOT decremented, so the drain delay is overstated by that interval
     (typically <20ms) and the +100ms margin is applied on top. Overstated =
     slightly LONGER silence at each boundary.

  b) The wall-clock estimate assumes the sink consumes at exactly real time
     from byte zero and ignores Qt sink priming/suspension, so for bursty TTS
     delivery the estimate can undercount; the max() with _sink_buffered_ms and
     the +100ms margin are what actually protect the tail. _sink_buffered_ms
     (audio.py:602-612) is computed correctly (bufferSize - bytesFree).

  c) The 80ms floor + 100ms margin are per-boundary fixed overhead; they only
     matter because the player is stopped/restarted per sentence. Remove the
     chaining (fix 2 below) and this whole accounting becomes end-of-utterance
     only.

Conclusion for (2): no double-count bug; a minor stale-estimate inflation of
the drain margin at each boundary. Not the root cause of "seconds" pauses.

------------------------------------------------------------------------------
(3) CAN CONCURRENT PER-SENTENCE TTS SESSIONS TIME OUT THE STT SERVICE?
------------------------------------------------------------------------------

Exact timeout strings in clients.py:
  - clients.py:140-145 connect(timeout=10.0): socket timeout = 10.0s for
    connect AND every subsequent recv/send.
  - clients.py:384-387  "STT send failed: timed out"   (OSError from sendall)
  - clients.py:399      _connected.wait(timeout=10.0)  (silent - no error msg)
  - clients.py:429-431  "STT receive failed after audio-stop: timed out"
  - clients.py:432-433  "STT receive failed: timed out"

Direct client-side interference: NO. Each TTS session is a separate
thread/connection (clients.py:631-686); blocking socket I/O releases the GIL,
and Qt audio-sink writes are non-blocking (short writes go to pending_bytes,
audio.py:536-563), so TTS traffic cannot starve the STT writer/reader threads
or block the GUI thread for 10s.

Indirect exposure (real, and made worse by streaming synthesis):
  a) If STT and TTS run on the SAME Wyoming server (or share a GPU/thread
     pool), per-sentence synthesize requests are serialized server-side and
     can delay STT responses past the hard 10s socket timeout.
  b) The STT reader uses the 10s timeout on EVERY receive_event
     (clients.py:140-145 + 407-417). Long utterances where the STT server
     emits no partials for >10s trip "STT receive failed: timed out" even
     with zero TTS load (pre-existing, but streaming synthesis raises the
     odds because TTS work is now in flight while STT is still open).
  c) Blast radius: any STT error -> _handle_stt_error (controller.py:860-864)
     -> _handle_error (controller.py:871-881) -> _abort_current_activity
     (controller.py:432-469) which closes ALL _synthesis_sessions and calls
     _player.stop_stream(). With streaming synthesis, an STT timeout now
     destroys in-flight/queued TTS that the pre-feature design would not have
     started yet, silently killing the whole reply.
  d) The silent _connected.wait(10.0) path (clients.py:399-401) exits the
     reader without an error; the writer may still connect later and send into
     a socket with no reader, then fail with "STT send failed: ...", again
     aborting everything.

So: the TTS sessions do not directly cause STT timeouts, but the feature makes
a mid-utterance STT timeout much more damaging, and shared-server setups make
the 10s timeout much more likely to trip.

------------------------------------------------------------------------------
(4) MINIMAL SAFE FIX — restore single-continuous-playback
------------------------------------------------------------------------------

Option A (safest, smallest, exactly restores pre-feature behavior):
  Default streaming_synthesis to False (config.py:329 currently True;
  ui.py:216 checkbox + config.py:391 coerce default also True). With the flag
  off, _handle_stt_complete (controller.py:635-639) takes the single-shot
  branch: one _start_sentence_synthesis(final_text) -> one TextToSpeechSession
  -> one MultiOutputPlayer stream -> one finish_stream(). Zero inter-sentence
  boundaries by construction. This is the minimal, low-risk change.

Option B (keep the feature, remove the gaps):
  Stop chaining player streams. Start the stream once (first unit), append each
  subsequent unit's audio into the SAME stream as it becomes available, and
  call finish_stream() only after the LAST unit completes. Concretely:
    - _maybe_start_playback should not stop/restart when a current stream is
      already active (guard on player state, not just _current_unit_index);
    - _handle_playback_finished should not tear down the player when
      _next_unit_to_play < len(_sentence_units); instead keep the stream open
      and write the next unit's buffered audio into it;
    - drop the per-sentence finish_stream()/drain (controller.py:753-756,
      827-828) in favor of a single end-of-reply drain.
  This eliminates contributors (a), (b), (d) and most of (c).

Both options should also include the duplicate-tail fix (P0) below.

------------------------------------------------------------------------------
PRIORITIZED CONCRETE FIXES
------------------------------------------------------------------------------

[P0] streaming.py:64-67 — finish() double-commits the trailing (un-bounded)
     sentence. finish() is invoked twice per utterance (controller.py:530 at
     VAD speech-end, controller.py:636 at STT complete). For un-punctuated STT
     output the ENTIRE utterance is "trailing", and the second finish() returns
     it again (trailing is appended unconditionally, unlike the bounded
     sentences which are content-key deduped). Result: the tail sentence is
     synthesized TWICE and played twice (whole reply repeats), with an extra
     drain+restart gap in the middle. Fix: skip trailing when its content key
     already matches the last committed sentence (compare
     _content_key(trailing) against the tail of _committed).

[P0] controller.py:789-836 + audio.py:417-457,499-527 — per-sentence
     player chaining is the structural cause of boundary gaps. Apply Option A
     (config.py:329 default False) for the immediate regression fix, and/or
     Option B (one continuous stream across units) to keep the feature without
     gaps.

[P1] controller.py:804-807 — "wait for audio-start" turns TTS-server
     serialization into seconds of silence. If streaming synthesis is kept,
     serialize synthesis client-side (issue the next sentence's request only
     after the previous unit's audio-start arrives, or reuse one
     connection/queue) so the next unit's format is available before the
     previous unit finishes playing.

[P1] clients.py:140-145 (10s socket timeout) + controller.py:860-881
     (STT error aborts all TTS) — a mid-utterance STT timeout now kills the
     entire reply. Raise the timeout (e.g., 30s) or make it configurable;
     consider not treating a read timeout as terminal while the utterance is
     still producing partials; and do not abort already-queued TTS playback
     when the STT error arrives after speech-end.

[P2] audio.py:479-485,592-597 — drain estimate is frozen at last write; decay
     it in _schedule_drain_stop or cap the margin. Only matters while chaining
     exists (fix P0b removes it). No sum double-count present (confirmed by
     tests/test_audio.py:71-93).

------------------------------------------------------------------------------
KEY FILE:LINE REFERENCES
------------------------------------------------------------------------------
  controller.py:529-532  tail synthesis at speech-end (finish #1)
  controller.py:588-593  per-sentence synthesis from partials
  controller.py:635-639  tail synthesis at STT complete (finish #2)
  controller.py:653-669  _start_sentence_synthesis (one TTS session per unit)
  controller.py:720-730  _handle_sentence_audio_start
  controller.py:732-746  _handle_sentence_audio_chunk (buffers non-current units)
  controller.py:749-761  _handle_sentence_audio_complete (per-unit finish_stream)
  controller.py:789-836  _maybe_start_playback (per-unit start_stream;
                         804-807 format wait)
  controller.py:838-849  _handle_playback_finished (chains next unit)
  controller.py:432-469  _abort_current_activity (kills TTS on any STT error)
  controller.py:860-881  _handle_stt_error -> _handle_error
  audio.py:28-33        _drain_delay_for (max + 100ms margin, 80ms floor)
  audio.py:417-457      start_stream (stop_stream + new QAudioSink per unit)
  audio.py:475-493      write_audio (estimate accounting)
  audio.py:499-516      finish_stream (per-unit drain scheduling)
  audio.py:518-527      stop_stream (teardown + playback_finished)
  audio.py:592-597      _schedule_drain_stop
  audio.py:602-612      _sink_buffered_ms (correct: bufferSize - bytesFree)
  streaming.py:64-67    finish() trailing not content-deduped (duplicate bug)
  streaming.py:26-38    split_completed_sentences (boundary rules)
  clients.py:140-145    10.0s socket timeout (connect + all I/O)
  clients.py:384-387    "STT send failed: timed out"
  clients.py:399        _connected.wait(timeout=10.0) (silent)
  clients.py:429-431    "STT receive failed after audio-stop: timed out"
  clients.py:432-433    "STT receive failed: timed out"
  config.py:329         streaming_synthesis default True
  tests/test_audio.py:71-93  drain-delay max() behavior pinned by tests
===============================================================================