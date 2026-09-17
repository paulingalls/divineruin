"""Tests for how narration normalizes the model's `segments` tool output."""

import json
import subprocess
from pathlib import Path

import pytest

import narration

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _repository_files() -> tuple[Path, ...]:
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            "apps",
            "packages",
            "scripts",
        ],
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return tuple(Path(path.decode()) for path in result.stdout.split(b"\0") if path)


def _files_containing(needle: bytes, paths: tuple[Path, ...]) -> list[str]:
    return [str(path) for path in paths if (_REPO_ROOT / path).is_file() and needle in (_REPO_ROOT / path).read_bytes()]


def _dead_helper_names() -> tuple[str, str]:
    return (
        "_" + "_".join(("segments", "to", "text")),
        "_" + "_".join(("segments", "to", "segment", "objects")),
    )


def test_dead_narration_helper_attributes_are_absent():
    present = [name for name in _dead_helper_names() if hasattr(narration, name)]

    assert present == []


def test_dead_narration_helper_names_are_absent_from_repository():
    paths = _repository_files()
    this_test = Path("apps/agent/tests/test_narration_segments.py")
    assert paths and this_test in paths

    searched_paths = tuple(path for path in paths if path != this_test)
    hits = {name: _files_containing(name.encode(), searched_paths) for name in _dead_helper_names()}

    assert hits == {name: [] for name in _dead_helper_names()}


class TestTheNarrationToolSchema:
    """Strict is what makes the string-shaped `segments` impossible at the source.

    The schema has always declared an array of objects and the model sent a JSON string twice
    anyway (sprint-049, sprint-050). ADR 0004's ceilings — 20 strict tools, compiled grammar size —
    are about the gameplay agents' toolsets; this is one small tool on a direct call, and the live
    API accepts it strict, which it does only when every object closes itself.
    """

    def test_the_tool_is_built_strict_with_every_object_closed(self):
        tool = json.loads(json.dumps(narration._build_narration_tool(["COMPANION_KAEL"])))
        schema = tool["input_schema"]

        assert tool["strict"] is True
        assert schema["additionalProperties"] is False
        assert schema["properties"]["segments"]["items"]["additionalProperties"] is False

    def test_strict_requires_every_declared_property_to_be_required(self):
        """A strict request is refused outright when `required` omits a declared property, and the
        refusal names the schema, not the field — so pin it here rather than pay an API call."""
        tool = json.loads(json.dumps(narration._build_narration_tool(["COMPANION_KAEL"])))
        schema = tool["input_schema"]
        item = schema["properties"]["segments"]["items"]

        assert set(schema["required"]) == set(schema["properties"])
        assert set(item["required"]) == set(item["properties"])


class TestMalformedSegmentsFromTheModel:
    """The segments come from an LLM tool call, so their SHAPE is the model's output, not ours.

    A live errand resolution died on `AttributeError: 'str' object has no attribute 'get'`
    during the sprint-048 close, intermittently: the model returned one segment as a bare
    string instead of an object. The parser assumed every segment was a dict and called
    `seg.get(...)`. Constraint 9: never model the other side's shape, validate it.
    """

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
        """Coercion must not become silence. Dropping every segment leaves an errand that
        "resolved" with no narration — in an audio-first game the player just gets nothing,
        which is worse than the crash this normalizer replaced. Segments keyed on names we
        do not know is a malformed response, not a recoverable one."""
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
