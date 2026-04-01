"""Shared sample data for tests — import from here instead of duplicating."""

SAMPLE_PLAYER = {
    "player_id": "player_1",
    "name": "Arwen",
    "class": "ranger",
    "level": 2,
    "attributes": {
        "strength": 12,
        "dexterity": 16,
        "constitution": 14,
        "intelligence": 10,
        "wisdom": 13,
        "charisma": 8,
    },
    "proficiencies": ["stealth", "perception"],
    "saving_throw_proficiencies": ["strength", "dexterity"],
    "equipment": {
        "main_hand": {
            "name": "Longbow",
            "damage": "1d8",
            "damage_type": "piercing",
            "properties": [],
        }
    },
    "hp": {"current": 28, "max": 28},
    "ac": 15,
}

SAMPLE_ENCOUNTER = {
    "id": "wolf_pack",
    "name": "Wolf Pack",
    "difficulty": "moderate",
    "enemies": [
        {
            "id": "dire_wolf_1",
            "name": "Dire Wolf",
            "level": 2,
            "ac": 14,
            "hp": 15,
            "attributes": {"strength": 16, "dexterity": 14},
            "action_pool": [
                {
                    "name": "Bite",
                    "damage": "1d8+3",
                    "damage_type": "piercing",
                    "properties": [],
                }
            ],
            "xp_value": 100,
        },
    ],
}
