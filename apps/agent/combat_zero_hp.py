"""The zero-HP door: Hollowed rise, instant death, fall or companion KO, and what follows a death."""

import architect_zero_hp
import combat_grapple
import combat_hollow_death
import combat_resolution
import conditions
import encounter_facts
from combat_fortitude import try_fortitude
from combat_sound_events import publish_combat_sounds as _publish_sounds
from patron_combat_edges import reward_worthy_foe
from session_data import CombatParticipant, CombatState, SessionData
from tool_support import SOUND_HOLLOW_RISE, SOUND_PLAYER_FALLEN


def _handle_hp_zero(
    session: SessionData,
    combat_state: CombatState | None,
    target: CombatParticipant,
    *,
    overkill: int,
    was_fallen: bool,
    hp_status: str,
    sounds: list[str],
    outcome: dict | None = None,
    fortitude_save=None,
    destroy: bool = False,
) -> tuple[str, bool, list[str]]:
    """Resolve a target dropped to 0 HP — Hollowed rise, instant death, fall, or companion KO.

    The ONE door for every zero-HP transition, whether the damage came from a blow or from the
    caster's own fire; a caller that drives HP to 0 without knocking leaves the flags behind
    (bug 16c5f8a0). The census that keeps it the only door is
    ``tests/combat/test_handle_hp_zero.py::TestTheDoorIsTheOnlyDoor``.
    Returns the HP status, whether a Hollowed rose, and ids released from this target's grapples."""
    if destroy:
        target.hp_current = 0
    elif (
        not was_fallen
        and target.unholy_fortitude is not None
        and not target.hollow_death_resolved
        and try_fortitude(target, outcome, fortitude_save)
    ):
        return combat_resolution.hp_threshold_status(target.hp_current, target.hp_max), False, []
    if not destroy and not was_fallen and target.type == "player" and conditions.hollowed_stage(target.conditions) >= 2:
        # Temporary Hollowed rise: a Stage-2+ Hollowed player at 0 HP does NOT
        # fall — their corpse rises as a hostile Temporary Hollowed combatant (HP=50% of max,
        # hits add 1d6 necrotic, immune to Charmed/Frightened/Poisoned) that blocks combat-end
        # until destroyed (combat_phase._wrap). Transform in place: flipping `type` makes the
        # engine's player-defeat gate go dormant (no player participant) and the echo block
        # victory, AND it deliberately suppresses the player-HP write + concentration-break +
        # armor-durability accrual below — the echo's HP is the monster's, not the player's.
        # The persisted Hollowed condition is left intact; trigger_character_death reads it at
        # the echo's destruction to mark hollow_killed and clear it.
        target.type = "temporary_hollowed"
        target.hp_current = max(1, target.hp_max // 2)
        target.conditions = conditions.apply_condition(target.conditions, "temporary_hollowed")
        hp_status = combat_resolution.hp_threshold_status(target.hp_current, target.hp_max)
        sounds.append(SOUND_HOLLOW_RISE)
        return hp_status, True, []

    if architect_zero_hp.collapse_structure(combat_state, target):
        return hp_status, False, []
    target.is_fallen = True
    combat_hollow_death.mark_destroyed(target)
    released = combat_grapple.release_from_grappler(combat_state, target.id) if combat_state is not None else []
    # Instant death: overkill (excess damage past 0) >= max HP kills
    # outright — no Fallen grace, no death saves. is_dead is the stronger state; the pure
    # _wrap reads it to end combat without a death-save beat. This is the one site with both
    # overkill + hp_max. Gated on `not was_fallen` so it fires only on the live -> 0
    # transition the spec scopes it to; a hit on an already-downed target is the separate
    # "damage while Fallen" failure mechanic.
    if destroy or (not was_fallen and overkill >= target.hp_max):
        target.is_dead = True
    sounds.append(SOUND_PLAYER_FALLEN)
    if target.type == "companion" and session.companion and target.id == session.companion.id:
        session.companion.is_conscious = False
        session.record_companion_memory(f"{target.name} was knocked unconscious in combat")
    return hp_status, False, released


async def _after_hp_change(
    session: SessionData,
    combat_state: CombatState | None,
    target: CombatParticipant,
    hp_before: int,
    was_fallen: bool,
    death_resolved_before: bool,
    counted_before: bool,
    *,
    queries,
    conn,
) -> list[dict]:
    import choir_encounter
    import still_encounter

    if combat_hollow_death.new_destruction(target, death_resolved_before, was_fallen, hp_before):
        await combat_hollow_death.accrue_death(session, combat_state, target, conn=conn, queries=queries)
        if combat_state is not None and combat_state.choir_encounter is not None:
            choir_encounter.destroyed(combat_state)
        architect_zero_hp.collapse_owned_walls(combat_state, target.id)

    renewals = await encounter_facts.renew_on_death(
        combat_state, target, counted_before, queries=queries, conn=conn, session=session
    )
    renewals.extend(
        await still_encounter.after_damage(
            session, combat_state, target, conn=conn, queries=queries, was_fallen=was_fallen
        )
    )
    return renewals


async def destroy_creature(
    session: SessionData, state: CombatState, target: CombatParticipant, *, queries, conn, sink
) -> dict:
    hp_before = target.hp_current
    counted_before = encounter_facts.counted_death(target)
    death_resolved_before = target.hollow_death_resolved
    sounds: list[str] = []
    hp_status, _, released = _handle_hp_zero(
        session,
        state,
        target,
        destroy=True,
        overkill=0,
        was_fallen=False,
        hp_status=combat_resolution.hp_threshold_status(0, target.hp_max),
        sounds=sounds,
    )
    await reward_worthy_foe(state, target, queries=queries, conn=conn)
    renewals = await _after_hp_change(
        session, state, target, hp_before, False, death_resolved_before, counted_before, queries=queries, conn=conn
    )
    await _publish_sounds(session, sounds, sink=sink)
    return {
        "target_hp_status": hp_status,
        "target_fallen": target.is_fallen,
        "target_dead": target.is_dead,
        **({"focus_renewals": renewals} if renewals else {}),
        **({"released_from_grapple": released} if released else {}),
    }
