"""Archetype abilities — DB-loaded content config (M2.2).

content/archetype_abilities.json is the single source of truth for every
archetype's activatable abilities: core actives + casters' fixed core spells
(ability_type=core), core reactions (reaction), and L4/L8 elective techniques
(elective). This module is the Python loader, an exact mirror of archetypes.py
(M2.1): a module-global dict populated by load_abilities() at process startup
(or set_abilities() in tests), a fail-loud parse_ability_row shared by the DB
loader and the JSON test fixture, and sync accessors.

Cost is a structured object (decision m22-cost-object-schema): {stamina, focus,
scaling}. Fixed/zero/mixed costs live in stamina+focus; variable (Divine Smite)
and pool-based (Lay on Hands) costs put their base in stamina/focus and the
human-readable rule in the free-text scaling field. The request_ability_activation
tool (story-004) consumes get_ability / get_archetype_abilities.
"""

import json
import logging
from dataclasses import dataclass
from typing import Literal, get_args

logger = logging.getLogger("divineruin.abilities")

AbilityType = Literal["core", "reaction", "elective"]

# Closed vocabulary for the ability_type enum — the loader owns fail-loud
# validation, mirroring archetypes.parse_archetype_row.
_ABILITY_TYPES = frozenset(get_args(AbilityType))


@dataclass(frozen=True)
class Cost:
    stamina: int
    focus: int
    scaling: str | None  # variable/pool cost detail (e.g. Divine Smite, Lay on Hands)


@dataclass(frozen=True)
class Ability:
    id: str
    archetype_id: str
    name: str
    ability_type: AbilityType
    level_requirement: int
    cost: Cost
    effect: str
    narration_cue: str


# Module-level runtime-loaded abilities, keyed by ability id. Populated by
# load_abilities() at startup, or by set_abilities() in tests.
_abilities: dict[str, Ability] = {}


def _parse_cost(raw: object, ctx: str) -> Cost:
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx} is not an object")
    stamina = raw["stamina"]
    focus = raw["focus"]
    scaling = raw["scaling"]
    if not isinstance(stamina, int) or isinstance(stamina, bool):
        raise ValueError(f"{ctx}.stamina is not an int")
    if not isinstance(focus, int) or isinstance(focus, bool):
        raise ValueError(f"{ctx}.focus is not an int")
    if scaling is not None and not isinstance(scaling, str):
        raise ValueError(f"{ctx}.scaling is not a string or null")
    return Cost(stamina=stamina, focus=focus, scaling=scaling)


def parse_ability_row(ability_id: str, data: dict) -> Ability:
    """Parse a raw dict (from JSON file or DB JSONB) into an Ability.

    Shared by load_abilities (DB) and tests/archetype_abilities_config_fixture
    (JSON). Raises ValueError wrapping the underlying error with the row id for
    context; owns fail-loud validation of the ability_type enum and cost shape.
    """
    try:
        ability_type = data["ability_type"]
        if ability_type not in _ABILITY_TYPES:
            raise ValueError(f"ability {ability_id!r} ability_type {ability_type!r} not in {sorted(_ABILITY_TYPES)}")
        level_requirement = data["level_requirement"]
        # bool is a subclass of int — exclude it explicitly, mirroring _parse_cost.
        if not isinstance(level_requirement, int) or isinstance(level_requirement, bool):
            raise ValueError(f"ability {ability_id!r} level_requirement is not an int")
        return Ability(
            id=ability_id,
            archetype_id=data["archetype_id"],
            name=data["name"],
            ability_type=ability_type,
            level_requirement=level_requirement,
            cost=_parse_cost(data["cost"], f"{ability_id}.cost"),
            effect=data["effect"],
            narration_cue=data["narration_cue"],
        )
    except (KeyError, TypeError) as e:
        raise ValueError(f"Malformed archetype_abilities row {ability_id!r}: {e}") from e


def set_abilities(config: dict[str, Ability]) -> None:
    """Test seam: populate _abilities directly without going through the DB."""
    _abilities.clear()
    _abilities.update(config)


def get_ability(ability_id: str) -> Ability:
    """Return the ability for an id. Raises ValueError if not loaded/unknown."""
    if ability_id not in _abilities:
        raise ValueError(f"Unknown ability: {ability_id!r}")
    return _abilities[ability_id]


def get_archetype_abilities(archetype_id: str) -> tuple[Ability, ...]:
    """Return all loaded abilities for an archetype, in load order.

    Empty tuple when the archetype has none loaded (e.g. an unknown id). Callers
    filter by ability_type / level_requirement (e.g. the L4/L8 elective pools).
    """
    return tuple(a for a in _abilities.values() if a.archetype_id == archetype_id)


def owns_ability(player_class: str | None, ability: Ability, *, owns_elective: bool) -> bool:
    """Whether a player owns a base ability — the predicate the activation and
    learn(variant) gates share (story-006).

    Two ownership rules, keyed on ability_type (migration 030): core and reaction
    abilities are always-known, derived from the archetype, with NO
    character_abilities row — so they are owned iff the player's class is the
    ability's archetype. Elective techniques DO get a row when chosen, so their
    ownership is the EXISTS-on-character_abilities result the caller passes as
    owns_elective (computed lazily, only when needed — core/reaction skip the DB).
    """
    if ability.ability_type == "elective":
        return owns_elective
    return player_class == ability.archetype_id


def is_loaded() -> bool:
    """True once the abilities have been populated (startup load or test seam)."""
    return bool(_abilities)


async def load_abilities() -> None:
    """Load the archetype abilities from the DB into _abilities.

    Called from agent.py (dm_session, guarded) and async_worker.py startup. Fails
    loud if the query or a row errors. Builds a local dict then swaps in one
    synchronous step (no await between), so a malformed row fails loud WITHOUT
    wiping an already-loaded map and a concurrent get_ability never observes a
    half-populated map.
    """
    import db

    pool = await db.get_pool()
    rows = await pool.fetch("SELECT id, data FROM archetype_abilities")
    loaded: dict[str, Ability] = {}
    for row in rows:
        data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
        loaded[row["id"]] = parse_ability_row(row["id"], data)
    _abilities.clear()
    _abilities.update(loaded)
    logger.info("Loaded %d archetype abilities", len(_abilities))
