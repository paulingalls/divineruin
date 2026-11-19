"""Prepare a hostile swing before publishing its post-roll reaction window."""

from dataclasses import asdict

import check_resolution_attack
import combat_wrongdoing
import zhael_fate
from combat_action_availability import begin_execution
from combat_attack_roll import attack_roll_inputs, promote_attack, record_beacon_attack, roll_attack, serialize_roll


async def roll_hostile(session, state, head, declaration, action, contribution, packet_deps, fate_rolls):
    attacker = state.get_participant(head["actor_id"])
    target = state.get_participant(declaration.target_id)
    stored = head.get("fate_attack")
    action = (
        head["executed_action"] if stored is not None else begin_execution(state, attacker, action, declaration, head)
    )
    ac_bonus = state.ac_modifiers.get(target.id, 0) + contribution
    enemies_remaining = sum(1 for p in state.participants if p.type == "enemy" and not p.is_fallen)
    first_attack = not state.first_attack_resolved
    prepared = None
    if stored is not None:
        assert fate_rolls is not None
        prepared = check_resolution_attack.PreparedAttack.from_dict(stored["prepared"])
        attacker_data = stored["attacker_data"]
    elif fate_rolls is not None:
        candidates = await zhael_fate.candidates(session, queries=packet_deps["queries"], conn=packet_deps["conn"])
        if candidates.choices(attacker.id):
            attacker_data, ac, attack_mod = attack_roll_inputs(attacker, target, ac_bonus, state)
            prepared = check_resolution_attack.prepare_attack(
                attacker_data, action, ac, attack_mod=attack_mod, target_conditions=target.conditions
            )
            if await fate_rolls.hold(
                session,
                "attack",
                attacker.id,
                prepared.original,
                prepared.d20,
                queries=packet_deps["queries"],
                conn=packet_deps["conn"],
                candidates=candidates,
            ):
                data = asdict(prepared)
                data["consumed"] = list(prepared.consumed)
                head["fate_attack"] = {"prepared": data, "attacker_data": attacker_data}
                return False
    if prepared is not None:
        assert fate_rolls is not None
        kept = fate_rolls.select(prepared.original)
        result = check_resolution_attack.finish_attack(
            attacker_data,
            action,
            prepared.d20.dc,
            target.hp_current,
            prepared,
            kept,
            damage_mult=attacker.damage_mult,
            target_conditions=target.conditions,
        )
        result = promote_attack(result, enemies_remaining, first_attack)
        effective_ac = prepared.d20.dc
        head.pop("fate_attack", None)
    else:
        result, effective_ac = roll_attack(
            attacker,
            action,
            target,
            target_ac_bonus=ac_bonus,
            enemies_remaining=enemies_remaining,
            is_first_attack_of_combat=first_attack,
            resolver=packet_deps["resolver"],
            combat_state=state,
        )
    combat_wrongdoing.record_attack(state, attacker, target)
    record_beacon_attack(state, attacker, target, result)
    head.update(roll=serialize_roll(result, effective_ac), reaction_ac_bonus=contribution)
    return True
