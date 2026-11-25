"""Dispatch resolved weapon actions through the encounter or swing path."""

import architect_actions
import combat_martial
from combat_ability import _with_variant
from combat_ability_gate import CLEAVING_BLOW, declared_ability
from combat_fate import continue_attack
from condition_sources import DeliveryRefused


async def resolve(
    session, state, packet, attacker, target, action, held_head, attack_deps, *, opportunity_attack, player_movement
):
    if opportunity_attack:
        # An opportunity swing skips encounter-owner resolution (the Architect's Slam push and
        # Geometry auto-hit): displacing the mover would break the paused route it resumes.
        return await continue_attack(
            session,
            state,
            packet,
            attacker,
            target,
            [action],
            sum(p.type == "enemy" and not p.is_fallen for p in state.participants),
            not state.first_attack_resolved,
            **{**attack_deps, "attack_cursor": {}},
        )
    if player_movement is not None:
        attack_deps["player_movement"] = player_movement
    return await architect_actions.resolve(session, state, packet, attacker, target, action, held_head, attack_deps)


async def resolve_multi_target(session, state, packet, attacker, player, attack_deps) -> dict:
    decl = packet.declaration
    resolved = declared_ability(decl.action)
    assert resolved is not None
    ability, _ = resolved
    weapon = combat_martial.main_hand(player, ability.name)
    base = {"actor_id": attacker.id, "action": decl.action, "declaration_type": str(decl.type), "resolved": False}
    skipped = {}
    if ability.id == CLEAVING_BLOW:
        targets = combat_martial.cleave_targets(decl)
        for target_id in targets:
            target = state.get_participant(target_id)
            if not combat_martial.standing_foe(target):
                skipped[target_id] = f"{target.name if target else target_id} is already down."
            elif reason := combat_martial.reach_refusal(state, attacker, target_id, weapon):
                skipped[target_id] = reason
    else:
        try:
            targets = combat_martial.whirlwind_targets(state, attacker, weapon)
        except DeliveryRefused as error:
            return {**base, "reason": str(error)}
    if len(skipped) == len(targets):
        return {
            **base,
            "reason": "No selected foe remains within main-hand melee reach.",
            "attacks": [combat_martial.skip_swing(target_id, skipped[target_id]) for target_id in targets],
        }

    variant = await combat_martial.pay(attacker.id, resolved, queries=attack_deps["queries"], conn=attack_deps["conn"])
    cursor = attack_deps["attack_cursor"]
    if cursor is None:
        cursor = {}
    cursor.update(
        swing_targets=targets,
        skipped_targets=skipped,
        variant_receipt=_with_variant({}, variant),
    )
    if ability.id == CLEAVING_BLOW:
        cursor["shared_faces"] = combat_martial.cleave_faces()
    anchor = state.get_participant(next(target_id for target_id in targets if target_id not in skipped))
    return await continue_attack(
        session,
        state,
        packet,
        attacker,
        anchor,
        [weapon] * len(targets),
        sum(p.type == "enemy" and not p.is_fallen for p in state.participants),
        not state.first_attack_resolved,
        **{**attack_deps, "attack_cursor": cursor},
    )
