"""The level-20 reference party beats the shipped Architect on at least twelve seeds."""

import json
from statistics import median
from unittest.mock import AsyncMock

from architect_reference_party import ELECTIVE_PICKS
from asyncpg import Pool
from first_blood_harness import (
    ARCHETYPES,
    ARCHITECT_WORKS,
    TechniqueReport,
    architect_party,
    architect_techniques,
    drive_architect_fight,
)
from livekit.agents import RunContext
from sample_fixtures import CONTENT_ROOT

import architect_scene
import character_spells
import db
import db_content_queries
import db_queries
from architect_encounter import CREATURE_ID
from creature_catalog import query_creature_by_id
from mode_tools import enter_mode
from patron_passives import effective_hp
from session_data import SessionData

SEEDS = tuple(range(20))


async def test_architect_balance(reset_db_pool, monkeypatch):
    pool = await db.get_pool()
    monkeypatch.setattr(db, "_cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr(db, "_cache_set", AsyncMock())
    templates = json.loads((CONTENT_ROOT / "content/encounter_templates.json").read_text())
    creatures = json.loads((CONTENT_ROOT / "content/creatures.json").read_text())
    template = next(row for row in templates if row["id"] == CREATURE_ID)
    creature = next(row for row in creatures if row["id"] == CREATURE_ID)
    assert await db_content_queries.get_encounter_template(CREATURE_ID) == template
    assert await query_creature_by_id(CREATURE_ID) == creature
    assert template["recommended_party_level"] == 20
    assert template["enemies"] == [{"id": "architect", "creature_id": CREATURE_ID, "role": "named"}]

    print(f"Architect techniques tracked: {', '.join(sorted(architect_techniques()))}", flush=True)
    assert {key: set(picks) for key, picks in ELECTIVE_PICKS.items()} == {"warrior": {4, 8}, "rogue": {4, 8}}
    results = {}
    held = set()
    resolved = set()
    for seed in SEEDS:
        assert seed not in results, f"Duplicate Architect seed {seed}"
        outcome, rounds, techniques = await reference_fight(pool, seed, creature)
        results[seed] = outcome, rounds
        print(f"Architect seed {seed:2}: {outcome}, {rounds} rounds, {json.dumps(techniques)}", flush=True)
        for archetype, picks in ELECTIVE_PICKS.items():
            assert set(techniques[archetype]["held"]) == set(picks.values())
        for archetype, report in techniques.items():
            assert set(report["resolved"]) <= set(report["declared"]) <= set(report["held"]), (seed, archetype, report)
            held.update((archetype, technique) for technique in report["held"])
            resolved.update((archetype, technique) for technique in report["resolved"])
    assert tuple(results) == tuple(range(20))
    wins = sum(outcome == "victory" for outcome, _ in results.values())
    rounds = [count for _, count in results.values()]
    print(
        f"Architect {creature['hp']} HP: {wins}/20 wins, median {median(rounds):g} rounds, max {max(rounds)}",
        flush=True,
    )
    assert held <= resolved, f"Held techniques never resolved: {held - resolved}"
    assert 12 <= wins <= 20, results


async def reference_fight(pool: Pool, seed: int, creature: dict) -> tuple[str, int, dict[str, TechniqueReport]]:
    async with architect_party(pool, seed) as (ctx, loadouts):
        player_ids = tuple(loadouts)
        for archetype, player_id in zip(ARCHETYPES, player_ids, strict=True):
            if archetype in ELECTIVE_PICKS:
                assert loadouts[player_id] == tuple(ELECTIVE_PICKS[archetype][tier] for tier in (4, 8))
        await enter_reference(ctx, player_ids, creature)
        outcome, rounds, report = await drive_architect_fight(ctx, loadouts, seed)
        techniques: dict[str, TechniqueReport] = dict(zip(ARCHETYPES, (report[pid] for pid in player_ids), strict=True))
        if outcome == "victory":
            row = await db_queries.get_player(player_ids[0])
            scene = architect_scene.read(row, ARCHITECT_WORKS)
            assert scene is not None and scene["status"] == "destroyed", (seed, scene)
    for player_id in player_ids:
        assert await db_queries.get_player(player_id) is None, seed
    return outcome, rounds, techniques


async def enter_reference(ctx: RunContext[SessionData], player_ids: tuple[str, ...], creature: dict) -> None:
    assert isinstance(await enter_mode(ctx, "combat", CREATURE_ID, "Balance reference"), tuple)
    state = ctx.userdata.combat_state
    assert state is not None
    assert (state.location_id, state.encounter_id) == (ARCHITECT_WORKS, CREATURE_ID)
    players = {actor.id: actor for actor in state.participants if actor.type == "player"}
    assert set(players) == set(player_ids)
    assert not any(actor.type == "companion" for actor in state.participants)
    for archetype, player_id in zip(ARCHETYPES, player_ids, strict=True):
        actor = players[player_id]
        row = await db_queries.get_player(player_id)
        assert row is not None
        assert (actor.archetype_id, row["class"], actor.level, row["level"]) == (archetype, archetype, 20, 20)
        assert actor.hp_current == actor.hp_max == effective_hp(row)["max"]
        assert (actor.attributes, actor.ac, actor.action_pool) == (
            row["attributes"],
            row["ac"],
            [row["equipment"]["main_hand"]],
        )
        for name in ("stamina", "focus"):
            if name in row:
                assert row[name]["current"] == row[name]["max"]
        assert row["divine_favor"]["patron"] != "none"
        assert len(await character_spells.get_prepared(player_id)) == {"mage": 16, "cleric": 13}.get(archetype, 0)

    encounter = state.architect_encounter
    assert encounter is not None
    owner = state.get_participant(encounter["owner_id"])
    assert owner is not None
    assert (owner.creature_id, owner.role, owner.hp_max) == (CREATURE_ID, "named", creature["hp"])
    assert state.spatial is not None
    assert len(encounter["structure_ids"]) == 2
    assert set(encounter["structure_ids"]) == set(state.spatial["structures"])
