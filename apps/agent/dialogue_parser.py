import re
from collections.abc import AsyncGenerator, AsyncIterable
from dataclasses import dataclass

from voices import VOICES

TAG_PATTERN = re.compile(
    r'\[([A-Z_]+),\s*([a-z]+)\]:\s*"',
    re.DOTALL,
)

DEFAULT_CHARACTER = "DM_NARRATOR"
DEFAULT_EMOTION = "neutral"

# The emotion group is [a-z]+, so the DM can improvise past the longest catalogued EMOTIONS
# word; budget for that rather than for the catalogue.
_MAX_EMOTION_LENGTH = 24

# How far past a "[" we wait for the tag to close. A longer tag is emitted as literal
# narration and its line is then spoken by DM_NARRATOR, so the bound tracks the registry:
# a newly registered VOICES key must not be able to outgrow it.
MAX_TAG_LENGTH = len('[, ]: "') + max(len(k) for k in VOICES) + _MAX_EMOTION_LENGTH


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
                buffer = buffer[end_quote + 1 :]
                in_dialogue = False
                if text:
                    yield Segment(current_character, current_emotion, text)
                current_character = DEFAULT_CHARACTER
                current_emotion = DEFAULT_EMOTION
                continue

            match = TAG_PATTERN.search(buffer)
            if match:
                before = buffer[: match.start()]
                if before.strip():
                    yield Segment(DEFAULT_CHARACTER, DEFAULT_EMOTION, before)

                current_character = match.group(1)
                current_emotion = match.group(2)
                buffer = buffer[match.end() :]
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

                before = buffer[: bracket_pos + 1]
                if before.strip():
                    yield Segment(DEFAULT_CHARACTER, DEFAULT_EMOTION, before)
                buffer = buffer[bracket_pos + 1 :]
                continue

            yield Segment(DEFAULT_CHARACTER, DEFAULT_EMOTION, buffer)
            buffer = ""
            break

    if buffer.strip():
        yield Segment(current_character, current_emotion, buffer)
