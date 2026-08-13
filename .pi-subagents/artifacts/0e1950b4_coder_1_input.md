# Task for coder

READ-ONLY code review - do NOT modify any files. Repo: /home/justinlime/code/wyomingchat (Python/PySide6 voice bridge using the Wyoming protocol over TCP).

BUG REPORT: TTS audio only plays after the final chunk is received, instead of playing each chunk as it arrives.

Read carefully:
- src/wyomingchat/clients.py TextToSpeechSession._read_loop and WyomingTcpConnection: how audio-start, audio-chunk, and audio-stop events are decoded and how the on_audio_start/on_audio_chunk/on_complete callbacks are invoked (which thread, how often).
- src/wyomingchat/wyoming_protocol.py: encode_event/decode_event and read_exactly - confirm the framing delivers each event independently (no accidental buffering of the whole payload).
- The controller lambdas passed as callbacks in _start_tts (controller.py) that emit PySide6 Signals from the reader thread.

Answer with file:line references: (1) Does the reader deliver audio-chunk callbacks immediately per event, or could the socket reads block/accumulate until audio-stop? (2) Is there any per-event payload buffering in decode_event/read_exactly? (3) Could PySide6 queued signal delivery between the reader thread and GUI thread reorder or delay chunks, and is the audio-start signal guaranteed before chunks? (4) Any way the reader thread gets starved (GIL, blocking sendall on the same socket in the writer thread) so that chunks accumulate server-side and arrive in one burst at the end? (5) Recommend the minimal fix to guarantee per-chunk streaming playback.

Return a concise findings report with file:line references.

---
**Output:**
Write your findings to exactly this path: /tmp/review_playback2.txt
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