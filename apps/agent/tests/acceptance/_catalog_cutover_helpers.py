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

    async def start(encounter_id, level=None, companion=None, player_class="warrior"):
        pid = f"cutover_{uuid4().hex}"
        await seed_player(pool, player_id=pid, class_="warrior")
        level = level or TARGETS[encounter_id][0]
        created = build_character_data(
            "Strength reference", "draethar", player_class, None, "", created_at=datetime(2026, 10, 1, tzinfo=UTC)
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
        hp = calculate_max_hp(player_class, level, attribute_modifier(created["attributes"]["constitution"]))
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


async def complete_reference_combat(ctx):
    from acceptance._capstone_helpers import _d20, _resolve_round

    import combat_turn

    combat_id = ctx.userdata.combat_state.combat_id
    with patch("check_resolution.dice_roll", return_value=_d20(20)), reference_damage():
        for _ in range(20):
            state = ctx.userdata.combat_state
            actor = state.get_participant(ctx.userdata.player_id)
            target = next(p for p in state.participants if p.type == "enemy" and not p.is_fallen)
            await combat_turn._declare_phase_impl(
                ctx, {actor.id: {"type": "attack", "action": actor.action_pool[0]["name"], "target_id": target.id}}
            )
            result = await _resolve_round(ctx)
            if isinstance(result, tuple):
                assert json.loads(result[1])["outcome"] == "victory"
                assert ctx.userdata.combat_state is None
                assert await db_mutations.load_combat_state(combat_id) is None
                return
    raise AssertionError("referenced encounter did not reach a committed victory")


async def assert_catalog_effects(started):
    from acceptance._capstone_helpers import _d20, _resolve_round
    from livekit.agents.llm import ToolError

    import combat_turn
    import conditions
    from combat_marks import attack_bonus

    for encounter, enemy_id, name, condition, face in [
        ("ashmark_patrol", "ashmark_soldier_1", "Shield Bash", "prone", 1),
        ("ruins_mawling_pair", "mawling_1", "Lunge", "grappled", 13),
    ]:
        ctx, roster = await started(encounter)
        pid = ctx.userdata.player_id
        produced = next(p for p in roster["participants"] if p["id"] == enemy_id)
        name = next(action for action in produced["actions"] if action == name)
        await combat_turn._declare_phase_impl(
            ctx, {pid: {"type": "defend"}, enemy_id: {"type": "attack", "action": name, "target_id": pid}}
        )
        with patch("check_resolution.dice_roll", return_value=_d20(face)), reference_damage():
            result = await _resolve_round(ctx)
        packet = next(p for p in result["packets"] if p["actor_id"] == enemy_id)
        assert packet["condition_inflicted"] == condition
        state = ctx.userdata.combat_state
        saved = await db_mutations.load_combat_state(state.combat_id)
        assert saved is not None and saved.to_dict() == state.to_dict()
        player = saved.get_participant(pid)
        assert player is not None
        assert conditions.has_condition(player.conditions, condition)
        if condition == "grappled":
            assert next(c for c in player.conditions if c["type"] == condition)["source"] == enemy_id
            with pytest.raises(ToolError, match="grappled"):
                await combat_turn._declare_phase_impl(ctx, {pid: {"type": "retreat"}})
            await combat_turn._declare_phase_impl(
                ctx, {pid: {"type": "maneuver", "maneuver_intent": "escape", "target_id": enemy_id}}
            )
            with patch("random.randint", return_value=20):
                escaped = await _resolve_round(ctx)
            assert any(p.get("escape") == "escaped" for p in escaped["packets"])
            assert not conditions.has_condition(ctx.userdata.combat_state.get_participant(pid).conditions, condition)

    ctx, roster = await started("ashmark_patrol")
    pid, source_id = ctx.userdata.player_id, "ashmark_sergeant"
    producer = next(p for p in roster["participants"] if p["id"] == source_id)
    assert {"name": "Rally", "kind": "command"} in producer["mark_actions"]
    # The mark-consumer diagnostic needs Rally to resolve before the consuming strike.
    state = ctx.userdata.combat_state
    state.get_participant(source_id).initiative = max(p.initiative for p in state.participants) + 1
    command = next(action["name"] for action in producer["mark_actions"] if action["kind"] == "command")
    soldier = next(p for p in roster["participants"] if p["id"] == "ashmark_soldier_1")
    strike = next(name for name in soldier["actions"] if name == "Longsword")
    await combat_turn._declare_phase_impl(
        ctx,
        {
            pid: {"type": "defend"},
            source_id: {"type": "attack", "action": command, "target_id": pid},
            soldier["id"]: {"type": "attack", "action": strike, "target_id": pid},
            "ashmark_soldier_2": {"type": "defend"},
        },
    )
    import combat_marks

    original_mark = combat_marks.resolve_mark_action

    def observe_mark(state, source, target, kind, **kwargs):
        outcome = original_mark(state, source, target, kind, **kwargs)
        assert state.focus_marks[pid] == {"source_id": source_id, "kind": "command"}
        assert attack_bonus(state, state.get_participant("ashmark_soldier_1"), target) == 2
        return outcome

    with (
        patch("combat_marks.resolve_mark_action", side_effect=observe_mark) as mark,
        patch("check_resolution.dice_roll", return_value=_d20(13)),
        reference_damage(),
    ):
        result = await _resolve_round(ctx)
    mark.assert_called_once()
    assert any(p.get("kind") == "command" for p in result["packets"])
    attack = next(p for p in result["packets"] if p["actor_id"] == soldier["id"])
    assert attack["attack_total"] == 21, attack
    assert attack["damage"] > 0
    assert ctx.userdata.combat_state.focus_marks == {}
    saved = await db_mutations.load_combat_state(ctx.userdata.combat_state.combat_id)
    assert saved is not None and saved.focus_marks == {}

    import db_queries
    from ability_tools import _request_ability_activation_impl

    ctx, roster = await started("ruins_mawling_pair", player_class="rogue")
    pid = ctx.userdata.player_id
    assert "Lunge" in next(p for p in roster["participants"] if p["id"] == "mawling_1")["actions"]
    before = await db_queries.get_player(pid)
    assert before is not None
    from rules_engine import calculate_max_pools

    pools = calculate_max_pools(
        "rogue", before["level"], {k: attribute_modifier(v) for k, v in before["attributes"].items()}
    )
    assert pools.stamina is not None
    pool = await db.get_pool()
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{stamina}', $2::jsonb) WHERE player_id = $1",
        pid,
        json.dumps({"current": pools.stamina, "max": pools.stamina}),
    )
    before = await db_queries.get_player(pid)
    assert before is not None
    hp_before = ctx.userdata.combat_state.get_participant(pid).hp_current
    await combat_turn._declare_phase_impl(ctx, {"mawling_1": {"type": "attack", "action": "Lunge", "target_id": pid}})
    with patch("check_resolution.dice_roll", return_value=_d20(13)), reference_damage():
        for _ in range(16):
            raw = await combat_turn._resolve_phase_impl(ctx)
            assert isinstance(raw, str), "reaction combat must continue"
            payload = json.loads(raw)
            window = payload.get("next", {}).get("waiting_on")
            if window and window["stage"] == "post_roll":
                assert "rogue_slippery" in ctx.userdata.combat_state.get_participant(pid).reaction_ids
                with ctx.userdata._bind_authenticated_actor(pid, 1, lambda *_args: None):
                    await _request_ability_activation_impl(ctx, "rogue_slippery")
                break
        else:
            raise AssertionError("catalog Lunge never offered a post-roll reaction")
        result = await _resolve_round(ctx)
    assert any(p.get("mechanical_effect") == "grapple_escaped" for p in result["packets"])
    player = ctx.userdata.combat_state.get_participant(pid)
    assert player.hp_current < hp_before
    assert not conditions.has_condition(player.conditions, "grappled")
    after = await db_queries.get_player(pid)
    assert after is not None
    assert before["stamina"]["current"] - after["stamina"]["current"] == 3


async def assert_catalog_grapple_release(started):
    from acceptance._capstone_helpers import _d20, _resolve_round

    import combat_turn
    import conditions

    ctx, roster = await started("ruins_mawling_pair", companion="companion_kael")
    pid = ctx.userdata.player_id
    declarations = {pid: {"type": "defend"}, "companion_kael": {"type": "defend"}}
    for source, target in [("mawling_1", pid), ("mawling_2", "companion_kael")]:
        produced = next(p for p in roster["participants"] if p["id"] == source)
        name = next(name for name in produced["actions"] if name == "Lunge")
        declarations[source] = {"type": "attack", "action": name, "target_id": target}
    await combat_turn._declare_phase_impl(ctx, declarations)
    with patch("check_resolution.dice_roll", return_value=_d20(20)), reference_damage():
        await _resolve_round(ctx)
    state = ctx.userdata.combat_state
    for source, target in [("mawling_1", pid), ("mawling_2", "companion_kael")]:
        condition = next(c for c in state.get_participant(target).conditions if c["type"] == "grappled")
        assert condition["source"] == source
        assert next(a for a in state.get_participant(source).action_pool if a["name"] == "Lunge")["escape_dc"] == 13
    state.get_participant("mawling_1").hp_current = 1
    actor = state.get_participant(pid)
    await combat_turn._declare_phase_impl(
        ctx,
        {
            pid: {"type": "attack", "action": actor.action_pool[0]["name"], "target_id": "mawling_1"},
            "companion_kael": {"type": "defend"},
            "mawling_1": {"type": "defend"},
            "mawling_2": {"type": "defend"},
        },
    )
    with patch("check_resolution.dice_roll", return_value=_d20(20)), reference_damage():
        result = await _resolve_round(ctx)
    packet = next(p for p in result["packets"] if p["actor_id"] == pid)
    assert packet["target_fallen"] is True
    assert packet["released_from_grapple"] == [pid], "catalog_grapple_release"
    saved = await db_mutations.load_combat_state(state.combat_id)
    assert saved is not None and saved.to_dict() == ctx.userdata.combat_state.to_dict()
    player, ally = saved.get_participant(pid), saved.get_participant("companion_kael")
    assert player is not None and ally is not None
    assert not conditions.has_condition(player.conditions, "grappled")
    assert next(c for c in ally.conditions if c["type"] == "grappled")["source"] == "mawling_2"
