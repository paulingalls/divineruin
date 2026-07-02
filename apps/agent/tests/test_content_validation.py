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
        # The 'companion' shorthand resolves into the companions id space (Kael now lives in
        # companions.json, not npcs.json), so validate against the npcs + companions union.
        valid_ids = _load_ids("npcs.json") | _load_ids("companions.json")
        quests = _load_json("quests.json")

        for quest in quests:
            for stage in quest.get("stages", []):
                on_complete = stage.get("on_complete", {})
                for effect in on_complete.get("world_effects", []):
                    m = re.match(r"^(\w+)_disposition\s*[+-]\d+$", effect)
                    if m:
                        shorthand = m.group(1)
                        resolved = EFFECT_NPC_MAP.get(shorthand, shorthand)
                        assert resolved in valid_ids, (
                            f"Quest '{quest['id']}' world_effect '{effect}' references unknown target '{resolved}'"
                        )

    def test_companion_kael_migrated_out_of_npcs(self):
        # story-004: Kael is a dedicated Companion (companions.json), no longer an npcs.json entry.
        assert "companion_kael" not in _load_ids("npcs.json")
        assert "companion_kael" in _load_ids("companions.json")

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


# M4.7 (story-002): role-scaled loot + currency. Mirrors scripts/seed_content.py's strict
# load-time validation so a bad reference fails the fast lane, not just at seed time.
_VALID_ENEMY_CATEGORIES = {
    "humanoid",
    "beast",
    "hollow_drift",
    "hollow_rend",
    "construct",
    "undead",
    "named",
}


class TestLootAndCurrencyContent:
    def _enemies(self):
        for enc in _load_json("encounter_templates.json"):
            for enemy in enc.get("enemies", []):
                yield enc["id"], enemy

    def test_every_enemy_has_category_and_loot_table_id(self):
        for enc_id, enemy in self._enemies():
            assert enemy.get("category"), f"'{enc_id}' enemy '{enemy.get('id', '?')}' missing 'category'"
            assert enemy.get("loot_table_id"), f"'{enc_id}' enemy '{enemy.get('id', '?')}' missing 'loot_table_id'"

    def test_enemy_categories_are_valid(self):
        for enc_id, enemy in self._enemies():
            assert enemy["category"] in _VALID_ENEMY_CATEGORIES, (
                f"'{enc_id}' enemy '{enemy['id']}' has invalid category '{enemy['category']}'"
            )

    def test_enemy_loot_table_ids_resolve(self):
        loot_ids = _load_ids("loot_tables.json")
        for enc_id, enemy in self._enemies():
            assert enemy["loot_table_id"] in loot_ids, (
                f"'{enc_id}' enemy '{enemy['id']}' references unknown loot_table_id '{enemy['loot_table_id']}'"
            )

    def test_loot_table_drops_reference_real_items(self):
        item_ids = _load_ids("items.json")
        for table in _load_json("loot_tables.json"):
            for drop in table.get("drops", []):
                assert drop["item_id"] in item_ids, (
                    f"Loot table '{table['id']}' references unknown item '{drop['item_id']}'"
                )

    def test_loot_table_drops_have_valid_chance_and_quantity(self):
        for table in _load_json("loot_tables.json"):
            for drop in table.get("drops", []):
                assert 0.0 <= drop["chance"] <= 1.0, (
                    f"Loot table '{table['id']}' drop '{drop['item_id']}' chance out of [0,1]"
                )
                assert drop["quantity"] >= 1, (
                    f"Loot table '{table['id']}' drop '{drop['item_id']}' quantity must be >= 1"
                )

    def test_material_sell_value_below_craft_value(self):
        # D78: selling a raw material is always worth less than crafting with it — the crafting
        # loop must stay the more rewarding path. Every material that pins a craft_value must have
        # value_base (the merchant sell floor) strictly below it.
        materials = [i for i in _load_json("items.json") if "craft_value" in i]
        assert materials, "expected at least one material item carrying a craft_value"
        for mat in materials:
            assert mat["value_base"] < mat["craft_value"], (
                f"Material '{mat['id']}' sell value_base {mat['value_base']} is not < "
                f"craft_value {mat['craft_value']} (D78)"
            )


# M4.8 (story-015): gathering node + resource_table refs. Mirrors scripts/seed_content.py's strict
# load-time validation so a bad gathering reference fails the fast lane, not just at seed time.
class TestGatheringContent:
    def test_gathering_node_location_ids_resolve(self):
        location_ids = _load_ids("locations.json")
        for node in _load_json("gathering_nodes.json"):
            assert node["location_id"] in location_ids, (
                f"Gathering node '{node['id']}' references unknown location_id '{node['location_id']}'"
            )

    def test_gathering_node_resource_types_resolve(self):
        material_ids = _load_ids("materials_catalog.json")
        for node in _load_json("gathering_nodes.json"):
            assert node["resource_type"] in material_ids, (
                f"Gathering node '{node['id']}' references unknown resource_type '{node['resource_type']}'"
            )

    def test_location_resource_table_entries_resolve(self):
        material_ids = _load_ids("materials_catalog.json")
        for loc in _load_json("locations.json"):
            for rarity, material_refs in (loc.get("resource_table") or {}).items():
                for material_ref in material_refs:
                    assert material_ref in material_ids, (
                        f"Location '{loc['id']}' resource_table '{rarity}' references unknown material '{material_ref}'"
                    )


# M13 (sprint-030 story-001): enemy hostile-condition content. Mirrors combat_init's fail-loud
# guard so an unknown/malformed applies_condition fails the fast lane, not just combat entry.
_HOSTILE_CONDITIONS = frozenset({"charmed", "frightened", "poisoned"})


class TestEnemyHostileConditionContent:
    def _enemy_actions_with_condition(self):
        for enc in _load_json("encounter_templates.json"):
            for enemy in enc.get("enemies", []):
                for action in enemy.get("action_pool", []):
                    if action.get("applies_condition") is not None:
                        yield enc["id"], enemy, action

    def test_enemy_applies_condition_is_catalog_key_with_valid_save_and_dc(self):
        import check_resolution_save
        import conditions

        for enc_id, enemy, action in self._enemy_actions_with_condition():
            cond = action["applies_condition"]
            assert cond in conditions.CONDITION_CATALOG, (
                f"'{enc_id}' enemy '{enemy['id']}' action '{action['name']}' "
                f"applies_condition '{cond}' is not a known condition"
            )
            # Use the SAME save-key check the load gate + runtime resolver use (accepts a full name
            # OR a 3-letter abbrev), so this fast-lane test can't be stricter than what the engine runs.
            assert check_resolution_save.is_valid_save_key(action.get("save")), (
                f"'{enc_id}' enemy '{enemy['id']}' action '{action['name']}' save '{action.get('save')}' "
                f"is not a valid save key"
            )
            assert isinstance(action.get("dc"), int), (
                f"'{enc_id}' enemy '{enemy['id']}' action '{action['name']}' dc must be an int"
            )

    def test_at_least_one_enemy_action_inflicts_a_hostile_condition(self):
        conditions_seen = {action["applies_condition"] for _, _, action in self._enemy_actions_with_condition()}
        assert conditions_seen & _HOSTILE_CONDITIONS, (
            "expected at least one enemy action_pool entry to declare a hostile "
            f"applies_condition ({sorted(_HOSTILE_CONDITIONS)}), found none"
        )
