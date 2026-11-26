"""Authored encounter references shared by seed preflight and combat entry."""

from collections.abc import Collection

from encounter_testimony import Testimony

NAMED_INTEGRATIONS = frozenset({"hollow_choir", "hollow_still", "hollow_architect"})
REFERENCE_FIELDS = frozenset({"id", "creature_id", "role"})
REFERENCE_ROLES = frozenset({"minion", "standard", "elite", "boss"})


def validate_encounter_references(
    encounter: dict, creature_ids=None, *, npc_ids: Collection[str] | None = None
) -> Testimony | None:
    label = f"encounter {encounter.get('id')!r}"
    level = encounter.get("recommended_party_level")
    if type(level) is not int or not 1 <= level <= 20:
        raise ValueError(f"{label}: recommended_party_level must be an integer 1-20")
    if "recommended_party_size" in encounter:
        size = encounter["recommended_party_size"]
        if type(size) is not int or size < 1:
            raise ValueError(f"{label}: recommended_party_size must be a positive integer")
    enemies = encounter.get("enemies")
    if not isinstance(enemies, list) or not enemies:
        raise ValueError(f"{label}: enemies must be a nonempty list")
    seen = set()
    for index, enemy in enumerate(enemies):
        if not isinstance(enemy, dict):
            raise ValueError(f"{label} enemy {index}: expected reference object")
        context = f"{label} enemy {enemy.get('id', index)!r}"
        for field in ("id", "creature_id", "role"):
            value = enemy.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{context}: {field} must be a nonempty string")
        extra = set(enemy) - REFERENCE_FIELDS
        if extra:
            raise ValueError(f"{context}: forbidden reference fields {sorted(extra)}")
        if enemy["id"] in seen:
            raise ValueError(f"{context}: duplicate id")
        seen.add(enemy["id"])
        if enemy["role"] not in REFERENCE_ROLES and not (
            enemy["role"] == "named" and enemy["creature_id"] in NAMED_INTEGRATIONS
        ):
            raise ValueError(f"{context}: unsupported role {enemy['role']!r}")
        if creature_ids is not None and enemy["creature_id"] not in creature_ids:
            raise ValueError(f"{context}: unknown creature_id {enemy['creature_id']!r}")

    testimony = Testimony.from_dict(encounter, label) if "witness" in encounter or "accused" in encounter else None
    if testimony is not None:
        if npc_ids is not None and testimony.witness not in npc_ids:
            raise ValueError(f"{label}: unknown witness {testimony.witness!r}")
        for enemy_id in testimony.accused:
            if enemy_id not in seen:
                raise ValueError(f"{label}: unknown accused enemy id {enemy_id!r}")

    if any(enemy["creature_id"] in NAMED_INTEGRATIONS for enemy in enemies) and len(enemies) != 1:
        raise ValueError(f"{label}: a Named integration is solitary and must have one damage/reward owner")

    return testimony
