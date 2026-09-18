from unittest.mock import AsyncMock, MagicMock

LOCATION_WITH_HIDDEN = {
    "id": "test_location",
    "name": "Test Location",
    "description": "A room.",
    "atmosphere": "plain",
    "key_features": [],
    "hidden_elements": [
        {
            "id": "secret_door",
            "discover_skill": "perception",
            "dc": 12,
            "description": "A hidden passage behind the bookshelf",
        }
    ],
    "exits": {},
    "tags": [],
    "conditions": {},
}

LOCATION_TWO_SECRETS = {
    **LOCATION_WITH_HIDDEN,
    "hidden_elements": [
        {"id": "hard_secret", "discover_skill": "perception", "dc": 15, "description": "A hard find"},
        {"id": "easy_secret", "discover_skill": "perception", "dc": 10, "description": "An easy find"},
    ],
}

# M6: an element bound to a visible target via attaches_to surfaces ONLY when that
# target is examined; an unannotated element is the room-wide skill-match fallback.
LOCATION_ATTACHED = {
    **LOCATION_WITH_HIDDEN,
    "hidden_elements": [
        {
            "id": "door_seal",
            "discover_skill": "arcana",
            "dc": 10,
            "description": "A ward-seal on the inner door",
            "attaches_to": "inner_door",
        }
    ],
}

LOCATION_MIXED = {
    **LOCATION_WITH_HIDDEN,
    "hidden_elements": [
        {
            "id": "door_seal",
            "discover_skill": "perception",
            "dc": 10,
            "description": "A ward-seal on the inner door",
            "attaches_to": "inner_door",
        },
        {
            "id": "loose_brick",
            "discover_skill": "perception",
            "dc": 10,
            "description": "A loose brick in the wall",
        },
    ],
}

# M6 (story-004 follow-up): attaches_to is a short token ("arch") but the warm layer
# advertises the key_feature as prose ("a cracked stone arch to the north"). Matching is
# asymmetric whole-word containment — attaches_to must appear as a whole word IN the
# examined target, so the player examines via the advertised prose; mid-word substrings
# (e.g. "arch" in "search") must NOT match.
LOCATION_ARCH = {
    **LOCATION_WITH_HIDDEN,
    "hidden_elements": [
        {
            "id": "arch_seal",
            "discover_skill": "perception",
            "dc": 10,
            "description": "A seal behind the arch",
            "attaches_to": "arch",
        }
    ],
}

DISCOVER_PLAYER = {
    "player_id": "player_1",
    "name": "Kael",
    "class": "warrior",
    "level": 1,
    "attributes": {
        "strength": 14,
        "dexterity": 12,
        "constitution": 13,
        "intelligence": 10,
        "wisdom": 16,
        "charisma": 8,
    },
    "proficiencies": ["perception", "athletics"],
    "hp": {"current": 25, "max": 25},
    "ac": 14,
    "equipment": {},
}


def _make_discover_mocks(location=LOCATION_WITH_HIDDEN, player=DISCOVER_PLAYER):
    mock_content = MagicMock()
    mock_content.get_location = AsyncMock(return_value=location)
    mock_queries = MagicMock()
    mock_queries.get_player = AsyncMock(return_value=player)
    mock_mutations = MagicMock()
    mock_mutations.set_player_flag = AsyncMock()
    return mock_content, mock_queries, mock_mutations


def _roll(total):
    from dice import DiceResult

    return DiceResult(notation="d20", rolls=[total], dropped=[], total=total)
