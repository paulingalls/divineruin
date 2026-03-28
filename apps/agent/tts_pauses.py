"""Shared pause/silence constants and text-chunking logic for TTS.

Used by both the live agent (agent.py) and the pre-render pipeline
(tts_prerender.py) to ensure consistent pause behavior.
"""

import re
from dataclasses import dataclass

PAUSE_PATTERN = re.compile(r"(\.{2,}|…|—|–)")

PAUSE_DURATIONS: dict[str, float] = {
    "...": 0.4,
    "…": 0.4,
    "—": 0.2,
    "–": 0.2,
}

SENTENCE_END_PAUSE: float = 0.6
PARAGRAPH_PAUSE: float = 0.8

# Matches sentence-ending punctuation, optionally followed by a closing quote
_SENTENCE_END_RE = re.compile(r'[.!?][""\u201d]?\s*$')

# Split sentences at .!? (optionally followed by a closing quote) then whitespace.
# Uses alternation for fixed-width lookbehinds (Python requires fixed-width).
_SENTENCE_SPLIT_RE = re.compile(r'(?:(?<=[.!?])(?![""\u201d])|(?<=[.!?][""\u201d]))\s+')


@dataclass(frozen=True)
class TTSChunk:
    """A piece of text or a silence gap to insert between speech."""

    text: str | None = None
    silence: float | None = None


def chunk_text_with_pauses(text: str) -> list[TTSChunk]:
    """Split text into speech chunks and silence gaps.

    Handles:
    - Paragraph breaks (\\n\\n) -> PARAGRAPH_PAUSE silence
    - Pause markers (..., \u2026, \u2014, \u2013) -> PAUSE_DURATIONS silence
    - Sentence endings (.!?) -> SENTENCE_END_PAUSE silence after each sentence
    """
    chunks: list[TTSChunk] = []

    paragraphs = re.split(r"\n\n+", text)

    for i, paragraph in enumerate(paragraphs):
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        sentences = _SENTENCE_SPLIT_RE.split(paragraph)

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            # Split sentence on pause markers
            parts = PAUSE_PATTERN.split(sentence)
            for part in parts:
                pause = PAUSE_DURATIONS.get(part)
                if pause is not None:
                    chunks.append(TTSChunk(silence=pause))
                else:
                    cleaned = part.strip()
                    if cleaned and re.sub(r"[^\w]", "", cleaned):
                        chunks.append(TTSChunk(text=cleaned))

            # Sentence-end pause
            if _SENTENCE_END_RE.search(sentence):
                chunks.append(TTSChunk(silence=SENTENCE_END_PAUSE))

        # Paragraph pause between paragraphs (not after the last one)
        if i < len(paragraphs) - 1:
            chunks.append(TTSChunk(silence=PARAGRAPH_PAUSE))

    return chunks
