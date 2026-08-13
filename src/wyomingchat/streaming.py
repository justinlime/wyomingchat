"""Streaming transcript chunking helpers for incremental TTS synthesis.

The STT service delivers streaming partial transcripts. Instead of waiting for
the full utterance and then synthesizing the entire text in one request, the
controller feeds partials through this module to confirm complete sentences as
soon as they are stable. Each confirmed sentence is synthesized immediately,
so the TTS server works on the first sentences while the user is still
speaking the rest - hiding synthesis latency behind the remaining speech.
"""

from __future__ import annotations

SENTENCE_BOUNDARY_CHARS = ".!?"


# Usage: split transcript text into completed sentences and the trailing remainder.
# Parameters: text - the transcript text to split.
# Return: a tuple of (completed sentences, trailing un-bounded remainder).
def split_completed_sentences(text: str) -> tuple[list[str], str]:
    """Split text into sentences ending with a boundary character and the trailing remainder."""

    sentences: list[str] = []
    start = 0
    for index, char in enumerate(text):
        if char in SENTENCE_BOUNDARY_CHARS:
            is_end = index + 1 >= len(text) or text[index + 1].isspace()
            if not is_end:
                continue
            sentence = text[start : index + 1].strip()
            if sentence:
                sentences.append(sentence)
            start = index + 1

    return sentences, text[start:].strip()


class StreamingTranscriptChunker:
    """Emit stable, sentence-bounded transcript chunks for incremental synthesis.

    A sentence is only confirmed once it has appeared unchanged in a small
    number of consecutive partial updates, which protects against STT
    mid-stream revisions of words that have not yet crossed a boundary.
    Sentences without a hard boundary are never confirmed here; they are
    finalized through finish() when the utterance ends.
    """

    # Usage: create a chunker that confirms completed sentences after a stability window.
    # Parameters: min_chars - minimum character length before a sentence can be confirmed; stability - consecutive partial updates required with identical sentence content before confirming.
    # Return: None.
    def __init__(self, min_chars: int = 3, stability: int = 2) -> None:
        """Initialize the streaming transcript chunker."""

        self._min_chars = max(1, int(min_chars))
        self._stability = max(1, int(stability))
        self._committed: list[str] = []
        self._last_uncommitted: list[str] = []
        self._last_streaks: list[int] = []

    @property
    # Usage: expose the sentences that have already been confirmed.
    # Parameters: none.
    # Return: a copy of the list of committed sentence texts.
    def committed(self) -> list[str]:
        """Return the sentences confirmed so far."""

        return list(self._committed)

    # Usage: process the latest partial transcript and return any newly confirmed sentences.
    # Parameters: text - the current streaming partial transcript text.
    # Return: a list of newly confirmed sentence texts that should be synthesized immediately.
    def consume_partial(self, text: str) -> list[str]:
        """Return newly confirmed sentences from the latest partial transcript."""

        sentences, _remainder = split_completed_sentences(text)

        committed_index = 0
        uncommitted: list[str] = []
        for sentence in sentences:
            if committed_index < len(self._committed) and sentence == self._committed[committed_index]:
                committed_index += 1
                continue
            uncommitted.append(sentence)

        previous = self._last_uncommitted
        previous_streaks = self._last_streaks

        new_commits: list[str] = []
        streaks: list[int] = []
        committed_positions: set[int] = set()
        for index, sentence in enumerate(uncommitted):
            if index < len(previous) and sentence == previous[index]:
                streak = previous_streaks[index] + 1
            else:
                streak = 1
            streaks.append(streak)
            if streak >= self._stability and len(sentence) >= self._min_chars:
                new_commits.append(sentence)
                self._committed.append(sentence)
                committed_positions.add(index)

        self._last_uncommitted = [
            sentence for index, sentence in enumerate(uncommitted) if index not in committed_positions
        ]
        self._last_streaks = [
            streak for index, streak in enumerate(streaks) if index not in committed_positions
        ]
        return new_commits

    # Usage: finalize the transcript when the utterance ends and return all sentences that still need synthesis.
    # Parameters: final_text - the final transcript text delivered by the STT service.
    # Return: the remaining sentence texts (including the un-bounded tail, which is final now).
    def finish(self, final_text: str) -> list[str]:
        """Return the remaining sentences from the final transcript that need synthesis."""

        sentences, trailing = split_completed_sentences(final_text)

        remaining: list[str] = []
        committed_index = 0
        for sentence in sentences:
            if committed_index < len(self._committed) and sentence == self._committed[committed_index]:
                committed_index += 1
                continue
            remaining.append(sentence)

        if trailing:
            remaining.append(trailing)

        return [sentence for sentence in remaining if sentence]
