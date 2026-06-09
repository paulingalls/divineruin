"""Tests for the role_archetypes content loader + instantiator (Phase 6 M6.1 / story-002).

The loader mirrors apps/agent/mentor_variants.py: fail-loud parse of the
content/role_archetypes.json catalog into frozen RoleArchetype dataclasses, a
module-global dict with a set_* test seam, and a build-then-swap async DB loader.
create_npc_from_archetype is the pure rules-engine instantiator (tested in the
companion instantiator suite). These loader tests own the parse + accessor contract.
"""

import json
from pathlib import Path

import pytest

import role_archetypes
from role_archetypes import (
    RoleArchetype,
    create_npc_from_archetype,
    get_role_archetype,
    is_loaded,
    parse_role_archetype_row,
    set_role_archetypes,
)

_CONTENT_PATH = Path(__file__).resolve().parents[3] / "content" / "role_archetypes.json"
_RAW = json.loads(_CONTENT_PATH.read_text())

_COMBATANTS = {"guard", "soldier_ashmark", "assassin_rogue", "mage", "priest"}
_NON_COMBATANTS = {"scholar_sage", "stablemaster"}


def _row(rid: str) -> dict:
    return next(e for e in _RAW if e["id"] == rid)


class TestParse:
    def test_all_19_rows_parse(self):
        parsed = [parse_role_archetype_row(e["id"], e) for e in _RAW]
        assert len(parsed) == 19
        assert all(isinstance(a, RoleArchetype) for a in parsed)

    def test_combatants_carry_combat_stats(self):
        for rid in _COMBATANTS:
            a = parse_role_archetype_row(rid, _row(rid))
            assert a.combat_stats is not None
            assert isinstance(a.combat_stats.hp, int)
            assert a.combat_stats.action_pool  # non-empty

    def test_non_combatants_have_null_combat_stats(self):
        for rid in _NON_COMBATANTS:
            a = parse_role_archetype_row(rid, _row(rid))
            assert a.combat_stats is None

    def test_missing_required_field_fails_loud(self):
        bad = {k: v for k, v in _row("guard").items() if k != "default_disposition"}
        with pytest.raises(ValueError, match="guard"):
            parse_role_archetype_row("guard", bad)

    def test_wrong_typed_field_fails_loud(self):
        bad = {**_row("blacksmith"), "price_modifier": "cheap"}
        with pytest.raises(ValueError, match="blacksmith"):
            parse_role_archetype_row("blacksmith", bad)

    def test_malformed_nested_combat_stats_fails_loud(self):
        bad = {**_row("guard"), "combat_stats": {"hp": "lots", "ac": 14}}
        with pytest.raises(ValueError, match="guard"):
            parse_role_archetype_row("guard", bad)

    def test_malformed_service_fails_loud(self):
        bad = {**_row("innkeeper"), "services": [{"name": "lodging"}]}  # missing cost/cost_unit
        with pytest.raises(ValueError, match="innkeeper"):
            parse_role_archetype_row("innkeeper", bad)


class TestAccessors:
    def test_get_role_archetype_returns_loaded(self):
        # The autouse seed_role_archetypes fixture (conftest) populated the catalog.
        assert is_loaded()
        guard = get_role_archetype("guard")
        assert guard.id == "guard"
        assert guard.role_type == "military"

    def test_get_unknown_role_fails_loud(self):
        with pytest.raises(ValueError, match="unknown_role"):
            get_role_archetype("unknown_role")

    def test_set_role_archetypes_seam(self):
        only = {"guard": parse_role_archetype_row("guard", _row("guard"))}
        set_role_archetypes(only)
        assert is_loaded()
        assert get_role_archetype("guard").id == "guard"
        with pytest.raises(ValueError):
            get_role_archetype("blacksmith")
        # restore the full catalog for any later test in this module
        set_role_archetypes({e["id"]: parse_role_archetype_row(e["id"], e) for e in _RAW})

    def test_module_globals_present(self):
        assert hasattr(role_archetypes, "load_role_archetypes")
        assert hasattr(role_archetypes, "create_npc_from_archetype")


class TestCreateNpcFromArchetype:
    def test_every_archetype_produces_a_stat_block(self):
        for e in _RAW:
            npc = create_npc_from_archetype(e["id"])
            assert npc["role_archetype"] == e["id"]
            assert "default_disposition" in npc
            assert "inventory_pool" in npc
            assert "price_modifier" in npc
            assert isinstance(npc["services"], list)
            assert isinstance(npc["knowledge_domains"], list)

    def test_combatants_emit_combat_stats_as_plain_dict(self):
        for rid in _COMBATANTS:
            npc = create_npc_from_archetype(rid)
            cs = npc["combat_stats"]
            assert isinstance(cs, dict)  # plain dict, not a dataclass
            # combat_init.py-style consumption must work.
            assert isinstance(cs.get("hp"), int)
            assert isinstance(cs.get("ac"), int)
            assert isinstance(cs.get("attributes"), dict)
            assert isinstance(cs.get("action_pool"), list)

    def test_non_combatants_emit_null_combat_stats(self):
        for rid in _NON_COMBATANTS:
            assert create_npc_from_archetype(rid)["combat_stats"] is None

    def test_combat_variants_propagated_when_present(self):
        # guard carries an Elite Guard combat_variant; it must survive into the stat block.
        npc = create_npc_from_archetype("guard")
        assert isinstance(npc["combat_variants"], list)
        assert any(v["name"] == "Elite Guard" for v in npc["combat_variants"])

    def test_overrides_win_and_supply_identity(self):
        npc = create_npc_from_archetype(
            "blacksmith",
            {"id": "grimjaw_blacksmith", "name": "Grimjaw", "default_disposition": "friendly"},
        )
        assert npc["id"] == "grimjaw_blacksmith"
        assert npc["name"] == "Grimjaw"
        assert npc["default_disposition"] == "friendly"  # override beats archetype "neutral"
        assert npc["role_archetype"] == "blacksmith"  # archetype link still recorded

    def test_tuple_carrying_override_normalizes_to_list(self):
        # _jsonable must run AFTER the override merge: a tuple supplied by an override
        # is normalized to a list, honoring the docstring's normalize-to-lists promise.
        npc = create_npc_from_archetype("guard", {"knowledge_domains": ("a", "b")})
        assert npc["knowledge_domains"] == ["a", "b"]
        assert isinstance(npc["knowledge_domains"], list)

    def test_unknown_role_fails_loud(self):
        with pytest.raises(ValueError, match="unknown_role"):
            create_npc_from_archetype("unknown_role")
