"""Live chambers and the conditions they own."""

from __future__ import annotations

from typing import TYPE_CHECKING

import architect_encounter
import combat_spatial
import conditions
from combat_participant import CombatParticipant
from combat_structures import WALL_AC, WALL_HP, collapse_wall

if TYPE_CHECKING:
    from combat_state import CombatState

ACTION = "Entomb"
ESCAPE_DC = 12
COMPRESSION = {"damage": "1d4", "damage_type": "bludgeoning"}


def matches(actor: CombatParticipant, action: dict) -> bool:
    return actor.creature_id == architect_encounter.CREATURE_ID and action["name"] == ACTION


def range_refusal(state: CombatState, actor: CombatParticipant, action: dict, target_id: str | None) -> str | None:
    target = state.get_participant(target_id) if target_id else None
    if target is None or not target.is_ally:
        return "Entomb requires a traveller as its target."
    spatial = combat_spatial.require_spatial(state)
    distance = combat_spatial.distance(
        combat_spatial.position(spatial, actor.id), combat_spatial.position(spatial, target.id)
    )
    if distance > action["reach"]:
        return f"{target.name} is {distance:g} feet away. Entomb reaches {action['reach']} feet."
    return None


def chambers(spatial: dict | None) -> dict:
    return spatial.get("chambers", {}) if spatial is not None else {}


def source(state: CombatState, target_id: str) -> str | None:
    return next((id_ for id_, link in chambers(state.spatial).items() if link["target_id"] == target_id), None)


def blocker(
    spatial: dict,
    origin_id: str | None,
    target_id: str | None,
) -> str | None:
    for chamber_id, link in chambers(spatial).items():
        victim = link["target_id"]
        if victim == origin_id and target_id not in (victim, chamber_id):
            return chamber_id
        if victim == target_id and origin_id != victim:
            return chamber_id
    return None


def _prefix(owner_id: str) -> str:
    return f"{owner_id}_chamber_"


def _sourced(condition: dict, chamber_id: str) -> bool:
    return condition["type"] == "restrained" and condition.get("source") == chamber_id


def _facts(chamber: CombatParticipant, target_id: str) -> dict:
    return {
        "chamber_id": chamber.id,
        "target_id": target_id,
        "ac": chamber.ac,
        "hp": chamber.hp_current,
        "hp_max": chamber.hp_max,
        "escape_attribute": "STR",
        "escape_dc": ESCAPE_DC,
        "compression": dict(COMPRESSION),
    }


def land(state: CombatState, owner: CombatParticipant, target: CombatParticipant, summary: dict) -> None:
    if summary["save_success"]:
        summary["condition_resisted"] = "restrained"
        return
    if immunity := target.condition_immunities.get("restrained"):
        summary.update(condition_immune="restrained", condition_immunity_source=immunity)
        return
    spatial = combat_spatial.require_spatial(state)
    record = state.architect_encounter
    if record is None or record["owner_id"] != owner.id:
        raise ValueError("Entomb requires the Architect encounter owner")
    index = len(record["structure_ids"])
    chamber_id = f"{_prefix(owner.id)}{index}"
    while any(chamber_id in spatial[key] for key in ("positions", "locations", "zones")):
        index += 1
        chamber_id = f"{_prefix(owner.id)}{index}"
    applied = conditions.apply_condition(target.conditions, "restrained", source=chamber_id)
    if not any(_sourced(condition, chamber_id) for condition in applied):
        summary["condition_immune"] = "restrained"
        return
    chamber = CombatParticipant(chamber_id, "Entomb chamber", "structure", 0, WALL_HP, WALL_HP, WALL_AC)
    target.conditions = applied
    state.participants.append(chamber)
    spatial["positions"][chamber_id] = dict(combat_spatial.position(spatial, target.id))
    spatial["speeds"][chamber_id] = 0
    spatial.setdefault("chambers", {})[chamber_id] = {"target_id": target.id}
    record["structure_ids"].append(chamber_id)
    summary.update(_facts(chamber, target.id), condition_inflicted="restrained")


def unlink(state: CombatState, chamber_id: str) -> bool:
    link = chambers(state.spatial).pop(chamber_id, None)
    if link is None:
        return False
    victim = state.get_participant(link["target_id"])
    assert victim is not None
    victim.conditions = [c for c in victim.conditions if not _sourced(c, chamber_id)]
    return True


def release_all(state: CombatState) -> None:
    for chamber_id in tuple(chambers(state.spatial)):
        chamber = state.get_participant(chamber_id)
        assert chamber is not None
        collapse_wall(state, chamber)


def validate_links(state: CombatState, links: dict) -> None:
    record = state.architect_encounter
    owned = record.get("structure_ids") if isinstance(record, dict) else None
    victims = set()
    for chamber_id, link in links.items():
        if not isinstance(owned, list) or chamber_id not in owned:
            raise ValueError("Entomb chamber must be owned by the Architect")
        if not isinstance(link, dict) or set(link) != {"target_id"} or not isinstance(link["target_id"], str):
            raise ValueError("Invalid Entomb chamber link")
        victim = state.get_participant(link["target_id"])
        if victim is None or victim.is_structure:
            raise ValueError("Entomb chamber requires a creature target")
        if victim.id in victims:
            raise ValueError("A creature can occupy only one Entomb chamber")
        victims.add(victim.id)
        restraints = [c for c in victim.conditions if _sourced(c, chamber_id)]
        if len(restraints) != 1 or restraints[0].get("duration", False) is not None:
            raise ValueError("Entomb target requires its chamber's permanent Restrained")
        if chamber_id in state.initiative_order:
            raise ValueError("Entomb chamber cannot have an initiative turn")

    owner_id = record.get("owner_id") if isinstance(record, dict) else None
    if not isinstance(owner_id, str):
        return
    prefix = _prefix(owner_id)
    for actor in state.participants:
        for condition in actor.conditions:
            source_id = condition.get("source")
            if condition["type"] != "restrained" or not isinstance(source_id, str):
                continue
            if (source_id in links or source_id.startswith(prefix)) and links.get(source_id) != {"target_id": actor.id}:
                raise ValueError("Chamber-sourced Restrained has no matching Entomb link")


def retired_ids(state: CombatState) -> set[str]:
    record = state.architect_encounter
    if record is None:
        return set()
    prefix = _prefix(record["owner_id"])
    return {p.id for p in state.participants if p.is_structure and p.is_dead and p.id.startswith(prefix)}


def facts(state: CombatState, spatial: dict) -> tuple[list[dict], list[str]]:
    details = []
    spoken = []
    for chamber_id, link in chambers(spatial).items():
        chamber = state.get_participant(chamber_id)
        victim = state.get_participant(link["target_id"])
        assert chamber is not None and victim is not None
        details.append(_facts(chamber, victim.id))
        spoken.append(
            f"{victim.name} is sealed in {chamber_id}. The chamber has armor class {chamber.ac} and {chamber.hp_current} hit points. "
            f"Break it or escape with a DC {ESCAPE_DC} Strength check. It deals {COMPRESSION['damage']} bludgeoning at each turn start."
        )
    return details, spoken
