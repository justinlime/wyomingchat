"""Tests for the always-on voice activity detector state machine."""

from __future__ import annotations

import sys
from array import array
from types import SimpleNamespace

from wyomingchat.audio_types import AudioFormatSpec, PCM_SAMPLE_FORMAT_FLOAT32
from wyomingchat.constants import DEFAULT_VAD_STOP_SILENCE_FRAMES
from wyomingchat.vad import (
    OpenMicVoiceDetector,
    SileroSpeechDetector,
    amplify_pcm_chunk,
    build_stt_audio_format,
    convert_audio_chunk_for_stt,
    measure_pcm_level,
)


class FakeSpeechDetector:
    """Return a predefined speech-probability sequence so the VAD state machine can be tested deterministically."""

    # Usage: create a fake detector that will return the supplied speech probabilities one frame at a time.
    # Parameters: decisions - ordered per-frame bool or float values returned by measure_speech_probability.
    # Return: None.
    def __init__(self, decisions: list[bool | float]) -> None:
        """Initialize the fake detector with a finite decision sequence."""

        self._decisions = list(decisions)
        self._index = 0
        self.reset_calls = 0

    # Usage: emulate the streaming speech-probability interface used by OpenMicVoiceDetector.
    # Parameters: frame - ignored test PCM frame bytes; sample_rate - ignored test sample rate.
    # Return: the next predefined speech probability, or 0.0 after the sequence is exhausted.
    def measure_speech_probability(self, frame: bytes, sample_rate: int) -> float:
        """Return the next predefined speech probability."""

        del frame, sample_rate
        if self._index >= len(self._decisions):
            return 0.0

        decision = self._decisions[self._index]
        self._index += 1
        return float(decision)

    # Usage: emulate the detector reset hook invoked by OpenMicVoiceDetector when monitoring state is discarded.
    # Parameters: none.
    # Return: None.
    def reset(self) -> None:
        """Record that the fake detector reset hook was invoked."""

        self.reset_calls += 1


# Usage: build one fixed-size mono PCM int16 frame suitable for the VAD tests.
# Parameters: value - the int16 sample value to repeat across the frame; sample_count - the number of mono samples to include.
# Return: raw mono int16 PCM bytes.
def build_pcm_frame(value: int, sample_count: int = 480) -> bytes:
    """Return a mono int16 PCM frame filled with the requested sample value."""

    return array("h", [value] * sample_count).tobytes()


# Usage: build one fixed-size mono float32 frame to verify that float microphone capture is decoded correctly for VAD and level measurement.
# Parameters: value - the normalized float32 sample value to repeat across the frame; sample_count - the number of mono samples to include.
# Return: raw mono float32 PCM bytes.
def build_float32_frame(value: float, sample_count: int = 480) -> bytes:
    """Return a mono float32 PCM frame filled with the requested sample value."""

    return array("f", [value] * sample_count).tobytes()


# Usage: verify that raw PCM chunks are converted into a normalized RMS level suitable for the mic meter and gate slider.
# Parameters: none.
# Return: None.
def test_measure_pcm_level_returns_normalized_rms_level() -> None:
    """Ensure PCM level measurement returns a stable normalized RMS value."""

    level = measure_pcm_level(
        build_pcm_frame(16384),
        AudioFormatSpec(rate=16000, width=2, channels=1),
    )

    assert round(level, 2) == 0.5


# Usage: verify that float32 capture frames are decoded correctly before RMS level measurement so the detector can safely analyze microphones that resolve to Qt float sample formats.
# Parameters: none.
# Return: None.
def test_measure_pcm_level_handles_float32_capture_frames() -> None:
    """Ensure float32 microphone frames are converted into the expected normalized RMS level."""

    level = measure_pcm_level(
        build_float32_frame(0.5),
        AudioFormatSpec(rate=16000, width=4, channels=1, sample_format=PCM_SAMPLE_FORMAT_FLOAT32),
    )

    assert round(level, 2) == 0.5


# Usage: verify that outgoing STT audio is normalized to mono int16 PCM so float32 capture never reaches the Wyoming server in an ambiguous raw format.
# Parameters: none.
# Return: None.
def test_convert_audio_chunk_for_stt_normalizes_float32_capture() -> None:
    """Ensure float32 microphone chunks are transcoded into the canonical STT stream format."""

    source_format = AudioFormatSpec(
        rate=16000,
        width=4,
        channels=1,
        sample_format=PCM_SAMPLE_FORMAT_FLOAT32,
    )
    target_format = build_stt_audio_format()

    converted_chunk = convert_audio_chunk_for_stt(build_float32_frame(0.5), source_format, target_format)

    assert len(converted_chunk) == 960
    assert round(measure_pcm_level(converted_chunk, target_format), 2) == 0.5


# Usage: verify that the canonical STT stream format remains the expected 16 kHz mono int16 PCM shape used by the controller when opening Wyoming transcription sessions.
# Parameters: none.
# Return: None.
def test_build_stt_audio_format_returns_canonical_mono_int16_pcm() -> None:
    """Ensure the controller uses a stable STT transport format regardless of capture format."""

    format_spec = build_stt_audio_format()

    assert format_spec.rate == 16000
    assert format_spec.width == 2
    assert format_spec.channels == 1


# Usage: verify that the Silero wrapper validates frame shape, forwards probabilities, and resets the underlying detector state.
# Parameters: monkeypatch - pytest fixture used to inject a fake pysilero_vad module.
# Return: None.
def test_silero_speech_detector_wraps_probability_api(monkeypatch) -> None:
    """Ensure the Silero detector wrapper exposes a stable probability-based interface."""

    class FakeSileroVoiceActivityDetector:
        """Provide the tiny subset of the pysilero_vad API exercised by the wrapper test."""

        # Usage: create the fake detector with a reset counter.
        # Parameters: none.
        # Return: None.
        def __init__(self) -> None:
            """Initialize the fake detector state used by the wrapper test."""

            self.reset_calls = 0

        # Usage: return the required Silero chunk size advertised by the native wrapper.
        # Parameters: none.
        # Return: the number of bytes expected per inference call.
        def chunk_bytes(self) -> int:
            """Return the fake detector's required frame size."""

            return 1024

        # Usage: return a deterministic speech probability for the supplied detector frame.
        # Parameters: frame - the raw mono int16 bytes supplied by the wrapper.
        # Return: a floating-point speech probability.
        def __call__(self, frame: bytes) -> float:
            """Return a stable fake speech probability."""

            assert len(frame) == 1024
            return 0.73

        # Usage: record that the wrapper asked the detector to forget its streaming state.
        # Parameters: none.
        # Return: None.
        def reset(self) -> None:
            """Record one fake detector reset request."""

            self.reset_calls += 1

    monkeypatch.setitem(
        sys.modules,
        "pysilero_vad",
        SimpleNamespace(SileroVoiceActivityDetector=FakeSileroVoiceActivityDetector),
    )

    detector = SileroSpeechDetector()

    assert detector.measure_speech_probability(b"\x00" * 1024, 16000) == 0.73
    detector.reset()
    assert detector._detector.reset_calls == 1


# Usage: verify that the configurable start-level gate prevents low-level audio from triggering a speech start even when the detector reports a high speech probability.
# Parameters: none.
# Return: None.
def test_open_mic_voice_detector_requires_minimum_level_before_start() -> None:
    """Ensure the level gate blocks low-volume frames from starting an utterance."""

    detector = OpenMicVoiceDetector(
        audio_format=AudioFormatSpec(rate=16000, width=2, channels=1),
        detector=FakeSpeechDetector([1.0, 1.0, 1.0, 1.0]),
        frame_ms=30,
        pre_roll_ms=30,
        start_window_frames=2,
        start_trigger_frames=2,
        stop_silence_frames=2,
        start_level_threshold=0.05,
    )

    quiet_start = detector.process_audio_chunk(build_pcm_frame(300))
    quiet_follow_up = detector.process_audio_chunk(build_pcm_frame(300))
    loud_start = detector.process_audio_chunk(build_pcm_frame(4000))
    loud_follow_up = detector.process_audio_chunk(build_pcm_frame(4000))

    assert quiet_start.should_start_stream is False
    assert quiet_follow_up.should_start_stream is False
    assert loud_start.should_start_stream is False
    assert loud_follow_up.should_start_stream is True


# Usage: verify that the stricter start probability threshold still requires a high-confidence speech frame to open a stream, even when the lower continuation threshold would treat the same frame as ongoing speech.
# Parameters: none.
# Return: None.
def test_open_mic_voice_detector_uses_stricter_start_probability_threshold() -> None:
    """Ensure start-time probability gating is stricter than active-session continuation gating."""

    detector = OpenMicVoiceDetector(
        audio_format=AudioFormatSpec(rate=16000, width=2, channels=1),
        detector=FakeSpeechDetector([0.62, 0.62, 0.62, 0.81, 0.81]),
        frame_ms=30,
        pre_roll_ms=60,
        start_window_frames=2,
        start_trigger_frames=2,
        stop_silence_frames=2,
        start_speech_threshold=0.8,
        continue_speech_threshold=0.6,
    )

    decisions = [detector.process_audio_chunk(build_pcm_frame(index + 1)) for index in range(5)]

    assert all(decision.should_start_stream is False for decision in decisions[:-1])
    assert decisions[-1].should_start_stream is True
    assert decisions[-1].audio_chunks == [build_pcm_frame(4), build_pcm_frame(5)]


# Usage: verify that the VAD state machine keeps a short pre-roll and emits buffered frames when speech starts.
# Parameters: none.
# Return: None.
def test_open_mic_voice_detector_uses_pre_roll_when_speech_starts() -> None:
    """Ensure the detector emits recent pre-roll frames when it confirms speech onset."""

    detector = OpenMicVoiceDetector(
        audio_format=AudioFormatSpec(rate=16000, width=2, channels=1),
        detector=FakeSpeechDetector([0.0, 0.0, 1.0, 1.0]),
        frame_ms=30,
        pre_roll_ms=60,
        start_window_frames=2,
        start_trigger_frames=2,
        stop_silence_frames=2,
    )

    frames = [build_pcm_frame(index + 1) for index in range(4)]
    decisions = [detector.process_audio_chunk(frame) for frame in frames]

    assert decisions[-1].should_start_stream is True
    assert decisions[-1].audio_chunks == [frames[2], frames[3]]


# Usage: verify that the detector forwards the complete pre-roll buffer when speech starts so gradual onsets are never clipped.
# Parameters: none.
# Return: None.
def test_open_mic_voice_detector_forwards_full_pre_roll_when_speech_starts() -> None:
    """Ensure the full buffered pre-roll is forwarded even when it contains leading non-speech frames."""

    detector = OpenMicVoiceDetector(
        audio_format=AudioFormatSpec(rate=16000, width=2, channels=1),
        detector=FakeSpeechDetector([0.0, 1.0, 1.0]),
        frame_ms=30,
        pre_roll_ms=90,
        speech_pad_ms=0,
        start_window_frames=2,
        start_trigger_frames=2,
        stop_silence_frames=2,
    )

    frames = [build_pcm_frame(index + 10) for index in range(3)]
    first = detector.process_audio_chunk(frames[0])
    second = detector.process_audio_chunk(frames[1])
    third = detector.process_audio_chunk(frames[2])

    assert first.should_start_stream is False
    assert second.should_start_stream is False
    assert third.should_start_stream is True
    assert third.audio_chunks == [frames[0], frames[1], frames[2]]


# Usage: verify that non-zero speech padding preserves a small amount of leading context before the first speech-confirmed frame so the first word is less likely to be clipped.
# Parameters: none.
# Return: None.
def test_open_mic_voice_detector_keeps_leading_speech_padding_when_stream_starts() -> None:
    """Ensure configured speech padding reintroduces a short lead-in before detected speech starts."""

    detector = OpenMicVoiceDetector(
        audio_format=AudioFormatSpec(rate=16000, width=2, channels=1),
        detector=FakeSpeechDetector([0.0, 0.0, 1.0, 1.0]),
        frame_ms=30,
        pre_roll_ms=120,
        speech_pad_ms=60,
        start_window_frames=2,
        start_trigger_frames=2,
        stop_silence_frames=2,
    )

    frames = [build_pcm_frame(index + 100) for index in range(4)]
    decisions = [detector.process_audio_chunk(frame) for frame in frames]

    assert decisions[-1].should_start_stream is True
    assert decisions[-1].audio_chunks == [frames[0], frames[1], frames[2], frames[3]]


# Usage: verify that the detector now starts as soon as the required number of speech-confirmed frames has been observed, instead of waiting for the full rolling start window to fill and risking clipped first words.
# Parameters: none.
# Return: None.
def test_open_mic_voice_detector_starts_as_soon_as_trigger_frames_are_met() -> None:
    """Ensure speech start can trigger before the full rolling window fills once the configured trigger count is satisfied."""

    detector = OpenMicVoiceDetector(
        audio_format=AudioFormatSpec(rate=16000, width=2, channels=1),
        detector=FakeSpeechDetector([1.0, 1.0, 1.0]),
        frame_ms=30,
        pre_roll_ms=150,
        speech_pad_ms=0,
        start_window_frames=5,
        start_trigger_frames=3,
        stop_silence_frames=2,
    )

    decisions = [
        detector.process_audio_chunk(build_pcm_frame(index + 20))
        for index in range(3)
    ]

    assert decisions[0].should_start_stream is False
    assert decisions[1].should_start_stream is False
    assert decisions[2].should_start_stream is True


# Usage: verify that the pre-roll forwards its full buffer regardless of where older speech-positive frames fall, so no earlier onset audio is dropped.
# Parameters: none.
# Return: None.
def test_open_mic_voice_detector_forwards_full_pre_roll_ignoring_stale_window_position() -> None:
    """Ensure the complete pre-roll buffer is forwarded even when older speech frames are outside the current start window."""

    detector = OpenMicVoiceDetector(
        audio_format=AudioFormatSpec(rate=16000, width=2, channels=1),
        detector=FakeSpeechDetector([1.0, 0.0, 0.0, 1.0, 1.0]),
        frame_ms=30,
        pre_roll_ms=150,
        speech_pad_ms=0,
        start_window_frames=3,
        start_trigger_frames=2,
        stop_silence_frames=2,
    )

    frames = [build_pcm_frame(index + 40) for index in range(5)]
    decisions = [detector.process_audio_chunk(frame) for frame in frames]

    assert decisions[-1].should_start_stream is True
    assert decisions[-1].audio_chunks == [frames[0], frames[1], frames[2], frames[3], frames[4]]


# Usage: verify that the VAD state machine stops an utterance only after the configured amount of trailing silence, while dropping that trailing silence instead of forwarding it to STT when explicit trailing padding is disabled.
# Parameters: none.
# Return: None.
def test_open_mic_voice_detector_waits_for_trailing_silence_before_stop() -> None:
    """Ensure the detector waits for the configured silence hangover and suppresses trailing non-speech audio when padding is disabled."""

    detector = OpenMicVoiceDetector(
        audio_format=AudioFormatSpec(rate=16000, width=2, channels=1),
        detector=FakeSpeechDetector([1.0, 1.0, 1.0, 0.0, 0.0]),
        frame_ms=30,
        pre_roll_ms=30,
        speech_pad_ms=0,
        start_window_frames=2,
        start_trigger_frames=2,
        stop_silence_frames=2,
    )

    frames = [build_pcm_frame(index + 10) for index in range(5)]
    first = detector.process_audio_chunk(frames[0])
    second = detector.process_audio_chunk(frames[1])
    third = detector.process_audio_chunk(frames[2])
    fourth = detector.process_audio_chunk(frames[3])
    fifth = detector.process_audio_chunk(frames[4])

    assert first.should_start_stream is False
    assert second.should_start_stream is True
    assert second.audio_chunks == [frames[1]]
    assert third.should_stop_stream is False
    assert third.audio_chunks == [frames[2]]
    assert fourth.should_stop_stream is False
    assert fourth.audio_chunks == []
    assert fifth.should_stop_stream is True
    assert fifth.audio_chunks == []


# Usage: verify that a non-zero speech pad preserves a short trailing tail of silence when speech ends so the STT server does not see an unnaturally abrupt cutoff.
# Parameters: none.
# Return: None.
def test_open_mic_voice_detector_keeps_trailing_speech_padding_when_stream_stops() -> None:
    """Ensure configured speech padding forwards a short trailing tail when an utterance ends."""

    detector = OpenMicVoiceDetector(
        audio_format=AudioFormatSpec(rate=16000, width=2, channels=1),
        detector=FakeSpeechDetector([1.0, 1.0, 1.0, 0.0, 0.0]),
        frame_ms=30,
        pre_roll_ms=30,
        speech_pad_ms=60,
        start_window_frames=2,
        start_trigger_frames=2,
        stop_silence_frames=2,
    )

    frames = [build_pcm_frame(index + 200) for index in range(5)]
    detector.process_audio_chunk(frames[0])
    detector.process_audio_chunk(frames[1])
    detector.process_audio_chunk(frames[2])
    detector.process_audio_chunk(frames[3])
    stop_decision = detector.process_audio_chunk(frames[4])

    assert stop_decision.should_stop_stream is True
    assert stop_decision.audio_chunks == [frames[3], frames[4]]


# Usage: verify that a brief pause inside an active utterance is held locally and only forwarded when speech resumes, which keeps natural word gaps without streaming long stretches of silence.
# Parameters: none.
# Return: None.
def test_open_mic_voice_detector_buffers_brief_pause_until_speech_resumes() -> None:
    """Ensure short in-utterance pauses are forwarded only when followed by more speech."""

    detector = OpenMicVoiceDetector(
        audio_format=AudioFormatSpec(rate=16000, width=2, channels=1),
        detector=FakeSpeechDetector([1.0, 1.0, 0.0, 0.7, 0.0, 0.0]),
        frame_ms=30,
        pre_roll_ms=30,
        speech_pad_ms=0,
        start_window_frames=2,
        start_trigger_frames=2,
        stop_silence_frames=2,
        continue_speech_threshold=0.55,
    )

    frames = [build_pcm_frame(index + 30) for index in range(6)]
    detector.process_audio_chunk(frames[0])
    start_decision = detector.process_audio_chunk(frames[1])
    brief_pause = detector.process_audio_chunk(frames[2])
    resumed_speech = detector.process_audio_chunk(frames[3])
    trailing_pause = detector.process_audio_chunk(frames[4])
    stop_decision = detector.process_audio_chunk(frames[5])

    assert start_decision.should_start_stream is True
    assert start_decision.audio_chunks == [frames[1]]
    assert brief_pause.audio_chunks == []
    assert resumed_speech.audio_chunks == [frames[2], frames[3]]
    assert trailing_pause.audio_chunks == []
    assert stop_decision.should_stop_stream is True
    assert stop_decision.audio_chunks == []


# Usage: verify that the default silence hangover leaves enough room for a short natural pause without ending the utterance.
# Parameters: none.
# Return: None.
def test_open_mic_voice_detector_default_stop_delay_tolerates_brief_pauses() -> None:
    """Ensure the default stop delay keeps listening through a short mid-sentence pause."""

    detector = OpenMicVoiceDetector(
        audio_format=AudioFormatSpec(rate=16000, width=2, channels=1),
        detector=FakeSpeechDetector([1.0, 1.0] + ([0.0] * DEFAULT_VAD_STOP_SILENCE_FRAMES)),
        frame_ms=30,
        pre_roll_ms=30,
        speech_pad_ms=0,
        start_window_frames=2,
        start_trigger_frames=2,
    )

    start_decision = detector.process_audio_chunk(build_pcm_frame(1))
    speaking_decision = detector.process_audio_chunk(build_pcm_frame(2))
    silent_decisions = [
        detector.process_audio_chunk(build_pcm_frame(0))
        for _ in range(DEFAULT_VAD_STOP_SILENCE_FRAMES)
    ]

    assert start_decision.should_start_stream is False
    assert speaking_decision.should_start_stream is True
    assert all(
        decision.should_stop_stream is False
        for decision in silent_decisions[:-1]
    )
    assert all(decision.audio_chunks == [] for decision in silent_decisions)
    assert silent_decisions[-1].should_stop_stream is True


# Usage: verify that reset clears buffered state and resets the underlying detector so a later utterance starts cleanly.
# Parameters: none.
# Return: None.
def test_open_mic_voice_detector_reset_clears_pending_state() -> None:
    """Ensure reset forgets buffered audio, prior speech decisions, and detector state."""

    fake_detector = FakeSpeechDetector([1.0, 0.0, 1.0, 1.0])
    detector = OpenMicVoiceDetector(
        audio_format=AudioFormatSpec(rate=16000, width=2, channels=1),
        detector=fake_detector,
        frame_ms=30,
        pre_roll_ms=60,
        speech_pad_ms=0,
        start_window_frames=2,
        start_trigger_frames=2,
        stop_silence_frames=2,
    )

    detector.process_audio_chunk(build_pcm_frame(1))
    detector.process_audio_chunk(build_pcm_frame(2))
    detector.reset()
    start_decision = detector.process_audio_chunk(build_pcm_frame(3))
    final_decision = detector.process_audio_chunk(build_pcm_frame(4))

    assert fake_detector.reset_calls == 1
    assert start_decision.should_start_stream is False
    assert final_decision.should_start_stream is True


# Usage: verify that the speech-oriented level blends peak energy so quiet speech reads higher than pure RMS.
# Parameters: none.
# Return: None.
def test_measure_pcm_level_blends_peak_for_speech_like_frames() -> None:
    """Ensure high-crest (speech-like) frames register clearly on the meter."""

    # A mostly-silent frame with one loud sample: RMS is tiny but peak is large.
    samples = [0] * 511 + [20000]
    frame = array("h", samples).tobytes()
    format_spec = AudioFormatSpec(rate=16000, width=2, channels=1)

    level = measure_pcm_level(frame, format_spec)

    # max(rms, peak * 0.5) = max(~0.03, 0.31)
    assert round(level, 2) == 0.31


# Usage: verify that int16 microphone chunks are amplified by the requested gain with clipping protection.
# Parameters: none.
# Return: None.
def test_amplify_pcm_chunk_boosts_int16_and_clips() -> None:
    """Ensure int16 chunks scale by the gain and clamp at full scale."""

    format_spec = AudioFormatSpec(rate=16000, width=2, channels=1)

    boosted = amplify_pcm_chunk(build_pcm_frame(16384), format_spec, 1.5)
    assert round(measure_pcm_level(boosted, format_spec), 2) == 0.75

    clipped = amplify_pcm_chunk(build_pcm_frame(16384), format_spec, 2.0)
    assert round(measure_pcm_level(clipped, format_spec), 2) == 1.0


# Usage: verify that float32 microphone chunks are amplified and clamped to the normalized range.
# Parameters: none.
# Return: None.
def test_amplify_pcm_chunk_boosts_float32_and_clamps() -> None:
    """Ensure float32 chunks scale by the gain and clamp at unity."""

    format_spec = AudioFormatSpec(
        rate=16000,
        width=4,
        channels=1,
        sample_format=PCM_SAMPLE_FORMAT_FLOAT32,
    )

    boosted = amplify_pcm_chunk(build_float32_frame(0.4), format_spec, 2.0)
    assert round(measure_pcm_level(boosted, format_spec), 2) == 0.8

    clamped = amplify_pcm_chunk(build_float32_frame(0.8), format_spec, 2.0)
    assert round(measure_pcm_level(clamped, format_spec), 2) == 1.0


# Usage: verify that gain at or below unity leaves the chunk untouched.
# Parameters: none.
# Return: None.
def test_amplify_pcm_chunk_leaves_unchanged_without_boost() -> None:
    """Ensure a gain of 1.0 or lower passes the chunk through unchanged."""

    format_spec = AudioFormatSpec(rate=16000, width=2, channels=1)
    frame = build_pcm_frame(16384)

    assert amplify_pcm_chunk(frame, format_spec, 1.0) == frame
    assert amplify_pcm_chunk(frame, format_spec, 0.5) == frame
    assert amplify_pcm_chunk(b"", format_spec, 2.0) == b""


# Usage: verify that raising the silence hangover live tolerates longer mid-utterance pauses.
# Parameters: none.
# Return: None.
def test_set_stop_silence_frames_extends_pause_tolerance() -> None:
    """Ensure the live stop-silence update lets longer natural pauses continue the utterance."""

    detector = OpenMicVoiceDetector(
        audio_format=AudioFormatSpec(rate=16000, width=2, channels=1),
        detector=FakeSpeechDetector([1.0, 1.0, 0.0, 0.0, 0.0, 0.0]),
        frame_ms=30,
        pre_roll_ms=30,
        speech_pad_ms=0,
        start_window_frames=2,
        start_trigger_frames=2,
        stop_silence_frames=2,
    )

    frames = [build_pcm_frame(index + 1) for index in range(6)]
    detector.process_audio_chunk(frames[0])
    detector.process_audio_chunk(frames[1])

    # A 2-frame hangover would already have stopped; extend it live to 4 frames.
    detector.set_stop_silence_frames(4)

    third = detector.process_audio_chunk(build_pcm_frame(0))
    fourth = detector.process_audio_chunk(build_pcm_frame(0))
    fifth = detector.process_audio_chunk(build_pcm_frame(0))
    sixth = detector.process_audio_chunk(build_pcm_frame(0))

    assert third.should_stop_stream is False
    assert fourth.should_stop_stream is False
    assert fifth.should_stop_stream is False
    assert sixth.should_stop_stream is True
