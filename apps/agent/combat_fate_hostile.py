"""Prepare a hostile swing before publishing its post-roll reaction window."""

from copy import deepcopy
from dataclasses import asdict, replace

import check_resolution_attack
import combat_wrongdoing
import thyra_seasons
import zhael_fate
from ability_voice_rules import IMPLANT_DOUBT
from combat_action_availability import begin_execution
from combat_attack_roll import (
    attack_roll_inputs,
    promote_attack,
    record_beacon_attack,
    roll_attack,
    serialize_roll,
    shield_of_faith_ac,
    spend_sneak_attack,
)
from combat_reaction_defense import miss
from patron_synergy_combat import attack_player, witness_defense


async def roll_hostile(session, state, head, declaration, action, contribution, packet_deps, fate_rolls):
    attacker = state.get_participant(head["actor_id"])
    target = state.get_participant(declaration.target_id)
    stored = head.get("fate_attack")
    action = (
        head["executed_action"] if stored is not None else begin_execution(state, attacker, action, declaration, head)
    )
    ac_bonus = state.ac_modifiers.get(target.id, 0) + contribution
    first_attack = not state.first_attack_resolved
    prepared = None
    can_implant_doubt = any(IMPLANT_DOUBT in participant.reaction_ids for participant in state.participants)
    disadvantage_source = head.get("attack_disadvantage_source")
    if stored is not None:
        assert fate_rolls is not None
        prepared = check_resolution_attack.PreparedAttack.from_dict(stored["prepared"])
        attacker_data = stored["attacker_data"]
        if can_implant_doubt:
            head["attack_context"] = stored
    else:
        head["shield_of_faith_ac"] = shield_of_faith_ac(target.conditions)
        queries, conn = packet_deps["queries"], packet_deps["conn"]
        player = await attack_player(attacker, queries=queries, conn=conn)
        defender = await attack_player(target, queries=queries, conn=conn)
        valdris_ac_bonus = await witness_defense(defender, state, attacker, queries=queries, conn=conn)
        season = await thyra_seasons.season_for(player, conn=conn)
        candidates = None
        if fate_rolls is not None and not head.get("sidestep_escaped"):
            candidates = await zhael_fate.candidates(session, queries=queries, conn=conn)
        if can_implant_doubt or (candidates is not None and candidates.choices(attacker.id)):
            attacker_data, ac, attack_mod = attack_roll_inputs(
                attacker,
                target,
                ac_bonus,
                state,
                action,
                valdris_ac_bonus=valdris_ac_bonus,
                player=player,
                defender=defender,
                season=season,
                attack_disadvantage_source=disadvantage_source,
            )
            prepared = check_resolution_attack.prepare_attack(
                attacker_data, action, ac, attack_mod=attack_mod, target_conditions=target.conditions
            )
            context = {
                "prepared": {**asdict(prepared), "consumed": list(prepared.consumed)},
                "attacker_data": deepcopy(attacker_data),
            }
            if can_implant_doubt:
                head["attack_context"] = context
            if (
                candidates is not None
                and fate_rolls is not None
                and await fate_rolls.hold(
                    session,
                    "attack",
                    attacker.id,
                    prepared.original,
                    prepared.d20,
                    queries=queries,
                    conn=conn,
                    candidates=candidates,
                )
            ):
                head["fate_attack"] = context
                return False
    if prepared is not None:
        kept = fate_rolls.select(prepared.original) if fate_rolls is not None else prepared.original
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
        spend_sneak_attack(attacker, state, result)
        result = promote_attack(result, state, first_attack)
        effective_ac = prepared.d20.dc
        head.pop("fate_attack", None)
    else:
        assert stored is None
        result, effective_ac = roll_attack(
            attacker,
            action,
            target,
            valdris_ac_bonus=valdris_ac_bonus,
            target_ac_bonus=ac_bonus,
            is_first_attack_of_combat=first_attack,
            resolver=packet_deps["resolver"],
            combat_state=state,
            player=player,
            defender=defender,
            season=season,
            attack_disadvantage_source=disadvantage_source,
        )
    if head.get("sidestep_escaped"):
        result = miss(replace(result, narrative_hint="The target stepped out of melee reach."), target)
    combat_wrongdoing.record_attack(state, attacker, target)
    record_beacon_attack(state, attacker, target, result)
    head.update(roll=serialize_roll(result, effective_ac), reaction_ac_bonus=contribution)
    return True
