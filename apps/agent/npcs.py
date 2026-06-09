"""NPCs — DB-loaded content catalog (Phase 6 / M6.1, story-004).

content/npcs.json is the single source of truth for authored world NPCs. This module
is the in-memory catalog that narration and other SYNCHRONOUS consumers read at
build time, mirroring role_archetypes.py: a module-global dict populated by
load_npcs() at startup (or set_npcs() in tests), a fail-loud parse_npc_row shared by
the DB loader and the JSON test fixture, and sync accessors.

It complements the async db_content_queries.get_npc() (Valkey+Postgres, used by tool
handlers that already await): same source rows, different timing/shape. NPC records
are static content, so the catalog is loaded once and never invalidated.

Each loader owns its own fail-loud validation — the npcs.json row IS the contract.
default_disposition is validated against the canonical 5-tier ladder (parity with
role_archetypes._DISPOSITIONS), and role_archetype is required: story-004 binds every
NPC to a catalog archetype.
"""

import json
import logging

logger = logging.getLogger("divineruin.npcs")

_npcs: dict[str, dict] = {}

_DISPOSITIONS = ("hostile", "unfriendly", "neutral", "friendly", "trusted")


def _parse_str(raw: object, ctx: str) -> str:
    if not isinstance(raw, str):
        raise ValueError(f"{ctx} is not a string")
    return raw


def _parse_str_list(raw: object, ctx: str) -> list[str]:
    if not isinstance(raw, list):
        raise ValueError(f"{ctx} is not a list")
    for i, x in enumerate(raw):
        _parse_str(x, f"{ctx}[{i}]")
    return raw


def _parse_dict(raw: object, ctx: str) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx} is not an object")
    return raw


def parse_npc_row(npc_id: str, data: dict) -> dict:
    """Validate a raw NPC dict (JSON file or DB JSONB) fail-loud; return it unchanged.

    Shared by load_npcs (DB) and the JSON test fixture. Consumers read the row by key
    (npc["name"], npc["personality"], npc["knowledge"]), so the validated dict is
    returned as-is rather than wrapped in a dataclass. Wraps the underlying error with
    the row id for context.
    """
    try:
        _parse_str(data["name"], f"{npc_id}.name")
        _parse_str(data["role"], f"{npc_id}.role")
        _parse_str(data["role_archetype"], f"{npc_id}.role_archetype")
        _parse_str(data["speech_style"], f"{npc_id}.speech_style")
        _parse_str(data["voice_id"], f"{npc_id}.voice_id")
        _parse_str(data["faction"], f"{npc_id}.faction")
        _parse_str_list(data["personality"], f"{npc_id}.personality")
        _parse_dict(data["knowledge"], f"{npc_id}.knowledge")
        _parse_dict(data["schedule"], f"{npc_id}.schedule")
        disposition = _parse_str(data["default_disposition"], f"{npc_id}.default_disposition")
        if disposition not in _DISPOSITIONS:
            raise ValueError(f"{npc_id}.default_disposition {disposition!r} not in {_DISPOSITIONS}")
        return data
    except (KeyError, TypeError) as e:
        raise ValueError(f"Malformed npcs row {npc_id!r}: {e}") from e


def set_npcs(config: dict[str, dict]) -> None:
    """Test seam: populate _npcs directly without going through the DB."""
    _npcs.clear()
    _npcs.update(config)


def get_npc_sync(npc_id: str) -> dict | None:
    """Return the authored NPC record for an id, or None if unknown. Synchronous."""
    return _npcs.get(npc_id)


def is_loaded() -> bool:
    """True once the catalog has been populated (startup load or test seam)."""
    return bool(_npcs)


async def load_npcs() -> None:
    """Load the NPC catalog from the DB into _npcs.

    Called at agent + async-worker startup beside load_role_archetypes(). Fails loud if
    the query or a row errors. Builds a local dict then swaps in one synchronous step
    (no await between), so a malformed row fails loud WITHOUT wiping an already-loaded
    map and a concurrent get_npc_sync never observes a half-populated map.
    """
    import db

    pool = await db.get_pool()
    rows = await pool.fetch("SELECT id, data FROM npcs")
    loaded: dict[str, dict] = {}
    for row in rows:
        data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
        loaded[row["id"]] = parse_npc_row(row["id"], data)
    _npcs.clear()
    _npcs.update(loaded)
    logger.info("Loaded %d NPCs", len(_npcs))
