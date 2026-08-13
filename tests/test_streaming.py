"""Tests for streaming transcript chunking used by incremental TTS synthesis."""

from __future__ import annotations

from wyomingchat.streaming import StreamingTranscriptChunker, split_completed_sentences


# Usage: verify that completed sentences are split out from the trailing remainder.
# Parameters: none.
# Return: None.
def test_split_completed_sentences_handles_boundaries_and_remainder() -> None:
    """Ensure text splits into completed sentences plus the un-bounded tail."""

    sentences, remainder = split_completed_sentences(
        "Turn on the lights. Then set the temperature to 20. Thank you"
    )

    assert sentences == ["Turn on the lights.", "Then set the temperature to 20."]
    assert remainder == "Thank you"


# Usage: verify that decimals and ellipses do not fragment sentences prematurely.
# Parameters: none.
# Return: None.
def test_split_completed_sentences_ignores_inner_periods() -> None:
    """Ensure '3.5' and '...' are not treated as sentence boundaries."""

    sentences, remainder = split_completed_sentences("The price is 3.5 dollars... okay")

    assert sentences == ["The price is 3.5 dollars..."]
    assert remainder == "okay"


# Usage: verify that a sentence is only confirmed after it is stable across consecutive partials.
# Parameters: none.
# Return: None.
def test_consume_partial_requires_stability_before_confirming() -> None:
    """Ensure single-appearance sentences stay pending until stable."""

    chunker = StreamingTranscriptChunker(stability=2)

    assert chunker.consume_partial("Turn on the lights.") == []
    assert chunker.consume_partial("Turn on the lights. Then set") == ["Turn on the lights."]


# Usage: verify that un-bounded partial text is never confirmed early.
# Parameters: none.
# Return: None.
def test_consume_partial_never_confirms_unbounded_text() -> None:
    """Ensure text without a hard boundary is never synthesized mid-stream."""

    chunker = StreamingTranscriptChunker(stability=1)

    assert chunker.consume_partial("Turn on the") == []
    assert chunker.consume_partial("Turn on the lights") == []


# Usage: verify that mid-stream revisions of a pending sentence delay its confirmation.
# Parameters: none.
# Return: None.
def test_consume_partial_absorbs_revisions_before_commit() -> None:
    """Ensure a revised pending sentence re-stabilizes before confirmation."""

    chunker = StreamingTranscriptChunker(stability=2)

    assert chunker.consume_partial("Turn on the light.") == []
    assert chunker.consume_partial("Turn on the lights.") == []  # revision resets the streak
    assert chunker.consume_partial("Turn on the lights. Now") == ["Turn on the lights."]


# Usage: verify that multiple sentences in one partial are confirmed in order.
# Parameters: none.
# Return: None.
def test_consume_partial_confirms_multiple_sentences_in_order() -> None:
    """Ensure several completed sentences confirm together in utterance order."""

    chunker = StreamingTranscriptChunker(stability=2)

    assert chunker.consume_partial("One. Two.") == []
    assert chunker.consume_partial("One. Two. Three.") == ["One.", "Two."]


# Usage: verify that finish() returns the remaining sentences including the un-bounded tail.
# Parameters: none.
# Return: None.
def test_finish_returns_remaining_and_tail() -> None:
    """Ensure finalization hands back unconfirmed sentences plus the final tail."""

    chunker = StreamingTranscriptChunker(stability=2)

    assert chunker.consume_partial("One. Two.") == []
    assert chunker.consume_partial("One. Two.") == ["One.", "Two."]
    assert chunker.finish("One. Two. Three") == ["Three"]


# Usage: verify that finish() skips sentences already committed during streaming.
# Parameters: none.
# Return: None.
def test_finish_skips_committed_sentences() -> None:
    """Ensure already-confirmed sentences are not synthesized a second time."""

    chunker = StreamingTranscriptChunker(stability=2)

    assert chunker.consume_partial("One. Two.") == []
    assert chunker.consume_partial("One. Two.") == ["One.", "Two."]
    assert chunker.finish("One. Two.") == []


# Usage: verify that empty input produces no output.
# Parameters: none.
# Return: None.
def test_finish_handles_empty_final_text() -> None:
    """Ensure an empty final transcript yields no synthesis work."""

    chunker = StreamingTranscriptChunker()

    assert chunker.finish("") == []
