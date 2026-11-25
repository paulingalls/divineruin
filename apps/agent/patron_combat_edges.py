"""Combat state changes prepared by actively spent patron gifts."""

from copy import deepcopy
from typing import Literal, get_args

import asyncpg
from livekit.agents.llm import ToolError

import ability_persistence
import combat_spatial
import temp_hp
import thyra_thornwall
from archetypes import get_archetype_chassis
from combat_down import is_terminally_down
from combat_participant import CombatParticipant
from combat_spatial_declarations import is_move
from combat_state import CombatState
from condition_catalog import INCORPOREAL, MARK_OF_JUSTICE
from condition_consume import consume_beneficial_conditions
from conditions import apply_condition, has_condition, hollowed_stage
from declarations import resolve_declaration
from rules_engine import attribute_modifier

VEILSTEP = "syrath_veilstep"
THRESHOLD_WALK = "mortaen_threshold_walk"
WILDMOTHERS_WRATH = "thyra_wildmothers_wrath"
SCALES_VERDICT = "valdris_the_scales_verdict"
COMMUNITY_SHIELD = "aelora_community_shield"
PARTIAL_ROUND_GIFTS = {
    thyra_thornwall.GIFT: "Thornwall",
    VEILSTEP: "Veilstep",
    THRESHOLD_WALK: "Threshold Walk",
    WILDMOTHERS_WRATH: "Wildmother's Wrath",
    COMMUNITY_SHIELD: "Community Shield",
    SCALES_VERDICT: "The Scale's Verdict",
    "zhael_unravel_fate": "Unravel Fate",
}
VEILSTEP_RANGE_FT = 60
BATTLE_CRY = "kaelen_battle_cry_of_the_ironhand"
JUDGMENT = "kaelen_kaelens_judgment"
SurgeCondition = Literal["poisoned"] | Literal["blinded"] | Literal["frightened"] | Literal["hollowed"]
SURGE_CONDITIONS = tuple(arg for literal in get_args(SurgeCondition) for arg in get_args(literal))
RESTORATION_SURGE = "orenthel_restoration_surge"
WORTHY_FOE = "worthy_foe"
MARK_OF_JUSTICE_GIFT = "valdris_mark_of_justice"


def battle_cry(state: CombatState | None, actor: str, *, target_id: str | None) -> tuple[CombatState, dict]:
    if state is None:
        raise ToolError("Battle Cry can only be used in combat.")
    participant = state.get_participant(actor)
    if participant is None or participant.type != "player":
        raise ToolError("Battle Cry requires the acting player to be a player participant.")

    updated = deepcopy(state)
    allies = []
    for ally in updated.participants:
        if ally.is_ally and not ally.is_dead:
            ally.conditions = apply_condition(ally.conditions, "battle_cry", duration=2, source=actor)
            allies.append({"id": ally.id, "name": ally.name})
    return updated, {"allies": allies}


def kaelens_judgment(state: CombatState | None, actor: str, *, target_id: str | None) -> tuple[CombatState, dict]:
    if state is None:
        raise ToolError("Kaelen's Judgment can only be used in combat.")
    participant = state.get_participant(actor)
    if participant is None or participant.type != "player":
        raise ToolError("Kaelen's Judgment requires the acting player to be a player participant.")

    updated = deepcopy(state)
    target = updated.get_participant(target_id) if target_id is not None else None
    if target is None or target.is_ally or target.hp_current <= 0 or target.is_dead or target.is_fallen:
        raise ToolError("Kaelen's Judgment requires a living enemy in this encounter.")
    if has_condition(target.conditions, WORTHY_FOE):
        raise ToolError("That enemy is already a Worthy Foe.")
    target.conditions = apply_condition(target.conditions, WORTHY_FOE, source=actor)
    return updated, {"worthy_foe": {"id": target.id, "name": target.name}}


def mark_of_justice(state: CombatState | None, actor: str, *, target_id: str | None) -> tuple[CombatState, dict]:
    if state is None:
        raise ToolError("Mark of Justice can only be used in combat.")
    participant = state.get_participant(actor)
    if participant is None or participant.type != "player":
        raise ToolError("Mark of Justice requires the acting player to be a player participant.")

    updated = deepcopy(state)
    target = updated.get_participant(target_id) if target_id is not None else None
    if target is None or target.is_ally or target.hp_current <= 0 or target.is_dead or target.is_fallen:
        raise ToolError("Mark of Justice requires a living enemy in this encounter.")
    target.conditions = apply_condition(target.conditions, MARK_OF_JUSTICE, source=actor)
    return updated, {"marked_target": {"id": target.id, "name": target.name}}


def require_complete_round(state: CombatState | None, ability_id: str) -> None:
    if state is None:
        return
    if state.ally_continuation is not None or state.held_actions:
        raise ToolError(f"Finish the partially resolved round before using {PARTIAL_ROUND_GIFTS[ability_id]}.")


def threshold_walk(state: CombatState | None, actor: str, *, target_id: str | None) -> tuple[CombatState | None, dict]:
    cue = {
        "dm_cue": "Narrate Threshold Walk. The follower slips across Mortaen's threshold, beyond the reach of steel."
    }
    if state is None:
        return None, cue
    require_complete_round(state, THRESHOLD_WALK)
    updated = deepcopy(state)
    follower = updated.get_participant(actor)
    if follower is None or follower.type != "player":
        raise ToolError("Threshold Walk requires the acting player to be a player participant.")
    if follower.is_fallen or follower.is_dead or follower.hp_current <= 0:
        raise ToolError("A fallen or dead follower cannot use Threshold Walk.")
    follower.conditions = apply_condition(follower.conditions, INCORPOREAL, duration=2, source=actor)
    return updated, cue


def veilstep(state: CombatState | None, actor: str, *, destination: dict | None) -> tuple[CombatState | None, dict]:
    cue = "Narrate the follower slipping into one shadow and stepping out of another."
    if state is None:
        return None, {"dm_cue": cue}
    follower = state.get_participant(actor)
    if follower is None or follower.type != "player":
        raise ToolError("Veilstep requires the acting player to be a player participant.")
    if follower.is_fallen or follower.is_dead:
        raise ToolError("A fallen or dead follower cannot Veilstep.")
    require_complete_round(state, VEILSTEP)
    if state.spatial is None:
        return None, {"dm_cue": cue}
    if destination is None:
        raise ToolError("Veilstep requires a destination point in feet (x, y, z).")

    try:
        origin = combat_spatial.position(state.spatial, actor)
        travelled = combat_spatial.distance(origin, destination)
        if travelled > VEILSTEP_RANGE_FT:
            raise ToolError(f"Veilstep reaches up to {VEILSTEP_RANGE_FT} feet.")
        updated = deepcopy(state)
        placed = combat_spatial.place(updated, actor, destination)
    except ValueError as exc:
        raise ToolError(f"Cannot place Veilstep: {exc}") from exc

    queued = updated.pending_declarations.get(actor)
    if updated.beat == "resolution" and queued is not None and is_move(resolve_declaration(queued)):
        del updated.pending_declarations[actor]
        cue += " The queued move is removed. Ask for a new move from the new position at the next declaration beat."
    return updated, {"position": placed, "dm_cue": cue}


def _shield_participant(state: CombatState, player_id: str, role: str) -> CombatParticipant:
    participant = state.get_participant(player_id)
    if participant is None or participant.type != "player":
        raise ToolError(f"Community Shield requires the {role} to be a player in this encounter.")
    if participant.is_fallen or is_terminally_down(participant):
        raise ToolError(f"Community Shield requires the {role} to be standing.")
    return participant


async def community_shield(
    state: CombatState | None, actor: str, target: str, giver: dict, ally: dict, *, conn: asyncpg.Connection
) -> tuple[CombatState | None, dict]:
    require_complete_round(state, COMMUNITY_SHIELD)
    updated = deepcopy(state)
    recipient = None
    if updated is not None:
        _shield_participant(updated, actor, "follower")
        recipient = _shield_participant(updated, target, "target")

    amount = max(1, giver["level"] + attribute_modifier(giver["attributes"].get("charisma", 10)))
    if amount <= temp_hp.from_player(ally):
        raise ToolError("Community Shield would not increase the target's temporary HP.")
    _, pool = await temp_hp.grant(target, ally, amount, participant=recipient, conn=conn)
    follower_name, target_name = giver["name"], ally["name"]
    return updated, {
        "follower_id": actor,
        "follower_name": follower_name,
        "target_id": target,
        "target_name": target_name,
        "granted": amount,
        "temp_hp": pool,
        "dm_cue": f"Narrate that {follower_name}'s Community Shield gives {target_name} {amount} temporary HP.",
    }


async def restoration_surge(
    state: CombatState | None, actor: str, target: str, condition: str | None, player: dict, *, conn
) -> tuple[CombatState | None, dict]:
    if condition is None:
        raise ToolError("Restoration Surge requires a condition selector.")
    if condition not in SURGE_CONDITIONS:
        raise ToolError(f"Restoration Surge cannot remove {condition!r}.")

    stored = player.get("conditions") or []
    current = stored
    if state is not None:
        follower = state.get_participant(actor)
        recipient = state.get_participant(target)
        if follower is None:
            raise ToolError("Restoration Surge requires the acting player to be a player participant.")
        if recipient is None:
            raise ToolError("Restoration Surge requires its target to be a player participant.")
        current = recipient.conditions

    if not has_condition(current, condition):
        raise ToolError(f"The target does not have {condition!r}.")
    # Combat end can restore persisted Hollowed, so protect a higher stage in either store.
    if condition == "hollowed" and (hollowed_stage(current) != 1 or hollowed_stage(stored) >= 2):
        raise ToolError("Restoration Surge can only remove stage 1 Hollowed.")

    updated = await consume_beneficial_conditions(target, (condition,), conn=conn, combat_state=state)
    return updated, {"target_id": target, "condition_removed": condition}


async def reward_worthy_foe(state: CombatState, target: CombatParticipant, *, queries, conn) -> None:
    mark = next((c for c in target.conditions if c["type"] == WORTHY_FOE), None)
    if mark is None:
        return
    source = mark["source"]
    if not isinstance(source, str) or not source:
        raise ValueError("Worthy Foe is missing its marking follower")
    if any(r["player_id"] == source and r["target_id"] == target.id for r in state.judgment_rewards):
        return
    if conn is None:
        raise ValueError("Worthy Foe payout requires a combat transaction")

    player = await queries.get_player(source, for_update=True, conn=conn)
    if player is None:
        raise ValueError(f"Worthy Foe follower {source} is missing")
    restored = 0
    if "stamina" in player or get_archetype_chassis(player["class"]).resource.stamina_formula is not None:
        stamina = player.get("stamina")
        if not isinstance(stamina, dict):
            raise ValueError(f"Worthy Foe follower {source} has no valid Stamina pool")
        current, maximum = stamina.get("current"), stamina.get("max")
        if type(current) is not int or type(maximum) is not int or not 0 <= current <= maximum:
            raise ValueError(f"Worthy Foe follower {source} has an invalid Stamina pool")
        restored = min(maximum - current, maximum // 2)
        if restored:
            await ability_persistence.update_player_resources(source, stamina=current + restored, conn=conn)
    state.judgment_rewards.append(
        {"ability_id": JUDGMENT, "player_id": source, "target_id": target.id, "stamina_restored": restored}
    )


DESTINATION_GIFTS = {VEILSTEP, thyra_thornwall.GIFT}

ACTIVE_GIFTS = {
    thyra_thornwall.GIFT: thyra_thornwall.thornwall,
    BATTLE_CRY: battle_cry,
    JUDGMENT: kaelens_judgment,
    MARK_OF_JUSTICE_GIFT: mark_of_justice,
    VEILSTEP: veilstep,
    THRESHOLD_WALK: threshold_walk,
}
