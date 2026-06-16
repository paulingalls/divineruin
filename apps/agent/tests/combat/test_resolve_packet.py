"""Tests for _resolve_attack_packet: per-attack resolution against CombatParticipant HP.

This is the shared resolver the phase-loop packet path (story-003) drives via
``_resolve_one_packet``. It mutates the target participant in place, publishes its
HUD events/sounds in order, and returns a response dict — it does NOT persist (the
caller owns one save per phase).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _make_combat_state, _make_context, _make_mock_room

from check_resolution import AttackResult
from combat_turn import _resolve_attack_packet


def _fixed_resolver(*, damage: int, hp_remaining: int):
    """A resolver whose resolve_attack returns a fixed hit — pins the damage the
    concentration break-check sees and whether the hit drops the target to 0."""
    result = AttackResult(
        hit=True,
        roll=15,
        attack_modifier=3,
        attack_total=18,
        target_ac=14,
        damage=damage,
        damage_type="slashing",
        critical_success=False,
        critical_failure=False,
        target_hp_remaining=hp_remaining,
        target_killed=hp_remaining <= 0,
        narrative_hint="The blade bites deep.",
    )
    resolver = MagicMock()
    resolver.resolve_attack = MagicMock(return_value=result)
    return resolver


def _break_mod(return_value):
    """Mock the concentration_break module — its return is what the packet reports."""
    mod = MagicMock()
    mod.break_concentration_on_damage = AsyncMock(return_value=return_value)
    return mod


def _make_mocks():
    mock_mutations = MagicMock()
    mock_mutations.save_combat_state = AsyncMock()
    mock_mutations.update_player_hp = AsyncMock()
    return mock_mutations


def _make_queries():
    """No equipped items, so a player hit accrues no durability (the accrual path
    is covered in test_combat_durability)."""
    mock_queries = MagicMock()
    mock_queries.get_player_inventory = AsyncMock(return_value=[])
    return mock_queries


def _attacker_target_action(cs):
    enemy = cs.get_participant("goblin_scout_1")
    player = cs.get_participant("player_1")
    assert enemy is not None and player is not None
    return enemy, player, enemy.action_pool[0]


class TestResolveAttackPacket:
    @pytest.mark.asyncio
    async def test_resolves_attack(self):
        ctx = _make_context()
        cs = _make_combat_state()
        attacker, target, action = _attacker_target_action(cs)

        response = await _resolve_attack_packet(
            ctx.userdata,
            attacker,
            action,
            target,
            mutations=_make_mocks(),
            queries=_make_queries(),
        )

        assert "hit" in response
        assert "damage" in response
        assert "narrative_hint" in response
        assert response["attacker"] == "Goblin Scout"
        assert response["target"] == "Kael"

    @pytest.mark.asyncio
    async def test_does_not_persist(self):
        # The packet helper never persists — the caller saves once per phase.
        mock_mutations = _make_mocks()
        ctx = _make_context()
        cs = _make_combat_state()
        attacker, target, action = _attacker_target_action(cs)

        await _resolve_attack_packet(
            ctx.userdata,
            attacker,
            action,
            target,
            mutations=mock_mutations,
            queries=_make_queries(),
        )

        mock_mutations.save_combat_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_mutates_target_hp_on_state(self):
        mock_mutations = _make_mocks()
        ctx = _make_context()
        cs = _make_combat_state(player_hp=25)
        attacker, target, action = _attacker_target_action(cs)

        await _resolve_attack_packet(
            ctx.userdata,
            attacker,
            action,
            target,
            mutations=mock_mutations,
            queries=_make_queries(),
            resolver=_fixed_resolver(damage=10, hp_remaining=15),
        )

        assert target.hp_current == 15
        # target is the live participant reference held by cs, so the state mutated.
        in_state = cs.get_participant("player_1")
        assert in_state is not None and in_state.hp_current == 15

    @pytest.mark.asyncio
    async def test_updates_player_hp(self):
        mock_mutations = _make_mocks()
        ctx = _make_context()
        cs = _make_combat_state()
        attacker, target, action = _attacker_target_action(cs)

        await _resolve_attack_packet(
            ctx.userdata,
            attacker,
            action,
            target,
            mutations=mock_mutations,
            queries=_make_queries(),
        )

        mock_mutations.update_player_hp.assert_called_once()

    @pytest.mark.asyncio
    async def test_publishes_dice_roll_and_sound(self):
        room = _make_mock_room()
        ctx = _make_context(room=room)
        cs = _make_combat_state()
        attacker, target, action = _attacker_target_action(cs)

        await _resolve_attack_packet(
            ctx.userdata,
            attacker,
            action,
            target,
            mutations=_make_mocks(),
            queries=_make_queries(),
        )

        # At minimum: dice_roll event + at least one play_sound
        assert room.local_participant.publish_data.call_count >= 2

    @pytest.mark.asyncio
    async def test_sets_fallen_at_zero_hp(self):
        ctx = _make_context()
        cs = _make_combat_state(player_hp=8)
        attacker, target, action = _attacker_target_action(cs)

        response = await _resolve_attack_packet(
            ctx.userdata,
            attacker,
            action,
            target,
            mutations=_make_mocks(),
            queries=_make_queries(),
            resolver=_fixed_resolver(damage=30, hp_remaining=0),
        )

        assert response["target_fallen"] is True
        assert target.is_fallen is True

    @pytest.mark.asyncio
    async def test_player_hit_invokes_break_and_reports_it(self):
        ctx = _make_context()
        cs = _make_combat_state(player_hp=25)
        attacker, target, action = _attacker_target_action(cs)
        break_mod = _break_mod("arcane_fly")

        response = await _resolve_attack_packet(
            ctx.userdata,
            attacker,
            action,
            target,
            mutations=_make_mocks(),
            queries=_make_queries(),
            resolver=_fixed_resolver(damage=10, hp_remaining=15),
            concentration_break_mod=break_mod,
        )

        assert response["concentration_broken"] == "arcane_fly"
        break_mod.break_concentration_on_damage.assert_awaited_once()
        args, kwargs = break_mod.break_concentration_on_damage.call_args
        assert args[0] is ctx.userdata  # the session
        assert args[1] == 10  # the damage dealt
        assert kwargs["incapacitated"] is False  # 15 HP remaining

    @pytest.mark.asyncio
    async def test_incapacitating_hit_passes_incapacitated(self):
        ctx = _make_context()
        cs = _make_combat_state(player_hp=8)
        attacker, target, action = _attacker_target_action(cs)
        break_mod = _break_mod("arcane_fly")

        await _resolve_attack_packet(
            ctx.userdata,
            attacker,
            action,
            target,
            mutations=_make_mocks(),
            queries=_make_queries(),
            resolver=_fixed_resolver(damage=30, hp_remaining=0),
            concentration_break_mod=break_mod,
        )

        _args, kwargs = break_mod.break_concentration_on_damage.call_args
        assert kwargs["incapacitated"] is True

    @pytest.mark.asyncio
    async def test_no_break_reports_none(self):
        ctx = _make_context()
        cs = _make_combat_state(player_hp=25)
        attacker, target, action = _attacker_target_action(cs)

        response = await _resolve_attack_packet(
            ctx.userdata,
            attacker,
            action,
            target,
            mutations=_make_mocks(),
            queries=_make_queries(),
            resolver=_fixed_resolver(damage=10, hp_remaining=15),
            concentration_break_mod=_break_mod(None),
        )

        assert response["concentration_broken"] is None
