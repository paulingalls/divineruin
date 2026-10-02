"""Catalog entry, persisted snapshots and actual companion strength inputs on Postgres."""

import json
import math
import random
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import asyncpg
import pytest
from acceptance.seeds import seed_player
from sample_fixtures import CONTENT_ROOT, make_context, make_mock_room

import combat_init
import combat_resolution
import db
import db_mutations
from companion_profiles import get_companion_profile
from creation_rules import build_character_data
from hp_scaling import calculate_max_hp
from progression_tools import _award_xp_core
from rules_engine import XP_FOR_LEVEL, attribute_modifier
from session_data import CompanionState

TEMPLATES = json.loads((CONTENT_ROOT / "content/encounter_templates.json").read_text())
TARGETS = {
    "shadeling_cluster": (1, "easy", [("hollow_shadeling", "standard", 2)]),
    "hollow_wisp": (2, "moderate", [("hollow_wisp", "standard", 1)]),
    "hollow_patrol_greyvale": (3, "hard", [("hollow_mawling", "standard", 1), ("hollow_shadeling", "minion", 2)]),
    "hollowed_scout": (4, "hard", [("hollowed_scout", "elite", 1)]),
    "ruins_mawling_pair": (5, "moderate", [("hollow_mawling", "standard", 2)]),
    "bandit_ambush": (5, "moderate", [("bandit_captain", "elite", 1), ("bandit", "minion", 4)]),
    "ashmark_patrol": (6, "moderate", [("ashmark_sergeant", "elite", 1), ("ashmark_soldier", "standard", 2)]),
    "ruins_guardian": (7, "hard", [("hollow_warden", "boss", 1)]),
    "cult_cell": (8, "hard", [("cult_leader", "boss", 1), ("cult_fanatic", "standard", 1), ("cultist", "minion", 2)]),
    "hollow_corrupted_settlement": (
        14,
        "hard",
        [("hollow_knight", "standard", 1), ("hollow_mawling", "minion", 1), ("hollow_shadeling", "minion", 2)],
    ),
}
ROLE_PINS = {
    "minion": (0.5, -1, 0, 0.75, -1),
    "standard": (1, 0, 0, 1, 0),
    "elite": (1.5, 1, 1, 1.25, 1),
    "boss": (2, 2, 2, 1.5, 2),
}


@pytest.fixture(autouse=True)
def cold_catalog_reads(monkeypatch):
    import creature_catalog

    monkeypatch.setattr(db, "_cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr(db, "_cache_set", AsyncMock())
    query = AsyncMock(wraps=creature_catalog.query_creature_by_id)
    monkeypatch.setattr(creature_catalog, "query_creature_by_id", query)
    return query


@pytest.fixture
async def started(reset_db_pool, monkeypatch):
    monkeypatch.setattr(db, "_cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr(db, "_cache_set", AsyncMock())
    pool = await db.get_pool()
    sessions = []

    async def start(encounter_id, level=None, companion=None):
        pid = f"cutover_{uuid4().hex}"
        await seed_player(pool, player_id=pid, class_="warrior")
        level = level or TARGETS[encounter_id][0]
        created = build_character_data(
            "Strength reference", "draethar", "warrior", None, "", created_at=datetime(2026, 10, 1, tzinfo=UTC)
        )
        created["player_id"] = pid
        await pool.execute("UPDATE players SET data = $2::jsonb WHERE player_id = $1", pid, json.dumps(created))
        pending_events = []
        async with pool.acquire() as conn, conn.transaction():
            await _award_xp_core(
                player_id=pid,
                player=created,
                amount=XP_FOR_LEVEL[level],
                reason="strength reference",
                conn=cast(asyncpg.Connection, conn),
                pending_events=pending_events,
            )
        hp = calculate_max_hp("warrior", level, attribute_modifier(created["attributes"]["constitution"]))
        await pool.execute(
            "UPDATE players SET data = jsonb_set(data, '{hp}', $2::jsonb) WHERE player_id = $1",
            pid,
            json.dumps({"current": hp, "max": hp}),
        )
        ctx = make_context(pid, room=make_mock_room())
        if companion:
            profile = get_companion_profile(companion)
            ctx.userdata.companion = CompanionState(id=companion, name=profile.name)
        ctx.strength_events = pending_events
        sessions.append(ctx)
        roll_initiative = combat_resolution.roll_initiative
        with patch(
            "combat_resolution.roll_initiative",
            side_effect=lambda entries: roll_initiative(entries, rng=random.Random(138)),
        ):
            raw = await combat_init._start_combat_impl(ctx, encounter_id, "Catalog entry.")
        return ctx, json.loads(raw[1])

    yield start
    for ctx in sessions:
        if ctx.userdata.combat_state:
            await db_mutations.delete_combat_state(ctx.userdata.combat_state.combat_id, conn=pool)
        await pool.execute("DELETE FROM players WHERE player_id = $1", ctx.userdata.player_id)


def assert_stats(enemy, row, role):
    hp_mult, ac_mod, attack_mod, damage_mult, dc_mod = ROLE_PINS[role]
    expected_hp = max(1, math.floor(row["hp"] * hp_mult)) if role == "minion" else math.ceil(row["hp"] * hp_mult)
    assert enemy.hp_max == expected_hp
    assert enemy.ac == row["ac"] + ac_mod
    assert (enemy.attack_mod, enemy.damage_mult, enemy.dc_mod) == (attack_mod, damage_mult, dc_mod)
    assert enemy.xp_value == int(row["xp_reward"] * hp_mult)
    assert enemy.tier == row["tier"] and enemy.level == row["level"]
    assert enemy.loot_table_id == row["loot_table_id"]


def reference_damage():
    import dice

    rng = random.Random(138)
    return patch(
        "check_resolution_attack.dice_roll", side_effect=lambda notation, **kwargs: dice.roll(notation, rng=rng)
    )


async def assert_boundary_result(ctx, result, combat_id, companion, xp_before):
    import db_queries

    events = [json.loads(call.args[0]) for call in ctx.userdata.room.local_participant.publish_data.call_args_list]
    packets = [packet for event in events for packet in event.get("packets", [])]
    if isinstance(result, dict):
        packets.extend(result.get("packets", []))
        state = ctx.userdata.combat_state
        assert state is not None, "continued combat needs state"
        assert state.get_participant(ctx.userdata.player_id).hp_current > 0, "unsafe opening"
        saved = await db_mutations.load_combat_state(combat_id)
        assert saved is not None
        assert saved.to_dict() == state.to_dict(), "continued combat must persist"
    elif isinstance(result, tuple) and len(result) == 2:
        outcome = json.loads(result[1])
        assert outcome.get("outcome") == "victory", "only committed victory is tolerated"
        assert outcome.get("xp_total", 0) > 0, "victory must grant rewards"
        assert ctx.userdata.combat_state is None, "victory must clear state"
        assert await db_mutations.load_combat_state(combat_id) is None, "victory must delete state"
        player = await db_queries.get_player(ctx.userdata.player_id)
        assert player is not None
        assert player["xp"] > xp_before
    else:
        raise AssertionError("unknown boundary result")
    assert packets, "boundary must produce usable packets"
    assert any(packet.get("actor_id") == companion for packet in packets), "companion must participate"
