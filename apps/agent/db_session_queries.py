"""Session-init payload builders — composes the full session_init payload.

Extracted from db_queries.py (story-008) by SRP. All async composers; they call
the general-purpose reads that remain in db_queries.
"""

import asyncio
import logging

import abilities
import character_spells
import db
import db_activity_queries
import db_content_queries
import db_queries
import spells
from companion_profiles import get_companion_profile

logger = logging.getLogger("divineruin.db")


async def _enrich_quests_with_scene_hints(quests: list[dict]) -> list[dict]:
    """Add 'hints' from scene beats to each quest's data for client display."""
    from scene_tools import _resolve_scene_from_graph

    scene_ids: list[str] = []
    for q in quests:
        for entry in q.get("scene_graph", []):
            sid = entry.get("scene_id")
            if sid and sid not in scene_ids:
                scene_ids.append(sid)
    if not scene_ids:
        return quests

    scene_cache = await db_content_queries.get_scenes_batch(scene_ids)
    for q in quests:
        scene = _resolve_scene_from_graph(scene_cache, q, q.get("current_stage", 0))
        hints: list[str] = []
        if scene:
            for beat in scene.get("beats", []):
                hints.extend(beat.get("companion_hints", []))
        q["hints"] = hints
    return quests


def _enrich_spell_row(spell_id: str, *, is_prepared: bool) -> dict | None:
    """Catalog-enrich one spell id for the character-sheet payload, or None if unknown.

    Display-only: an unresolvable id (missing catalog entry) is skipped (logged) rather
    than aborting the whole session payload — the FK + strict loader make this rare.
    """
    try:
        spell = spells.get_spell(spell_id)
    except ValueError:
        logger.warning("session_init: skipping unknown spell %r", spell_id)
        return None
    return {
        "spell_id": spell.id,
        "name": spell.name,
        "spell_tier": spell.spell_tier,
        "focus_cost": spell.focus_cost,
        "is_prepared": is_prepared,
    }


async def _build_player_spells(player_id: str, player: dict | None) -> dict:
    """Build the {core, learned} spell payload for the character sheet (story-007).

    core = the archetype's always-known spell-backed abilities (always prepared);
    learned = the character_spells elective library. A learned spell that is also core
    is deduped out of learned (core is the always-prepared grant). Each row is
    catalog-enriched to {spell_id, name, spell_tier, focus_cost, is_prepared}.
    """
    archetype_id = player.get("class") if player else None
    core: list[dict] = []
    core_ids: set[str] = set()
    if archetype_id:
        for ability in abilities.get_archetype_abilities(archetype_id):
            if ability.ability_type == "core" and ability.spell_id:
                row = _enrich_spell_row(ability.spell_id, is_prepared=True)
                if row:
                    core.append(row)
                    core_ids.add(ability.spell_id)

    learned: list[dict] = []
    for known in await character_spells.get_known(player_id):
        if known["spell_id"] in core_ids:
            continue
        row = _enrich_spell_row(known["spell_id"], is_prepared=known["is_prepared"])
        if row:
            learned.append(row)

    return {"core": core, "learned": learned}


async def get_session_init_payload(player_id: str) -> dict:
    """Build the full session_init payload for a player."""
    # Fetch player first (need location_id), then parallelize the rest
    player = await db_queries.get_player(player_id)
    location_id = player.get("location_id", "") if player else ""

    location, inventory, quests, map_progress = await asyncio.gather(
        db_content_queries.get_location(location_id) if location_id else asyncio.sleep(0),
        db_queries.get_player_inventory(player_id),
        db_queries.get_active_player_quests(player_id),
        db_activity_queries.get_player_map_progress(player_id),
    )

    # Enrich quests with scene beat hints for client display
    quests = await _enrich_quests_with_scene_hints(quests)

    # The companion's identity: resolved ONCE and passed into the portrait builder so the
    # payload and the portrait can never name two different companions. Nothing shipped a
    # companion name to the client before this — constraint 6, this is the producer.
    companion_id = db.resolve_player_companion_id(player)
    companion = None
    if companion_id is not None:
        profile = get_companion_profile(companion_id)
        companion = {"id": profile.id, "name": profile.name, "voice_id": profile.voice_id}
    portraits = db._build_portraits(companion_id)

    # Character-sheet spell list: core (archetype-fixed) + learned electives (story-007).
    spell_list = await _build_player_spells(player_id, player)

    return {
        "character": player,
        "location": location if location_id else None,
        "quests": quests,
        "inventory": inventory,
        "map_progress": map_progress,
        "world_state": {"time": "evening"},
        "portraits": portraits,
        "spells": spell_list,
        "companion": companion,
    }
