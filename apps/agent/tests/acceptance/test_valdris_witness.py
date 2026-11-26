"""Witness Shield through real discovery, entry and registered combat commands."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from acceptance._enemy_opportunity_helpers import attack, declare, move
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import pos
from test_encounter_facts_damage import dice
from voice_condition_fixtures import participant

import db_queries
from combat_agent import CombatAgent, create_combat_agent
from combat_spatial import require_spatial
from combat_state import CombatState

CLAUSE = "valdris_witness_shield"
ACCUSED = "cultist_1"
TESTIMONY = {
    "witness": {"id": "elder_yanna", "name": "Elder Yanna"},
    "accused": [{"id": "cult_leader", "name": "Cult Leader"}, {"id": ACCUSED, "name": "Cultist"}],
}


@asynccontextmanager
async def entered(
    *, location: str = "millhaven", patron: str = "valdris", archetype: str = "guardian"
) -> AsyncIterator[tuple[MawlingHarness, dict, str]]:
    h = MawlingHarness()
    try:
        await h.prepare((8,), companion=None, location=location)
        await h.pool.execute(
            "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
            h.players[0],
            json.dumps({"class": archetype, "divine_favor": {"patron": patron, "level": 20, "max": 100}}),
        )
        discovery = await h.command("query_info", {"kind": "creature"})
        [entry] = [template for template in discovery["encounter_templates"] if template["id"] == "cult_cell"]
        with patch("combat_agent.create_combat_agent", wraps=create_combat_agent) as factory:
            receipt = await h.command("enter_mode", {"mode": "combat", "encounter_id": entry["id"]})
        assert isinstance(h.session.current_agent, CombatAgent)
        (message,) = factory.call_args.kwargs["chat_ctx"].items
        h.enemies = [p["id"] for p in receipt["participants"] if p["type"] == "enemy"]
        yield h, receipt, message.content[0]
    finally:
        await h.close()


async def strike(h: MawlingHarness, bonus: int, *, enemy: str = ACCUSED, opportunity: bool = False) -> None:
    state = h.sd.combat_state
    assert state is not None
    hero = participant(state, h.players[0])
    cultist = participant(state, enemy)
    positions = require_spatial(state)["positions"]
    positions[hero.id], positions[enemy] = pos(0), pos(5)
    for other in h.enemies:
        if other != enemy:
            positions[other] = pos(-25)
    await h.persist()
    hp = hero.hp_current
    if opportunity:
        await declare(h, move(hero.id, 20))
    else:
        await declare(h, move(hero.id, 0), attack(enemy, hero.id, "Ritual Dagger"))
    dagger = next(action for action in cultist.action_pool if action["name"] == "Ritual Dagger")
    face = hero.ac - dagger["to_hit"]
    assert 1 < face < 20
    with dice(face):
        packets = await h.drain()
    strikes = [packet for packet in packets if packet.get("actor_id") == enemy and "attack_total" in packet]
    assert len(strikes) == 1, packets
    [packet] = strikes
    assert bool(packet.get("opportunity_attack")) is opportunity
    assert (packet["attack_total"], packet["target_ac"], packet["hit"]) == (hero.ac, hero.ac + bonus, not bonus)
    assert (packet["valdris_ac_bonus"], packet.get("valdris_ac_clause_id")) == (bonus, CLAUSE if bonus else None)
    assert (packet["damage"] == 0) is bool(bonus)
    saved = participant(await h.reload(), hero.id)
    row = await db_queries.get_player(hero.id, conn=h.pool)
    assert row is not None
    assert (saved.ac, saved.hp_current, row["hp"]["current"]) == (hero.ac, hp - packet["damage"], hp - packet["damage"])


async def witness_shield(_world: SimpleNamespace | None = None) -> None:
    async with entered() as (h, receipt, context):
        profile = (await h.command("query_info", {"kind": "patron"}))["synergy"]
        await strike(h, 1)
        persisted = await h.reload()
        checkpoint = persisted.round_checkpoints[-1]["combat"]
        h.sd.combat_state = CombatState.from_dict({**checkpoint, "round_checkpoints": persisted.round_checkpoints})
        await strike(h, 1, opportunity=True)
        assert receipt["testimony"] == TESTIMONY
        assert json.dumps(TESTIMONY) in context
        state = await h.reload()
        witness_id = TESTIMONY["witness"]["id"]
        assert witness_id not in {p.id for p in state.participants}
        assert witness_id not in state.initiative_order
        assert witness_id not in require_spatial(state)["positions"]
        assert profile["name"] == "Witness Shield"
        assert [(c["status"], c["implementation_id"]) for c in profile["clauses"]] == [("active", CLAUSE)]


SCENARIOS = {CLAUSE: ("patron_synergy_combat:witness_defense", witness_shield, [()])}


async def test_witness_shield(reset_db_pool: str) -> None:
    await witness_shield()


@pytest.mark.parametrize(
    "options,enemy",
    [
        pytest.param({}, "cultist_2", id="not-accused"),
        pytest.param({"location": "millhaven_inn"}, ACCUSED, id="witness-elsewhere"),
        pytest.param({"patron": "kaelen"}, ACCUSED, id="other-patron"),
        pytest.param({"archetype": "warrior"}, ACCUSED, id="other-archetype"),
    ],
)
async def test_witness_shield_eligibility(reset_db_pool: str, options: dict, enemy: str) -> None:
    async with entered(**options) as (h, _, _):
        await strike(h, 0, enemy=enemy)
