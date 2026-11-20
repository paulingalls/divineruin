"""Recipient-turn and combat-end healing from Regenerate."""

import event_types as E
from combat_down import is_terminally_down
from combat_events import EventSink
from combat_spell_heal import restore
from conditions import remove_condition
from session_data import CombatState, SessionData


def _condition(target) -> dict | None:
    return next((c for c in target.conditions if c["type"] == "regenerating"), None)


def _remaining(condition: dict) -> int:
    remaining = condition.get("ticks_remaining")
    if type(remaining) is not int or remaining <= 0:
        raise ValueError("regenerating requires positive integer ticks_remaining")
    return remaining


async def tick(target, *, conn, mutations) -> dict | None:
    condition = _condition(target)
    if condition is None or not target.is_ally or is_terminally_down(target):
        return None
    remaining = _remaining(condition)
    healed = await restore(target, 1, conn=conn, mutations=mutations)
    if remaining == 1:
        target.conditions = remove_condition(target.conditions, "regenerating")
    else:
        condition["ticks_remaining"] = remaining - 1
    return {
        "name": "Regenerating",
        "source_id": condition["source"],
        "target_id": target.id,
        "healed": healed,
        "hp_current": target.hp_current,
        "hp_max": target.hp_max,
    }


async def settle(state: CombatState, *, conn, mutations) -> set[str]:
    regenerated = set()
    for target in state.participants:
        condition = _condition(target)
        if condition is None:
            continue
        if not target.is_ally or is_terminally_down(target):
            continue
        await restore(target, _remaining(condition), conn=conn, mutations=mutations)
        regenerated.add(target.id)
    return regenerated


async def publish_settled_hp(
    session: SessionData, state: CombatState, sink: EventSink, settled_hp: dict[str, tuple[int, int]]
) -> None:
    for target in state.participants:
        if target.type == "player" or target.id in settled_hp:
            current, maximum = settled_hp.get(target.id, (target.hp_current, target.hp_max))
            await sink.emit(
                session.room,
                E.HP_CHANGED,
                {"current": current, "max": maximum, "temp_hp": target.temp_hp},
                event_bus=session.event_bus,
                destination_identities=[target.id],
            )
