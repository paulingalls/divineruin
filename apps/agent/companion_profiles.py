"""Companion profiles — DB-loaded content config (Phase 6 / M6.4, story-002).

content/companions.json is the single source of truth for the 4 companions
(Kael/Lira/Tam/Sable): the narrative subset reused from the NPC schema, typed ability
buckets (attacks/passives/actives/reactions), and a scaling_rules block. This module is
the Python loader, an exact mirror of role_archetypes.py: frozen dataclasses, a module-
global dict populated by load_companion_profiles() at startup (or set_companion_profiles()
in tests), a fail-loud parse_companion_row shared by the DB loader and the JSON test
fixture, and sync accessors.

scale_companion_stats_to_player_level(profile, player_max_hp, player_level) is the pure
scaler the combat layer (story-004) and capstone (story-005) consume: HP scales to a
fraction of the player's max HP (hp_factor — 0.75 for Kael/Lira/Tam, 0.50 for Sable), AC
steps up at level thresholds, and attributes accrue per-companion bumps. It takes the
player's already-computed max HP (from hp_scaling.calculate_max_hp) so the scaler stays
pure — no coupling to the player's archetype/CON.

Generic field validation (str/int/number/list/dict/attributes + optionals) comes from the
shared catalog_parse module; only the domain-specific parsers below stay inlined here. This
preserves cross-language parity with the TS Companion type
(packages/shared/src/entities/companion.ts): the companions.json row IS the contract, and a
malformed row must reject identically.
"""

import json
import logging
from dataclasses import dataclass

from catalog_parse import (
    ATTRIBUTE_KEYS,
    opt_int,
    opt_str,
    parse_attributes,
    parse_int,
    parse_number,
    parse_str,
    parse_str_tuple,
)
from role_archetypes import DISPOSITIONS  # canonical 5-tier ladder SSOT

logger = logging.getLogger("divineruin.companion_profiles")

_TACTICAL_PREFERENCES = ("aggressive", "protective", "cautious", "observational", "opportunistic")


@dataclass(frozen=True)
class AcThreshold:
    min_level: int
    ac: int


@dataclass(frozen=True)
class AttributeScalingStep:
    level: int
    attribute: str
    amount: int


@dataclass(frozen=True)
class ScalingRules:
    hp_factor: float
    ac_thresholds: tuple[AcThreshold, ...]
    attribute_scaling: tuple[AttributeScalingStep, ...]


@dataclass(frozen=True)
class CompanionAttack:
    name: str
    type: str
    reach: str
    hit: str
    damage: str
    damage_type: str
    special: str | None = None
    scaling: str | None = None


@dataclass(frozen=True)
class CompanionPassive:
    name: str
    description: str
    unlock_level: int | None = None
    scaling: str | None = None


@dataclass(frozen=True)
class CompanionActive:
    name: str
    description: str
    frequency: str
    cost: str | None = None
    unlock_level: int | None = None
    scaling: str | None = None


@dataclass(frozen=True)
class CompanionReaction:
    name: str
    description: str
    frequency: str
    unlock_level: int | None = None


@dataclass(frozen=True)
class ProgressionMilestone:
    level: int
    gains: str


@dataclass(frozen=True)
class Companion:
    id: str
    name: str
    species: str
    personality: tuple[str, ...]
    speech_style: str
    knowledge: dict
    default_disposition: str
    tactical_preference: str
    speed: int
    base_attributes: dict[str, int]
    save_proficiencies: tuple[str, ...]
    scaling_rules: ScalingRules
    attacks: tuple[CompanionAttack, ...]
    passives: tuple[CompanionPassive, ...]
    actives: tuple[CompanionActive, ...]
    reactions: tuple[CompanionReaction, ...]
    complements: tuple[str, ...]
    voice_id: str
    gender: str | None = None
    age: str | None = None
    appearance: str | None = None
    mannerisms: tuple[str, ...] = ()
    backstory_summary: str | None = None
    disposition_modifiers: dict[str, int] | None = None
    secrets: tuple[str, ...] = ()
    progression: tuple[ProgressionMilestone, ...] = ()
    relationship_unlocks: dict[str, list[str]] | None = None
    voice_notes: str | None = None
    non_verbal: bool = False


_companion_profiles: dict[str, Companion] = {}


# --- domain-specific parse helpers (generic primitives come from catalog_parse) ---


def _parse_scaling_rules(raw: object, ctx: str) -> ScalingRules:
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx} is not an object")
    thresholds = raw["ac_thresholds"]
    if not isinstance(thresholds, list) or not thresholds:
        raise ValueError(f"{ctx}.ac_thresholds is not a non-empty list")
    steps = raw["attribute_scaling"]
    if not isinstance(steps, list):
        raise ValueError(f"{ctx}.attribute_scaling is not a list")
    ac_thresholds = tuple(
        AcThreshold(
            min_level=parse_int(t["min_level"], f"{ctx}.ac_thresholds[{i}].min_level"),
            ac=parse_int(t["ac"], f"{ctx}.ac_thresholds[{i}].ac"),
        )
        for i, t in enumerate(thresholds)
    )
    attribute_scaling = tuple(_parse_scaling_step(s, f"{ctx}.attribute_scaling[{i}]") for i, s in enumerate(steps))
    return ScalingRules(
        hp_factor=parse_number(raw["hp_factor"], f"{ctx}.hp_factor"),
        ac_thresholds=ac_thresholds,
        attribute_scaling=attribute_scaling,
    )


def _parse_scaling_step(raw: object, ctx: str) -> AttributeScalingStep:
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx} is not an object")
    attribute = parse_str(raw["attribute"], f"{ctx}.attribute")
    if attribute not in ATTRIBUTE_KEYS:
        raise ValueError(f"{ctx}.attribute {attribute!r} not in {ATTRIBUTE_KEYS}")
    return AttributeScalingStep(
        level=parse_int(raw["level"], f"{ctx}.level"),
        attribute=attribute,
        amount=parse_int(raw["amount"], f"{ctx}.amount"),
    )


def _parse_attack(raw: object, ctx: str) -> CompanionAttack:
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx} is not an object")
    return CompanionAttack(
        name=parse_str(raw["name"], f"{ctx}.name"),
        type=parse_str(raw["type"], f"{ctx}.type"),
        reach=parse_str(raw["reach"], f"{ctx}.reach"),
        hit=parse_str(raw["hit"], f"{ctx}.hit"),
        damage=parse_str(raw["damage"], f"{ctx}.damage"),
        damage_type=parse_str(raw["damage_type"], f"{ctx}.damage_type"),
        special=opt_str(raw.get("special"), f"{ctx}.special"),
        scaling=opt_str(raw.get("scaling"), f"{ctx}.scaling"),
    )


def _parse_passive(raw: object, ctx: str) -> CompanionPassive:
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx} is not an object")
    return CompanionPassive(
        name=parse_str(raw["name"], f"{ctx}.name"),
        description=parse_str(raw["description"], f"{ctx}.description"),
        unlock_level=opt_int(raw.get("unlock_level"), f"{ctx}.unlock_level"),
        scaling=opt_str(raw.get("scaling"), f"{ctx}.scaling"),
    )


def _parse_active(raw: object, ctx: str) -> CompanionActive:
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx} is not an object")
    return CompanionActive(
        name=parse_str(raw["name"], f"{ctx}.name"),
        description=parse_str(raw["description"], f"{ctx}.description"),
        frequency=parse_str(raw["frequency"], f"{ctx}.frequency"),
        cost=opt_str(raw.get("cost"), f"{ctx}.cost"),
        unlock_level=opt_int(raw.get("unlock_level"), f"{ctx}.unlock_level"),
        scaling=opt_str(raw.get("scaling"), f"{ctx}.scaling"),
    )


def _parse_reaction(raw: object, ctx: str) -> CompanionReaction:
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx} is not an object")
    return CompanionReaction(
        name=parse_str(raw["name"], f"{ctx}.name"),
        description=parse_str(raw["description"], f"{ctx}.description"),
        frequency=parse_str(raw["frequency"], f"{ctx}.frequency"),
        unlock_level=opt_int(raw.get("unlock_level"), f"{ctx}.unlock_level"),
    )


def _parse_progression(raw: object, ctx: str) -> ProgressionMilestone:
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx} is not an object")
    return ProgressionMilestone(
        level=parse_int(raw["level"], f"{ctx}.level"),
        gains=parse_str(raw["gains"], f"{ctx}.gains"),
    )


def parse_companion_row(companion_id: str, data: dict) -> Companion:
    """Parse a raw dict (JSON file or DB JSONB) into a Companion, fail-loud.

    Shared by load_companion_profiles (DB) and the JSON test fixture. Wraps the underlying
    error with the row id for context.
    """
    try:
        disposition = parse_str(data["default_disposition"], f"{companion_id}.default_disposition")
        if disposition not in DISPOSITIONS:
            raise ValueError(f"{companion_id}.default_disposition {disposition!r} not in {DISPOSITIONS}")
        tactical = parse_str(data["tactical_preference"], f"{companion_id}.tactical_preference")
        if tactical not in _TACTICAL_PREFERENCES:
            raise ValueError(f"{companion_id}.tactical_preference {tactical!r} not in {_TACTICAL_PREFERENCES}")
        knowledge = data["knowledge"]
        if not isinstance(knowledge, dict) or not isinstance(knowledge.get("free"), list):
            raise ValueError(f"{companion_id}.knowledge missing a 'free' list")
        save_profs = parse_str_tuple(data["save_proficiencies"], f"{companion_id}.save_proficiencies")
        if len(save_profs) != 2:
            raise ValueError(f"{companion_id}.save_proficiencies must have exactly 2 entries")
        for sp in save_profs:
            if sp not in ATTRIBUTE_KEYS:
                raise ValueError(f"{companion_id}.save_proficiencies {sp!r} not in {ATTRIBUTE_KEYS}")
        non_verbal = bool(data.get("non_verbal", False))
        mods = data.get("disposition_modifiers")
        if mods is not None and not isinstance(mods, dict):
            raise ValueError(f"{companion_id}.disposition_modifiers is not an object or null")
        unlocks = data.get("relationship_unlocks")
        if unlocks is not None and not isinstance(unlocks, dict):
            raise ValueError(f"{companion_id}.relationship_unlocks is not an object or null")
        return Companion(
            id=companion_id,
            name=parse_str(data["name"], f"{companion_id}.name"),
            species=parse_str(data["species"], f"{companion_id}.species"),
            personality=parse_str_tuple(data["personality"], f"{companion_id}.personality"),
            speech_style=parse_str(data["speech_style"], f"{companion_id}.speech_style"),
            knowledge=knowledge,
            default_disposition=disposition,
            tactical_preference=tactical,
            speed=parse_int(data["speed"], f"{companion_id}.speed"),
            base_attributes=parse_attributes(data["base_attributes"], f"{companion_id}.base_attributes"),
            save_proficiencies=save_profs,
            scaling_rules=_parse_scaling_rules(data["scaling_rules"], f"{companion_id}.scaling_rules"),
            attacks=tuple(_parse_attack(a, f"{companion_id}.attacks[{i}]") for i, a in enumerate(data["attacks"])),
            passives=tuple(_parse_passive(p, f"{companion_id}.passives[{i}]") for i, p in enumerate(data["passives"])),
            actives=tuple(_parse_active(a, f"{companion_id}.actives[{i}]") for i, a in enumerate(data["actives"])),
            reactions=tuple(
                _parse_reaction(r, f"{companion_id}.reactions[{i}]") for i, r in enumerate(data["reactions"])
            ),
            complements=parse_str_tuple(data["complements"], f"{companion_id}.complements"),
            voice_id=parse_str(data["voice_id"], f"{companion_id}.voice_id"),
            gender=opt_str(data.get("gender"), f"{companion_id}.gender"),
            age=opt_str(data.get("age"), f"{companion_id}.age"),
            appearance=opt_str(data.get("appearance"), f"{companion_id}.appearance"),
            mannerisms=parse_str_tuple(data.get("mannerisms", []), f"{companion_id}.mannerisms"),
            backstory_summary=opt_str(data.get("backstory_summary"), f"{companion_id}.backstory_summary"),
            disposition_modifiers=mods,
            secrets=parse_str_tuple(data.get("secrets", []), f"{companion_id}.secrets"),
            progression=tuple(
                _parse_progression(m, f"{companion_id}.progression[{i}]")
                for i, m in enumerate(data.get("progression", []))
            ),
            relationship_unlocks=unlocks,
            voice_notes=opt_str(data.get("voice_notes"), f"{companion_id}.voice_notes"),
            non_verbal=non_verbal,
        )
    except (KeyError, TypeError) as e:
        raise ValueError(f"Malformed companions row {companion_id!r}: {e}") from e


def set_companion_profiles(config: dict[str, Companion]) -> None:
    """Test seam: populate _companion_profiles directly without going through the DB."""
    _companion_profiles.clear()
    _companion_profiles.update(config)


def get_companion_profile(companion_id: str) -> Companion:
    """Return the companion profile for an id. Raises ValueError if not loaded/unknown."""
    if companion_id not in _companion_profiles:
        raise ValueError(f"Unknown companion: {companion_id!r}")
    return _companion_profiles[companion_id]


def is_loaded() -> bool:
    """True once the catalog has been populated (startup load or test seam)."""
    return bool(_companion_profiles)


async def load_companion_profiles() -> None:
    """Load the companion catalog from the DB into _companion_profiles.

    Called at agent startup beside load_npcs(). Fails loud if the query or a row errors.
    Builds a local dict then swaps in one synchronous step (no await between), so a malformed
    row fails loud WITHOUT wiping an already-loaded map and a concurrent get_companion_profile
    never observes a half-populated map.
    """
    import db

    pool = await db.get_pool()
    rows = await pool.fetch("SELECT id, data FROM companions")
    loaded: dict[str, Companion] = {}
    for row in rows:
        data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
        loaded[row["id"]] = parse_companion_row(row["id"], data)
    _companion_profiles.clear()
    _companion_profiles.update(loaded)
    logger.info("Loaded %d companions", len(_companion_profiles))
