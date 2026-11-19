"""Condition specifications and their catalog."""

from dataclasses import dataclass, field

from _gods_content import load_gods


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
    # A bonus to the bearer's roll total. Clearance controls whether the die is single-use.
    bonus_die: str | None = None
    bonus_die_scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class BonusDie:
    """Keep each granting condition identifiable so single-use dice can be cleared independently."""

    source: str  # condition type that granted the die, e.g. "blessed"
    dice: str  # dice notation, e.g. "1d4"
    scopes: frozenset[str]  # roll kinds it applies to: subset of {"attack", "save", "check"}


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
    bonus_dice: tuple[BonusDie, ...] = ()


CONDITION_CATALOG: dict[str, ConditionSpec] = {
    "iron_resolve": ConditionSpec(
        clearance="end_of_next_turn",
        check_modifier=next(row for row in load_gods() if row["god_id"] == "kaelen")["layer_1_gift"]["mechanics"][
            "amount"
        ],
    ),
    "battle_cry": ConditionSpec(clearance="duration", bonus_die="1d4", bonus_die_scopes=("attack",)),
    "worthy_foe": ConditionSpec(clearance="end_of_combat_or_dismissed", restrictions=("incoming_advantage",)),
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
        tick_save="wis",
    ),
    "poisoned": ConditionSpec(
        clearance="short_rest_medicine_or_antidote",
        disadvantage_scopes=("str", "dex", "con"),
    ),
    "blessed": ConditionSpec(
        clearance="consumed_on_use",
        # +1d4 on the bearer's next attack or saving throw, consumed on use (M4.8). NOT advantage:
        # the prior advantage_scopes=("next_roll",) never intersected any resolver scope and
        # mismodelled a flat die as roll-twice.
        bonus_die="1d4",
        bonus_die_scopes=("attack", "save"),
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
    "precise_strike": ConditionSpec(
        clearance="consumed_on_use",
        advantage_scopes=("attack",),
        restrictions=("consumed_on_use",),
    ),
    "inspired": ConditionSpec(
        clearance="consumed_on_use",
        # +1d4 on ANY of the bearer's next rolls, consumed on use (M4.8). Replaces the inert
        # "bonus_d4_creative_social" restriction string no resolver ever read.
        bonus_die="1d4",
        bonus_die_scopes=("attack", "save", "check"),
        restrictions=("consumed_on_use",),
    ),
    "regenerating": ConditionSpec(clearance="regeneration_expired"),
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
