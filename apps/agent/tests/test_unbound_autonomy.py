"""Autonomy judgments at the locked database boundary."""

import json

import pytest
from test_patron_deeds import judge, read
from test_patron_deeds import player as player

from patron_deeds import judge_pending_deeds, mark_awarded, record_deed
from unbound_autonomy import AutonomyGrant

ACTIONS = {"won_alone": "pending", "succeeded_alone": "pending", "channeled_raw": "pending"}


async def prepare(player, *, deeds=None, autonomy=None):
    pool, pid = player
    data = {"divine_favor": {"patron": "none", "level": 0, "max": 100}, "patron_deeds": deeds or ACTIONS}
    if autonomy is not None:
        data["unbound_autonomy"] = autonomy
    await pool.execute("UPDATE players SET data=data || $2::jsonb WHERE player_id=$1", pid, json.dumps(data))
    return await read(pool, pid)


@pytest.mark.parametrize(
    "fields,kind,amount",
    [
        ({"divine_favor": {"patron": None}}, "succeeded_alone", 1),
        ({}, "won_alone", 4),
        ({"divine_favor": {}}, "won_alone", 4),
    ],
)
async def test_missing_or_null_patron_awards_autonomy(player, fields, kind, amount):
    pool, pid = player
    before = await prepare(player, deeds={kind: "pending"})
    del before["divine_favor"]
    before.update(fields)
    await pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", pid, json.dumps(before))

    grant, events = await judge(pool, pid)

    assert isinstance(grant, AutonomyGrant)
    assert (grant.previous_level, grant.new_level) == (0, amount)
    assert events == []
    assert await read(pool, pid) == dict(
        before, patron_deeds={}, unbound_autonomy={"level": amount, "max": 100, "tier": "Self-Reliant"}
    )


async def test_authored_gain_preserves_fields(player):
    pool, pid = player
    before = await prepare(player)
    grant, events = await judge(pool, pid)
    assert isinstance(grant, AutonomyGrant)
    assert (grant.previous_level, grant.new_level, grant.reached_tier) == (0, 7, None)
    assert events == []
    after = dict(before, patron_deeds={}, unbound_autonomy={"level": 7, "max": 100, "tier": "Self-Reliant"})
    assert await read(pool, pid) == after
    assert await judge(pool, pid) == (None, [])
    assert await read(pool, pid) == after


@pytest.mark.parametrize(
    "start,tier,kind,end,reached",
    [
        (38, "Self-Reliant", "won_alone", 42, "Self-Forged"),
        (38, "Self-Reliant", "succeeded_alone", 39, None),
        (39, "Self-Reliant", "succeeded_alone", 40, "Self-Forged"),
        (73, "Self-Forged", "succeeded_alone", 74, None),
        (74, "Self-Forged", "succeeded_alone", 75, "Sovereign"),
        (2, "Self-Forged", "won_alone", 6, None),
        (99, "Sovereign", None, 100, None),
    ],
)
async def test_tier_and_cap(player, start, tier, kind, end, reached):
    pool, pid = player
    before = await prepare(
        player,
        deeds={kind: "pending"} if kind else None,
        autonomy={"level": start, "max": 100, "tier": tier, "extra": [1]},
    )
    grant, events = await judge(pool, pid)
    assert isinstance(grant, AutonomyGrant)
    assert (grant.previous_level, grant.new_level, grant.previous_tier, grant.reached_tier) == (
        start,
        end,
        tier,
        reached,
    )
    assert events == []
    assert await read(pool, pid) == dict(
        before, patron_deeds={}, unbound_autonomy=dict(before["unbound_autonomy"], level=end, tier=reached or tier)
    )
    assert await judge(pool, pid) == (None, [])


async def test_pending_once_and_new_window(player):
    pool, pid = player
    await prepare(player, deeds={"won_combat": "pending"})
    async with pool.acquire() as conn, conn.transaction():
        await mark_awarded(pid, "channeled_raw", conn=conn)
        for _ in range(3):
            await record_deed(pid, "won_alone", conn=conn)
            await record_deed(pid, "channeled_raw", conn=conn)
    assert (await read(pool, pid))["patron_deeds"] == {
        "won_combat": "pending",
        "won_alone": "pending",
        "channeled_raw": "awarded",
    }
    grant, _ = await judge(pool, pid)
    assert isinstance(grant, AutonomyGrant)
    assert grant.new_level == 4
    assert await judge(pool, pid) == (None, [])
    async with pool.acquire() as conn, conn.transaction():
        await record_deed(pid, "won_alone", conn=conn)
    grant, _ = await judge(pool, pid)
    assert isinstance(grant, AutonomyGrant)
    assert grant.new_level == 8


async def test_rollback(player):
    pool, pid = player
    before = await prepare(player)
    with pytest.raises(RuntimeError, match="abort"):
        async with pool.acquire() as conn, conn.transaction():
            grant = await judge_pending_deeds(pid, conn=conn, pending_events=[])
            assert isinstance(grant, AutonomyGrant)
            assert grant.new_level == 7
            assert (await read(conn, pid))["patron_deeds"] == {}
            raise RuntimeError("abort")
    assert await read(pool, pid) == before


@pytest.mark.parametrize(
    "change",
    [
        {"autonomy_actions": []},
        {"autonomy_actions": None},
        {"autonomy_actions": [{"action": "won_alone", "amount": 1}] * 3},
        *[{"field": "action", "value": "unknown"}],
        *[{"field": "amount", "value": value} for value in (0, -1, True, 1.5)],
        *[{"tiers": value} for value in ([], ["a", "a", "c"], ["a", "", "c"], ["a", 2, "c"], None)],
    ],
)
async def test_invalid_authored_config_preserves_row(player, tmp_path, monkeypatch, change):
    import unbound_autonomy as autonomy

    pool, pid = player
    before = await prepare(player)
    data = json.loads(autonomy._UNBOUND_JSON_PATH.read_text())
    if "field" in change:
        data["autonomy_actions"][0][change["field"]] = change["value"]
    else:
        data.update(change)
    path = tmp_path / "unbound.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(autonomy, "_UNBOUND_JSON_PATH", path)
    autonomy.load_unbound.cache_clear()
    try:
        with pytest.raises(ValueError, match=r"autonomy_actions|tiers"):
            await judge(pool, pid)
        assert await read(pool, pid) == before
    finally:
        autonomy.load_unbound.cache_clear()


async def test_authored_amounts_and_names(player, tmp_path, monkeypatch):
    import unbound_autonomy as autonomy

    pool, pid = player
    await prepare(player, deeds={"won_alone": "pending"}, autonomy={"level": 38, "max": 100, "tier": "Self-Reliant"})
    data = json.loads(autonomy._UNBOUND_JSON_PATH.read_text())
    data["autonomy_actions"][0]["amount"] = 9
    data["tiers"][1] = "Authored tier"
    path = tmp_path / "unbound.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(autonomy, "_UNBOUND_JSON_PATH", path)
    autonomy.load_unbound.cache_clear()
    try:
        grant, _ = await judge(pool, pid)
        assert isinstance(grant, AutonomyGrant)
        assert (grant.new_level, grant.reached_tier) == (47, "Authored tier")
        assert (await read(pool, pid))["unbound_autonomy"]["tier"] == "Authored tier"
    finally:
        autonomy.load_unbound.cache_clear()


@pytest.mark.parametrize(
    "state",
    [
        {"level": -1, "tier": "Self-Reliant"},
        {"level": 101, "tier": "Self-Reliant"},
        {"level": 3, "tier": "Unknown"},
        {"level": 0, "max": 0, "tier": "Self-Reliant"},
    ],
)
async def test_corrupt_stored_state_preserves_row(player, state):
    pool, pid = player
    before = await prepare(player, autonomy=state)
    with pytest.raises(ValueError):
        await judge(pool, pid)
    assert await read(pool, pid) == before
