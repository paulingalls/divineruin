"""Beneficial dice shared by skill, attack and save resolution."""

import random
from dataclasses import dataclass

from conditions import CONDITION_CATALOG, ConditionEffects
from dice import roll as dice_roll


@dataclass(frozen=True)
class BonusDiceRoll:
    total: int
    consumed: tuple[str, ...]
    war_songs_bonus: int = 0


def roll_bonus_dice(
    effects: ConditionEffects,
    roll_kind: str,
    rng: random.Random | None = None,
    *,
    spoken_buffs_eligible: bool = True,
) -> BonusDiceRoll:
    total = 0
    war_songs_bonus = 0
    consumed: list[str] = []
    for bonus in effects.bonus_dice:
        if bonus.source == "inspired" and (not spoken_buffs_eligible or "no_spoken_buffs" in effects.restrictions):
            continue
        if roll_kind in bonus.scopes:
            upgraded = roll_kind == "attack" and bonus.inspire_attack_upgrade
            value = dice_roll("1d6" if upgraded else bonus.dice, rng=rng).total
            total += value
            if upgraded:
                war_songs_bonus += value
            if CONDITION_CATALOG[bonus.source].clearance == "consumed_on_use":
                consumed.append(bonus.source)
    return BonusDiceRoll(total, tuple(consumed), war_songs_bonus)
