from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CombatParticipant:
    id: str
    name: str
    type: str  # "player", "enemy", "companion", "temporary_hollowed" — use is_ally for the band check
    initiative: int
    hp_current: int
    hp_max: int
    ac: int
    attributes: dict = field(default_factory=lambda: {"strength": 10, "dexterity": 10})
    level: int = 1
    is_fallen: bool = False
    # Instant death (M4.4 story-002): a single hit whose overkill (excess damage past 0) >= hp_max
    # kills outright — skips the Fallen state and death saves entirely. Distinct from is_fallen
    # (fallen = dying/making saves; dead = gone). Set at the damage site (combat_support); the pure
    # _wrap ends combat without a death-save beat. Serializes via asdict, defaults False for old rows.
    is_dead: bool = False
    death_save_successes: int = 0
    death_save_failures: int = 0
    action_pool: list[dict] = field(default_factory=list)
    xp_value: int = 0
    # Declaration enhancers this participant has been granted (M4.2, story-004). Keys:
    # extra_attack, shield_bash, cunning_action, hit_and_run, command_lesser, quick_change.
    # An enhancer EXPANDS what one declaration resolves into; it never grants a 2nd
    # declaration. Populated from players.data.flags at combat init; serializes via asdict
    # and falls back to [] for rows written before the field existed.
    enhancers: list[str] = field(default_factory=list)
    # Active status conditions (M4.3, story-002). Each is a plain JSON-native dict
    # {type, duration, source, stacks, stage?} produced by conditions.apply_condition;
    # the phase engine's Beat-4 wrap ticks them (combat_phase._wrap). Serializes via asdict
    # and falls back to [] for rows written before the field existed. Cross-encounter
    # persistence (Wounded/Exhausted/Hollowed) is story-004's migration-050 concern.
    conditions: list[dict] = field(default_factory=list)
    # Encounter-role overlay (M4.7, story-001). ``role`` is the assigned EncounterRole
    # (minion/standard/elite/boss/named) and the rest are the role-derived modifiers
    # encounter_roles.derive_role_stats produces at combat init. ``attack_mod``/``dc_mod``/
    # ``damage_mult`` are read by the resolver (check_resolution_attack/save) to scale this
    # participant's to-hit / save-DC / damage; ``legendary_actions`` + ``signature_ability``
    # scaffold the Boss runtime (firing is story-003). All default to identity so players and
    # pre-M4.7 enemy rows resolve unchanged, and serialize via asdict / fall back on from_dict
    # for rows written before the fields existed (same pattern as enhancers/conditions).
    role: str = "standard"
    attack_mod: int = 0
    damage_mult: float = 1.0
    dc_mod: int = 0
    legendary_actions: int = 0
    signature_ability: dict | None = None
    # Loot & currency overlay (M4.7, story-002). ``category`` is the enemy's creature category
    # (humanoid/beast/hollow_drift/hollow_rend/construct/undead/named) and ``loot_table_id`` points
    # at its content/loot_tables.json table. combat_init carries both off the template enemy; on
    # victory _end_combat_db reads them to roll role-scaled loot (derive_role_loot) and currency
    # (calculate_currency_drop). Empty-string defaults so players/companions and pre-M4.7 enemy
    # rows serialize via asdict / fall back on from_dict unchanged (same pattern as the role fields).
    category: str = ""
    loot_table_id: str = ""
    # Saving-throw proficiencies (M13 close-fix): the attribute save names this participant is
    # proficient in (e.g. ["wisdom", "charisma"]), sourced from players.data at combat init for
    # a player. resolve_saving_throw adds the proficiency bonus when the rolled save is listed —
    # so a WIS-proficient target resists an enemy-inflicted Frightened as the rules intend.
    # Defaults to [] (enemies/companions and pre-fix rows carry none; from_dict falls back).
    saving_throw_proficiencies: list[str] = field(default_factory=list)
    # Tier-3 social resistance personality (M15 story-002): the argument-resistance tags
    # (social_resolution.RESISTANCE_TAGS — pragmatic/emotional/suspicious/...) an enemy carries,
    # loaded from the encounter template at combat init and validated there. The de-escalation
    # orchestrator (combat_ability) reads them per enemy so each disposition shifts by its OWN
    # profile — a matching argument eases that enemy's DC, a resisted one stiffens it. Empty for
    # players/companions and untagged/pre-M15 enemy rows (from_dict uses CombatParticipant(**p),
    # so the default covers legacy rows), mirroring enhancers/conditions/saving_throw_proficiencies.
    resistance_tags: list[str] = field(default_factory=list)
    # None is a row persisted before this field existed. The window openers read it as NOT an
    # owner rather than tolerating it: such a row carries no reaction_ids either, so a window
    # offered to it could only ever end in the activation gate refusing the spend.
    has_reaction_ability: bool | None = None
    # The class catalog's reaction ids: a participant carries no class, and the DM must be handed
    # an exact id at a window.
    reaction_ids: list[str] = field(default_factory=list)
    prone_immunity: str | None = None
    # Carried-item protections (story-053), folded from the member's inventory by
    # item_effects.combat_traits at combat init. Each maps the protected token -> the NAME of the
    # item(s) granting it, because every consumer must tell the DM which item saved them; a bare
    # set would lose that. Empty for enemies/companions and for rows written before the fields
    # existed (from_dict uses CombatParticipant(**p)). Read by _land_condition_on_one (immunity),
    # roll_participant_save (save advantage) and resolve_maneuver (shove defence).
    condition_immunities: dict[str, str] = field(default_factory=dict)
    save_advantages: dict[str, str] = field(default_factory=dict)
    advantage_vs: dict[str, str] = field(default_factory=dict)

    @property
    def is_ally(self) -> bool:
        """True when this participant sits on the player's side (player or companion).

        Single source of truth for the ally/enemy band — consumers (HUD packet builder,
        initiative tie-break, future role logic) read this rather than re-encoding the
        type taxonomy. Enemies and temporary_hollowed (a Stage-2+ player-turned-echo
        that fights AGAINST the party) both read False.
        """
        return self.type in ("player", "companion")
