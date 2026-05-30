"""Deterministic d20-seed helper shared across crafting/experimentation tests.

`resolve_crafting`/`resolve_experimentation` draw the d20 as their first rng call
(gates consume no rng), so a Random seed whose first randint(1,20) equals a target
fixes the outcome band deterministically. Kept in one place so the four band-driven
test modules don't each carry a copy.
"""

from __future__ import annotations

import random


def seed_for_d20(target: int, *, search_limit: int = 2000) -> int:
    """Return a seed whose first ``randint(1, 20)`` equals ``target``."""
    for seed in range(search_limit):
        if random.Random(seed).randint(1, 20) == target:
            return seed
    raise AssertionError(f"no seed for d20={target}")
