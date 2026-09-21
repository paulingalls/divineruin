"""Declared limits of the Sprint 103 direct-session voice diagnostic."""

from multiplayer_transcription import COMPLETE_UTTERANCE_ENDPOINTING_SECONDS

REPLAY_INSTRUCTION = """
VOICE REPLAY SCENARIO: Start by saying exactly “I'll look.” If the check tool is available, immediately call it
once with roll.kind gather and roll.category any, then say each returned material id as ordinary spaced words.
If the tool is unavailable, stop after the acknowledgement.
"""

# voice_replay.py builds its AgentSession from this value rather than its own literal: the
# published latency numbers are only honest while the declared scope IS the runner's setting.
REPLAY_ENDPOINTING_SECONDS = 0.5

VOICE_REPLAY_SCOPE = {
    "production_gameplay_equivalent": False,
    "input_endpointing_seconds": REPLAY_ENDPOINTING_SECONDS,
    "production_endpointing_seconds": COMPLETE_UTTERANCE_ENDPOINTING_SECONDS,
    "excluded_production_stages": [
        "multi_participant_transcriber_queue",
        "multiplayer_input_serialization",
    ],
}
