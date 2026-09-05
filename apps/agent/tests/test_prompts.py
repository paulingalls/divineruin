"""Tests for prompt building (warm layer)."""

from unittest.mock import AsyncMock, patch

from prompt_fixtures import SAMPLE_LOCATION, SAMPLE_NPC_RAW, SAMPLE_QUEST

from system_prompts import build_system_prompt
from warm_prompts import build_warm_layer, format_training_section


def _onboarding_prompt_surface() -> str:
    """The whole onboarding prompt surface a prompt-tool-drift scan must cover.

    story-013 split the prompt into an invariant body plus a beat-3/4 span rendered per
    assigned companion, so scanning one constant no longer sees the whole thing: an
    instruction to call a removed tool could hide in a span the scan never rendered. Union
    all five renderings (four companions + the unresolved case).
    """
    from onboarding_prompt import build_onboarding_instructions

    companions = ("companion_kael", "companion_lira", "companion_tam", "companion_sable", None)
    return "\n".join(build_onboarding_instructions(3, cid) for cid in companions)


SAMPLE_AWAITING_TRAINING = {
    "id": "train_mid01",
    "activity_type": "technique_base",
    "state": "awaiting_decision",
    "data": {
        "program_name": "Combat Fundamentals",
        "decision_prompt": "Refine your stance: aggressive or defensive?",
        "decision_options": [
            {"id": "aggressive", "label": "Aggressive stance"},
            {"id": "defensive", "label": "Defensive stance"},
        ],
    },
}

SAMPLE_RUNNING_TRAINING = {
    "id": "train_run02",
    "activity_type": "spell_standard",
    "state": "running_first_half",
    "data": {"program_name": "Firebolt Study"},
}

SAMPLE_COMPLETE_TRAINING = {
    "id": "train_done03",
    "activity_type": "skill_practice",
    "state": "complete",
    "data": {"program_name": "Stealth Drills"},
}


class TestFormatTrainingSection:
    def test_empty_returns_none(self):
        assert format_training_section([]) is None

    def test_awaiting_decision_names_id_state_program_prompt_options(self):
        section = format_training_section([SAMPLE_AWAITING_TRAINING])
        assert section is not None
        assert section.startswith("ACTIVE TRAINING")
        # The training_id must be unambiguous so the DM can pass it to
        # resolve_training_midpoint.
        assert "train_mid01" in section
        assert "awaiting_decision" in section
        assert "Combat Fundamentals" in section
        assert "aggressive or defensive" in section
        assert "Aggressive stance" in section
        assert "aggressive" in section
        assert "Defensive stance" in section
        assert "defensive" in section

    def test_running_cycle_has_id_and_state_but_no_options(self):
        section = format_training_section([SAMPLE_RUNNING_TRAINING])
        assert section is not None
        assert "train_run02" in section
        assert "running_first_half" in section
        assert "Firebolt Study" in section
        assert "Options:" not in section

    def test_multiple_active_cycles_all_listed(self):
        section = format_training_section([SAMPLE_AWAITING_TRAINING, SAMPLE_RUNNING_TRAINING])
        assert section is not None
        assert "train_mid01" in section
        assert "train_run02" in section


class TestBuildWarmLayer:
    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_includes_location(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = []
        mock_quests.return_value = []
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        assert "Guild Hall" in result
        assert "evening" in result

    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_includes_npcs(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = [SAMPLE_NPC_RAW]
        mock_disp.return_value = {}
        mock_quests.return_value = []
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        assert "Guildmaster Torin" in result
        assert "neutral" in result

    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_includes_quests(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = []
        mock_quests.return_value = [SAMPLE_QUEST]
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        assert "Greyvale Anomaly" in result
        assert "Find the source" in result

    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_night_applies_time_conditions(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = []
        mock_quests.return_value = []
        result = await build_warm_layer("accord_guild_hall", "player_1", "night")
        assert "dim and quiet" in result
        assert "hushed" in result

    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_active_training_section_appears(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = []
        mock_quests.return_value = []
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening", training=[SAMPLE_AWAITING_TRAINING])
        assert "ACTIVE TRAINING" in result
        assert "train_mid01" in result

    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_completed_training_omitted(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = []
        mock_quests.return_value = []
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening", training=[SAMPLE_COMPLETE_TRAINING])
        assert "ACTIVE TRAINING" not in result


class TestBuildWarmLayerExits:
    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_exits_appear_in_warm_layer(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = []
        mock_quests.return_value = []
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        # §7: ungated exits are `go` affordances.
        assert "go:" in result
        assert "south" in result
        assert "accord_market_square" in result

    @patch("db_queries.get_player_flag", new_callable=AsyncMock)
    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_blocked_exit_shows_locked_without_leaking_requires(
        self, mock_loc, mock_npcs, mock_disp, mock_quests, mock_flag
    ):
        location_with_blocked = {
            **SAMPLE_LOCATION,
            "exits": {
                "south": {"destination": "accord_market_square"},
                "east": {"destination": "accord_temple_row", "requires": "temple_key"},
            },
        }
        mock_loc.return_value = location_with_blocked
        mock_npcs.return_value = []
        mock_quests.return_value = []
        mock_flag.return_value = False  # requirement unmet -> exit stays locked
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        # §7: a gated exit renders under `check` as "(locked)", until unlocked — but the raw
        # `requires` string (flag names / undiscovered hidden ids) never reaches the DM layer.
        assert "check:" in result
        assert "east (locked)" in result
        assert "temple_key" not in result

    @patch("db_queries.get_player_flag", new_callable=AsyncMock)
    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_blocked_exit_uses_blocked_hint_when_present(
        self, mock_loc, mock_npcs, mock_disp, mock_quests, mock_flag
    ):
        # When content gives a DM-safe blocked_hint, the locked label surfaces it (still no
        # raw requires).
        location_with_hint = {
            **SAMPLE_LOCATION,
            "exits": {
                "east": {
                    "destination": "accord_temple_row",
                    "requires": "temple_key",
                    "blocked_hint": "a sealed bronze door bars the way",
                },
            },
        }
        mock_loc.return_value = location_with_hint
        mock_npcs.return_value = []
        mock_quests.return_value = []
        mock_flag.return_value = False
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        assert "east (locked: a sealed bronze door bars the way)" in result
        assert "temple_key" not in result

    @patch("db_queries.get_player_flag", new_callable=AsyncMock)
    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_met_requirement_promotes_exit_check_to_go(
        self, mock_loc, mock_npcs, mock_disp, mock_quests, mock_flag
    ):
        # §7 (story-004): once the requirement is MET, the gated exit promotes check -> go.
        location_with_gate = {
            **SAMPLE_LOCATION,
            "exits": {
                "south": {"destination": "accord_market_square"},
                "east": {"destination": "accord_temple_row", "requires": "temple_key"},
            },
        }
        mock_loc.return_value = location_with_gate
        mock_npcs.return_value = []
        mock_quests.return_value = []
        mock_flag.return_value = True  # player holds the flag -> requirement met
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        assert "east → accord_temple_row" in result  # now a go affordance
        assert "east (locked" not in result

    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_no_exits_no_section(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        location_no_exits = {**SAMPLE_LOCATION, "exits": {}}
        mock_loc.return_value = location_no_exits
        mock_npcs.return_value = []
        mock_quests.return_value = []
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        assert "EXITS" not in result

    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_danger_rendered_as_band_not_integer(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        # §7: numbers stay in engine/HUD; the voiced warm layer speaks the danger BAND.
        mock_loc.return_value = {**SAMPLE_LOCATION, "danger_level": 2}
        mock_npcs.return_value = []
        mock_quests.return_value = []
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        assert "danger: dangerous" in result
        assert "danger: 2" not in result
        assert "AFFORDANCES" in result


class TestNavigationPromptIncluded:
    def test_system_prompt_includes_navigation(self):
        prompt = build_system_prompt("accord_guild_hall")
        assert 'mode="discover"' in prompt
        assert "Navigation" in prompt

    def test_navigation_prompt_nudges_scene_transition_narration(self):
        # update_quest carries a quest-driven region move in response["scene_transition"];
        # the DM needs a cue to voice it, since NAVIGATION otherwise only covers move_player
        # (concern c7c8d6acb6ec).
        prompt = build_system_prompt("accord_guild_hall")
        assert "scene_transition" in prompt


# NOTE: region-specific system-prompt assertions moved to tests/test_region_register.py.
# After M7 story-002, build_system_prompt is region-agnostic — wilderness/dungeon/city
# narration flavor now rides the warm-layer Stage register (REGION_REGISTER), so the
# per-region prose is asserted there (TestWarmLayerRegionRegister), not here.


def _registered_tool_descriptions() -> dict[str, str]:
    """Every registered tool's description, per agent, joined into one blob.

    Tool docstrings are the OTHER half of the surface the LLM reads to decide what to call — the
    system prompts are not the whole of it. A fold that removes a verb has to clear both, and a
    prompt-only guard reports a fold as verified while the docstrings still cue the dead tool.
    """
    from blacksmith_agent import BLACKSMITH_TOOLS
    from combat_agent import COMBAT_AGENT_TOOLS
    from creation_agent import CREATION_TOOLS
    from dispatch_agent import DISPATCH_TOOLS
    from exploration_agent import EXPLORATION_TOOLS
    from onboarding_agent import ONBOARDING_TOOLS

    toolsets = {
        "exploration tools": EXPLORATION_TOOLS,
        "combat tools": COMBAT_AGENT_TOOLS,
        "dispatch tools": DISPATCH_TOOLS,
        "blacksmith tools": BLACKSMITH_TOOLS,
        "creation tools": CREATION_TOOLS,
        "onboarding tools": ONBOARDING_TOOLS,
    }
    descriptions = {name: "\n".join(t.info.description or "" for t in tools) for name, tools in toolsets.items()}
    # Fail loud rather than pass vacuously if a toolset stops exposing descriptions.
    for name, blob in descriptions.items():
        assert blob.strip(), f"{name} exposed no tool descriptions — the guard below would be vacuous"
    return descriptions


class TestPromptToolConsistency:
    """A gameplay agent's assembled prompt must name a tool only when the agent
    actually holds it — otherwise the DM is told to call an absent tool
    (concern b1591cb23262). Enforced by construction so the next prompt edit can't
    silently reintroduce the drift (concern df5cc73b2473)."""

    def test_query_info_consolidation_consistency(self):
        """After collapsing query_* into query_info: a prompt naming query_info must hold
        it (no absent-tool instruction), and no prompt may name a removed query_* tool."""
        from combat_agent import COMBAT_AGENT_TOOLS
        from dispatch_agent import DISPATCH_TOOLS
        from exploration_agent import EXPLORATION_TOOLS
        from mode_tools import enter_mode
        from onboarding_agent import ONBOARDING_TOOLS
        from query_tools import query_info
        from system_prompts import COMBAT_SYSTEM_PROMPT, DISPATCH_SYSTEM_PROMPT

        agents = {
            "exploration": (build_system_prompt("loc"), EXPLORATION_TOOLS),
            "combat": (COMBAT_SYSTEM_PROMPT, COMBAT_AGENT_TOOLS),
            "training": (DISPATCH_SYSTEM_PROMPT, DISPATCH_TOOLS),
            "onboarding": (_onboarding_prompt_surface(), ONBOARDING_TOOLS),
        }
        for name, (prompt, tools) in agents.items():
            if "query_info" in prompt:
                assert query_info in tools, f"{name} prompt names query_info but lacks the tool"
            for removed in ("query_location", "query_npc", "query_lore", "query_inventory"):
                assert removed not in prompt, f"{name} prompt still names removed tool {removed}"
            # enter_mode named iff held (region agents hold + name it; others neither).
            assert ("enter_mode" in prompt) == (enter_mode in tools), (
                f"{name}: prompt names enter_mode but tool-holding differs"
            )

    def test_activity_fold_consistency(self):
        """M26 Phase-5 story-003: after folding the 10 downtime noun tools into
        begin_activity/resolve_activity, the DISPATCH prompt must never name a folded
        tool (prompt-tool drift bit production in M25 story-002), and must name
        begin_activity/resolve_activity iff DispatchAgent actually holds them."""
        from activity_tools import begin_activity, resolve_activity
        from dispatch_agent import DISPATCH_TOOLS
        from system_prompts import DISPATCH_SYSTEM_PROMPT

        removed_activity_tools = (
            "query_training_programs",
            "initiate_training_cycle",
            "resolve_training_midpoint",
            "dispatch_companion_errand",
            "resolve_companion_errand",
            "query_recipe_requirements",
            "query_available_workspaces",
            "rent_workspace",
            "start_crafting_project",
            "experiment_with_materials",
        )
        for removed in removed_activity_tools:
            assert removed not in DISPATCH_SYSTEM_PROMPT, f"dispatch prompt still names removed tool {removed}"
        assert ("begin_activity" in DISPATCH_SYSTEM_PROMPT) == (begin_activity in DISPATCH_TOOLS)
        assert ("resolve_activity" in DISPATCH_SYSTEM_PROMPT) == (resolve_activity in DISPATCH_TOOLS)

    def test_dispatch_narrates_all_begin_activity_kinds(self):
        """Debt 574d0c6e83cd: DispatchAgent can begin 5 activity kinds via begin_activity(kind),
        but after the M26 fold the dispatch prompt only narrated training/companion_errand —
        crafting/workspace/experiment had the verb but no when-to-invoke guidance. Every
        registered kind must be named in the prompt. Kinds are DERIVED from the begin_activity
        Literal (not hardcoded) so a future 6th kind fails loud rather than silently uncovered."""
        import inspect
        import typing

        from activity_tools import begin_activity
        from system_prompts import DISPATCH_SYSTEM_PROMPT

        kinds = typing.get_args(inspect.signature(begin_activity).parameters["kind"].annotation)
        # Guard the reflection itself: if the Literal ever stops resolving (e.g. the param
        # becomes `str`), kinds would be () and the loop below would pass vacuously.
        assert len(kinds) >= 5, f"reflection returned too few begin_activity kinds ({kinds}) — guard would be vacuous"
        for kind in kinds:
            assert kind in DISPATCH_SYSTEM_PROMPT, f"dispatch prompt omits begin_activity kind {kind!r}"

    def test_audio_tool_fold_consistency(self):
        """M27 story-003: play_sound/set_music_state were torn out as LLM tools — SFX/music
        now derive only from deterministic Resolves and the Stage. No gameplay prompt may
        still instruct the LLM to call either (prompt-tool drift bit production before,
        concern df5cc73b2473)."""
        from system_prompts import COMBAT_SYSTEM_PROMPT, DISPATCH_SYSTEM_PROMPT

        prompts = {
            "exploration": build_system_prompt("loc"),
            "combat": COMBAT_SYSTEM_PROMPT,
            "training": DISPATCH_SYSTEM_PROMPT,
            "onboarding": _onboarding_prompt_surface(),
        }
        for name, prompt in prompts.items():
            for removed in ("play_sound", "set_music_state"):
                assert removed not in prompt, f"{name} prompt still names removed tool {removed}"

    def test_reward_tool_fold_consistency(self):
        """M28 story-003: award_xp/award_divine_favor were torn out as LLM tools — XP and
        divine favor are granted by the combat-exit and quest-completion Resolves instead.

        The system prompts never named either verb, so scanning them alone was green on arrival
        and would have stayed green through the exact regression it claims to guard: the
        instruction M28 actually deleted lived in a TOOL DOCSTRING (end_combat's "call award_xp
        separately with the returned total"), and docstrings are the other half of the surface the
        LLM reads. So every REGISTERED tool's description is scanned too — restore that sentence
        and the DM emits a call to a tool no agent holds, erroring out the combat-exit turn.
        """
        from system_prompts import COMBAT_SYSTEM_PROMPT, DISPATCH_SYSTEM_PROMPT

        prompts = {
            "exploration": build_system_prompt("loc"),
            "combat": COMBAT_SYSTEM_PROMPT,
            "training": DISPATCH_SYSTEM_PROMPT,
            "onboarding": _onboarding_prompt_surface(),
        }
        for name, prompt in prompts.items():
            for removed in ("award_xp", "award_divine_favor"):
                assert removed not in prompt, f"{name} prompt still names removed tool {removed}"

        for agent_name, docstring in _registered_tool_descriptions().items():
            for removed in ("award_xp", "award_divine_favor"):
                assert removed not in docstring, f"{agent_name} still names removed tool {removed}"

    def test_combat_prompt_names_consume_legendary_action(self):
        """story-009: the combat prompt must name consume_legendary_action so the DM knows to spend
        the Boss's legendary beat resolve_phase surfaces, and the agent must hold the tool."""
        from combat_agent import COMBAT_AGENT_TOOLS
        from combat_turn import consume_legendary_action
        from system_prompts import COMBAT_SYSTEM_PROMPT

        assert "consume_legendary_action" in COMBAT_SYSTEM_PROMPT
        assert consume_legendary_action in COMBAT_AGENT_TOOLS


# NOTE: the training-hall referral moved from the city system prompt to the city
# REGION_REGISTER (warm layer) in M7 story-002 — asserted in
# tests/test_region_register.py::TestWarmLayerRegionRegister.test_city_location_yields_city_register.
