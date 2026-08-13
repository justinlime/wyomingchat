# Task for coder

READ-ONLY code review - do NOT modify any files. Repo: /home/justinlime/code/wyomingchat (Python/PySide6 app bridging a mic to Wyoming STT/TTS TCP servers).

INVESTIGATE: The user reports 'speech to text timeouts a lot now' which never happened before. The recent changes added: per-sentence streaming TTS (multiple TextToSpeechSession instances created DURING the STT session), a stop-time tail dispatch (TTS sessions started when the utterance ends), longer silence timeout (2.5s), larger capture buffer (250ms), longer VAD pre-roll (600ms).

Read carefully:
- src/wyomingchat/clients.py — SpeechToTextSession and WyomingTcpConnection: connect(timeout=10), _connected.wait(timeout=10.0), send/read loops, close()/wait_closed(1.0), thread lifecycle, socket timeouts. Identify every path that can produce a timeout-ish error and whether stale threads/sockets can linger.
- src/wyomingchat/controller.py — _start_stt_session, _abort_current_activity, _handle_stt_complete, the stop-time tail dispatch in _handle_audio_chunk, and how many TCP connections can be open concurrently per utterance.

Answer: (1) Enumerate every error string in clients.py that could surface as an 'STT timeout' and the exact conditions that trigger each. (2) Can a previous STT session's writer/reader thread still be blocked (e.g., socket.create_connection blocking up to 10s) when a new session starts, and what happens? (3) Does starting N concurrent TTS sessions while the STT session is still finalizing delay or starve the STT socket in any way? (4) Any resource leak (threads, sockets) that accumulates per utterance and could cause later sessions to time out?

Return a findings report with file:line references.

---
**Output:**
Write your findings to exactly this path: /tmp/review_stt_timeout.txt
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