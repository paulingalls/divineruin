"""Renewing Spark for an aid spell cast directly with ``activate`` while combat is active."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

import db_mutations
import db_queries
import event_types as E
from condition_produce import resolve_effective_targets
from game_events import publish_game_event
from patron_synergy_heal import grant_mage_warding, mage_warding_spell

if TYPE_CHECKING:
    import asyncpg

    from session_data import CombatState, SessionData
    from spells import Spell


async def settle(
    session: SessionData,
    spell: Spell,
    caster_id: str,
    target_id: str | None,
    target_ids: list[str] | None,
    packet: dict,
    events: list,
    *,
    conn: asyncpg.Connection,
    queries=db_queries,
) -> CombatState | None:
    """Ward the cast's living allied recipients on a copy of the combat image and persist it.

    The caller commits, then swaps the returned copy into the session. A direct cast applies no
    condition to combat participants, so a condition spell wards no one here."""
    if session.combat_state is None or not mage_warding_spell(spell) or spell.applies_condition is not None:
        return None
    caster = await queries.get_player(caster_id, conn=conn)
    if caster is None:
        raise RuntimeError(f"Missing player row for spell caster {caster_id}")
    state = deepcopy(session.combat_state)
    targets = resolve_effective_targets(target_ids, target_id, self_value=caster_id, dedup=True)
    recipients = {
        pid: target
        for pid in targets
        if (target := state.get_participant(pid)) is not None and target.is_ally and target.hp_current > 0
    }
    ward = await grant_mage_warding(caster, list(recipients), participants=recipients, queries=queries, conn=conn)
    if ward is None:
        return None
    packet["mage_warding"] = ward
    await db_mutations.save_combat_state(state.combat_id, state.to_dict(), conn=conn)
    for pid, target in recipients.items():
        if target.type != "player":
            continue
        health = {"current": target.hp_current, "max": target.hp_max, "temp_hp": target.temp_hp}
        events.append(
            lambda pid=pid, payload=health: publish_game_event(
                session.room, E.HP_CHANGED, payload, event_bus=session.event_bus, destination_identities=[pid]
            )
        )
    return state
