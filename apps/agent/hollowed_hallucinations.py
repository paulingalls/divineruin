"""Load Python narration content. There is no TypeScript gameplay consumer."""

import json
from random import choice
from typing import TypedDict

from condition_restrictions import hallucinations


class HallucinationEntry(TypedDict):
    id: str
    description: str


class PlayerHallucination(TypedDict):
    name: str
    description: str


def parse_hollowed_hallucination_row(entry_id: str, raw: object) -> HallucinationEntry:
    if not isinstance(entry_id, str) or not entry_id.strip():
        raise ValueError("hollowed_hallucinations requires a nonblank id")
    description = raw.get("description") if isinstance(raw, dict) else None
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"hollowed_hallucinations[{entry_id}].description must be nonblank")
    return {"id": entry_id, "description": description}


async def get_hollowed_hallucinations() -> list[HallucinationEntry]:
    """Load the whole seeded catalog for Python narration, with no TypeScript gameplay consumer."""
    # The seeder imports the parser from a separate environment without Redis.
    import db

    key = "hollowed_hallucinations:all"
    cached = await db._cache_get(key)
    if cached is not None:
        return json.loads(cached)

    pool = await db.get_pool()
    rows = await pool.fetch("SELECT id, data FROM hollowed_hallucinations ORDER BY id")
    if not rows:
        raise ValueError("hollowed_hallucinations produced no rows")
    entries = [parse_hollowed_hallucination_row(row["id"], json.loads(row["data"])) for row in rows]
    await db._cache_set(key, json.dumps(entries))
    return entries


class HallucinationSelections:
    def __init__(self) -> None:
        self._selected: dict[str, tuple[str, str]] = {}

    async def for_present_players(
        self, players: dict[str, dict], present_ids: tuple[str, ...], location_id: str
    ) -> list[PlayerHallucination]:
        entries = None
        active: list[PlayerHallucination] = []
        for pid, row in players.items():
            location = row.get("location_id")
            selected = self._selected.get(pid)
            if selected is not None and selected[0] != location:
                del self._selected[pid]
                selected = None
            if pid not in present_ids or location != location_id or not hallucinations(row.get("conditions") or []):
                continue
            if selected is None:
                if entries is None:
                    entries = await get_hollowed_hallucinations()
                selected = (location_id, choice(entries)["description"])
                self._selected[pid] = selected
            active.append({"name": row["name"], "description": selected[1]})
        return active
