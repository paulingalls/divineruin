import pytest
from dialogue_parser import parse_dialogue_stream, Segment


async def _collect(text: str) -> list[Segment]:
    async def stream():
        yield text

    return [seg async for seg in parse_dialogue_stream(stream())]


async def _collect_chunked(chunks: list[str]) -> list[Segment]:
    async def stream():
        for c in chunks:
            yield c

    return [seg async for seg in parse_dialogue_stream(stream())]


@pytest.mark.asyncio
async def test_plain_narration():
    segments = await _collect("The wind howls through the ruins.")
    assert len(segments) == 1
    assert segments[0].character == "dm_narrator"
    assert segments[0].emotion == "neutral"
    assert "wind howls" in segments[0].text


@pytest.mark.asyncio
async def test_single_character_line():
    text = '[GUILDMASTER_TORIN, stern]: "Watch your step, traveler."'
    segments = await _collect(text)
    dialogue_segs = [s for s in segments if s.character == "GUILDMASTER_TORIN"]
    assert len(dialogue_segs) >= 1
    combined = "".join(s.text for s in dialogue_segs)
    assert "Watch your step" in combined
    assert dialogue_segs[0].emotion == "stern"


@pytest.mark.asyncio
async def test_narration_then_dialogue():
    text = (
        'The guild hall falls quiet.\n'
        '[GUILDMASTER_TORIN, angry]: "Get out."'
    )
    segments = await _collect(text)
    narration = [s for s in segments if s.character == "dm_narrator"]
    dialogue = [s for s in segments if s.character == "GUILDMASTER_TORIN"]
    assert len(narration) >= 1
    assert len(dialogue) >= 1
    assert "quiet" in "".join(s.text for s in narration)
    assert "Get out" in "".join(s.text for s in dialogue)


@pytest.mark.asyncio
async def test_multiple_characters():
    text = (
        '[ELDER_YANNA, calm]: "Peace, child."\n'
        '[SCHOLAR_EMRIS, nervous]: "We should hurry."'
    )
    segments = await _collect(text)
    yanna = [s for s in segments if s.character == "ELDER_YANNA"]
    emris = [s for s in segments if s.character == "SCHOLAR_EMRIS"]
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
    dialogue = [s for s in segments if s.character == "GUILDMASTER_TORIN"]
    assert len(dialogue) >= 1
    combined = "".join(s.text for s in dialogue)
    assert "listening" in combined


@pytest.mark.asyncio
async def test_fallback_on_unparseable():
    text = "Just plain text with no [tags at all"
    segments = await _collect(text)
    assert all(s.character == "dm_narrator" for s in segments)


@pytest.mark.asyncio
async def test_empty_input():
    segments = await _collect("")
    assert len(segments) == 0
