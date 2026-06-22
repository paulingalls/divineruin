"""In-combat ABILITY (cast) resolution helpers.

Splits the ability-cast concern out of combat_support (story-007): resolving an
in-combat ABILITY declaration through the shared cast logic, the side-channel that
carries the cast result back to the phase loop, action lookup, and enhancer-rider
attachment. Consumed by the phase loop (combat_turn)."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from livekit.agents.llm import ToolError

import ability_persistence
import check_resolution
import combat_enhancers
import combat_resolution
import event_types as E
import spell_casting
from combat_events import emit_or_publish
from dice import roll as dice_roll
from rules_engine import attribute_modifier
from session_data import CombatParticipant, SessionData

if TYPE_CHECKING:
    from spell_casting import CastResult

# Diplomat de-escalation (M4.6a story-004, spec game_mechanics_combat.md:175-183).
_DEESCALATE_FOCUS_COST = 3
_DEESCALATE_BASE_DC = 15


def _lead_enemy(state):
    """The living enemy the Diplomat addresses: highest WIS resists hardest (spec L180)."""
    living = [p for p in state.participants if p.type == "enemy" and not p.is_fallen]
    if not living:
        return None
    return max(living, key=lambda e: e.attributes.get("wisdom", 10))


def _gate_deescalation(player: dict, state) -> None:
    """Declare-time fail-loud gate for de_escalate: one attempt per encounter, 3 Focus.

    Mirrors spell_casting._gate_spell's pre-resolution discipline — validate with NO state
    writes so a bad attempt never rolls back a phase that already resolved other actors."""
    if state.deescalation_used:
        raise ToolError("De-escalate can only be attempted once per encounter.")
    have = (player.get("focus") or {}).get("current", 0)
    if have < _DEESCALATE_FOCUS_COST:
        raise ToolError(f"De-escalate costs {_DEESCALATE_FOCUS_COST} Focus; you have {have}.")


async def _resolve_deescalation_packet(
    session: SessionData,
    attacker: CombatParticipant,
    decl,
    *,
    state,
    conn,
    player: dict | None,
    sink=None,
    persistence=ability_persistence,
    rng=None,
) -> dict:
    """Resolve a de_escalate ABILITY in combat (M4.6a story-004).

    Focus + lockout are pre-validated at declare time (_gate_deescalation); here we spend the
    3 Focus, roll the contested CHA-vs-lead-enemy-WIS gate plus one argument, set the combat-end
    flags on CombatState, and emit the always-dramatic de_escalate DICE_ROLL. ``player`` is the
    for_update row from prevalidation (reused, so the lock is taken once). The flags are set on
    the phase loop's working ``state`` (the deep-copied next_state the wrap reads), NOT
    session.combat_state — that stays the pristine pre-phase copy until the tx commits."""
    if state is None or player is None:
        return {"actor_id": attacker.id, "resolved": False, "reason": "no active combat or player"}
    lead = _lead_enemy(state)
    if lead is None:
        return {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": "no living enemy to de-escalate",
        }

    have = (player.get("focus") or {}).get("current", 0)
    await persistence.update_player_resources(session.player_id, focus=have - _DEESCALATE_FOCUS_COST, conn=conn)

    attrs = player.get("attributes", {})
    cha_total = dice_roll("d20", rng=rng).total + attribute_modifier(attrs.get("charisma", 10))
    enemy_wis_total = dice_roll("d20", rng=rng).total + attribute_modifier(lead.attributes.get("wisdom", 10))
    argument_total = check_resolution.resolve_skill_check_dc(player, "persuasion", _DEESCALATE_BASE_DC, rng).total

    outcome = combat_resolution.resolve_deescalation(
        cha_total=cha_total,
        enemy_wis_total=enemy_wis_total,
        argument_total=argument_total,
        base_dc=_DEESCALATE_BASE_DC,
    )
    state.deescalation_used = True
    if outcome.ends_combat:
        state.deescalated = True

    await emit_or_publish(
        sink,
        session.room,
        E.DICE_ROLL,
        {
            "roll_type": "de_escalate",
            "actor": attacker.name,
            "scene_entered": outcome.scene_entered,
            "success": outcome.success,
            "dramatic": outcome.dramatic,
            "context": outcome.context,
        },
        event_bus=session.event_bus,
    )
    session.record_event(
        f"{attacker.name} attempts de-escalation: {'combat ends' if outcome.ends_combat else 'combat continues'}"
    )
    return {
        "actor_id": attacker.id,
        "resolved": True,
        "declaration_type": str(decl.type),
        "action": "de_escalate",
        "deescalation": {
            "scene_entered": outcome.scene_entered,
            "success": outcome.success,
            "ends_combat": outcome.ends_combat,
            "narrative_cue": outcome.narrative_cue,
        },
    }


@dataclass
class AbilityCastOutcome:
    """Side-channel carrying an in-loop ABILITY cast's ``CastResult`` back to the phase loop.

    At most one player ability resolves per phase (one declaration per participant), so a single
    slot suffices. The loop reads ``cast_result`` post-commit to seed the WRAP resonance, sync
    concentration in-memory, and flush the cast's deferred client events — all of which must happen
    after the phase tx commits (story-007). ``cast_result`` stays ``None`` when no ability resolved."""

    cast_result: "CastResult | None" = None


async def _resolve_ability_packet(
    session: SessionData,
    attacker: CombatParticipant,
    decl,
    *,
    cast_resolver,
    conn,
    player: dict | None,
    cast_outcome: AbilityCastOutcome,
) -> dict:
    """Resolve one in-combat ABILITY declaration through the shared cast logic (story-007).

    Player-gated: only the player carries a Focus pool + resonance track, so a non-player ABILITY
    (or one missing its action) is a *wasted* packet — enemy/companion casting is later M4.x work.
    Delegates to ``cast_resolver._resolve_cast`` with the cast's own RESONANCE_CHANGED suppressed
    (in combat the phase WRAP push is the single authoritative HUD update), stashing the returned
    CastResult on ``cast_outcome`` for the loop to commit. The returned summary carries the spell
    packet for the DM plus any narrated enhancer riders."""
    if attacker.type != "player":
        return {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": "ability resolution not yet implemented for non-player actors",
        }
    if not decl.action:
        return {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": "ability declaration missing an action",
        }

    result = await cast_resolver._resolve_cast(
        session,
        decl.action,
        conn=conn,
        player=player,
        target_id=decl.target_id,
        suppress_resonance_changed=True,
    )
    cast_outcome.cast_result = result
    # Sync concentration into the session SSOT IN-LOOP (not post-commit): a lower-initiative enemy
    # attack later this same phase runs break_concentration_on_damage, which reads the in-memory
    # session.concentration to pick which spell to save for and to clear on a failed save. A
    # post-commit sync would leave it stale — the break would save against the OLD spell and, on a
    # break, write None to the DB (clearing the just-cast spell) while the post-commit sync forced
    # memory back to the new spell, diverging from the DB (story-007). _CombatScratchSnapshot
    # captures concentration, so this in-tx mutation is reverted if the phase rolls back.
    if result.concentration_spell_id is not spell_casting._UNCHANGED:
        session.concentration.spell_id = cast("str | None", result.concentration_spell_id)
    summary = {
        "actor_id": attacker.id,
        "resolved": True,
        "declaration_type": str(decl.type),
        "action": decl.action,
        "cast": result.packet,
    }
    return _attach_riders(summary, attacker, decl)


def _find_action(participant, action_name) -> dict | None:
    """Find the named action in a participant's action_pool (case-insensitive)."""
    if not action_name:
        return None
    wanted = str(action_name).lower()
    for a in participant.action_pool:
        if a.get("name", "").lower() == wanted:
            return a
    return None


def _attach_riders(summary: dict, attacker, decl) -> dict:
    """Add the actor's narrated enhancer riders to a packet summary, if any.

    Riders are descriptive (non-mechanical) — they carry no HP/AC effect, just the DM
    cue for an enhancer's expansion (Cunning Action's dash/disengage/hide, Hit and Run,
    Command Lesser, Quick Change). Omitted entirely when the actor has none, so a
    no-enhancer declaration keeps its flat summary (AC3: no phantom expansion)."""
    riders = combat_enhancers.declaration_riders(attacker.enhancers, decl)
    if riders:
        summary["riders"] = riders
    return summary
