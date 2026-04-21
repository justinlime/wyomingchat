"""Voice activity detection helpers for always-on microphone monitoring."""

from __future__ import annotations

from array import array
from collections import deque
from dataclasses import dataclass, field
from typing import Protocol

from .audio_types import (
    AudioFormatSpec,
    PCM_SAMPLE_FORMAT_FLOAT32,
    PCM_SAMPLE_FORMAT_INT16,
    PCM_SAMPLE_FORMAT_UINT8,
)
from .constants import (
    DEFAULT_VAD_CONTINUE_SPEECH_THRESHOLD,
    DEFAULT_VAD_FRAME_MS,
    DEFAULT_VAD_PAUSE_BUFFER_MS,
    DEFAULT_VAD_PRE_ROLL_MS,
    DEFAULT_VAD_SAMPLE_RATE,
    DEFAULT_VAD_SPEECH_PAD_MS,
    DEFAULT_VAD_START_SPEECH_THRESHOLD,
    DEFAULT_VAD_START_TRIGGER_FRAMES,
    DEFAULT_VAD_START_WINDOW_FRAMES,
    DEFAULT_VAD_STOP_SILENCE_FRAMES,
)

DEFAULT_SPEECH_DETECTOR_SAMPLE_WIDTH = 2


class FrameSpeechDetector(Protocol):
    """Describe the minimal speech-detector interface used by the open-mic state machine."""

    # Usage: score one fixed-duration mono PCM frame with a speech probability so the open-mic state machine can apply hysteresis and buffering rules.
    # Parameters: frame - a mono 16-bit PCM frame prepared for the detector; sample_rate - the sampling rate of the frame.
    # Return: a floating-point probability between 0.0 and 1.0 where larger values indicate a stronger belief that speech is present.
    def measure_speech_probability(self, frame: bytes, sample_rate: int) -> float:
        """Return the probability that the supplied PCM frame contains speech."""

    # Usage: clear any detector-internal streaming state whenever the controller abandons the current microphone context.
    # Parameters: none.
    # Return: None.
    def reset(self) -> None:
        """Clear any detector-internal state before a new audio stream begins."""


class SileroSpeechDetector:
    """Use pysilero-vad to score fixed 16 kHz mono PCM frames for speech probability."""

    # Usage: create the default speech detector used by the always-on microphone monitor.
    # Parameters: none.
    # Return: None.
    def __init__(self) -> None:
        """Initialize the pysilero-vad detector and cache its required frame shape."""

        try:
            from pysilero_vad import SileroVoiceActivityDetector
        except ImportError as exc:  # pragma: no cover - exercised through the raised message path in runtime environments.
            raise RuntimeError(
                "Silero VAD support is unavailable. Install the 'pysilero-vad' package to enable microphone speech detection."
            ) from exc

        self._detector = SileroVoiceActivityDetector()
        self._sample_rate = DEFAULT_VAD_SAMPLE_RATE
        self._chunk_bytes = int(self._detector.chunk_bytes())

    @property
    # Usage: expose the required input sample rate for callers that need to prepare audio for this detector.
    # Parameters: none.
    # Return: the required detector input sample rate in Hz.
    def sample_rate(self) -> int:
        """Return the only sample rate accepted by this Silero detector wrapper."""

        return self._sample_rate

    @property
    # Usage: expose the required frame byte length for callers that need to prepare detector input buffers.
    # Parameters: none.
    # Return: the exact number of mono int16 bytes expected for each detector call.
    def chunk_bytes(self) -> int:
        """Return the exact byte length expected by each Silero detector inference call."""

        return self._chunk_bytes

    # Usage: score one prepared detector frame with Silero VAD and clamp the result into a stable 0.0-1.0 probability range.
    # Parameters: frame - one mono int16 PCM frame with the exact byte length required by the model; sample_rate - the input sampling rate that should match the detector's required rate.
    # Return: a floating-point speech probability between 0.0 and 1.0.
    def measure_speech_probability(self, frame: bytes, sample_rate: int) -> float:
        """Return Silero's speech probability for one prepared audio frame."""

        if sample_rate != self._sample_rate:
            raise ValueError(f"Silero VAD expects {self._sample_rate} Hz audio, received {sample_rate} Hz")
        if len(frame) != self._chunk_bytes:
            raise ValueError(
                f"Silero VAD expects {self._chunk_bytes} bytes per frame, received {len(frame)} bytes"
            )

        speech_probability = float(self._detector(frame))
        return max(0.0, min(1.0, speech_probability))

    # Usage: clear any streaming state retained by the underlying Silero model when the controller discards the current audio context.
    # Parameters: none.
    # Return: None.
    def reset(self) -> None:
        """Reset the underlying Silero detector state for a fresh audio stream."""

        self._detector.reset()


@dataclass(slots=True)
class VoiceActivityDecision:
    """Describe what the controller should do after processing one audio chunk."""

    should_start_stream: bool = False
    should_stop_stream: bool = False
    audio_chunks: list[bytes] = field(default_factory=list)


@dataclass(slots=True)
class AnalyzedAudioFrame:
    """Store one microphone frame together with the speech metadata needed by the VAD state machine."""

    frame: bytes
    detected_speech: bool
    counts_as_start_speech: bool


# Usage: choose the detector input sample rate used by the always-on speech pipeline.
# Parameters: source_rate - the incoming microphone sampling rate, retained only for interface symmetry with older callers.
# Return: the detector sample rate in Hz.
def choose_detector_sample_rate(source_rate: int) -> int:
    """Return the fixed Silero-compatible sample rate used by the detector pipeline."""

    del source_rate
    return DEFAULT_VAD_SAMPLE_RATE


# Usage: clip an arbitrary numeric sample into the signed 16-bit PCM range required by the Silero detector and the app's level meter.
# Parameters: sample - the numeric sample value that should be clipped.
# Return: an integer constrained to the [-32768, 32767] int16 range.
def clamp_int16(sample: float) -> int:
    """Return a sample value clamped into the signed 16-bit PCM range."""

    return max(-32768, min(32767, int(round(sample))))


# Usage: convert one raw PCM frame into mono 16-bit samples suitable for speech detection and level measurement.
# Parameters: frame - raw PCM bytes from Qt capture; format_spec - the PCM format that describes the incoming frame.
# Return: a Python list of mono int16 samples at the original capture rate.
def pcm_frame_to_mono_int16(frame: bytes, format_spec: AudioFormatSpec) -> list[int]:
    """Convert a raw PCM frame into a mono int16 sample list."""

    if not frame:
        return []

    if format_spec.sample_format == PCM_SAMPLE_FORMAT_FLOAT32:
        raw_samples = array("f")
        raw_samples.frombytes(frame)
        source_samples = [sample * 32767.0 for sample in raw_samples]
    elif format_spec.sample_format == PCM_SAMPLE_FORMAT_UINT8 or format_spec.width == 1:
        source_samples = [((value - 128) * 256) for value in frame]
    elif format_spec.width == 4:
        raw_samples = array("i")
        raw_samples.frombytes(frame)
        source_samples = [sample / 65536.0 for sample in raw_samples]
    elif format_spec.width == 2:
        raw_samples = array("h")
        raw_samples.frombytes(frame)
        source_samples = list(raw_samples)
    else:
        raise ValueError(
            f"Unsupported PCM sample format for speech detection: {format_spec.sample_format} ({format_spec.width} bytes)"
        )

    if format_spec.channels <= 1:
        return [clamp_int16(sample) for sample in source_samples]

    mono_samples: list[int] = []
    for index in range(0, len(source_samples), format_spec.channels):
        channel_slice = source_samples[index : index + format_spec.channels]
        if not channel_slice:
            continue
        mono_samples.append(clamp_int16(sum(channel_slice) / len(channel_slice)))

    return mono_samples


# Usage: convert mono int16 PCM samples into a normalized 0.0-1.0 RMS level that can drive a mic meter or gate.
# Parameters: samples - mono signed 16-bit PCM samples.
# Return: a floating-point RMS level where 0.0 is silence and 1.0 is full-scale PCM.
def calculate_rms_level(samples: list[int]) -> float:
    """Return a normalized RMS level for mono int16 PCM samples."""

    if not samples:
        return 0.0

    squared_sum = sum(float(sample) * float(sample) for sample in samples)
    mean_square = squared_sum / len(samples)
    return min(1.0, (mean_square ** 0.5) / 32767.0)


# Usage: calculate the normalized peak level of mono int16 PCM samples.
# Parameters: samples - mono signed 16-bit PCM samples.
# Return: a floating-point peak level where 0.0 is silence and 1.0 is full-scale PCM.
def calculate_peak_level(samples: list[int]) -> float:
    """Return a normalized peak level for mono int16 PCM samples."""

    if not samples:
        return 0.0

    peak = max(abs(sample) for sample in samples)
    return min(1.0, peak / 32767.0)


# Usage: compute a speech-oriented level that blends RMS with a fraction of the peak so quiet speech reads more clearly.
# Parameters: samples - mono signed 16-bit PCM samples.
# Return: a floating-point level where 0.0 is silence and 1.0 is full-scale PCM.
def calculate_speech_level(samples: list[int]) -> float:
    """Return a normalized speech-oriented level that blends RMS with peak.

    Pure RMS reads very low for real speech because utterances have high crest
    factors (loud peaks over a modest average), which makes meters and gates
    feel insensitive. Blending in a fraction of the peak level keeps noise
    floors stable while making voiced speech register much more clearly.
    """

    if not samples:
        return 0.0

    rms_level = calculate_rms_level(samples)
    peak_level = calculate_peak_level(samples)
    return max(rms_level, peak_level * 0.5)


# Usage: measure the normalized speech-oriented level of an arbitrary raw PCM chunk using the same sample conversion rules as the speech-detection pipeline.
# Parameters: frame - raw PCM bytes from Qt capture; format_spec - the PCM format used to decode the frame.
# Return: a floating-point level where 0.0 is silence and 1.0 is full-scale PCM.
def measure_pcm_level(frame: bytes, format_spec: AudioFormatSpec) -> float:
    """Return a normalized speech-oriented level for a raw PCM chunk."""

    return calculate_speech_level(pcm_frame_to_mono_int16(frame, format_spec))


# Usage: scale a raw PCM chunk by a gain multiplier while preserving its exact sample format.
# Parameters: chunk - raw PCM bytes from Qt capture; format_spec - the PCM format that describes the chunk; gain - the linear gain multiplier (1.0 means unchanged).
# Return: the amplified PCM bytes in the original format, clamped to the format's native range.
def amplify_pcm_chunk(chunk: bytes, format_spec: AudioFormatSpec, gain: float) -> bytes:
    """Return a raw PCM chunk scaled by a gain multiplier in its original format.

    A gain above 1.0 boosts quiet microphones before VAD analysis, level
    metering, and STT streaming. Sample values are clamped to the format's
    native range so the boosted signal cannot overflow.
    """

    if gain <= 1.0 or not chunk:
        return chunk

    if format_spec.sample_format == PCM_SAMPLE_FORMAT_FLOAT32:
        raw_samples = array("f")
        raw_samples.frombytes(chunk)
        scaled_samples = array(
            "f",
            (max(-1.0, min(1.0, sample * gain)) for sample in raw_samples),
        )
        return scaled_samples.tobytes()

    if format_spec.sample_format == PCM_SAMPLE_FORMAT_UINT8 or format_spec.width == 1:
        scaled = bytearray()
        for value in chunk:
            scaled.append(max(0, min(255, round(((value - 128) * gain) + 128))))
        return bytes(scaled)

    if format_spec.width == 4:
        raw_samples = array("i")
        raw_samples.frombytes(chunk)
        scaled_samples = array(
            "i",
            (
                max(-2147483648, min(2147483647, int(round(sample * gain))))
                for sample in raw_samples
            ),
        )
        return scaled_samples.tobytes()

    if format_spec.width == 2:
        raw_samples = array("h")
        raw_samples.frombytes(chunk)
        scaled_samples = array("h", (clamp_int16(sample * gain) for sample in raw_samples))
        return scaled_samples.tobytes()

    return chunk


# Usage: resample a mono int16 PCM sample list so the detector can evaluate it at its supported sample rate.
# Parameters: samples - mono int16 PCM samples; source_rate - the original sampling rate; target_rate - the desired detector sampling rate.
# Return: a resampled mono int16 sample list at the target rate.
def resample_mono_int16(samples: list[int], source_rate: int, target_rate: int) -> list[int]:
    """Resample mono int16 PCM samples to a new sample rate using linear interpolation."""

    if not samples or source_rate == target_rate:
        return list(samples)

    target_length = max(1, round(len(samples) * target_rate / source_rate))
    resampled: list[int] = []
    step = source_rate / target_rate
    for target_index in range(target_length):
        source_position = target_index * step
        left_index = min(int(source_position), len(samples) - 1)
        right_index = min(left_index + 1, len(samples) - 1)
        fraction = source_position - left_index
        interpolated = (samples[left_index] * (1.0 - fraction)) + (samples[right_index] * fraction)
        resampled.append(clamp_int16(interpolated))

    return resampled


# Usage: resize a mono int16 PCM sample list to an exact sample count so detector frames stay aligned even after rounding differences during sample-rate conversion.
# Parameters: samples - mono int16 PCM samples; target_length - the exact number of samples required by the detector.
# Return: a mono int16 sample list containing exactly target_length samples.
def resize_mono_int16(samples: list[int], target_length: int) -> list[int]:
    """Resize mono int16 PCM samples to an exact length using linear interpolation."""

    if target_length <= 0:
        return []
    if not samples:
        return [0] * target_length
    if len(samples) == target_length:
        return list(samples)
    if len(samples) == 1:
        return [samples[0]] * target_length

    resized: list[int] = []
    scale = (len(samples) - 1) / max(target_length - 1, 1)
    for target_index in range(target_length):
        source_position = target_index * scale
        left_index = min(int(source_position), len(samples) - 1)
        right_index = min(left_index + 1, len(samples) - 1)
        fraction = source_position - left_index
        interpolated = (samples[left_index] * (1.0 - fraction)) + (samples[right_index] * fraction)
        resized.append(clamp_int16(interpolated))

    return resized


# Usage: encode a mono int16 sample list back into raw PCM bytes for the speech detector.
# Parameters: samples - mono int16 PCM samples.
# Return: raw mono 16-bit PCM bytes.
def encode_int16_samples(samples: list[int]) -> bytes:
    """Return raw PCM bytes for a mono int16 sample list."""

    encoded = array("h", (clamp_int16(sample) for sample in samples))
    return encoded.tobytes()


# Usage: prepare one raw capture frame for the speech detector by converting it to mono 16-bit PCM at the detector sample rate and exact detector frame length.
# Parameters: frame - raw PCM bytes from the microphone; format_spec - the capture format used to interpret the frame; target_rate - the detector sample rate; target_sample_count - the exact mono sample count required by the detector.
# Return: raw mono 16-bit PCM bytes ready for detector inference.
def prepare_frame_for_speech_detector(
    frame: bytes,
    format_spec: AudioFormatSpec,
    target_rate: int,
    target_sample_count: int,
) -> bytes:
    """Convert one capture frame into the PCM format expected by the speech detector."""

    mono_samples = pcm_frame_to_mono_int16(frame, format_spec)
    resampled_samples = resample_mono_int16(mono_samples, format_spec.rate, target_rate)
    resized_samples = resize_mono_int16(resampled_samples, target_sample_count)
    return encode_int16_samples(resized_samples)


# Usage: describe the canonical mono int16 PCM format that should be streamed to Wyoming STT regardless of the microphone's native capture format.
# Parameters: target_rate - the sample rate that should be used for the outgoing STT stream.
# Return: an AudioFormatSpec describing mono 16-bit PCM at the requested sample rate.
def build_stt_audio_format(target_rate: int = DEFAULT_VAD_SAMPLE_RATE) -> AudioFormatSpec:
    """Return the normalized PCM format used when streaming audio to STT."""

    return AudioFormatSpec(
        rate=target_rate,
        width=DEFAULT_SPEECH_DETECTOR_SAMPLE_WIDTH,
        channels=1,
        sample_format=PCM_SAMPLE_FORMAT_INT16,
    )


# Usage: convert one arbitrary microphone chunk into the canonical mono int16 PCM format used for Wyoming STT so float or int32 capture never reaches the network ambiguously.
# Parameters: chunk - raw PCM bytes from the active microphone capture stream; source_format - the actual capture format used to decode the chunk; target_format - the normalized STT format that should be produced.
# Return: raw PCM bytes encoded using target_format.
def convert_audio_chunk_for_stt(
    chunk: bytes,
    source_format: AudioFormatSpec,
    target_format: AudioFormatSpec,
) -> bytes:
    """Convert one captured microphone chunk into the normalized PCM format used for STT."""

    if not chunk:
        return b""
    if (
        source_format.rate == target_format.rate
        and source_format.width == target_format.width
        and source_format.channels == target_format.channels
        and source_format.sample_format == target_format.sample_format
    ):
        return chunk

    mono_samples = pcm_frame_to_mono_int16(chunk, source_format)
    resampled_samples = resample_mono_int16(mono_samples, source_format.rate, target_format.rate)
    return encode_int16_samples(resampled_samples)


class OpenMicVoiceDetector:
    """Turn continuous microphone PCM chunks into start/stop decisions for Wyoming STT sessions."""

    # Usage: create the always-on speech gate that watches microphone audio and decides when an utterance starts and ends.
    # Parameters: audio_format - the raw PCM format produced by the microphone capture stream; detector - optional speech detector override used by tests or alternate implementations; frame_ms - fixed frame duration used for detector analysis; pre_roll_ms - amount of raw audio to preserve before speech starts; speech_pad_ms - amount of leading and trailing non-speech context that should be preserved around a detected utterance; pause_buffer_ms - maximum amount of in-utterance silence that should be retained so natural pauses can still reach STT when speech resumes; start_window_frames - rolling frame window size used to smooth speech onset; start_trigger_frames - number of speech-positive frames required inside the rolling window to start an utterance; stop_silence_frames - number of consecutive non-speech frames required to stop an utterance; start_level_threshold - normalized 0.0-1.0 RMS level required before a frame can count toward speech start detection; start_speech_threshold - speech probability threshold required for a frame to count toward opening a new stream; continue_speech_threshold - speech probability threshold required to keep an active stream alive.
    # Return: None.
    def __init__(
        self,
        audio_format: AudioFormatSpec,
        detector: FrameSpeechDetector | None = None,
        frame_ms: int = DEFAULT_VAD_FRAME_MS,
        pre_roll_ms: int = DEFAULT_VAD_PRE_ROLL_MS,
        speech_pad_ms: int = DEFAULT_VAD_SPEECH_PAD_MS,
        pause_buffer_ms: int = DEFAULT_VAD_PAUSE_BUFFER_MS,
        start_window_frames: int = DEFAULT_VAD_START_WINDOW_FRAMES,
        start_trigger_frames: int = DEFAULT_VAD_START_TRIGGER_FRAMES,
        stop_silence_frames: int = DEFAULT_VAD_STOP_SILENCE_FRAMES,
        start_level_threshold: float = 0.0,
        start_speech_threshold: float = DEFAULT_VAD_START_SPEECH_THRESHOLD,
        continue_speech_threshold: float = DEFAULT_VAD_CONTINUE_SPEECH_THRESHOLD,
    ) -> None:
        """Initialize the open-microphone speech-detection state machine."""

        if frame_ms <= 0:
            raise ValueError("frame_ms must be greater than zero")
        if audio_format.rate <= 0 or audio_format.channels <= 0 or audio_format.width <= 0:
            raise ValueError("The microphone audio format must have positive rate, width, and channel counts")

        created_default_detector = detector is None
        if detector is None:
            detector = SileroSpeechDetector()

        self._audio_format = audio_format
        self._frame_ms = frame_ms
        self._detector_sample_rate = choose_detector_sample_rate(audio_format.rate)
        self._detector_frame_samples = max(1, round(self._detector_sample_rate * (frame_ms / 1000.0)))
        self._source_frame_samples = max(1, round(audio_format.rate * (frame_ms / 1000.0)))
        self._source_frame_bytes = self._source_frame_samples * audio_format.frame_bytes()
        self._pre_roll_frames: deque[AnalyzedAudioFrame] = deque(maxlen=max(1, round(pre_roll_ms / frame_ms)))
        self._speech_pad_frames = max(0, round(speech_pad_ms / frame_ms))
        self._start_window_frames = max(1, start_window_frames)
        self._start_trigger_frames = max(1, min(start_trigger_frames, self._start_window_frames))
        self._stop_silence_frames = max(1, stop_silence_frames)
        self._start_level_threshold = max(0.0, min(1.0, float(start_level_threshold)))
        self._start_speech_threshold = max(0.0, min(1.0, float(start_speech_threshold)))
        self._continue_speech_threshold = max(0.0, min(1.0, float(continue_speech_threshold)))
        self._speech_resume_buffer_frames = max(1, min(self._stop_silence_frames, round(pause_buffer_ms / frame_ms)))
        self._recent_voiced_flags: deque[bool] = deque(maxlen=self._start_window_frames)
        self._pending_bytes = bytearray()
        self._pending_silence_frames: deque[bytes] = deque(maxlen=self._speech_resume_buffer_frames)
        self._speech_active = False
        self._silent_frame_count = 0
        self._detector = detector

        if created_default_detector and getattr(self._detector, "chunk_bytes", self._detector_frame_samples * 2) != (
            self._detector_frame_samples * DEFAULT_SPEECH_DETECTOR_SAMPLE_WIDTH
        ):
            raise ValueError(
                "The default Silero detector requires frame_ms that maps to its fixed detector frame size. "
                "Use the default frame_ms or supply a custom detector override for tests."
            )

    # Usage: collect the buffered lead-in audio that should be sent when a new STT stream starts, including a small amount of prefix padding before the first speech-confirmed frame inside the current rolling start window.
    # Parameters: none.
    # Return: a list of raw PCM frames from the start of the buffered pre-roll through the trigger frame.
    def _collect_start_audio_chunks(self) -> list[bytes]:
        """Return the complete buffered pre-roll audio for a newly detected utterance.

        The entire pre-roll window is forwarded rather than trimmed back from the
        first speech-confirmed frame. Speech onsets are often gradual - the first
        syllable may stay below the start thresholds for a few frames - so trimming
        from the first qualifying frame could drop the actual beginning of the
        utterance. Leading silence in the pre-roll is harmless to STT.
        """

        return [analyzed_frame.frame for analyzed_frame in self._pre_roll_frames]

    # Usage: collect a short tail of buffered non-speech frames that should still be sent when an utterance ends so STT receives a natural trailing pad instead of an abrupt cutoff.
    # Parameters: none.
    # Return: a list containing at most the configured trailing padding frames from the buffered silence queue.
    def _collect_stop_audio_chunks(self) -> list[bytes]:
        """Return the trailing silence padding that should accompany the end of an utterance."""

        if self._speech_pad_frames <= 0 or not self._pending_silence_frames:
            return []

        buffered_silence_frames = list(self._pending_silence_frames)
        return buffered_silence_frames[-self._speech_pad_frames :]

    # Usage: consume one raw microphone chunk and decide whether the controller should start or stop an STT stream.
    # Parameters: chunk - raw PCM bytes from the active microphone capture stream.
    # Return: a VoiceActivityDecision containing any buffered audio that should be forwarded to STT and flags for utterance boundaries.
    def process_audio_chunk(self, chunk: bytes) -> VoiceActivityDecision:
        """Process one microphone chunk and return utterance start/stop decisions."""

        decision = VoiceActivityDecision()
        if not chunk:
            return decision

        self._pending_bytes.extend(chunk)
        while len(self._pending_bytes) >= self._source_frame_bytes:
            frame = bytes(self._pending_bytes[: self._source_frame_bytes])
            del self._pending_bytes[: self._source_frame_bytes]

            frame_level = measure_pcm_level(frame, self._audio_format)
            speech_probability = self._detector.measure_speech_probability(
                prepare_frame_for_speech_detector(
                    frame,
                    self._audio_format,
                    self._detector_sample_rate,
                    self._detector_frame_samples,
                ),
                self._detector_sample_rate,
            )
            detected_speech = speech_probability >= self._continue_speech_threshold
            passes_start_level_gate = frame_level >= self._start_level_threshold
            counts_as_start_speech = (
                speech_probability >= self._start_speech_threshold and passes_start_level_gate
            )

            analyzed_frame = AnalyzedAudioFrame(
                frame=frame,
                detected_speech=detected_speech,
                counts_as_start_speech=counts_as_start_speech,
            )

            if self._speech_active:
                if detected_speech:
                    if self._pending_silence_frames:
                        decision.audio_chunks.extend(self._pending_silence_frames)
                        self._pending_silence_frames.clear()
                    decision.audio_chunks.append(frame)
                    self._silent_frame_count = 0
                else:
                    self._pending_silence_frames.append(frame)
                    self._silent_frame_count += 1
                    if self._silent_frame_count >= self._stop_silence_frames:
                        decision.audio_chunks.extend(self._collect_stop_audio_chunks())
                        decision.should_stop_stream = True
                        self._speech_active = False
                        self._silent_frame_count = 0
                        self._recent_voiced_flags.clear()
                        self._pre_roll_frames.clear()
                        self._pending_silence_frames.clear()
                continue

            self._pre_roll_frames.append(analyzed_frame)
            self._recent_voiced_flags.append(counts_as_start_speech)
            voiced_count = sum(1 for flag in self._recent_voiced_flags if flag)
            if (
                counts_as_start_speech
                and len(self._recent_voiced_flags) >= self._start_trigger_frames
                and voiced_count >= self._start_trigger_frames
            ):
                decision.should_start_stream = True
                decision.audio_chunks.extend(self._collect_start_audio_chunks())
                self._pre_roll_frames.clear()
                self._pending_silence_frames.clear()
                self._speech_active = True
                self._silent_frame_count = 0
                self._recent_voiced_flags.clear()

        return decision

    # Usage: update the minimum normalized RMS level required before frames can trigger a new speech start.
    # Parameters: start_level_threshold - normalized 0.0-1.0 RMS level used by the start gate.
    # Return: None.
    def set_start_level_threshold(self, start_level_threshold: float) -> None:
        """Update the microphone start-level gate threshold used for future speech onset decisions."""

        self._start_level_threshold = max(0.0, min(1.0, float(start_level_threshold)))

    # Usage: update how many consecutive silent frames end the current utterance while it is active.
    # Parameters: stop_silence_frames - the number of silent frames required before the utterance ends.
    # Return: None.
    def set_stop_silence_frames(self, stop_silence_frames: int) -> None:
        """Update the trailing-silence hangover used to end the current utterance."""

        self._stop_silence_frames = max(1, int(stop_silence_frames))

    # Usage: clear all buffered microphone and detector state after a session completes or when the controller must ignore audio temporarily.
    # Parameters: none.
    # Return: None.
    def reset(self) -> None:
        """Clear buffered audio and forget any in-progress speech detection state."""

        self._pending_bytes.clear()
        self._pre_roll_frames.clear()
        self._recent_voiced_flags.clear()
        self._pending_silence_frames.clear()
        self._speech_active = False
        self._silent_frame_count = 0
        self._detector.reset()
