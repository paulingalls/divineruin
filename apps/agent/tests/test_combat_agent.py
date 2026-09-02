"""Tests for CombatAgent — combat-specific agent with focused tools and prompt."""

from base_agent import BaseGameAgent
from combat_agent import COMBAT_AGENT_TOOLS, COMBAT_SYSTEM_PROMPT, CombatAgent


class TestCombatAgentConfig:
    """Test CombatAgent is correctly configured."""

    def test_is_subclass_of_base_game_agent(self):
        assert issubclass(CombatAgent, BaseGameAgent)

    def test_combat_tools_are_complete(self):
        from activate_tools import activate
        from check_tools import check
        from combat_death_save import request_death_save
        from combat_end import end_combat
        from combat_turn import consume_legendary_action, declare_phase, resolve_phase
        from query_tools import query_info
        from spell_info_tools import get_spell_info

        # The phase-loop verbs (declare_phase/resolve_phase) replaced the old per-actor
        # resolve_enemy_turn + request_attack (story-003, unified packet resolution).
        # Phase 5 (story-002, M25) folded cast_spell/request_ability_activation/
        # activate_veil_ward/inner_fire into the single polymorphic activate verb.
        expected = {
            declare_phase,
            resolve_phase,
            consume_legendary_action,
            check,
            request_death_save,
            end_combat,
            query_info,
            activate,
            get_spell_info,
        }
        assert set(COMBAT_AGENT_TOOLS) == expected

    def test_activate_and_get_spell_info_registered(self):
        # story-004 M3: the cast path is callable from the combat agent. Phase 5
        # (story-002) folded cast_spell into activate.
        from activate_tools import activate
        from spell_info_tools import get_spell_info

        assert activate in COMBAT_AGENT_TOOLS
        assert get_spell_info in COMBAT_AGENT_TOOLS

    def test_demoted_capability_wrappers_not_registered(self):
        # Phase 5 (story-002): the four folded wrappers are no longer @function_tool
        # entries at all, so checking the registered tool names is sufficient.
        registered_names = {getattr(t, "__name__", None) for t in COMBAT_AGENT_TOOLS}
        for name in (
            "cast_spell",
            "request_ability_activation",
            "activate_veil_ward",
            "inner_fire",
        ):
            assert name not in registered_names

    def test_combat_tools_exclude_exploration(self):
        from mode_tools import enter_mode
        from movement_tools import move_player
        from quest_tools import update_quest
        from scene_tools import enter_location

        for tool in [enter_location, move_player, enter_mode, update_quest]:
            assert tool not in COMBAT_AGENT_TOOLS

    def test_combat_excludes_milestone_resolution(self):
        # Combat DOES award XP (end_combat grants it party-wide via the XP Resolve, M28
        # story-001), but the L5 fork it can surface is only ever RESOLVED after the handoff:
        # end_combat returns the exploration agent in the same breath, and select lives there
        # (concern 3c02318dfa99).
        from choice_tools import select

        assert select not in COMBAT_AGENT_TOOLS


class TestCombatSystemPrompt:
    """Test COMBAT_SYSTEM_PROMPT content."""

    def test_contains_combat_narration_style(self):
        assert "staccato" in COMBAT_SYSTEM_PROMPT

    def test_contains_initiative_flow(self):
        assert "initiative" in COMBAT_SYSTEM_PROMPT.lower()

    def test_contains_hp_status_guidance(self):
        assert "hp_status" in COMBAT_SYSTEM_PROMPT or "bloodied" in COMBAT_SYSTEM_PROMPT

    def test_contains_voice_style_rules(self):
        assert "spoken aloud" in COMBAT_SYSTEM_PROMPT or "write for the ear" in COMBAT_SYSTEM_PROMPT.lower()

    def test_contains_character_tag_format(self):
        assert "[CHARACTER_NAME" in COMBAT_SYSTEM_PROMPT or "COMPANION_KAEL" in COMBAT_SYSTEM_PROMPT

    def test_contains_companion_combat_instructions(self):
        assert "companion" in COMBAT_SYSTEM_PROMPT.lower()


class TestCombatBeatContract:
    """story-004: COMBAT_SYSTEM_PROMPT encodes the 4-beat DM contract for the phase
    engine — declaration (with hesitation->Defend), silent resolution, narration with
    reaction windows + dramatic-dice pauses, and wrap. Prompt + contract only."""

    def test_names_four_beats_in_order(self):
        p = COMBAT_SYSTEM_PROMPT.lower()
        # Anchor on a unique body phrase from EACH beat (not the single overview line),
        # so deleting or reordering a beat body — not just its header — fails the test.
        bodies = [
            p.index("call declare_phase"),  # Beat 1 declaration body
            p.index("call resolve_phase"),  # Beat 2 resolution body
            p.index("narrate the returned packets"),  # Beat 3 narration body
            p.index("death saves due"),  # Beat 4 wrap body
        ]
        assert bodies == sorted(bodies), f"beat bodies out of order: {bodies}"
        for beat in ("declaration", "resolution", "narration", "wrap"):
            assert beat in p, f"missing beat name: {beat}"

    def test_declaration_hesitation_falls_back_to_defend(self):
        p = COMBAT_SYSTEM_PROMPT
        assert "Defend" in p
        assert "freeze" in p.lower() or "hesitat" in p.lower()

    def test_resolution_is_silent_before_narration(self):
        # Beat 2 resolves silently; the Beat-3 narration instruction comes after.
        p = COMBAT_SYSTEM_PROMPT.lower()
        assert "silent" in p
        assert p.index("silent") < p.index("now narrate")

    def test_narration_does_not_open_an_undeclared_reaction_window(self):
        low = COMBAT_SYSTEM_PROMPT.lower()
        assert "do not open an undeclared reaction window" in low
        assert "before an enemy's blow lands" not in low

    def test_honors_dramatic_pause(self):
        # "pause" alone leaks from VOICE_STYLE ("Use pauses") and the Beat-4 death-save
        # line; anchor on the unique Beat-3 phrase so deleting it actually fails.
        assert "pause for the dramatic dice" in COMBAT_SYSTEM_PROMPT.lower()

    def test_player_action_must_be_equipped_weapon_name(self):
        # Concern 4fa8d5aedce6: the player's Attack action is the exact name of an equipped
        # weapon — so a player turn is never silently wasted on a name mismatch.
        low = COMBAT_SYSTEM_PROMPT.lower()
        assert "exact name" in low and "equipped weapon" in low

    def test_in_combat_ability_is_a_declaration_not_activate(self):
        # story-007: an in-combat spell/ability is an Ability declaration through declare_phase;
        # a free cast via activate is the OUT-OF-COMBAT entry only (story-002 folded cast_spell into
        # activate). The prompt must teach the new shape so the DM routes casting through the phase
        # loop (Focus/Resonance accounted) instead of a free activate cast.
        prompt = COMBAT_SYSTEM_PROMPT
        assert '"type": "ability"' in prompt
        assert "activate" in prompt
        assert "ordinary spell or ability" in prompt
        assert "never a free cast via activate" in prompt

    def test_reaction_declaration_has_catalog_trigger_shape(self):
        prompt = COMBAT_SYSTEM_PROMPT
        assert "Four types resolve in combat today" in prompt
        assert '"type": "reaction"' in prompt
        assert '"trigger": <catalog window>' in prompt

    def test_declared_reaction_activates_before_resolution(self):
        low = COMBAT_SYSTEM_PROMPT.lower()
        declaration = low.index("declare the reaction")
        activation = low.index("activate that exact reaction ability id")
        resolution = low.index("call resolve_phase", activation)
        assert declaration < activation < resolution
        assert "reaction activation is an exception" in low

    def test_combat_only_capabilities_still_use_activate(self):
        # M25 fix: Inner Fire and raising/dropping a Veil Ward are combat-only capabilities that
        # enter through activate (the reserved tokens), so the blanket "never activate in combat"
        # rule would silently forbid them mid-fight. The prompt must carve out the exception.
        low = COMBAT_SYSTEM_PROMPT.lower()
        assert "draethar_inner_fire" in low
        assert "veil_ward" in low
