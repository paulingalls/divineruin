"""Seasonal Attunement at the healing, damage, and skill roll boundaries."""

from __future__ import annotations

from typing import TYPE_CHECKING

import world_season
from patron_passives import acknowledged_passive

if TYPE_CHECKING:
    import asyncpg

    from world_season import Season

GIFT = "thyra_seasonal_attunement"
ACTIVE_BONUS: dict[Season, str] = {
    "spring": "+1 healing received per heal.",
    "summer": "+1 damage per fire or lightning roll.",
    "autumn": "+1 to Insight checks.",
    "winter": "+1 to Stealth checks.",
}
SKILL_SEASONS: dict[str, Season] = {"insight": "autumn", "stealth": "winter"}
DAMAGE_TYPES = {"fire", "lightning"}


def eligible(player: dict | None) -> bool:
    return player is not None and acknowledged_passive(player, "thyra", GIFT)


async def season_for(player: dict | None, *, conn: asyncpg.Connection | asyncpg.Pool | None = None) -> Season | None:
    return await world_season.current_season(conn=conn) if eligible(player) else None


async def skill_season(
    player: dict, skill: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> Season | None:
    return await season_for(player, conn=conn) if skill.lower() in SKILL_SEASONS else None


def healing_bonus(season: Season | None, heals: int = 1) -> int:
    return heals if season == "spring" else 0


def damage_bonus(player: dict | None, season: Season | None, damage_type: str | None) -> int:
    if damage_type not in DAMAGE_TYPES or not eligible(player):
        return 0
    if season is None:
        raise ValueError("Seasonal Attunement damage roll requires the world season")
    return int(season == "summer")


def skill_bonus(player: dict, season: Season | None, skill: str) -> int:
    active = SKILL_SEASONS.get(skill)
    if active is None or not eligible(player):
        return 0
    if season is None:
        raise ValueError("Seasonal Attunement skill check requires the world season")
    return int(season == active)
