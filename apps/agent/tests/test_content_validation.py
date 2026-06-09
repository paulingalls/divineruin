"""Tests for content JSON validation — cross-references, schema integrity (WU4)."""

import json
import re
from pathlib import Path

import pytest

CONTENT_DIR = Path(__file__).parent.parent.parent.parent / "content"

EFFECT_NPC_MAP = {
    "torin": "guildmaster_torin",
    "yanna": "elder_yanna",
    "emris": "scholar_emris",
    "companion": "companion_kael",
}


def _load_json(filename: str) -> list[dict]:
    path = CONTENT_DIR / filename
    if not path.exists():
        pytest.skip(f"{filename} not found")
    return json.loads(path.read_text())


def _load_ids(filename: str, id_field: str = "id") -> set[str]:
    return {entity[id_field] for entity in _load_json(filename)}


class TestContentCrossReferences:
    def test_encounter_ids_referenced_by_quests_exist(self):
        encounter_ids = _load_ids("encounter_templates.json")
        quests = _load_json("quests.json")

        for quest in quests:
            for stage in quest.get("stages", []):
                cc = stage.get("completion_conditions", {})
                encounter_ref = cc.get("encounter")
                if encounter_ref:
                    assert encounter_ref in encounter_ids, (
                        f"Quest '{quest['id']}' stage '{stage.get('id', '?')}' "
                        f"references unknown encounter '{encounter_ref}'"
                    )

    def test_item_ids_in_quest_rewards_exist(self):
        item_ids = _load_ids("items.json")
        quests = _load_json("quests.json")

        for quest in quests:
            for stage in quest.get("stages", []):
                on_complete = stage.get("on_complete", {})
                for reward in on_complete.get("rewards", []):
                    reward_item = reward.get("item") or reward.get("item_id")
                    if reward_item:
                        assert reward_item in item_ids, (
                            f"Quest '{quest['id']}' stage '{stage.get('id', '?')}' "
                            f"references unknown reward item '{reward_item}'"
                        )

    def test_item_ids_in_quest_completion_conditions_exist(self):
        item_ids = _load_ids("items.json")
        quests = _load_json("quests.json")

        for quest in quests:
            for stage in quest.get("stages", []):
                cc = stage.get("completion_conditions", {})
                for item_ref in cc.get("items", []):
                    assert item_ref in item_ids, (
                        f"Quest '{quest['id']}' stage '{stage.get('id', '?')}' "
                        f"references unknown item '{item_ref}' in completion_conditions"
                    )

    def test_npc_shorthand_in_world_effects_resolves(self):
        npc_ids = _load_ids("npcs.json")
        quests = _load_json("quests.json")

        for quest in quests:
            for stage in quest.get("stages", []):
                on_complete = stage.get("on_complete", {})
                for effect in on_complete.get("world_effects", []):
                    m = re.match(r"^(\w+)_disposition\s*[+-]\d+$", effect)
                    if m:
                        shorthand = m.group(1)
                        resolved = EFFECT_NPC_MAP.get(shorthand, shorthand)
                        assert resolved in npc_ids, (
                            f"Quest '{quest['id']}' world_effect '{effect}' references unknown NPC '{resolved}'"
                        )

    def test_location_exits_reference_valid_destinations(self):
        locations = _load_json("locations.json")
        location_ids = {loc["id"] for loc in locations}

        for loc in locations:
            for direction, exit_info in loc.get("exits", {}).items():
                dest = exit_info.get("destination") if isinstance(exit_info, dict) else exit_info
                assert dest in location_ids, (
                    f"Location '{loc['id']}' exit '{direction}' references unknown destination '{dest}'"
                )

    def test_faction_leaders_resolve_to_real_npc_or_null(self):
        # A faction's leader is either null (leader not modeled as an NPC yet) or a real
        # npcs.json id — no dangling references (story-005 close-review concern 34d6eb85a088).
        npc_ids = _load_ids("npcs.json")
        for faction in _load_json("factions.json"):
            leader = faction.get("leader")
            assert leader is None or leader in npc_ids, (
                f"Faction '{faction['id']}' leader '{leader}' is neither null nor a known NPC"
            )


class TestContentIntegrity:
    def test_all_npcs_have_knowledge_tiers(self):
        npcs = _load_json("npcs.json")
        for npc in npcs:
            knowledge = npc.get("knowledge", {})
            tier_count = sum(1 for k in knowledge if k in ("free", "disposition >= friendly", "disposition >= trusted"))
            assert tier_count >= 2, f"NPC '{npc['id']}' has only {tier_count} knowledge tier(s), expected >= 2"

    def test_encounter_templates_have_enemies(self):
        encounters = _load_json("encounter_templates.json")
        for enc in encounters:
            assert len(enc.get("enemies", [])) > 0, f"Encounter '{enc['id']}' has no enemies"

    def test_items_have_required_fields(self):
        items = _load_json("items.json")
        for item in items:
            assert "id" in item, f"Item missing 'id': {item.get('name', '?')}"
            assert "name" in item, f"Item '{item['id']}' missing 'name'"
            assert "type" in item, f"Item '{item['id']}' missing 'type'"

    def test_hollow_patrol_greyvale_exists(self):
        encounter_ids = _load_ids("encounter_templates.json")
        assert "hollow_patrol_greyvale" in encounter_ids

    def test_ruins_guardian_exists(self):
        encounter_ids = _load_ids("encounter_templates.json")
        assert "ruins_guardian" in encounter_ids

    def test_required_items_exist(self):
        item_ids = _load_ids("items.json")
        required = [
            "ruins_journal_fragment",
            "guild_contract_greyvale",
            "healing_potion",
            "hollow_ward_charm",
            "millhaven_provisions",
        ]
        for item_id in required:
            assert item_id in item_ids, f"Required item '{item_id}' not found"

    def test_required_npcs_exist(self):
        npc_ids = _load_ids("npcs.json")
        required = ["wounded_rider", "innkeeper_maren", "faction_investigator_valdris"]
        for npc_id in required:
            assert npc_id in npc_ids, f"Required NPC '{npc_id}' not found"

    def test_greyvale_quest_has_5_stages(self):
        quests = _load_json("quests.json")
        greyvale = next((q for q in quests if q["id"] == "greyvale_anomaly"), None)
        assert greyvale is not None, "greyvale_anomaly quest not found"
        assert len(greyvale["stages"]) == 5, f"Expected 5 stages, got {len(greyvale['stages'])}"

    def test_all_locations_have_region_type(self):
        locations = _load_json("locations.json")
        valid_types = {"city", "wilderness", "dungeon"}
        for loc in locations:
            assert "region_type" in loc, f"Location '{loc['id']}' missing 'region_type'"
            assert loc["region_type"] in valid_types, (
                f"Location '{loc['id']}' has invalid region_type '{loc['region_type']}', expected one of {valid_types}"
            )


# Phase 6 / M6.2 (story-005): the 4 humanoid-faction hostile encounters + the Ashmark Patrol
# reputation-gated stance.
_ENEMY_REQUIRED_FIELDS = (
    "id",
    "name",
    "level",
    "ac",
    "hp",
    "attributes",
    "action_pool",
    "xp_value",
    "sound_signature",
)
_ATTRIBUTE_KEYS = ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma")
# Fixed inline compositions within the audit-spec ranges.
_NEW_ENCOUNTER_ENEMY_COUNTS = {
    "bandit_ambush": 5,  # 4 Bandits + 1 Bandit Captain
    "ashmark_patrol": 5,  # 4 Ashmark Soldiers + 1 Ashmark Sergeant
    "cult_cell": 7,  # 2 Cult Fanatics + 4 Cultists + 1 Cult Leader
    "hollow_corrupted_settlement": 10,  # 1 Hollowed Knight + 3 Mawlings + 6 Shadelings
}


class TestM62HostileEncounters:
    def _encounters(self) -> dict[str, dict]:
        return {e["id"]: e for e in _load_json("encounter_templates.json")}

    def _factions(self) -> dict[str, dict]:
        return {f["id"]: f for f in _load_json("factions.json")}

    def test_four_new_encounters_exist_with_expected_enemy_counts(self):
        encs = self._encounters()
        for eid, count in _NEW_ENCOUNTER_ENEMY_COUNTS.items():
            assert eid in encs, f"missing encounter '{eid}'"
            assert len(encs[eid]["enemies"]) == count, (
                f"encounter '{eid}' expected {count} enemies, got {len(encs[eid]['enemies'])}"
            )

    def test_new_encounter_enemies_have_full_stat_blocks(self):
        encs = self._encounters()
        for eid in _NEW_ENCOUNTER_ENEMY_COUNTS:
            for enemy in encs[eid]["enemies"]:
                for field in _ENEMY_REQUIRED_FIELDS:
                    assert field in enemy, f"'{eid}' enemy '{enemy.get('id', '?')}' missing '{field}'"
                for attr in _ATTRIBUTE_KEYS:
                    assert attr in enemy["attributes"], f"'{eid}' enemy '{enemy['id']}' attributes missing '{attr}'"
                assert len(enemy["action_pool"]) > 0, f"'{eid}' enemy '{enemy['id']}' has no actions"

    def test_thornwatch_faction_exists_with_reputation_tiers(self):
        factions = self._factions()
        assert "thornwatch" in factions, "thornwatch faction not found in factions.json"
        tiers = factions["thornwatch"]["reputation_tiers"]
        assert "friendly" in tiers, "thornwatch reputation_tiers missing 'friendly'"
        assert "threshold" in tiers["friendly"]

    def test_ashmark_patrol_stance_gate_references_real_faction_and_tier(self):
        gate = self._encounters()["ashmark_patrol"]["stance_gate"]
        factions = self._factions()
        assert gate["faction"] in factions, f"stance_gate faction '{gate['faction']}' not in factions.json"
        tiers = factions[gate["faction"]]["reputation_tiers"]
        assert gate["allied_at_or_above"] in tiers, (
            f"stance_gate tier '{gate['allied_at_or_above']}' not in {gate['faction']} reputation_tiers"
        )

    def test_ashmark_stance_resolves_allied_high_hostile_low(self):
        from encounter_stance import resolve_encounter_stance

        gate = self._encounters()["ashmark_patrol"]["stance_gate"]
        tiers = self._factions()[gate["faction"]]["reputation_tiers"]
        assert resolve_encounter_stance(gate, 25, tiers) == "allied"
        assert resolve_encounter_stance(gate, -10, tiers) == "hostile"
