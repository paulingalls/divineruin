"""Pause a player's declared route while a hostile reach-exit attack resolves."""

import math
from dataclasses import dataclass

import combat_melee_approach as melee
import combat_spatial_declarations as moves
import dice
import reaction_spend
from combat_action_availability import available_actions
from combat_fate_rolls import PhaseRolls
from combat_movement_cost import movement_cost
from combat_spatial import distance, position, require_spatial
from combat_structures import blocking_wall
from condition_restrictions import cannot_act, effective_speed
from declarations import Declaration
from session_data import CombatParticipant, CombatState, SessionData


def _melee_actions(state: CombatState, actor: CombatParticipant) -> list[dict]:
    if (
        actor.type != "enemy"
        or actor.is_fallen
        or actor.is_dead
        or actor.hp_current <= 0
        or cannot_act(actor.conditions)
        or reaction_spend.is_spent(state.reactions_available.get(actor.id))
    ):
        return []
    return [action for action in available_actions(actor) if melee.is_melee(action)]


def _damage_average(action: dict) -> float:
    return dice.average(action.get("damage") or "0") + dice.average(action.get("bonus_damage", {}).get("dice", "0"))


def _exits(state: CombatState, mover: CombatParticipant, endpoint: dict) -> list[dict]:
    from combat_opportunity import reach_exits

    spatial = require_spatial(state)
    reaches = {}
    for actor in state.participants:
        actions = _melee_actions(state, actor)
        if actions:
            reaches[actor.id] = (position(spatial, actor.id), max(melee.melee_reach(action) for action in actions))
    exits = reach_exits(position(spatial, mover.id), endpoint, reaches)
    for group in exits:
        group["reactors"].sort()
    return exits


@dataclass
class PlayerMovement:
    session: SessionData
    state: CombatState
    steps: dict
    packet_deps: dict
    fate_rolls: PhaseRolls
    summaries: list[dict]

    @property
    def route(self) -> dict | None:
        return self.steps.get("movement_route")

    async def move(self, actor: CombatParticipant, declaration: Declaration) -> dict | None:
        if self.route is None:
            if moves.ineligible(actor):
                return moves.apply_move(self.state, actor, declaration)
            try:
                endpoint, _, _, _ = moves.movement_geometry(self.state, actor.id, declaration)
            except moves.MovementRefused as error:
                return {"actor_id": actor.id, "resolved": False, "reason": str(error)}
            spatial = require_spatial(self.state)
            if not self._start(
                actor,
                {"endpoint": endpoint, "mode": declaration.movement_mode},
                {
                    "actor_id": actor.id,
                    "resolved": True,
                    "declaration_type": "maneuver",
                    "moved_ft": 0,
                    "destination": position(spatial, actor.id),
                },
                {"remaining": effective_speed(spatial["speeds"][actor.id], actor.conditions)},
            ):
                return moves.apply_move(self.state, actor, declaration)
        route = await self._finish(actor)
        if route is None:
            return None
        return {
            key: value for key, value in route["facts"].items() if key not in ("attack_resolved", "closed_distance")
        }

    async def approach(
        self, actor: CombatParticipant, target: CombatParticipant, action: dict, budget: dict
    ) -> dict | None:
        if self.route is None:
            facts, route = melee.plan(self.state, actor, target, action, budget)
            if route is None:
                return facts
            if not self._start(actor, route, facts, budget):
                facts = melee.apply_leg(self.state, actor, facts, route["endpoint"], route["mode"], budget)
                return melee.finish(facts, route["target"], route["reach"]) if facts["resolved"] else facts
            declaration = melee.leg_declaration(actor.id, route["endpoint"], route["mode"])
            try:
                moves.movement_geometry(self.state, actor.id, declaration, allowance=budget["remaining"])
            except moves.MovementRefused as error:
                del self.steps["movement_route"]
                return {**facts, "resolved": False, "attack_resolved": False, "reason": str(error)}
        route = await self._finish(actor)
        if route is None:
            return None
        budget.update(route["budget"])
        facts = route["facts"]
        return melee.finish(facts, route["target"], route["reach"]) if facts["resolved"] else facts

    def _start(self, actor: CombatParticipant, route: dict, facts: dict, budget: dict) -> bool:
        if budget.get("disengage") or moves.in_pit(self.state, actor.id):
            return False
        exits = _exits(self.state, actor, route["endpoint"])
        if not exits:
            return False
        self.steps["movement_route"] = {
            **route,
            "actor_id": actor.id,
            "facts": facts,
            "budget": budget,
            "exits": exits,
        }
        return True

    async def _finish(self, actor: CombatParticipant) -> dict | None:
        route = self.route
        assert route is not None and route["actor_id"] == actor.id
        if not route.get("finished") and not await self.advance():
            return None
        return self.steps.pop("movement_route")

    async def advance(self) -> bool:
        from combat_hold import new_head, pump

        route = self.route
        assert route is not None
        state = self.state
        mover = state.get_participant(route["actor_id"])
        assert mover is not None
        spatial = require_spatial(state)
        while True:
            if execution_id := route.get("execution_id"):
                assert state.held_actions and state.held_actions[0]["execution_id"] == execution_id
                self.summaries.extend(
                    await pump(
                        self.session,
                        state,
                        packet_deps=self.packet_deps,
                        fate_rolls=self.fate_rolls,
                        execution_id=execution_id,
                    )
                )
                if state.open_window is not None or self.fate_rolls.pending is not None:
                    return False
                del route["execution_id"]
            if not route["exits"]:
                self._leg(mover, route, route["endpoint"])
                break

            group = route["exits"][0]
            if not group["reactors"]:
                route["exits"].pop(0)
                continue
            reactor = state.get_participant(group["reactors"].pop(0))
            if reactor is None:
                continue
            actions = _melee_actions(state, reactor)
            if not actions:
                continue
            center, point = position(spatial, reactor.id), group["point"]
            separation = distance(center, point)
            action = max(
                (
                    action
                    for action in actions
                    if separation <= melee.melee_reach(action)
                    or math.isclose(separation, melee.melee_reach(action), rel_tol=1e-12)
                ),
                key=_damage_average,
                default=None,
            )
            if action is None or blocking_wall(
                state, spatial, center, point, target_id=mover.id, origin_id=reactor.id, physical=True
            ):
                continue
            self._leg(mover, route, point)
            if not route["facts"]["resolved"]:
                break
            assert not state.held_actions
            head = new_head(
                state,
                reactor.id,
                reactor.initiative,
                {"type": "attack", "action": action["name"], "target_id": mover.id},
                opportunity_attack=True,
                interrupt_position=point,
            )
            state.reactions_available[reactor.id] = {**reaction_spend.unspent(), "spent": True}
            state.held_actions.append(head)
            route["execution_id"] = head["execution_id"]

        route["finished"] = True
        return True

    def _leg(self, actor: CombatParticipant, route: dict, endpoint: dict) -> None:
        facts, budget = route["facts"], route["budget"]
        remaining = budget["remaining"]
        cost = movement_cost(require_spatial(self.state), actor.id, facts["destination"], endpoint)
        if cost > remaining and math.isclose(cost, remaining, rel_tol=1e-12, abs_tol=1e-12):
            budget["remaining"] = cost
        route["facts"] = melee.apply_leg(self.state, actor, facts, endpoint, route["mode"], budget)
