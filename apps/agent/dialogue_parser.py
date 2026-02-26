import re
from dataclasses import dataclass
from collections.abc import AsyncIterable, AsyncGenerator

TAG_PATTERN = re.compile(
    r'\[([A-Z_]+),\s*([a-z]+)\]:\s*"',
    re.DOTALL,
)

DEFAULT_CHARACTER = "DM_NARRATOR"
DEFAULT_EMOTION = "neutral"

MAX_TAG_LENGTH = 50


@dataclass
class Segment:
    character: str
    emotion: str
    text: str


async def parse_dialogue_stream(
    text_stream: AsyncIterable[str],
) -> AsyncGenerator[Segment, None]:
    buffer = ""
    current_character = DEFAULT_CHARACTER
    current_emotion = DEFAULT_EMOTION
    in_dialogue = False

    async for chunk in text_stream:
        buffer += chunk

        while buffer:
            if in_dialogue:
                end_quote = buffer.find('"')
                if end_quote == -1:
                    text = buffer
                    buffer = ""
                    yield Segment(current_character, current_emotion, text)
                    break

                text = buffer[:end_quote]
                buffer = buffer[end_quote + 1:]
                in_dialogue = False
                if text:
                    yield Segment(current_character, current_emotion, text)
                current_character = DEFAULT_CHARACTER
                current_emotion = DEFAULT_EMOTION
                continue

            match = TAG_PATTERN.search(buffer)
            if match:
                before = buffer[:match.start()]
                if before.strip():
                    yield Segment(DEFAULT_CHARACTER, DEFAULT_EMOTION, before)

                current_character = match.group(1)
                current_emotion = match.group(2)
                buffer = buffer[match.end():]
                in_dialogue = True
                continue

            bracket_pos = buffer.find("[")
            if bracket_pos != -1:
                remaining = buffer[bracket_pos:]

                if len(remaining) < MAX_TAG_LENGTH:
                    before = buffer[:bracket_pos]
                    if before.strip():
                        yield Segment(DEFAULT_CHARACTER, DEFAULT_EMOTION, before)
                    buffer = remaining
                    break

                before = buffer[:bracket_pos + 1]
                if before.strip():
                    yield Segment(DEFAULT_CHARACTER, DEFAULT_EMOTION, before)
                buffer = buffer[bracket_pos + 1:]
                continue

            yield Segment(DEFAULT_CHARACTER, DEFAULT_EMOTION, buffer)
            buffer = ""
            break

    if buffer.strip():
        yield Segment(current_character, current_emotion, buffer)
