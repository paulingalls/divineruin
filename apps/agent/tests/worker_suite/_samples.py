"""Shared sample fixtures for the async-worker test suite."""

SAMPLE_ACTIVITY = {
    "id": "activity_abc123",
    "player_id": "player_1",
    "status": "in_progress",
    "activity_type": "crafting",
    "parameters": {
        "recipe_id": "iron_sword",
        "result_item_id": "iron_sword",
        "result_item_name": "Iron Sword",
        "required_materials": ["iron_ingot", "leather_strip"],
        "skill": "arcana",
        "dc": 13,
        "npc_id": "grimjaw_blacksmith",
        # story-005 resolution gate inputs (captured at creation).
        "workspace_required": "forge",
        "workspace_access": ["field", "forge"],
        "crafting_tier": "expert",
        "tainted_materials": False,
    },
    "resolve_at": "2026-01-01T00:00:00Z",
}

SAMPLE_PLAYER = {
    "name": "Aldric",
    "level": 3,
    "class": "warrior",
    "attributes": {
        "strength": 14,
        "dexterity": 12,
        "constitution": 13,
        "intelligence": 10,
        "wisdom": 11,
        "charisma": 8,
    },
    "proficiencies": ["athletics", "arcana"],
}

# story-003: the worker's crafting branch delegates to crafting_resolution, which fetches
# the recipe category + that category's quality_outcomes row before calling the pure
# resolver. This is the return value the conftest _stub_crafting_worker_db fixture feeds
# get_quality_outcomes, so the worker tests exercise the real resolver (gates, bands)
# without a database — only the table fetch is mocked.
_WEAPON_QUALITY = {
    "id": "weapon",
    "bonus_properties": [{"id": "keen_edge", "name": "Keen Edge", "description": "It hums when it cuts."}],
    "flaws": [{"id": "dull_bite", "name": "Dull Bite", "description": "The edge drags."}],
}
