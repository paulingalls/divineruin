"""Per-recipient patron bonuses for healing spells."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypedDict

from patron_synergy import has_engine_synergy
from rules_engine import attribute_modifier

DAWNS_MERCY = "orenthel_dawns_mercy"


class HealBonus(TypedDict):
    id: str
    bonus: int


HealSynergy = Callable[[int], list[HealBonus]]


def bonus_components(player: dict, hp_before: int) -> list[HealBonus]:
    if not has_engine_synergy(player, DAWNS_MERCY):
        return []
    attributes = player["attributes"]
    amount = max(0, attribute_modifier(attributes["wisdom"]), attribute_modifier(attributes["charisma"]))
    return [{"id": DAWNS_MERCY, "bonus": amount}] if amount else []
