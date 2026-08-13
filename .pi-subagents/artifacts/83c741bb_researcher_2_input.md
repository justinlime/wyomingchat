# Task for researcher

READ-ONLY review - do NOT modify any files. Repo: /home/justinlime/code/wyomingchat (Python/PySide6 voice bridge).

VERIFY the audio/VAD timing pipeline for cumulative drift or misalignment bugs that could make transcription truncation worse over a long session:
- src/wyomingchat/vad.py — OpenMicVoiceDetector.process_audio_chunk: frame buffering (_pending_bytes), _source_frame_bytes, _pre_roll_frames, _pending_silence_frames, _silent_frame_count, _stop_silence_frames, pause buffer logic, and set_stop_silence_frames. Verify frame accounting is bounded and self-correcting (no drift accumulation).
- src/wyomingchat/audio.py — AudioCaptureStream._drain_audio (reads all available), QAudioSource buffer 250ms, and MultiOutputPlayer timing.
- src/wyomingchat/controller.py — _handle_audio_chunk, mic_gain application, cooldown, state gating.

Answer: (1) Is the frame pipeline bounded and correct, or does anything accumulate (pending bytes, silent counts, stale flags) across utterances? (2) Does a 250ms capture buffer plus the frame-count-based VAD introduce any systematic drift? (3) Any interaction where a config save or state change while paused/monitoring could double-consume or drop audio? (4) Note anything that could explain truncation worsening over time.

Return a findings report with file:line references.

---
**Output:**
Write your findings to exactly this path: /tmp/review_drift.txt
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