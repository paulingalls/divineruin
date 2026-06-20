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
