# Task for researcher

Research the Wyoming protocol's STREAMING text-to-speech (TTS) wire format, and the client-side handshake a TTS client must perform to have a Wyoming TTS server treat a request as "streaming" instead of a normal single-shot "Synthesize".

Context: We are writing a Python client that talks to Wyoming-compatible TTS servers (Rhasspy/Home Assistant ecosystem). The server's logs show our requests are treated as non-streaming "Synthesize". We want to switch to the streaming text-synthesis events.

Reference material available locally:
- /home/justinlime/.cache/uv/archive-v0/flAJ2b2_BjfBbVXx1NY23/wyoming/tts.py (wyoming lib 1.8.0) — defines Synthesize, SynthesizeStart, SynthesizeChunk, SynthesizeStop, SynthesizeStopped event classes
- /home/justinlime/.cache/uv/archive-v0/flAJ2b2_BjfBbVXx1NY23/wyoming/info.py — TtsInfo has a field `supports_synthesize_streaming: bool`
- /home/justinlime/.cache/uv/archive-v0/flAJ2b2_BjfBbVXx1NY23/wyoming/client.py — check if it has AsyncTtsClient or TtsClient with streaming synthesize methods
- /home/justinlime/.cache/uv/archive-v0/QH-2nHZrp3xB5iV0gFPFI/wyoming/ (wyoming lib 1.7.1)

Please answer precisely:
1. The exact sequence of client→server events for streaming synthesis, and server→client events in response (including where audio-start/audio-chunk/audio-stop and synthesize-stopped appear relative to the client's synthesize-stop).
2. Whether the client must advertise streaming support somehow (e.g., an info describe exchange, or a flag), or whether sending synthesize-start/chunk/stop is sufficient. Look at how the server dispatches events (check wyoming/server.py or any ServerTts handler in the repo) and how `supports_synthesize_streaming` is set/advertised by servers.
3. What a client should do if the server does NOT advertise `supports_synthesize_streaming` (fallback to single-shot synthesize?).
4. Any exact wire-format details: event data fields for synthesize-start (voice dict shape: name/speaker vs language), synthesize-chunk ({"text": ...}), synthesize-stop (no data).

If GitHub is reachable, also check https://github.com/rhasspy/wyoming (docs or protocol.md) and how wyoming-piper or the Home Assistant wyoming TTS providers implement the streaming side, so we can confirm the client handshake. Report concrete findings with the exact event types and data shapes, and cite the local file paths/line numbers you used.

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