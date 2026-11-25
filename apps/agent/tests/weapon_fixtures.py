"""Weapon shapes for combat fixtures with scripted damage."""

LONGSWORD = {
    "name": "Longsword",
    "damage": "1d8",
    "damage_type": "slashing",
    "properties": ["versatile"],
    "weapon_category": "martial",
    "weapon_range": "melee",
    "weapon_kind": "longsword",
}
SHORTBOW = {
    "name": "Shortbow",
    "damage": "1d6",
    "damage_type": "piercing",
    "properties": ["two-handed", "ammunition"],
    "weapon_category": "simple",
    "weapon_range": "ranged",
    "weapon_kind": "shortbow",
    "ranged": True,
}
DAGGER = {
    "name": "Training Blade",
    "damage": "1d8",
    "damage_type": "slashing",
    "properties": ["finesse", "light", "thrown"],
    "weapon_category": "simple",
    "weapon_range": "melee",
    "weapon_kind": "dagger",
    "governing_attribute": "strength",
}
QUARTERSTAFF = {
    "name": "Quarterstaff",
    "damage": "1d8",
    "damage_type": "bludgeoning",
    "properties": ["versatile"],
    "weapon_category": "simple",
    "weapon_range": "melee",
    "weapon_kind": "quarterstaff",
}
