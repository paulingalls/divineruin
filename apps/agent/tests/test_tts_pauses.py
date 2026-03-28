"""Tests for the shared TTS pause constants and text-chunking logic."""

from tts_pauses import (
    PARAGRAPH_PAUSE,
    SENTENCE_END_PAUSE,
    TTSChunk,
    chunk_text_with_pauses,
)


class TestChunkTextWithPauses:
    def test_simple_sentence(self):
        chunks = chunk_text_with_pauses("Hello world.")
        assert chunks == [
            TTSChunk(text="Hello world."),
            TTSChunk(silence=SENTENCE_END_PAUSE),
        ]

    def test_two_sentences(self):
        chunks = chunk_text_with_pauses("Hello world. Goodbye world.")
        assert chunks == [
            TTSChunk(text="Hello world."),
            TTSChunk(silence=SENTENCE_END_PAUSE),
            TTSChunk(text="Goodbye world."),
            TTSChunk(silence=SENTENCE_END_PAUSE),
        ]

    def test_ellipsis_pause(self):
        chunks = chunk_text_with_pauses("Wait for it... there!")
        texts = [c.text for c in chunks if c.text]
        silences = [c.silence for c in chunks if c.silence]
        assert "Wait for it" in texts[0]
        assert "there!" in texts[1]
        assert 0.4 in silences  # ellipsis pause

    def test_unicode_ellipsis_pause(self):
        chunks = chunk_text_with_pauses("Wait for it\u2026 there!")
        silences = [c.silence for c in chunks if c.silence]
        assert 0.4 in silences

    def test_em_dash_pause(self):
        chunks = chunk_text_with_pauses("The city fell \u2014 no one survived.")
        texts = [c.text for c in chunks if c.text]
        silences = [c.silence for c in chunks if c.silence]
        assert 0.2 in silences  # em dash pause
        assert len(texts) == 2

    def test_en_dash_pause(self):
        chunks = chunk_text_with_pauses("The city fell \u2013 no one survived.")
        silences = [c.silence for c in chunks if c.silence]
        assert 0.2 in silences

    def test_paragraph_break(self):
        chunks = chunk_text_with_pauses("First paragraph.\n\nSecond paragraph.")
        silences = [c.silence for c in chunks if c.silence]
        assert PARAGRAPH_PAUSE in silences

    def test_multiple_paragraph_breaks(self):
        text = "Para one.\n\nPara two.\n\nPara three."
        chunks = chunk_text_with_pauses(text)
        paragraph_pauses = [c for c in chunks if c.silence == PARAGRAPH_PAUSE]
        assert len(paragraph_pauses) == 2  # between 1-2 and 2-3, not after last

    def test_no_paragraph_pause_after_last(self):
        chunks = chunk_text_with_pauses("Only one paragraph.")
        paragraph_pauses = [c for c in chunks if c.silence == PARAGRAPH_PAUSE]
        assert len(paragraph_pauses) == 0

    def test_exclamation_and_question_marks(self):
        chunks = chunk_text_with_pauses("What? Really! Yes.")
        sentence_pauses = [c for c in chunks if c.silence == SENTENCE_END_PAUSE]
        assert len(sentence_pauses) == 3

    def test_empty_input(self):
        assert chunk_text_with_pauses("") == []

    def test_whitespace_only(self):
        assert chunk_text_with_pauses("   \n\n   ") == []

    def test_text_without_sentence_ending(self):
        chunks = chunk_text_with_pauses("No punctuation here")
        assert chunks == [TTSChunk(text="No punctuation here")]

    def test_sentence_ending_with_closing_quote(self):
        chunks = chunk_text_with_pauses('She said "hello."')
        sentence_pauses = [c for c in chunks if c.silence == SENTENCE_END_PAUSE]
        assert len(sentence_pauses) == 1

    def test_prologue_excerpt(self):
        """Test with actual prologue-style text containing paragraphs and em dashes."""
        text = (
            "Before the breaking, Aethos was whole. "
            "A world shaped by gods.\n\n"
            "Then the Veil cracked \u2014 something seeped in."
        )
        chunks = chunk_text_with_pauses(text)
        texts = [c.text for c in chunks if c.text]
        silences = [c.silence for c in chunks if c.silence]

        # Should have text chunks
        assert len(texts) >= 3
        # Should have paragraph pause
        assert PARAGRAPH_PAUSE in silences
        # Should have em dash pause
        assert 0.2 in silences
        # Should have sentence end pauses
        assert SENTENCE_END_PAUSE in silences

    def test_mixed_pause_markers_in_sentence(self):
        chunks = chunk_text_with_pauses("Wait... no \u2014 stop.")
        silences = [c.silence for c in chunks if c.silence]
        assert 0.4 in silences  # ellipsis
        assert 0.2 in silences  # em dash
        assert SENTENCE_END_PAUSE in silences  # sentence end
