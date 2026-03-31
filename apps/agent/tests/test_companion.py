"""Tests for companion system (Milestone 6.2)."""

import json
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import event_types as E
from background_process import (
    COMPANION_IDLE_SECS,
    BackgroundProcess,
    SpeechPriority,
)
from event_bus import GameEvent
from session_data import (
    MAX_COMPANION_MEMORIES,
    CombatParticipant,
    CombatState,
    CompanionState,
    SessionData,
)

# --- WU1: CompanionState + SessionData ---


class TestCompanionState:
    def test_default_values(self):
        cs = CompanionState(id="companion_kael", name="Kael")
        assert cs.is_present is True
        assert cs.is_conscious is True
        assert cs.emotional_state == "steady"
        assert cs.relationship_tier == 1
        assert cs.session_memories == []
        assert cs.last_speech_time == 0.0

    def test_serialization(self):
        cs = CompanionState(id="companion_kael", name="Kael", emotional_state="alert")
        d = asdict(cs)
        assert d["id"] == "companion_kael"
        assert d["name"] == "Kael"
        assert d["emotional_state"] == "alert"
        assert d["is_conscious"] is True


class TestSessionDataCompanion:
    def test_has_companion_true(self):
        sd = SessionData(player_id="p1", location_id="loc")
        sd.companion = CompanionState(id="companion_kael", name="Kael")
        assert sd.has_companion is True

    def test_has_companion_false_when_none(self):
        sd = SessionData(player_id="p1", location_id="loc")
        assert sd.has_companion is False

    def test_has_companion_false_when_not_present(self):
        sd = SessionData(player_id="p1", location_id="loc")
        sd.companion = CompanionState(id="companion_kael", name="Kael", is_present=False)
        assert sd.has_companion is False

    def test_record_companion_memory(self):
        sd = SessionData(player_id="p1", location_id="loc")
        sd.companion = CompanionState(id="companion_kael", name="Kael")
        sd.record_companion_memory("Traveled to Millhaven")
        assert "Traveled to Millhaven" in sd.companion.session_memories

    def test_record_companion_memory_caps_at_max(self):
        sd = SessionData(player_id="p1", location_id="loc")
        sd.companion = CompanionState(id="companion_kael", name="Kael")
        for i in range(MAX_COMPANION_MEMORIES + 5):
            sd.record_companion_memory(f"Memory {i}")
        assert len(sd.companion.session_memories) == MAX_COMPANION_MEMORIES
        assert sd.companion.session_memories[0] == "Memory 5"

    def test_record_companion_memory_no_companion(self):
        sd = SessionData(player_id="p1", location_id="loc")
        sd.record_companion_memory("Should not crash")
        # No error raised


class TestKaelEntity:
    def test_kael_entity_valid_schema(self):
        with open("../../content/npcs.json") as f:
            npcs = json.load(f)
        kael = next(n for n in npcs if n["id"] == "companion_kael")

        assert kael["name"] == "Kael"
        assert kael["role"] == "companion, former caravan guard"
        assert kael["default_disposition"] == "friendly"
        assert kael["voice_id"] == "COMPANION_KAEL"

        # Has 3 knowledge tiers
        knowledge = kael["knowledge"]
        assert "free" in knowledge
        assert "disposition >= friendly" in knowledge
        assert "disposition >= trusted" in knowledge
        assert len(knowledge["free"]) >= 2

        # Combat stats
        stats = kael["combat_stats"]
        assert stats["hp"] == 22
        assert stats["ac"] == 15
        assert stats["level"] == 2
        assert len(stats["action_pool"]) >= 2

        # Personality
        assert len(kael["personality"]) >= 3
        assert "speech_style" in kael
        assert len(kael["mannerisms"]) >= 2


# --- WU2: Companion Prompt Layer ---


class TestCompanionPrompt:
    def test_system_prompt_includes_companion_when_present(self):
        from prompts import build_system_prompt

        companion = CompanionState(id="companion_kael", name="Kael")
        prompt = build_system_prompt("accord_guild_hall", companion=companion)
        assert "Companion" in prompt
        assert "COMPANION_KAEL" in prompt
        assert "warm baritone" in prompt

    def test_system_prompt_excludes_companion_when_none(self):
        from prompts import build_system_prompt

        prompt = build_system_prompt("accord_guild_hall", companion=None)
        assert "Companion — Kael" not in prompt

    def test_system_prompt_excludes_companion_when_not_present(self):
        from prompts import build_system_prompt

        companion = CompanionState(id="companion_kael", name="Kael", is_present=False)
        prompt = build_system_prompt("accord_guild_hall", companion=companion)
        assert "Companion — Kael" not in prompt

    @patch("db.get_active_player_quests", new_callable=AsyncMock)
    @patch("db.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db.get_location", new_callable=AsyncMock)
    async def test_warm_layer_includes_companion(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        from prompts import build_warm_layer

        mock_loc.return_value = {
            "id": "test_loc",
            "name": "Test Location",
            "description": "A test.",
            "atmosphere": "calm",
            "exits": {},
        }
        mock_npcs.return_value = []
        mock_quests.return_value = []

        companion = CompanionState(
            id="companion_kael",
            name="Kael",
            emotional_state="alert",
            relationship_tier=2,
            session_memories=["Traveled to Millhaven", "Fought goblins"],
        )

        result = await build_warm_layer("test_loc", "p1", "evening", companion=companion)
        assert "COMPANION — Kael" in result
        assert "alert" in result
        assert "Relationship tier: 2" in result
        assert "Traveled to Millhaven" in result

    @patch("db.get_active_player_quests", new_callable=AsyncMock)
    @patch("db.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db.get_location", new_callable=AsyncMock)
    async def test_warm_layer_shows_unconscious(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        from prompts import build_warm_layer

        mock_loc.return_value = {
            "id": "test_loc",
            "name": "Test",
            "description": "A test.",
            "atmosphere": "calm",
            "exits": {},
        }
        mock_npcs.return_value = []
        mock_quests.return_value = []

        companion = CompanionState(id="companion_kael", name="Kael", is_conscious=False)

        result = await build_warm_layer("test_loc", "p1", "evening", companion=companion)
        assert "Conscious: no" in result

    @patch("db.get_active_player_quests", new_callable=AsyncMock)
    @patch("db.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db.get_location", new_callable=AsyncMock)
    async def test_warm_layer_no_companion_section_when_none(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        from prompts import build_warm_layer

        mock_loc.return_value = {
            "id": "test_loc",
            "name": "Test",
            "description": "A test.",
            "atmosphere": "calm",
            "exits": {},
        }
        mock_npcs.return_value = []
        mock_quests.return_value = []

        result = await build_warm_layer("test_loc", "p1", "evening", companion=None)
        assert "COMPANION" not in result


class TestKaelVoiceRateOffset:
    def test_kael_rate_offset(self):
        from voices import get_voice_config

        cfg = get_voice_config("COMPANION_KAEL", "neutral")
        # neutral rate = 0.95, offset = -0.05 → 0.90
        assert cfg.speaking_rate == pytest.approx(0.90)
        assert cfg.inworld_markup == ""  # neutral has no markup


# --- WU3: Proactive Companion Speech ---


def _make_session_data(**kwargs) -> SessionData:
    defaults = dict(player_id="player_1", location_id="accord_guild_hall", room=None)
    defaults.update(kwargs)
    return SessionData(**defaults)


def _make_bg(session_data=None) -> tuple[BackgroundProcess, MagicMock, MagicMock]:
    sd = session_data or _make_session_data()
    agent = MagicMock()
    agent.update_instructions = AsyncMock()
    session = MagicMock()
    session.generate_reply = AsyncMock()
    bg = BackgroundProcess(agent=agent, session=session, session_data=sd)
    return bg, agent, session


class TestCompanionSpeechInEvents:
    def test_location_changed_with_companion_mentions_kael(self):
        sd = _make_session_data()
        sd.companion = CompanionState(id="companion_kael", name="Kael", last_speech_time=time.time())
        bg, _, _ = _make_bg(session_data=sd)
        events = [GameEvent(event_type=E.LOCATION_CHANGED, payload={"new_location": "market"})]
        bg._handle_events(events)
        assert len(bg._speech_queue) == 1
        assert "COMPANION_KAEL" in bg._speech_queue[0].instructions

    def test_location_changed_without_companion_no_kael(self):
        sd = _make_session_data()
        bg, _, _ = _make_bg(session_data=sd)
        events = [GameEvent(event_type=E.LOCATION_CHANGED, payload={"new_location": "market"})]
        bg._handle_events(events)
        assert len(bg._speech_queue) == 1
        assert "COMPANION_KAEL" not in bg._speech_queue[0].instructions

    def test_quest_updated_with_companion(self):
        sd = _make_session_data()
        sd.companion = CompanionState(id="companion_kael", name="Kael")
        bg, _, _ = _make_bg(session_data=sd)
        events = [GameEvent(event_type=E.QUEST_UPDATED, payload={"quest_name": "Test", "objective": "Do thing"})]
        bg._handle_events(events)
        assert "COMPANION_KAEL" in bg._speech_queue[0].instructions

    def test_combat_ended_victory_with_companion(self):
        sd = _make_session_data()
        sd.companion = CompanionState(id="companion_kael", name="Kael")
        bg, _, _ = _make_bg(session_data=sd)
        events = [GameEvent(event_type=E.COMBAT_ENDED, payload={"outcome": "victory"})]
        bg._handle_events(events)
        assert "COMPANION_KAEL" in bg._speech_queue[0].instructions
        assert sd.companion.emotional_state == "relieved"

    def test_combat_ended_victory_restores_unconscious_companion(self):
        sd = _make_session_data()
        sd.companion = CompanionState(id="companion_kael", name="Kael", is_conscious=False)
        bg, _, _ = _make_bg(session_data=sd)
        events = [GameEvent(event_type=E.COMBAT_ENDED, payload={"outcome": "victory"})]
        bg._handle_events(events)
        assert sd.companion.is_conscious is True
        assert sd.companion.emotional_state == "weary"

    def test_disposition_changed_with_companion(self):
        sd = _make_session_data()
        sd.companion = CompanionState(id="companion_kael", name="Kael")
        bg, _, _ = _make_bg(session_data=sd)
        events = [
            GameEvent(
                event_type=E.DISPOSITION_CHANGED,
                payload={"npc_name": "Torin", "previous": "neutral", "new": "friendly"},
            )
        ]
        bg._handle_events(events)
        assert len(bg._speech_queue) == 1
        assert "approves" in bg._speech_queue[0].instructions
        assert sd.companion.emotional_state == "pleased"


class TestCompanionIdleSpeech:
    def test_queues_speech_after_idle(self):
        sd = _make_session_data()
        sd.companion = CompanionState(
            id="companion_kael",
            name="Kael",
            last_speech_time=time.time() - COMPANION_IDLE_SECS - 1,
        )
        bg, _, _ = _make_bg(session_data=sd)
        bg._check_companion_idle()
        assert len(bg._speech_queue) == 1
        assert "COMPANION_KAEL" in bg._speech_queue[0].instructions
        assert bg._speech_queue[0].priority == SpeechPriority.ROUTINE

    def test_skips_during_combat(self):
        cs = CombatState(
            combat_id="test",
            participants=[
                CombatParticipant(id="p1", name="P", type="player", initiative=10, hp_current=10, hp_max=10, ac=10)
            ],
            initiative_order=["p1"],
        )
        sd = _make_session_data(combat_state=cs)
        sd.companion = CompanionState(
            id="companion_kael",
            name="Kael",
            last_speech_time=time.time() - 100,
        )
        bg, _, _ = _make_bg(session_data=sd)
        bg._check_companion_idle()
        assert len(bg._speech_queue) == 0

    def test_skips_when_no_companion(self):
        sd = _make_session_data()
        bg, _, _ = _make_bg(session_data=sd)
        bg._check_companion_idle()
        assert len(bg._speech_queue) == 0

    def test_skips_when_unconscious(self):
        sd = _make_session_data()
        sd.companion = CompanionState(
            id="companion_kael",
            name="Kael",
            is_conscious=False,
            last_speech_time=time.time() - 100,
        )
        bg, _, _ = _make_bg(session_data=sd)
        bg._check_companion_idle()
        assert len(bg._speech_queue) == 0

    def test_skips_when_no_speech_time(self):
        sd = _make_session_data()
        sd.companion = CompanionState(id="companion_kael", name="Kael", last_speech_time=0)
        bg, _, _ = _make_bg(session_data=sd)
        bg._check_companion_idle()
        assert len(bg._speech_queue) == 0


class TestQuestHints:
    def test_get_quest_hints_returns_hint_for_current_stage(self):
        sd = _make_session_data()
        bg, _, _ = _make_bg(session_data=sd)
        bg._quest_cache = [
            {
                "quest_id": "greyvale_anomaly",
                "current_stage": 0,
                "global_hints": {"stuck_stage_1": "Head north to Millhaven."},
            }
        ]
        hints = bg._get_quest_hints()
        assert hints == ["Head north to Millhaven."]

    def test_get_quest_hints_empty_without_cache(self):
        sd = _make_session_data()
        bg, _, _ = _make_bg(session_data=sd)
        hints = bg._get_quest_hints()
        assert hints == []

    def test_get_quest_hints_no_matching_stage(self):
        sd = _make_session_data()
        bg, _, _ = _make_bg(session_data=sd)
        bg._quest_cache = [
            {
                "quest_id": "greyvale_anomaly",
                "current_stage": 4,
                "global_hints": {"stuck_stage_1": "Head north."},
            }
        ]
        hints = bg._get_quest_hints()
        assert hints == []

    def test_guidance_with_companion_uses_kael(self):
        sd = _make_session_data()
        sd.companion = CompanionState(id="companion_kael", name="Kael")
        past = time.time() - 40
        sd.last_player_speech_time = past
        sd.last_agent_speech_end = past
        bg, _, _ = _make_bg(session_data=sd)
        bg._check_guidance()
        assert len(bg._speech_queue) == 1
        assert "COMPANION_KAEL" in bg._speech_queue[0].instructions


# --- WU4: Companion in Combat ---


SAMPLE_ENCOUNTER = {
    "id": "goblin_patrol",
    "name": "Goblin Patrol",
    "enemies": [
        {
            "id": "goblin_1",
            "name": "Goblin Scout",
            "level": 1,
            "ac": 13,
            "hp": 7,
            "attributes": {"strength": 8, "dexterity": 14},
            "action_pool": [{"name": "Scimitar", "damage": "1d6", "damage_type": "slashing", "properties": []}],
            "xp_value": 50,
        }
    ],
}

SAMPLE_PLAYER = {
    "player_id": "player_1",
    "name": "Hero",
    "level": 1,
    "attributes": {
        "strength": 14,
        "dexterity": 12,
        "constitution": 13,
        "intelligence": 10,
        "wisdom": 11,
        "charisma": 8,
    },
    "hp": {"current": 25, "max": 25},
    "ac": 14,
}

KAEL_NPC = {
    "id": "companion_kael",
    "name": "Kael",
    "combat_stats": {
        "hp": 22,
        "ac": 15,
        "level": 2,
        "attributes": {
            "strength": 15,
            "dexterity": 13,
            "constitution": 14,
            "intelligence": 10,
            "wisdom": 12,
            "charisma": 11,
        },
        "action_pool": [
            {"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": ["versatile"]},
        ],
    },
}


def _make_context(player_id="player_1", location_id="accord_guild_hall", room=None):
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id=player_id, location_id=location_id, room=room)
    return ctx


class TestCompanionInCombat:
    @pytest.mark.asyncio
    @patch("tools.db.get_npc", new_callable=AsyncMock)
    @patch("tools.db.save_combat_state", new_callable=AsyncMock)
    @patch("tools.db.get_player", new_callable=AsyncMock)
    @patch("tools.db.get_encounter_template", new_callable=AsyncMock)
    async def test_start_combat_includes_companion(self, mock_encounter, mock_player, mock_save, mock_get_npc):
        from tools import start_combat

        mock_encounter.return_value = SAMPLE_ENCOUNTER
        mock_player.return_value = SAMPLE_PLAYER
        mock_get_npc.return_value = KAEL_NPC

        ctx = _make_context()
        ctx.userdata.companion = CompanionState(id="companion_kael", name="Kael")

        raw = await start_combat._func(ctx, encounter_id="goblin_patrol", encounter_description="Fight!")
        _, json_str = raw
        result = json.loads(json_str)

        assert len(result["participants"]) == 3
        companion_p = next(p for p in result["participants"] if p["name"] == "Kael")
        assert companion_p["type"] == "companion"
        assert companion_p["ac"] == 15
        # Verify the actual combat state participant has correct stats
        cs = ctx.userdata.combat_state
        kael_p = cs.get_participant("companion_kael")
        assert kael_p is not None
        assert kael_p.hp_current == 22
        assert kael_p.hp_max == 22

    @pytest.mark.asyncio
    @patch("tools.db.save_combat_state", new_callable=AsyncMock)
    @patch("tools.db.get_player", new_callable=AsyncMock)
    @patch("tools.db.get_encounter_template", new_callable=AsyncMock)
    async def test_start_combat_no_companion_when_absent(self, mock_encounter, mock_player, mock_save):
        from tools import start_combat

        mock_encounter.return_value = SAMPLE_ENCOUNTER
        mock_player.return_value = SAMPLE_PLAYER

        ctx = _make_context()

        _, json_str = await start_combat._func(ctx, encounter_id="goblin_patrol", encounter_description="Fight!")
        result = json.loads(json_str)

        assert len(result["participants"]) == 2

    @pytest.mark.asyncio
    @patch("tools.db.get_npc", new_callable=AsyncMock)
    @patch("tools.db.save_combat_state", new_callable=AsyncMock)
    @patch("tools.db.get_player", new_callable=AsyncMock)
    @patch("tools.db.get_encounter_template", new_callable=AsyncMock)
    async def test_start_combat_no_companion_when_unconscious(
        self, mock_encounter, mock_player, mock_save, mock_get_npc
    ):
        from tools import start_combat

        mock_encounter.return_value = SAMPLE_ENCOUNTER
        mock_player.return_value = SAMPLE_PLAYER
        mock_get_npc.return_value = KAEL_NPC

        ctx = _make_context()
        ctx.userdata.companion = CompanionState(id="companion_kael", name="Kael", is_conscious=False)

        _, json_str = await start_combat._func(ctx, encounter_id="goblin_patrol", encounter_description="Fight!")
        result = json.loads(json_str)

        assert len(result["participants"]) == 2

    @pytest.mark.asyncio
    @patch("tools.db.save_combat_state", new_callable=AsyncMock)
    async def test_companion_ko_sets_unconscious(self, mock_save):
        from tools import resolve_enemy_turn

        ctx = _make_context()
        ctx.userdata.companion = CompanionState(id="companion_kael", name="Kael")

        # Build combat state with companion at 1 HP
        cs = CombatState(
            combat_id="combat_test",
            participants=[
                CombatParticipant(
                    id="player_1", name="Hero", type="player", initiative=15, hp_current=25, hp_max=25, ac=14
                ),
                CombatParticipant(
                    id="goblin_1",
                    name="Goblin",
                    type="enemy",
                    initiative=12,
                    hp_current=7,
                    hp_max=7,
                    ac=13,
                    action_pool=[{"name": "Scimitar", "damage": "1d6", "damage_type": "slashing", "properties": []}],
                ),
                CombatParticipant(
                    id="companion_kael",
                    name="Kael",
                    type="companion",
                    initiative=10,
                    hp_current=1,
                    hp_max=22,
                    ac=15,
                    action_pool=[{"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}],
                ),
            ],
            initiative_order=["player_1", "goblin_1", "companion_kael"],
        )
        ctx.userdata.combat_state = cs

        result = json.loads(
            await resolve_enemy_turn._func(ctx, enemy_id="goblin_1", action_name="Scimitar", target_id="companion_kael")
        )

        if result["hit"]:
            assert ctx.userdata.companion.is_conscious is False
            assert "knocked unconscious" in ctx.userdata.companion.session_memories[-1]


# --- WU5: Meeting Scene ---


class TestMeetingScene:
    def test_meeting_triggers_on_market_visit(self):
        sd = _make_session_data()
        bg, _, _ = _make_bg(session_data=sd)
        events = [GameEvent(event_type=E.LOCATION_CHANGED, payload={"new_location": "accord_market_square"})]
        bg._handle_events(events)
        assert len(bg._speech_queue) == 1
        assert bg._speech_queue[0].priority == SpeechPriority.CRITICAL
        assert "commotion" in bg._speech_queue[0].instructions.lower()

    def test_meeting_does_not_retrigger(self):
        sd = _make_session_data()
        bg, _, _ = _make_bg(session_data=sd)
        events = [GameEvent(event_type=E.LOCATION_CHANGED, payload={"new_location": "accord_market_square"})]
        bg._handle_events(events)
        bg._speech_queue.clear()

        # Second visit
        bg._handle_events(events)
        assert len(bg._speech_queue) == 1
        # Should be a regular location speech, not the meeting
        assert "commotion" not in bg._speech_queue[0].instructions.lower()

    def test_meeting_does_not_trigger_when_companion_present(self):
        sd = _make_session_data()
        sd.companion = CompanionState(id="companion_kael", name="Kael")
        bg, _, _ = _make_bg(session_data=sd)
        events = [GameEvent(event_type=E.LOCATION_CHANGED, payload={"new_location": "accord_market_square"})]
        bg._handle_events(events)
        assert "commotion" not in bg._speech_queue[0].instructions.lower()

    @pytest.mark.asyncio
    async def test_initialize_companion_after_meeting(self):
        sd = _make_session_data()
        bg, _, _ = _make_bg(session_data=sd)

        with patch("db.set_player_flag", new_callable=AsyncMock) as mock_flag:
            with patch.object(bg, "_rebuild_warm_layer", new_callable=AsyncMock):
                await bg._initialize_companion_after_meeting()

        assert sd.companion is not None
        assert sd.companion.id == "companion_kael"
        assert sd.companion.name == "Kael"
        mock_flag.assert_awaited_once_with("player_1", "companion_met", True)


# --- WU6: Emotional State + Memory ---


class TestEmotionalState:
    def test_location_changed_sets_curious(self):
        sd = _make_session_data()
        sd.companion = CompanionState(id="companion_kael", name="Kael")
        bg, _, _ = _make_bg(session_data=sd)
        events = [GameEvent(event_type=E.LOCATION_CHANGED, payload={"new_location": "market"})]
        bg._handle_events(events)
        assert sd.companion.emotional_state == "curious"

    def test_quest_updated_sets_focused(self):
        sd = _make_session_data()
        sd.companion = CompanionState(id="companion_kael", name="Kael")
        bg, _, _ = _make_bg(session_data=sd)
        events = [GameEvent(event_type=E.QUEST_UPDATED, payload={"quest_name": "Test", "objective": "Do"})]
        bg._handle_events(events)
        assert sd.companion.emotional_state == "focused"

    def test_combat_ended_sets_relieved(self):
        sd = _make_session_data()
        sd.companion = CompanionState(id="companion_kael", name="Kael")
        bg, _, _ = _make_bg(session_data=sd)
        events = [GameEvent(event_type=E.COMBAT_ENDED, payload={"outcome": "victory"})]
        bg._handle_events(events)
        assert sd.companion.emotional_state == "relieved"

    def test_negative_disposition_sets_troubled(self):
        sd = _make_session_data()
        sd.companion = CompanionState(id="companion_kael", name="Kael")
        bg, _, _ = _make_bg(session_data=sd)
        events = [
            GameEvent(
                event_type=E.DISPOSITION_CHANGED,
                payload={"npc_name": "Torin", "previous": "friendly", "new": "neutral"},
            )
        ]
        bg._handle_events(events)
        assert sd.companion.emotional_state == "troubled"


_mock_conn = MagicMock(name="mock_txn_conn")


@asynccontextmanager
async def _mock_transaction():
    yield _mock_conn


@patch("tools.db.transaction", _mock_transaction)
class TestCompanionMemoryInTools:
    @pytest.mark.asyncio
    @patch("tools.db.get_player", new_callable=AsyncMock)
    @patch("tools.db.get_targets_at_location", new_callable=AsyncMock)
    @patch("tools.db.get_npc_dispositions", new_callable=AsyncMock)
    @patch("tools.db.get_npcs_at_location", new_callable=AsyncMock)
    @patch("tools.db.upsert_map_progress", new_callable=AsyncMock)
    @patch("tools.db.update_player_location", new_callable=AsyncMock)
    @patch("tools.db.get_location", new_callable=AsyncMock)
    async def test_move_player_records_memory(
        self, mock_loc, mock_update, mock_upsert, mock_npcs, mock_disp, mock_targets, mock_player
    ):
        from tools import move_player

        mock_loc.side_effect = [
            {"id": "guild", "name": "Guild Hall", "exits": {"south": {"destination": "market"}}},
            {
                "id": "market",
                "name": "Market Square",
                "description": "Busy market",
                "atmosphere": "lively",
                "exits": {},
            },
            {
                "id": "market",
                "name": "Market Square",
                "description": "Busy market",
                "atmosphere": "lively",
                "exits": {},
            },
        ]
        mock_npcs.return_value = []
        mock_targets.return_value = []
        mock_player.return_value = SAMPLE_PLAYER
        mock_disp.return_value = {}

        ctx = _make_context()
        ctx.userdata.companion = CompanionState(id="companion_kael", name="Kael")

        await move_player._func(ctx, destination_id="market")

        assert any("Market Square" in m for m in ctx.userdata.companion.session_memories)


class TestDeliverSpeechUpdatesCompanionTime:
    @pytest.mark.asyncio
    async def test_companion_speech_updates_last_speech_time(self):
        sd = _make_session_data()
        sd.companion = CompanionState(id="companion_kael", name="Kael", last_speech_time=0)
        bg, _, _session = _make_bg(session_data=sd)
        from background_process import PendingSpeech

        bg._speech_queue = [
            PendingSpeech(priority=SpeechPriority.IMPORTANT, instructions="Use [COMPANION_KAEL, calm] tag."),
        ]
        await bg._deliver_speech()
        assert sd.companion.last_speech_time > 0
