"""In-combat ABILITY (cast) resolution helpers.

Splits the ability-cast concern out of combat_support (story-007): resolving an
in-combat ABILITY declaration through the shared cast logic, the side-channel that
carries the cast result back to the phase loop, action lookup, and enhancer-rider
attachment. Consumed by the phase loop (combat_turn)."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import combat_enhancers
import spell_casting
from session_data import CombatParticipant, SessionData

if TYPE_CHECKING:
    from spell_casting import CastResult


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
