"""Patron effects for healing."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import ModuleType
from typing import TYPE_CHECKING, TypedDict

import asyncpg

import db_queries
import dice
import temp_hp
from condition_catalog import CONDITION_CATALOG
from healing_dice import shared_roll
from patron_synergy import has_engine_synergy
from rules_engine import attribute_modifier
from terrain import is_natural

if TYPE_CHECKING:
    from combat_participant import CombatParticipant
    from combat_spell_profile import HealProfile
    from encounter_facts import EncounterFacts
    from session_data import CombatState
    from spells import Spell

DAWNS_MERCY = "orenthel_dawns_mercy"
THRESHOLD_HEALING = "mortaen_threshold_healing"
FINAL_MERCY = "mortaen_final_mercy"
VERDANT_HEALING = "thyra_verdant_healing"
TRAVELERS_BLESSING = "nythera_travelers_blessing"
APPOINTED_MERCY = "zhael_appointed_mercy"
CLEANSING_TOUCH = "orenthel_cleansing_touch"
INSPIRE_HEAL = "orenthel_inspire_heal"
INSPIRE = "bard_inspire"
MAGE_WARDING = "orenthel_mage_warding"


def mage_warding_spell(spell: Spell) -> bool:
    return not spell.hostile and spell.combat_aid


async def grant_mage_warding(
    caster: dict,
    recipient_ids: list[str],
    *,
    conn: asyncpg.Connection,
    rows: dict[str, dict] | None = None,
    participants: dict[str, CombatParticipant] | None = None,
    queries: ModuleType = db_queries,
) -> dict | None:
    if not recipient_ids or not has_engine_synergy(caster, MAGE_WARDING):
        return None
    if rows is None:
        assert participants is not None
        recipient_rows: dict[str, dict] = await queries.get_players_for_update(
            [pid for pid in recipient_ids if participants[pid].type == "player"], conn=conn
        )
    else:
        recipient_rows = rows
    recipients = []
    for pid in recipient_ids:
        participant = participants[pid] if participants is not None else None
        if participant is not None and participant.type != "player":
            before = participant.temp_hp
            participant.temp_hp = after = max(before, 1)
        else:
            before, after = await temp_hp.grant(pid, recipient_rows[pid], 1, participant=participant, conn=conn)
        recipients.append({"recipient_id": pid, "granted": after - before, "temp_hp": after})
    return {"id": MAGE_WARDING, "name": "Renewing Spark", "recipients": recipients}


def require_inspire_heal(player: dict) -> None:
    if not has_engine_synergy(player, INSPIRE_HEAL):
        raise ValueError("Inspire healing requires an Orenthel bard.")


async def preflight_inspire_heal(state: CombatState, *, get_player: Callable[[str], Awaitable[dict | None]]) -> None:
    for actor_id, declaration in state.pending_declarations.items():
        if declaration.get("type") != "ability" or declaration.get("action") != INSPIRE_HEAL:
            continue
        actor = state.get_participant(actor_id)
        assert actor is not None
        player = await get_player(actor_id)
        if player is None:
            raise ValueError(f"Inspire healing requires a player row for {actor_id}.")
        require_inspire_heal(player)


def inspire_heal() -> HealProfile:
    die = CONDITION_CATALOG["inspired"].bonus_die
    assert die is not None
    return {"dice": die, "recipients": "single"}


class HealBonus(TypedDict):
    id: str
    bonus: int


class ResonanceRemoval(TypedDict):
    id: str
    resonance_removed: int


HealComponent = HealBonus | ResonanceRemoval
HealSynergy = Callable[[str, int, int, bool], list[HealComponent]]


def for_cast(
    player: dict,
    spell_id: str,
    *,
    terrain: str | None,
    first_stay: bool,
    facts: EncounterFacts | None = None,
    round_number: int | None = None,
    dice_mod=dice,
) -> HealSynergy:
    shared: list[HealComponent] = []
    if spell_id == "primal_healing_touch" and has_engine_synergy(player, CLEANSING_TOUCH):
        shared.append({"id": CLEANSING_TOUCH, "resonance_removed": 1})
    verdant_roll = None
    if has_engine_synergy(player, VERDANT_HEALING):
        if terrain is None:
            raise RuntimeError("Verdant Healing requires resolved cast terrain")
        if is_natural(terrain):
            verdant_roll = shared_roll("1d4", dice_mod.roll)
    if first_stay and has_engine_synergy(player, TRAVELERS_BLESSING):
        shared.append({"id": TRAVELERS_BLESSING, "bonus": 1})
    savers = set()
    if facts is not None and has_engine_synergy(player, APPOINTED_MERCY):
        savers = {pid for pid, saved_round in facts["death_save_success_round"].items() if saved_round == round_number}

    def effects(recipient_id: str, before: int, base: int, maximized: bool) -> list[HealComponent]:
        components = list(shared)
        if verdant_roll is not None:
            components.append({"id": VERDANT_HEALING, "bonus": verdant_roll(maximized)})
        components.extend(bonus_components(player, before, base))
        if recipient_id in savers:
            components.append({"id": APPOINTED_MERCY, "bonus": 1})
        return components

    return effects


def bonus_components(player: dict, hp_before: int, base_heal: int) -> list[HealBonus]:
    if has_engine_synergy(player, DAWNS_MERCY):
        attributes = player["attributes"]
        amount = max(0, attribute_modifier(attributes["wisdom"]), attribute_modifier(attributes["charisma"]))
        return [{"id": DAWNS_MERCY, "bonus": amount}] if amount else []
    if hp_before == 0:
        if base_heal > 0 and has_engine_synergy(player, THRESHOLD_HEALING):
            return [{"id": THRESHOLD_HEALING, "bonus": base_heal}]
        if has_engine_synergy(player, FINAL_MERCY):
            return [{"id": FINAL_MERCY, "bonus": 1}]
    return []
