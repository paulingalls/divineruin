"""Close a held action's reaction window and schedule its continuations."""

import combat_hold_windows
import combat_reaction_contest
import combat_reaction_disruption
import combat_reaction_effect
import patron_synergy_combat
import reaction_spend
from combat_hold_actions import _attack_action
from combat_multiattack import strike_summary
from combat_natures_grasp import finish_held
from combat_state import CombatState
from patron_synergy_heal import grant_mage_warding
from reaction_windows import POST_ROLL


async def close_window(
    state: CombatState, head: dict, window: dict, summaries: list[dict], packet_deps: dict, contest_rng
) -> tuple[list[dict], bool]:
    hit_before_close = window["stage"] == POST_ROLL and (head["roll"] or {}).get("attack_result", {}).get("hit")
    attack_action = _attack_action(state, head)
    reaction_packets = combat_reaction_effect.close(
        state, head, window, attack_action=attack_action, contest_rng=contest_rng
    )
    queries, conn = packet_deps["queries"], packet_deps["conn"]
    for packet in reaction_packets:
        if packet.get("shield_spell_applied"):
            actor_id = packet["actor_id"]
            rows = await queries.get_players_for_update([actor_id], conn=conn)
            actor = state.get_participant(actor_id)
            assert actor is not None
            if ward := await grant_mage_warding(
                rows[actor_id], [actor_id], rows=rows, participants={actor_id: actor}, conn=conn
            ):
                packet["mage_warding"] = ward
    await patron_synergy_combat.grant_interceding_rallies(
        state, reaction_packets, window["target_id"], queries=queries, conn=conn
    )
    await patron_synergy_combat.restore_guard_stamina(reaction_packets, queries=queries, conn=conn)
    reaction_packets = combat_reaction_effect.defer_thought_shield(head, reaction_packets)
    hesitation_reason = combat_reaction_contest.hesitation_reason(head)
    if hesitation_reason is not None:
        summaries.extend(
            combat_reaction_disruption.defer(state, head, reaction_packets, hesitation_reason, attack_action)
        )
        summaries.extend(combat_reaction_effect.finish_thought_shield(head, {}))
        summaries.append(
            strike_summary(
                head,
                {
                    **head.get("melee_approach", {}),
                    "actor_id": head["actor_id"],
                    "attack_resolved": False,
                    "resolved": False,
                    "hesitated": True,
                    "reason": hesitation_reason,
                },
            )
        )
        finish_held(state)
    else:
        for packet in list(reaction_packets):
            if packet["ability_id"] == reaction_spend.SIDESTEP:
                spend = state.reactions_available[packet["actor_id"]]
                if "destination" in spend:
                    head["sidestep"] = {"packet": packet, "destination": spend["destination"]}
                    reaction_packets.remove(packet)
        reaction_packets = combat_reaction_disruption.defer(state, head, reaction_packets, None, attack_action)
        turned_miss = hit_before_close and not head["roll"]["attack_result"]["hit"]
        if turned_miss or any(packet["ability_id"] in reaction_spend.COUNTERS for packet in reaction_packets):
            head.setdefault("pending_reaction_packets", []).extend(reaction_packets)
            reaction_packets = []
        summaries.extend(reaction_packets)
        if turned_miss and combat_hold_windows.offer_reaction_miss(state, head):
            return reaction_packets, True

    return reaction_packets, False
