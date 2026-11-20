"""Authoritative patron selection and combat synergy effects."""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from dice import roll as dice_roll
from patron_synergy import has_engine_synergy

if TYPE_CHECKING:
    from combat_participant import CombatParticipant
    from combat_state import CombatState


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
        "weapon_damage_bonus": bool((player.get("flags") or {}).get("extra_attack"))
        and has_engine_synergy(player, "kaelen_extra_attack_damage"),
    }


def encounter_damage_clause(
    player: dict,
    state: CombatState | None,
    attacker: CombatParticipant,
    target: CombatParticipant,
    action: dict,
) -> str | None:
    if state is None:
        return None

    from combat_melee_approach import is_melee
    from encounter_facts import ZHAEL_THREADED_BLADE

    facts = state.encounter_facts
    if target.id in facts["ally_downers"] and has_engine_synergy(player, "mortaen_last_vigil"):
        return "mortaen_last_vigil"
    if (
        target.id in facts["misses"].get(attacker.id, ())
        and attacker.id not in facts["once_spent"].get(ZHAEL_THREADED_BLADE, ())
        and has_engine_synergy(player, ZHAEL_THREADED_BLADE)
        and is_melee(action)
    ):
        return ZHAEL_THREADED_BLADE
    return None


def expanded_critical(attacker_data: dict, face: int) -> bool:
    return bool(attacker_data.get("expanded_critical")) and face == 19


def spell_attack_bonus(player: dict, target) -> int:
    return int(target.category == "undead" and has_engine_synergy(player, "mortaen_ashen_formula"))


def spell_damage_type_override(player: dict, spell_id: str) -> str | None:
    if spell_id == "divine_sacred_flame" and has_engine_synergy(player, "mortaen_threshold_mercy"):
        return "necrotic"
    return None


def critical_rider(attacker_data: dict, critical: bool, *, rng: random.Random | None) -> tuple[int, str | None]:
    if critical and attacker_data.get("critical_rider"):
        return dice_roll("1d4", rng=rng).total, "lightning"
    return 0, None


def weapon_damage_bonus(attacker_data: dict, critical: bool, *, rng: random.Random | None) -> int:
    if attacker_data.get("weapon_damage_bonus"):
        return dice_roll("2d4" if critical else "1d4", rng=rng).total
    return 0
