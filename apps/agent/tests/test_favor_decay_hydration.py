import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import session_hydration
from base_agent import BaseGameAgent
from exploration_agent import ExplorationAgent
from participant_lifecycle import _setup_party_join
from session_data import SessionData

NOW = datetime(2026, 9, 23, tzinfo=UTC)
FIXTURE = json.loads((Path(__file__).parents[2] / "mobile/src/__tests__/fixtures/favor-neglect-event.json").read_text())


async def _seed(pool, player_id, favor):
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data=$2::jsonb",
        player_id,
        json.dumps({"divine_favor": favor}),
    )


async def _favor(pool, player_id):
    row = await pool.fetchrow("SELECT data->'divine_favor' AS favor FROM players WHERE player_id=$1", player_id)
    value = row["favor"]
    return json.loads(value) if isinstance(value, str) else value


def _mods():
    res = MagicMock()
    res.read_player_resonance = AsyncMock(return_value={"current": 0, "flickering_bonus": 0})
    res.update_player_flickering_bonus = AsyncMock()
    ward = MagicMock()
    ward.read_active_ward = AsyncMock(return_value=None)
    conc = MagicMock()
    conc.read_player_concentration = AsyncMock(return_value={"spell_id": None})
    count = MagicMock()
    count.hydrate_player_session = AsyncMock(return_value=1)
    racial = MagicMock()
    racial.compute_flickering_bonus.return_value = 0
    return dict(
        resonance_mutations_mod=res,
        veil_ward_mutations_mod=ward,
        concentration_mutations_mod=conc,
        player_session_mod=count,
        racial_mod=racial,
    )


@pytest.mark.parametrize(
    ("age", "level", "expected", "amount"),
    [(8, 12, 7, -5), (6, 12, 12, 0), (8, 3, 0, -3)],
)
async def test_primary_decay_persists_once_and_publishes_after_commit(dev_db_pool, age, level, expected, amount):
    player_id = "s224_primary"
    served = (NOW - timedelta(days=age)).isoformat()
    favor = {"patron": "kaelen", "level": level, "max": 100, "last_whisper_level": 0, "last_served_at": served}
    await _seed(dev_db_pool, player_id, favor)
    session = SessionData(player_id=player_id, location_id="loc")
    events = []

    async def capture(_room, event_type, payload, _bus):
        events.append({"type": event_type, **payload})
        persisted = await _favor(dev_db_pool, player_id)
        assert persisted["level"] == expected
        assert persisted["last_decay_at"] == NOW.isoformat()

    try:
        with patch("game_events.publish_game_event", side_effect=capture):
            await session_hydration.hydrate_session_state(
                session, {"race": "human", "divine_favor": favor}, conn=dev_db_pool, now=NOW, **_mods()
            )
        persisted = await _favor(dev_db_pool, player_id)
        assert persisted["level"] == expected
        assert persisted["last_served_at"] == served
        assert (persisted.get("last_decay_at") == NOW.isoformat()) == bool(amount)
        assert session.favor_loss == (("kaelen", -amount) if amount else None)
        if level == 12 and amount:
            assert events == [FIXTURE["primary"]]
        else:
            assert len(events) == bool(amount)
            if amount:
                assert events[0]["amount"] == amount
                assert events[0]["new_level"] == expected
        with patch("game_events.publish_game_event", side_effect=capture):
            await session_hydration.hydrate_session_state(
                SessionData(player_id=player_id, location_id="loc"),
                {"race": "human", "divine_favor": persisted},
                conn=dev_db_pool,
                now=NOW,
                **_mods(),
            )
        assert len(events) == bool(amount)
    finally:
        await dev_db_pool.execute("DELETE FROM players WHERE player_id=$1", player_id)


@pytest.mark.parametrize(
    "favor",
    [
        {"patron": "kaelen", "level": 12, "max": 100, "last_whisper_level": 0},
        {
            "patron": "none",
            "level": 0,
            "max": 100,
            "last_whisper_level": 0,
            "last_served_at": (NOW - timedelta(days=8)).isoformat(),
        },
    ],
)
async def test_legacy_clock_and_unbound(dev_db_pool, favor):
    player_id = "s224_primary"
    await _seed(dev_db_pool, player_id, favor)
    try:
        with patch("game_events.publish_game_event", new_callable=AsyncMock) as publish:
            await session_hydration.hydrate_session_state(
                SessionData(player_id=player_id, location_id="loc"),
                {"race": "human", "divine_favor": favor},
                conn=dev_db_pool,
                now=NOW,
                **_mods(),
            )
        expected = {**favor, "last_served_at": NOW.isoformat()} if favor["patron"] != "none" else favor
        assert await _favor(dev_db_pool, player_id) == expected
        publish.assert_not_awaited()
    finally:
        await dev_db_pool.execute("DELETE FROM players WHERE player_id=$1", player_id)


async def test_join_callback_decays_only_joiner(dev_db_pool):
    primary_id, joiner_id = "s224_primary", "s224_joiner"
    served = (NOW - timedelta(days=8)).isoformat()
    favor = {"patron": "kaelen", "level": 12, "max": 100, "last_whisper_level": 0, "last_served_at": served}
    for player_id in (primary_id, joiner_id):
        await _seed(dev_db_pool, player_id, favor)
    session = SessionData(player_id=primary_id, location_id="loc")
    room = MagicMock()
    room.remote_participants = {}
    handlers = {}
    room.on.side_effect = lambda name, callback: handlers.setdefault(name, callback)
    queries = MagicMock()
    reads_started = asyncio.Event()
    release_reads = asyncio.Event()

    async def get_player(_identity):
        reads_started.set()
        await release_reads.wait()
        return {"player_id": joiner_id, "divine_favor": favor}

    queries.get_player = AsyncMock(side_effect=get_player)
    res = MagicMock()
    res.read_player_resonance = AsyncMock(return_value={"current": 0, "flickering_bonus": 0})
    conc = MagicMock()
    conc.read_player_concentration = AsyncMock(return_value={"spell_id": None})
    events = []

    async def capture(_room, kind, payload, _bus):
        events.append({"type": kind, **payload})
        assert (await _favor(dev_db_pool, joiner_id))["level"] == 7

    try:
        with (
            patch("db.get_pool", new_callable=AsyncMock, return_value=dev_db_pool),
            patch("session_hydration.datetime") as clock,
            patch("game_events.publish_game_event", side_effect=capture),
        ):
            clock.now.return_value = NOW
            _setup_party_join(room, session, queries=queries, resonance_mod=res, concentration_mod=conc)
            participant = SimpleNamespace(identity=joiner_id)
            handlers["participant_connected"](participant)
            await reads_started.wait()
            handlers["participant_disconnected"](participant)
            handlers["participant_connected"](participant)
            release_reads.set()
            await asyncio.gather(*(asyncio.all_tasks() - {asyncio.current_task()}))
        assert events == [FIXTURE["joiner"]]
        assert queries.get_player.await_count == 2
        assert (await _favor(dev_db_pool, primary_id)) == favor
        assert session.party.contains(joiner_id)
    finally:
        for player_id in (primary_id, joiner_id):
            await dev_db_pool.execute("DELETE FROM players WHERE player_id=$1", player_id)


async def test_combat_handback_enter_does_not_decay_again():
    session = SessionData(player_id="s224_primary", location_id="loc", room=MagicMock())
    session.background = MagicMock()
    agent_session = MagicMock()
    agent_session.userdata = session
    with (
        patch.object(ExplorationAgent, "session", property(lambda _self: agent_session)),
        patch.object(BaseGameAgent, "_enter", new_callable=AsyncMock),
        patch.object(ExplorationAgent, "_publish_session_init", new_callable=AsyncMock),
        patch("exploration_agent.start_specialization_tap"),
        patch("session_hydration.apply_session_favor_decay", new_callable=AsyncMock) as decay,
        patch("game_events.publish_game_event", new_callable=AsyncMock) as publish,
    ):
        agent = ExplorationAgent(region_type="wilderness")
        await agent._enter()
        await asyncio.gather(*agent._bg_tasks)
        decay.assert_not_awaited()
        publish.assert_not_awaited()
