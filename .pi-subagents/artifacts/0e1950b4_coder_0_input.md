# Task for coder

READ-ONLY code review - do NOT modify any files. Repo: /home/justinlime/code/wyomingchat (Python/PySide6 voice bridge; streams mic to a Wyoming STT server and plays Wyoming TTS audio back).

BUG REPORT: TTS audio now only starts playing AFTER the final chunk arrives from the Wyoming server. Expected: playback begins as soon as the first audio chunk streams in (incremental/streaming playback). This regressed after a refactor.

Read carefully:
- src/wyomingchat/controller.py: _start_tts, _handle_tts_audio_start, _handle_tts_audio_chunk, _handle_tts_complete, _handle_playback_finished, _handle_error, and how Qt signals (_tts_audio_start_received, _tts_audio_chunk_received, _tts_complete_received) are emitted from client threads and connected.
- src/wyomingchat/audio.py MultiOutputPlayer: start_stream, write_audio, _write_to_output, finish_stream, _flush_pending_buffers, _schedule_drain_stop, _drain_delay_for, _sink_buffered_ms, _flush_timer, _drain_timer, _estimated_buffer_ms accounting.
- src/wyomingchat/audio_types.py: AudioFormatSpec fields and defaults.

Answer concretely with file:line references: (1) Is there anything that could cause all chunks to be buffered (pending_bytes) instead of written to the QAudioSink until the end - e.g., the flush timer never starting, write() returning 0, a format mismatch, or _estimated_buffer_ms miscalculation? (2) Does _handle_tts_audio_start reliably run before the first chunk, and what happens if the first audio-chunk arrives before audio-start (signal ordering across threads)? (3) Could the drain timer fire mid-stream and stop the sink (then a later flush plays a burst)? (4) Trace the exact sequence of events from TTS server 'audio-start' to the first audible sample, and identify any step that would delay it until audio-stop. (5) Is there a regression vs the natural expectation of per-chunk playback (check git blame is unavailable - just reason from the code).

Return a concise findings report with prioritized fixes.

---
**Output:**
Write your findings to exactly this path: /tmp/review_playback1.txt
This path is authoritative for this run.
Ignore any other output filename or output path mentioned elsewhere, including output destinations in the base agent prompt, system prompt, or task instructions.

## Acceptance Contract
Acceptance level: attested
Completion is not accepted from prose alone. End with a structured acceptance report.

Criteria:
- criterion-1: Return concrete findings with file paths and severity when applicable

Required evidence: review-findings, residual-risks

Finish with a fenced JSON block tagged `acceptance-report` in this shape:
Use empty arrays when no items apply; array fields contain strings unless object entries are shown.
`criteriaSatisfied[].status` must be exactly one of: satisfied, not-satisfied, not-applicable.
`commandsRun[].result` must be exactly one of: passed, failed, not-run.
`manualNotes` and `notes` are optional strings; an empty string means no note and does not satisfy `manual-notes` evidence.
```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "specific proof"
    }
  ],
  "changedFiles": [
    "src/file.ts"
  ],
  "testsAddedOrUpdated": [
    "test/file.test.ts"
  ],
  "commandsRun": [
    {
      "command": "command",
      "result": "passed",
      "summary": "short result"
    }
  ],
  "validationOutput": [
    "validation output or concise summary"
  ],
  "residualRisks": [
    "none"
  ],
  "noStagedFiles": true,
  "diffSummary": "short description of the diff",
  "reviewFindings": [
    "blocker: file.ts:12 - issue found, or no blockers"
  ],
  "manualNotes": "anything else the parent should know"
}
```