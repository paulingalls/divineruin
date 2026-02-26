import re
from dataclasses import dataclass
from collections.abc import AsyncIterable, AsyncGenerator

TAG_PATTERN = re.compile(
    r'\[([A-Z_]+),\s*([a-z]+)\]:\s*"',
    re.DOTALL,
)


@dataclass
class Segment:
    character: str
    emotion: str
    text: str


async def parse_dialogue_stream(
    text_stream: AsyncIterable[str],
) -> AsyncGenerator[Segment, None]:
    buffer = ""
    current_character = "dm_narrator"
    current_emotion = "neutral"
    in_dialogue = False

    async for chunk in text_stream:
        buffer += chunk

        while buffer:
            if in_dialogue:
                end_quote = buffer.find('"')
                if end_quote == -1:
                    if buffer:
                        text = buffer
                        buffer = ""
                        yield Segment(current_character, current_emotion, text)
                    break

                text = buffer[:end_quote]
                buffer = buffer[end_quote + 1:]
                in_dialogue = False
                if text:
                    yield Segment(current_character, current_emotion, text)
                current_character = "dm_narrator"
                current_emotion = "neutral"
                continue

            match = TAG_PATTERN.search(buffer)
            if match:
                before = buffer[:match.start()]
                if before.strip():
                    yield Segment("dm_narrator", "neutral", before)

                current_character = match.group(1)
                current_emotion = match.group(2)
                buffer = buffer[match.end():]
                in_dialogue = True
                continue

            if "[" in buffer:
                bracket_pos = buffer.index("[")
                before = buffer[:bracket_pos]
                remaining = buffer[bracket_pos:]

                if len(remaining) < 30:
                    if before.strip():
                        yield Segment("dm_narrator", "neutral", before)
                    buffer = remaining
                    break

                if before.strip():
                    yield Segment("dm_narrator", "neutral", before)
                yield Segment("dm_narrator", "neutral", remaining[0])
                buffer = remaining[1:]
                continue

            yield Segment("dm_narrator", "neutral", buffer)
            buffer = ""
            break

    if buffer.strip():
        yield Segment(current_character, current_emotion, buffer)
