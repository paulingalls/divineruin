"""Pending Marshal order benefits, scoped to the combat that granted them."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, TypedDict, cast

if TYPE_CHECKING:
    from combat_state import CombatState

DIRECT_STRIKE = "marshal_direct_strike"
DIRECT_STRIKE_NAME = "Direct Strike"


class OrderRider(TypedDict):
    kind: Literal["direct_strike"]
    target_id: str | None
    expires_round: int
    order_id: str
    source_id: str


def validate(data: object, participants: list[dict]) -> dict[str, list[OrderRider]]:
    if not isinstance(data, dict):
        raise ValueError("Malformed order_riders map")
    participant_ids = tuple(p["id"] for p in participants if p["id"])
    for recipient, riders in data.items():
        if recipient not in participant_ids:
            raise ValueError(f"Malformed order_riders recipient: {recipient!r}")
        if not isinstance(riders, list):
            raise ValueError(f"Malformed order_riders list for {recipient!r}")
        kinds = set()
        for rider in riders:
            if not isinstance(rider, dict) or rider.keys() != OrderRider.__required_keys__:
                raise ValueError(f"Malformed order_riders entry for {recipient!r}")
            kind = rider["kind"]
            if kind != "direct_strike" or rider["order_id"] != DIRECT_STRIKE:
                raise ValueError(f"Malformed order_riders kind or order for {recipient!r}")
            if kind in kinds:
                raise ValueError(f"Duplicate order_riders kind for {recipient!r}: {kind}")
            kinds.add(kind)
            for field in ("source_id", "target_id"):
                pid = rider[field]
                if pid not in participant_ids:
                    raise ValueError(f"Malformed order_riders {field} for {recipient!r}")
            if type(rider["expires_round"]) is not int:
                raise ValueError(f"Malformed order_riders expires_round for {recipient!r}")
    return cast("dict[str, list[OrderRider]]", data)


def grant_direct_strike(state: CombatState, source_id: str, recipient_id: str, target_id: str) -> dict:
    rider = OrderRider(
        kind="direct_strike",
        target_id=target_id,
        expires_round=state.round_number + 1,
        order_id=DIRECT_STRIKE,
        source_id=source_id,
    )
    pending = state.order_riders.setdefault(recipient_id, [])
    replaced = next((entry for entry in pending if entry["kind"] == rider["kind"]), None)
    if replaced is not None:
        pending.remove(replaced)
    pending.append(rider)
    return {"recipient_id": recipient_id, "name": DIRECT_STRIKE_NAME, **rider, "replaced": replaced}


def select(state: CombatState | None, attacker_id: str, target_id: str) -> OrderRider | None:
    if state is None:
        return None
    for rider in state.order_riders.get(attacker_id, ()):
        if rider["target_id"] == target_id:
            return rider.copy()
    return None


def consume(state: CombatState, attacker_id: str, rider: OrderRider) -> None:
    pending = state.order_riders[attacker_id]
    pending.remove(rider)
    if not pending:
        del state.order_riders[attacker_id]


def expire(state: CombatState) -> None:
    for recipient, riders in list(state.order_riders.items()):
        for rider in riders.copy():
            if rider["expires_round"] <= state.round_number:
                consume(state, recipient, rider)
