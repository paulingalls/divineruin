"""Enemy pockets through registered entry, resolution, rewind and victory commands."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from random import Random
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from _zhael_unravel_fixtures import favor
from acceptance.loot_harness import LootHarness
from acceptance.seeds import seed_player_with_pools
from sample_fixtures import published_payloads

import creature_schema
import db
import db_content_queries
import db_mutations
import db_queries
import encounter_loot
import event_types as E
from caster_state import ConcentrationState, ResonanceTrack
from party_state import PartyMember

ROLES = ["standard", "standard", "standard", "elite"]
DROPS = [
    [
        {"item_id": "wolf_pelt", "quantity": 2, "tainted": False},
        {"item_id": "wolf_fangs", "quantity": 2, "tainted": False},
        {"item_id": "wolf_meat", "quantity": 1, "tainted": False},
    ],
    [{"item_id": "rend_shard", "quantity": 2, "tainted": True}],
    [{"item_id": "hollow_bone_fragment", "quantity": 1, "tainted": True}],
    [{"item_id": "ironwood_bark", "quantity": 2, "tainted": False}],
]


@pytest.fixture
def mock_combat_agent_factory() -> None:
    return None


@pytest.fixture(name="pocket_fight")
async def fixture_pocket_fight(reset_db_pool, tmp_path, monkeypatch):
    @asynccontextmanager
    async def open_fight(seats: int = 1) -> AsyncIterator[tuple[LootHarness, list[str], MagicMock]]:
        h = LootHarness()
        pool = await db.get_pool()
        base = json.loads(await pool.fetchval("SELECT data FROM creatures WHERE id='bandit'"))
        tables = json.loads(creature_schema.LOOT_CATALOG.read_text())
        ids = [f"pocket_{uuid4().hex}" for _ in DROPS]
        catalog = tmp_path / "loot_tables.json"
        for index, (table_id, drops) in enumerate(zip(ids, DROPS, strict=True)):
            entries = [{"item_id": d["item_id"], "quantity": d["quantity"], "chance": 1.0} for d in drops]
            if index == 0:
                entries[1]["quantity"] = "1d4"
                entries[2]["chance"] = 0.8
                entries[2]["requires"] = [{"skill": "survival", "tier": "trained"}]
            if ROLES[index] == "elite":
                entries[0]["quantity"] = 1
            table = {
                "id": table_id,
                "description": "Pocket fixture",
                "hollow_residue": drops[0]["tainted"],
                "drops": entries,
            }
            tables.append(table)
            await pool.execute("INSERT INTO loot_tables(id,data) VALUES($1,$2)", table_id, json.dumps(table))
            await pool.execute(
                "INSERT INTO creatures(id,data) VALUES($1,$2)",
                table_id,
                json.dumps({**base, "id": table_id, "loot_table_id": table_id}),
            )
        catalog.write_text(json.dumps(tables))
        monkeypatch.setattr(creature_schema, "LOOT_CATALOG", catalog)
        try:
            with patch("encounter_loot.generate_loot", wraps=encounter_loot.generate_loot) as generate:
                await h.start_loot(
                    ids, [{"survival": "trained"}, *[{} for _ in range(seats - 1)]], len(ids), Random(1), roles=ROLES
                )
                yield h, ids, generate
        finally:
            await h.close()
            for table_id in ids:
                await pool.execute("DELETE FROM creatures WHERE id=$1", table_id)
                await pool.execute("DELETE FROM loot_tables WHERE id=$1", table_id)

    return open_fight


async def raw_row(h: LootHarness) -> dict:
    state = h.sd.combat_state
    assert state is not None
    return json.loads(await h.pool.fetchval("SELECT data FROM combat_instances WHERE combat_id=$1", state.combat_id))


def enemy_rows(image: dict) -> list[dict]:
    return [row for row in image["participants"] if row["type"] == "enemy"]


def pockets(image: dict) -> list[list[dict] | None]:
    return [row["carried_items"] for row in enemy_rows(image)]


async def load_legacy(h: LootHarness, image: dict) -> None:
    combat_id = image["combat_id"]
    await db_mutations.save_combat_state(combat_id, image)
    h.sd.combat_state = await db_mutations.load_combat_state(combat_id)


async def defend(h: LootHarness) -> None:
    state = h.sd.combat_state
    assert state is not None
    await h.command(
        "declare_phase",
        {
            "declarations": [
                {"reshape": [], "kind": "defend", "actor_id": p.id} for p in state.participants if not p.is_fallen
            ]
        },
    )


async def assert_payout(h: LootHarness, drops: list[dict], outsider: str | None = None) -> None:
    rows = await h.pool.fetch(
        "SELECT player_id,item_id,tainted,(data->>'quantity')::int AS quantity "
        "FROM player_inventory WHERE player_id=ANY($1)",
        [*h.players, *([outsider] if outsider else [])],
    )
    expected = [
        (h.players[i % len(h.players)], drop["item_id"], drop["tainted"], drop["quantity"])
        for i, drop in enumerate(drops)
    ]
    assert sorted(tuple(row) for row in rows) == sorted(expected)
    acquired = [
        (p["player_id"], p["item_id"], p["quantity"], p["source"])
        for p in published_payloads(h.sd.room)
        if p["type"] == E.ITEM_ACQUIRED
    ]
    assert acquired == [(pid, item, quantity, "combat_loot") for pid, item, _, quantity in expected]


async def player_rewards(player_id: str) -> tuple[int, float]:
    player = await db_queries.get_player(player_id)
    assert player is not None
    return player.get("xp", 0), player["gold"]


def forbid_rolls(generate: MagicMock) -> None:
    generate.reset_mock(side_effect=True)
    generate.side_effect = AssertionError("initialized pockets rolled again")


def assert_pockets_private(h: LootHarness) -> None:
    before_victory = json.dumps(
        [
            json.loads(list(h.model.receipts.values())[-1].output),
            h.session.current_agent.chat_ctx.to_dict(),
            published_payloads(h.sd.room),
        ]
    )
    assert "carried_items" not in before_victory
    assert all(drop["item_id"] not in before_victory for drops in DROPS for drop in drops)


@pytest.mark.parametrize("seats", [1, 2])
async def test_entry_and_manual_victory(pocket_fight, seats: int) -> None:
    async with pocket_fight(seats) as (h, ids, generate):
        image = await raw_row(h)
        assert pockets(image) == pockets(image["round_checkpoints"][0]["combat"]) == DROPS
        assert all(row["carried_items"] is None for row in image["participants"] if row["type"] != "enemy")
        assert [(c.args[0]["id"], c.args[1]) for c in generate.call_args_list] == list(zip(ids, ROLES, strict=True))
        await assert_payout(h, [])
        assert_pockets_private(h)

        outsider = f"pocket_outsider_{uuid4().hex}"
        await seed_player_with_pools(h.pool, player_id=outsider)
        try:
            await h.pool.execute(
                "INSERT INTO skill_advancement(player_id,skill_id,tier) VALUES ($1,'survival','expert')", outsider
            )
            h.sd.party.members.append(PartyMember(outsider, ResonanceTrack(), ConcentrationState()))
            await h.pool.execute(
                "UPDATE players SET data = data || '{\"proficiencies\":[]}'::jsonb WHERE player_id=$1", h.players[0]
            )
            state = await h.reload()
            paid, emptied, standing, removed = [state.get_participant(id_) for id_ in h.enemies]
            for enemy in (paid, emptied):
                enemy.is_fallen = True
                enemy.hp_current = 0
            emptied.carried_items.clear()
            assert standing.carried_items == DROPS[2]
            state.participants.remove(removed)
            state.initiative_order.remove(removed.id)
            for key in ("positions", "speeds"):
                del state.spatial[key][removed.id]
            await h.persist()
            xp_before = [(await player_rewards(pid))[0] for pid in h.players]
            forbid_rolls(generate)
            await h.manual_victory(Random(1))
            await assert_payout(h, DROPS[0], outsider)
            assert generate.call_count == 0
            # Seed 1 rolls 2, 5, 1 silver for the three remaining tier-1 bandits.
            gold = pytest.approx(0.8 if seats == 1 else 0.6)
            xp_share = int(3 * paid.xp_value * (1 if seats == 1 else 0.75))
            assert [await player_rewards(pid) for pid in h.players] == [(xp + xp_share, gold) for xp in xp_before]
        finally:
            await h.pool.execute("DELETE FROM players WHERE player_id=$1", outsider)


async def test_legacy_reload_rewind_and_natural_victory(pocket_fight) -> None:
    async with pocket_fight() as (h, ids, generate):
        state = await h.reload()
        assert pockets(state.to_dict()) == DROPS
        assert generate.call_count == len(ids)
        await favor(h, h.players[0])
        image = await raw_row(h)
        current = enemy_rows(image)
        opening = enemy_rows(image["round_checkpoints"][0]["combat"])
        current[0]["carried_items"] = []
        opening[0].pop("carried_items")
        current[1].pop("carried_items")
        opening[1].pop("carried_items")
        opening[2]["carried_items"] = []
        opening[3].pop("carried_items")
        removed = current[3]["id"]
        image["participants"].remove(current[3])
        image["initiative_order"].remove(removed)
        for key in ("positions", "speeds"):
            del image["spatial"][key][removed]
        await load_legacy(h, image)
        assert pockets(h.sd.combat_state.to_dict()) == [[], None, DROPS[2]]
        generate.reset_mock()
        await defend(h)
        await h.drain()
        assert [c.args[0]["id"] for c in generate.call_args_list] == [ids[1], ids[3]]
        live = [[], DROPS[1], DROPS[2]]
        rewound = [[], DROPS[1], [], DROPS[3]]
        saved = await raw_row(h)
        assert pockets(saved) == live
        forbid_rolls(generate)
        await h.command("activate", {"id": "zhael_unravel_fate"})
        restored_state = await h.reload()
        restored = pockets(restored_state.to_dict())
        assert all(p.carried_items is None for p in restored_state.participants if p.type != "enemy")
        await defend(h)
        await h.drain()
        assert restored == pockets((await h.reload()).to_dict()) == rewound
        assert [pockets(c["combat"]) for c in saved["round_checkpoints"]] == [rewound, live]
        assert_pockets_private(h)
        await h.victory(Random(1))
        await assert_payout(h, [*DROPS[1], *DROPS[3]])
        assert generate.call_count == 0


@pytest.mark.parametrize("resume_inner_fire", [False, True], ids=["direct_victory", "inner_fire"])
async def test_legacy_first_use_before_victory(pocket_fight, resume_inner_fire: bool) -> None:
    async with pocket_fight() as (h, ids, generate):
        image = await raw_row(h)
        for index, row in enumerate(enemy_rows(image)):
            if index == 1:
                row.pop("carried_items")
                row.update(is_fallen=True, hp_current=0)
            else:
                row["carried_items"] = []
        enemy_rows(image["round_checkpoints"][0]["combat"])[1].pop("carried_items")
        if resume_inner_fire:
            image["inner_fire_continuation"] = {"player_id": h.players[0], "facts": {"fire_damage": 1}, "steps": {}}
        await load_legacy(h, image)
        generate.reset_mock()
        if resume_inner_fire:
            await h.command("resolve_phase", {})
            resumed = await h.reload()
            assert resumed.inner_fire_continuation is None
            assert pockets(resumed.to_dict()) == [[], DROPS[1], [], []]
        await h.manual_victory(Random(1))
        assert [c.args[0]["id"] for c in generate.call_args_list] == [ids[1]]
        await assert_payout(h, DROPS[1])


async def test_no_table_keeps_coin_and_xp(reset_db_pool) -> None:
    h = LootHarness()
    load = db_content_queries.load_creature_enemy

    async def no_table(*args, **kwargs) -> dict:
        return {**await load(*args, **kwargs), "loot_table_id": ""}

    with (
        patch.object(db_content_queries, "load_creature_enemy", side_effect=no_table),
        patch.object(encounter_loot, "generate_loot", side_effect=AssertionError("encounter has no loot table")),
    ):
        try:
            await h.start_loot("bandit", [{}], 1, Random(1))
            assert pockets((await h.reload()).to_dict()) == [[]]
            await defend(h)
            await h.drain()
            assert pockets((await raw_row(h))["round_checkpoints"][-1]["combat"]) == [[]]
            xp_before, _ = await player_rewards(h.players[0])
            state = h.sd.combat_state
            assert state is not None
            enemy = state.get_participant(h.enemies[0])
            assert enemy is not None
            await h.victory(Random(1))
            await assert_payout(h, [])
            assert await player_rewards(h.players[0]) == (xp_before + enemy.xp_value, pytest.approx(0.2))
        finally:
            await h.close()
