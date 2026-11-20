"""Patron bonuses for healing spells."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, TypedDict

import dice
from patron_synergy import has_engine_synergy
from rules_engine import attribute_modifier
from terrain import is_natural

if TYPE_CHECKING:
    from encounter_facts import EncounterFacts

DAWNS_MERCY = "orenthel_dawns_mercy"
THRESHOLD_HEALING = "mortaen_threshold_healing"
FINAL_MERCY = "mortaen_final_mercy"
VERDANT_HEALING = "thyra_verdant_healing"
TRAVELERS_BLESSING = "nythera_travelers_blessing"
APPOINTED_MERCY = "zhael_appointed_mercy"


class HealBonus(TypedDict):
    id: str
    bonus: int


HealSynergy = Callable[[str, int, int], list[HealBonus]]


def for_cast(
    player: dict,
    *,
    terrain: str | None,
    first_stay: bool,
    facts: EncounterFacts | None = None,
    round_number: int | None = None,
    dice_mod=dice,
) -> HealSynergy:
    place: list[HealBonus] = []
    if has_engine_synergy(player, VERDANT_HEALING):
        if terrain is None:
            raise RuntimeError("Verdant Healing requires resolved cast terrain")
        if is_natural(terrain):
            place.append({"id": VERDANT_HEALING, "bonus": dice_mod.roll("1d4").total})
    if first_stay and has_engine_synergy(player, TRAVELERS_BLESSING):
        place.append({"id": TRAVELERS_BLESSING, "bonus": 1})
    savers = set()
    if facts is not None and has_engine_synergy(player, APPOINTED_MERCY):
        savers = {pid for pid, saved_round in facts["death_save_success_round"].items() if saved_round == round_number}

    def bonuses(recipient_id: str, before: int, base: int) -> list[HealBonus]:
        components = [*place, *bonus_components(player, before, base)]
        if recipient_id in savers:
            components.append({"id": APPOINTED_MERCY, "bonus": 1})
        return components

    return bonuses


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
