"""Per-recipient patron bonuses for healing spells."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypedDict

from patron_synergy import has_engine_synergy
from rules_engine import attribute_modifier

DAWNS_MERCY = "orenthel_dawns_mercy"
THRESHOLD_HEALING = "mortaen_threshold_healing"
FINAL_MERCY = "mortaen_final_mercy"


class HealBonus(TypedDict):
    id: str
    bonus: int


HealSynergy = Callable[[int, int], list[HealBonus]]


def bonus_components(player: dict, hp_before: int, base_heal: int) -> list[HealBonus]:
    if has_engine_synergy(player, DAWNS_MERCY):
        attributes = player["attributes"]
        amount = max(0, attribute_modifier(attributes["wisdom"]), attribute_modifier(attributes["charisma"]))
        return [{"id": DAWNS_MERCY, "bonus": amount}] if amount else []
    if hp_before == 0:
        if base_heal > 0 and has_engine_synergy(player, THRESHOLD_HEALING):
            return [{"id": THRESHOLD_HEALING, "bonus": base_heal}]
        if has_engine_synergy(player, FINAL_MERCY):
            return [{"id": FINAL_MERCY, "bonus": 1}]
    return []
