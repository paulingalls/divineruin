"""The milestone corpus must describe the registered DM surface accurately."""

import re
from pathlib import Path

import pytest
from _retired_tools import NEVER_BUILT_TOOLS, RETIRED_TOOL_REPLACEMENTS
from agent_tool_profiles import AGENT_TOOL_LISTS

DOCS = Path(__file__).resolve().parents[4] / "docs" / "milestones"
BACKTICK = re.compile(r"`([a-z][a-z0-9_]*(?:\([^`]*\))?)`")
COMMENTS = re.compile(r"<!--.*?-->")
TOOL_CONTEXT = re.compile(r"\b(?:agent|DM) tools?\b|\btool surface\b|@function_tool", re.I)
# Explicitly named ordinary functions, planned functions, and internal functions.
NON_TOOLS = frozenset(
    {
        "resolve_check",
        "record_skill_use",
        "check_skill_capabilities",
        "calculate_max_pool",
        "apply_rest",
        "get_narrative_state",
        "level_for_xp",
        "get_level_up_rewards",
        "check_level_up",
        "build_level_up_payload",
        "apply_level_up",
        "build_level_up_payload_for_archetype",
        "get_archetype_chassis",
        "resolve_milestone",
        "calculate_max_hp",
        "calculate_max_pools",
        "resolve_hollow_echo",
        "calculate_resonance_generated",
        "get_resonance_state",
        "apply_resonance_decay",
        "check_concentration",
        "get_racial_resonance_modifier",
        "narrative_hint",
        "resolve_attack",
        "resolve_saving_throw",
        "advance_combat_phase",
        "determine_death_cost",
        "build_encounter",
        "apply_condition",
        "tick_conditions",
        "get_condition_effects",
        "trigger_character_death",
        "resolve_gathering",
        "resolve_death_save",
        "resolve_social_check",
        "validate_creature_stat_block",
        "query_creatures_by_region",
        "query_creature_by_id",
        "resolve_harvesting",
        "generate_encounter",
        "activate_patron_ability",
        "check_patron_tier",
        "query_patron_synergy",
        "get_merchant_price",
        "resolve_combat_loot",
        "grant_reputation",
        "check_faction_service_available",
        "query_merchant_inventory",
        "purchase_item",
        "sell_item",
        "consign_item",
        "consume_item",
        "is_natural",
        "is_earth_or_stone",
        "resonance_base",
        "crossed_dawn",
        "game_time",
        "time_of_day_period",
        "game_day_number",
        "season",
        "crossed_boundary",
        "compute_node_respawn",
        "allocate_materials",
        "apply_corruption_aura",
        "apply_durability_damage",
        "apply_pricing_modifiers",
        "apply_quality_outcome",
        "apply_unbound_resonance_push",
        "atomic_p2p_transfer",
        "attempt_purchase",
        "attempt_sale",
        "calculate_ac",
        "calculate_currency_drop",
        "calculate_price",
        "calculate_repair_cost",
        "check_item_condition",
        "check_material_requirements",
        "check_mentor_requirements",
        "clamp_price",
        "companion_errand",
        "compute_event_modifier",
        "compute_faction_modifier",
        "compute_recovery_multipliers",
        "compute_rental_price",
        "convert_currency",
        "create_npc_from_archetype",
        "daily_restock_at_dawn",
        "economy_simulation_tick",
        "errand_resolution",
        "errand_type",
        "evaluate_dramatic_context",
        "evaluate_patron_alignment",
        "generate_loot",
        "generate_settlement_npcs",
        "get_archetype_synergy",
        "get_patron_tier",
        "grimjaw_weapons",
        "instantiate_npc_from_template",
        "inventory_pools",
        "learn_spell_from_scroll",
        "lookup_base_price",
        "market_general",
        "millhaven_supplies",
        "player_inventory",
        "prepare_spells",
        "query_companion_relationship",
        "remove_condition",
        "resolve_crafting",
        "resolve_crafting_check",
        "resolve_declaration",
        "resolve_experimentation",
        "resolve_resonance_on_death",
        "resolve_travel_segment",
        "same_settlement",
        "save_proficiencies",
        "scale_companion_stats_to_player_level",
        "temple_supplies",
        "validate_magic_item_craft_tier",
        "validate_quest_reward",
        "validate_recipe_knowledge",
        "validate_recipe_slot_capacity",
        "validate_workspace_tier",
        "workspace_rentals",
        "ancient_forest",
        "location_id",
        "combat_id",
        "region_type",
    }
)


def live_names():
    return {tool.__name__ for _, tools in AGENT_TOOL_LISTS for tool in tools}


def segments(line):
    visible = COMMENTS.sub("", line)
    return [visible, *COMMENTS.findall(line)]


def candidates(segment):
    for match in BACKTICK.finditer(segment):
        raw = match.group(1)
        name = raw.split("(", 1)[0]
        if (
            "(" in raw
            or name in RETIRED_TOOL_REPLACEMENTS
            or name in NEVER_BUILT_TOOLS
            or ("_" in name and TOOL_CONTEXT.search(segment))
        ):
            yield name


def violations(path, number, line, live):
    for segment in segments(line):
        tokens = set(candidates(segment))
        for name in tokens:
            reason = None
            if name in NEVER_BUILT_TOOLS:
                reason = "never built as a DM tool"
            elif name in RETIRED_TOOL_REPLACEMENTS:
                replacement = RETIRED_TOOL_REPLACEMENTS[name]
                if replacement is None:
                    outside = BACKTICK.sub("", segment)
                    if not re.search(r"\b(?:retired|removed|deleted|Resolve)\b", outside, re.I):
                        reason = "retired without a retirement or Resolve explanation"
                elif replacement not in live:
                    reason = f"replacement {replacement} is not registered"
                elif replacement not in {m.group(1).split("(", 1)[0] for m in BACKTICK.finditer(segment)}:
                    reason = f"retired without replacement `{replacement}` on this line"
            elif name not in live and name not in NON_TOOLS:
                reason = "unclassified tool-shaped name"
            if reason:
                yield f"{path}:{number}: {name}: {reason}"


def scan_docs(directory, live):
    docs = sorted(directory.glob("*.md"))
    assert docs, f"no milestone docs under {directory}"
    return [
        error
        for path in docs
        for number, line in enumerate(path.read_text().splitlines(), 1)
        for error in violations(path, number, line, live)
    ]


def test_milestone_tool_names():
    live = live_names()
    assert len(RETIRED_TOOL_REPLACEMENTS) == 31
    assert not RETIRED_TOOL_REPLACEMENTS.keys() & live
    assert not NEVER_BUILT_TOOLS & live
    assert all(replacement in live for replacement in RETIRED_TOOL_REPLACEMENTS.values() if replacement)
    selected = {
        name
        for path in DOCS.glob("*.md")
        for line in path.read_text().splitlines()
        for segment in segments(line)
        for name in candidates(segment)
    }
    assert selected & live, "no registered tool names selected from milestone docs"
    errors = scan_docs(DOCS, live)
    assert not errors, "\n".join(errors)


@pytest.mark.parametrize(
    "line",
    [
        "Agent tool `learn_recipe`",
        "Agent tool `request_skill_check`",
        "Agent tool `activate_veil_ward`",
        "Agent tool `roll_dice` for a skill check",
        "`award_xp` agent tool <!-- `award_xp` deleted; Resolve -->",
        "Agent tool `request_parley`",
        "Agent tool `request_save`",
    ],
)
def test_bad_tool_line_reds(line):
    assert list(violations("fixture.md", 7, line, live_names()))


def test_empty_doc_walk_reds(tmp_path):
    with pytest.raises(AssertionError, match="no milestone docs"):
        scan_docs(tmp_path, live_names())


def require_retired_fixture(lines):
    assert any(
        set(candidates(segment)) & RETIRED_TOOL_REPLACEMENTS.keys() for line in lines for segment in segments(line)
    ), "no retired-name mentions in fixture corpus"


def test_retired_fixture_floor():
    require_retired_fixture(["`learn_recipe` folded into `learn`"])
    with pytest.raises(AssertionError, match="no retired-name mentions"):
        require_retired_fixture(["`learn` is registered"])


def test_dropped_map_name_reds(monkeypatch):
    monkeypatch.delitem(RETIRED_TOOL_REPLACEMENTS, "learn_recipe")
    assert "unclassified" in " ".join(violations("fixture.md", 4, "Agent tool `learn_recipe`", live_names()))


def test_unregistered_replacement_reds(monkeypatch):
    monkeypatch.setitem(RETIRED_TOOL_REPLACEMENTS, "learn_recipe", "invented_verb")
    assert "not registered" in " ".join(violations("fixture.md", 4, "`learn_recipe`", live_names()))


def test_injected_doc_lines_red_with_location(tmp_path):
    path = tmp_path / "05_crafting.md"
    path.write_text("Agent tool `learn_recipe`\nAgent tool `request_parley`\n")
    errors = scan_docs(tmp_path, live_names())
    assert any("05_crafting.md:1: learn_recipe" in error for error in errors)
    assert any("05_crafting.md:2: request_parley" in error for error in errors)


@pytest.mark.parametrize(
    "name",
    [
        "query_training_programs",
        "query_recipe_requirements",
        "query_available_workspaces",
    ],
)
def test_retired_lookups_use_query_info(name):
    assert RETIRED_TOOL_REPLACEMENTS[name] == "query_info"
