"""Tests for request_death_save: success/stabilize/death, nat-20 revive, nat-1, errors, events."""

import json
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from combat._helpers import _make_combat_state
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod, make_mock_room, published_payloads

import event_types as E
from combat_death_save import _request_death_save_impl


def _make_death_save_mocks():
    """Create mock modules for request_death_save DI params."""
    mock_mutations = MagicMock()
    mock_mutations.save_combat_state = AsyncMock()
    mock_mutations.update_player_hp = AsyncMock()
    return mock_mutations


def _fallen_ally(cs, player_id: str):
    """Add a SECOND fallen player participant — the multiplayer shape combat_init builds."""
    ally = replace(cs.participants[0], id=player_id, name="Ally", hp_current=0, is_fallen=True)
    cs.participants.append(ally)
    return ally


def _participant(ctx, player_id: str):
    """The live participant, asserted present — get_participant is Optional-typed."""
    p = ctx.userdata.combat_state.get_participant(player_id)
    assert p is not None, f"{player_id} missing from combat state"
    return p


class TestMultiPlayerDeathSave:
    """M14+ built a type="player" CombatParticipant per party member, but the death save still
    looked up session.player_id. A fallen non-primary could never roll their own save."""

    @pytest.mark.asyncio
    async def test_non_primary_rolls_its_own_save_while_the_primary_stands(self):
        """The primary is upright; the ally is down. The save belongs to the ally.

        Before: cs.get_participant(session.player_id) found the standing primary and raised
        "Player has not fallen" -- the surfaced death save could never be resolved."""
        mock_mutations = _make_death_save_mocks()
        mock_db, _conn = make_db_mod()
        ctx = make_context("player_1", party_member_ids=["player_2"])
        cs = _make_combat_state()  # primary standing
        _fallen_ally(cs, "player_2")
        ctx.userdata.combat_state = cs

        # A pinned ordinary failure (not a nat-1, which costs TWO failures, nor a nat-20, which
        # revives): one counter moves, so "whose counter" is the only thing this asserts.
        with patch("combat_resolution.dice_roll", return_value=MagicMock(total=5, natural=5)):
            result = json.loads(await _request_death_save_impl(ctx, mutations=mock_mutations, db_mod=mock_db))

        assert "roll" in result
        # The ALLY's counters moved; the standing primary's did not.
        ally = _participant(ctx, "player_2")
        primary = _participant(ctx, "player_1")
        assert (ally.death_save_successes, ally.death_save_failures) == (0, 1)
        assert (primary.death_save_successes, primary.death_save_failures) == (0, 0)

    @pytest.mark.asyncio
    async def test_two_fallen_members_require_naming_who_rolls(self):
        """Both down: rolling "the player" silently double-rolled the primary. Make the DM name one."""
        mock_mutations = _make_death_save_mocks()
        mock_db, _conn = make_db_mod()
        ctx = make_context("player_1", party_member_ids=["player_2"])
        cs = _make_combat_state(player_hp=0, player_fallen=True)
        _fallen_ally(cs, "player_2")
        ctx.userdata.combat_state = cs

        with pytest.raises(ToolError, match="player_2"):
            await _request_death_save_impl(ctx, mutations=mock_mutations, db_mod=mock_db)
        mock_mutations.save_combat_state.assert_not_awaited()  # ambiguity writes nothing

    @pytest.mark.asyncio
    async def test_named_member_rolls_and_its_nat20_revives_that_member(self):
        """A nat-20 restores the NAMED member's HP row, never the primary's."""
        mock_mutations = _make_death_save_mocks()
        mock_db, conn = make_db_mod()
        ctx = make_context("player_1", party_member_ids=["player_2"])
        cs = _make_combat_state(player_hp=0, player_fallen=True)
        _fallen_ally(cs, "player_2")
        ctx.userdata.combat_state = cs

        with patch("combat_resolution.dice_roll", return_value=MagicMock(total=20, natural=20)):
            await _request_death_save_impl(ctx, "player_2", mutations=mock_mutations, db_mod=mock_db)

        mock_mutations.update_player_hp.assert_awaited_once_with("player_2", 1, conn=conn)
        assert _participant(ctx, "player_2").is_fallen is False
        assert _participant(ctx, "player_1").is_fallen is True  # untouched

    @pytest.mark.asyncio
    async def test_a_fallen_enemy_can_never_be_named(self):
        """Enemies have no death-save loop; naming one is a DM error, not a silent roll."""
        mock_mutations = _make_death_save_mocks()
        mock_db, _conn = make_db_mod()
        ctx = make_context()
        cs = _make_combat_state(enemy_hp=0, enemy_fallen=True)
        ctx.userdata.combat_state = cs

        with pytest.raises(ToolError):
            await _request_death_save_impl(ctx, "goblin_scout_1", mutations=mock_mutations, db_mod=mock_db)


class TestDeathSaveAtomicity:
    @pytest.mark.asyncio
    async def test_a_failed_persist_leaves_no_advanced_counters_in_memory(self):
        """The live CombatState must not run ahead of the DB. Previously the participant was mutated
        in place BEFORE save_combat_state, so a failed write stranded an advanced counter in memory
        that the next reload silently lost."""
        mock_mutations = _make_death_save_mocks()
        mock_mutations.save_combat_state = AsyncMock(side_effect=RuntimeError("db down"))
        mock_db, _conn = make_db_mod()
        ctx = make_context()
        ctx.userdata.combat_state = _make_combat_state(player_hp=0, player_fallen=True)

        with pytest.raises(RuntimeError):
            await _request_death_save_impl(ctx, mutations=mock_mutations, db_mod=mock_db)

        p = _participant(ctx, "player_1")
        assert p.death_save_successes == 0 and p.death_save_failures == 0  # pristine
        assert p.is_fallen is True

    @pytest.mark.asyncio
    async def test_the_hp_and_state_writes_share_one_transaction(self):
        """A nat-20 writes players.data HP and the combat_instances SSOT. Split across two
        transactions, a crash between them leaves a live 1-HP player the combat row calls fallen."""
        mock_mutations = _make_death_save_mocks()
        mock_db, conn = make_db_mod()
        ctx = make_context()
        ctx.userdata.combat_state = _make_combat_state(player_hp=0, player_fallen=True)

        with patch("combat_resolution.dice_roll", return_value=MagicMock(total=20, natural=20)):
            await _request_death_save_impl(ctx, mutations=mock_mutations, db_mod=mock_db)

        assert mock_mutations.update_player_hp.await_args.kwargs["conn"] is conn
        assert mock_mutations.save_combat_state.await_args.kwargs["conn"] is conn


class TestRequestDeathSave:
    @pytest.mark.asyncio
    async def test_success(self):
        mock_mutations = _make_death_save_mocks()
        mock_db, _conn = make_db_mod()
        ctx = make_context()
        ctx.userdata.combat_state = _make_combat_state(player_hp=0, player_fallen=True)

        result = json.loads(await _request_death_save_impl(ctx, mutations=mock_mutations, db_mod=mock_db))

        assert "roll" in result
        assert "success" in result
        assert "total_successes" in result
        assert "total_failures" in result
        mock_mutations.save_combat_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_nat_20_restores_hp(self):
        """If we get a nat 20, player should be revived with 1 HP."""
        mock_mutations = _make_death_save_mocks()
        mock_db, _conn = make_db_mod()

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

            ctx = make_context()
            ctx.userdata.combat_state = _make_combat_state(player_hp=0, player_fallen=True)

            result = json.loads(await _request_death_save_impl(ctx, mutations=mock_mutations, db_mod=mock_db))

            assert result["critical_success"] is True
            assert result["revived"] is True
            # The HP write now rides the same transaction as the combat-state save.
            mock_mutations.update_player_hp.assert_called_once_with("player_1", 1, conn=_conn)

            # Player should no longer be fallen
            player = ctx.userdata.combat_state.participants[0]
            assert player.is_fallen is False
            assert player.hp_current == 1

    @pytest.mark.asyncio
    async def test_nat_1_double_fail(self):
        mock_mutations = _make_death_save_mocks()
        mock_db, _conn = make_db_mod()

        with patch("combat_resolution.dice_roll") as mock_dice:
            from dice import DiceResult

            mock_dice.return_value = DiceResult(notation="d20", rolls=[1], dropped=[], total=1)

            ctx = make_context()
            ctx.userdata.combat_state = _make_combat_state(player_hp=0, player_fallen=True)

            result = json.loads(await _request_death_save_impl(ctx, mutations=mock_mutations, db_mod=mock_db))

            assert result["critical_failure"] is True
            assert result["total_failures"] == 2

    @pytest.mark.asyncio
    async def test_stabilize(self):
        mock_mutations = _make_death_save_mocks()
        mock_db, _conn = make_db_mod()

        with patch("combat_resolution.dice_roll") as mock_dice:
            from dice import DiceResult

            mock_dice.return_value = DiceResult(notation="d20", rolls=[15], dropped=[], total=15)

            ctx = make_context()
            cs = _make_combat_state(player_hp=0, player_fallen=True)
            # Set 2 existing successes
            cs.participants[0].death_save_successes = 2
            ctx.userdata.combat_state = cs

            result = json.loads(await _request_death_save_impl(ctx, mutations=mock_mutations, db_mod=mock_db))

            assert result["stabilized"] is True
            assert result["total_successes"] == 3

    @pytest.mark.asyncio
    async def test_death(self):
        mock_mutations = _make_death_save_mocks()
        mock_db, _conn = make_db_mod()

        with patch("combat_resolution.dice_roll") as mock_dice:
            from dice import DiceResult

            mock_dice.return_value = DiceResult(notation="d20", rolls=[5], dropped=[], total=5)

            ctx = make_context()
            cs = _make_combat_state(player_hp=0, player_fallen=True)
            cs.participants[0].death_save_failures = 2
            ctx.userdata.combat_state = cs

            result = json.loads(await _request_death_save_impl(ctx, mutations=mock_mutations, db_mod=mock_db))

            assert result["dead"] is True
            assert result["total_failures"] == 3

    @pytest.mark.asyncio
    async def test_error_if_not_fallen(self):
        """Nobody is down, so there is no save to roll. Refused before any write, so this needs no
        db mock -- the guard runs ahead of the transaction."""
        ctx = make_context()
        ctx.userdata.combat_state = _make_combat_state(player_hp=25, player_fallen=False)

        with pytest.raises(ToolError, match="No one has fallen"):
            await _request_death_save_impl(ctx)

    @pytest.mark.asyncio
    async def test_error_if_not_in_combat(self):
        ctx = make_context()

        with pytest.raises(ToolError, match="Not in combat"):
            await _request_death_save_impl(ctx)

    @pytest.mark.asyncio
    async def test_publishes_events(self):
        mock_mutations = _make_death_save_mocks()
        mock_db, _conn = make_db_mod()
        room = make_mock_room()
        ctx = make_context(room=room)
        ctx.userdata.combat_state = _make_combat_state(player_hp=0, player_fallen=True)

        await _request_death_save_impl(ctx, mutations=mock_mutations, db_mod=mock_db)

        # dice_roll event + at least one play_sound
        assert room.local_participant.publish_data.call_count >= 2
        calls = published_payloads(room)
        types = [c["type"] for c in calls]
        assert E.DICE_ROLL in types
        death_save_event = next(c for c in calls if c.get("type") == E.DICE_ROLL)
        assert death_save_event["roll_type"] == "death_save"

    @pytest.mark.asyncio
    async def test_dice_roll_and_response_are_always_dramatic(self):
        # story-004: a death save is ALWAYS dramatic — the DICE_ROLL payload and the tool
        # response both carry dramatic=True + context="death_save" (the M4.5 contract label),
        # so the client overlay and the DM both pause for it.
        mock_mutations = _make_death_save_mocks()
        mock_db, _conn = make_db_mod()
        room = make_mock_room()
        ctx = make_context(room=room)
        ctx.userdata.combat_state = _make_combat_state(player_hp=0, player_fallen=True)

        response = json.loads(await _request_death_save_impl(ctx, mutations=mock_mutations, db_mod=mock_db))

        assert response["dramatic"] is True
        assert response["context"] == "death_save"
        calls = published_payloads(room)
        dice = next(c for c in calls if c.get("type") == E.DICE_ROLL)
        assert dice["dramatic"] is True
        assert dice["context"] == "death_save"
