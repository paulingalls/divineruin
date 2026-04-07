# ruff: noqa: F401, I001
"""Barrel re-exports for DM agent tools.

Tool functions live in focused modules:
- scene_tools: Scene resolution and context building
- query_tools: World queries (location, NPC, lore, inventory)
- check_tools: Skill checks, attacks, saving throws, dice
- combat_tools: Combat lifecycle (start, enemy turns, death saves, end)
- progression_tools: XP awards and divine favor
- inventory_tools: Add and remove items
- movement_tools: Player location changes
- quest_tools: Quest progression and world effects
- session_tools: End session, story moments, NPC disposition
- environment_tools: Audio (sound effects, music state)

Shared helpers and constants live in tool_support.py.

This module re-exports all tool functions so existing ``from tools import X``
continues to work during migration. Will be deleted once all imports are rewired.
"""

from tool_support import *  # noqa: F403

import db
import db_activity_queries
import db_content_queries
import db_mutations
import db_queries
from game_events import publish_game_event

# --- Re-exports from focused modules ---

from check_tools import (
    discover_hidden_element,
    mark_skill_breakthrough,
    request_attack,
    request_saving_throw,
    request_skill_check,
    roll_dice,
)
from combat_tools import (
    _participant_summary,
    _publish_sounds,
    _require_combat,
    end_combat,
    request_death_save,
    resolve_enemy_turn,
    start_combat,
)
from environment_tools import (
    play_sound,
    set_music_state,
)
from inventory_tools import (
    add_to_inventory,
    remove_from_inventory,
)
from movement_tools import (
    _check_exit_requirement,
    move_player,
)
from progression_tools import (
    award_divine_favor,
    award_xp,
)
from query_tools import (
    query_inventory,
    query_location,
    query_lore,
    query_npc,
)
from quest_tools import (
    _apply_world_effects,
    _clamp_disposition_shift,
    update_quest,
)
from scene_tools import (
    _build_scene_context,
    _resolve_scene_from_graph,
    detect_scene_transition,
    enter_location,
    get_active_scene_for_context,
)
from session_tools import (
    end_session,
    record_story_moment,
    update_npc_disposition,
)
