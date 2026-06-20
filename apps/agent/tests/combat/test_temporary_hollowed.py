"""Temporary Hollowed combat ride-along (M4.4 story-008).

Spec (gm_combat §The Hollowed Death): a Stage-2+ Hollowed player who drops to 0 HP does NOT enter
Fallen — their corpse rises as a Temporary Hollowed combatant (HP=50% of max, hits add 1d6
necrotic, immune to Charmed/Frightened/Poisoned) that takes DM turns and blocks combat-end until
destroyed. On its destruction the character enters normal Mortaen death (story-007): Hollowed
cleared, hollow_killed recorded.

Unit coverage here (rise at the death site + _wrap end-condition gating); the real-PG end-to-end
lands in the persistence test class below (AC3).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _make_combat_state
from sample_fixtures import make_context

import combat_phase
import conditions
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
        narrative_hint="A killing blow.",
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


def _hollowed(stage: int) -> list[dict]:
    conds: list[dict] = []
    for _ in range(stage):
        conds = conditions.apply_condition(conds, "hollowed")
    return conds


class TestRiseAtDeathSite:
    @pytest.mark.asyncio
    async def test_stage_2_hollowed_player_rises_instead_of_falling(self):
        ctx = make_context()
        cs = _make_combat_state()
        enemy = cs.get_participant("goblin_scout_1")
        player = cs.get_participant("player_1")
        assert enemy is not None and player is not None
        player.conditions = _hollowed(2)
        mutations, queries = _mocks()

        await _resolve_attack_packet(
            ctx.userdata,
            enemy,
            enemy.action_pool[0],
            player,
            mutations=mutations,
            queries=queries,
            resolver=_resolver(damage=player.hp_current, hp_remaining=0, overkill=0),
        )

        assert player.type == "temporary_hollowed"
        assert player.hp_current == player.hp_max // 2
        assert player.is_fallen is False
        assert player.is_dead is False
        assert any(c["type"] == "temporary_hollowed" for c in player.conditions)
        # The Hollowed condition is untouched on the echo — trigger_character_death reads it later.
        assert conditions.hollowed_stage(player.conditions) == 2
        # The echo's HP is not the player's: no player-HP write on rise.
        mutations.update_player_hp.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stage_1_hollowed_player_falls_normally(self):
        ctx = make_context()
        cs = _make_combat_state()
        enemy = cs.get_participant("goblin_scout_1")
        player = cs.get_participant("player_1")
        assert enemy is not None and player is not None
        player.conditions = _hollowed(1)
        mutations, queries = _mocks()

        await _resolve_attack_packet(
            ctx.userdata,
            enemy,
            enemy.action_pool[0],
            player,
            mutations=mutations,
            queries=queries,
            resolver=_resolver(damage=player.hp_current, hp_remaining=0, overkill=0),
        )

        assert player.type == "player"
        assert player.is_fallen is True
        assert all(c["type"] != "temporary_hollowed" for c in player.conditions)

    @pytest.mark.asyncio
    async def test_non_hollowed_player_falls_normally(self):
        ctx = make_context()
        cs = _make_combat_state()
        enemy = cs.get_participant("goblin_scout_1")
        player = cs.get_participant("player_1")
        assert enemy is not None and player is not None
        mutations, queries = _mocks()

        await _resolve_attack_packet(
            ctx.userdata,
            enemy,
            enemy.action_pool[0],
            player,
            mutations=mutations,
            queries=queries,
            resolver=_resolver(damage=player.hp_current, hp_remaining=0, overkill=0),
        )

        assert player.type == "player"
        assert player.is_fallen is True

    @pytest.mark.asyncio
    async def test_destroyed_echo_falls(self):
        # An already-risen echo at 0 HP is destroyed (Fallen) — it does NOT re-rise.
        ctx = make_context()
        cs = _make_combat_state()
        enemy = cs.get_participant("goblin_scout_1")
        echo = cs.get_participant("player_1")
        assert enemy is not None and echo is not None
        echo.type = "temporary_hollowed"
        echo.conditions = conditions.apply_condition(_hollowed(2), "temporary_hollowed")
        echo.hp_current = echo.hp_max // 2
        mutations, queries = _mocks()

        await _resolve_attack_packet(
            ctx.userdata,
            enemy,
            enemy.action_pool[0],
            echo,
            mutations=mutations,
            queries=queries,
            resolver=_resolver(damage=echo.hp_current, hp_remaining=0, overkill=0),
        )

        assert echo.type == "temporary_hollowed"
        assert echo.is_fallen is True


class TestWrapEchoGating:
    """The pure Beat-4 wrap: a live echo blocks combat-end; a destroyed echo ends it as defeat."""

    def _state_with_echo(self, *, echo_fallen: bool, enemies_fallen: bool):
        cs = _make_combat_state(enemy_fallen=enemies_fallen)
        echo = cs.get_participant("player_1")
        assert echo is not None
        echo.type = "temporary_hollowed"
        echo.is_fallen = echo_fallen
        return cs

    def test_live_echo_blocks_victory_even_with_all_enemies_fallen(self):
        cs = self._state_with_echo(echo_fallen=False, enemies_fallen=True)
        wrap = combat_phase._wrap(cs)
        assert wrap.combat_ended is False

    def test_destroyed_echo_ends_combat_as_defeat(self):
        cs = self._state_with_echo(echo_fallen=True, enemies_fallen=False)
        wrap = combat_phase._wrap(cs)
        assert wrap.combat_ended is True
        assert wrap.outcome == "defeat"

    def test_no_echo_combat_behaves_normally(self):
        # Regression: an ordinary victory (all enemies fallen, no echo) is unaffected.
        cs = _make_combat_state(enemy_fallen=True)
        wrap = combat_phase._wrap(cs)
        assert wrap.combat_ended is True
        assert wrap.outcome == "victory"
