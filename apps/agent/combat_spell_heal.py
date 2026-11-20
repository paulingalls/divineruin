"""Direct spell healing for working combat snapshots and locked exploration rows."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

import db_mutations
import dice
import patron_passives
from combat_down import is_terminally_down, revive
from combat_enemy_active import heal, healed_hp
from combat_structures import line_blocker
from conditions import apply_condition
from rules_engine import attribute_modifier
from spells import normalize_target_list

if TYPE_CHECKING:
    from combat_spell_profile import HealProfile
    from declarations import Declaration
    from session_data import CombatParticipant, CombatState
    from spells import Spell


class HpChange(TypedDict):
    healed: int
    hp_current: int
    hp_max: int


class HealingResult(HpChange):
    target_id: str
    rolled: int
    modifier: int


class GiftReceipt(HpChange):
    id: str
    name: str
    target_ids: list[str]


def _explicit_targets(
    spell: Spell, profile: HealProfile, caster_id: str, target_id: str | None, target_ids: list[str] | None
) -> list[str]:
    if profile["recipients"] == "all_allies":
        if target_id is not None or target_ids is not None:
            raise ValueError(f"{spell.name} selects its allies automatically")
        return []
    if target_ids is not None:
        if profile["recipients"] == "single":
            raise ValueError(f"{spell.name} heals one recipient; use a single target")
        return normalize_target_list(spell, target_id, target_ids)
    return [target_id if target_id is not None else caster_id]


def combat_recipients(
    state: CombatState, caster: CombatParticipant, declaration: Declaration, spell: Spell, profile: HealProfile
) -> list[CombatParticipant]:
    if profile.get("out_of_combat_only"):
        raise ValueError(f"{spell.name} can only be cast outside combat")
    targets = _explicit_targets(spell, profile, caster.id, declaration.target_id, declaration.target_ids)
    if profile["recipients"] == "all_allies":
        return [
            p
            for p in state.participants
            if p.is_ally and not is_terminally_down(p) and line_blocker(state, caster.id, p.id) is None
        ]
    return [combat_ally(state, tid, spell.name) for tid in targets]


def combat_ally(state: CombatState, target_id: str, source_name: str) -> CombatParticipant:
    target = state.get_participant(target_id)
    if target is None or not target.is_ally:
        raise ValueError(f"{source_name} requires an ally in the fight: {target_id}")
    if is_terminally_down(target):
        raise ValueError(f"{source_name} cannot heal a dead ally: {target_id}")
    return target


def exploration_recipients(
    spell: Spell,
    profile: HealProfile,
    caster_id: str,
    caster: dict,
    target_id: str | None,
    target_ids: list[str] | None,
    locked_rows: dict[str, dict],
) -> dict[str, dict]:
    targets = _explicit_targets(spell, profile, caster_id, target_id, target_ids)
    location = caster["location_id"]
    present = {pid: row for pid, row in locked_rows.items() if row["location_id"] == location}
    if profile["recipients"] == "all_allies":
        return present
    for tid in targets:
        if tid not in present:
            raise ValueError(f"{spell.name} requires a present party player: {tid}")
    return {tid: present[tid] for tid in targets}


def _healing_roll(profile: HealProfile, attributes: dict[str, int], dice_mod) -> tuple[int, int]:
    rolled = dice_mod.roll(profile["dice"]).total
    attribute = profile.get("attribute")
    modifier = attribute_modifier(attributes.get(attribute, 10)) if attribute is not None else 0
    return rolled, modifier


def _receipt(target_id: str, before: int, hp: int, maximum: int, rolled: int, modifier: int) -> HealingResult:
    return {
        "target_id": target_id,
        "rolled": rolled,
        "modifier": modifier,
        "healed": max(0, hp - before),
        "hp_current": hp,
        "hp_max": maximum,
    }


async def restore(target: CombatParticipant, amount: int, *, conn, mutations=db_mutations) -> int:
    restored = heal(target, amount)
    if target.is_fallen and restored > 0:
        revive(target, target.hp_current)
    if restored and target.type == "player":
        await mutations.update_player_hp(target.id, target.hp_current, conn=conn)
    return restored


def _gift_receipt(
    caster_id: str, caster_row: dict, current: int, maximum: int, results: list[HealingResult]
) -> GiftReceipt | None:
    targets = list(dict.fromkeys(r["target_id"] for r in results if r["healed"] > 0 and r["target_id"] != caster_id))
    if not targets or current >= maximum or (gift := patron_passives.dawns_resilience(caster_row)) is None:
        return None
    hp = healed_hp(current, maximum, 2 * len(targets))
    return {
        "id": gift["id"],
        "name": gift["name"],
        "target_ids": targets,
        "healed": hp - current,
        "hp_current": hp,
        "hp_max": maximum,
    }


def hp_updates(caster_id: str, packet: dict) -> dict[str, HpChange]:
    updates = {r["target_id"]: r for r in packet["healing_results"] if r["healed"] > 0}
    if gift := packet.get("gift_triggered"):
        updates[caster_id] = gift
    return updates


async def land(
    profile: HealProfile,
    caster: CombatParticipant,
    recipients: list[CombatParticipant],
    *,
    caster_row: dict,
    packet: dict,
    conn,
) -> list[HealingResult]:
    rolled, modifier = _healing_roll(profile, caster.attributes, dice)
    results = []
    for target in recipients:
        before = target.hp_current
        await restore(target, rolled + modifier, conn=conn)
        if rounds := profile.get("regeneration_rounds"):
            target.conditions = apply_condition(target.conditions, "regenerating", source=caster.id)
            for condition in target.conditions:
                if condition["type"] == "regenerating":
                    condition["ticks_remaining"] = rounds
        results.append(_receipt(target.id, before, target.hp_current, target.hp_max, rolled, modifier))
    gift = _gift_receipt(caster.id, caster_row, caster.hp_current, caster.hp_max, results)
    if gift is not None:
        await restore(caster, gift["healed"], conn=conn)
        packet["gift_triggered"] = gift
    return results


async def land_exploration(
    profile: HealProfile, caster: dict, recipients: dict[str, dict], *, caster_id: str, packet: dict, conn, dice_mod
) -> list[HealingResult]:
    rolled, modifier = _healing_roll(profile, caster.get("attributes", {}), dice_mod)
    caster_current = caster["hp"]["current"]
    results = []
    for pid, row in recipients.items():
        current = row["hp"]["current"]
        maximum = patron_passives.effective_hp(row)["max"]
        hp = healed_hp(current, maximum, rolled + modifier + profile.get("regeneration_rounds", 0))
        if hp != current:
            await db_mutations.update_player_hp(pid, hp, conn=conn)
        results.append(_receipt(pid, current, hp, maximum, rolled, modifier))
        if pid == caster_id:
            caster_current = hp
    gift = _gift_receipt(caster_id, caster, caster_current, patron_passives.effective_hp(caster)["max"], results)
    if gift is not None:
        await db_mutations.update_player_hp(caster_id, gift["hp_current"], conn=conn)
        packet["gift_triggered"] = gift
    return results
