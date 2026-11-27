"""Post-commit combat settlement and gameplay handoff."""

import json
import logging
from collections.abc import Callable

from livekit.agents.llm import ChatContext
from livekit.agents.voice import Agent

import first_episode
import quest_progress
from combat_down import sync_companion_consciousness
from region_types import REGION_CITY
from session_data import CombatState, SessionData

logger = logging.getLogger("divineruin.tools")


def finish(
    session: SessionData,
    cs: CombatState,
    outcome: str,
    end_data: dict,
    build_handoff_agent: Callable[[SessionData, str, ChatContext], Agent | None],
) -> tuple:
    """Clear session state and build the gameplay handoff after combat commits."""
    xp_total = end_data["xp_total"]
    xp_granted = end_data["xp_granted"]
    defeated_enemies = end_data["defeated_enemies"]

    # M18 story-003: reset EVERY member's per-encounter weapon flags (mirror combat_init).
    for member in session.party.members:
        member.weapon_used = False
        member.weapon_crit_vs_heavy = False
        member.draethar_inner_fire_used = False
        member.unbound_raw_channeling_used = False
    sync_companion_consciousness(session, cs)
    session.combat_state = None

    # Post-commit sync of the location-ward mirror: only when the dying encounter ward changed
    # wardedness (the in-tx half resolved and emitted the covering location scope). Deferred here so
    # a rolled-back phase leaves session.location_ward untouched, matching the combat_state contract.
    if end_data.get("ward_light_synced"):
        session.location_ward = end_data["resolved_location_ward"]

    # When the primary died (any outcome — the dead-life collector or the standing-primary defeat
    # fallback set death_context), it was revived AT its anchor (players.data.location_id = anchor).
    # Sync the live session so the post-death handoff agent is built at the anchor, not the stale
    # death site — the character returns at the anchor. death_context is None on a clean survival.
    death_context = end_data.get("death_context")
    if death_context is not None:
        session.location_id = death_context["anchor"]

    session.record_event(f"Combat ended: {outcome}")
    # Folding award_xp onto the combat-exit Resolve (story-003) took its `record_event` with it,
    # so the DM's warm `[Recent: ...]` layer and the session-summary transcript fallback lost every
    # XP grant (debt fb14dced76f6). The speaker's own share, matching session_xp_earned below.
    if xp_granted > 0:
        session.record_event(f"Awarded {xp_granted} XP: combat at {cs.location_id}")
    if defeated_enemies:
        session.record_companion_memory(f"Fought {', '.join(defeated_enemies)} at {cs.location_id}: {outcome}")

    episode_facts = first_episode.finish(session, end_data.get("episode"))

    session.session_xp_earned += end_data["summary_xp_granted"]
    for pid, share in end_data["xp_by_player"].items():
        session.record_player_metric(pid, "xp_earned", share)
    for pid, name in end_data["item_recipients"]:
        session.record_item_found(pid, name)

    loot = end_data.get("primary_loot", [])
    currency_gold = end_data.get("primary_currency_gold", 0)
    response = {
        "first_episode": episode_facts,
        "architect": end_data.get("architect"),
        "choir": end_data.get("choir"),
        "still": end_data.get("still"),
        "outcome": outcome,
        "xp_total": xp_total,
        # The XP is already GRANTED (M28 story-001) — there is no follow-up award call to cue.
        # The DM narrates the level-up beats from this response, not from the event bus:
        # milestone_grants voices each L10/15/20 auto-grant, and specialization_fork cues the L5
        # choice the generic select verb resolves.
        "xp_granted": xp_granted,
        "attribute_increases": end_data["attribute_increases"],
        "elective_choices": end_data["elective_choices"],
        "milestone_grants": end_data["milestone_grants"],
        "specialization_fork": end_data["specialization_fork"],
        "defeated_enemies": defeated_enemies,
        "weapon_durability": end_data["weapon_durability"],
        "loot": loot,
        "currency_gold": currency_gold,
    }
    if ended_forms := end_data.get("wild_shape_ended"):
        response["wild_shape_ended"] = ended_forms
    if judgment_rewards := end_data.get("judgment_rewards"):
        response["judgment_rewards"] = judgment_rewards
    logger.info(
        "end_combat result: %s, xp=%d granted (encounter total %d), loot=%d item(s), currency=%.1fgp",
        outcome,
        xp_granted,
        xp_total,
        len(loot),
        currency_gold,
    )

    summary_parts = [f"Combat resolved: {outcome}."]
    if residue := end_data.get("lost_scout_residue"):
        response["lost_scout_residue"] = residue
        summary_parts.append(residue)
    if episode_facts:
        summary_parts.append(episode_facts["aftermath"])
    if cue := (end_data.get("architect") or {}).get("cue"):
        summary_parts.append(cue)
    for encounter in ("choir", "still"):
        if end_data.get(encounter):
            summary_parts.append(end_data[encounter]["cue"])
    # The player's OWN share, not the encounter total — in a party the two differ, and narrating
    # the total would promise XP nobody received.
    if xp_granted > 0:
        summary_parts.append(f"XP earned: {xp_granted}.")
    if defeated_enemies:
        summary_parts.append(f"Defeated: {', '.join(defeated_enemies)}.")
    # Surface the haul so the DM can voice it (loot is a headline beat). Quantities collapse per
    # item id so a "2x Cured Hide" reads naturally rather than as two lines.
    if loot:
        qty_by_item: dict[str, int] = {}
        for drop in loot:
            qty_by_item[drop["item_id"]] = qty_by_item.get(drop["item_id"], 0) + drop["quantity"]
        summary_parts.append("Loot: " + ", ".join(f"{q}x {item}" for item, q in qty_by_item.items()) + ".")
    if currency_gold > 0:
        summary_parts.append(f"Currency: {currency_gold:.1f} gold.")

    quest_progress.finish_combat_quests(session, end_data, response, summary_parts)
    summary_ctx = ChatContext()
    summary_ctx.add_message(role="system", content=" ".join(summary_parts))

    agent_type = session.pre_combat_agent_type or REGION_CITY
    session.pre_combat_agent_type = None
    return build_handoff_agent(session, agent_type, summary_ctx), json.dumps(response)
