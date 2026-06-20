"""Pure status-condition catalog and logic (M4.3, story-001).

Conditions are the combat state layer that automatically factors into rolls:
a Poisoned fighter swings at disadvantage, an Exhausted one eats a flat penalty
per stack, a Stunned one loses the phase entirely. This module is the single
deterministic source for *what each condition means* (``CONDITION_CATALOG``) and
the pure functions that apply, remove, tick, and aggregate them. It is pure: it
reads only its explicit arguments and never touches IO, RNG, DB, or combat state.

An *active* condition is a plain ``dict`` — ``{"type", "duration", "source",
"stacks", "stage"?}`` — mirroring the serializable-primitive shape of
``CombatParticipant.enhancers`` so it round-trips through the combat_instances
JSONB SSOT with no conversion layer (story-004 owns that wiring). The catalog
metadata is a frozen ``ConditionSpec`` per type, mirroring dramatic.py's style.

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
}

_HOLLOWED_MAX_STAGE = 3


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

    for c in conditions:
        spec = CONDITION_CATALOG[c["type"]]
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
    )
