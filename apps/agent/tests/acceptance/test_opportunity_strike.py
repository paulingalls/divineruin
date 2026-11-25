import json
from collections.abc import AsyncIterator
from unittest.mock import patch
from uuid import uuid4

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_entomb import favor
from acceptance.test_architect_fight import pos
from acceptance.test_still_anchors import fresh_session
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory

import combat_wrap
import db_queries
from combat_spatial import require_spatial
from session_data import CombatParticipant, CombatState

STRIKE = "warrior_opportunity_strike"
MOVER = "bandit"


@pytest.fixture
async def fight(reset_db_pool: str, request: pytest.FixtureRequest) -> AsyncIterator[MawlingHarness]:
    harness = MawlingHarness()
    try:
        creature = getattr(request, "param", MOVER)
        await harness.prepare((10, 6, 6) if creature == "party" else (10, 6), companion=None)
        warrior, target, *_ = harness.players
        creature = MOVER if creature == "party" else creature
        harness.encounter_id = f"opportunity_{uuid4().hex}"
        harness.owns_template = True
        template = {
            "id": harness.encounter_id,
            "name": "Roadside ambush",
            "description": "A boot scrapes gravel.",
            "difficulty": "hard",
            "recommended_party_level": 6,
            "enemies": [
                {"id": MOVER, "creature_id": creature, "role": "standard"},
                {"id": "lookout", "creature_id": "bandit", "role": "standard"},
            ],
            "scene_placement": {
                "party_start": pos(0),
                "companion_start": pos(0),
                "actors": {MOVER: pos(3), "lookout": pos(-30)},
                "zones": {},
                "locations": {},
            },
        }
        await harness.pool.execute(
            "INSERT INTO encounter_templates (id, data) VALUES ($1,$2::jsonb)",
            harness.encounter_id,
            json.dumps(template),
        )
        harness.roster = (
            await harness.command("enter_mode", {"mode": "combat", "encounter_id": harness.encounter_id})
        )["participants"]
        state = await harness.reload()
        require_spatial(state)["positions"].update({warrior: pos(0), target: pos(25)})
        participant(state, warrior).enhancers.append("extra_attack")
        if len(harness.players) == 3:
            require_spatial(state)["positions"][harness.players[2]] = pos(6)
        await harness.persist()
        yield harness
    finally:
        await harness.close()


def participant(state: CombatState, actor: str) -> CombatParticipant:
    found = state.get_participant(actor)
    assert found is not None
    return found


async def declare_attack(fight: MawlingHarness, *, composite: bool = False) -> None:
    target = fight.players[1]
    mover = next(row for row in fight.roster if row["id"] == MOVER)
    if composite:
        action = next(row for row in mover["executable_actions"] if row["kind"] == "multiattack")
        attack = {
            "kind": "multiattack",
            "actor_id": MOVER,
            "action": action["id"],
            "strikes": [
                {"action": strike["action"], "target_id": target, "held_item_id": ""} for strike in action["strikes"]
            ],
        }
    else:
        attack = {
            "kind": "attack",
            "actor_id": MOVER,
            "target_id": target,
            "action": mover["executable_actions"][0]["id"],
            "held_item_id": "",
            "rider": "",
            "reshape": [],
        }
    await fight.command(
        "declare_phase",
        {
            "declarations": [
                attack,
                *({"kind": "defend", "actor_id": actor, "reshape": []} for actor in (*fight.players, "lookout")),
            ]
        },
    )


async def advance_to_departure(fight: MawlingHarness, *, composite: bool = False) -> dict:
    await declare_attack(fight, composite=composite)
    await fight.command("resolve_phase", {})
    return await fight.command("resolve_phase", {})


async def reconnect(fight: MawlingHarness) -> None:
    members = fight.sd.party.members[1:]
    await fresh_session(fight, await fight.reload())
    fight.sd.party.members.extend(members)


async def activate_as(fight: MawlingHarness, actor: str, *, error: bool = False) -> str:
    fight.model.commands.append(("activate", {"id": STRIKE}))
    with fight.sd._bind_authenticated_actor(actor, 1, lambda *_: None):
        await fight.session.run(user_input="Execute the next command.")
    receipt = list(fight.model.receipts.values())[-1]
    assert receipt.name == "activate" and receipt.is_error is error, receipt.output
    return receipt.output


async def stamina(actor: str) -> int:
    row = await db_queries.get_player(actor)
    assert row is not None
    return row["stamina"]["current"]


@pytest.mark.parametrize("strike", ["hit", "miss", "decline", "drop"])
async def test_departure_and_strike(fight: MawlingHarness, strike: str) -> None:
    warrior, target = fight.players
    state = await fight.reload()
    if strike == "drop":
        participant(state, MOVER).hp_current = 1
        await fight.persist()
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(1 if strike == "miss" else 15), _d20(18)]) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as damage,
    ):
        result = await advance_to_departure(fight)
        waiting = result["next"]["waiting_on"]
        assert waiting and waiting["stage"] == "movement" and waiting["triggers"] == ["on_enemy_move"]
        assert [(entry["actor_id"], entry["id"]) for entry in waiting["reactions"]] == [(warrior, STRIKE)]
        state = await fight.reload()
        assert require_spatial(state)["positions"][MOVER] == pos(5)
        assert state.held_actions[0]["opportunity_approach"]["endpoint"] == pos(20)
        assert state.held_actions[0]["roll"] is None
        rolls.assert_not_called()
        movement = next(packet for packet in result["packets"] if packet["actor_id"] == MOVER)
        assert movement["attack_pending"] and movement["moved_ft"] == 2

        if strike == "hit":
            await reconnect(fight)
            assert combat_wrap.next_envelope(await fight.reload())["waiting_on"] == waiting
        before = await stamina(warrior)
        if strike != "decline":
            await fight.command("activate", {"id": waiting["reactions"][0]["id"]})
            saved = await fight.reload()
            spend = saved.reactions_available[warrior]
            assert spend["window_id"] == waiting["window_id"] and spend["held_seq"] == saved.held_actions[0]["seq"]
            assert "already spent" in await fight.command("activate", {"id": STRIKE}, error=True)
            if strike == "hit":
                await reconnect(fight)
        assert await stamina(warrior) == before - (strike != "decline")
        result = await fight.command("resolve_phase", {})
        state = await fight.reload()
        reactions = [packet for packet in result["packets"] if packet.get("reaction") == STRIKE]
        assert require_spatial(state)["positions"][warrior] == pos(0)
        if strike == "decline":
            assert not reactions and MOVER not in state.encounter_facts["attacked"]
        else:
            (reaction,) = reactions
            assert reaction["actor_id"] == warrior and reaction["target_id"] == MOVER
            assert reaction["hit"] is (strike != "miss")
            assert state.first_hostility[MOVER] == "ally"
            assert MOVER in state.encounter_facts["attacked"]
            if strike == "miss":
                assert state.encounter_facts["misses"][warrior] == [MOVER]
            assert fight.sd.member_state(warrior).weapon_used
            assert not fight.sd.member_state(target).weapon_used
        if strike == "drop":
            assert participant(state, MOVER).is_fallen
            assert require_spatial(state)["positions"][MOVER] == pos(5)
            assert participant(state, target).hp_current == 100
            assert all(not packet.get("attack_resolved") for packet in result["packets"] if packet["actor_id"] == MOVER)
            rolls.assert_called_once()
            damage.assert_called_once()
            return
        assert result["next"]["waiting_on"]["stage"] == "post_roll"
        assert require_spatial(state)["positions"][MOVER] == pos(20)
        assert state.held_actions[0]["movement_remaining"] == 13
        assert state.held_actions[0]["melee_approach"]["movement_spent_ft"] == 17
        assert rolls.call_count == (1 if strike == "decline" else 2)
        packets = await fight.drain()
        assert any(packet["actor_id"] == MOVER and packet["hit"] for packet in packets)
        assert not any(packet.get("reaction") == STRIKE for packet in packets)
        assert participant(await fight.reload(), target).hp_current == 96


async def test_reaction_and_hostile_fate_rolls_resume_once(fight: MawlingHarness) -> None:
    warrior, target = fight.players
    await favor(fight)
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(15), _d20(18)]) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as damage,
    ):
        assert (await advance_to_departure(fight))["next"]["waiting_on"]["stage"] == "movement"
        await activate_as(fight, warrior)
        result = await fight.command("resolve_phase", {})
        assert result["fate_offer"]["roller_id"] == warrior
        state = await fight.reload()
        assert require_spatial(state)["positions"][MOVER] == pos(5)
        assert state.open_window is None and state.held_actions[0]["roll"] is None
        rolls.assert_called_once()
        damage.assert_not_called()
        cost = await stamina(warrior)
        await reconnect(fight)
        result = await fight.command("resolve_phase", {})
        assert result["fate_offer"]["roller_id"] == MOVER
        state = await fight.reload()
        assert require_spatial(state)["positions"][MOVER] == pos(20)
        (reaction,) = [packet for packet in result["packets"] if packet.get("reaction") == STRIKE]
        assert reaction["hit"] and participant(state, MOVER).hp_current == 16 - reaction["damage"]
        damage.assert_called_once()
        await reconnect(fight)
        result = await fight.command("resolve_phase", {})
        assert result["next"]["waiting_on"]["stage"] == "post_roll"
        packets = result["packets"] + await fight.drain()
    assert await stamina(warrior) == cost
    assert not any(packet.get("reaction") == STRIKE for packet in packets)
    assert rolls.call_count == damage.call_count == 2
    assert participant(await fight.reload(), target).hp_current == 96


@pytest.mark.parametrize("fight", ["hollow_mawling"], indirect=True)
async def test_a_fallen_mover_loses_every_composite_swing(fight: MawlingHarness) -> None:
    warrior, target = fight.players
    state = await fight.reload()
    participant(state, MOVER).hp_current = 1
    await fight.persist()
    with (
        patch("check_resolution.dice_roll", return_value=_d20(15)) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        result = await advance_to_departure(fight, composite=True)
        assert result["next"]["waiting_on"]["stage"] == "movement"
        assert len([head for head in (await fight.reload()).held_actions if head["actor_id"] == MOVER]) == 2
        await activate_as(fight, warrior)
        result = await fight.command("resolve_phase", {})
    state = await fight.reload()
    assert participant(state, MOVER).is_fallen and require_spatial(state)["positions"][MOVER] == pos(5)
    assert participant(state, target).hp_current == 100
    attacks = [packet for packet in result["packets"] if packet["actor_id"] == MOVER]
    assert len(attacks) == 2 and all(not attack["resolved"] for attack in attacks)
    rolls.assert_called_once()
