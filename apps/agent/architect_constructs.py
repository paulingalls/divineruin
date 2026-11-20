"""Summoned enemy turns and lifetime in the Architect's encounter."""

from math import cos, sin, tau
from typing import TYPE_CHECKING

import combat_spatial
from combat_participant import CombatParticipant
from dice import roll

if TYPE_CHECKING:
    from combat_state import CombatState
    from declarations import Declaration


KIND = "summon_constructs"


def _prefix(owner_id: str) -> str:
    return f"{owner_id}_summon_"


def _timing(owner: CombatParticipant) -> tuple[int, int] | None:
    action = next((action for action in owner.action_pool if action.get("kind") == KIND), None)
    if action is None:
        return None
    entry = owner.action_ledger.get(action["name"].casefold())
    if entry is None:
        return None
    remaining = entry.get("remaining")
    if type(remaining) is not int or remaining != 0:
        return None
    summoned = entry.get("round")
    if type(summoned) is not int or summoned < 1:
        raise ValueError("Architect summon round is invalid")
    return summoned, summoned + action["summon"]["lifetime_rounds"] + 1


def facts(owner: CombatParticipant) -> dict:
    timing = _timing(owner)
    if timing is None:
        return {}
    summoned, expiry = timing
    return {"summon_round": summoned, "construct_first_round": summoned + 1, "construct_expiry_round": expiry}


def validate(state: CombatState, owner: CombatParticipant, record: dict) -> None:
    ids = record["construct_ids"]
    if not isinstance(ids, list) or any(not isinstance(actor_id, str) for actor_id in ids):
        raise ValueError("Invalid Architect construct IDs")
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate Architect construct IDs")
    participants = [p for p in state.participants if p.id.startswith(_prefix(owner.id))]
    if set(ids) != {p.id for p in participants} or len(ids) != len(participants):
        raise ValueError("Architect construct IDs must match their summoned participants")
    if any(p.type != "enemy" for p in participants):
        raise ValueError("Architect summons must be enemies")
    timing = _timing(owner)
    if bool(ids) != (timing is not None):
        raise ValueError("Architect constructs require a matching spent summon")
    if timing is None:
        return
    summoned, expiry = timing
    if summoned > state.round_number:
        raise ValueError("Architect summon round is invalid")
    if (state.round_number >= expiry or owner.hp_current <= 0) and any(
        p.hp_current > 0 or not p.is_fallen or not p.is_dead for p in participants
    ):
        raise ValueError("Expired or destroyed Architect still owns live constructs")


def _add(
    state: CombatState, owner: CombatParticipant, summons: list[CombatParticipant], positions: dict, speeds: dict
) -> None:
    ids = list(positions)
    if set(ids).intersection(p.id for p in state.participants):
        raise ValueError("Architect summon IDs are already in use")
    spatial = combat_spatial.require_spatial(state)
    start = state.initiative_order.index(owner.id) + 1
    state.participants.extend(summons)
    spatial["positions"].update(positions)
    spatial["speeds"].update(speeds)
    state.initiative_order[start:start] = ids
    combat_spatial.require_spatial(state)


def resolve(state: CombatState, owner: CombatParticipant, action: dict, declaration: Declaration) -> dict:
    from combat_action_availability import begin_execution

    record = state.architect_encounter
    if record is None or owner.id != record["owner_id"]:
        raise ValueError("Summon Constructs requires the Architect")
    spatial = combat_spatial.require_spatial(state)
    origin = combat_spatial.position(spatial, owner.id)
    spec = action["summon"]
    count = roll(spec["count_dice"]).total
    block = spec["construct"]
    slam = {**block["slam"], "attack_source": "catalog"}
    summons = []
    positions = {}
    for index in range(count):
        actor_id = f"{_prefix(owner.id)}{index + 1}"
        summons.append(
            CombatParticipant(
                id=actor_id,
                name=f"Construct {index + 1}",
                type="enemy",
                initiative=owner.initiative,
                hp_current=block["hp"],
                hp_max=block["hp"],
                ac=block["ac"],
                role="minion",
                action_pool=[dict(slam)],
            )
        )
        angle = tau * index / count
        # A ring at the full authored radius lands a hair past it after cos/sin rounding (10.000000000000002 ft),
        # so the ring sits well inside it.
        radius = spec["placement_radius_ft"] / 2
        positions[actor_id] = {**origin, "x": origin["x"] + radius * cos(angle), "y": origin["y"] + radius * sin(angle)}
    _add(state, owner, summons, positions, dict.fromkeys(positions, block["speed"]))
    begin_execution(state, owner, action, declaration)
    record["construct_ids"] = list(positions)
    return {
        "actor_id": owner.id,
        "action": action["name"],
        "resolved": True,
        "construct_ids": record["construct_ids"],
        **facts(owner),
    }


def restore(state: CombatState, retained: CombatState, owner: CombatParticipant, ids: list[str]) -> None:
    if not ids:
        return
    spatial = combat_spatial.require_spatial(retained)
    summons = []
    for actor_id in ids:
        construct = retained.get_participant(actor_id)
        assert construct is not None
        construct.initiative = owner.initiative
        summons.append(construct)
    _add(
        state,
        owner,
        summons,
        {actor_id: spatial["positions"][actor_id] for actor_id in ids},
        {actor_id: spatial["speeds"][actor_id] for actor_id in ids},
    )


def resolution_order(state: CombatState, ordered_ids: list[str]) -> list[str]:
    record = state.architect_encounter
    if record is None or not record["construct_ids"]:
        return ordered_ids
    owner_id = record["owner_id"]
    group = [actor_id for actor_id in record["construct_ids"] if actor_id in ordered_ids]
    if not group:
        return ordered_ids
    ordered = [actor_id for actor_id in ordered_ids if actor_id not in group]
    if owner_id in ordered:
        start = ordered.index(owner_id) + 1
    else:
        from combat_phase import resolution_sort_key

        slot = resolution_sort_key(state.get_participant(owner_id))
        # A missing owner still anchors its group at the same initiative and DEX priority.
        start = next(
            (
                index
                for index, actor_id in enumerate(ordered)
                if resolution_sort_key(state.get_participant(actor_id)) < slot
            ),
            len(ordered),
        )
    ordered[start:start] = group
    return ordered


def collapse(state: CombatState, ids: list[str]) -> None:
    for actor_id in ids:
        construct = state.get_participant(actor_id)
        assert construct is not None
        construct.hp_current = 0
        construct.is_fallen = True
        construct.is_dead = True


def expire(state: CombatState) -> None:
    record = state.architect_encounter
    if record is None or not record["construct_ids"]:
        return
    owner = state.get_participant(record["owner_id"])
    assert owner is not None
    timing = _timing(owner)
    assert timing is not None
    if state.round_number == timing[1]:
        collapse(state, record["construct_ids"])
