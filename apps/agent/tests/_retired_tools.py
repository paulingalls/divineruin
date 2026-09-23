"""Retired DM tool names and the registered verbs that replaced them."""

RETIRED_TOOL_REPLACEMENTS = {
    "add_to_inventory": "transact",
    "remove_from_inventory": "transact",
    "learn_recipe": "learn",
    "request_skill_check": "check",
    "discover_hidden_element": "check",
    "request_saving_throw": "check",
    "roll_dice": "check",
    "start_combat": "enter_mode",
    "enter_dispatch": "enter_mode",
    "enter_blacksmith": "enter_mode",
    "request_attack": "declare_phase",
    "resolve_enemy_turn": "resolve_phase",
    "cast_spell": "activate",
    "request_ability_activation": "activate",
    "activate_veil_ward": "activate",
    "inner_fire": "activate",
    "deploy_veil_anchor": "activate",
    "query_training_programs": "query_info",
    "initiate_training_cycle": "begin_activity",
    "resolve_training_midpoint": "resolve_activity",
    "dispatch_companion_errand": "begin_activity",
    "resolve_companion_errand": "resolve_activity",
    "query_recipe_requirements": "query_info",
    "query_available_workspaces": "query_info",
    "rent_workspace": "begin_activity",
    "start_crafting_project": "begin_activity",
    "experiment_with_materials": "begin_activity",
    "play_sound": None,
    "set_music_state": None,
    "award_xp": None,
    "award_divine_favor": None,
}

NEVER_BUILT_TOOLS = frozenset(
    {
        "request_save",
        "get_death_cost",
        "start_travel",
        "learn_spell_from_scroll",
        "prepare_spells",
        "get_settlement_npc_population",
        "enroll_mentor_training",
        "query_settlement_population",
    }
)
