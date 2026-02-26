import pytest
from dialogue_parser import parse_dialogue_stream, Segment, DEFAULT_CHARACTER


async def _collect(text: str) -> list[Segment]:
    async def stream():
        yield text

    return [seg async for seg in parse_dialogue_stream(stream())]


async def _collect_chunked(chunks: list[str]) -> list[Segment]:
    async def stream():
        for c in chunks:
            yield c

    return [seg async for seg in parse_dialogue_stream(stream())]


def _all_text(segments: list[Segment]) -> str:
    return "".join(s.text for s in segments)


def _by_character(segments: list[Segment], character: str) -> list[Segment]:
    return [s for s in segments if s.character == character]


@pytest.mark.asyncio
async def test_plain_narration():
    segments = await _collect("The wind howls through the ruins.")
    assert len(segments) == 1
    assert segments[0].character == DEFAULT_CHARACTER
    assert segments[0].emotion == "neutral"
    assert "wind howls" in segments[0].text


@pytest.mark.asyncio
async def test_single_character_line():
    text = '[GUILDMASTER_TORIN, stern]: "Watch your step, traveler."'
    segments = await _collect(text)
    dialogue = _by_character(segments, "GUILDMASTER_TORIN")
    assert len(dialogue) >= 1
    assert "Watch your step" in _all_text(dialogue)
    assert dialogue[0].emotion == "stern"


@pytest.mark.asyncio
async def test_narration_then_dialogue():
    text = (
        'The guild hall falls quiet.\n'
        '[GUILDMASTER_TORIN, angry]: "Get out."'
    )
    segments = await _collect(text)
    narration = _by_character(segments, DEFAULT_CHARACTER)
    dialogue = _by_character(segments, "GUILDMASTER_TORIN")
    assert len(narration) >= 1
    assert len(dialogue) >= 1
    assert "quiet" in _all_text(narration)
    assert "Get out" in _all_text(dialogue)


@pytest.mark.asyncio
async def test_multiple_characters():
    text = (
        '[ELDER_YANNA, calm]: "Peace, child."\n'
        '[SCHOLAR_EMRIS, nervous]: "We should hurry."'
    )
    segments = await _collect(text)
    yanna = _by_character(segments, "ELDER_YANNA")
    emris = _by_character(segments, "SCHOLAR_EMRIS")
    assert len(yanna) >= 1
    assert len(emris) >= 1
    assert yanna[0].emotion == "calm"
    assert emris[0].emotion == "nervous"


@pytest.mark.asyncio
async def test_chunked_tag_across_boundary():
    chunks = [
        "The room darkens. [GUILDMASTER",
        "_TORIN, whispering]: \"They're listening.\"",
    ]
    segments = await _collect_chunked(chunks)
    dialogue = _by_character(segments, "GUILDMASTER_TORIN")
    assert len(dialogue) >= 1
    assert "listening" in _all_text(dialogue)


@pytest.mark.asyncio
async def test_fallback_on_unparseable():
    text = "Just plain text with no [tags at all"
    segments = await _collect(text)
    assert all(s.character == DEFAULT_CHARACTER for s in segments)


@pytest.mark.asyncio
async def test_empty_input():
    segments = await _collect("")
    assert len(segments) == 0


@pytest.mark.asyncio
async def test_tag_like_text_not_a_real_tag():
    text = "The sign reads [DANGER, ahead] in faded paint."
    segments = await _collect(text)
    combined = _all_text(segments)
    assert "DANGER" in combined
    assert all(s.character == DEFAULT_CHARACTER for s in segments)


@pytest.mark.asyncio
async def test_lowercase_character_name_not_matched():
    text = '[torin, angry]: "hello"'
    segments = await _collect(text)
    assert all(s.character == DEFAULT_CHARACTER for s in segments)


@pytest.mark.asyncio
async def test_empty_emotion_not_matched():
    text = '[GUILDMASTER_TORIN, ]: "hello"'
    segments = await _collect(text)
    assert all(s.character == DEFAULT_CHARACTER for s in segments)


@pytest.mark.asyncio
async def test_dialogue_with_inner_quotes():
    text = '[GUILDMASTER_TORIN, stern]: "He said run and fled"'
    segments = await _collect(text)
    dialogue = _by_character(segments, "GUILDMASTER_TORIN")
    assert len(dialogue) >= 1
    assert "said run" in _all_text(dialogue)


@pytest.mark.asyncio
async def test_no_single_character_segments():
    text = "She looked at the [old map] on the wall."
    segments = await _collect(text)
    for seg in segments:
        assert len(seg.text.strip()) > 1 or not seg.text.strip()


@pytest.mark.asyncio
async def test_rapid_character_alternation_chunked():
    chunks = [
        '[ELDER_YANNA, calm]: "Go',
        '." [SCHOLAR_EMRIS, urgent]: "No, stay',
        '!"',
    ]
    segments = await _collect_chunked(chunks)
    yanna = _by_character(segments, "ELDER_YANNA")
    emris = _by_character(segments, "SCHOLAR_EMRIS")
    assert len(yanna) >= 1
    assert len(emris) >= 1


@pytest.mark.asyncio
async def test_long_narration_no_tags():
    text = "A very long narration. " * 100
    segments = await _collect(text)
    combined = _all_text(segments)
    assert combined == text
    assert all(s.character == DEFAULT_CHARACTER for s in segments)
