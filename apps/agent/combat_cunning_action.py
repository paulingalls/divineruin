"""Cunning Action borrows the weapon attack's movement and continuation."""

import check_resolution
import combat_martial
import combat_spatial
import concealment
import condition_voice_rules
import conditions
from combat_ability_gate import CUNNING_ACTION, declared_ability
from combat_fate_rolls import PacketRolls
from combat_participant import CombatParticipant
from combat_terrain import skill_natural_terrain
from declarations import Declaration, resolve_declaration
from patron_location import check_first_stay
from resource_costs import gate_pool
from rules_engine import attribute_modifier
from session_data import CombatState, SessionData


async def preflight(state: CombatState, *, queries) -> None:
    for actor_id, raw in state.pending_declarations.items():
        if combat_martial.attack_ability(resolve_declaration(raw)) != CUNNING_ACTION:
            continue
        player = await queries.get_player(actor_id)
        if player is None:
            raise ValueError(f"Unknown player: {actor_id}")
        resolved = declared_ability(CUNNING_ACTION)
        assert resolved is not None
        ability, _ = resolved
        gate_pool(player, "stamina", ability.cost.stamina, label=ability.name)


def movement_allowance(state: CombatState, actor: CombatParticipant, decl: Declaration) -> dict:
    if combat_martial.attack_ability(decl) == CUNNING_ACTION and decl.rider == "dash":
        return {"remaining": 2 * combat_spatial.require_spatial(state)["speeds"][actor.id]}
    return {}


async def pay(actor: CombatParticipant, *, queries, conn) -> None:
    resolved = declared_ability(CUNNING_ACTION)
    assert resolved is not None
    await combat_martial.pay(actor.id, resolved, queries=queries, conn=conn)


async def hide(
    session: SessionData,
    state: CombatState,
    actor: CombatParticipant,
    *,
    queries,
    conn,
    progress: PacketRolls | None,
) -> dict | None:
    player = await queries.get_player(actor.id, conn=conn, for_update=True)
    if player is None:
        raise ValueError(f"Unknown player: {actor.id}")
    dc = 10 + max(
        (
            attribute_modifier(foe.attributes.get("wisdom", 10))
            for foe in state.participants
            if not foe.is_ally and not foe.is_structure and foe.hp_current > 0 and not foe.is_fallen
        ),
        default=0,
    )

    async def roll() -> check_resolution.SkillCheckResult:
        return check_resolution.resolve_skill_check_dc(
            condition_voice_rules.roll_data(player, state, actor.id),
            "stealth",
            dc,
            ally_present=session.allies_present_for(actor.id),
            natural_terrain=await skill_natural_terrain(session, player, "stealth", combat_state=state),
            hearing_only=False,
            first_stay=await check_first_stay(player, session, "stealth", player_id=actor.id, conn=conn),
        )

    result = await progress.skill(session, actor.id, roll) if progress is not None else await roll()
    if result is None:
        return None
    actor.conditions = conditions.remove_conditions(actor.conditions, result.consumed_conditions)
    hidden = await concealment.transition(
        actor.id, player, result.success, ended_by=None if result.success else "failed_stealth", conn=conn
    )
    return {**hidden, "dc": result.dc, "roll": result.roll}
