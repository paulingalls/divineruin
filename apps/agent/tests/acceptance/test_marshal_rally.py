"""Marshal Rally at the registered combat boundary."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from _zhael_fate_fixtures import game_tools
from _zhael_marshal_rally_fixtures import bonus
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_martial_core_kit import enter, weapon_attack
from acceptance.test_self_buff_electives import defend, discovered, receipt
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_war_cry import point
from sample_fixtures import published_payloads
from test_aelora_gift import _live_party
from voice_condition_fixtures import participant

import abilities
import combat_spatial
import db_mutations
import db_queries
from activate_tools import activate
from combat_agent import create_combat_agent
from combat_turn import declare_phase
from rest_tools import rest

RALLY = "marshal_rally"


@asynccontextmanager
async def prepared(patron: str = "none") -> AsyncIterator[MawlingHarness]:
    walk = MawlingHarness()
    try:
        await walk.prepare((3, 3, 3), location="accord_guild_hall", tools=(activate, declare_phase))
        await walk.pool.execute(
            """UPDATE players SET data = data || '{"class":"marshal"}' ||
               jsonb_build_object('attributes', data->'attributes' || '{"charisma":14}')
               WHERE player_id = $1""",
            walk.players[0],
        )
        await set_favor(walk, walk.players[0], patron)
        yield walk
    finally:
        await walk.close()


@pytest.fixture
async def fight(reset_db_pool: str) -> AsyncIterator[MawlingHarness]:
    async with prepared() as walk:
        yield walk


async def set_favor(walk: MawlingHarness, pid: str, patron: str) -> None:
    await walk.pool.execute(
        "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
        pid,
        json.dumps({"divine_favor": {"patron": patron, "level": 40 if patron != "none" else 0, "max": 100}}),
    )


async def enter_fight(walk: MawlingHarness) -> None:
    await enter(walk)
    state = await walk.reload()
    for index, combatant in enumerate(state.participants):
        combatant.initiative = 100 - index
        combat_spatial.place(state, combatant.id, point(5 * index))
    await walk.persist()


def rally(actor: str, action: str = RALLY) -> dict:
    return {"kind": "ability", "actor_id": actor, "action": action, "targets": [], "argument_type": "", "reshape": []}


async def declare_round(walk: MawlingHarness, *actions: dict, error: bool = False) -> dict | str:
    by_actor = {action["actor_id"]: action for action in actions}
    state = await walk.reload()
    return await walk.command(
        "declare_phase",
        {"declarations": [by_actor.get(p.id, defend(p.id)) for p in state.participants if not p.is_fallen]},
        error=error,
    )


async def player(player_id: str) -> dict:
    row = await db_queries.get_player(player_id)
    assert row is not None
    return row


async def cast_rally(walk: MawlingHarness, action: str = RALLY) -> dict:
    marshal = walk.players[0]
    await declare_round(walk, rally(marshal, action))
    return receipt(await walk.drain(), marshal)


async def test_discovered_rally_pays_focus_and_persists_each_recipient(fight: MawlingHarness) -> None:
    marshal, *allies = fight.players
    await set_favor(fight, allies[0], "orenthel")
    await fight.pool.execute(
        "UPDATE players SET data = data || $2::jsonb WHERE player_id = $1", allies[0], json.dumps({"class": "marshal"})
    )
    await enter_fight(fight)
    ability = await discovered(fight, RALLY)
    assert ability["declaration"] == {"kind": "ability", "targets": []}
    before = await player(marshal)
    previous_events = len(published_payloads(fight.sd.room))
    result = await cast_rally(fight, ability["id"])
    authored = abilities.get_ability(RALLY)
    assert (result["effect"], result["narration_cue"]) == (authored.effect, authored.narration_cue)
    assert result["effect_resolution"] == "engine"
    assert result["deducted"] == {"focus": 3, "stamina": 0}
    outcomes = {row["recipient_id"]: row for row in result["rally_results"]}
    state = await fight.reload()
    companion = next(p for p in state.participants if p.type == "companion")
    assert set(result["target_ids"]) == {*allies, companion.id}
    for ally in allies:
        assert (outcomes[ally]["amount"], outcomes[ally]["granted"]) == (5, 5)
        assert (await player(ally))["temp_hp"] == participant(state, ally).temp_hp == 5
    after = await player(marshal)
    assert after["focus"]["current"] == before["focus"]["current"] - 3
    assert after["hp"] == before["hp"]
    assert after.get("temp_hp", 0) == participant(state, marshal).temp_hp == 0
    events = published_payloads(fight.sd.room)[previous_events:]
    update = next(event for event in reversed(events) if event["type"] == "combat_ui_update")
    assert {p["id"]: p["tempHp"] for p in update["combatants"]} == {p.id: p.temp_hp for p in state.participants}


async def rally_at_dawn(_world: SimpleNamespace) -> None:
    with patch("combat_agent.create_combat_agent", wraps=create_combat_agent):
        await exercise_rally_at_dawn()


async def exercise_rally_at_dawn() -> None:
    async with prepared("orenthel") as fight:
        marshal, *allies = fight.players
        await enter_fight(fight)
        corpus_path = Path(__file__).resolve().parents[4] / "packages/shared/fixtures/god_profiles.json"
        corpus = json.loads(corpus_path.read_text())["rally_at_dawn"]
        profile = (await fight.command("query_info", {"kind": "patron"}))["synergy"]
        assert profile["name"] == corpus["name"] and profile["type"] == corpus["type"]
        for key, value in corpus["clauses"][0].items():
            assert profile["clauses"][0][key] == value
        before = {pid: await player(pid) for pid in fight.players}
        result = await cast_rally(fight)
        assert {r["granted"] for r in result["rally_results"]} == {6}
        assert result["synergy_clause_id"] == "orenthel_marshal_rally"
        assert result["synergy_clause_name"] == corpus["name"]
        state = await fight.reload()
        for ally in allies:
            after = await player(ally)
            assert after["temp_hp"] == participant(state, ally).temp_hp == 6
            assert after["hp"] == before[ally]["hp"]
        assert (await player(marshal))["focus"]["current"] == before[marshal]["focus"]["current"] - 3


SCENARIOS = {"orenthel_marshal_rally": ("patron_synergy_combat:marshal_rally_bonus", rally_at_dawn, [()])}


async def test_companion_absorbs_rally_pool_and_overflow(fight: MawlingHarness) -> None:
    await enter_fight(fight)
    state = await fight.reload()
    companion = next(p for p in state.participants if p.type == "companion")
    foe = participant(state, "mawling_1")
    combat_spatial.place(state, foe.id, combat_spatial.position(state.spatial, companion.id))
    companion.hp_current = 3
    await fight.persist()
    result = await cast_rally(fight)
    assert next(r for r in result["rally_results"] if r["recipient_id"] == companion.id)["granted"] == 5
    for damage, expected in ((4, (3, 1, 4)), (3, (1, 0, 1))):
        await declare_round(fight, {**weapon_attack(foe.id, companion.id, ""), "action": "Claw"})
        with (
            patch("check_resolution.dice_roll", return_value=_d20(17)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(damage)),
        ):
            hit = receipt(await fight.drain(), foe.id)
        saved = participant(await fight.reload(), companion.id)
        assert (saved.hp_current, saved.temp_hp, hit["temp_hp_absorbed"]) == expected
        assert hit["hit"] and not hit["target_fallen"] and hit["context"] != "killing_blow"
    events = published_payloads(fight.sd.room)
    rolls = [e for e in events if e.get("roll_type") == "attack" and e["attacker"] == foe.name]
    assert [e["damage"] for e in rolls] == [4, 3]
    assert all(e["success"] and not e["critical"] and e["context"] != "killing_blow" for e in rolls)
    updates = [e for e in events if e["type"] == "combat_ui_update"]
    assert any(p["id"] == companion.id and p["tempHp"] == 5 for event in updates for p in event["combatants"])


async def test_rally_pool_survives_new_encounter_and_expires_at_local_long_rest(fight: MawlingHarness) -> None:
    marshal, local, remote = fight.players
    await enter_fight(fight)
    assert (await cast_rally(fight))["resolved"]
    await fight.command("end_combat", {"outcome": "fled"})
    await enter_fight(fight)
    state = await fight.reload()
    assert participant(state, local).temp_hp == 5
    assert next(p for p in state.participants if p.type == "companion").temp_hp == 0
    await fight.command("end_combat", {"outcome": "fled"})

    inn = "millhaven_inn"
    fight.sd.location_id = inn
    for pid in (marshal, local):
        await db_mutations.update_player_location(pid, inn)
    lifecycle = _live_party(fight.sd, *fight.players)
    try:
        await fight.command("rest", {"rest_type": "short", "use_song_of_rest": False})
        assert (await player(local))["temp_hp"] == 5
        await fight.command("rest", {"rest_type": "long", "use_song_of_rest": False})
        assert (await player(local))["temp_hp"] == 0
        assert (await player(remote))["temp_hp"] == 5
        await db_mutations.update_player_location(remote, inn)
        with fight.sd._bind_authenticated_actor(remote, 1, lambda *_: None):
            await game_tools(fight.sd, rest)("rest", rest_type="long", use_song_of_rest=False)
        assert (await player(remote))["temp_hp"] == 0
        await enter_fight(fight)
        assert participant(await fight.reload(), local).temp_hp == 0
    finally:
        await lifecycle.aclose()


async def test_zhael_rally_leaves_moment_to_rally_for_reposition(fight: MawlingHarness) -> None:
    marshal, ally, _ = fight.players
    await set_favor(fight, marshal, "zhael")
    await enter_fight(fight)
    result = await cast_rally(fight)
    assert {r["granted"] for r in result["rally_results"]} == {5}
    assert "rally_grant" not in result
    facts = (await fight.reload()).encounter_facts
    clause = "zhael_moment_to_rally"
    assert facts["rally_pending"] == {} and clause not in facts["once_spent"]
    await declare_round(
        fight,
        {
            "kind": "reposition",
            "actor_id": marshal,
            "target_id": ally,
            "destination": point(5),
            "reshape": [],
        },
    )
    packets = await fight.drain()
    assert [p["rally_grant"] for p in packets if "rally_grant" in p] == [bonus(marshal, ally)]
    facts = (await fight.reload()).encounter_facts
    assert facts["rally_pending"] == {marshal: ally}
    assert facts["once_spent"][clause] == [marshal]
