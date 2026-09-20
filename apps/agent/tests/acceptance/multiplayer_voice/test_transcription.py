from __future__ import annotations

import os

import pytest
from acceptance._live_voice import has_live_voice_key
from acceptance.multiplayer_voice._harness import PLAYER_ONE_SPEECH, PLAYER_TWO_SPEECH, MultiplayerVoiceHarness

# The skipif is the not-opted-in path (CI without the secret, a worktree carrying
# .env.example's placeholder); REQUIRE_REAL_LLM=1 suppresses it so the conftest fixture
# fails this lane LOUD rather than letting it absent itself from the boundary.
pytestmark = pytest.mark.skipif(
    not has_live_voice_key(os.environ) and not os.environ.get("REQUIRE_REAL_LLM"),
    reason="live-voice acceptance drives the real Deepgram STT API and needs DEEPGRAM_API_KEY",
)


async def test_two_microphones_reach_the_transcription_seam_with_their_identities(
    livekit_server: dict[str, str],
) -> None:
    harness = MultiplayerVoiceHarness(livekit_server)
    try:
        await harness.start()
        await harness.play(harness.player_one_identity, PLAYER_ONE_SPEECH)
        first = await harness.await_marker(harness.player_one_identity, PLAYER_ONE_SPEECH.marker)
        assert first.text
        await harness.play(harness.player_two_identity, PLAYER_TWO_SPEECH)
        second = await harness.await_marker(harness.player_two_identity, PLAYER_TWO_SPEECH.marker)
        assert second.text
    finally:
        await harness.aclose()


async def test_transcription_tracks_mute_unpublish_disconnect_and_reconnect(
    livekit_server: dict[str, str],
) -> None:
    harness = MultiplayerVoiceHarness(livekit_server)
    try:
        await harness.start()
        assert harness.manager is not None
        assert harness.manager.start_counts == {
            harness.player_one_identity: 1,
            harness.player_two_identity: 1,
        }

        await harness.mute(harness.player_two_identity, True)
        await harness.drain()
        await harness.play(harness.player_one_identity, PLAYER_ONE_SPEECH)
        await harness.await_marker(harness.player_one_identity, PLAYER_ONE_SPEECH.marker)
        await harness.play(harness.player_two_identity, PLAYER_TWO_SPEECH)
        await harness.assert_no_transcript(harness.player_two_identity)

        await harness.mute(harness.player_two_identity, False)
        await harness.drain()
        await harness.play(harness.player_two_identity, PLAYER_TWO_SPEECH)
        await harness.await_marker(harness.player_two_identity, PLAYER_TWO_SPEECH.marker)

        await harness.drain()
        await harness.unpublish(harness.player_two_identity)
        await harness.play(harness.player_one_identity, PLAYER_TWO_SPEECH)
        await harness.await_marker(harness.player_one_identity, PLAYER_TWO_SPEECH.marker)
        await harness.assert_no_transcript(harness.player_two_identity, 2)
        await harness.republish(harness.player_two_identity)
        await harness.play(harness.player_two_identity, PLAYER_ONE_SPEECH)
        await harness.await_marker(harness.player_two_identity, PLAYER_ONE_SPEECH.marker)

        await harness.drain()
        await harness.disconnect_player_two()
        await harness.play(harness.player_one_identity, PLAYER_ONE_SPEECH)
        await harness.await_marker(harness.player_one_identity, PLAYER_ONE_SPEECH.marker)
        await harness.reconnect_player_two()
        assert harness.manager.start_counts[harness.player_two_identity] == 2
        await harness.play(harness.player_two_identity, PLAYER_TWO_SPEECH)
        await harness.await_marker(harness.player_two_identity, PLAYER_TWO_SPEECH.marker)
    finally:
        await harness.aclose()
