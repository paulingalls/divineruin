"""Pure encounter-role overlay — the SSOT for the 5-role stat-modifier system (M4.7, story-001).

A base creature stat block plus an assigned encounter role yields a derived stat block: the same
Bandit is a throwaway Minion (half HP, no special abilities) or a climactic Boss (double HP, a
signature ability, one legendary action per round). This module is the single deterministic source
for *what a role does to a stat block* (``ROLE_MODIFIERS``) and the pure ``derive_role_stats``
function that applies it. It is pure: it reads only its arguments, never touches IO/RNG/DB, and
returns a NEW dict — it never mutates its input (mirroring companion_scaling.py's copy-not-mutate
discipline).

``ROLE_MODIFIERS`` is read read-only by the other M4.7 stories: loot/currency (story-002),
legendary-action runtime + XP multiplier (story-003), and encounter budget (story-004). They
consume the table and the participant's ``role`` field; only this module owns the table.

Numbers come from docs/game_mechanics/game_mechanics_encounter_roles.md — the ``ROLE_MODIFIERS``
dict + ``derive_role_stats`` pseudocode (L656-716), the modifier table (L69-79), and decisions
D73-D81 (L770-791).

Honest scope notes:
- Damage is a MULTIPLIER (``damage_mult``) applied to the final rolled total at resolution
  (check_resolution_attack.resolve_attack), NOT a dice-notation rewrite. The doc's curated example
  dice (1d6+2 -> 1d4+1) are illustrative; the deterministic engine scales the rolled number.
- ``enhance_abilities`` tags each active ability ``enhanced`` (and bumps a ``uses`` field where one
  exists). Today's action dicts carry no frequency/uses field, so this is largely a marker until
  richer per-ability enhancement content lands; the live Elite/Boss power comes from the HP/AC/
  attack/dc/damage/xp deltas.
- Boss ``signature_ability`` is AUTHORED content on the template enemy (not generated here);
  derivation attaches it and sets ``legendary_actions=1``. The signature's in-combat firing and the
  legendary-action runtime are story-003 — this story only scaffolds the fields.
- The doc's Boss "proficient saves +1" (the boss's OWN saves) has no structured home on the enemy
  dict and is rarely exercised; it is deferred. ``dc_mod`` covers the common case — a Boss ability
  is harder for its TARGET to resist.
"""

import math
from dataclasses import dataclass
from enum import StrEnum


class EncounterRole(StrEnum):
    MINION = "minion"
    STANDARD = "standard"
    ELITE = "elite"
    BOSS = "boss"
    NAMED = "named"


@dataclass(frozen=True)
class RoleMod:
    """The per-role modifier set (the ``ROLE_MODIFIERS`` value).

    ``hp_round`` selects the HP rounding direction ("down" for Minion, "up" for Elite, "exact" for
    Boss whose 2.0 is already integral). ``budget_cost`` is the story-004 encounter-budget weight,
    carried here so the role table stays the single source of truth.
    """

    hp_mult: float
    ac_mod: int
    damage_mult: float
    attack_mod: int
    dc_mod: int
    xp_mult: float
    budget_cost: float
    hp_round: str = "exact"


# The four derivable roles. STANDARD/NAMED short-circuit to identity in derive_role_stats and need
# no row (STANDARD is listed for budget_cost + as an explicit identity anchor for consumers).
ROLE_MODIFIERS: dict[str, RoleMod] = {
    EncounterRole.MINION: RoleMod(
        hp_mult=0.5,
        ac_mod=-1,
        damage_mult=0.75,
        attack_mod=0,
        dc_mod=-1,
        xp_mult=0.5,
        budget_cost=0.5,
        hp_round="down",
    ),
    EncounterRole.STANDARD: RoleMod(
        hp_mult=1.0,
        ac_mod=0,
        damage_mult=1.0,
        attack_mod=0,
        dc_mod=0,
        xp_mult=1.0,
        budget_cost=1.0,
    ),
    EncounterRole.ELITE: RoleMod(
        hp_mult=1.5,
        ac_mod=1,
        damage_mult=1.25,
        attack_mod=1,
        dc_mod=1,
        xp_mult=1.5,
        budget_cost=2.0,
        hp_round="up",
    ),
    EncounterRole.BOSS: RoleMod(
        hp_mult=2.0,
        ac_mod=2,
        damage_mult=1.5,
        attack_mod=2,
        dc_mod=2,
        xp_mult=2.0,
        budget_cost=4.0,
    ),
}

# Action-pool ``properties`` markers that make an action an ACTIVE ABILITY rather than a basic
# attack. Minions strip these (D74: "Minions attack. That's it."); Elites/Bosses enhance them.
_ACTIVE_PROPERTY_MARKERS = frozenset({"buff", "debuff", "aoe", "healing", "control"})


def _is_active_ability(action: dict) -> bool:
    """An action is an active ability (vs. a basic weapon attack) when it deals no direct damage
    (``damage`` falsy or "0"/"0d0") or carries an active-effect property marker."""
    damage = str(action.get("damage", "")).strip()
    if damage in ("", "0", "0d0"):
        return True
    return bool(_ACTIVE_PROPERTY_MARKERS.intersection(action.get("properties", []) or []))


def _apply_hp(base_hp: int, mod: RoleMod) -> int:
    scaled = base_hp * mod.hp_mult
    if mod.hp_round == "down":
        return max(1, math.floor(scaled))
    if mod.hp_round == "up":
        return math.ceil(scaled)
    if mod.hp_round == "exact":
        return int(scaled)
    raise ValueError(f"Unknown hp_round {mod.hp_round!r}; valid values are 'down', 'up', 'exact'")


def enhance_abilities(actives: list[dict]) -> list[dict]:
    """Return enhanced copies of each active ability (Elite/Boss, D75).

    Marks each active ``enhanced`` and bumps a ``uses`` count where one exists (frequency increase
    per the Elite Enhancement Rules). Pure: copies each dict, never mutates the input.
    """
    enhanced: list[dict] = []
    for active in actives:
        copy = dict(active)
        copy["enhanced"] = True
        if isinstance(copy.get("uses"), int):
            copy["uses"] += 1
        enhanced.append(copy)
    return enhanced


def _derive_action_pool(action_pool: list[dict], role: str) -> list[dict]:
    """Minion: drop active abilities, keep basic attacks. Elite/Boss: keep attacks, enhance actives.
    Standard/Named never reach here (identity short-circuit)."""
    attacks = [dict(a) for a in action_pool if not _is_active_ability(a)]
    actives = [a for a in action_pool if _is_active_ability(a)]
    if role == EncounterRole.MINION:
        return attacks
    return attacks + enhance_abilities(actives)


def derive_role_stats(enemy: dict, role: str) -> dict:
    """Apply an encounter role to a base enemy stat block, returning a NEW derived dict.

    Standard and Named are stat-identity (returned as a copy with identity modifiers + the role
    tag, so the caller can uniformly read role/attack_mod/dc_mod/damage_mult). The derivable roles
    scale HP (rounded per role), AC, XP, and the action pool (strip for Minion, enhance for
    Elite/Boss), carry the flat ``attack_mod``/``dc_mod`` and ``damage_mult`` for the resolver, and
    — for Boss — attach the authored ``signature_ability`` and one legendary action.
    """
    derived = dict(enemy)
    derived["role"] = role

    if role in (EncounterRole.STANDARD, EncounterRole.NAMED):
        derived["attack_mod"] = 0
        derived["dc_mod"] = 0
        derived["damage_mult"] = 1.0
        derived["legendary_actions"] = 0
        derived["signature_ability"] = None
        return derived

    mod = ROLE_MODIFIERS.get(role)
    if mod is None:
        valid = sorted(r.value for r in EncounterRole)
        raise ValueError(f"Unknown encounter role {role!r}; valid roles are {valid}")
    derived["hp"] = _apply_hp(enemy.get("hp", 1), mod)
    derived["ac"] = enemy.get("ac", 10) + mod.ac_mod
    derived["xp_value"] = int(enemy.get("xp_value", 0) * mod.xp_mult)
    derived["action_pool"] = _derive_action_pool(enemy.get("action_pool", []), role)
    derived["attack_mod"] = mod.attack_mod
    derived["dc_mod"] = mod.dc_mod
    derived["damage_mult"] = mod.damage_mult

    is_boss = role == EncounterRole.BOSS
    derived["legendary_actions"] = 1 if is_boss else 0
    derived["signature_ability"] = enemy.get("signature_ability") if is_boss else None
    return derived
