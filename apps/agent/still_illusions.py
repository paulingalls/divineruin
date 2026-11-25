"""Free round-wrap illusions and their public Investigation check."""

import json
from copy import deepcopy

from livekit.agents.llm import ToolError

import check_resolution
import combat_recharge
import condition_voice_rules
import conditions
from combat_terrain import skill_natural_terrain
from patron_location import check_first_stay
from still_encounter import in_zone

ID_PREFIX = "still_illusion_"


def generate(state):
    record = state.still_encounter
    if record is None:
        return
    owner = state.get_participant(record["owner_id"])
    if owner.still_dormant or owner.is_dead:
        return
    action = next((action for action in owner.action_pool if action.get("kind") == "illusion"), None)
    if action is None:
        return
    combat_recharge.initialize(owner, state.round_number)
    entry = owner.action_ledger[combat_recharge.action_key(action)]
    if entry["remaining"] == 0:
        return
    eligible = [
        actor_id
        for actor_id in state.initiative_order
        if (actor := state.get_participant(actor_id)).is_ally
        and not actor.is_dead
        and not actor.is_fallen
        and in_zone(state, owner, actor_id)
    ]
    if not eligible:
        record["illusion"] = None
        return
    target_id = eligible[state.round_number % len(eligible)]
    illusion_id = f"{ID_PREFIX}{state.round_number}"
    entry["remaining"] -= 1
    entry["round"] = state.round_number
    record["illusion"] = {
        "id": illusion_id,
        "target_id": target_id,
        "round": state.round_number,
        "seen_through": False,
        "narration": f"Voice a familiar sound or treasured memory for {state.get_participant(target_id).name} based on what they have shared.",
        "check": {"kind": "discover", "skill": action["check_skill"], "target": illusion_id, "hearing_only": False},
        "dc": action["dc"],
    }


def validate(state, illusion):
    if illusion is None:
        return
    if (
        not isinstance(illusion, dict)
        or type(illusion.get("round")) is not int
        or not 1 <= illusion["round"] <= state.round_number
        or illusion.get("id") != f"{ID_PREFIX}{illusion['round']}"
        or not isinstance(illusion.get("target_id"), str)
        or (target := state.get_participant(illusion["target_id"])) is None
        or not target.is_ally
        or type(illusion.get("seen_through")) is not bool
        or not isinstance(illusion.get("narration"), str)
        or not illusion["narration"]
        or type(illusion.get("dc")) is not int
        or illusion["dc"] <= 0
        or illusion.get("check")
        != {"kind": "discover", "skill": "investigation", "target": illusion["id"], "hearing_only": False}
    ):
        raise ValueError("Invalid Still illusion")


async def investigate(session, skill, target, *, queries, mutations, conditions_mutations, db_mod, publish_roll):
    state = session.combat_state
    illusion = state.still_encounter.get("illusion")
    if illusion is None or target != illusion["id"]:
        raise ToolError("That Still illusion is no longer present.")
    if skill != illusion["check"]["skill"]:
        raise ToolError("Use Investigation to see through the Still's illusion.")
    target_id = illusion["target_id"]
    actor = state.get_participant(target_id)
    player_id = session.acting_player_id
    companion = actor.type == "companion" and player_id == session.primary_player_id
    if player_id != target_id and not companion:
        raise ToolError("Only the creature experiencing the Still illusion can investigate it.")
    if illusion["seen_through"]:
        return json.dumps({"target": target, "dc": illusion["dc"], "seen_through": True})

    working = deepcopy(state)
    async with db_mod.transaction() as conn:
        if companion:
            player = {"attributes": actor.attributes, "level": actor.level}
        else:
            player = await queries.get_player(player_id, conn=conn, for_update=True)
            if player is None:
                raise ToolError(f"Player {player_id!r} not found.")
        result = check_resolution.resolve_skill_check_dc(
            condition_voice_rules.roll_data(player, working, target_id),
            skill,
            illusion["dc"],
            ally_present=session.allies_present_for(player_id),
            natural_terrain=await skill_natural_terrain(session, player, skill, combat_state=working),
            hearing_only=False,
            first_stay=not companion and await check_first_stay(player, session, skill, player_id=player_id, conn=conn),
        )
        working.still_encounter["illusion"]["seen_through"] = result.success
        if result.consumed_conditions and not companion:
            await conditions_mutations.remove_player_conditions(player_id, result.consumed_conditions, conn=conn)
        actor = working.get_participant(target_id)
        actor.conditions = conditions.remove_conditions(actor.conditions, result.consumed_conditions)
        await mutations.save_combat_state(working.combat_id, working.to_dict(), conn=conn)
    session.combat_state = working
    if not result.auto_fail:
        await publish_roll(session, result)
    return json.dumps(
        {
            "target": target,
            "skill": result.skill,
            "roll": result.roll,
            "modifier": result.modifier,
            "total": result.total,
            "dc": result.dc,
            "seen_through": result.success,
        }
    )
