from unittest.mock import AsyncMock, MagicMock, patch

from livekit.agents.llm import ChatContext, ChatMessage
from prompt_fixtures import sample_combat_state

from base_agent import BaseGameAgent
from caster_state import ConcentrationState, ResonanceTrack
from combat_agent import COMBAT_AGENT_TOOLS, COMBAT_SYSTEM_PROMPT, CombatAgent
from party_state import PartyMember
from session_data import SessionData
from speaker_context import build_speaker_context


class TestCombatAgentConfig:
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
        from activate_tools import activate
        from spell_info_tools import get_spell_info

        assert activate in COMBAT_AGENT_TOOLS
        assert get_spell_info in COMBAT_AGENT_TOOLS

    def test_demoted_capability_wrappers_not_registered(self):
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
        p = COMBAT_SYSTEM_PROMPT.lower()
        assert "silent" in p
        assert p.index("silent") < p.index("now narrate")

    def test_beat3_teaches_the_dm_to_read_next_rather_than_guess_a_window(self):
        """The prompt must surface reaction windows instead of requiring the DM to guess."""
        low = COMBAT_SYSTEM_PROMPT.lower()
        assert "do not open an undeclared reaction window" not in low, "the reversed model is back"
        assert "next.waiting_on" in low
        assert "window_id" in low and "never invent one" in low
        assert "next.waiting_on.action" in low
        assert low.index("next.waiting_on.action") < low.index("the pause is the mechanic")
        assert "the pause is the mechanic" in low
        assert "pre_roll" in low and "post_roll" in low
        assert low.index('every resolve_phase result carries a "next" block') < low.index("next.waiting_on")

    def test_next_verbs_is_taught_as_the_advance_verb_not_a_whitelist(self):
        """The next-step affordance must include death saves, not only ordinary phase verbs."""
        low = COMBAT_SYSTEM_PROMPT.lower()
        assert "not a whitelist" in low
        assert "which verb advances the beat" in low
        assert "still call request_death_save when death_saves_due names someone" in low
        assert "only the verbs in next.verbs are legal" not in low, "the whitelist reading is back"
        assert "call request_death_save" in low
        assert "call consume_legendary_action" in low

    def test_beat2_says_the_enemy_blows_are_held(self):
        """The prompt must not imply a held enemy blow has already resolved."""
        low = COMBAT_SYSTEM_PROMPT.lower()
        assert "holds every enemy action back for beat 3" in low
        assert "the enemy blows are held" in low

    def test_the_prompt_warns_that_end_combat_is_refused_mid_beat(self):
        """The DM needs the refusal state before attempting another declaration."""
        low = COMBAT_SYSTEM_PROMPT.lower()
        assert "refuse while enemy actions are still held" in low

    def test_honors_dramatic_pause(self):
        # "pause" alone leaks from VOICE_STYLE ("Use pauses") and the Beat-4 death-save
        # line; anchor on the unique Beat-3 phrase so deleting it actually fails.
        assert "pause for the dramatic dice" in COMBAT_SYSTEM_PROMPT.lower()

    def test_player_action_must_be_equipped_weapon_name(self):
        low = COMBAT_SYSTEM_PROMPT.lower()
        attack_kind = low[low.index("attack — action is") : low.index("ability — action is")]
        assert "exact name" in attack_kind and "equipped weapon" in attack_kind
        assert "combatants[].actions" in attack_kind
        assert low.index("combatants[].actions") < low.index("call declare_phase")
        # start_combat's tool output never reaches CombatAgent (the handoff drops it).
        assert "start_combat's participants" not in low and "from their action_pool" not in low

    def test_in_combat_ability_is_a_declaration_not_activate(self):
        prompt = COMBAT_SYSTEM_PROMPT
        assert "ability — action is the EXACT id of a spell" in prompt
        assert "activate" in prompt
        assert "ordinary spell or ability" in prompt
        assert "never a free cast via activate" in prompt

    def test_declare_phase_offers_no_reaction_kind_to_the_dm(self):
        """A removed reaction must not remain a prompt affordance."""
        prompt = COMBAT_SYSTEM_PROMPT
        low = prompt.lower()
        assert "Supported declarations:" in prompt
        assert "maneuver — target_id names who is moved" in prompt
        assert "reaction — action is the EXACT id" not in prompt
        assert "trigger is its catalog window" not in low
        assert "declare the reaction during beat 1" not in low

    def test_the_dm_activates_a_reaction_at_an_open_window(self):
        """Expose producer ids so the DM can invoke the available windows."""
        low = COMBAT_SYSTEM_PROMPT.lower()
        pause = low.index("the pause is the mechanic")
        teaching = low[pause : low.index("when you close a window", pause)]
        assert "activate" in teaching
        assert "next.waiting_on.reactions" in teaching
        assert "next.waiting_on.triggers" not in teaching, "the prompt still sends the DM to triggers for an id"
        assert "one reaction per round" in teaching
        assert "no pre-declaration" in teaching

    def test_the_prompt_says_to_declare_the_active_variant_id(self):
        low = COMBAT_SYSTEM_PROMPT.lower()
        assert "active_variant_id" in low
        assert "declare that exact variant id" in low

    def test_no_reaction_packet_narration_advice_survives(self):
        assert "narrate a reaction packet as successful" not in COMBAT_SYSTEM_PROMPT.lower()

    def test_the_dm_is_told_what_a_reaction_packet_reports(self):
        """A mechanical reaction cue must not claim an unresolved outcome.
        Sidestep and Retaliating Shield distinguish activation from the eventual blow."""
        low = COMBAT_SYSTEM_PROMPT.lower()
        assert "mechanical_effect" in low
        effect = low.index("mechanical_effect")
        teaching = low[effect : low.index("next.verbs", effect)]
        assert "damage_halved" in teaching
        assert "target_ac_bonus" in teaching
        assert "shield_durability" in teaching
        assert "null" in teaching
        assert "narration_cue" in teaching
        assert "not a report" in teaching

    def test_combat_only_capabilities_still_use_activate(self):
        low = COMBAT_SYSTEM_PROMPT.lower()
        assert "draethar_inner_fire" in low
        assert "veil_ward" in low

    def test_the_never_activate_rule_carves_out_reactions(self):
        """The narration prohibition must apply alongside its explicit carve-out."""
        low = COMBAT_SYSTEM_PROMPT.lower()
        prohibition = low.index("never a free cast via activate")
        carve_out = low[prohibition : prohibition + 400]
        assert "reaction" in carve_out


class TestCombatHotContext:
    """Combat changes must not invalidate the cached static prefix."""

    @staticmethod
    def _agent_and_session(combat_state):
        sd = SessionData(player_id="p1", location_id="accord_guild_hall")
        sd.combat_state = combat_state
        session = MagicMock()
        session.userdata = sd
        return CombatAgent(), session

    @staticmethod
    async def _take_turn(agent, session, turn_ctx):
        with (
            patch.object(type(agent), "session", new_callable=lambda: property(lambda self: session)),
            patch.object(agent, "update_instructions", new_callable=AsyncMock) as update,
        ):
            await agent.on_user_turn_completed(turn_ctx, ChatMessage(role="user", content=["I swing at Grosh."]))
        return update

    async def test_the_turn_carries_the_round_and_each_hp_status_as_a_message(self):
        agent, session = self._agent_and_session(sample_combat_state(round_number=3, hp_current=8))
        turn_ctx = ChatContext.empty()  # the real vendor type, not a mock (constraint 9)

        update = await self._take_turn(agent, session, turn_ctx)

        assert turn_ctx.items, "the turn context carries nothing at all"
        text = " ".join(
            str(item.content) for item in turn_ctx.items if isinstance(item, ChatMessage) and item.role == "assistant"
        )
        assert "Round 3" in text
        assert "Kael(healthy)" in text
        assert "Grosh(bloodied)" in text
        update.assert_not_called()

    async def test_speaker_message_out_of_combat(self):
        agent, session = self._agent_and_session(None)
        turn_ctx = ChatContext.empty()

        await self._take_turn(agent, session, turn_ctx)

        assert "[Speaker: player p1]" in " ".join(
            str(item.content) for item in turn_ctx.items if isinstance(item, ChatMessage)
        )

    async def test_guest_speaker_uses_live_combat_hp(self):
        state = sample_combat_state(round_number=3)
        state.participants[0].id = "guest"
        state.participants[0].hp_current = 3
        state.participants[0].hp_max = 12
        state.initiative_order[0] = "guest"
        agent, session = self._agent_and_session(state)
        sd = session.userdata
        sd.party.members.append(
            PartyMember(player_id="guest", resonance=ResonanceTrack(), concentration=ConcentrationState())
        )
        sd.speaker_summaries["guest"] = build_speaker_context(
            "guest", {"name": "Bryn", "hp": {"current": 12, "max": 12}}, [], [], []
        )
        with sd._bind_authenticated_actor("guest", 1, lambda *_: None):
            turn_ctx = ChatContext.empty()
            await self._take_turn(agent, session, turn_ctx)
        text = " ".join(str(item.content) for item in turn_ctx.items if isinstance(item, ChatMessage))
        assert "Speaker: Bryn (player guest); HP 3/12" in text
        assert "12/12" not in text
        assert "Round 3" in text

    async def test_speaker_outside_the_fight_keeps_cached_hp(self):
        agent, session = self._agent_and_session(sample_combat_state(round_number=3))
        sd = session.userdata
        sd.party.members.append(
            PartyMember(player_id="guest", resonance=ResonanceTrack(), concentration=ConcentrationState())
        )
        sd.speaker_summaries["guest"] = build_speaker_context(
            "guest", {"name": "Bryn", "hp": {"current": 7, "max": 12}}, [], [], []
        )
        with sd._bind_authenticated_actor("guest", 1, lambda *_: None):
            turn_ctx = ChatContext.empty()
            await self._take_turn(agent, session, turn_ctx)
        text = " ".join(str(item.content) for item in turn_ctx.items if isinstance(item, ChatMessage))
        assert "Speaker: Bryn (player guest); HP 7/12" in text
