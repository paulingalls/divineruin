import json

import pytest

import narration


class TestTheNarrationToolSchema:
    """Construct vendor schemas because strict validation closes nested objects too."""

    def test_the_tool_is_built_strict_with_every_object_closed(self):
        tool = json.loads(json.dumps(narration._build_narration_tool(["COMPANION_KAEL"])))
        schema = tool["input_schema"]

        assert tool["strict"] is True
        assert schema["additionalProperties"] is False
        assert schema["properties"]["segments"]["items"]["additionalProperties"] is False

    def test_strict_requires_every_declared_property_to_be_required(self):
        """Strict vendor schemas require every property to appear in required."""
        tool = json.loads(json.dumps(narration._build_narration_tool(["COMPANION_KAEL"])))
        schema = tool["input_schema"]
        item = schema["properties"]["segments"]["items"]

        assert set(schema["required"]) == set(schema["properties"])
        assert set(item["required"]) == set(item["properties"])


class TestMalformedSegmentsFromTheModel:
    """Validate real vendor narration shapes instead of assuming a dictionary."""

    def test_a_bare_string_segment_is_narration_not_a_crash(self):
        segments = [
            "The cart wheel finally turns.",
            {"character": "COMPANION_KAEL", "emotion": "calm", "text": "Done."},
        ]
        objs = narration._normalize_segments(segments)
        assert [o.text for o in objs] == ["The cart wheel finally turns.", "Done."]
        assert objs[0].character == "DM_NARRATOR"

    def test_a_segment_missing_character_or_emotion_still_narrates(self):
        objs = narration._normalize_segments([{"text": "Only text."}])
        assert [o.character for o in objs] == ["DM_NARRATOR"]
        assert [o.emotion for o in objs] == ["neutral"]

    def test_a_payload_that_normalizes_to_nothing_raises(self):
        """Tolerance must still refuse a response that produced nothing usable."""
        with pytest.raises(ValueError, match="no speakable narration"):
            narration._normalize_segments_or_raise([{"speaker": "DM", "line": "Lost."}])
        with pytest.raises(ValueError, match="no speakable narration"):
            narration._normalize_segments_or_raise([{"text": "   "}, 42])

    def test_an_unusable_segment_is_dropped_from_a_mixed_list(self):
        objs = narration._normalize_segments([{"text": "Still here."}, {"character": "X"}, 42, None, "  "])

        assert [(o.character, o.emotion, o.text) for o in objs] == [("DM_NARRATOR", "neutral", "Still here.")]

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
        """A missing closing bracket is tolerated only when usable tokens remain."""
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
