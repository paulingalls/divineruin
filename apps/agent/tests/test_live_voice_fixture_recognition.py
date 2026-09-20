"""The live-voice lane's whole positive claim rests on one predicate.

Every real-room assertion that a recording reached a listener — `await_speech`, and the
"heard exactly once" counts in `test_dm_turn` — is `SpeechFixture.spoken_in`. It runs only
where Deepgram does, so nothing else can catch it drifting into always-true; this pins both
sides of it in the fast lane, against the transcripts those tests actually speak.
"""

from __future__ import annotations

import pytest
from acceptance.multiplayer_voice._harness import PLAYER_ONE_SPEECH, PLAYER_TWO_SPEECH, SpeechFixture


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
