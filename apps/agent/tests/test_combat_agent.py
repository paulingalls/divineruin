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
        low = COMBAT_SYSTEM_PROMPT.lower()
        assert "freeze" in low or "hesitat" in low
        # A bare `"defend" in low` is vacuous now that defend is one of the declaration kinds
        # the prompt lists: pin the FALLBACK, i.e. that the hesitation instruction is what
        # names it.
        start = low.index("freeze") if "freeze" in low else low.index("hesitat")
        assert "defend" in low[start : start + 200], "hesitation instruction does not fall back to defend"

    def test_resolution_is_silent_before_narration(self):
        # Beat 2 resolves silently; the Beat-3 narration instruction comes after.
        p = COMBAT_SYSTEM_PROMPT.lower()
        assert "silent" in p
        assert p.index("silent") < p.index("now narrate")

    def test_beat3_teaches_the_dm_to_read_next_rather_than_guess_a_window(self):
        """constraint 6, the prompt half. `next` is only a producer if the DM is told to read it:
        an id the engine mints but the prompt never mentions is still a guess. Sprint 45 shipped a
        gate keyed on a reaction window the DM had to pick among nine, and the prompt's advice then
        was the opposite of the design — "do not open an undeclared reaction window during Beat 3".
        M29 story-016 restored the interrupt model; these are the phrases that carry it."""
        low = COMBAT_SYSTEM_PROMPT.lower()
        assert "do not open an undeclared reaction window" not in low, "the reversed model is back"
        assert "next.waiting_on" in low
        assert "window_id" in low and "never invent one" in low
        # The pause is the mechanic, and both stages are named so the DM knows what it may voice.
        assert "the pause is the mechanic" in low
        assert "pre_roll" in low and "post_roll" in low
        # Reading `next` is taught before Beat 3 needs it.
        assert low.index('every resolve_phase result carries a "next" block') < low.index("next.waiting_on")

    def test_next_verbs_is_taught_as_the_advance_verb_not_a_whitelist(self):
        """`next.verbs` carries the ADVANCE verb only (combat_wrap.next_envelope), so a prompt that
        called it the complete set of legal calls would contradict Beat 4 in the same breath: the
        very payload whose next.verbs reads ["declare_phase"] also carries death_saves_due and
        legendary_available, and neither request_death_save nor consume_legendary_action has a beat
        gate. An obedient DM would leave a downed player unrolled."""
        low = COMBAT_SYSTEM_PROMPT.lower()
        assert "not a whitelist" in low
        assert "which verb advances the beat" in low
        assert "still call request_death_save when death_saves_due names someone" in low
        assert "only the verbs in next.verbs are legal" not in low, "the whitelist reading is back"
        # Beat 4 still asks for both verbs `next.verbs` omits — that is what makes the above true.
        assert "call request_death_save" in low
        assert "call consume_legendary_action" in low

    def test_beat2_says_the_enemy_blows_are_held(self):
        """AC1's contract, as the DM sees it: Beat 2 resolves the player's side only. A prompt that
        still promised "resolves every declaration" would have the DM narrate blows that have not
        landed."""
        low = COMBAT_SYSTEM_PROMPT.lower()
        assert "holds every enemy action back for beat 3" in low
        assert "the enemy blows are held" in low

    def test_the_prompt_warns_that_end_combat_is_refused_mid_beat(self):
        """D7's DM-visible cost: end_combat("fled") raises while enemy actions are held pending, so
        the prompt says so rather than letting the DM discover it as a tool error."""
        low = COMBAT_SYSTEM_PROMPT.lower()
        assert "refuse while enemy actions are still held" in low

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
        assert "ability — action is the EXACT id of a spell" in prompt
        assert "activate" in prompt
        assert "ordinary spell or ability" in prompt
        assert "never a free cast via activate" in prompt

    def test_declare_phase_offers_no_reaction_kind_to_the_dm(self):
        """AC2's prompt half. The schema stopped accepting `kind: "reaction"` (story-017), so a
        prompt that still taught it would have the DM spend a tool call on a rejected payload
        every round — and, worse, believe the reaction was armed."""
        prompt = COMBAT_SYSTEM_PROMPT
        low = prompt.lower()
        assert "Three kinds resolve in combat today" in prompt
        assert "four kinds resolve in combat today" not in low
        assert "reaction — action is the EXACT id" not in prompt
        assert "trigger is its catalog window" not in low
        assert "declare the reaction during beat 1" not in low

    def test_the_dm_activates_a_reaction_at_an_open_window(self):
        """AC8: the interrupt teaching, at the ONE place the DM meets it — the Beat-3 pause.

        The window is the permission now, and `next.waiting_on.triggers` is the only thing that
        says which reaction fits. A prompt that named `activate` without naming `triggers` would
        send the DM back to guessing among nine windows (constraint 6), which is the defect
        sprint-045 shipped twice."""
        low = COMBAT_SYSTEM_PROMPT.lower()
        pause = low.index("the pause is the mechanic")
        teaching = low[pause : pause + 900]
        assert "activate" in teaching
        assert "next.waiting_on.triggers" in teaching
        assert "one reaction per round" in teaching
        assert "no pre-declaration" in teaching

    def test_the_prompt_advertises_no_variant_ids_in_combat(self):
        """note 9724fb7c(a): a variant id in declare_phase's ability path raises "Unknown spell",
        so advising the DM to learn "active variant ids" in combat produces a tool error and a
        lost round. Uncovered until story-017 — nothing asserted on that line."""
        assert "variant id" not in COMBAT_SYSTEM_PROMPT.lower()

    def test_no_reaction_packet_narration_advice_survives(self):
        """The Beat-3 narration line described combat_packet's REACTION branch, which is deleted:
        no packet reports a `declaration_type` of "reaction" any more, so the advice describes a
        packet the DM will never see."""
        assert "narrate a reaction packet as successful" not in COMBAT_SYSTEM_PROMPT.lower()

    def test_the_dm_is_told_what_a_reaction_packet_reports(self):
        """story-018's producer half (constraint 6). A reaction packet exists again — synthesized
        at window close, not from a declaration — and its `mechanical_effect` is the field that
        says what the reaction DID. The DM has to be reintroduced to it deliberately: a packet
        nothing in the prompt names is a capability the DM cannot narrate.

        The null reading is taught too, because null is the honest report for a reaction that was
        spent and changed nothing mechanical — and a DM who reads the packet's `resolved: true` as
        the claim would tell the player they were saved when they were not."""
        low = COMBAT_SYSTEM_PROMPT.lower()
        assert "mechanical_effect" in low
        effect = low.index("mechanical_effect")
        teaching = low[effect : effect + 500]
        assert "damage_halved" in teaching
        assert "target_ac_bonus" in teaching
        assert "shield_durability" in teaching
        assert "null" in teaching
        assert "narration_cue" in teaching

    def test_combat_only_capabilities_still_use_activate(self):
        # M25 fix: Inner Fire and raising/dropping a Veil Ward are combat-only capabilities that
        # enter through activate (the reserved tokens), so the blanket "never activate in combat"
        # rule would silently forbid them mid-fight. The prompt must carve out the exception.
        low = COMBAT_SYSTEM_PROMPT.lower()
        assert "draethar_inner_fire" in low
        assert "veil_ward" in low

    def test_the_never_activate_rule_carves_out_reactions(self):
        """story-017 made a REACTION the third activate-in-combat capability, and the Beat-1
        blanket rule ("an ordinary spell or ability is an Ability declaration ... never a free
        cast via activate") sits 40 lines above the Beat-3 teaching that tells the DM to call
        activate. An obedient DM meeting the prohibition first never reaches the window.

        The carve-out has to live AT the prohibition, not only at the pause."""
        low = COMBAT_SYSTEM_PROMPT.lower()
        prohibition = low.index("never a free cast via activate")
        carve_out = low[prohibition : prohibition + 400]
        assert "reaction" in carve_out
