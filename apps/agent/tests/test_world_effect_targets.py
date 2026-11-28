"""Assigned companions resolve at runtime; authoring validation can only check that a companion exists."""

import json
from pathlib import Path

from world_effect_targets import EFFECT_NPC_MAP, is_valid_disposition_target

CONTENT_DIR = Path(__file__).parent.parent.parent.parent / "content"


def _load_ids(filename: str) -> set[str]:
    return {entity["id"] for entity in json.loads((CONTENT_DIR / filename).read_text())}


class TestEffectNpcMap:
    def test_static_shorthands_resolve(self):
        assert EFFECT_NPC_MAP["torin"] == "guildmaster_torin"
        assert EFFECT_NPC_MAP["yanna"] == "elder_yanna"
        assert EFFECT_NPC_MAP["emris"] == "scholar_emris"

    def test_companion_is_absent_from_the_static_map(self):
        assert "companion" not in EFFECT_NPC_MAP


class TestIsValidDispositionTarget:
    def test_companion_shorthand_is_valid_whenever_any_companion_exists(self):
        npc_ids, companion_ids = _load_ids("npcs.json"), _load_ids("companions.json")
        assert is_valid_disposition_target("companion", npc_ids, companion_ids)
        assert not is_valid_disposition_target("companion", npc_ids, set())

    def test_rejects_an_unknown_target(self):
        npc_ids, companion_ids = _load_ids("npcs.json"), _load_ids("companions.json")
        assert is_valid_disposition_target("torin", npc_ids, companion_ids)
        assert is_valid_disposition_target("companion_kael", npc_ids, companion_ids)
        assert not is_valid_disposition_target("guildmaster_toren", npc_ids, companion_ids)
        assert not is_valid_disposition_target("nobody", npc_ids, companion_ids)
