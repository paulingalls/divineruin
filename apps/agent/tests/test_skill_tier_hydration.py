import copy
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from combat._helpers import _resolve_deps, _resolve_round
from sample_fixtures import make_context, make_mock_room

import conditions
import db_mutations_skill_advancement
import db_queries
import rules_engine
from check_tools import _check_skill_impl
from combat_init import _start_combat_impl
from tests.combat.test_shield_bash_prone import _ashmark_patrol
from tests.combat.test_start_combat import SAMPLE_PLAYER


def _player(player_id: str, *, proficient: bool = True, inspired: bool = False) -> dict:
    player = copy.deepcopy(SAMPLE_PLAYER)
    player["player_id"] = player_id
    player["name"] = player_id
    player["proficiencies"] = ["athletics"] if proficient else []
    player["conditions"] = conditions.apply_condition([], "inspired") if inspired else []
    player.pop("skill_tiers", None)
    return player


async def _seed_player(pool, player: dict) -> None:
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player["player_id"],
        json.dumps(player),
    )


async def _seed_tier(pool, player_id: str, skill: str, tier: str) -> None:
    await pool.execute(
        "INSERT INTO skill_advancement "
        "(player_id, skill_id, tier, use_counter, narrative_moment_ready) "
        "VALUES ($1, $2, $3, 0, FALSE) "
        "ON CONFLICT (player_id, skill_id) DO UPDATE SET tier = EXCLUDED.tier",
        player_id,
        skill,
        tier,
    )


async def _cleanup(pool, *player_ids: str) -> None:
    await pool.execute("DELETE FROM players WHERE player_id = ANY($1)", list(player_ids))


class _CombatQueries:
    def __init__(self, pool):
        self.pool = pool

    async def get_player(self, player_id: str):
        return await db_queries.get_player(player_id, conn=self.pool)

    async def get_players_for_update(self, player_ids: list[str]):
        return await db_queries.get_players_for_update(player_ids, conn=self.pool)

    async def get_player_inventory(self, _player_id: str):
        return []

    async def get_player_faction_reputation(self, _player_id: str, _faction_id: str):
        return 0


def _combat_dependencies(pool) -> tuple[MagicMock, Any, MagicMock]:
    mutations = MagicMock()
    mutations.save_combat_state = AsyncMock()
    content = MagicMock()
    content.get_encounter_template = AsyncMock(return_value=_ashmark_patrol())
    content.get_faction = AsyncMock(
        return_value={
            "id": "thornwatch",
            "name": "The Thornwatch",
            "reputation_tiers": {"neutral": {"threshold": 0}, "friendly": {"threshold": 5}},
        }
    )
    return mutations, _CombatQueries(pool), content


@pytest.mark.parametrize("target_member", ["primary", "second"])
async def test_master_athletics_from_advancement_prevents_party_member_prone(dev_db_pool, target_member):
    pool = dev_db_pool
    primary = f"s056_master_primary_{target_member}"
    second = f"s056_master_second_{target_member}"
    await _seed_player(pool, _player(primary))
    await _seed_player(pool, _player(second))
    await _seed_tier(pool, primary, "athletics", "master")
    await _seed_tier(pool, second, "athletics", "master")
    try:
        mutations, queries, content = _combat_dependencies(pool)
        ctx = make_context(primary, room=make_mock_room(), party_member_ids=[second])
        await _start_combat_impl(
            ctx,
            "ashmark_patrol",
            "The patrol closes in.",
            mutations=mutations,
            queries=queries,
            content=content,
        )
        state = ctx.userdata.combat_state
        target_id = primary if target_member == "primary" else second
        target = state.get_participant(target_id)
        soldier = state.get_participant("ashmark_soldier_1")
        state.beat = "resolution"
        state.pending_declarations = {
            target.id: {"type": "defend"},
            soldier.id: {"type": "maneuver", "target_id": target.id},
        }

        with patch("random.randint", side_effect=[18, 3]):
            result = await _resolve_round(ctx, **_resolve_deps())

        packet = next(row for row in result["packets"] if row["actor_id"] == soldier.id)
        assert packet["shove"] == "resisted"
        assert packet["prone_immunity"] == "Immovable Anchor"
        assert not conditions.has_condition(state.get_participant(target_id).conditions, "prone")
    finally:
        await _cleanup(pool, primary, second)


@pytest.mark.parametrize("inspired", [False, True], ids=["plain", "consumed-condition"])
async def test_proficient_first_use_persists_trained_without_json_store(dev_db_pool, inspired):
    pool = dev_db_pool
    player_id = f"s056_proficient_{inspired}"
    await _seed_player(pool, _player(player_id, inspired=inspired))
    try:
        before = await db_queries.get_player(player_id, conn=pool)
        assert before is not None
        assert rules_engine._get_skill_tier(before, "athletics") == "trained"

        ctx = make_context(player_id, room=make_mock_room())
        await _check_skill_impl(
            ctx,
            "athletics",
            "moderate",
            "climbing",
            queries=db_queries,
            mutations=db_mutations_skill_advancement,
        )

        row = await pool.fetchrow(
            "SELECT tier, use_counter FROM skill_advancement WHERE player_id = $1 AND skill_id = 'athletics'",
            player_id,
        )
        reread = await db_queries.get_player(player_id, conn=pool)
        assert reread is not None
        assert dict(row) == {"tier": "trained", "use_counter": 1}
        assert rules_engine._get_skill_tier(reread, "athletics") == "trained"
        assert await pool.fetchval("SELECT data ? 'skill_tiers' FROM players WHERE player_id = $1", player_id) is False
    finally:
        await _cleanup(pool, player_id)


async def test_nonproficient_first_use_stays_untrained(dev_db_pool):
    pool = dev_db_pool
    player_id = "s056_nonproficient"
    await _seed_player(pool, _player(player_id, proficient=False))
    try:
        before = await db_queries.get_player(player_id, conn=pool)
        assert before is not None
        assert rules_engine._get_skill_tier(before, "athletics") == "untrained"

        await _check_skill_impl(
            make_context(player_id, room=make_mock_room()),
            "athletics",
            "moderate",
            "climbing",
            queries=db_queries,
            mutations=db_mutations_skill_advancement,
        )

        row = await pool.fetchrow(
            "SELECT tier, use_counter FROM skill_advancement WHERE player_id = $1 AND skill_id = 'athletics'",
            player_id,
        )
        assert dict(row) == {"tier": "untrained", "use_counter": 1}
        reread = await db_queries.get_player(player_id, conn=pool)
        assert reread is not None
        assert rules_engine._get_skill_tier(reread, "athletics") == "untrained"
    finally:
        await _cleanup(pool, player_id)


async def test_public_read_ignores_stale_json_and_uses_only_advancement_rows(dev_db_pool):
    pool = dev_db_pool
    player_id = "s056_stale_json"
    player = _player(player_id)
    player["skill_tiers"] = {"athletics": "master"}
    await _seed_player(pool, player)
    try:
        without_row = await db_queries.get_player(player_id, conn=pool)
        assert without_row is not None
        assert "skill_tiers" not in without_row
        assert rules_engine._get_skill_tier(without_row, "athletics") == "trained"

        await _seed_tier(pool, player_id, "athletics", "expert")
        with_row = await db_queries.get_player(player_id, conn=pool)
        assert with_row is not None
        assert with_row["skill_tiers"] == {"athletics": "expert"}
        assert rules_engine._get_skill_tier(with_row, "athletics") == "expert"
    finally:
        await _cleanup(pool, player_id)
