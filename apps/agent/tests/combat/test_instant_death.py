"""Instant-death threshold (M4.4 story-002).

Spec (game_mechanics_combat.md §The Fallen State): if a single hit drops HP to 0 AND the excess
damage (overkill) equals or exceeds the target's max HP, the character dies instantly — no Fallen
state, no death saves. The overkill is computed in resolve_attack (pre-floor) and the verdict is
applied at the damage site (combat_support._resolve_attack_packet); the pure engine (combat_phase
._wrap) then ends combat without a death-save beat. is_dead is distinct from is_fallen
(fallen = dying/making saves; dead = gone)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _make_combat_state
from sample_fixtures import make_context

import combat_phase
from check_resolution_attack import AttackResult
from combat_support import _resolve_attack_packet


def _resolver(*, damage: int, hp_remaining: int, overkill: int):
    result = AttackResult(
        hit=True,
        roll=15,
        attack_modifier=3,
        attack_total=18,
        target_ac=14,
        damage=damage,
        damage_type="slashing",
        target_hp_remaining=hp_remaining,
        target_killed=hp_remaining <= 0,
        overkill=overkill,
        narrative_hint="A devastating blow.",
    )
    resolver = MagicMock()
    resolver.resolve_attack = MagicMock(return_value=result)
    return resolver


def _mocks():
    mutations = MagicMock()
    mutations.save_combat_state = AsyncMock()
    mutations.update_player_hp = AsyncMock()
    queries = MagicMock()
    queries.get_player_inventory = AsyncMock(return_value=[])
    return mutations, queries


def _attacker_target_action(cs):
    enemy = cs.get_participant("goblin_scout_1")
    player = cs.get_participant("player_1")
    assert enemy is not None and player is not None
    return enemy, player, enemy.action_pool[0]


class TestInstantDeathVerdict:
    @pytest.mark.asyncio
    async def test_overkill_at_or_above_max_hp_flags_instant_dead(self):
        ctx = make_context()
        cs = _make_combat_state()
        attacker, target, action = _attacker_target_action(cs)
        mutations, queries = _mocks()

        await _resolve_attack_packet(
            ctx.userdata,
            attacker,
            action,
            target,
            mutations=mutations,
            queries=queries,
            resolver=_resolver(damage=target.hp_max * 3, hp_remaining=0, overkill=target.hp_max),
        )

        assert target.is_dead is True
        assert target.is_fallen is True  # also fallen; is_dead is the stronger state

    @pytest.mark.asyncio
    async def test_lethal_without_excess_overkill_is_fallen_not_dead(self):
        ctx = make_context()
        cs = _make_combat_state()
        attacker, target, action = _attacker_target_action(cs)
        mutations, queries = _mocks()

        # Drops to 0 but overkill below max HP -> normal Fallen (death saves), not instant death.
        await _resolve_attack_packet(
            ctx.userdata,
            attacker,
            action,
            target,
            mutations=mutations,
            queries=queries,
            resolver=_resolver(damage=target.hp_current, hp_remaining=0, overkill=target.hp_max - 1),
        )

        assert target.is_fallen is True
        assert target.is_dead is False

    @pytest.mark.asyncio
    async def test_non_lethal_hit_is_neither_fallen_nor_dead(self):
        ctx = make_context()
        cs = _make_combat_state()
        attacker, target, action = _attacker_target_action(cs)
        mutations, queries = _mocks()

        await _resolve_attack_packet(
            ctx.userdata,
            attacker,
            action,
            target,
            mutations=mutations,
            queries=queries,
            resolver=_resolver(damage=1, hp_remaining=target.hp_current - 1, overkill=0),
        )

        assert target.is_fallen is False
        assert target.is_dead is False


class TestWrapInstantDeath:
    """The pure Beat-4 wrap ends combat on an instant-dead player without a death-save beat."""

    def test_instant_dead_player_ends_combat_as_defeat(self):
        cs = _make_combat_state()
        player = cs.get_participant("player_1")
        assert player is not None
        player.is_fallen = True
        player.is_dead = True
        player.death_save_failures = 0  # never made a save — instant death bypasses the grind

        wrap = combat_phase._wrap(cs)
        assert wrap.combat_ended is True
        assert wrap.outcome == "defeat"

    def test_instant_dead_participant_not_in_death_saves_due(self):
        cs = _make_combat_state()
        player = cs.get_participant("player_1")
        assert player is not None
        player.is_fallen = True
        player.is_dead = True

        wrap = combat_phase._wrap(cs)
        assert "player_1" not in wrap.death_saves_due

    def test_fallen_but_not_dead_player_still_rolls_death_saves(self):
        # Control: a normally-fallen player (overkill below max HP) still enters the death-save grind.
        cs = _make_combat_state()
        player = cs.get_participant("player_1")
        assert player is not None
        player.is_fallen = True
        player.is_dead = False
        player.death_save_failures = 1

        wrap = combat_phase._wrap(cs)
        assert "player_1" in wrap.death_saves_due
        assert wrap.combat_ended is False
