"""Kaelen's once-per-encounter living HP crossing."""

from _gods_content import load_gods
from combat_participant import CombatParticipant
from conditions import apply_condition
from session_data import SessionData


def trigger_iron_resolve(session: SessionData, target: CombatParticipant, hp_before: int) -> str | None:
    if target.type != "player":
        return None
    member = session.party.member(target.id)
    if member is None:
        raise ValueError(f"Missing party member for combat player {target.id!r}")
    if member.patron_id != "kaelen" or target.iron_resolve_spent:
        return None
    gift = next(row for row in load_gods() if row["god_id"] == "kaelen")["layer_1_gift"]
    if gift["status"] != "active":
        raise ValueError("Kaelen's Iron Resolve gift is not active")
    mechanics = gift["mechanics"]
    threshold = target.hp_max * mechanics["threshold"]
    if not (hp_before >= threshold and 0 < target.hp_current < threshold):
        return None
    target.conditions = apply_condition(
        target.conditions, "iron_resolve", duration=mechanics["duration_phases"], source=gift["id"]
    )
    target.iron_resolve_spent = True
    return gift["name"]
