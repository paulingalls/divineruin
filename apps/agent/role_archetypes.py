"""Role archetypes — DB-loaded content config (Phase 6 / M6.1, story-002).

content/role_archetypes.json is the single source of truth for NPC role-archetype
templates: per-archetype combat stats (inlined; no CreatureStatBlock until Phase 7),
services, inventory pool, knowledge domains, and disposition baseline. This module is
the Python loader, an exact mirror of mentor_variants.py: frozen dataclasses, a module-
global dict populated by load_role_archetypes() at startup (or set_role_archetypes() in
tests), a fail-loud parse_role_archetype_row shared by the DB loader and the JSON test
fixture, and sync accessors.

create_npc_from_archetype(role, overrides) is the pure rules-engine instantiator: it
merges an archetype's template defaults UNDER per-NPC overrides into an Npc-shaped stat
block dict (combat_stats/services emitted as plain dicts via asdict so combat_init.py's
.get() chain works). Consumed by M6.2's settlement generation.

Generic field validation comes from the shared catalog_parse module; only the
domain-specific parsers stay here. This preserves cross-language parity with the TS loader
(apps/server/src/role_archetypes.ts, story-003) — the role_archetypes.json row IS the
contract, and a malformed row must reject identically on both sides.
"""

import json
import logging
from dataclasses import asdict, dataclass

from catalog_parse import (
    parse_attributes,
    parse_int,
    parse_number,
    parse_str,
    parse_str_tuple,
)

logger = logging.getLogger("divineruin.role_archetypes")


@dataclass(frozen=True)
class CombatAction:
    name: str
    damage: str
    damage_type: str
    properties: tuple[str, ...]
    effect: str | None = None


@dataclass(frozen=True)
class CombatStats:
    level: int
    hp: int
    ac: int
    attributes: dict[str, int]
    action_pool: tuple[CombatAction, ...]
    save_proficiencies: tuple[str, ...] = ()
    passives: tuple[str, ...] = ()
    actives: tuple[str, ...] = ()


@dataclass(frozen=True)
class CombatVariant:
    name: str
    level: int
    hp: int | None = None
    ac: int | None = None
    action_pool: tuple[CombatAction, ...] = ()
    passives: tuple[str, ...] = ()
    actives: tuple[str, ...] = ()
    notes: str | None = None


@dataclass(frozen=True)
class ArchetypeService:
    name: str
    cost: int | float | dict[str, int | float]
    cost_unit: str
    time_to_complete: str | None = None
    requirements: dict[str, str] | None = None
    description: str | None = None


@dataclass(frozen=True)
class RoleArchetype:
    id: str
    name: str
    role_type: str
    default_disposition: str
    knowledge_domains: tuple[str, ...]
    services: tuple[ArchetypeService, ...]
    inventory_pool: str | None
    price_modifier: float
    combat_stats: CombatStats | None
    combat_variants: tuple[CombatVariant, ...] = ()


_role_archetypes: dict[str, RoleArchetype] = {}

_ROLE_TYPES = ("civilian", "military", "specialist")
# Canonical 5-tier disposition ladder — the single Python SSOT (mirrors the TS
# DISPOSITION_VALUES home in role_archetype.ts). npcs.py and tool_support.py import
# this so a tier change touches one place, not three.
DISPOSITIONS = ("hostile", "unfriendly", "neutral", "friendly", "trusted")


# --- domain-specific parse helpers (generic primitives come from catalog_parse) ---


def _parse_action(raw: object, ctx: str) -> CombatAction:
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx} is not an object")
    effect = raw.get("effect")
    return CombatAction(
        name=parse_str(raw["name"], f"{ctx}.name"),
        damage=parse_str(raw["damage"], f"{ctx}.damage"),
        damage_type=parse_str(raw["damage_type"], f"{ctx}.damage_type"),
        properties=parse_str_tuple(raw["properties"], f"{ctx}.properties"),
        effect=None if effect is None else parse_str(effect, f"{ctx}.effect"),
    )


def _parse_combat_stats(raw: object, ctx: str) -> CombatStats | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx} is not an object or null")
    actions = raw["action_pool"]
    if not isinstance(actions, list):
        raise ValueError(f"{ctx}.action_pool is not a list")
    return CombatStats(
        level=parse_int(raw["level"], f"{ctx}.level"),
        hp=parse_int(raw["hp"], f"{ctx}.hp"),
        ac=parse_int(raw["ac"], f"{ctx}.ac"),
        attributes=parse_attributes(raw["attributes"], f"{ctx}.attributes"),
        action_pool=tuple(_parse_action(a, f"{ctx}.action_pool[{i}]") for i, a in enumerate(actions)),
        save_proficiencies=parse_str_tuple(raw.get("save_proficiencies", []), f"{ctx}.save_proficiencies"),
        passives=parse_str_tuple(raw.get("passives", []), f"{ctx}.passives"),
        actives=parse_str_tuple(raw.get("actives", []), f"{ctx}.actives"),
    )


def _parse_variant(raw: object, ctx: str) -> CombatVariant:
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx} is not an object")
    actions = raw.get("action_pool", [])
    if not isinstance(actions, list):
        raise ValueError(f"{ctx}.action_pool is not a list")
    notes = raw.get("notes")
    return CombatVariant(
        name=parse_str(raw["name"], f"{ctx}.name"),
        level=parse_int(raw["level"], f"{ctx}.level"),
        hp=None if raw.get("hp") is None else parse_int(raw["hp"], f"{ctx}.hp"),
        ac=None if raw.get("ac") is None else parse_int(raw["ac"], f"{ctx}.ac"),
        action_pool=tuple(_parse_action(a, f"{ctx}.action_pool[{i}]") for i, a in enumerate(actions)),
        passives=parse_str_tuple(raw.get("passives", []), f"{ctx}.passives"),
        actives=parse_str_tuple(raw.get("actives", []), f"{ctx}.actives"),
        notes=None if notes is None else parse_str(notes, f"{ctx}.notes"),
    )


def _parse_service(raw: object, ctx: str) -> ArchetypeService:
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx} is not an object")
    cost = raw["cost"]
    if isinstance(cost, dict):
        cost = {
            "min": parse_number(cost["min"], f"{ctx}.cost.min"),
            "max": parse_number(cost["max"], f"{ctx}.cost.max"),
        }
    else:
        cost = parse_number(cost, f"{ctx}.cost")
    reqs = raw.get("requirements")
    if reqs is not None and not isinstance(reqs, dict):
        raise ValueError(f"{ctx}.requirements is not an object or null")
    ttc = raw.get("time_to_complete")
    desc = raw.get("description")
    return ArchetypeService(
        name=parse_str(raw["name"], f"{ctx}.name"),
        cost=cost,
        cost_unit=parse_str(raw["cost_unit"], f"{ctx}.cost_unit"),
        time_to_complete=None if ttc is None else parse_str(ttc, f"{ctx}.time_to_complete"),
        requirements=reqs,
        description=None if desc is None else parse_str(desc, f"{ctx}.description"),
    )


def parse_role_archetype_row(archetype_id: str, data: dict) -> RoleArchetype:
    """Parse a raw dict (JSON file or DB JSONB) into a RoleArchetype, fail-loud.

    Shared by load_role_archetypes (DB) and the JSON test fixture. Wraps the
    underlying error with the row id for context.
    """
    try:
        role_type = parse_str(data["role_type"], f"{archetype_id}.role_type")
        if role_type not in _ROLE_TYPES:
            raise ValueError(f"{archetype_id}.role_type {role_type!r} not in {_ROLE_TYPES}")
        disposition = parse_str(data["default_disposition"], f"{archetype_id}.default_disposition")
        if disposition not in DISPOSITIONS:
            raise ValueError(f"{archetype_id}.default_disposition {disposition!r} not in {DISPOSITIONS}")
        inv = data["inventory_pool"]
        if inv is not None and not isinstance(inv, str):
            raise ValueError(f"{archetype_id}.inventory_pool is not a string or null")
        services = data["services"]
        if not isinstance(services, list):
            raise ValueError(f"{archetype_id}.services is not a list")
        variants = data.get("combat_variants", [])
        if not isinstance(variants, list):
            raise ValueError(f"{archetype_id}.combat_variants is not a list")
        return RoleArchetype(
            id=archetype_id,
            name=parse_str(data["name"], f"{archetype_id}.name"),
            role_type=role_type,
            default_disposition=disposition,
            knowledge_domains=parse_str_tuple(data["knowledge_domains"], f"{archetype_id}.knowledge_domains"),
            services=tuple(_parse_service(s, f"{archetype_id}.services[{i}]") for i, s in enumerate(services)),
            inventory_pool=inv,
            price_modifier=parse_number(data["price_modifier"], f"{archetype_id}.price_modifier"),
            combat_stats=_parse_combat_stats(data["combat_stats"], f"{archetype_id}.combat_stats"),
            combat_variants=tuple(
                _parse_variant(v, f"{archetype_id}.combat_variants[{i}]") for i, v in enumerate(variants)
            ),
        )
    except (KeyError, TypeError) as e:
        raise ValueError(f"Malformed role_archetypes row {archetype_id!r}: {e}") from e


def set_role_archetypes(config: dict[str, RoleArchetype]) -> None:
    """Test seam: populate _role_archetypes directly without going through the DB."""
    _role_archetypes.clear()
    _role_archetypes.update(config)


def get_role_archetype(role: str) -> RoleArchetype:
    """Return the archetype for a role id. Raises ValueError if not loaded/unknown."""
    if role not in _role_archetypes:
        raise ValueError(f"Unknown role archetype: {role!r}")
    return _role_archetypes[role]


def is_loaded() -> bool:
    """True once the catalog has been populated (startup load or test seam)."""
    return bool(_role_archetypes)


def _jsonable(value: object) -> object:
    """Recursively normalize a structure to JSON shapes (tuple -> list).

    asdict() preserves the dataclasses' immutable tuple fields as tuples; content
    NPCs (content/npcs.json) and combat_init.py expect list-shaped action_pool/services,
    so the emitted stat block normalizes tuples to lists.
    """
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def create_npc_from_archetype(role: str, overrides: dict | None = None) -> dict:
    """Build a complete NPC stat-block dict from a role archetype template.

    Sources combat/economy/disposition/knowledge from the archetype and shallow-merges
    `overrides` ON TOP (overrides win; they supply per-NPC identity fields like id, name,
    species, knowledge, schedule, faction, voice_id). combat_stats/services/combat_variants
    are emitted as plain dicts (via asdict) so combat_init.py and the content consumers read
    them like a content/npcs.json row. Raises ValueError for an unknown role.

    Shallow merge is intentional for M6.1: a per-NPC override of combat_stats replaces the
    whole block. A future deep/partial-override need (M6.2) can layer on top.
    """
    archetype = get_role_archetype(role)
    stat_block: dict = {
        "role_archetype": archetype.id,
        "default_disposition": archetype.default_disposition,
        "inventory_pool": archetype.inventory_pool,
        "price_modifier": archetype.price_modifier,
        "services": [asdict(s) for s in archetype.services],
        "knowledge_domains": list(archetype.knowledge_domains),
        "combat_stats": asdict(archetype.combat_stats) if archetype.combat_stats else None,
        "combat_variants": [asdict(v) for v in archetype.combat_variants],
    }
    if overrides:
        stat_block.update(overrides)
    return _jsonable(stat_block)  # type: ignore[return-value]


async def load_role_archetypes() -> None:
    """Load the role archetype catalog from the DB into _role_archetypes.

    Called at agent + async-worker startup beside load_mentor_variants(). Fails loud if the
    query or a row errors. Builds a local dict then swaps in one synchronous step (no await
    between), so a malformed row fails loud WITHOUT wiping an already-loaded map and a
    concurrent get_role_archetype never observes a half-populated map.
    """
    import db

    pool = await db.get_pool()
    rows = await pool.fetch("SELECT id, data FROM role_archetypes")
    loaded: dict[str, RoleArchetype] = {}
    for row in rows:
        data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
        loaded[row["id"]] = parse_role_archetype_row(row["id"], data)
    _role_archetypes.clear()
    _role_archetypes.update(loaded)
    logger.info("Loaded %d role archetypes", len(_role_archetypes))
