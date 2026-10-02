"""Catalog entry and strength inputs on Postgres; constant-d20 outcomes are reference diagnostics, not win rates."""

import json
import math
import random
from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from acceptance._capstone_helpers import _d20, _resolve_round
from acceptance._catalog_cutover_helpers import (
    TARGETS,
    TEMPLATES,
    assert_boundary_result,
    assert_stats,
    reference_damage,
)
from acceptance._catalog_cutover_helpers import cold_catalog_reads as cold_catalog_reads
from acceptance._catalog_cutover_helpers import started as started
from acceptance.seeds import seed_player
from livekit.agents.llm import ToolError
from sample_fixtures import CONTENT_ROOT, make_context, make_mock_room

import combat_init
import combat_turn
import db
import db_mutations
import event_types as E
from companion_profiles import get_companion_profile
from creation_rules import build_character_data
from creature_catalog import query_creature_by_id
from creature_combat import translate_creature
from encounter_budget import calculate_encounter_budget
from hp_scaling import calculate_max_hp
from rules_engine import attribute_modifier
from session_data import CombatState


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda row: row["id"])
async def test_every_encounter_starts_from_catalog(started, template, cold_catalog_reads, mock_combat_agent_factory):
    import db_content_queries

    pool = await db.get_pool()
    assert await pool.fetchval("SELECT count(*) FROM encounter_templates") == 10
    assert template == await db_content_queries.get_encounter_template(template["id"])
    ctx, response = await started(template["id"])
    state = ctx.userdata.combat_state
    saved = await db_mutations.load_combat_state(state.combat_id)
    assert saved is not None
    assert saved.to_dict() == state.to_dict()
    assert cold_catalog_reads.await_count == len(template["enemies"])
    handoff = mock_combat_agent_factory.call_args.kwargs["chat_ctx"]
    assert any(
        json.dumps(response["participants"]) in text
        for item in handoff.items
        for text in item.content
        if isinstance(text, str)
    )
    roster = {p["id"]: p for p in response["participants"]}
    events = [json.loads(c.args[0]) for c in ctx.userdata.room.local_participant.publish_data.call_args_list]
    hud = next(event for event in events if event["type"] == E.COMBAT_UI_UPDATE)
    assert len([p for p in state.participants if p.type == "enemy"]) == len(template["enemies"])
    for ref in template["enemies"]:
        row = await query_creature_by_id(ref["creature_id"])
        enemy = saved.get_participant(ref["id"])
        assert enemy is not None
        assert_stats(enemy, row, ref["role"])
        expected = translate_creature(row, encounter_id=template["id"], enemy_id=ref["id"], role=ref["role"])
        for field in (
            "action_pool",
            "attributes",
            "saving_throw_proficiencies",
            "category",
            "signature_ability",
            "legendary_actions",
            "catalog_audio",
            "catalog_narration",
            "deferred_effects",
        ):
            assert getattr(enemy, field) == expected[field]
        assert enemy.creature_id == ref["creature_id"]
        assert roster[enemy.id]["name"] == row["name"]
        assert roster[enemy.id]["actions"] == [a["name"] for a in enemy.action_pool]
        view = next(p for p in hud["combatants"] if p["id"] == enemy.id)
        assert view["hpMax"] == enemy.hp_max
        assert view["hpCurrent"] == enemy.hp_current
        assert view["name"] == enemy.name
        for field in ("ac", "creature_id", "catalog_audio", "catalog_narration", "deferred_effects"):
            assert roster[enemy.id][field] == getattr(enemy, field)


async def test_catalog_changes_affect_next_start_not_saved_combat(started):
    pool = await db.get_pool()
    original = await query_creature_by_id("hollow_wisp")
    first, _ = await started("hollow_wisp")
    before = first.userdata.combat_state.to_dict()
    changed = deepcopy(original)
    changed["hp"] += 5
    changed["attacks"][0]["to_hit"] += 2
    changed["loot_table_id"] = "loot_hollow_drift"
    try:
        await pool.execute("UPDATE creatures SET data = $2::jsonb WHERE id = $1", original["id"], json.dumps(changed))
        second, _ = await started("hollow_wisp")
        enemy = next(p for p in second.userdata.combat_state.participants if p.type == "enemy")
        assert enemy.hp_max == changed["hp"]
        assert enemy.action_pool[0]["to_hit"] == changed["attacks"][0]["to_hit"]
        assert enemy.loot_table_id == changed["loot_table_id"]
        snapshot = await db_mutations.load_combat_state(before["combat_id"])
        assert snapshot is not None
        assert snapshot.to_dict() == before
        await pool.execute("DELETE FROM creatures WHERE id = $1", original["id"])
        snapshot = await db_mutations.load_combat_state(before["combat_id"])
        assert snapshot is not None
        assert snapshot.to_dict() == before
        assert CombatState.from_dict(before).to_dict() == before
    finally:
        await pool.execute(
            "INSERT INTO creatures (id, data) VALUES ($1, $2::jsonb) ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data",
            original["id"],
            json.dumps(original),
        )


async def test_missing_catalog_row_has_no_side_effects(reset_db_pool, monkeypatch, mock_combat_agent_factory):
    pool = await db.get_pool()
    pid = f"missing_{uuid4().hex}"
    await seed_player(pool, player_id=pid)
    original = await query_creature_by_id("hollow_wisp")
    ctx = make_context(pid, room=make_mock_room())
    baseline = await pool.fetchval("SELECT count(*) FROM combat_instances")
    initiative = MagicMock(wraps=combat_init.combat_resolution.roll_initiative)
    monkeypatch.setattr(combat_init.combat_resolution, "roll_initiative", initiative)
    try:
        await pool.execute("DELETE FROM creatures WHERE id = $1", original["id"])
        with pytest.raises(ToolError, match="hollow_wisp"):
            await combat_init._start_combat_impl(ctx, "hollow_wisp", "missing")
        assert await pool.fetchval("SELECT count(*) FROM combat_instances") == baseline
        initiative.assert_not_called()
        mock_combat_agent_factory.assert_not_called()
        ctx.userdata.room.local_participant.publish_data.assert_not_called()
        assert ctx.userdata.combat_state is None and not ctx.userdata.in_combat
    finally:
        await pool.execute(
            "INSERT INTO creatures (id, data) VALUES ($1, $2::jsonb)", original["id"], json.dumps(original)
        )
        await pool.execute("DELETE FROM players WHERE player_id = $1", pid)


def assert_strength(template, catalog):
    level = template["recommended_party_level"]
    report = calculate_encounter_budget(template["enemies"], level)
    assert not report["too_many_bosses"], "too_many_bosses"
    assert not report["all_minion"], "all_minion"
    ceiling = (
        "standard"
        if template["difficulty"] != "hard"
        else "boss"
        if any(r["role"] == "boss" for r in template["enemies"])
        else "tough"
    )
    assert report["total"] <= report["thresholds"][ceiling], "difficulty budget"
    max_tier = 1 if level <= 2 else 2 if level <= 8 else 3 if level <= 14 else 4
    assert all(catalog[r["creature_id"]]["tier"] <= max_tier for r in template["enemies"]), "tier ceiling"


def test_final_balance_table():
    catalog = {row["id"]: row for row in json.loads((CONTENT_ROOT / "content/creatures.json").read_text())}
    assert {row["id"] for row in TEMPLATES} == set(TARGETS)
    assert sum(len(row["enemies"]) for row in TEMPLATES) == 26
    assert len({ref["creature_id"] for row in TEMPLATES for ref in row["enemies"]}) == 13
    for row in TEMPLATES:
        level, difficulty, groups = TARGETS[row["id"]]
        assert (row["recommended_party_level"], row["difficulty"]) == (level, difficulty)
        assert Counter((r["creature_id"], r["role"]) for r in row["enemies"]) == Counter(
            {(species, role): count for species, role, count in groups}
        )
        assert_strength(row, catalog)
    for name, change, diagnostic in [
        (
            "cult_cell",
            lambda r: r["enemies"].append({"id": "extra", "creature_id": "cult_leader", "role": "boss"}),
            "too_many_bosses",
        ),
        (
            "hollow_wisp",
            lambda r: r["enemies"].extend(
                [
                    {"id": "extra1", "creature_id": "hollow_wisp", "role": "elite"},
                    {"id": "extra2", "creature_id": "hollow_wisp", "role": "elite"},
                ]
            ),
            "difficulty budget",
        ),
        ("shadeling_cluster", lambda r: [e.update(role="minion") for e in r["enemies"]], "all_minion"),
        ("hollow_wisp", lambda r: r["enemies"][0].update(creature_id="hollow_knight"), "tier ceiling"),
    ]:
        row = deepcopy(next(t for t in TEMPLATES if t["id"] == name))
        change(row)
        with pytest.raises(AssertionError, match=diagnostic):
            assert_strength(row, catalog)


async def test_fresh_seed_uses_the_runtime_database(fresh_migrated_db, monkeypatch):
    import asyncpg
    from test_seed_encounter_references import seed_content

    await db.close_all()
    monkeypatch.setenv("DATABASE_URL", fresh_migrated_db)
    conn = await asyncpg.connect(fresh_migrated_db)
    try:
        assert await conn.fetchval("SELECT count(*) FROM creatures") == 0
        counts = await seed_content.seed(conn)
        assert counts["encounter_templates"] == 10
        assert await seed_content.validate(conn) == []
        await seed_player(conn, player_id="fresh_catalog")
        pool = await db.get_pool()
        assert await pool.fetchval("SELECT current_database()") == await conn.fetchval("SELECT current_database()")
        assert await pool.fetchval("SELECT pg_postmaster_start_time()") == await conn.fetchval(
            "SELECT pg_postmaster_start_time()"
        )
        ctx = make_context("fresh_catalog", room=make_mock_room())
        await combat_init._start_combat_impl(ctx, "hollow_wisp", "fresh catalog")
        assert next(p for p in ctx.userdata.combat_state.participants if p.type == "enemy").creature_id == "hollow_wisp"
    finally:
        await db.close_all()
        await conn.close()


@pytest.mark.parametrize("companion", ["companion_kael", "companion_lira", "companion_tam", "companion_sable"])
@pytest.mark.parametrize(
    "encounter_id", ["shadeling_cluster", "hollow_wisp", "bandit_ambush", "cult_cell", "hollow_corrupted_settlement"]
)
async def test_actual_companion_boundary_combat(started, companion, encounter_id):
    ctx, roster = await started(encounter_id, companion=companion)
    state = ctx.userdata.combat_state
    player = state.get_participant(ctx.userdata.player_id)
    ally = state.get_participant(companion)
    profile = get_companion_profile(companion)
    assert ally and ally.type == "companion"
    assert ally.hp_max == math.floor(player.hp_max * profile.scaling_rules.hp_factor)
    assert profile.scaling_rules.hp_factor == (0.5 if companion == "companion_sable" else 0.75)
    assert ally.action_pool and any(p["id"] == companion for p in roster["participants"])
    enemies = [p for p in state.participants if p.type == "enemy"]
    selected = enemies[0]
    producer = {p["id"]: p for p in roster["participants"]}
    declarations = {
        player.id: {"type": "attack", "action": player.action_pool[0]["name"], "target_id": selected.id},
        companion: {"type": "attack", "action": ally.action_pool[0]["name"], "target_id": selected.id},
    }
    for enemy in enemies:
        declarations[enemy.id] = {"type": "attack", "action": producer[enemy.id]["actions"][0], "target_id": player.id}
    # Optional reactions are declined by the deterministic drain, never removed from profiles.
    await combat_turn._declare_phase_impl(ctx, declarations)
    import db_queries

    original_player = await db_queries.get_player(player.id)
    assert original_player is not None
    xp_before = original_player["xp"]
    with patch("check_resolution.dice_roll", return_value=_d20(13)), reference_damage():
        result = await _resolve_round(ctx)
    await assert_boundary_result(ctx, result, state.combat_id, companion, xp_before)
    if ctx.userdata.combat_state:
        saved = await db_mutations.load_combat_state(state.combat_id)
        assert saved is not None
        struck = saved.get_participant(selected.id)
        assert struck is not None
        assert struck.hp_current < selected.hp_max


@pytest.mark.parametrize(
    "encounter_id,level",
    [
        ("shadeling_cluster", 1),
        ("hollow_wisp", 2),
        ("bandit_ambush", 5),
        ("cult_cell", 8),
        ("hollow_corrupted_settlement", 14),
    ],
)
async def test_absent_companion_boundary(started, encounter_id, level):
    ctx, _ = await started(encounter_id, level=level)
    assert not any(p.type == "companion" for p in ctx.userdata.combat_state.participants)
    assert ctx.userdata.combat_state.get_participant(ctx.userdata.player_id).hp_max == calculate_max_hp(
        "warrior",
        level,
        attribute_modifier(
            build_character_data(
                "Reference", "draethar", "warrior", None, "", created_at=datetime(2026, 10, 1, tzinfo=UTC)
            )["attributes"]["constitution"]
        ),
    )


async def test_catalog_declarations_execute(started):
    from acceptance._catalog_cutover_helpers import assert_catalog_effects

    await assert_catalog_effects(started)


async def test_ashmark_stance_and_quest_identity(started):
    import db_mutations_reputation
    import db_queries
    from quest_tools import _update_quest_impl

    hostile, _ = await started("ashmark_patrol")
    assert (
        next(p for p in hostile.userdata.combat_state.participants if p.id == "ashmark_sergeant").creature_id
        == "ashmark_sergeant"
    )
    pid = hostile.userdata.player_id
    await db_mutations_reputation.adjust_player_faction_reputation(pid, "thornwatch", 5, "cutover")
    allied = make_context(pid, room=make_mock_room())
    result = await combat_init._start_combat_impl(allied, "ashmark_patrol", "allied")
    assert isinstance(result, str) and "stands down" in result
    assert allied.userdata.combat_state is None
    pool = await db.get_pool()
    quests = json.loads((CONTENT_ROOT / "content/quests.json").read_text())
    quest = next(q for q in quests if q["id"] == "greyvale_anomaly")
    index = next(
        i
        for i, stage in enumerate(quest["stages"])
        if stage.get("completion_conditions", {}).get("encounter") == "hollow_patrol_greyvale"
    )
    from acceptance._catalog_cutover_helpers import complete_reference_combat

    victorious, _ = await started(quest["stages"][index]["completion_conditions"]["encounter"], level=14)
    await complete_reference_combat(victorious)
    pid = victorious.userdata.player_id
    before = await db_queries.get_player(pid)
    assert before is not None
    await db_mutations.set_player_quest(pid, quest["id"], {"current_stage": index, "status": "active"}, conn=pool)
    result = json.loads(await _update_quest_impl(victorious, quest["id"], index + 1))
    assert result["quest_id"] == quest["id"]
    advanced = await db_queries.get_player_quest(pid, quest["id"])
    assert advanced is not None
    assert advanced["current_stage"] == index + 1
    rewarded = await db_queries.get_player(pid)
    assert rewarded is not None
    assert rewarded["xp"] - before["xp"] == quest["stages"][index]["on_complete"]["xp"]
    inventory = await db_queries.get_player_inventory(pid)
    assert any(item["id"] == "hollow_bone_fragment" for item in inventory)


@pytest.mark.parametrize("companion", ["companion_kael", "companion_lira", "companion_tam", "companion_sable"])
@pytest.mark.parametrize("encounter_id", ["shadeling_cluster", "hollow_wisp", "hollow_corrupted_settlement"])
async def test_actual_companion_committed_outcome(started, companion, encounter_id):

    import db_queries
    import dice

    ctx, _ = await started(encounter_id, companion=companion)
    combat_id = ctx.userdata.combat_state.combat_id
    damage_rng = random.Random(138)
    outcome = None
    rounds = 0
    with (
        patch("check_resolution.dice_roll", return_value=_d20(13)),
        patch(
            "check_resolution_attack.dice_roll",
            side_effect=lambda notation, **kwargs: dice.roll(notation, rng=damage_rng),
        ),
    ):
        for rounds in range(1, 31):
            state = ctx.userdata.combat_state
            player = state.get_participant(ctx.userdata.player_id)
            ally = state.get_participant(companion)
            enemies = [p for p in state.participants if p.type == "enemy" and not p.is_fallen]
            target = min(enemies, key=lambda p: p.hp_current)
            declarations = {}
            for actor in (player, ally):
                if not actor.is_fallen:
                    declarations[actor.id] = {
                        "type": "attack",
                        "action": actor.action_pool[0]["name"],
                        "target_id": target.id,
                    }
            for enemy in enemies:
                declarations[enemy.id] = {
                    "type": "attack",
                    "action": enemy.action_pool[0]["name"],
                    "target_id": player.id,
                }
            await combat_turn._declare_phase_impl(ctx, declarations)
            result = await _resolve_round(ctx)
            if ctx.userdata.combat_state:
                live = ctx.userdata.combat_state
                bearer = live.get_participant(player.id)
                if bearer.is_fallen:
                    remaining = [
                        (p.id, p.hp_current, p.hp_max)
                        for p in live.participants
                        if p.type == "enemy" and not p.is_fallen
                    ]
                    pytest.fail(
                        f"unsafe target: {encounter_id} {companion} level={player.level} round={rounds} player_hp={bearer.hp_current}/{bearer.hp_max}, remaining={remaining}"
                    )
            if isinstance(result, tuple):
                outcome = json.loads(result[1])
                break
    assert outcome is not None, "bounded ordinary combat did not reach a committed outcome"
    assert ctx.userdata.combat_state is None
    assert await db_mutations.load_combat_state(combat_id) is None
    print(f"strength outcome: {encounter_id} {companion} rounds={rounds} outcome={outcome['outcome']}")
    assert outcome["outcome"] == "victory", "unsafe authored target in the bounded ordinary combat"
    assert outcome["xp_total"] > 0
    rewarded = await db_queries.get_player(ctx.userdata.player_id)
    assert rewarded is not None
    assert rewarded["xp"] > 0


@pytest.mark.parametrize(
    "encounter_id,level,points",
    [("shadeling_cluster", 1, 0), ("cult_cell", 8, 4), ("hollow_corrupted_settlement", 14, 6)],
)
async def test_strength_fixture_uses_created_warrior_and_level_grants(started, encounter_id, level, points):
    import db_queries

    expected = build_character_data(
        "Strength reference", "draethar", "warrior", None, "", created_at=datetime(2026, 10, 1, tzinfo=UTC)
    )
    ctx, _ = await started(encounter_id)
    player = await db_queries.get_player(ctx.userdata.player_id)
    assert player is not None
    for field in ("attributes", "equipment", "saving_throw_proficiencies"):
        assert player[field] == expected[field]
    assert player["level"] == level
    assert player["hp"]["max"] == calculate_max_hp(
        "warrior", level, attribute_modifier(expected["attributes"]["constitution"])
    )
    award = next(payload for kind, payload in ctx.strength_events if kind == E.XP_AWARDED)
    assert award["attribute_points"] == points
    actor = ctx.userdata.combat_state.get_participant(ctx.userdata.player_id)
    assert bool(player.get("flags", {}).get("extra_attack")) == (level >= 10)
    assert ("extra_attack" in actor.enhancers) == (level >= 10)
    if level >= 10:
        enemy = next(p for p in ctx.userdata.combat_state.participants if p.type == "enemy")
        await combat_turn._declare_phase_impl(
            ctx, {actor.id: {"type": "attack", "action": actor.action_pool[0]["name"], "target_id": enemy.id}}
        )
        with patch("check_resolution.dice_roll", return_value=_d20(13)), reference_damage():
            result = await _resolve_round(ctx)
        packet = next(packet for packet in result["packets"] if packet["actor_id"] == actor.id)
        assert len(packet["attacks"]) == 2
