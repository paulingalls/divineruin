"""Authored encounter references shared by seed preflight and combat entry."""

REFERENCE_FIELDS = frozenset({"id", "creature_id", "role"})
REFERENCE_ROLES = frozenset({"minion", "standard", "elite", "boss"})


def validate_encounter_references(encounter: dict, creature_ids=None) -> None:
    label = f"encounter {encounter.get('id')!r}"
    level = encounter.get("recommended_party_level")
    if type(level) is not int or not 1 <= level <= 20:
        raise ValueError(f"{label}: recommended_party_level must be an integer 1-20")
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
            enemy["role"] == "named" and enemy["creature_id"] == "hollow_choir"
        ):
            raise ValueError(f"{context}: unsupported role {enemy['role']!r}")
        if creature_ids is not None and enemy["creature_id"] not in creature_ids:
            raise ValueError(f"{context}: unknown creature_id {enemy['creature_id']!r}")

    if any(enemy["creature_id"] == "hollow_choir" for enemy in enemies) and len(enemies) != 1:
        raise ValueError(f"{label}: the Choir is solitary and must have one damage/reward owner")
