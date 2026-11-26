"""Authoritative patron selection and combat synergy effects."""

from __future__ import annotations

import random
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Literal

import encounter_facts
from dice import roll as dice_roll
from patron_synergy import has_engine_synergy

if TYPE_CHECKING:
    from combat_participant import CombatParticipant
    from combat_state import CombatState

OATH_OF_VALOR = "kaelen_oath_of_valor"
SECOND_BEFORE = "zhael_second_before"
ORENTHEL_GUARDIAN_WARD = "orenthel_guardian_ward"
ORENTHEL_UNDEAD_WRATH = "orenthel_undead_wrath"
MORTAEN_THRESHOLD_SHIELD = "mortaen_threshold_shield"
MORTAEN_HOLD_THE_CROSSING = "mortaen_hold_the_crossing"
NYTHERA_SALTWIND_CASTING = "nythera_saltwind_casting"

KAELEN_WAR_SONGS = "kaelen_war_songs"
TWO_ROUND_VEIL = "syrath_two_round_veil"
VEILED_STRIKE = "syrath_veiled_strike"

VeiledStrike = Literal["sneak_attack", "weapon"]


def shadow_veil_rounds(player: dict) -> int:
    return 2 if has_engine_synergy(player, TWO_ROUND_VEIL) else 1


def veiled_strike(player: dict) -> VeiledStrike | None:
    if has_engine_synergy(player, VEILED_STRIKE):
        return "sneak_attack" if player["class"] == "rogue" else "weapon"
    return None


def inspire_attack_upgrade(player: dict) -> bool:
    return has_engine_synergy(player, KAELEN_WAR_SONGS)


async def attack_player(participant, *, queries, conn) -> dict | None:
    if participant.type not in ("player", "temporary_hollowed"):
        return None
    player = await queries.get_player(participant.id, conn=conn)
    if player is None:
        raise RuntimeError(f"Attack participant {participant.id!r} has no player row")
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
    from combat_veilrender import living
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
    if (
        has_engine_synergy(player, ORENTHEL_UNDEAD_WRATH)
        and (target.hollow or target.category == "undead")
        and any(
            ally.id != attacker.id and ally.is_ally and living(ally) and 2 * ally.hp_current < ally.hp_max
            for ally in state.participants
        )
    ):
        return ORENTHEL_UNDEAD_WRATH
    return None


def first_attack_defense(defender: dict | None, state: CombatState | None, target: CombatParticipant) -> int:
    if (
        defender is not None
        and state is not None
        and target.id not in state.encounter_facts["attacked"]
        and has_engine_synergy(defender, SECOND_BEFORE)
    ):
        return 1
    return 0


def fallen_ally_defense(defender: dict | None, state: CombatState | None, target: CombatParticipant) -> int:
    from combat_down import is_terminally_down
    from combat_veilrender import living

    if (
        defender is None
        or state is None
        or not living(target)
        or not has_engine_synergy(defender, MORTAEN_THRESHOLD_SHIELD)
    ):
        return 0
    return int(
        any(
            ally.is_ally and ally.hp_current == 0 and ally.is_fallen and not is_terminally_down(ally)
            for ally in state.participants
        )
    )


def wounded_ally_defense(defender: dict | None, state: CombatState | None, target: CombatParticipant) -> int:
    from combat_spatial import inside, position, require_spatial
    from combat_veilrender import living

    if (
        defender is None
        or state is None
        or not living(target)
        or not has_engine_synergy(defender, ORENTHEL_GUARDIAN_WARD)
    ):
        return 0

    spatial = require_spatial(state)
    target_position = position(spatial, target.id)
    return int(
        any(
            ally.id != target.id
            and ally.is_ally
            and living(ally)
            and 2 * ally.hp_current < ally.hp_max
            and inside(target_position, position(spatial, ally.id), 5)
            for ally in state.participants
        )
    )


async def marshal_death_save_bonus(state: CombatState, *, queries) -> int:
    from combat_veilrender import living

    for candidate in state.participants:
        if candidate.type != "player" or not living(candidate):
            continue
        player = await queries.get_player(candidate.id)
        if player is None:
            raise RuntimeError(f"Death save ally {candidate.id!r} has no player row")
        if has_engine_synergy(player, MORTAEN_HOLD_THE_CROSSING):
            return 1
    return 0


async def preflight_tidal_step(state: CombatState, *, get_player: Callable[[str], Awaitable[dict | None]]) -> None:
    spent = state.encounter_facts["once_spent"].get(encounter_facts.NYTHERA_TIDAL_STEP, ())
    for actor_id, declaration in state.pending_declarations.items():
        if not declaration.get("nythera_step"):
            continue
        player = await get_player(actor_id)
        if player is None:
            raise ValueError(f"Nythera's Unmoored Step: {actor_id} has no player row.")
        actor = state.get_participant(actor_id)
        assert actor is not None
        if actor.type != "player":
            raise ValueError("Nythera's Unmoored Step requires a player combatant.")
        if not has_engine_synergy(player, encounter_facts.NYTHERA_TIDAL_STEP):
            raise ValueError("Nythera's Unmoored Step requires a Nythera skirmisher or rogue.")
        if actor_id in spent:
            raise ValueError("Nythera's Unmoored Step is already spent in this encounter.")


def spend_tidal_step(state: CombatState, actor_id: str) -> dict[str, str | bool]:
    spent = state.encounter_facts["once_spent"].setdefault(encounter_facts.NYTHERA_TIDAL_STEP, [])
    if actor_id in spent:
        raise RuntimeError(f"Nythera's Unmoored Step was already spent by {actor_id}.")
    spent.append(actor_id)
    return {
        "synergy_clause_id": encounter_facts.NYTHERA_TIDAL_STEP,
        "nythera_step_spent": True,
        "dm_cue": "Nythera's Unmoored Step is spent for this encounter.",
    }


async def grant_marshal_rally(
    state: CombatState, marshal_id: str, ally_id: str, *, queries, conn
) -> dict[str, str | int] | None:
    ally = state.get_participant(ally_id)
    if ally is None or not ally.is_ally or ally_id == marshal_id:
        return None
    spent = state.encounter_facts["once_spent"]
    if marshal_id in spent.get(encounter_facts.ZHAEL_RALLY, ()):
        return None
    player = await queries.get_player(marshal_id, conn=conn)
    if player is None:
        raise RuntimeError(f"Marshal {marshal_id!r} has no player row")
    if not has_engine_synergy(player, encounter_facts.ZHAEL_RALLY):
        return None
    spent.setdefault(encounter_facts.ZHAEL_RALLY, []).append(marshal_id)
    state.encounter_facts["rally_pending"][marshal_id] = ally_id
    return encounter_facts.rally_entry(marshal_id, ally_id)


async def grant_interceding_rallies(state: CombatState, packets: list[dict], ally_id: str, *, queries, conn) -> None:
    for packet in packets:
        if packet["ability_id"] == "marshal_interceding_order" and packet["mechanical_effect"] == "target_ac_bonus":
            grant = await grant_marshal_rally(state, packet["actor_id"], ally_id, queries=queries, conn=conn)
            if grant is not None:
                packet["rally_grant"] = grant


def outnumbered_oath(player: dict, state: CombatState | None, attacker: CombatParticipant) -> bool:
    if state is None or not attacker.is_ally or not has_engine_synergy(player, OATH_OF_VALOR):
        return False

    from combat_veilrender import living

    allies = enemies = 0
    for participant in state.participants:
        if living(participant):
            if participant.is_ally:
                allies += 1
            else:
                enemies += 1
    return enemies > allies


def expanded_critical(attacker_data: dict, face: int) -> bool:
    return bool(attacker_data.get("expanded_critical")) and face == 19


def spell_attack_bonus(player: dict, target) -> int:
    return int(target.category == "undead" and has_engine_synergy(player, "mortaen_ashen_formula"))


def saltwind_casting_bonus(player: dict, *, coastal: bool) -> int:
    return int(coastal and has_engine_synergy(player, NYTHERA_SALTWIND_CASTING))


def spell_damage_type_override(player: dict, spell_id: str) -> str | None:
    if spell_id == "divine_sacred_flame" and has_engine_synergy(player, "mortaen_threshold_mercy"):
        return "necrotic"
    return None


def critical_rider(attacker_data: dict, critical: bool, *, rng: random.Random | None) -> tuple[int, str | None]:
    if critical and attacker_data.get("critical_rider"):
        return dice_roll("1d4", rng=rng).total, "lightning"
    return 0, None


def outnumbered_rider(critical: bool, *, rng: random.Random | None) -> tuple[int, str]:
    return dice_roll("2d6" if critical else "1d6", rng=rng).total, "radiant"


def weapon_damage_bonus(attacker_data: dict, critical: bool, *, rng: random.Random | None) -> int:
    if attacker_data.get("weapon_damage_bonus"):
        return dice_roll("2d4" if critical else "1d4", rng=rng).total
    return 0
