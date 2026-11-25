"""Pending Marshal order benefits, scoped to the combat that granted them."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, TypedDict, cast

if TYPE_CHECKING:
    from combat_state import CombatState

DIRECT_STRIKE = "marshal_direct_strike"
DIRECT_STRIKE_NAME = "Direct Strike"
COORDINATED_ASSAULT = "marshal_coordinated_assault"
COORDINATED_ASSAULT_NAME = "Coordinated Assault"
SACRIFICE_PLAY = "marshal_sacrifice_play"
SACRIFICE_PLAY_NAME = "Sacrifice Play"
FIELD_MEDIC = "marshal_field_medic_order"
FIELD_MEDIC_NAME = "Field Medic Order"


class _Rider(TypedDict):
    expires_round: int
    order_id: str
    source_id: str


class DirectStrikeRider(_Rider):
    kind: Literal["direct_strike"]
    target_id: str


class FirstHit(TypedDict):
    ally_id: str
    target_id: str
    damage_type: str
    magical: bool
    spell_source: str | None


class CoordinatedRider(_Rider):
    kind: Literal["coordinated_assault"]
    target_id: None
    partner_id: str | None
    first_hit: FirstHit | None


class SacrificePlayRider(_Rider):
    kind: Literal["sacrifice_play"]


class FieldMedicRider(_Rider):
    kind: Literal["field_medic"]


OrderRider = DirectStrikeRider | CoordinatedRider | SacrificePlayRider | FieldMedicRider


def _validate_coordinated(rider: dict, recipient: str, participant_ids: tuple[str, ...]) -> None:
    partner = rider["partner_id"]
    if rider["target_id"] is not None:
        raise ValueError(f"Malformed order_riders target_id for {recipient!r}")
    if partner == recipient or partner not in (*participant_ids, None):
        raise ValueError(f"Malformed order_riders partner_id for {recipient!r}")
    first = rider["first_hit"]
    if first is None:
        return
    if (
        not isinstance(first, dict)
        or first.keys() != FirstHit.__required_keys__
        or partner is None
        or first["ally_id"] != partner
        or first["target_id"] not in participant_ids
        or not isinstance(first["damage_type"], str)
        or type(first["magical"]) is not bool
        or not isinstance(first["spell_source"], (str, type(None)))
    ):
        raise ValueError(f"Malformed order_riders first_hit for {recipient!r}")


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
            kind = rider.get("kind") if isinstance(rider, dict) else None
            if kind == "direct_strike":
                shape, order = DirectStrikeRider, DIRECT_STRIKE
            elif kind == "coordinated_assault":
                shape, order = CoordinatedRider, COORDINATED_ASSAULT
            elif kind == "sacrifice_play":
                shape, order = SacrificePlayRider, SACRIFICE_PLAY
            elif kind == "field_medic":
                shape, order = FieldMedicRider, FIELD_MEDIC
            else:
                raise ValueError(f"Malformed order_riders kind for {recipient!r}")
            if rider.keys() != shape.__required_keys__ or rider["order_id"] != order:
                raise ValueError(f"Malformed order_riders entry for {recipient!r}")
            if kind in kinds:
                raise ValueError(f"Duplicate order_riders kind for {recipient!r}: {kind}")
            kinds.add(kind)
            if rider["source_id"] not in participant_ids:
                raise ValueError(f"Malformed order_riders source_id for {recipient!r}")
            if kind == "coordinated_assault":
                _validate_coordinated(rider, recipient, participant_ids)
            if kind == "direct_strike" and rider["target_id"] not in participant_ids:
                raise ValueError(f"Malformed order_riders target_id for {recipient!r}")
            if type(rider["expires_round"]) is not int:
                raise ValueError(f"Malformed order_riders expires_round for {recipient!r}")
    return cast("dict[str, list[OrderRider]]", data)


def _grant(state: CombatState, recipient_id: str, rider: OrderRider) -> dict:
    pending = state.order_riders.setdefault(recipient_id, [])
    replaced = next((entry for entry in pending if entry["kind"] == rider["kind"]), None)
    if replaced is not None:
        pending.remove(replaced)
    pending.append(rider)
    return {"recipient_id": recipient_id, **rider, "replaced": replaced}


def grant_direct_strike(state: CombatState, source_id: str, recipient_id: str, target_id: str) -> dict:
    rider = DirectStrikeRider(
        kind="direct_strike",
        target_id=target_id,
        expires_round=state.round_number + 1,
        order_id=DIRECT_STRIKE,
        source_id=source_id,
    )
    return {"name": DIRECT_STRIKE_NAME, **_grant(state, recipient_id, rider)}


def grant_coordinated_assault(state: CombatState, source_id: str, recipients: list[str]) -> dict:
    first, second = recipients
    grants = [
        _grant(
            state,
            ally,
            CoordinatedRider(
                kind="coordinated_assault",
                target_id=None,
                expires_round=state.round_number + 1,
                order_id=COORDINATED_ASSAULT,
                source_id=source_id,
                partner_id=partner,
                first_hit=None,
            ),
        )
        for ally, partner in ((first, second), (second, first))
    ]
    scrubbed = []
    for ally in state.order_riders:
        if ally in recipients:
            continue
        rider = _coordinated(state, ally)
        if rider is not None and rider["partner_id"] in recipients:
            scrubbed.append({"recipient_id": ally, **rider})
            rider.update(partner_id=None, first_hit=None)
    return {
        "order_id": COORDINATED_ASSAULT,
        "name": COORDINATED_ASSAULT_NAME,
        "source_id": source_id,
        "recipients": grants,
        "scrubbed": scrubbed,
    }


def grant_sacrifice_play(state: CombatState, source_id: str, recipient_id: str) -> dict:
    rider = SacrificePlayRider(
        kind="sacrifice_play",
        expires_round=state.round_number + 1,
        order_id=SACRIFICE_PLAY,
        source_id=source_id,
    )
    return {"name": SACRIFICE_PLAY_NAME, **_grant(state, recipient_id, rider)}


def grant_field_medic(state: CombatState, source_id: str, recipient_id: str) -> dict:
    rider = FieldMedicRider(
        kind="field_medic",
        expires_round=state.round_number + 1,
        order_id=FIELD_MEDIC,
        source_id=source_id,
    )
    return {"name": FIELD_MEDIC_NAME, "declaration_kind": "attack_consume", **_grant(state, recipient_id, rider)}


def select_field_medic(state: CombatState, ally_id: str) -> FieldMedicRider | None:
    return next(
        (
            rider
            for rider in state.order_riders.get(ally_id, ())
            if rider["kind"] == "field_medic" and rider["expires_round"] >= state.round_number
        ),
        None,
    )


def select(state: CombatState | None, attacker_id: str, target_id: str) -> DirectStrikeRider | None:
    if state is None:
        return None
    for rider in state.order_riders.get(attacker_id, ()):
        if rider["kind"] == "direct_strike" and rider["target_id"] == target_id:
            return rider.copy()
    return None


def _coordinated(state: CombatState, ally_id: str) -> CoordinatedRider | None:
    return next((r for r in state.order_riders.get(ally_id, ()) if r["kind"] == "coordinated_assault"), None)


def select_coordinated(state: CombatState | None, attacker_id: str) -> CoordinatedRider | None:
    rider = _coordinated(state, attacker_id) if state is not None else None
    return rider.copy() if rider is not None else None


def select_sacrifice(state: CombatState | None, attacker_id: str) -> SacrificePlayRider | None:
    if state is None:
        return None
    return next((r.copy() for r in state.order_riders.get(attacker_id, ()) if r["kind"] == "sacrifice_play"), None)


def consume(state: CombatState, attacker_id: str, rider: OrderRider) -> None:
    pending = state.order_riders[attacker_id]
    pending.remove(rider)
    if not pending:
        del state.order_riders[attacker_id]


def settle_coordinated(
    state: CombatState, attacker_id: str, rider: CoordinatedRider, first_hit: FirstHit | None
) -> None:
    consume(state, attacker_id, rider)
    partner_id = rider["partner_id"]
    partner = _coordinated(state, partner_id) if partner_id is not None else None
    if partner is not None and partner["partner_id"] == attacker_id:
        partner["first_hit"] = first_hit
        if first_hit is None:
            partner["partner_id"] = None


def expire(state: CombatState) -> None:
    for recipient, riders in list(state.order_riders.items()):
        for rider in riders.copy():
            if rider["expires_round"] <= state.round_number:
                consume(state, recipient, rider)
