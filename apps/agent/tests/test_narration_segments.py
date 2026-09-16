"""Tests for how narration normalizes the model's `segments` tool output."""

import json

import pytest

import narration


class TestMalformedSegmentsFromTheModel:
    """The segments come from an LLM tool call, so their SHAPE is the model's output, not ours.

    A live errand resolution died on `AttributeError: 'str' object has no attribute 'get'`
    during the sprint-048 close, intermittently: the model returned one segment as a bare
    string instead of an object. Both helpers assumed dicts — `_segments_to_text` on
    `seg["text"]` and `_segments_to_segment_objects` on `seg.get(...)`. Constraint 9: never
    model the other side's shape, validate it.
    """

    def test_a_bare_string_segment_is_narration_not_a_crash(self):
        segments = [
            "The cart wheel finally turns.",
            {"character": "COMPANION_KAEL", "emotion": "calm", "text": "Done."},
        ]
        objs = narration._segments_to_segment_objects(segments)
        assert [o.text for o in objs] == ["The cart wheel finally turns.", "Done."]
        assert objs[0].character == "DM_NARRATOR"
        assert narration._segments_to_text(segments) == "The cart wheel finally turns. Done."

    def test_a_segment_missing_character_or_emotion_still_narrates(self):
        objs = narration._segments_to_segment_objects([{"text": "Only text."}])
        assert [o.character for o in objs] == ["DM_NARRATOR"]
        assert [o.emotion for o in objs] == ["neutral"]

    def test_a_payload_that_normalizes_to_nothing_raises(self):
        """Coercion must not become silence. Dropping every segment leaves an errand that
        "resolved" with no narration — in an audio-first game the player just gets nothing,
        which is worse than the crash this normalizer replaced. Segments keyed on names we
        do not know is a malformed response, not a recoverable one."""
        with pytest.raises(ValueError, match="no speakable narration"):
            narration._normalize_segments_or_raise([{"speaker": "DM", "line": "Lost."}])
        with pytest.raises(ValueError, match="no speakable narration"):
            narration._normalize_segments_or_raise([{"text": "   "}, 42])

    def test_an_unusable_segment_is_dropped_not_raised(self):
        assert narration._segments_to_segment_objects([{"character": "X"}, 42, None, "  "]) == []
        assert narration._segments_to_text([{"character": "X"}, 42, None, "  "]) == ""

    def test_a_json_encoded_segments_array_is_decoded_not_discarded(self):
        raw = json.dumps(
            [
                {"character": "DM_NARRATOR", "emotion": "neutral", "text": "Kael emerges from the mist."},
                {"character": "COMPANION_KAEL", "emotion": "weary", "text": "Millhaven is quiet."},
            ],
            indent=2,
        )
        objs = narration._normalize_segments_or_raise(raw)
        assert [(o.character, o.emotion, o.text) for o in objs] == [
            ("DM_NARRATOR", "neutral", "Kael emerges from the mist."),
            ("COMPANION_KAEL", "weary", "Millhaven is quiet."),
        ]

    def test_a_json_array_missing_its_closing_bracket_still_narrates(self):
        """The shape that red the Sprint 50 close, verbatim from the gate log: three complete
        segments, `stop_reason='tool_use'` at 308 of 500 tokens — the model simply never wrote the
        `]`. Nothing was cut off and nothing is malformed inside, so refusing it spends a whole
        errand's narration on one absent character."""
        raw = (
            '[\n  {\n    "character": "DM_NARRATOR", "emotion": "calm",\n'
            '    "text": "Kael emerges from the mist-shrouded path."\n  },\n'
            '  {\n    "character": "COMPANION_KAEL", "emotion": "calm",\n'
            '    "text": "It\'s there. The mark you described."\n  }\n'
        )
        objs = narration._normalize_segments_or_raise(raw)
        assert [(o.character, o.text) for o in objs] == [
            ("DM_NARRATOR", "Kael emerges from the mist-shrouded path."),
            ("COMPANION_KAEL", "It's there. The mark you described."),
        ]

    def test_a_trailing_half_written_segment_is_dropped_and_the_rest_narrates(self):
        raw = '[{"character": "DM_NARRATOR", "emotion": "calm", "text": "The forge cools."}, {"character": "COMPAN'
        objs = narration._normalize_segments_or_raise(raw)
        assert [o.text for o in objs] == ["The forge cools."]

    @pytest.mark.parametrize(
        "raw",
        [
            pytest.param('{"text": "an object, not a list"}', id="json-object"),
            pytest.param('"a json string"', id="json-string"),
            pytest.param("[{not json", id="invalid-json"),
            pytest.param("Kael returns.", id="plain-prose"),
        ],
    )
    def test_a_string_that_does_not_decode_to_a_list_still_hits_the_floor(self, raw):
        with pytest.raises(ValueError, match="no speakable narration"):
            narration._normalize_segments_or_raise(raw)
