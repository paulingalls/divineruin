"""Dice notation parser and roller.

Supports: d20, 2d6, 4d6kh3 (keep highest), 4d6kl1 (keep lowest),
1d8+3, 2d6-1. Accepts seeded RNG for deterministic testing.
"""

import random
import re
from dataclasses import dataclass

_DICE_RE = re.compile(
    r"^(\d*)d(\d+)"
    r"(?:k([hl])(\d+))?"
    r"([+-]\d+)?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DiceResult:
    notation: str
    rolls: list[int]
    dropped: list[int]
    total: int


def roll(notation: str, rng: random.Random | None = None) -> DiceResult:
    """Roll dice from a notation string. Raises ValueError for invalid input."""
    clean = notation.strip().lower()
    m = _DICE_RE.match(clean)
    if not m:
        raise ValueError(f"Invalid dice notation: '{notation}'")

    count = int(m.group(1)) if m.group(1) else 1
    sides = int(m.group(2))

    if count < 1 or sides < 1:
        raise ValueError(f"Invalid dice notation: '{notation}'")

    keep_mode = m.group(3)  # 'h' or 'l' or None
    keep_count = int(m.group(4)) if m.group(4) else None
    bonus = int(m.group(5)) if m.group(5) else 0

    if keep_count is not None and keep_count > count:
        raise ValueError(
            f"Cannot keep {keep_count} dice when only rolling {count}"
        )

    r = rng or random.SystemRandom()
    all_rolls = [r.randint(1, sides) for _ in range(count)]

    if keep_count is not None:
        sorted_rolls = sorted(all_rolls, reverse=(keep_mode == "h"))
        kept = sorted_rolls[:keep_count]
        dropped = sorted_rolls[keep_count:]
    else:
        kept = list(all_rolls)
        dropped = []

    total = sum(kept) + bonus

    return DiceResult(
        notation=clean,
        rolls=kept,
        dropped=dropped,
        total=total,
    )
