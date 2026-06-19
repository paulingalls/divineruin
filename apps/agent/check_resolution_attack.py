"""Attack resolution. Zero IO, zero async.

Split from check_resolution.py (resolver-concern split): the d20 success rule
lives in check_resolution._roll_d20_check (the shared SSOT); attack vocab
(hit/critical, crit-doubles-damage, killing-blow) stays here.
resolve_attack accepts an optional `rng` for deterministic testing.
"""

import random
from dataclasses import dataclass

from check_resolution import _roll_d20_check
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
    # Crit flags read from D20CheckCore.critical_success/critical_failure (nat-20 /
    # nat-1), so every roll-result packet agrees on crits. Defaulted for direct
    # constructors (tests); the resolver always sets them explicitly.
    critical_success: bool = False
    critical_failure: bool = False
    # Intrinsic dramatic-dice verdict (M4.5): nat-20/nat-1 or killing_blow. The
    # killing-blow inputs are gated on `hit` in resolve_attack, so this label
    # equals target_killed by construction. Defaulted + appended so story-004
    # encounter-context signals stay additive. See dramatic.py.
    dramatic: bool = False
    context: str = ""


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
    if weapon.get("ranged", False):
        return attribute_modifier(attributes.get("dexterity", 10))
    return attribute_modifier(attributes.get("strength", 10))


def attack_modifier(player_data: dict, weapon: dict) -> int:
    level = player_data.get("level", 1)
    return weapon_attribute_modifier(player_data, weapon) + proficiency_bonus(level)


def resolve_attack(
    attacker_data: dict,
    weapon: dict,
    target_ac: int,
    target_hp: int,
    rng: random.Random | None = None,
) -> AttackResult:
    atk_mod = attack_modifier(attacker_data, weapon)
    # Attack uses the same d20+mod-vs-target rule as skill checks/saves: nat-20
    # always hits, nat-1 always misses, else total >= AC. Route through the shared
    # primitive (target_ac is the attack-side DC) so the rule can't drift; attack
    # vocab (hit/critical) and the crit-doubles-damage side-effect stay here.
    core = _roll_d20_check(mod=atk_mod, dc=target_ac, rng=rng)
    d20 = core.roll
    attack_total = core.total
    hit = core.success
    critical = core.critical_success

    damage = 0
    damage_type = weapon.get("damage_type", "bludgeoning")

    if hit:
        damage_notation = weapon.get("damage", "1d4")
        damage_result = dice_roll(damage_notation, rng=rng)
        damage = damage_result.total
        if critical:
            crit_result = dice_roll(damage_notation, rng=rng)
            damage += crit_result.total
        # Damage adds the governing-attribute modifier once (even on a crit),
        # never proficiency (spec: proficiency is attack-roll only).
        damage += weapon_attribute_modifier(attacker_data, weapon)
        # Floor at 0: a low-attribute attacker (e.g. STR 1 → -5) rolling low must
        # never produce negative damage, which would HEAL the target via the
        # max(0, hp - damage) below. A hit deals at least 0.
        damage = max(0, damage)

    new_hp = max(0, target_hp - damage)

    # Killing-blow inputs are gated on `hit`: pass pre-hit HP + damage only when
    # the attack landed, else None. This makes the evaluator's killing_blow label
    # equal target_killed BY CONSTRUCTION (both derive from hit + pre-hit-HP +
    # damage), so they can never diverge — the evaluator can't fire on a miss.
    verdict = evaluate_dramatic_context(
        DramaticContext(
            raw_die=d20,
            roll_type="attack",
            target_hp_remaining=target_hp if hit else None,
            damage_potential=damage if hit else None,
        )
    )

    return AttackResult(
        hit=hit,
        roll=d20,
        attack_modifier=atk_mod,
        attack_total=attack_total,
        target_ac=target_ac,
        damage=damage,
        damage_type=damage_type,
        critical_success=core.critical_success,
        critical_failure=core.critical_failure,
        target_hp_remaining=new_hp,
        target_killed=new_hp == 0 and hit,
        narrative_hint=core.narrative_hint,
        dramatic=verdict.dramatic,
        context=verdict.context,
    )
