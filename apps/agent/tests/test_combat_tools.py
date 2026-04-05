"""Integration tests for combat tools (mocked DB + room)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import event_types as E
from session_data import CombatParticipant, CombatState, SessionData
from tools import (
    end_combat,
    request_death_save,
    resolve_enemy_turn,
    start_combat,
)

SAMPLE_PLAYER = {
    "player_id": "player_1",
    "name": "Kael",
    "class": "warrior",
    "level": 1,
    "attributes": {
        "strength": 14,
        "dexterity": 12,
        "constitution": 13,
        "intelligence": 10,
        "wisdom": 11,
        "charisma": 8,
    },
    "proficiencies": ["athletics", "stealth", "perception"],
    "saving_throw_proficiencies": ["strength", "constitution"],
    "equipment": {
        "main_hand": {
            "name": "Longsword",
            "damage": "1d8",
            "damage_type": "slashing",
            "properties": [],
        }
    },
    "hp": {"current": 25, "max": 25},
    "ac": 14,
}

SAMPLE_ENCOUNTER = {
    "id": "goblin_patrol",
    "name": "Goblin Patrol",
    "difficulty": "easy",
    "enemies": [
        {
            "id": "goblin_scout_1",
            "name": "Goblin Scout",
            "level": 1,
            "ac": 13,
            "hp": 7,
            "attributes": {
                "strength": 8,
                "dexterity": 14,
                "constitution": 10,
                "intelligence": 10,
                "wisdom": 8,
                "charisma": 8,
            },
            "action_pool": [
                {
                    "name": "Scimitar",
                    "damage": "1d6",
                    "damage_type": "slashing",
                    "properties": ["light"],
                },
                {
                    "name": "Shortbow",
                    "damage": "1d6",
                    "damage_type": "piercing",
                    "properties": [],
                    "ranged": True,
                },
            ],
            "xp_value": 50,
        },
    ],
}


def _make_context(player_id="player_1", location_id="accord_guild_hall", room=None):
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id=player_id, location_id=location_id, room=room)
    return ctx


def _make_mock_room():
    room = MagicMock()
    room.local_participant = MagicMock()
    room.local_participant.publish_data = AsyncMock()
    return room


def _make_combat_state(player_hp=25, player_fallen=False, enemy_hp=7, enemy_fallen=False):
    """Create a CombatState for testing."""
    return CombatState(
        combat_id="combat_test123",
        participants=[
            CombatParticipant(
                id="player_1",
                name="Kael",
                type="player",
                initiative=15,
                hp_current=player_hp,
                hp_max=25,
                ac=14,
                is_fallen=player_fallen,
            ),
            CombatParticipant(
                id="goblin_scout_1",
                name="Goblin Scout",
                type="enemy",
                initiative=12,
                hp_current=enemy_hp,
                hp_max=7,
                ac=13,
                action_pool=[
                    {
                        "name": "Scimitar",
                        "damage": "1d6",
                        "damage_type": "slashing",
                        "properties": ["light"],
                    },
                ],
                xp_value=50,
            ),
        ],
        initiative_order=["player_1", "goblin_scout_1"],
        round_number=1,
        current_turn_index=0,
        location_id="accord_guild_hall",
    )


# --- start_combat ---


class TestStartCombat:
    @pytest.mark.asyncio
    @patch("tools.db_mutations.save_combat_state", new_callable=AsyncMock)
    @patch("tools.db_queries.get_player", new_callable=AsyncMock)
    @patch("tools.db_content_queries.get_encounter_template", new_callable=AsyncMock)
    async def test_creates_combat_state(self, mock_encounter, mock_player, mock_save):
        mock_encounter.return_value = SAMPLE_ENCOUNTER
        mock_player.return_value = SAMPLE_PLAYER
        ctx = _make_context()

        raw = await start_combat._func(ctx, encounter_id="goblin_patrol", encounter_description="Goblins ambush!")
        assert isinstance(raw, tuple), "start_combat success should return (CombatAgent, json_str)"
        _, json_str = raw
        result = json.loads(json_str)

        assert "combat_id" in result
        assert result["encounter_name"] == "Goblin Patrol"
        assert len(result["initiative_order"]) == 2
        assert len(result["participants"]) == 2
        assert ctx.userdata.in_combat is True
        assert ctx.userdata.combat_state is not None
        mock_save.assert_called_once()

    @pytest.mark.asyncio
    @patch("tools.db_mutations.save_combat_state", new_callable=AsyncMock)
    @patch("tools.db_queries.get_player", new_callable=AsyncMock)
    @patch("tools.db_content_queries.get_encounter_template", new_callable=AsyncMock)
    async def test_returns_agent_tuple(self, mock_encounter, mock_player, mock_save):
        mock_encounter.return_value = SAMPLE_ENCOUNTER
        mock_player.return_value = SAMPLE_PLAYER
        ctx = _make_context()

        raw = await start_combat._func(ctx, encounter_id="goblin_patrol", encounter_description="Ambush!")
        assert isinstance(raw, tuple)
        assert len(raw) == 2

    @pytest.mark.asyncio
    @patch("tools.db_mutations.save_combat_state", new_callable=AsyncMock)
    @patch("tools.db_queries.get_player", new_callable=AsyncMock)
    @patch("tools.db_content_queries.get_encounter_template", new_callable=AsyncMock)
    async def test_rolls_initiative(self, mock_encounter, mock_player, mock_save):
        mock_encounter.return_value = SAMPLE_ENCOUNTER
        mock_player.return_value = SAMPLE_PLAYER
        ctx = _make_context()

        _, json_str = await start_combat._func(ctx, encounter_id="goblin_patrol", encounter_description="Ambush!")
        result = json.loads(json_str)

        for entry in result["initiative_order"]:
            assert "roll" in entry
            assert "total" in entry
            assert entry["roll"] >= 1 and entry["roll"] <= 20

    @pytest.mark.asyncio
    @patch("tools.db_mutations.save_combat_state", new_callable=AsyncMock)
    @patch("tools.db_queries.get_player", new_callable=AsyncMock)
    @patch("tools.db_content_queries.get_encounter_template", new_callable=AsyncMock)
    async def test_publishes_events(self, mock_encounter, mock_player, mock_save):
        mock_encounter.return_value = SAMPLE_ENCOUNTER
        mock_player.return_value = SAMPLE_PLAYER
        room = _make_mock_room()
        ctx = _make_context(room=room)

        await start_combat._func(ctx, encounter_id="goblin_patrol", encounter_description="Ambush!")

        # Should publish combat_started and play_sound events
        assert room.local_participant.publish_data.call_count == 2
        calls = [json.loads(c[0][0]) for c in room.local_participant.publish_data.call_args_list]
        types = [c["type"] for c in calls]
        assert E.COMBAT_STARTED in types
        assert E.PLAY_SOUND in types

    @pytest.mark.asyncio
    async def test_error_if_already_in_combat(self):
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()

        result = json.loads(
            await start_combat._func(ctx, encounter_id="goblin_patrol", encounter_description="Another fight!")
        )

        assert "error" in result
        assert "Already in combat" in result["error"]

    @pytest.mark.asyncio
    @patch("tools.db_content_queries.get_encounter_template", new_callable=AsyncMock)
    async def test_error_missing_encounter(self, mock_encounter):
        mock_encounter.return_value = None
        ctx = _make_context()

        result = json.loads(await start_combat._func(ctx, encounter_id="nonexistent", encounter_description="Nothing"))

        assert "error" in result


# --- resolve_enemy_turn ---


class TestResolveEnemyTurn:
    @pytest.mark.asyncio
    @patch("tools.db_mutations.update_player_hp", new_callable=AsyncMock)
    @patch("tools.db_mutations.save_combat_state", new_callable=AsyncMock)
    async def test_resolves_attack(self, mock_save, mock_update_hp):
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()

        result = json.loads(
            await resolve_enemy_turn._func(ctx, enemy_id="goblin_scout_1", action_name="Scimitar", target_id="player_1")
        )

        assert "hit" in result
        assert "damage" in result
        assert "narrative_hint" in result
        assert result["attacker"] == "Goblin Scout"
        assert result["target"] == "Kael"
        mock_save.assert_called_once()

    @pytest.mark.asyncio
    @patch("tools.db_mutations.update_player_hp", new_callable=AsyncMock)
    @patch("tools.db_mutations.save_combat_state", new_callable=AsyncMock)
    async def test_updates_player_hp(self, mock_save, mock_update_hp):
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()

        result = json.loads(
            await resolve_enemy_turn._func(ctx, enemy_id="goblin_scout_1", action_name="Scimitar", target_id="player_1")
        )

        if result["hit"]:
            mock_update_hp.assert_called_once()

    @pytest.mark.asyncio
    @patch("tools.db_mutations.update_player_hp", new_callable=AsyncMock)
    @patch("tools.db_mutations.save_combat_state", new_callable=AsyncMock)
    async def test_publishes_sounds(self, mock_save, mock_update_hp):
        room = _make_mock_room()
        ctx = _make_context(room=room)
        ctx.userdata.combat_state = _make_combat_state()

        await resolve_enemy_turn._func(ctx, enemy_id="goblin_scout_1", action_name="Scimitar", target_id="player_1")

        # At minimum: dice_roll event + at least one play_sound
        assert room.local_participant.publish_data.call_count >= 2

    @pytest.mark.asyncio
    @patch("tools.db_mutations.update_player_hp", new_callable=AsyncMock)
    @patch("tools.db_mutations.save_combat_state", new_callable=AsyncMock)
    async def test_triggers_heartbeat_below_50_percent(self, mock_save, mock_update_hp):
        room = _make_mock_room()
        ctx = _make_context(room=room)
        # Set player HP to 10/25 = 40%, which is bloodied
        ctx.userdata.combat_state = _make_combat_state(player_hp=10)

        result = json.loads(
            await resolve_enemy_turn._func(ctx, enemy_id="goblin_scout_1", action_name="Scimitar", target_id="player_1")
        )

        if result["hit"] and result["target_hp_status"] in ("bloodied", "critical"):
            calls = [json.loads(c[0][0]) for c in room.local_participant.publish_data.call_args_list]
            sounds = [c.get("sound_name") for c in calls if c.get("type") == E.PLAY_SOUND]
            assert "heartbeat_low_hp" in sounds

    @pytest.mark.asyncio
    @patch("tools.db_mutations.update_player_hp", new_callable=AsyncMock)
    @patch("tools.db_mutations.save_combat_state", new_callable=AsyncMock)
    async def test_sets_fallen_at_zero_hp(self, mock_save, mock_update_hp):
        ctx = _make_context()
        # Set player HP to 1 so a hit will bring to 0
        ctx.userdata.combat_state = _make_combat_state(player_hp=1)

        result = json.loads(
            await resolve_enemy_turn._func(ctx, enemy_id="goblin_scout_1", action_name="Scimitar", target_id="player_1")
        )

        if result["hit"]:
            assert result["target_fallen"] is True

    @pytest.mark.asyncio
    async def test_error_not_in_combat(self):
        ctx = _make_context()

        result = json.loads(
            await resolve_enemy_turn._func(ctx, enemy_id="goblin_scout_1", action_name="Scimitar", target_id="player_1")
        )

        assert "error" in result

    @pytest.mark.asyncio
    @patch("tools.db_mutations.save_combat_state", new_callable=AsyncMock)
    async def test_error_invalid_enemy(self, mock_save):
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()

        result = json.loads(
            await resolve_enemy_turn._func(ctx, enemy_id="nonexistent", action_name="Scimitar", target_id="player_1")
        )

        assert "error" in result

    @pytest.mark.asyncio
    @patch("tools.db_mutations.save_combat_state", new_callable=AsyncMock)
    async def test_error_invalid_action(self, mock_save):
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()

        result = json.loads(
            await resolve_enemy_turn._func(ctx, enemy_id="goblin_scout_1", action_name="Fireball", target_id="player_1")
        )

        assert "error" in result

    @pytest.mark.asyncio
    @patch("tools.db_mutations.save_combat_state", new_callable=AsyncMock)
    async def test_error_fallen_target(self, mock_save):
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state(player_fallen=True, player_hp=0)

        result = json.loads(
            await resolve_enemy_turn._func(ctx, enemy_id="goblin_scout_1", action_name="Scimitar", target_id="player_1")
        )

        assert "error" in result


# --- request_death_save ---


class TestRequestDeathSave:
    @pytest.mark.asyncio
    @patch("tools.db_mutations.update_player_hp", new_callable=AsyncMock)
    @patch("tools.db_mutations.save_combat_state", new_callable=AsyncMock)
    async def test_success(self, mock_save, mock_update_hp):
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state(player_hp=0, player_fallen=True)

        result = json.loads(await request_death_save._func(ctx))

        assert "roll" in result
        assert "success" in result
        assert "total_successes" in result
        assert "total_failures" in result
        mock_save.assert_called_once()

    @pytest.mark.asyncio
    @patch("tools.db_mutations.update_player_hp", new_callable=AsyncMock)
    @patch("tools.db_mutations.save_combat_state", new_callable=AsyncMock)
    async def test_nat_20_restores_hp(self, mock_save, mock_update_hp):
        """If we get a nat 20, player should be revived with 1 HP."""
        import random

        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 20:
                # We need to patch dice.roll to use this seed
                break
        else:
            pytest.skip("Could not find seed for nat 20")

        with patch("combat_resolution.dice_roll") as mock_dice:
            from dice import DiceResult

            mock_dice.return_value = DiceResult(notation="d20", rolls=[20], dropped=[], total=20)

            ctx = _make_context()
            ctx.userdata.combat_state = _make_combat_state(player_hp=0, player_fallen=True)

            result = json.loads(await request_death_save._func(ctx))

            assert result["critical_success"] is True
            assert result["revived"] is True
            mock_update_hp.assert_called_once_with("player_1", 1)

            # Player should no longer be fallen
            player = ctx.userdata.combat_state.participants[0]
            assert player.is_fallen is False
            assert player.hp_current == 1

    @pytest.mark.asyncio
    @patch("tools.db_mutations.update_player_hp", new_callable=AsyncMock)
    @patch("tools.db_mutations.save_combat_state", new_callable=AsyncMock)
    async def test_nat_1_double_fail(self, mock_save, mock_update_hp):
        with patch("combat_resolution.dice_roll") as mock_dice:
            from dice import DiceResult

            mock_dice.return_value = DiceResult(notation="d20", rolls=[1], dropped=[], total=1)

            ctx = _make_context()
            ctx.userdata.combat_state = _make_combat_state(player_hp=0, player_fallen=True)

            result = json.loads(await request_death_save._func(ctx))

            assert result["critical_failure"] is True
            assert result["total_failures"] == 2

    @pytest.mark.asyncio
    @patch("tools.db_mutations.update_player_hp", new_callable=AsyncMock)
    @patch("tools.db_mutations.save_combat_state", new_callable=AsyncMock)
    async def test_stabilize(self, mock_save, mock_update_hp):
        with patch("combat_resolution.dice_roll") as mock_dice:
            from dice import DiceResult

            mock_dice.return_value = DiceResult(notation="d20", rolls=[15], dropped=[], total=15)

            ctx = _make_context()
            cs = _make_combat_state(player_hp=0, player_fallen=True)
            # Set 2 existing successes
            cs.participants[0].death_save_successes = 2
            ctx.userdata.combat_state = cs

            result = json.loads(await request_death_save._func(ctx))

            assert result["stabilized"] is True
            assert result["total_successes"] == 3

    @pytest.mark.asyncio
    @patch("tools.db_mutations.update_player_hp", new_callable=AsyncMock)
    @patch("tools.db_mutations.save_combat_state", new_callable=AsyncMock)
    async def test_death(self, mock_save, mock_update_hp):
        with patch("combat_resolution.dice_roll") as mock_dice:
            from dice import DiceResult

            mock_dice.return_value = DiceResult(notation="d20", rolls=[5], dropped=[], total=5)

            ctx = _make_context()
            cs = _make_combat_state(player_hp=0, player_fallen=True)
            cs.participants[0].death_save_failures = 2
            ctx.userdata.combat_state = cs

            result = json.loads(await request_death_save._func(ctx))

            assert result["dead"] is True
            assert result["total_failures"] == 3

    @pytest.mark.asyncio
    async def test_error_if_not_fallen(self):
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state(player_hp=25, player_fallen=False)

        result = json.loads(await request_death_save._func(ctx))

        assert "error" in result
        assert "not fallen" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_error_if_not_in_combat(self):
        ctx = _make_context()

        result = json.loads(await request_death_save._func(ctx))

        assert "error" in result

    @pytest.mark.asyncio
    @patch("tools.db_mutations.update_player_hp", new_callable=AsyncMock)
    @patch("tools.db_mutations.save_combat_state", new_callable=AsyncMock)
    async def test_publishes_events(self, mock_save, mock_update_hp):
        room = _make_mock_room()
        ctx = _make_context(room=room)
        ctx.userdata.combat_state = _make_combat_state(player_hp=0, player_fallen=True)

        await request_death_save._func(ctx)

        # dice_roll event + at least one play_sound
        assert room.local_participant.publish_data.call_count >= 2
        calls = [json.loads(c[0][0]) for c in room.local_participant.publish_data.call_args_list]
        types = [c["type"] for c in calls]
        assert E.DICE_ROLL in types
        death_save_event = next(c for c in calls if c.get("type") == E.DICE_ROLL)
        assert death_save_event["roll_type"] == "death_save"


# --- end_combat ---


class TestEndCombat:
    @pytest.mark.asyncio
    @patch("tools.db_mutations.delete_combat_state", new_callable=AsyncMock)
    async def test_clears_state(self, mock_delete):
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()

        raw = await end_combat._func(ctx, outcome="victory")
        assert isinstance(raw, tuple), "end_combat success should return (DungeonMasterAgent, json_str)"
        _, json_str = raw
        result = json.loads(json_str)

        assert result["outcome"] == "victory"
        assert ctx.userdata.in_combat is False
        assert ctx.userdata.combat_state is None
        mock_delete.assert_called_once()

    @pytest.mark.asyncio
    @patch("tools.db_mutations.delete_combat_state", new_callable=AsyncMock)
    async def test_returns_city_agent(self, mock_delete):
        from city_agent import CityAgent

        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()

        raw = await end_combat._func(ctx, outcome="victory")
        agent_instance, _ = raw
        assert isinstance(agent_instance, CityAgent)

    @pytest.mark.asyncio
    @patch("tools.db_mutations.delete_combat_state", new_callable=AsyncMock)
    async def test_returned_agent_has_combat_summary_context(self, mock_delete):
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()

        raw = await end_combat._func(ctx, outcome="victory")
        agent_instance, _ = raw
        # The returned agent should have a chat_ctx with a combat summary
        items = list(agent_instance.chat_ctx.items)
        assert len(items) > 0

    @pytest.mark.asyncio
    @patch("tools.db_mutations.delete_combat_state", new_callable=AsyncMock)
    async def test_calculates_xp_on_victory(self, mock_delete):
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()

        _, json_str = await end_combat._func(ctx, outcome="victory")
        result = json.loads(json_str)

        assert result["xp_total"] == 50
        assert "Goblin Scout" in result["defeated_enemies"]

    @pytest.mark.asyncio
    @patch("tools.db_mutations.delete_combat_state", new_callable=AsyncMock)
    async def test_no_xp_on_defeat(self, mock_delete):
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()

        _, json_str = await end_combat._func(ctx, outcome="defeat")
        result = json.loads(json_str)

        assert result["xp_total"] == 0
        assert result["defeated_enemies"] == []

    @pytest.mark.asyncio
    @patch("tools.db_mutations.delete_combat_state", new_callable=AsyncMock)
    async def test_no_xp_on_fled(self, mock_delete):
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()

        _, json_str = await end_combat._func(ctx, outcome="fled")
        result = json.loads(json_str)

        assert result["xp_total"] == 0

    @pytest.mark.asyncio
    @patch("tools.db_mutations.delete_combat_state", new_callable=AsyncMock)
    async def test_publishes_events(self, mock_delete):
        room = _make_mock_room()
        ctx = _make_context(room=room)
        ctx.userdata.combat_state = _make_combat_state()

        await end_combat._func(ctx, outcome="victory")

        calls = [json.loads(c[0][0]) for c in room.local_participant.publish_data.call_args_list]
        types = [c["type"] for c in calls]
        assert E.COMBAT_ENDED in types
        assert E.PLAY_SOUND in types

    @pytest.mark.asyncio
    async def test_error_if_not_in_combat(self):
        ctx = _make_context()

        result = json.loads(await end_combat._func(ctx, outcome="victory"))

        assert "error" in result

    @pytest.mark.asyncio
    @patch("tools.db_mutations.delete_combat_state", new_callable=AsyncMock)
    async def test_error_invalid_outcome(self, mock_delete):
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()

        result = json.loads(await end_combat._func(ctx, outcome="surrender"))

        assert "error" in result
