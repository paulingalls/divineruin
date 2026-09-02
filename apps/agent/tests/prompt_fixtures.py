"""Shared sample rows for the prompt-layer tests.

Home for the location/NPC/quest rows that test_prompts and test_warm_prompt_regions both feed
to build_warm_layer. They live here rather than in either test module so the split of the warm
region tests out of test_prompts (500-line cap) did not fork a second, silently drifting copy.
Distinct from sample_fixtures.SAMPLE_LOCATION, whose exits carry a `requires` gate these
prompt tests do not want.
"""

SAMPLE_LOCATION = {
    "id": "accord_guild_hall",
    "name": "Guild Hall",
    "description": "Heavy oak doors open onto a hall.",
    "atmosphere": "busy, purposeful",
    "key_features": ["the main counter"],
    "hidden_elements": [],
    "exits": {"south": {"destination": "accord_market_square"}},
    "tags": ["guild"],
    "conditions": {
        "time_night": {
            "description_override": "The guild hall is dim and quiet.",
            "atmosphere": "hushed",
        }
    },
}

SAMPLE_NPC_RAW = {
    "id": "guildmaster_torin",
    "name": "Guildmaster Torin",
    "role": "guild hall master",
    "default_disposition": "neutral",
    "voice_notes": "deep baritone",
    "schedule": {"07:00-22:00": "accord_guild_hall"},
}

SAMPLE_QUEST = {
    "quest_id": "greyvale_anomaly",
    "quest_name": "The Greyvale Anomaly",
    "current_stage": 1,
    "stages": [
        {"id": 0, "objective": "Investigate the strange lights."},
        {"id": 1, "objective": "Find the source of the anomaly."},
    ],
}
