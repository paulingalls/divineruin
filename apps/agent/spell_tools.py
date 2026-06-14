"""Spell acquisition helpers (M8 story-005).

Spells add ZERO new @function_tools (ADR 0007): the generic learn(kind, id, source)
verb in recipe_tools dispatches kind="spell" here. `_learn_spell_impl` validates the
immediate-acquisition source, enforces the per-archetype level→tier unlock gate
(leveling.is_spell_tier_unlocked, keyed by the caster's archetype), and records the
learn via character_spells.record_learned. Errors raise LiveKit `ToolError` (ADR 0002);
the `*_mod=` keyword seams are TEST-ONLY (production callers use the defaults).
"""

import json
import logging

from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import character_spells
import db_queries
import leveling
import spells
from session_data import SessionData
from tool_support import _validate_id

logger = logging.getLogger("divineruin.spell_tools")

# Immediate-acquisition sources learn(kind="spell") accepts. "training" is the async
# study-cycle track (story-004 worker), not instant-learnable through this verb.
SPELL_LEARN_SOURCES = frozenset({"discovery", "npc_teaching"})


async def _learn_spell_impl(
    context: RunContext[SessionData],
    spell_id: str,
    source: str,
    *,
    queries_mod=db_queries,
    spells_mod=spells,
    character_spells_mod=character_spells,
    leveling_mod=leveling,
) -> str:
    context.disallow_interruptions()
    _validate_id(spell_id, "spell_id")
    if source not in SPELL_LEARN_SOURCES:
        raise ToolError(f"Invalid spell source {source!r}; expected one of {sorted(SPELL_LEARN_SOURCES)}.")

    # Catalog lookup is an in-memory read (no IO) — do it before touching the DB.
    try:
        spell = spells_mod.get_spell(spell_id)
    except ValueError as exc:
        raise ToolError(f"Unknown spell: {spell_id}") from exc

    player_id = context.userdata.player_id
    player = await queries_mod.get_player(player_id)
    if not player:
        raise ToolError(f"Unknown player: {player_id}")

    level = player.get("level", 1)
    archetype = player.get("class", "")
    try:
        unlocked = leveling_mod.is_spell_tier_unlocked(archetype, spell.spell_tier, level)
    except ValueError as exc:
        # Non-caster archetype (no spell-tier table) — surface as a user-facing tool error.
        raise ToolError(f"{archetype or 'This archetype'} cannot learn spells.") from exc
    if not unlocked:
        floor = leveling_mod.min_level_for_tier(archetype, spell.spell_tier)
        if floor is None:
            raise ToolError(f"Cannot learn {spell_id}: {spell.spell_tier} spells are not available to {archetype}.")
        raise ToolError(
            f"Cannot learn {spell_id}: {spell.spell_tier} spells unlock at level {floor} for "
            f"{archetype}, character is level {level}."
        )

    logger.info("learn spell: player=%s spell=%s tier=%s via=%s", player_id, spell_id, spell.spell_tier, source)
    await character_spells_mod.record_learned(player_id, spell_id, source)

    return json.dumps(
        {
            "learned": spell_id,
            "name": spell.name,
            "tier": spell.spell_tier,
            "acquisition_track": source,
        }
    )
