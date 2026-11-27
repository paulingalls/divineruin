"""Persist and surface concentration ending from damage or incapacitating conditions.

There is no concentration HUD element, so a break is returned for the caller to surface in its
DM-facing response rather than pushed as a client event nothing would consume.
"""

from functools import partial

import asyncpg

import check_resolution_save
import concentration
import db
import db_mutations_concentration
import db_mutations_conditions
import db_queries
import encounter_facts
import spells
from combat_fate_rolls import packet_save
from session_data import CombatState, ConcentrationState, SessionData


async def break_concentration_on_damage(
    session: SessionData,
    damage: int,
    incapacitated: bool,
    *,
    damaged_player_id: str,
    queries=db_queries,
    resolver=check_resolution_save,
    concentration_mutations=db_mutations_concentration,
    spells_mod=spells,
    combat_state=None,
    conn=None,
    progress=None,
    receipt: dict | None = None,
) -> str | None:
    """Resolve the DAMAGED party member's (``damaged_player_id``) CON save after taking ``damage``;
    end concentration on a failed save or incapacitation. Returns the spell_id that broke (for the
    DM to narrate), or None when nothing breaks — not concentrating, no damage, or the save held.

    ``damaged_player_id`` is required and REQUIRED to be an existing party member (resolved via
    ``session.member_state``, fail-loud on an unknown id) — a party can have >1 member (M18), so
    the member whose concentration is at risk is whoever actually took the damage, not necessarily
    the primary.

    The DC scales with damage (concentration.check_concentration); the save is the canonical
    proficiency-aware CON save (resolver.resolve_saving_throw); the save's own verdict decides
    keep or break (natural 1 fails, natural 20 holds), and incapacitation auto-fails without a roll. Persists the
    end via concentration_mutations.update_player_concentration(damaged_player_id, None) and clears
    the in-memory member state, mirroring how cast_spell sets/ends concentration.

    ``conn`` joins the break to a caller's transaction: in combat the phase loop passes its phase
    conn so a rolled-back phase reverts the break too (story-007). The player fetch reads the same
    conn so the save sees the in-tx state. Without a caller transaction, the default ``None``
    runs the write on its own connection.

    ``combat_state`` is the WORKING combat state to read/mutate. The phase loop resolves against a
    deep-copied working state and only adopts it as session.combat_state AFTER the tx commits
    (combat_turn), so DURING resolution session.combat_state is a DIFFERENT, pristine object — both
    the caster-conditions lookup (CON save) and the linked-condition strip must hit the working
    state the loop persists, not the discarded pristine copy. The phase loop threads its working
    state here; the OOC Draethar path and direct callers pass ``None`` and fall back to
    session.combat_state (the object they themselves persist), keeping the default path correct.
    """
    member = session.member_state(damaged_player_id)
    spell_id = member.concentration.spell_id
    if spell_id is None or damage <= 0:
        return None

    cstate = combat_state if combat_state is not None else session.combat_state

    dc = concentration.check_concentration(damage)
    # Incapacitation auto-fails (the engine enforces it) — skip the pointless roll and DB fetch.
    holds = False
    if not incapacitated:
        player = await queries.get_player(damaged_player_id, conn=conn)
        if player is None:
            # The player row is gone (a data glitch — an in-combat caster should always exist). Fail
            # safe: don't roll an unfounded save and don't strip their spell; leave concentration as-is.
            return None
        participant = cstate.get_participant(damaged_player_id) if cstate else None
        if participant is not None:
            player["conditions"] = participant.conditions
        save = await packet_save(
            progress,
            session,
            damaged_player_id,
            "concentration",
            partial(
                resolver.resolve_saving_throw,
                player,
                "constitution",
                dc,
                "concentration",
                advantage=encounter_facts.hearth_save_advantage(cstate, damaged_player_id),
                bonus_dice_eligible=False,
                originating_participant_id=progress.originating_participant_id if progress is not None else None,
                rally_sources=encounter_facts.pending_rally(combat_state, damaged_player_id),
            ),
            state=cstate,
            queries=queries,
            conn=conn,
            player=player,
        )
        if save is None:
            return None
        holds = save.success
        if receipt is not None and (save.rally_sources or save.oath_justice is not None or save.oath_timed is not None):
            receipt["concentration_save"] = {
                "roll": save.roll,
                "total": save.total,
                "dc": save.dc,
                "success": save.success,
                **save.oath_fields(),
                **encounter_facts.rally_receipt(damaged_player_id, save.rally_sources),
            }

    if holds:
        return None

    return await end_concentration(
        session,
        damaged_player_id,
        combat_state=combat_state,
        conn=conn,
        concentration_mutations=concentration_mutations,
        spells_mod=spells_mod,
    )


async def break_concentration_on_incapacitation(
    session: SessionData,
    player_id: str,
    *,
    combat_state,
    conn,
    concentration_mutations=db_mutations_concentration,
    spells_mod=spells,
) -> str | None:
    return await end_concentration(
        session,
        player_id,
        combat_state=combat_state,
        conn=conn,
        concentration_mutations=concentration_mutations,
        spells_mod=spells_mod,
    )


def _release_sustained(conditions: list[dict], spell_id: str, applied: str, caster_id: str) -> list[dict]:
    remaining = []
    for condition in conditions:
        if (condition["type"], condition.get("source")) == (applied, spell_id):
            casters = [cid for cid in condition.get("sustaining_caster_ids", []) if cid != caster_id]
            if casters:
                remaining.append({**condition, "sustaining_caster_ids": casters})
        else:
            remaining.append(condition)
    return remaining


async def release_persisted_spell_conditions(
    state: CombatState | None,
    spell_id: str,
    applied: str,
    caster_id: str,
    *,
    conn,
    locked_rows: dict[str, dict] | None = None,
) -> None:
    if locked_rows is None:
        recipients = await db_mutations_conditions.sustaining_recipient_ids(spell_id, applied, caster_id, conn=conn)
        # The checkpoint restores the roster and concentration. Participant rows reconcile at combat end.
        participants = {p.id for p in state.participants} if state is not None else set()
        lock_ids = sorted((set(recipients) | {caster_id}) - participants)
        locked_rows = await db_queries.get_players_for_update(lock_ids, conn=conn)
    writes = {}
    for pid, row in locked_rows.items():
        before = row.get("conditions") or []
        after = _release_sustained(before, spell_id, applied, caster_id)
        if before != after:
            writes[pid] = after
    await db_mutations_conditions.save_many_player_conditions(writes, conn=conn)
    for pid, updated in writes.items():
        locked_rows[pid]["conditions"] = updated


def remove_owned_spell_conditions(state: CombatState, spell_id: str, caster_id: str, *, applied: str | None) -> None:
    for participant in state.participants:
        active = [
            condition
            for condition in participant.conditions
            if (condition.get("source"), condition.get("originating_participant_id")) != (spell_id, caster_id)
        ]
        participant.conditions = (
            _release_sustained(active, spell_id, applied, caster_id) if applied is not None else active
        )


async def end_concentration(
    session: SessionData,
    player_id: str,
    *,
    combat_state,
    conn,
    concentration_mutations=db_mutations_concentration,
    spells_mod=spells,
    updates: dict[str, ConcentrationState] | None = None,
    record: ConcentrationState | None = None,
    release_combat_rows: bool = False,
) -> str | None:
    member = session.member_state(player_id)
    spell_id = (record if record is not None else member.concentration).spell_id
    if spell_id is None:
        return None
    cstate = combat_state if combat_state is not None else session.combat_state
    applied = spells_mod.get_spell(spell_id).applies_condition

    async def persist(connection) -> None:
        if applied is not None:
            await release_persisted_spell_conditions(
                None if release_combat_rows else cstate, spell_id, applied, player_id, conn=connection
            )
        await concentration_mutations.update_player_concentration(player_id, None, conn=connection)

    if applied is not None and (conn is None or isinstance(conn, asyncpg.Pool)):
        pool = conn or await db.get_pool()
        async with pool.acquire() as connection, connection.transaction():
            await persist(connection)
    else:
        await persist(conn)

    if cstate is not None:
        remove_owned_spell_conditions(cstate, spell_id, player_id, applied=applied)
    if updates is None:
        member.concentration = ConcentrationState()
    else:
        updates[player_id] = ConcentrationState()
    return spell_id
