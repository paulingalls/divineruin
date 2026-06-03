"""Shared sample data for tests — import from here instead of duplicating."""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import event_types as E
from milestones import Grant, Milestone, SpecializationOption
from session_data import SessionData

FIXED_NOW = datetime(2026, 5, 19, 12, 0, 0, tzinfo=UTC)


@asynccontextmanager
async def mock_txn(conn):
    yield conn


def make_db_mod():
    mock_conn = MagicMock()
    mock_db = MagicMock()
    mock_db.transaction = lambda: mock_txn(mock_conn)
    return mock_db, mock_conn


def level_up_payload(room):
    """Return the LEVEL_UP event payload from a mock room's publish_data calls, or None."""
    for call in room.local_participant.publish_data.call_args_list:
        data = json.loads(call[0][0])
        if data["type"] == E.LEVEL_UP:
            return data
    return None


def make_context(player_id="player_1", location_id="accord_guild_hall", room=None):
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id=player_id, location_id=location_id, room=room)
    return ctx


def make_mock_room():
    room = MagicMock()
    room.local_participant = MagicMock()
    room.local_participant.publish_data = AsyncMock()
    return room


SAMPLE_PLAYER = {
    "player_id": "player_1",
    "name": "Arwen",
    "class": "skirmisher",
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

# Generic guild-hall player for mutation/progression/quest tool tests.
# Distinct from SAMPLE_PLAYER (Arwen): level 1, xp 0, and a valid archetype.
GUILD_PLAYER = {
    "player_id": "player_1",
    "name": "Kael",
    "class": "warrior",
    "level": 1,
    "xp": 0,
    "attributes": {
        "strength": 14,
        "dexterity": 12,
        "constitution": 13,
        "intelligence": 10,
        "wisdom": 11,
        "charisma": 8,
    },
    "proficiencies": ["athletics", "stealth", "perception"],
    "saving_throw_proficiencies": ["strength", "constitution"],
    "equipment": {
        "main_hand": {
            "name": "Longsword",
            "damage": "1d8",
            "damage_type": "slashing",
            "properties": [],
        }
    },
    "hp": {"current": 25, "max": 25},
    "ac": 14,
}

SAMPLE_NPC = {
    "id": "guildmaster_torin",
    "name": "Guildmaster Torin",
    "role": "guild hall master",
    "default_disposition": "neutral",
    "voice_notes": "deep baritone",
}

SAMPLE_ITEM = {
    "id": "health_potion",
    "name": "Health Potion",
    "type": "consumable",
    "description": "A glowing red vial.",
    "rarity": "common",
}

SAMPLE_LOCATION = {
    "id": "accord_guild_hall",
    "name": "Guild Hall",
    "description": "Heavy oak doors open onto a hall.",
    "atmosphere": "busy, purposeful",
    "key_features": ["the main counter"],
    "hidden_elements": [],
    "exits": {
        "south": {"destination": "accord_market_square"},
        "east": {"destination": "accord_temple", "requires": "temple_key"},
    },
    "tags": ["guild"],
    "conditions": {},
}

SAMPLE_DESTINATION = {
    "id": "accord_market_square",
    "name": "Market Square",
    "description": "A bustling open-air market.",
    "atmosphere": "noisy, chaotic",
    "ambient_sounds": "market_bustle",
    "ambient_sounds_night": "harbor_quiet",
    "key_features": ["merchant stalls"],
    "hidden_elements": [],
    "exits": {"north": {"destination": "accord_guild_hall"}},
    "tags": ["market"],
    "conditions": {},
}


# --- Shared milestone fixtures for progression/quest XP tests ---
# A warrior milestone ladder mirroring content/archetype_milestones.json shapes:
# L5 fork with populated options (the fork-present path), L10 auto-grant with the
# extra_attack flag, L15/L20 narrative-only. Imported by both test_progression_tools
# and test_quest_tools — keep it here, not duplicated per-file.

_FORK_OPTIONS = (
    SpecializationOption("battle_master", "Battle Master", "Tactical maneuvers."),
    SpecializationOption("berserker", "Berserker", "Reckless fury."),
)

_WARRIOR_MILESTONES = [
    Milestone("warrior_identity", "warrior", "identity", 5, "specialization_fork", False, _FORK_OPTIONS, None, "cue"),
    Milestone(
        "warrior_power",
        "warrior",
        "power",
        10,
        "auto_grant",
        False,
        (),
        Grant("Extra Attack", "Your blade strikes twice.", "extra_attack"),
        "cue",
    ),
    Milestone(
        "warrior_mastery",
        "warrior",
        "mastery",
        15,
        "auto_grant",
        False,
        (),
        Grant("Indomitable", "Reroll a failed save.", None),
        "cue",
    ),
    Milestone(
        "warrior_legend",
        "warrior",
        "legend",
        20,
        "auto_grant",
        False,
        (),
        Grant("Legendary Action", "Act outside the turn order.", None),
        "cue",
    ),
]


def _milestones_mod_for(ladder, archetype_id):
    """A milestones-module mock whose get_milestone_by_level resolves `ladder` for
    `archetype_id` and returns None for any other archetype."""
    mod = MagicMock()
    by_level = {m.level: m for m in ladder}
    mod.get_milestone_by_level = MagicMock(
        side_effect=lambda aid, level: by_level.get(level) if aid == archetype_id else None
    )
    return mod
