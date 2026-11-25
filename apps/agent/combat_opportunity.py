"""Interrupt a held melee approach at the boundary of a warrior's weapon reach."""

import math

import combat_fate
import combat_melee_approach as melee
import combat_reaction_effect
import reaction_gate
import reaction_spend
from combat_fate_rolls import PacketRolls
from combat_movement_cost import AXES, movement_cost
from combat_phase import ResolutionPacket
from combat_spatial import distance, position, require_spatial
from combat_spatial_declarations import in_pit
from condition_restrictions import cannot_act
from declarations import Declaration, DeclarationType
from encounter_actions import action_kind
from reaction_windows import ENEMY_MOVE, MOVEMENT, open_window_for
from session_data import CombatParticipant, CombatState, SessionData

STRIKE = "warrior_opportunity_strike"


def reach_exits(origin: dict, endpoint: dict, reaches: dict[str, tuple[dict, float]]) -> list[dict]:
    """Group departures along a straight segment by the fraction where each reach ends."""
    delta = {axis: endpoint[axis] - origin[axis] for axis in AXES}
    length_sq = sum(step**2 for step in delta.values())
    crossings = []
    for reactor_id, (center, reach) in reaches.items():
        if distance(origin, center) > reach or distance(endpoint, center) <= reach:
            continue
        offset = {axis: origin[axis] - center[axis] for axis in AXES}
        projection = sum(offset[axis] * delta[axis] for axis in AXES)
        depth = reach**2 - sum(step**2 for step in offset.values())
        discriminant = max(0.0, projection**2 + length_sq * depth)
        fraction = (math.sqrt(discriminant) - projection) / length_sq
        crossings.append((fraction, reactor_id))
    exits: list[dict] = []
    for fraction, reactor_id in sorted(crossings):
        if not exits or not math.isclose(fraction, exits[-1]["fraction"], rel_tol=1e-12, abs_tol=1e-12):
            exits.append(
                {
                    "fraction": fraction,
                    "point": {axis: origin[axis] + fraction * delta[axis] for axis in AXES},
                    "reactors": [],
                }
            )
        exits[-1]["reactors"].append(reactor_id)
    return exits


def movement_candidate(
    state: CombatState, head: dict, action: dict, exit_point: dict, weapons: dict, ordinal: int
) -> dict:
    candidate = open_window_for(
        round_number=state.round_number,
        seq=head["seq"],
        stage=MOVEMENT,
        actor_id=head["actor_id"],
        target_id=head["declaration"]["target_id"],
        action_kind=action_kind(action),
        triggers=(ENEMY_MOVE,),
        movement_ordinal=ordinal,
    )
    candidate["reactors"] = {actor_id: weapons[actor_id] for actor_id in sorted(exit_point["reactors"])}
    return candidate


async def _find_exits(state: CombatState, mover: CombatParticipant, route: dict, deps: dict) -> list[dict]:
    if (mover.flyby and route["mode"] == "flying") or in_pit(state, mover.id):
        return []
    spatial = require_spatial(state)
    origin = position(spatial, mover.id)
    endpoint = route["endpoint"]
    reaches, weapons = {}, {}
    for reactor in state.participants:
        if (
            reactor.type != "player"
            or STRIKE not in reactor.reaction_ids
            or reactor.is_fallen
            or cannot_act(reactor.conditions)
            or reaction_spend.is_spent(state.reactions_available.get(reactor.id))
        ):
            continue
        center = position(spatial, reactor.id)
        separation = distance(origin, center)
        if not any(
            melee.is_melee(action) and separation <= melee.melee_reach(action) for action in reactor.action_pool
        ):
            continue
        player = await deps["queries"].get_player(reactor.id, conn=deps["conn"])
        if player is None:
            raise ValueError(f"Missing player for reactor {reactor.id!r}")
        action = player.get("equipment", {}).get("main_hand")
        if isinstance(action, dict) and melee.is_melee(action):
            reach = melee.melee_reach(action)
            reaches[reactor.id] = (center, reach)
            weapons[reactor.id] = {"action": action, "reach": reach}
    return [
        {
            "point": group["point"],
            "reactors": group["reactors"],
            "weapons": {actor_id: weapons[actor_id] for actor_id in group["reactors"]},
        }
        for group in reach_exits(origin, endpoint, reaches)
    ]


async def _strike(
    session: SessionData,
    state: CombatState,
    mover: CombatParticipant,
    window: dict,
    spend: dict,
    deps: dict,
    fate_rolls,
) -> dict:
    warrior = state.get_participant(spend["actor_id"])
    assert warrior is not None
    weapon = window["reactors"][warrior.id]["action"]
    action = {key: value for key, value in weapon.items() if key != "durability_rider"}
    packet = ResolutionPacket(warrior.id, Declaration(DeclarationType.ATTACK, action["name"], target_id=mover.id), 0)
    progress = None
    if fate_rolls is not None and (session.fate_lock.locked() or "steps" in spend):
        progress = PacketRolls(fate_rolls, spend.setdefault("steps", {}), deps["queries"], deps["conn"])
    receipt = await combat_fate.continue_attack(
        session,
        state,
        packet,
        warrior,
        mover,
        [action],
        sum(p.type == "enemy" and not p.is_fallen for p in state.participants),
        not state.first_attack_resolved,
        attack_cursor=spend.setdefault("attack", {}),
        progress=progress,
        **{key: deps[key] for key in ("queries", "mutations", "resolver", "concentration_break_mod", "conn", "sink")},
    )
    return {**receipt, "reaction": STRIKE, "window_id": window["id"], "target_id": mover.id}


async def prepare_held(
    session: SessionData,
    state: CombatState,
    head: dict,
    action: dict | None,
    summaries: list[dict],
    *,
    packet_deps: dict,
    fate_rolls,
) -> dict | None:
    """Return completed approach facts, or None while a window or its strike is pending."""
    if previous := head.get("melee_approach"):
        return previous
    mover = state.get_participant(head["actor_id"])
    assert mover is not None
    target = state.get_participant(head["declaration"].get("target_id"))
    route = head.get("opportunity_approach")
    if route is None:
        if action is None or target is None or not melee.is_melee(action):
            return {}
        budget = {"remaining": head["movement_remaining"]} if "movement_remaining" in head else {}
        facts, route = melee.plan(state, mover, target, action, budget)
        if route is None:
            melee.cache_held(state, head, facts, budget)
            return facts
        exits = await _find_exits(state, mover, route, packet_deps)
        route.update(facts=facts, budget=budget, exits=exits, next_exit=0)
        head["opportunity_approach"] = route

    if window := route.get("window"):
        if "spends" not in route:
            route["spends"] = sorted(
                combat_reaction_effect.bound_spends(state, head, MOVEMENT, window_id=window["id"]),
                key=lambda spend: spend["actor_id"],
            )
        for spend in list(route["spends"]):
            if mover.is_fallen:
                break
            receipt = await _strike(session, state, mover, window, spend, packet_deps, fate_rolls)
            if fate_rolls is not None and fate_rolls.pending is not None:
                return None
            summaries.append(receipt)
            route["spends"].pop(0)
        del route["window"], route["spends"]

    facts, budget = route["facts"], route["budget"]
    assert action is not None
    while route["next_exit"] < len(route["exits"]):
        ordinal = route["next_exit"]
        exit_point = route["exits"][ordinal]
        route["next_exit"] += 1
        facts = melee.apply_leg(state, mover, facts, exit_point["point"], route["mode"], budget)
        if not facts["resolved"]:
            break
        candidate = movement_candidate(state, head, action, exit_point, exit_point["weapons"], ordinal)
        if not reaction_gate.offers_for_window(state, candidate):
            continue
        route.update(window=candidate, facts=facts)
        state.open_window = candidate
        summaries.append({**facts, "attack_resolved": False, "attack_pending": True})
        return None
    if facts["resolved"]:
        if facts["closed_distance"]:
            # Splitting the integral can round the last leg above the remaining allowance.
            spent = movement_cost(require_spatial(state), mover.id, facts["destination"], route["endpoint"])
            remaining = budget["remaining"]
            if spent > remaining and math.isclose(spent, remaining, rel_tol=1e-12, abs_tol=1e-12):
                budget["remaining"] = spent
        facts = melee.apply_leg(state, mover, facts, route["endpoint"], route["mode"], budget)
        if facts["resolved"]:
            melee.finish(facts, route["target"], route["reach"])
    melee.cache_held(state, head, facts, budget)
    del head["opportunity_approach"]
    return facts
