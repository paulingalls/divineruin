"""Healing dice shared by recipients with individual Beacon of Hope effects."""

from collections.abc import Callable
from functools import cache

import dice
from condition_catalog import BEACON_OF_HOPE
from conditions import has_condition


def maximum_healing(conditions: list[dict]) -> bool:
    return has_condition(conditions, BEACON_OF_HOPE)


def shared_roll(notation: str, roll: Callable) -> Callable[[bool], int]:
    @cache
    def result(maximized: bool) -> int:
        return dice.maximum(notation) if maximized else roll(notation).total

    return result
