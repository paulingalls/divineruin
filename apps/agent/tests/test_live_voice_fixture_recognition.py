"""The live-voice lane's whole positive claim rests on one predicate.

Every real-room assertion that a recording reached a listener — `await_speech`, and the
"heard exactly once" counts in `test_dm_turn` — is `SpeechFixture.spoken_in`. It runs only
where Deepgram does, so nothing else can catch it drifting into always-true; this pins both
sides of it in the fast lane, against the transcripts those tests actually speak.
"""

from __future__ import annotations

import asyncio

import pytest
from acceptance.multiplayer_voice._harness import (
    PLAYER_ONE_SPEECH,
    PLAYER_TWO_SPEECH,
    MultiplayerVoiceHarness,
    SpeechFixture,
)

from multiplayer_transcription import AuthenticatedTranscript

_FIRST = "Mister Quilter is the apostle of the middle classes"
_SECOND = "and we are glad to welcome his gospel."


def _without(transcript: str, *words: str) -> str:
    dropped = {word.lower() for word in words}
    return " ".join(word for word in transcript.split() if word.lower() not in dropped)


@pytest.mark.parametrize("fixture", [PLAYER_ONE_SPEECH, PLAYER_TWO_SPEECH])
def test_a_recording_is_recognized_through_the_words_real_stt_drops(fixture: SpeechFixture) -> None:
    assert fixture.spoken_in(fixture.transcript)
    assert fixture.spoken_in(fixture.transcript.lower().replace(" ", ", ") + ".")
    for word in fixture.transcript.split():
        assert fixture.spoken_in(_without(fixture.transcript, word)), f"one dropped {word!r} lost the utterance"


@pytest.mark.parametrize(
    ("fixture", "other"),
    [(PLAYER_ONE_SPEECH, PLAYER_TWO_SPEECH), (PLAYER_TWO_SPEECH, PLAYER_ONE_SPEECH)],
)
def test_recognition_still_refuses_the_wrong_speech_silence_and_a_fragment(
    fixture: SpeechFixture, other: SpeechFixture
) -> None:
    assert not fixture.spoken_in(other.transcript)
    assert not fixture.spoken_in("")
    words = fixture.transcript.split()
    assert not fixture.spoken_in(" ".join(words[: len(words) // 2]))


async def _heard(fragments: list[AuthenticatedTranscript], monkeypatch: pytest.MonkeyPatch) -> AuthenticatedTranscript:
    queue: asyncio.Queue[AuthenticatedTranscript] = asyncio.Queue()
    for fragment in fragments:
        queue.put_nowait(fragment)
    harness = MultiplayerVoiceHarness({})

    async def receive(_timeout: float = 20) -> AuthenticatedTranscript:
        return await queue.get()

    monkeypatch.setattr(harness, "receive", receive)
    return await harness.await_speech("player-two", PLAYER_ONE_SPEECH, timeout=0.1)


@pytest.mark.asyncio
async def test_real_stt_split_is_recognized_as_one_recording(monkeypatch: pytest.MonkeyPatch) -> None:
    heard = await _heard(
        [AuthenticatedTranscript("player-two", _FIRST, 1), AuthenticatedTranscript("player-two", _SECOND, 1)],
        monkeypatch,
    )
    assert heard == AuthenticatedTranscript("player-two", f"{_FIRST} {_SECOND}", 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("first_identity,first_generation", [("player-one", 1), ("player-two", 0)])
async def test_fragments_cannot_join_across_players_or_generations(
    monkeypatch: pytest.MonkeyPatch, first_identity: str, first_generation: int
) -> None:
    fragments = [
        AuthenticatedTranscript(first_identity, _FIRST, first_generation),
        AuthenticatedTranscript("player-two", _SECOND, 1),
    ]
    with pytest.raises(TimeoutError, match="no 1272-128104-0000 transcript"):
        await _heard(fragments, monkeypatch)
