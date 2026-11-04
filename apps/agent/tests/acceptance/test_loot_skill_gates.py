"""Skill-gated rewards through persisted CombatAgent victory commands."""

import random
from uuid import uuid4

import pytest
from acceptance.loot_harness import LootHarness
from acceptance.seeds import seed_player_with_pools

import db_queries
from caster_state import ConcentrationState, ResonanceTrack
from party_state import PartyMember


@pytest.fixture
def mock_combat_agent_factory():
    return None


@pytest.mark.parametrize(
    "creature,tiers,seed,count,expected,silver,rolls",
    [
        ("hollowed_scout", [{"crafting": "trained"}], 1, 1, [(0, "hollow_bone_fragment", 1)], 8, 1),
        (
            "hollowed_scout",
            [{}, {"crafting": "expert"}],
            9,
            1,
            [(0, "rend_shard", 1), (1, "hollow_bone_fragment", 1)],
            0,
            2,
        ),
        ("hollowed_scout", [{}, {}], 9, 1, [], 0, 1),
        ("hollow_mawling", [{"crafting": "expert"}], 9, 1, [(0, "rend_shard", 1)], 0, 1),
        ("hollow_mawling", [{"arcana": "trained"}], 9, 1, [], 0, 0),
        ("hollow_mawling", [{}], 9, 1, [], 0, 0),
        (
            "hollow_mawling",
            [{"crafting": "expert"}, {"arcana": "trained"}],
            9,
            1,
            [(0, "rend_shard", 1), (1, "dissolution_membrane", 1)],
            0,
            2,
        ),
        (
            "hollow_mawling",
            [{"crafting": "master"}, {"arcana": "trained"}],
            9,
            1,
            [(0, "rend_shard", 1), (1, "dissolution_membrane", 1)],
            0,
            2,
        ),
        ("hollowed_scout", [{"crafting": "expert"}], 122, 1, [(0, "rend_shard", 1)], 0, 2),
        ("hollowed_scout", [{"crafting": "trained"}], 1, 2, [(0, "hollow_bone_fragment", 1)], 8, 1),
    ],
)
async def test_victory_inventory(reset_db_pool, creature, tiers, seed, count, expected, silver, rolls):
    harness = LootHarness()
    outsider = f"loot_outsider_{uuid4().hex}"
    try:
        await harness.start_loot(creature, tiers, count)
        # A room member who did not fight cannot unlock harvesting.
        await seed_player_with_pools(harness.pool, player_id=outsider)
        await harness.pool.execute(
            "INSERT INTO skill_advancement (player_id, skill_id, tier) VALUES ($1,'crafting','expert')", outsider
        )
        harness.sd.party.members.append(PartyMember(outsider, ResonanceTrack(), ConcentrationState()))
        rng, reference = random.Random(seed), random.Random(seed)
        for _ in range(count):
            if reference.random() < 0.15:
                reference.randint(1, 6)
                reference.randint(1, 6)
            for _ in range(rolls):
                reference.random()
        await harness.victory(rng)
        actual = await harness.pool.fetch(
            "SELECT player_id, item_id, (data->>'quantity')::int AS quantity FROM player_inventory "
            "WHERE player_id=ANY($1) ORDER BY player_id, item_id",
            [*harness.players, outsider],
        )
        assert sorted((r["player_id"], r["item_id"], r["quantity"]) for r in actual) == sorted(
            (harness.players[index], item, quantity) for index, item, quantity in expected
        )
        assert rng.getstate() == reference.getstate()
        total_gold = 0
        for pid in harness.players:
            player = await db_queries.get_player(pid)
            assert player is not None
            total_gold += player["gold"]
        assert total_gold == pytest.approx(silver / 10)
    finally:
        if hasattr(harness, "encounter_id"):
            await harness.close()
        if hasattr(harness, "pool"):
            await harness.pool.execute("DELETE FROM players WHERE player_id=$1", outsider)
