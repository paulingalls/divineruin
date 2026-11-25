"""Attack resolution. Zero IO, zero async.

Split from check_resolution.py (resolver-concern split): the d20 success rule
lives in check_resolution._roll_d20_check (the shared SSOT); attack vocab
(hit/critical, crit-doubles-damage, killing-blow) stays here.
resolve_attack accepts an optional `rng` for deterministic testing.
"""

import random
from dataclasses import dataclass

import patron_synergy_combat
import thyra_seasons
from check_resolution import D20CheckCore, D20Roll, roll_bonus_dice
from condition_restrictions import (
    attack_consumed_conditions,
    incoming_advantage,
    incoming_attack_modes,
    incoming_melee_autocrit,
)
from conditions import damage_hp_floor, get_condition_effects
from dice import roll as dice_roll
from dramatic import DramaticContext, evaluate_dramatic_context
from rules_engine import attribute_modifier, proficiency_bonus


@dataclass(frozen=True)
class AttackResult:
    hit: bool
    roll: int
    attack_modifier: int
    attack_total: int
    target_ac: int
    damage: int
    damage_type: str
    target_hp_remaining: int
    target_killed: bool
    narrative_hint: str
    # Excess damage past 0 HP (M4.4 story-002): max(0, damage - pre_hit_hp) on a hit, else 0.
    # target_hp_remaining floors at 0 and loses this, so it's captured here pre-floor — the
    # instant-death verdict (combat_support) compares it against the target's max HP. Defaulted
    # for direct constructors (tests); the resolver always sets it explicitly.
    overkill: int = 0
    critical_success: bool = False
    critical_failure: bool = False
    dramatic: bool = False
    context: str = ""
    # Bonus-damage rider (M4.4 story-008): the necrotic die a Temporary Hollowed attacker adds to a
    # hit, already folded into ``damage``/``overkill``. Surfaced separately so the DM can narrate
    # the necrotic bite. 0/None when the attacker grants no rider or the attack missed.
    bonus_damage: int = 0
    bonus_damage_type: str | None = None
    # Conditions spent by this attack. Downstream removes them even on a miss because the roll
    # consumed their benefit.
    rider_damage: int = 0
    rider_damage_type: str | None = None
    rider_ignores_resistance: bool = False
    consumed_conditions: tuple[str, ...] = ()
    sneak_attack_dice: str | None = None
    sneak_attack_raw_damage: int = 0
    attack_disadvantage_source: str | None = None
    synergy_damage: int = 0
    synergy_damage_type: str | None = None
    synergy_clause_id: str | None = None
    synergy_ac_bonus: int = 0
    synergy_ac_clause_id: str | None = None
    mortaen_ac_bonus: int = 0
    mortaen_ac_clause_id: str | None = None
    war_songs_bonus: int = 0
    war_songs_clause_id: str | None = None


def _is_ranged(weapon: dict) -> bool:
    return bool(weapon.get("ranged") or "ranged" in weapon.get("properties", []))


def weapon_attribute_modifier(player_data: dict, weapon: dict) -> int:
    """The governing-attribute modifier for a weapon (no proficiency).

    Shared source of truth for attribute selection: the attack roll adds this on
    top of proficiency, and damage adds this alone (spec game_mechanics_combat.md
    — proficiency is attack-roll only, the Weapon Damage table adds just the
    attribute modifier).
    """
    attributes = player_data.get("attributes", {})
    governing = weapon.get("governing_attribute")

    if governing:
        # An explicit governing attribute (e.g. a companion's INT spell-attack or a DEX finesse
        # melee, set by companion_attacks_to_action_pool from the attack's hit field) is
        # authoritative — it overrides the melee/ranged/finesse inference below (story-008).
        return attribute_modifier(attributes.get(governing, 10))
    if "finesse" in weapon.get("properties", []):
        str_mod = attribute_modifier(attributes.get("strength", 10))
        dex_mod = attribute_modifier(attributes.get("dexterity", 10))
        return max(str_mod, dex_mod)
    if _is_ranged(weapon):
        return attribute_modifier(attributes.get("dexterity", 10))
    return attribute_modifier(attributes.get("strength", 10))


def attack_modifier(player_data: dict, weapon: dict) -> int:
    level = player_data.get("level", 1)
    return weapon_attribute_modifier(player_data, weapon) + proficiency_bonus(level)


def attack_modes(attacker_data: dict, weapon: dict, target_conditions=()) -> tuple[bool, bool]:
    effects = get_condition_effects(attacker_data.get("conditions") or [])
    incoming_mode_advantage, incoming_disadvantage = incoming_attack_modes(target_conditions, ranged=_is_ranged(weapon))
    disadvantage = (
        "attack" in effects.disadvantage_scopes
        or incoming_disadvantage
        or attacker_data.get("attack_disadvantage_source") is not None
    )
    advantage = (
        weapon.get("advantage") is True
        or "attack" in effects.advantage_scopes
        or incoming_advantage(target_conditions)
        or incoming_mode_advantage
    )
    return advantage, disadvantage


@dataclass(frozen=True)
class PreparedAttack:
    d20: D20Roll
    original: D20CheckCore
    consumed: tuple[str, ...]
    attack_disadvantage_source: str | None = None
    war_songs_bonus: int = 0
    war_songs_clause_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "PreparedAttack":
        return cls(
            D20Roll(**data["d20"]),
            D20CheckCore(**data["original"]),
            tuple(data["consumed"]),
            data.get("attack_disadvantage_source"),
            war_songs_bonus=data.get("war_songs_bonus", 0),
            war_songs_clause_id=data.get("war_songs_clause_id"),
        )


def resolve_attack(
    attacker_data: dict,
    weapon: dict,
    target_ac: int,
    target_hp: int,
    rng: random.Random | None = None,
    attack_mod: int = 0,
    damage_mult: float = 1.0,
    target_conditions: list[dict] | tuple = (),
) -> AttackResult:
    prepared = prepare_attack(attacker_data, weapon, target_ac, rng, attack_mod, target_conditions)
    return finish_attack(
        attacker_data,
        weapon,
        target_ac,
        target_hp,
        prepared,
        prepared.original,
        rng=rng,
        damage_mult=damage_mult,
        target_conditions=target_conditions,
    )


def prepare_attack(
    attacker_data: dict,
    weapon: dict,
    target_ac: int,
    rng: random.Random | None = None,
    attack_mod: int = 0,
    target_conditions: list[dict] | tuple = (),
) -> PreparedAttack:
    # Attacker condition effects (M4.3): Exhausted -1/stack folds into the attack roll,
    # Prone/Blinded etc. impose disadvantage (scope "attack"), Enraged adds +2 damage below.
    # The defender's AC modifier (e.g. Enraged -2 AC) is the caller's concern (combat_support),
    # already baked into target_ac here.
    # ``attack_mod`` / ``damage_mult`` are the encounter-role overlay (M4.7, story-001): a flat
    # to-hit bonus and a damage multiplier the role-derived attacker carries (Elite +1/x1.25,
    # Boss +2/x1.5, Minion x0.75). They default to identity, so the player path is unchanged.
    effects = get_condition_effects(attacker_data.get("conditions") or [])
    if "attack_source" in weapon and weapon["attack_source"] != "catalog":
        raise ValueError("invalid attack_source")
    catalog = weapon.get("attack_source") == "catalog"
    if catalog and type(weapon.get("to_hit")) is not int:
        raise ValueError("catalog attack requires integer to_hit")
    base_modifier = weapon["to_hit"] if catalog else attack_modifier(attacker_data, weapon)
    atk_mod = base_modifier + effects.check_modifier + attack_mod
    attack_advantage, attack_disadvantage = attack_modes(attacker_data, weapon, target_conditions)
    # Freeze beneficial dice in the d20 modifier so a Fate choice reuses their original rolls.
    bonus = roll_bonus_dice(
        effects, "attack", rng=rng, spoken_buffs_eligible=attacker_data.get("spoken_buffs_eligible", True)
    )
    consumed = tuple(
        dict.fromkeys(
            (
                *attack_consumed_conditions(
                    attacker_data.get("conditions") or [],
                    spoken_buffs_eligible=attacker_data.get("spoken_buffs_eligible", True),
                ),
                *bonus.consumed,
            )
        )
    )
    d20 = D20Roll(atk_mod + bonus.total, target_ac, attack_advantage, attack_disadvantage)
    return PreparedAttack(
        d20,
        d20.roll(rng),
        consumed,
        attacker_data.get("attack_disadvantage_source"),
        war_songs_bonus=bonus.war_songs_bonus,
        war_songs_clause_id=patron_synergy_combat.KAELEN_WAR_SONGS if bonus.war_songs_bonus else None,
    )


def finish_attack(
    attacker_data: dict,
    weapon: dict,
    target_ac: int,
    target_hp: int,
    prepared: PreparedAttack,
    core: D20CheckCore,
    *,
    rng: random.Random | None = None,
    damage_mult: float = 1.0,
    target_conditions: list[dict] | tuple = (),
) -> AttackResult:
    effects = get_condition_effects(attacker_data.get("conditions") or [])
    d20 = core.roll
    attack_total = core.total
    expanded = patron_synergy_combat.expanded_critical(attacker_data, d20)
    hit = core.success or expanded
    critical = (
        core.critical_success
        or expanded
        or (hit and incoming_melee_autocrit(target_conditions) and not _is_ranged(weapon))
    )

    damage = 0
    damage_type = attacker_data.get("damage_type_override", weapon.get("damage_type", "bludgeoning"))
    bonus_damage = 0
    bonus_damage_type: str | None = None

    rider_damage = 0
    rider_damage_type = None
    rider_ignores_resistance = False
    sneak_attack_dice = None
    sneak_attack_raw_damage = 0
    synergy_damage, synergy_damage_type = 0, None
    synergy_clause_id = None
    veiled_strike = attacker_data.get("veiled_strike")
    if hit:
        season = attacker_data.get("season")
        damage_notation = weapon.get("damage", "1d4")
        if damage_notation != "0":
            damage = dice_roll(damage_notation, rng=rng).total
            if critical:
                damage += dice_roll(damage_notation, rng=rng).total
            damage += thyra_seasons.damage_bonus(attacker_data, season, damage_type)
        damage += patron_synergy_combat.weapon_damage_bonus(attacker_data, critical, rng=rng)
        if weapon.get("attack_source") != "catalog" and weapon.get("damage_attribute", True) and damage_notation != "0":
            damage += weapon_attribute_modifier(attacker_data, weapon)
        if attacker_data.get("sneak_attack_available") and (
            (prepared.d20.advantage and not prepared.d20.disadvantage)
            or attacker_data.get("sneak_attack_adjacent_ally")
        ):
            count = 1 + (attacker_data.get("level", 1) - 1) // 4
            if veiled_strike == "sneak_attack":
                count += 1
                synergy_clause_id = patron_synergy_combat.VEILED_STRIKE
            sneak_attack_dice = f"{count * (2 if critical else 1)}d6"
            sneak_attack_raw_damage = dice_roll(sneak_attack_dice, rng=rng).total
            damage += sneak_attack_raw_damage
        # Condition damage modifier (M4.3): Enraged adds +2 damage. Applied once, like
        # the attribute mod, before the floor.
        damage += effects.damage_modifier
        # Bonus-damage rider die (M4.4 story-008): a Temporary Hollowed attacker adds 1d6 necrotic.
        # Rolled here — after weapon damage so a fixed-seed weapon roll is unchanged by the rider —
        # and added before the floor so it counts toward overkill below. Surfaced separately too.
        if effects.bonus_damage_dice is not None:
            bonus_damage = dice_roll(effects.bonus_damage_dice, rng=rng).total
            bonus_damage_type = effects.bonus_damage_type
            damage += bonus_damage
        if count := weapon.get("devastating_strike_dice"):
            damage += dice_roll(f"{count * (2 if critical else 1)}d8", rng=rng).total
        authored_bonus = weapon.get("bonus_damage")
        if authored_bonus is not None:
            if effects.bonus_damage_dice is not None:
                raise ValueError("multiple bonus damage sources")
            bonus_damage = dice_roll(authored_bonus["dice"], rng=rng).total
            bonus_damage_type = authored_bonus["damage_type"]
            damage += bonus_damage
        on_hit = weapon.get("prepared_on_hit")
        if on_hit is not None and "damage" in on_hit:
            rider_damage = dice_roll(on_hit["damage"], rng=rng).total
            rider_damage_type = on_hit["damage_type"]
            rider_ignores_resistance = on_hit["ignores_resistance"]
            damage += rider_damage
        if veiled_strike == "weapon":
            synergy_clause_id = patron_synergy_combat.VEILED_STRIKE
            synergy_damage = dice_roll("2d6" if critical else "1d6", rng=rng).total
            synergy_damage_type = damage_type
        elif (encounter_clause := attacker_data.get("encounter_damage_clause")) is not None:
            synergy_clause_id = encounter_clause
            synergy_damage, synergy_damage_type = 1, damage_type
        elif attacker_data.get("outnumbered_oath"):
            synergy_clause_id = patron_synergy_combat.OATH_OF_VALOR
            synergy_damage, synergy_damage_type = patron_synergy_combat.outnumbered_rider(critical, rng=rng)
        else:
            synergy_damage, synergy_damage_type = patron_synergy_combat.critical_rider(attacker_data, critical, rng=rng)
            synergy_damage += thyra_seasons.damage_bonus(attacker_data, season, synergy_damage_type)
        damage += synergy_damage
        synergy_damage = int(synergy_damage * damage_mult)
        bonus_damage = int(bonus_damage * damage_mult)
        rider_damage = int(rider_damage * damage_mult)
        # Role damage multiplier (M4.7, story-001): scale the FINAL accumulated total (weapon +
        # crit + attribute + condition + rider) before the floor, so overkill below is computed
        # from the scaled number and instant-death/never-heal semantics still hold.
        damage = int(damage * damage_mult)
        # Floor at 0: a low-attribute attacker (e.g. STR 1 → -5) rolling low must
        # never produce negative damage, which would HEAL the target via the
        # max(0, hp - damage) below. A hit deals at least 0.
        damage = max(0, damage)

    new_hp = max(damage_hp_floor(target_conditions), target_hp - damage)
    killed = hit and new_hp == 0
    overkill = max(0, damage - target_hp) if killed else 0
    verdict = evaluate_dramatic_context(
        DramaticContext(
            raw_die=d20,
            roll_type="attack",
            target_hp_remaining=target_hp if killed else None,
            damage_potential=damage if hit else None,
        )
    )

    return AttackResult(
        hit=hit,
        roll=d20,
        attack_modifier=prepared.d20.modifier,
        attack_total=attack_total,
        target_ac=target_ac,
        damage=damage,
        damage_type=damage_type,
        critical_success=critical,
        critical_failure=core.critical_failure,
        target_hp_remaining=new_hp,
        target_killed=killed,
        overkill=overkill,
        narrative_hint="critical success" if expanded else core.narrative_hint,
        dramatic=expanded or verdict.dramatic,
        context="critical_hit" if expanded else verdict.context,
        bonus_damage=bonus_damage,
        bonus_damage_type=bonus_damage_type,
        rider_damage=rider_damage,
        rider_damage_type=rider_damage_type,
        rider_ignores_resistance=rider_ignores_resistance,
        consumed_conditions=prepared.consumed,
        sneak_attack_dice=sneak_attack_dice,
        sneak_attack_raw_damage=sneak_attack_raw_damage,
        attack_disadvantage_source=prepared.attack_disadvantage_source,
        synergy_damage=synergy_damage,
        synergy_damage_type=synergy_damage_type,
        synergy_clause_id=synergy_clause_id,
        synergy_ac_bonus=attacker_data.get("synergy_ac_bonus", 0),
        synergy_ac_clause_id=attacker_data.get("synergy_ac_clause_id"),
        mortaen_ac_bonus=attacker_data.get("mortaen_ac_bonus", 0),
        mortaen_ac_clause_id=attacker_data.get("mortaen_ac_clause_id"),
        war_songs_bonus=prepared.war_songs_bonus,
        war_songs_clause_id=prepared.war_songs_clause_id,
    )
