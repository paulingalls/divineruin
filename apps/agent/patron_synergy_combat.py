"""Authoritative patron selection and attack-only synergy effects."""

import random

from dice import roll as dice_roll
from patron_synergy import has_engine_synergy


async def attack_player(attacker, *, queries, conn) -> dict | None:
    if attacker.type not in ("player", "temporary_hollowed"):
        return None
    player = await queries.get_player(attacker.id, conn=conn)
    if player is None:
        raise RuntimeError(f"Attack participant {attacker.id!r} has no player row")
    return player


def attack_flags(player: dict) -> dict[str, bool]:
    return {
        "expanded_critical": has_engine_synergy(player, "zhael_bent_probability"),
        "critical_rider": has_engine_synergy(player, "thyra_natures_edge"),
    }


def expanded_critical(attacker_data: dict, face: int) -> bool:
    return bool(attacker_data.get("expanded_critical")) and face == 19


def critical_rider(attacker_data: dict, critical: bool, *, rng: random.Random | None) -> tuple[int, str | None]:
    if critical and attacker_data.get("critical_rider"):
        return dice_roll("1d4", rng=rng).total, "lightning"
    return 0, None
