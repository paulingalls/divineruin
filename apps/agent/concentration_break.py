"""Concentration break-on-damage consumer (story-008, M3.4).

The single production consumer of the pure concentration engine (concentration.py): when a
concentrating player takes damage, roll a CON save (DC scales with the damage) and end
concentration on a failed save — or automatically when the damage leaves them incapacitated.
Called from every combat damage site (enemy attacks in combat_turn, the Draethar inner_fire
self-damage), so the break logic lives here ONCE rather than duplicated at each.

The pure engine stays content-/IO-agnostic in concentration.py (check_concentration computes the
DC, concentration_holds owns the keep/break decision incl. the incapacitation auto-fail); this
module does the I/O the engine can't — the player fetch, the canonical CON save roll
(check_resolution.resolve_saving_throw, proficiency-aware), and the persisted end. There is no
concentration HUD element, so the break is returned for the caller to surface in its DM-facing
response rather than pushed as a (consumer-less) client event.
"""

import check_resolution
import concentration
import db_mutations_concentration
import db_queries
from session_data import SessionData


async def break_concentration_on_damage(
    session: SessionData,
    damage: int,
    incapacitated: bool,
    *,
    queries=db_queries,
    resolver=check_resolution,
    concentration_mutations=db_mutations_concentration,
) -> str | None:
    """Resolve a concentrating player's CON save after taking ``damage``; end concentration on a
    failed save or incapacitation. Returns the spell_id that broke (for the DM to narrate), or
    None when nothing breaks — not concentrating, no damage, or the save held.

    The DC scales with damage (concentration.check_concentration); the save is the canonical
    proficiency-aware CON save (resolver.resolve_saving_throw); the keep/break decision and the
    incapacitation auto-fail are the engine's (concentration.concentration_holds). Persists the
    end via concentration_mutations.update_player_concentration(player_id, None) and clears the
    in-memory session state, mirroring how cast_spell sets/ends concentration.
    """
    spell_id = session.concentration.spell_id
    if spell_id is None or damage <= 0:
        return None

    dc = concentration.check_concentration(damage)
    # Incapacitation auto-fails (the engine enforces it) — skip the pointless roll and DB fetch.
    save_total = 0
    if not incapacitated:
        player = await queries.get_player(session.player_id)
        save_total = resolver.resolve_saving_throw(player, "constitution", dc, "concentration").total

    if concentration.concentration_holds(save_total, dc, incapacitated=incapacitated):
        return None

    # Persist the end BEFORE clearing the in-memory SSOT (mirrors cast_spell's commit-then-sync):
    # a failed write leaves session.concentration intact rather than diverging from the DB, which
    # would otherwise re-populate the old spell on the next session reload.
    await concentration_mutations.update_player_concentration(session.player_id, None)
    session.concentration.spell_id = None
    return spell_id
