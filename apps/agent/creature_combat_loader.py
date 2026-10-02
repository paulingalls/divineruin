"""Load a single catalog creature without coupling translation to storage."""

import creature_catalog
from creature_combat import translate_creature


async def load_creature_enemy(creature_id, *, encounter_id, enemy_id, role):
    context = f"creature {creature_id!r}, encounter {encounter_id!r}, enemy {enemy_id!r}"
    if not isinstance(creature_id, str) or not creature_id.strip():
        raise ValueError(f"{context}: creature_id must be nonempty")
    try:
        row = await creature_catalog.query_creature_by_id(creature_id)
    except (creature_catalog.CreatureNotFoundError, ValueError) as exc:
        raise ValueError(f"{context}: catalog lookup failed: {exc}") from exc
    if not isinstance(row, dict) or row.get("id") != creature_id:
        raise ValueError(f"{context}: catalog identity mismatch")
    return translate_creature(row, encounter_id=encounter_id, enemy_id=enemy_id, role=role)
