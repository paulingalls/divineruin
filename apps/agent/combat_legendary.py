"""Bind an authored legendary spend to one durable held packet."""

from copy import deepcopy
from functools import partial
from typing import TYPE_CHECKING
from uuid import uuid4

import architect_encounter
import reaction_spend
from architect_reshape import place_section
from combat_ability import _find_action
from combat_declaration_validation import validate_declaration
from combat_down import target_unavailable
from creature_schema import legendary_problems
from declarations import resolve_declaration
from encounter_actions import action_kind
from reshape_payloads import parse_operations

if TYPE_CHECKING:
    from combat_participant import CombatParticipant
    from combat_state import CombatState


def _other_continuation(state: CombatState) -> bool:
    return any(
        cursor is not None
        for cursor in (state.ally_continuation, state.wrap_continuation, state.inner_fire_continuation)
    )


def require_boundary(state: CombatState, *, authored: bool) -> None:
    if (
        (authored and state.beat not in ("declaration", "narration"))
        or _other_continuation(state)
        or state.open_window is not None
        or state.legendary_continuation is not None
        or any(head.get("fate_attack") or any(head.get("roll_steps", {}).values()) for head in state.held_actions)
    ):
        raise ValueError("Finish the current combat action with resolve_phase before spending a legendary action.")


def bind(actor: CombatParticipant, action_id: str) -> dict:
    assert actor.legendary is not None
    for action in actor.legendary["actions"]:
        if action["id"] == action_id:
            return action
    raise ValueError(f"{action_id!r} is not a legendary action for {actor.name}")


def prepare(
    state: CombatState,
    actor: CombatParticipant,
    action_id: str,
    target_id: str,
    reshape: tuple[dict, ...],
    *,
    concealed: frozenset[str] = frozenset(),
) -> None:
    action = bind(actor, action_id)
    cost = action["cost"]
    if cost > actor.legendary_actions:
        raise ValueError(f"{action_id} costs {cost} legendary points; {actor.legendary_actions} remaining this round.")
    if action["kind"] == "attack":
        if not target_id or reshape:
            raise ValueError(f"{action_id} requires a target and empty reshape.")
        raw = {"type": "attack", "action": action_id, "target_id": target_id}
        validate_declaration(state, actor.id, resolve_declaration(raw), {}, concealed=concealed)
        target = state.get_participant(target_id)
        if target is None or target_unavailable(target, _find_action(actor, action_id)):
            raise ValueError(f"The target {target_id!r} is unavailable.")
    else:
        if not architect_encounter.is_owner(state, actor.id):
            raise ValueError("Only the Architect can spend a legendary terrain action.")
        if target_id or len(reshape) != 1:
            raise ValueError(f"{action_id} requires one reshape operation and an empty target.")
        [operation] = parse_operations(list(reshape))
        shift = action["kind"] == "shift_wall"
        if shift and operation["kind"] != "move_wall":
            raise ValueError("Shift Wall requires a move_wall operation.")
        place_section(deepcopy(state), actor.id, operation, shift_wall=shift)
        raw = {"type": "defend", "reshape": [operation]}

    if state.beat == "declaration" and action["kind"] == "attack":
        for participant in state.participants:
            if participant.type == "player" and participant.has_reaction_ability:
                state.reactions_available.setdefault(participant.id, reaction_spend.unspent())

    # Ordinary held packets use nonnegative indexes in reaction window IDs.
    state.legendary_sequence -= 1
    execution_id = uuid4().hex
    state.legendary_continuation = {
        "actor_id": actor.id,
        "action_id": action_id,
        "cost": cost,
        "remaining": actor.legendary_actions - cost,
        "round": state.round_number,
        "execution_id": execution_id,
    }
    actor.legendary_actions -= cost
    state.held_actions.insert(
        0,
        {
            "actor_id": actor.id,
            "seq": state.legendary_sequence,
            "execution_id": execution_id,
            "legendary_kind": action["kind"],
            "initiative": actor.initiative,
            "declaration": raw,
            "roll": None,
            "roll_published": False,
            "opened": [],
        },
    )


def _runtime_binding(state: CombatState, actor: CombatParticipant, identifier: str, kind: object) -> bool:
    if kind == "attack":
        return any(
            action.get("name") == identifier
            and action_kind(action) == "attack"
            and action.get("damage") not in (None, "", "0", "0d0", 0)
            for action in actor.action_pool
        )
    return architect_encounter.is_owner(state, actor.id) and (
        (kind, identifier) in (("shift_wall", "Shift Wall"), ("reshape", "Reshape"))
    )


def validate(state: CombatState) -> None:
    for actor in state.participants:
        if actor.legendary is None:
            continue
        if problems := legendary_problems(actor.legendary, partial(_runtime_binding, state, actor)):
            raise ValueError(f"{actor.id}: {'; '.join(problems)}")
        if type(actor.legendary_actions) is not int or not 0 <= actor.legendary_actions <= actor.legendary_capacity:
            raise ValueError(f"{actor.id}: invalid legendary points remaining")
    if type(state.legendary_sequence) is not int or state.legendary_sequence > 0:
        raise ValueError("Invalid legendary sequence")
    marked = [head for head in state.held_actions if "legendary_kind" in head or head.get("seq", 0) < 0]
    cursor = state.legendary_continuation
    if cursor is None:
        if marked:
            raise ValueError("Legendary packet has no continuation")
        return
    invalid = "Invalid legendary continuation"
    if (
        not isinstance(cursor, dict)
        or set(cursor) != {"actor_id", "action_id", "cost", "remaining", "round", "execution_id"}
        or not all(isinstance(cursor[k], str) and cursor[k] for k in ("actor_id", "action_id", "execution_id"))
        or not all(type(cursor[k]) is int for k in ("cost", "remaining", "round"))
        or cursor["round"] != state.round_number
        or state.beat not in ("declaration", "narration")
        or _other_continuation(state)
        or len(marked) != 1
        or marked[0] is not state.held_actions[0]
    ):
        raise ValueError(invalid)
    head = marked[0]
    actor = state.get_participant(cursor["actor_id"])
    if (
        actor is None
        or actor.legendary is None
        or head.get("actor_id") != actor.id
        or head.get("execution_id") != cursor["execution_id"]
        or head["seq"] != state.legendary_sequence
        or state.legendary_sequence >= 0
        or any(other.get("execution_id") == head["execution_id"] for other in state.held_actions[1:])
    ):
        raise ValueError(invalid)
    action = bind(actor, cursor["action_id"])
    if (
        cursor["cost"] != action["cost"]
        or head.get("legendary_kind") != action["kind"]
        or not 0 <= cursor["remaining"] == actor.legendary_actions <= actor.legendary_capacity - action["cost"]
    ):
        raise ValueError(invalid)
    decl = resolve_declaration(head["declaration"])
    if window := state.open_window:
        stage = window.get("stage")
        if (
            stage not in head["opened"]
            or window.get("id") != f"r{state.round_number}-{head['seq']}-{stage}"
            or window.get("actor_id") != actor.id
            or window.get("target_id") != decl.target_id
        ):
            raise ValueError(invalid)
    elif not (head.get("fate_attack") or any(head.get("roll_steps", {}).values())):
        raise ValueError(invalid)
    if action["kind"] == "attack":
        if (
            decl.type != "attack"
            or decl.action != action["id"]
            or decl.reshape
            or decl.target_id is None
            or state.get_participant(decl.target_id) is None
        ):
            raise ValueError(invalid)
    elif (
        not architect_encounter.is_owner(state, actor.id)
        or decl.type != "defend"
        or not decl.reshape
        or len(decl.reshape) != 1
        or (action["kind"] == "shift_wall" and decl.reshape[0]["kind"] != "move_wall")
    ):
        raise ValueError(invalid)
