"""Tests for _resolve_attack_packet: per-attack resolution against CombatParticipant HP.

This is the shared resolver the phase-loop packet path (story-003) drives via
``_resolve_one_packet``. It mutates the target participant in place, publishes its
HUD events/sounds in order, and returns a response dict — it does NOT persist (the
caller owns one save per phase).
"""

import json
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _make_combat_state
from sample_fixtures import make_context, make_mock_room

import event_types as E
from check_resolution_attack import AttackResult
from combat_events import EventSink
from combat_support import (
    _resolve_attack_packet,
    apply_attack_result,
    deserialize_roll,
    roll_attack,
    serialize_roll,
)


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


class TestRollThenApply:
    """The hold's seam (M29, story-016): the post-roll reaction window is PRE-DAMAGE, so the
    roll must survive a tool-call boundary with no HP written and no event published.

    This is also the seam story-018 needs, with one trap named here rather than rediscovered:
    ``apply_attack_result`` writes ``target.hp_current = attack_result.target_hp_remaining`` and
    never reads ``damage``. So halving ``damage`` between the halves changes NOTHING — an Uncanny
    Dodge must re-derive ``target_hp_remaining`` (and ``overkill``) from the pre-hit HP too, or the
    reaction reports half damage while the full blow still lands.
    """

    def test_roll_writes_no_hp_and_publishes_nothing(self):
        """The HOLD itself. A rolled-but-unapplied attack leaves the target untouched: that is
        what makes the pause between the roll and the impact a legal resting state."""
        cs = _make_combat_state(player_hp=25)
        attacker, target, action = _attacker_target_action(cs)
        sink = EventSink()

        attack_result, effective_ac = roll_attack(
            attacker,
            action,
            target,
            resolver=_fixed_resolver(damage=3, hp_remaining=22),
        )

        assert attack_result.damage == 3
        assert target.hp_current == 25  # untouched — the blow is held
        assert target.is_fallen is False
        assert effective_ac == target.ac
        assert sink.captured == []  # no DICE_ROLL, no sound, nothing published

    @pytest.mark.asyncio
    async def test_roll_then_apply_is_identical_to_the_unsplit_packet(self):
        """_resolve_attack_packet is now the composition of the two halves, so a caller that
        never pauses resolves exactly as on trunk (AC6). Same seeded resolver both times."""
        ctx_a, ctx_b = make_context(), make_context()
        cs_a, cs_b = _make_combat_state(player_hp=25), _make_combat_state(player_hp=25)
        att_a, tgt_a, action_a = _attacker_target_action(cs_a)
        att_b, tgt_b, action_b = _attacker_target_action(cs_b)

        unsplit = await _resolve_attack_packet(
            ctx_a.userdata,
            att_a,
            action_a,
            tgt_a,
            mutations=_make_mocks(),
            queries=_make_queries(),
            resolver=_fixed_resolver(damage=3, hp_remaining=22),
            concentration_break_mod=_break_mod(None),
        )

        result, effective_ac = roll_attack(att_b, action_b, tgt_b, resolver=_fixed_resolver(damage=3, hp_remaining=22))
        split = await apply_attack_result(
            ctx_b.userdata,
            att_b,
            action_b,
            tgt_b,
            result,
            effective_ac,
            mutations=_make_mocks(),
            queries=_make_queries(),
            concentration_break_mod=_break_mod(None),
        )

        assert split == unsplit
        assert tgt_b.hp_current == tgt_a.hp_current == 22

    def test_a_held_roll_round_trips_through_json(self):
        """The rolled AttackResult rides inside its held action across a tool-call boundary, so
        it goes through JSONB. consumed_conditions is the one field JSON loses — it is a tuple
        and comes back a list unless the deserializer re-tuples it, and a list would make the
        M4.8 single-use die look unconsumed."""
        cs = _make_combat_state(player_hp=25)
        attacker, target, action = _attacker_target_action(cs)
        resolver = _fixed_resolver(damage=3, hp_remaining=22)
        rolled = replace(resolver.resolve_attack.return_value, consumed_conditions=("blessed",))
        resolver.resolve_attack = MagicMock(return_value=rolled)
        result, effective_ac = roll_attack(attacker, action, target, resolver=resolver)

        restored, restored_ac = deserialize_roll(json.loads(json.dumps(serialize_roll(result, effective_ac))))

        assert restored == result
        assert restored_ac == effective_ac
        assert restored.consumed_conditions == ("blessed",)
        assert isinstance(restored.consumed_conditions, tuple)
