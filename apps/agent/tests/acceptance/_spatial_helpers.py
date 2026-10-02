"""Real entry fixtures for placement, migration and phase persistence."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sample_fixtures import make_context, make_mock_room

import db
import db_mutations
from creation_rules import build_character_data
from mode_tools import enter_mode


@pytest.fixture
async def spatial_entry(reset_db_pool, monkeypatch, mock_combat_agent_factory):
    monkeypatch.setattr(db, "_cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr(db, "_cache_set", AsyncMock())
    pool = await db.get_pool()
    contexts, ids = [], []

    async def create(data=None, *, members=1, companion=None, encounter="ruins_mawling_pair", enter=True):
        players = []
        for _ in range(members):
            pid = f"spatial_{uuid4().hex}"
            row = (
                data
                if data is not None
                else build_character_data(
                    "Spatial", "human", "warrior", None, "", created_at=datetime(2026, 10, 1, tzinfo=UTC)
                )
            )
            await db_mutations.create_player(pid, None, row)
            ids.append(pid)
            players.append(pid)
        ctx = make_context(players[0], room=make_mock_room(), party_member_ids=players, companion_id=companion)
        contexts.append(ctx)
        if enter:
            result = await enter_mode(ctx, "combat", encounter, "Spatial test")
            return ctx, json.loads(result[1])
        return ctx, players

    yield create
    for ctx in contexts:
        if ctx.userdata.combat_state:
            await db_mutations.delete_combat_state(ctx.userdata.combat_state.combat_id, conn=pool)
    for pid in ids:
        await pool.execute("DELETE FROM players WHERE player_id=$1", pid)


def pos(x: float = 0, y: float = 0, z: float = 0):
    return {"x": x, "y": y, "z": z}


def move(actor_id, x: float = 30):
    return {"type": "maneuver", "action": "move", "target_id": actor_id, "destination": pos(x)}


async def persisted(combat_id):
    state = await db_mutations.load_combat_state(combat_id)
    assert state is not None and state.spatial is not None
    return state.to_dict()
