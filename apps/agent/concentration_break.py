"""Concentration break-on-damage consumer (story-008, M3.4).

The single production consumer of the pure concentration engine (concentration.py): when a
concentrating player takes damage, roll a CON save (DC scales with the damage) and end
concentration on a failed save — or automatically when the damage leaves them incapacitated.
Called from every combat damage site (enemy attacks in combat_turn, the Draethar inner_fire
self-damage), so the break logic lives here ONCE rather than duplicated at each.

The pure engine stays content-/IO-agnostic in concentration.py (check_concentration computes the
DC, concentration_holds owns the keep/break decision incl. the incapacitation auto-fail); this
module does the I/O the engine can't — the player fetch, the canonical CON save roll
(check_resolution_save.resolve_saving_throw, proficiency-aware), and the persisted end. There is no
concentration HUD element, so the break is returned for the caller to surface in its DM-facing
response rather than pushed as a (consumer-less) client event.
"""

import check_resolution_save
import concentration
import conditions
import db_mutations_concentration
import db_queries
import spells
from session_data import SessionData


async def break_concentration_on_damage(
    session: SessionData,
    damage: int,
    incapacitated: bool,
    *,
    queries=db_queries,
    resolver=check_resolution_save,
    concentration_mutations=db_mutations_concentration,
    spells_mod=spells,
    conn=None,
) -> str | None:
    """Resolve a concentrating player's CON save after taking ``damage``; end concentration on a
    failed save or incapacitation. Returns the spell_id that broke (for the DM to narrate), or
    None when nothing breaks — not concentrating, no damage, or the save held.

    The DC scales with damage (concentration.check_concentration); the save is the canonical
    proficiency-aware CON save (resolver.resolve_saving_throw); the keep/break decision and the
    incapacitation auto-fail are the engine's (concentration.concentration_holds). Persists the
    end via concentration_mutations.update_player_concentration(player_id, None) and clears the
    in-memory session state, mirroring how cast_spell sets/ends concentration.

    ``conn`` joins the break to a caller's transaction: in combat the phase loop passes its phase
    conn so a rolled-back phase reverts the break too (story-007). The player fetch reads the same
    conn so the save sees the in-tx state. Out of combat (Draethar inner fire) the default ``None``
    runs the write on its own connection, post-commit, as before.
    """
    spell_id = session.concentration.spell_id
    if spell_id is None or damage <= 0:
        return None

    dc = concentration.check_concentration(damage)
    # Incapacitation auto-fails (the engine enforces it) — skip the pointless roll and DB fetch.
    save_total = 0
    if not incapacitated:
        player = await queries.get_player(session.player_id, conn=conn)
        if player is None:
            # The player row is gone (a data glitch — an in-combat caster should always exist). Fail
            # safe: don't roll an unfounded save and don't strip their spell; leave concentration as-is.
            return None
        # Thread the caster's in-combat conditions into the CON save (M4.3): Exhausted -1/stack
        # lowers it, Stunned/Paralyzed auto-fail it. Conditions live on the in-memory
        # CombatParticipant, not the DB player row; out of combat there are none ([]).
        participant = session.combat_state.get_participant(session.player_id) if session.combat_state else None
        player["conditions"] = participant.conditions if participant is not None else []
        # Damage-triggered CON save is engine-auto: it never spends the caster's beneficial +1d4
        # (M4.8 story-003) — only player-initiated saves do.
        save_total = resolver.resolve_saving_throw(
            player, "constitution", dc, "concentration", bonus_dice_eligible=False
        ).total

    if concentration.concentration_holds(save_total, dc, incapacitated=incapacitated):
        return None

    # Persist the end BEFORE clearing the in-memory SSOT (mirrors cast_spell's commit-then-sync):
    # a failed write leaves session.concentration intact rather than diverging from the DB, which
    # would otherwise re-populate the old spell on the next session reload.
    await concentration_mutations.update_player_concentration(session.player_id, None, conn=conn)
    session.concentration.spell_id = None

    # Concentration→condition lifecycle (M4.8 story-006, risk 0899a89ef0da): a concentration spell
    # that granted a beneficial condition (Bless → blessed) loses it when the spell ends, so the +1d4
    # does not outlive the broken concentration. Strip the spell's applies_condition from the
    # in-combat participants it buffed; the mutation rides the phase loop's save_combat_state (like
    # the combat-ability consume). OOC breaks (no combat_state) leave OOC buffs as-is.
    applied = spells_mod.get_spell(spell_id).applies_condition
    if applied is not None and session.combat_state is not None:
        for participant in session.combat_state.participants:
            participant.conditions = conditions.remove_conditions(participant.conditions, (applied,))
    return spell_id
