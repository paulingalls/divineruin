"""Declared limits of the Sprint 103 direct-session voice diagnostic."""

REPLAY_INSTRUCTION = """
VOICE REPLAY SCENARIO: Start by saying exactly “I'll look.” If the check tool is available, immediately call it
once with roll.kind gather and roll.category any, then say each returned material id as ordinary spaced words.
If the tool is unavailable, stop after the acknowledgement.
"""

VOICE_REPLAY_SCOPE = {
    "production_gameplay_equivalent": False,
    "input_endpointing_seconds": 0.5,
    "production_endpointing_seconds": 1.0,
    "excluded_production_stages": [
        "multi_participant_transcriber_queue",
        "multiplayer_input_serialization",
    ],
}
