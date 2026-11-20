"""Durable initial technique choices derived from level and ownership."""

from collections.abc import Iterable, Sequence

import abilities

PREFIX = "elective_technique_"
TIERS = (4, 8)


def pool(catalog: Iterable[abilities.Ability], level: int) -> tuple[abilities.Ability, ...]:
    return tuple(a for a in catalog if a.ability_type == "elective" and a.level_requirement == level)


def already_chosen(options: Iterable[abilities.Ability], owned_ids: set[str]) -> bool:
    return any(option.id in owned_ids for option in options)


def describe(ability: abilities.Ability) -> dict:
    return {
        "id": ability.id,
        "name": ability.name,
        "effect": ability.effect,
        "narration_cue": ability.narration_cue,
    }


def pools(
    catalog: Sequence[abilities.Ability], level: int, *, from_level: int = 0
) -> dict[int, tuple[abilities.Ability, ...]]:
    return {tier: options for tier in TIERS if from_level < tier <= level and (options := pool(catalog, tier))}


def offers(player_id: str, eligible: dict[int, tuple[abilities.Ability, ...]], owned_ids: set[str]) -> list[dict]:
    return [
        {
            "player_id": player_id,
            "choice_id": f"{PREFIX}{tier}",
            "level": tier,
            "resolve_with": "select",
            "options": [describe(option) for option in options],
            "narration_cue": "Read the technique options aloud and wait for the player's spoken choice.",
        }
        for tier, options in eligible.items()
        if not already_chosen(options, owned_ids)
    ]
