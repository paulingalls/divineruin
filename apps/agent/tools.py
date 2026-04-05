"""Shared helpers, constants, and re-exports for DM agent tools.

Tool functions live in focused modules:
- scene_tools: Scene resolution and context building
- query_tools: World queries (location, NPC, lore, inventory)
- check_tools: Skill checks, attacks, saving throws, dice
- combat_tools: Combat lifecycle (start, enemy turns, death saves, end)
- action_tools: Game actions (XP, inventory, movement, quests, session)
- environment_tools: Audio (sound effects, music state)

This module keeps shared helpers and constants, and re-exports all tool
functions so existing ``from tools import X`` continues to work.
"""

import json
import logging
import re

import db  # noqa: F401 — kept as attribute for test patch targets (tools.db.X)
import db_mutations  # noqa: F401 — kept as attribute for test patch targets (tools.db_mutations.X)
import db_queries
from game_events import publish_game_event  # noqa: F401 — kept for test patch targets

logger = logging.getLogger("divineruin.tools")

_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

LOCATION_CORRUPTION: dict[str, int] = {
    "greyvale_wilderness_north": 1,
    "hollow_incursion_site": 2,
    "greyvale_ruins_entrance": 2,
    "greyvale_ruins_inner": 3,
}

EFFECT_NPC_MAP: dict[str, str] = {
    "torin": "guildmaster_torin",
    "yanna": "elder_yanna",
    "emris": "scholar_emris",
    "companion": "companion_kael",
}


def _validate_id(value: str, label: str) -> str | None:
    """Return an error JSON string if the ID is invalid, else None."""
    if not value or len(value) > 128 or not _ID_RE.match(value):
        return json.dumps({"error": f"Invalid {label}: '{value[:64]}'"})
    return None


def _cap_str(value: str, max_len: int, name: str) -> str | None:
    """Return an error JSON string if value exceeds max_len, else None."""
    if len(value) > max_len:
        return json.dumps({"error": f"{name} exceeds maximum length of {max_len} characters."})
    return None


DISPOSITION_ORDER = ["hostile", "wary", "neutral", "friendly", "trusted"]

DISPOSITION_TIERS = {name: i for i, name in enumerate(DISPOSITION_ORDER)}
DISPOSITION_TIERS["cautious"] = DISPOSITION_TIERS["neutral"]  # alias


def _disposition_rank(tier: str) -> int:
    return DISPOSITION_TIERS.get(tier.lower(), 2)


def filter_knowledge(knowledge: dict, disposition: str) -> list[str]:
    """Filter NPC knowledge by the player's disposition tier.

    Returns a flat list of knowledge strings the player is allowed to see.
    """
    rank = _disposition_rank(disposition)
    result: list[str] = []

    for gate, entries in knowledge.items():
        if gate == "free":
            if isinstance(entries, list):
                result.extend(entries)
        elif gate == "disposition >= friendly":
            if rank >= DISPOSITION_TIERS["friendly"] and isinstance(entries, list):
                result.extend(entries)
        elif gate == "disposition >= trusted" and rank >= DISPOSITION_TIERS["trusted"] and isinstance(entries, list):
            result.extend(entries)
        # quest_triggered and other gates: skip for 3.1

    return result


def apply_time_conditions(location: dict, time_of_day: str = "day") -> dict:
    """Apply time-of-day condition overrides to a location dict.

    Returns a new dict with overrides applied. Does not mutate the original.
    """
    conditions = location.get("conditions", {})
    time_condition = conditions.get("time_night") if time_of_day == "night" else None

    if time_condition is None:
        return location

    result = {**location}

    if "description_override" in time_condition:
        result["description"] = time_condition["description_override"]
    if "atmosphere" in time_condition:
        result["atmosphere"] = time_condition["atmosphere"]

    return result


def _strip_hidden_dcs(location: dict) -> dict:
    """Remove dc and discover_skill from hidden_elements so the LLM can't
    reveal them without a skill check."""
    hidden = location.get("hidden_elements")
    if not hidden:
        return location

    stripped = []
    for elem in hidden:
        stripped.append(
            {
                "id": elem.get("id"),
                "description": elem.get("description"),
            }
        )

    result = {**location, "hidden_elements": stripped}
    return result


def _location_for_narration(location: dict) -> dict:
    """Extract the fields the LLM needs for narrating a location."""
    return {
        "id": location.get("id"),
        "name": location.get("name"),
        "description": location.get("description"),
        "atmosphere": location.get("atmosphere"),
        "key_features": location.get("key_features", []),
        "hidden_elements": location.get("hidden_elements", []),
        "exits": location.get("exits", {}),
        "tags": location.get("tags", []),
    }


def _npc_for_narration(npc: dict, disposition: str, knowledge: list[str]) -> dict:
    """Extract the fields the LLM needs for roleplaying an NPC."""
    return {
        "name": npc.get("name"),
        "role": npc.get("role"),
        "personality": npc.get("personality"),
        "speech_style": npc.get("speech_style"),
        "mannerisms": npc.get("mannerisms"),
        "appearance": npc.get("appearance"),
        "disposition": disposition,
        "knowledge": knowledge,
        "voice_notes": npc.get("voice_notes"),
    }


def _player_summary(player: dict) -> dict:
    hp = player.get("hp", {})
    equipment = player.get("equipment", {})
    weapon = equipment.get("main_hand", {})
    return {
        "name": player.get("name"),
        "class": player.get("class"),
        "level": player.get("level"),
        "hp_current": hp.get("current"),
        "hp_max": hp.get("max"),
        "ac": player.get("ac"),
        "weapon": weapon.get("name"),
        "weapon_damage": weapon.get("damage"),
    }


def _npc_summary(npc: dict, disposition: str) -> dict:
    return {
        "id": npc.get("id"),
        "name": npc.get("name"),
        "role": npc.get("role"),
        "disposition": disposition,
        "voice_notes": npc.get("voice_notes"),
    }


def _target_summary(target: dict) -> dict:
    hp = target.get("hp", {})
    return {
        "id": target.get("npc_id"),
        "name": target.get("name"),
        "ac": target.get("ac"),
        "hp_current": hp.get("current"),
        "hp_max": hp.get("max"),
        "description": target.get("description"),
    }


def _resolve_ambient_sounds(location: dict | None, world_time: str) -> str:
    """Pick ambient_sounds_night when world_time is night and the field exists,
    else fall back to ambient_sounds, else empty string."""
    if not location:
        return ""
    if world_time == "night" and location.get("ambient_sounds_night"):
        return location["ambient_sounds_night"]
    return location.get("ambient_sounds", "")


async def _resolve_disposition(npc_id: str, player_id: str, npc: dict) -> str:
    disposition = await db_queries.get_npc_disposition(npc_id, player_id)
    if disposition is None:
        disposition = npc.get("default_disposition", "neutral")
    return disposition


# --- Combat sound constants ---

SOUND_COMBAT_START = "combat_start_stinger"
SOUND_COMBAT_VICTORY = "combat_victory_stinger"
SOUND_COMBAT_DEFEAT = "combat_defeat_stinger"
SOUND_COMBAT_FLED = "combat_fled_stinger"
SOUND_ATTACK_HIT = "weapon_hit"
SOUND_ATTACK_MISS = "weapon_miss"
SOUND_ATTACK_CRITICAL = "critical_hit"
SOUND_HEARTBEAT = "heartbeat_low_hp"
SOUND_DEATH_SAVE_SUCCESS = "death_save_success"
SOUND_DEATH_SAVE_FAIL = "death_save_fail"
SOUND_DEATH_SAVE_CRITICAL = "death_save_critical_success"
SOUND_PLAYER_FALLEN = "player_fallen"
SOUND_PLAYER_DEATH = "player_death"
SOUND_PLAYER_STABILIZED = "player_stabilized"

# --- Story moment constants ---

STORY_MOMENTS: dict[str, tuple[str, str]] = {
    # moment_key: (template_id, asset_slug)
    "combat": ("story_combat", "story_combat_victory"),
    "hollow_encounter": ("story_hollow_encounter", "story_hollow_encounter"),
    "god_contact": ("story_god_contact", "story_god_contact"),
}
MAX_STORY_MOMENTS_PER_SESSION = 3


# --- Re-exports from focused modules ---
# Allows existing ``from tools import X`` to keep working.

from action_tools import (  # noqa: E402, F401
    _apply_world_effects,
    _check_exit_requirement,
    _clamp_disposition_shift,
    add_to_inventory,
    award_divine_favor,
    award_xp,
    end_session,
    move_player,
    record_story_moment,
    remove_from_inventory,
    update_npc_disposition,
    update_quest,
)
from check_tools import (  # noqa: E402, F401
    discover_hidden_element,
    mark_skill_breakthrough,
    request_attack,
    request_saving_throw,
    request_skill_check,
    roll_dice,
)
from combat_tools import (  # noqa: E402, F401
    _participant_summary,
    _publish_sounds,
    _require_combat,
    end_combat,
    request_death_save,
    resolve_enemy_turn,
    start_combat,
)
from environment_tools import (  # noqa: E402, F401
    play_sound,
    set_music_state,
)
from query_tools import (  # noqa: E402, F401
    query_inventory,
    query_location,
    query_lore,
    query_npc,
)
from scene_tools import (  # noqa: E402, F401
    _build_scene_context,
    _resolve_scene_from_graph,
    detect_scene_transition,
    enter_location,
    get_active_scene_for_context,
)
