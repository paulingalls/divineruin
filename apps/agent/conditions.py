"""Pure status-condition catalog and logic (M4.3, story-001).

Conditions are the combat state layer that automatically factors into rolls:
a Poisoned fighter swings at disadvantage, an Exhausted one eats a flat penalty
per stack, a Stunned one loses the phase entirely. This module is the single
deterministic source for *what each condition means* (``CONDITION_CATALOG``) and
the pure functions that apply, remove, tick, and aggregate them. It is pure: it
reads only its explicit arguments and never touches IO, RNG, DB, or combat state.

An *active* condition is a plain ``dict`` of JSON-native values — ``{"type",
"duration", "source", "stacks", "stage"?}`` — so it round-trips through the
combat_instances JSONB SSOT via ``asdict()`` with no conversion layer, the same
serialization approach the other ``CombatParticipant`` state fields use (story-004
owns that wiring). The catalog metadata is a frozen ``ConditionSpec`` per type,
mirroring dramatic.py's style.

Catalog and ordering mirror docs/game_mechanics/game_mechanics_combat.md
§Status Effects (L263-322).
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ConditionSpec:
    """Immutable metadata for one condition type (the catalog value).

    Fields default so each catalog entry declares only the mechanics that apply.
    Numeric modifiers are per-instance (per-stack for ``stackable`` conditions);
    the ``*_scopes`` / ``restrictions`` / ``auto_fail_saves`` tuples name the
    resolver-interpreted effects. ``tick_save`` names the ability for a recurring
    end-of-phase save-to-clear (only Frightened has one per the spec).
    """

    clearance: str
    persists_across_encounters: bool = False
    stackable: bool = False
    default_max_stacks: int | None = None
    check_modifier: int = 0
    ac_modifier: int = 0
    damage_modifier: int = 0
    disadvantage_scopes: tuple[str, ...] = ()
    advantage_scopes: tuple[str, ...] = ()
    auto_fail_saves: tuple[str, ...] = ()
    restrictions: tuple[str, ...] = ()
    tick_save: str | None = None
    # Bonus damage DIE the attacker's hits add (M4.4 story-008): a dice notation like "1d6" plus
    # its type (e.g. necrotic), rolled per-hit in resolve_attack. Distinct from the flat
    # ``damage_modifier`` (Enraged +2) — a rider die, not a constant.
    bonus_damage_dice: str | None = None
    bonus_damage_type: str | None = None
    # Condition types this condition makes its bearer IMMUNE to (M4.4 story-008): apply_condition
    # no-ops an incoming type listed here. The Temporary Hollowed is immune to Charmed/Frightened/
    # Poisoned.
    immunities: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConditionEffects:
    """Aggregate of every active condition's mechanical impact (the read model
    story-003 resolvers consume). Scope/restriction/save sets are unions; the
    numeric fields are sums."""

    check_modifier: int = 0
    ac_modifier: int = 0
    damage_modifier: int = 0
    disadvantage_scopes: frozenset[str] = field(default_factory=frozenset)
    advantage_scopes: frozenset[str] = field(default_factory=frozenset)
    auto_fail_saves: frozenset[str] = field(default_factory=frozenset)
    restrictions: frozenset[str] = field(default_factory=frozenset)
    # Bonus damage rider (M4.4 story-008): the single die+type an attacker's hits add (only the
    # Temporary Hollowed grants one today, so this is a scalar, not a sum).
    bonus_damage_dice: str | None = None
    bonus_damage_type: str | None = None
    immunities: frozenset[str] = field(default_factory=frozenset)


# The 21-condition catalog. Keys are frozen snake_case labels (same naming
# discipline as the dramatic-dice catalog); emitters and resolvers key off them.
CONDITION_CATALOG: dict[str, ConditionSpec] = {
    # --- Combat conditions ---
    "wounded": ConditionSpec(
        clearance="long_rest",
        persists_across_encounters=True,
        restrictions=("reduced_max_hp",),
    ),
    "stunned": ConditionSpec(
        clearance="end_of_next_turn",
        restrictions=("skip_phase",),
        auto_fail_saves=("str", "dex"),
    ),
    "prone": ConditionSpec(
        clearance="stand_costs_declaration",
        disadvantage_scopes=("attack",),
        restrictions=("costs_declaration", "incoming_melee_advantage", "incoming_ranged_disadvantage"),
    ),
    "grappled": ConditionSpec(
        clearance="escape_check_or_released",
        restrictions=("speed_0", "costs_declaration"),
    ),
    "restrained": ConditionSpec(
        clearance="str_check_vs_source_or_dispelled",
        disadvantage_scopes=("attack", "dex"),
        restrictions=("speed_0", "incoming_advantage"),
    ),
    "incapacitated": ConditionSpec(
        clearance="source_dependent",
        restrictions=("skip_phase",),
    ),
    "paralyzed": ConditionSpec(
        clearance="duration_greater_restoration_or_source_removed",
        auto_fail_saves=("str", "dex"),
        restrictions=("skip_phase", "incoming_advantage", "incoming_melee_autocrit"),
    ),
    "poisoned": ConditionSpec(
        clearance="short_rest_medicine_or_antidote",
        disadvantage_scopes=("str", "dex", "con"),
    ),
    "blessed": ConditionSpec(
        clearance="consumed_on_use",
        advantage_scopes=("next_roll",),
        restrictions=("consumed_on_use",),
    ),
    "shielded": ConditionSpec(
        clearance="duration",
        restrictions=("damage_reduction",),
    ),
    "enraged": ConditionSpec(
        clearance="end_of_combat_or_dismissed",
        ac_modifier=-2,
        damage_modifier=2,
    ),
    # --- Environmental conditions ---
    "exhausted": ConditionSpec(
        clearance="long_rest_removes_one_stack",
        persists_across_encounters=True,
        stackable=True,
        default_max_stacks=5,
        check_modifier=-1,  # per stack
    ),
    "blinded": ConditionSpec(
        clearance="situational",
        disadvantage_scopes=("attack", "perception"),
    ),
    "frightened": ConditionSpec(
        clearance="wis_save_each_turn",
        disadvantage_scopes=("vs_source",),
        restrictions=("no_approach_source",),
        tick_save="wis",
    ),
    "charmed": ConditionSpec(
        clearance="damage_from_source_or_duration",
        disadvantage_scopes=("vs_source",),
        restrictions=("no_hostile_source",),
    ),
    "deafened": ConditionSpec(
        clearance="duration_or_magical_healing",
        restrictions=("auto_fail_hearing_perception", "no_spoken_buffs"),
    ),
    "shaken": ConditionSpec(
        clearance="consumed_after_one_attack",
        disadvantage_scopes=("attack",),
        restrictions=("consumed_on_use", "one_time"),
    ),
    "petrified": ConditionSpec(
        clearance="greater_restoration_or_counter_magic",
        restrictions=(
            "skip_phase",
            "damage_resistance_all",
            "immune_poison_disease",
            "removed_from_combat",
        ),
    ),
    # --- Magical conditions ---
    "cursed": ConditionSpec(
        clearance="remove_curse_or_quest",
        restrictions=("source_specific_penalty",),
    ),
    "inspired": ConditionSpec(
        clearance="consumed_on_use",
        restrictions=("bonus_d4_creative_social", "consumed_on_use"),
    ),
    "hollowed": ConditionSpec(
        clearance="greater_restoration_or_sanctified_rest",
        persists_across_encounters=True,
        # Stage-distinct effects are resolved in get_condition_effects (story-001
        # decision: single type + stage field, escalated by apply_condition).
    ),
    # Engine-internal marker (M4.4 story-008), NOT one of the doc's 21 §Status Effects. A Stage-2+
    # Hollowed player who drops to 0 HP rises as a Temporary Hollowed combatant carrying this: its
    # hits add 1d6 necrotic and it is immune to Charmed/Frightened/Poisoned. Combat-local — cleared
    # when the echo is destroyed, never persisted onto players.data.
    "temporary_hollowed": ConditionSpec(
        clearance="combat_only_until_destroyed",
        persists_across_encounters=False,
        bonus_damage_dice="1d6",
        bonus_damage_type="necrotic",
        immunities=("charmed", "frightened", "poisoned"),
    ),
}

_HOLLOWED_MAX_STAGE = 3


def validate_condition_dict(c: object) -> dict:
    """Fail-loud validation for one stored condition dict (M4.4 story-005, JSONB read boundary).

    A condition round-trips through JSONB as {type, duration, source, stacks?|stage?}. Checks the
    closed-vocab ``type`` against CONDITION_CATALOG and the int-typed fields WHEN PRESENT (``stacks``
    / ``stage`` are int; ``duration`` is int|None) — well-formed dicts vary by condition, so absent
    fields are fine. Returns ``c`` on success; raises ValueError on a corrupt dict so a bad row
    surfaces at the boundary instead of crashing a downstream resolver."""
    if not isinstance(c, dict):
        raise ValueError(f"condition entry is not a dict: {c!r}")
    if "type" not in c:
        raise ValueError(f"condition dict missing 'type': {c!r}")
    ctype = c["type"]
    if ctype not in CONDITION_CATALOG:
        raise ValueError(f"unknown condition type: {ctype!r}")
    for int_field in ("stacks", "stage"):
        if int_field in c and not isinstance(c[int_field], int):
            raise ValueError(f"condition {ctype!r} {int_field} must be an int, got {c[int_field]!r}")
    if "duration" in c and c["duration"] is not None and not isinstance(c["duration"], int):
        raise ValueError(f"condition {ctype!r} duration must be int or None, got {c['duration']!r}")
    return c


def validate_conditions(conditions: list) -> list:
    """Validate every entry of a stored conditions list (fail-loud); returns it on success."""
    for c in conditions:
        validate_condition_dict(c)
    return conditions


def cap_exhaustion(conditions: list[dict], cap: int) -> list[dict]:
    """Return a new list with the ``exhausted`` entry's ``stacks`` clamped to ``cap`` (M4.4
    story-005). No-op when no exhausted entry is present or it is already at/below ``cap``. Never
    mutates the input. Used at the combat-START load boundary to enforce the iron-constitution cap
    (the in-scope apply site until a forced-march/travel producer ships)."""
    result = [dict(c) for c in conditions]
    existing = _find(result, "exhausted")
    if existing is not None and existing.get("stacks", 0) > cap:
        existing["stacks"] = cap
    return result


def _find(conditions: list[dict], condition_type: str) -> dict | None:
    """Return the active instance of ``condition_type``, or None."""
    for c in conditions:
        if c["type"] == condition_type:
            return c
    return None


def apply_condition(
    conditions: list[dict],
    condition_type: str,
    *,
    duration: int | None = None,
    source: str | None = None,
    max_stacks: int | None = None,
) -> list[dict]:
    """Return a new condition list with ``condition_type`` applied.

    Stackable conditions (Exhausted) increment ``stacks`` up to the effective cap
    (``max_stacks`` override, else the catalog's ``default_max_stacks``) rather than
    duplicating. Hollowed escalates its ``stage`` (capped at 3). Other re-applies of
    an already-active condition refresh its duration/source. Never mutates the input.
    Raises ``ValueError`` on an unknown condition type (fail-loud).
    """
    spec = CONDITION_CATALOG.get(condition_type)
    if spec is None:
        raise ValueError(f"Unknown condition type: {condition_type!r}")

    result = [dict(c) for c in conditions]

    # Immunity gate (M4.4 story-008): if any active condition makes its bearer immune to
    # ``condition_type``, applying it is a no-op (e.g. a Temporary Hollowed shrugs off Charmed).
    if any(condition_type in CONDITION_CATALOG[c["type"]].immunities for c in result):
        return result

    existing = _find(result, condition_type)

    if condition_type == "hollowed":
        if existing is not None:
            existing["stage"] = min(existing["stage"] + 1, _HOLLOWED_MAX_STAGE)
            return result
        result.append({"type": "hollowed", "duration": duration, "source": source, "stage": 1})
        return result

    if spec.stackable:
        cap = max_stacks if max_stacks is not None else spec.default_max_stacks
        if existing is not None:
            existing["stacks"] = min(existing["stacks"] + 1, cap) if cap is not None else existing["stacks"] + 1
            return result
        result.append({"type": condition_type, "duration": duration, "source": source, "stacks": 1})
        return result

    if existing is not None:  # non-stackable re-apply refreshes
        existing["duration"] = duration
        existing["source"] = source
        return result

    result.append({"type": condition_type, "duration": duration, "source": source, "stacks": 1})
    return result


def remove_condition(conditions: list[dict], condition_type: str) -> list[dict]:
    """Return a new condition list with every instance of ``condition_type`` removed.
    Other conditions are untouched; never mutates the input."""
    return [dict(c) for c in conditions if c["type"] != condition_type]


def hollowed_stage(conditions: list[dict] | None) -> int:
    """Return the active Hollowed stage (1-3), or 0 when not Hollowed (M4.4 story-008).

    Tolerates a JSON-null ``conditions`` (players.data.conditions can be stored null) by treating
    it as no conditions. The combat-engine rise check reads this to gate the Temporary Hollowed
    on Stage 2+."""
    existing = _find(conditions or [], "hollowed")
    return existing["stage"] if existing is not None else 0


def tick_conditions(conditions: list[dict]) -> tuple[list[dict], list[dict]]:
    """Advance conditions one phase. Return ``(survivors, save_events)``.

    Integer durations decrement; conditions hitting 0 are dropped. ``None`` durations
    persist until explicitly cleared. Conditions whose catalog spec names a recurring
    ``tick_save`` (only Frightened, per the spec) surface a save event so the wrap
    caller (story-002) can resolve the save-to-clear — this module only *signals* it,
    it never rolls. Never mutates the input.
    """
    survivors: list[dict] = []
    save_events: list[dict] = []
    for c in conditions:
        spec = CONDITION_CATALOG[c["type"]]
        if spec.tick_save is not None:
            save_events.append({"type": c["type"], "save": spec.tick_save, "source": c.get("source")})

        duration = c["duration"]
        if duration is None:
            survivors.append(dict(c))
            continue
        remaining = duration - 1
        if remaining <= 0:
            continue
        ticked = dict(c)
        ticked["duration"] = remaining
        survivors.append(ticked)
    return survivors, save_events


def _hollowed_effects(stage: int) -> tuple[set[str], set[str]]:
    """Return (disadvantage_scopes, restrictions) for a Hollowed instance at ``stage``.
    Stage 1 = disadvantage WIS; stage 2 adds hallucinations; stage 3 adds stat drain."""
    disadvantage = {"wis"}
    restrictions: set[str] = set()
    if stage >= 2:
        restrictions.add("hallucinations")
    if stage >= 3:
        restrictions.add("stat_drain")
    return disadvantage, restrictions


def get_condition_effects(conditions: list[dict]) -> ConditionEffects:
    """Aggregate every active condition into the read model resolvers consume.

    Numeric modifiers sum (Exhausted's per-stack penalty scales with ``stacks``);
    scope/restriction/save sets union. Hollowed contributes stage-distinct effects.
    """
    check_modifier = 0
    ac_modifier = 0
    damage_modifier = 0
    disadvantage: set[str] = set()
    advantage: set[str] = set()
    auto_fail: set[str] = set()
    restrictions: set[str] = set()
    immunities: set[str] = set()
    bonus_damage_dice: str | None = None
    bonus_damage_type: str | None = None

    for c in conditions:
        spec = CONDITION_CATALOG[c["type"]]
        immunities.update(spec.immunities)
        # At most one active condition grants a rider die today (the Temporary Hollowed), so a
        # scalar last-wins assignment is exact; revisit if two riders ever co-exist.
        if spec.bonus_damage_dice is not None:
            bonus_damage_dice = spec.bonus_damage_dice
            bonus_damage_type = spec.bonus_damage_type
        if c["type"] == "hollowed":
            hol_dis, hol_res = _hollowed_effects(c["stage"])
            disadvantage |= hol_dis
            restrictions |= hol_res
            continue
        stacks = c.get("stacks", 1)
        check_modifier += spec.check_modifier * stacks
        ac_modifier += spec.ac_modifier
        damage_modifier += spec.damage_modifier
        disadvantage.update(spec.disadvantage_scopes)
        advantage.update(spec.advantage_scopes)
        auto_fail.update(spec.auto_fail_saves)
        restrictions.update(spec.restrictions)

    return ConditionEffects(
        check_modifier=check_modifier,
        ac_modifier=ac_modifier,
        damage_modifier=damage_modifier,
        disadvantage_scopes=frozenset(disadvantage),
        advantage_scopes=frozenset(advantage),
        auto_fail_saves=frozenset(auto_fail),
        restrictions=frozenset(restrictions),
        bonus_damage_dice=bonus_damage_dice,
        bonus_damage_type=bonus_damage_type,
        immunities=frozenset(immunities),
    )
