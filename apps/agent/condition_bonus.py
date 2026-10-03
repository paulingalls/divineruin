"""Single-use beneficial dice shared by skill, attack and save resolution."""

import random

from conditions import ConditionEffects
from dice import roll as dice_roll


def roll_bonus_dice(
    effects: ConditionEffects,
    roll_kind: str,
    rng: random.Random | None = None,
    *,
    spoken_buffs_eligible: bool = True,
) -> tuple[int, tuple[str, ...]]:
    total = 0
    consumed: list[str] = []
    for bonus in effects.bonus_dice:
        if bonus.source == "inspired" and (not spoken_buffs_eligible or "no_spoken_buffs" in effects.restrictions):
            continue
        if roll_kind in bonus.scopes:
            total += dice_roll(bonus.dice, rng=rng).total
            consumed.append(bonus.source)
    return total, tuple(consumed)
