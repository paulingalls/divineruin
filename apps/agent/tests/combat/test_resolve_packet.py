"""Tests for _resolve_attack_packet: per-attack resolution against CombatParticipant HP.

This is the shared resolver the phase-loop packet path (story-003) drives via
``_resolve_one_packet``. It mutates the target participant in place, publishes its
HUD events/sounds in order, and returns a response dict — it does NOT persist (the
caller owns one save per phase).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _make_combat_state
from sample_fixtures import make_context, make_mock_room

import event_types as E
from check_resolution_attack import AttackResult
from combat_events import EventSink
from combat_support import _resolve_attack_packet
from session_data import CombatParticipant


def _fixed_resolver(*, damage: int, hp_remaining: int, dramatic: bool = False, context: str = ""):
    """A resolver whose resolve_attack returns a fixed hit — pins the damage the
    concentration break-check sees and whether the hit drops the target to 0. The
    intrinsic dramatic verdict (story-002) is injectable so emission tests can drive
    both the dramatic and non-dramatic paths."""
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
        dramatic=dramatic,
        context=context,
    )
    resolver = MagicMock()
    resolver.resolve_attack = MagicMock(return_value=result)
    return resolver


def _dice_payload(sink: EventSink) -> dict:
    """The DICE_ROLL event payload buffered by the sink for the attack (story-004)."""
    for ev in sink.captured:
        if ev.event_type == E.DICE_ROLL:
            return ev.payload
    raise AssertionError("no DICE_ROLL event was buffered")


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
        ctx = make_context()
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
        ctx = make_context()
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
        ctx = make_context()
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
        ctx = make_context()
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
        room = make_mock_room()
        ctx = make_context(room=room)
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
        ctx = make_context()
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
        ctx = make_context()
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
        ctx = make_context()
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
        ctx = make_context()
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


class TestDramaticEmission:
    """story-004: the attack DICE_ROLL event payload and the returned summary surface the
    dramatic verdict. The resolver's intrinsic verdict (nat-20/nat-1/killing-blow) is the
    floor; the emission site PROMOTES a non-dramatic attack on the encounter-context signals
    last_enemy + first_attack, never downgrading an intrinsic-dramatic one."""

    @pytest.mark.asyncio
    async def test_intrinsic_dramatic_reaches_payload_and_summary(self):
        sink = EventSink()
        ctx = make_context()
        cs = _make_combat_state(player_hp=25)
        attacker, target, action = _attacker_target_action(cs)

        response = await _resolve_attack_packet(
            ctx.userdata,
            attacker,
            action,
            target,
            mutations=_make_mocks(),
            queries=_make_queries(),
            resolver=_fixed_resolver(damage=5, hp_remaining=20, dramatic=True, context="natural_20"),
            sink=sink,
        )

        assert response["dramatic"] is True
        assert response["context"] == "natural_20"
        payload = _dice_payload(sink)
        assert payload["dramatic"] is True
        assert payload["context"] == "natural_20"

    @pytest.mark.asyncio
    async def test_routine_attack_is_not_dramatic(self):
        sink = EventSink()
        ctx = make_context()
        cs = _make_combat_state(player_hp=25)
        attacker, target, action = _attacker_target_action(cs)

        response = await _resolve_attack_packet(
            ctx.userdata,
            attacker,
            action,
            target,
            mutations=_make_mocks(),
            queries=_make_queries(),
            resolver=_fixed_resolver(damage=5, hp_remaining=20),
            enemies_remaining=3,
            sink=sink,
        )

        assert response["dramatic"] is False
        assert response["context"] == ""
        assert _dice_payload(sink)["dramatic"] is False

    @pytest.mark.asyncio
    async def test_last_enemy_promotes_a_routine_attack(self):
        sink = EventSink()
        ctx = make_context()
        cs = _make_combat_state(player_hp=25)
        attacker, target, action = _attacker_target_action(cs)

        response = await _resolve_attack_packet(
            ctx.userdata,
            attacker,
            action,
            target,
            mutations=_make_mocks(),
            queries=_make_queries(),
            resolver=_fixed_resolver(damage=5, hp_remaining=20),
            enemies_remaining=1,
            sink=sink,
        )

        assert response["dramatic"] is True
        assert response["context"] == "last_enemy"
        assert _dice_payload(sink)["context"] == "last_enemy"

    @pytest.mark.asyncio
    async def test_first_attack_promotes_a_routine_attack(self):
        sink = EventSink()
        ctx = make_context()
        cs = _make_combat_state(player_hp=25)
        attacker, target, action = _attacker_target_action(cs)

        response = await _resolve_attack_packet(
            ctx.userdata,
            attacker,
            action,
            target,
            mutations=_make_mocks(),
            queries=_make_queries(),
            resolver=_fixed_resolver(damage=5, hp_remaining=20),
            enemies_remaining=3,
            is_first_attack_of_combat=True,
            sink=sink,
        )

        assert response["dramatic"] is True
        assert response["context"] == "first_attack"

    @pytest.mark.asyncio
    async def test_intrinsic_verdict_wins_over_encounter_context(self):
        # A nat-20 that is ALSO the last enemy keeps the higher-severity intrinsic label —
        # the emission promotes only when the intrinsic verdict was not already dramatic.
        sink = EventSink()
        ctx = make_context()
        cs = _make_combat_state(player_hp=25)
        attacker, target, action = _attacker_target_action(cs)

        response = await _resolve_attack_packet(
            ctx.userdata,
            attacker,
            action,
            target,
            mutations=_make_mocks(),
            queries=_make_queries(),
            resolver=_fixed_resolver(damage=5, hp_remaining=20, dramatic=True, context="natural_20"),
            enemies_remaining=1,
            is_first_attack_of_combat=True,
            sink=sink,
        )

        assert response["context"] == "natural_20"


class TestResolveAbilityPacket:
    """story-007: an in-combat ABILITY declaration resolves through the shared cast logic.

    Player-gated (only the player has a Focus pool + resonance track); the CastResult is stashed on
    the AbilityCastOutcome so the phase loop can commit resonance/concentration/events post-commit."""

    def _player(self) -> CombatParticipant:
        return CombatParticipant(
            id="player_1", name="Lyra", type="player", initiative=15, hp_current=20, hp_max=20, ac=14
        )

    def _cast_resolver(self, result):
        mod = MagicMock()
        mod._resolve_cast = AsyncMock(return_value=result)
        return mod

    async def test_player_ability_resolves_and_stashes_castresult(self):
        from combat_ability import AbilityCastOutcome, _resolve_ability_packet
        from declarations import Declaration, DeclarationType
        from spell_casting import _UNCHANGED, CastResult

        session = make_context().userdata
        attacker = self._player()
        decl = Declaration(type=DeclarationType.ABILITY, action="arcane_bolt")
        result = CastResult(
            packet={"effect": "zap", "state": "stable"},
            new_resonance=6,
            concentration_spell_id=_UNCHANGED,
            generated=6,
            events=[],
        )
        cast_resolver = self._cast_resolver(result)
        outcome = AbilityCastOutcome()

        summary = await _resolve_ability_packet(
            session, attacker, decl, cast_resolver=cast_resolver, conn=object(), player=None, cast_outcome=outcome
        )

        assert summary["resolved"] is True
        assert summary["actor_id"] == "player_1"
        assert summary["declaration_type"] == "ability"
        assert summary["action"] == "arcane_bolt"
        assert summary["cast"] == {"effect": "zap", "state": "stable"}
        # the CastResult is handed to the loop, not applied here (in-memory sync is post-commit)
        assert outcome.cast_result is result
        # routed through the shared cast core with the cast's own RESONANCE_CHANGED suppressed —
        # in combat the phase WRAP push is the single authoritative HUD update.
        _args, kwargs = cast_resolver._resolve_cast.call_args
        assert kwargs["suppress_resonance_changed"] is True

    async def test_non_player_ability_is_wasted(self):
        from combat_ability import AbilityCastOutcome, _resolve_ability_packet
        from declarations import Declaration, DeclarationType

        session = make_context().userdata
        enemy = CombatParticipant(
            id="goblin_1", name="Goblin", type="enemy", initiative=10, hp_current=7, hp_max=7, ac=13
        )
        decl = Declaration(type=DeclarationType.ABILITY, action="goblin_hex")
        cast_resolver = MagicMock()
        cast_resolver._resolve_cast = AsyncMock()
        outcome = AbilityCastOutcome()

        summary = await _resolve_ability_packet(
            session, enemy, decl, cast_resolver=cast_resolver, conn=object(), player=None, cast_outcome=outcome
        )

        assert summary["resolved"] is False
        cast_resolver._resolve_cast.assert_not_called()
        assert outcome.cast_result is None

    async def test_missing_action_is_wasted(self):
        from combat_ability import AbilityCastOutcome, _resolve_ability_packet
        from declarations import Declaration, DeclarationType

        session = make_context().userdata
        attacker = self._player()
        decl = Declaration(type=DeclarationType.ABILITY, action=None)
        cast_resolver = MagicMock()
        cast_resolver._resolve_cast = AsyncMock()
        outcome = AbilityCastOutcome()

        summary = await _resolve_ability_packet(
            session, attacker, decl, cast_resolver=cast_resolver, conn=object(), player=None, cast_outcome=outcome
        )

        assert summary["resolved"] is False
        cast_resolver._resolve_cast.assert_not_called()
        assert outcome.cast_result is None
