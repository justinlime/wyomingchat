# Task for coder

READ-ONLY code review - do NOT modify any files. Repo: /home/justinlime/code/wyomingchat (a Python/PySide6 app that bridges a mic to Wyoming STT/TTS servers).

INVESTIGATE: A user reports a LONG PAUSE (up to seconds) between sentences in TTS playback that started when 'streaming synthesis' was added. The app synthesizes each transcript sentence as a separate Wyoming TTS request and chains playback per sentence.

Read these files carefully:
- src/wyomingchat/controller.py — focus on: _SentenceAudioUnit, _start_sentence_synthesis, _handle_sentence_audio_start/chunk/complete, _maybe_start_playback, _handle_playback_finished, _handle_stt_complete, and how sentence units chain playback.
- src/wyomingchat/audio.py — focus on MultiOutputPlayer: write_audio, finish_stream, _flush_pending_buffers, _schedule_drain_stop, _drain_delay_for, _sink_buffered_ms, _drain_timer, _flush_timer, _estimated_buffer_ms accounting.
- src/wyomingchat/streaming.py (transcript chunker).

Answer concretely: (1) Where exactly does an inter-sentence gap come from in the chaining logic? Quantify the delay contributors (drain timer margin, stream restart, wait-for-next-unit-format, anything else). (2) Is there a double-count or timing bug in _estimated_buffer_ms vs _sink_buffered_ms? (3) Could concurrent per-sentence TTS sessions (opened while the mic is still being listened to) cause the STT service to time out (report the exact timeout strings in clients.py: 'STT send failed: timed out', '_connected.wait(timeout=10.0)', 'STT receive failed')? (4) Recommend the minimal, safest way to restore single-continuous-playback behavior (one synthesize per utterance, one stream, no chaining).

Return a concise findings report with file:line references and a prioritized list of concrete fixes.

---
**Output:**
Write your findings to exactly this path: /tmp/review_pause.txt
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