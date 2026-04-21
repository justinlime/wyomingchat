"""Tests for pure audio-format helpers that do not require active device I/O."""

from __future__ import annotations

import pytest

QtMultimedia = pytest.importorskip("PySide6.QtMultimedia", exc_type=ImportError)
QAudioFormat = QtMultimedia.QAudioFormat

from wyomingchat.audio import build_format_spec
from wyomingchat.audio_types import (
    AudioFormatSpec,
    PCM_SAMPLE_FORMAT_FLOAT32,
    PCM_SAMPLE_FORMAT_INT32,
    describe_audio_format,
)


# Usage: verify that Qt float capture formats retain their float32 identity when converted into the app's lightweight AudioFormatSpec abstraction.
# Parameters: none.
# Return: None.
def test_build_format_spec_preserves_float32_sample_format() -> None:
    """Ensure Qt float sample formats are not collapsed into generic 4-byte PCM."""

    qt_format = QAudioFormat()
    qt_format.setSampleRate(48_000)
    qt_format.setChannelCount(2)
    qt_format.setSampleFormat(QAudioFormat.SampleFormat.Float)

    format_spec = build_format_spec(qt_format)

    assert format_spec.rate == 48_000
    assert format_spec.channels == 2
    assert format_spec.width == 4
    assert format_spec.sample_format == PCM_SAMPLE_FORMAT_FLOAT32


# Usage: verify that Qt int32 capture formats remain distinguishable from float32 so downstream PCM decoding can choose the correct conversion path.
# Parameters: none.
# Return: None.
def test_build_format_spec_preserves_int32_sample_format() -> None:
    """Ensure Qt int32 sample formats are preserved distinctly from float32 capture formats."""

    qt_format = QAudioFormat()
    qt_format.setSampleRate(44_100)
    qt_format.setChannelCount(1)
    qt_format.setSampleFormat(QAudioFormat.SampleFormat.Int32)

    format_spec = build_format_spec(qt_format)

    assert format_spec.width == 4
    assert format_spec.sample_format == PCM_SAMPLE_FORMAT_INT32


# Usage: verify that the human-readable audio-format description used by controller logging includes the resolved sample-format name for troubleshooting.
# Parameters: none.
# Return: None.
def test_describe_audio_format_includes_sample_format_name() -> None:
    """Ensure audio-format descriptions surface the sample-format detail needed for capture debugging."""

    description = describe_audio_format(
        AudioFormatSpec(rate=16_000, width=4, channels=1, sample_format=PCM_SAMPLE_FORMAT_FLOAT32)
    )

    assert description == "16000 Hz, 1 channel, 32-bit float32"


# Usage: verify that the drain delay uses the larger of the estimate and sink buffer, never their sum.
# Parameters: none.
# Return: None.
def test_drain_delay_never_double_counts_sink_buffer() -> None:
    """Ensure sentence chaining does not pause for nearly twice the remaining audio."""

    from wyomingchat.audio import _drain_delay_for

    # The wall-clock estimate already includes the sink-queued audio, so adding the
    # sink measurement on top would yield ~2x the remaining time.
    assert _drain_delay_for(500.0, 500.0) == 600  # 500 + 100ms margin, not ~1080
    assert _drain_delay_for(500.0, 0.0) == 600
    assert _drain_delay_for(0.0, 500.0) == 600
    assert _drain_delay_for(0.0, 0.0) == 100


# Usage: verify that a sink buffer larger than the estimate still protects the tail.
# Parameters: none.
# Return: None.
def test_drain_delay_uses_larger_measurement_to_protect_tail() -> None:
    """Ensure the drain waits long enough when the sink reports more buffered audio."""

    from wyomingchat.audio import _drain_delay_for

    assert _drain_delay_for(200.0, 1500.0) == 1600
    assert _drain_delay_for(1500.0, 200.0) == 1600
