"""Persisted first-episode players driven through registered combat tools."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sample_fixtures import make_context, make_mock_room, published_payloads

import db
import db_mutations
import db_queries
import event_types as E
from companion_profiles import select_companion_for_archetype
from creation_rules import build_character_data
from mode_tools import enter_mode


@pytest.fixture
async def fragment_player(reset_db_pool):
    pool = await db.get_pool()
    contexts = []

    async def create(
        *, location="accord_guild_infirmary", receipt="rider", encounter="fragment_shadeling", archetype="warrior"
    ):
        pid = f"fragment_{uuid4().hex}"
        row = build_character_data("Vale", "human", archetype, None, "", created_at=datetime(2026, 11, 1, tzinfo=UTC))
        row.update(location_id=location, flags={"onboarding_beat": "complete"})
        if receipt is not None:
            row["flags"]["first_episode"] = receipt
        await db_mutations.create_player(pid, None, row)
        ctx = make_context(
            pid, location_id=location, room=make_mock_room(), companion_id=select_companion_for_archetype(archetype)
        )
        contexts.append(ctx)
        await enter_mode(ctx, "combat", encounter, "The oilcloth bundle")
        return ctx

    yield create
    for ctx in contexts:
        if ctx.userdata.combat_state:
            await db_mutations.delete_combat_state(ctx.userdata.combat_state.combat_id)
        await pool.execute("DELETE FROM players WHERE player_id=$1", ctx.userdata.player_id)


async def assert_settled(ctx, *, stage=0):
    pid = ctx.userdata.player_id
    player = await db_queries.get_player(pid)
    assert player is not None
    assert player["flags"]["first_episode"] == "complete"
    quest = await db_queries.get_player_quest(pid, "greyvale_anomaly")
    assert quest is not None
    assert quest.get("status", "active") == "active" and quest["current_stage"] == stage
    pool = await db.get_pool()
    rows = await pool.fetch(
        "SELECT data, tainted FROM player_inventory WHERE player_id=$1 AND item_id='greyvale_veil_fragment'", pid
    )
    import json

    assert [(json.loads(row["data"])["quantity"], row["tainted"]) for row in rows] == [(1, False)]
    assert ctx.userdata.combat_state is None
    assert player["xp"] < 75 and player["level"] == 1
    packets = published_payloads(ctx.userdata.room)
    assert any(p["type"] == E.ITEM_ACQUIRED and p["item_id"] == "greyvale_veil_fragment" for p in packets)
    assert any(p["type"] == E.QUEST_UPDATED and p["quest_id"] == "greyvale_anomaly" for p in packets)
    assert any(p["type"] == E.INVENTORY_UPDATED for p in packets)


async def drain(ctx):
    import json

    from combat_turn import resolve_phase

    for _ in range(64):
        result = await resolve_phase(ctx)
        if isinstance(result, tuple):
            return result
        data = json.loads(result)
        if data["beat"] == "declaration" and data.get("next", {}).get("waiting_on") is None:
            return result
    raise AssertionError("Combat failed to drain")


async def declarations(ctx, *, argue=False):
    from combat_turn import declare_phase
    from declaration_payloads import AbilityDecl, AttackDecl, DefendDecl

    cs = ctx.userdata.combat_state
    enemies = [p for p in cs.participants if p.type == "enemy" and not p.is_fallen]
    target = enemies[0] if enemies else None
    decls = []
    for actor in cs.participants:
        if actor.is_fallen:
            continue
        if argue and actor.type == "player":
            decls.append(
                AbilityDecl(kind="ability", actor_id=actor.id, action="de_escalate", targets=[], argument_type="reason")
            )
        elif argue or target is None or actor.type == "enemy":
            decls.append(DefendDecl(reshape=[], kind="defend", actor_id=actor.id))
        else:
            decls.append(
                AttackDecl(
                    reshape=[],
                    kind="attack",
                    actor_id=actor.id,
                    action=actor.action_pool[0]["name"],
                    target_id=target.id,
                    held_item_id="",
                    rider="",
                )
            )
    await declare_phase(ctx, decls)
