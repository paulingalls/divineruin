import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sample_fixtures import make_context

from item_effects import CombatItemTraits, combat_traits
from query_tools import _query_inventory_impl

ITEMS_PATH = Path(__file__).parents[3] / "content" / "items.json"

STRUCTURED = {
    "cloak_steppe_winds": {"advantage_vs": ["prone", "push"]},
    "choirs_silence": {"condition_immunities": ["charmed", "frightened"]},
    "stillheart": {
        "condition_immunities": ["charmed"],
        "save_advantages": ["wisdom"],
    },
}

EXPECTED_TRAITS = {
    "cloak_steppe_winds": CombatItemTraits(
        advantage_vs={"prone": "Cloak of the Steppe Winds", "push": "Cloak of the Steppe Winds"}
    ),
    "choirs_silence": CombatItemTraits(
        condition_immunities={"charmed": "Choir's Silence", "frightened": "Choir's Silence"}
    ),
    "stillheart": CombatItemTraits(
        condition_immunities={"charmed": "Stillheart"},
        save_advantages={"wisdom": "Stillheart"},
    ),
}

DESCRIPTION_ONLY = {
    "backpack",
    "bedroll",
    "lantern_hooded",
    "oil_flask",
    "grappling_hook",
    "healers_kit",
    "thieves_tools",
    "climbing_kit",
    "tent_two",
    "ink_quill",
    "crystal_flask",
    "holy_symbol",
    "arcane_focus",
    "waterskin_full",
    "resonance_stabilizer",
    "anti_hollow_oil",
    "smoke_bomb",
    "lockpicks",
    "artificers_portable_lab",
    "veil_ward_anchor_small",
    "veil_ward_anchor_large",
    "veil_sight_lens",
    "ring_resonance_dampening",
    "potion_veil_walking",
    "climbers_kit",
    "healers_satchel",
    "ward_stone",
    "enchant_sharpen",
    "enchant_reinforce",
    "enchant_balance",
    "enchant_fireproof",
    "enchant_silk_grip",
    "enchant_minor",
    "enchant_elemental",
    "enchant_hollow_bane",
    "enchant_resonance_dampener",
    "enchant_supreme",
}


def _items():
    return {item["id"]: item for item in json.loads(ITEMS_PATH.read_text())}


def test_first_slice_has_exact_structured_effects_and_required_attunement():
    items = _items()
    for item_id, expected in STRUCTURED.items():
        item = items[item_id]
        assert item["attunement"] == {"kind": "required"}
        actual = {key: item["effects"][0][key] for key in expected}
        assert actual == expected
        assert combat_traits([item]) == EXPECTED_TRAITS[item_id]


def test_every_other_utility_effect_is_explicitly_description_only():
    items = _items()
    utility_ids = {
        item_id
        for item_id, item in items.items()
        if any(effect.get("type") == "utility" for effect in item.get("effects", []))
    }
    assert utility_ids == DESCRIPTION_ONLY | set(STRUCTURED)
    for item_id in DESCRIPTION_ONLY:
        for effect in items[item_id]["effects"]:
            assert not ({"condition_immunities", "save_advantages", "advantage_vs"} & effect.keys())
    assert combat_traits([items[item_id] for item_id in DESCRIPTION_ONLY]) == CombatItemTraits()


@pytest.mark.parametrize(
    ("effect", "message"),
    [
        ({"condition_immunities": "charmed"}, "must be a list"),
        ({"condition_immunities": [1]}, "must be a string"),
        ({"condition_immunities": ["charmd"]}, "unknown token 'charmd'"),
        ({"save_advantages": "wisdom"}, "must be a list"),
        ({"save_advantages": [1]}, "must be a string"),
        ({"save_advantages": ["luck"]}, "unknown token 'luck'"),
        ({"advantage_vs": "push"}, "must be a list"),
        ({"advantage_vs": [1]}, "must be a string"),
        ({"advantage_vs": ["trip"]}, "unknown token 'trip'"),
    ],
)
def test_python_fold_rejects_malformed_structured_effects_with_context(effect, message):
    with pytest.raises(ValueError, match=rf"Bad Charm.*effects\[0\].*{message}"):
        combat_traits([{"name": "Bad Charm", "effects": [{"type": "utility", **effect}]}])


def test_fold_joins_duplicate_sources_deterministically():
    inventory = [
        {"name": "Zeta", "effects": [{"condition_immunities": ["charmed"]}]},
        {"name": "Alpha", "effects": [{"condition_immunities": ["charmed"]}]},
        {"name": "Alpha", "effects": [{"condition_immunities": ["charmed"]}]},
    ]
    assert combat_traits(inventory).condition_immunities == {"charmed": "Alpha, Zeta"}


@pytest.mark.asyncio
async def test_description_only_effects_reach_dm_verbatim():
    items = _items()
    inventory = [items[item_id] for item_id in sorted(DESCRIPTION_ONLY)]
    queries = MagicMock(get_player_inventory=AsyncMock(return_value=inventory))

    result = json.loads(await _query_inventory_impl(make_context(), queries=queries))

    expected_by_name = {item["name"]: item for item in inventory}
    assert len(result["items"]) == len(inventory)
    for returned in result["items"]:
        source = expected_by_name[returned["name"]]
        assert returned["description"] == source.get("description")
        assert returned["effects"] == source["effects"]
