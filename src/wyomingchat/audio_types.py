"""Shared audio datatypes used by both Qt-bound and pure-Python modules."""

from __future__ import annotations

from dataclasses import dataclass

from .constants import DEFAULT_AUDIO_CHANNELS, DEFAULT_AUDIO_RATE, DEFAULT_AUDIO_WIDTH

PCM_SAMPLE_FORMAT_UINT8 = "uint8"
PCM_SAMPLE_FORMAT_INT16 = "int16"
PCM_SAMPLE_FORMAT_INT32 = "int32"
PCM_SAMPLE_FORMAT_FLOAT32 = "float32"


@dataclass(slots=True)
class AudioFormatSpec:
    """Describe the raw PCM format used for capture and playback."""

    rate: int = DEFAULT_AUDIO_RATE
    width: int = DEFAULT_AUDIO_WIDTH
    channels: int = DEFAULT_AUDIO_CHANNELS
    sample_format: str = PCM_SAMPLE_FORMAT_INT16

    # Usage: calculate the number of bytes in a single PCM frame for this format.
    # Parameters: none.
    # Return: the byte width of one audio frame.
    def frame_bytes(self) -> int:
        """Return the byte width of a single PCM frame."""

        return self.width * self.channels

    # Usage: estimate how long a number of raw PCM bytes will play for in milliseconds.
    # Parameters: byte_count - the number of PCM bytes to convert into a duration estimate.
    # Return: the estimated playback or capture duration in milliseconds.
    def bytes_to_duration_ms(self, byte_count: int) -> float:
        """Convert raw PCM byte counts into milliseconds for the current format."""

        if byte_count <= 0 or self.rate <= 0 or self.frame_bytes() <= 0:
            return 0.0

        return (byte_count / (self.rate * self.frame_bytes())) * 1000.0


# Usage: turn an AudioFormatSpec into a concise human-readable description for logs and debugging output.
# Parameters: format_spec - the audio format that should be described.
# Return: a descriptive string containing sample rate, channel count, bit depth, and sample format name.
def describe_audio_format(format_spec: AudioFormatSpec) -> str:
    """Return a human-readable description of an audio format specification."""

    channel_label = "channel" if format_spec.channels == 1 else "channels"
    return (
        f"{format_spec.rate} Hz, "
        f"{format_spec.channels} {channel_label}, "
        f"{format_spec.width * 8}-bit {format_spec.sample_format}"
    )
