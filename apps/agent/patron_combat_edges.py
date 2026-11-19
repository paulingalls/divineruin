"""Combat state changes prepared by actively spent patron gifts."""

from copy import deepcopy

from livekit.agents.llm import ToolError

import ability_persistence
from archetypes import get_archetype_chassis
from combat_participant import CombatParticipant
from combat_state import CombatState
from conditions import apply_condition, has_condition

BATTLE_CRY = "kaelen_battle_cry_of_the_ironhand"
JUDGMENT = "kaelen_kaelens_judgment"
WORTHY_FOE = "worthy_foe"


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


ACTIVE_GIFTS = {BATTLE_CRY: battle_cry, JUDGMENT: kaelens_judgment}
