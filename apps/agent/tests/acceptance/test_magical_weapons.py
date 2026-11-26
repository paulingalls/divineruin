"""Catalog weapon origin reaches the Knight through live combat tools and saved rolls."""

import json
from collections.abc import AsyncIterator
from unittest.mock import patch
from uuid import uuid4

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_entomb import favor
from acceptance.test_architect_fight import pos
from acceptance.test_martial_core_kit import declare
from acceptance.test_opportunity_strike import MOVER, STRIKE, advance_to_departure, participant, reconnect, stamina
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_weapon_proficiency_equip import declare_weapon

import db_queries
from activate_tools import activate
from combat_spatial import require_spatial
from inventory_tools import transact

ASHMARK = "blade_of_the_ashmark"
DEVASTATING = "warrior_devastating_strike"


@pytest.fixture(params=[ASHMARK, "longsword_guild"], ids=["magical", "mundane"])
async def fight(reset_db_pool: str, request: pytest.FixtureRequest) -> AsyncIterator[tuple[MawlingHarness, dict]]:
    harness = MawlingHarness()
    try:
        await harness.prepare((6, 6), companion=None, tools=(transact, activate))
        actor, victim = harness.players
        item = request.param
        grant = await harness.command("transact", {"action": "exchange", "item_id": item, "delta": 1})
        assert grant["action"] == "added"
        receipt = await harness.command("transact", {"action": "equip", "item_id": item, "delta": 0})
        assert receipt["action"] == "equipped"
        row = await db_queries.get_player(actor)
        assert row is not None
        weapon = row["equipment"]["main_hand"]
        assert weapon["id"] == item and "magical" not in weapon

        harness.encounter_id = f"knight_weapons_{uuid4().hex}"
        harness.owns_template = True
        template = {
            "id": harness.encounter_id,
            "name": "Knight patrol",
            "description": "A plated boot scrapes the road.",
            "difficulty": "hard",
            "recommended_party_level": 6,
            "enemies": [
                {"id": MOVER, "creature_id": "hollow_knight", "role": "standard"},
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
        require_spatial(state)["positions"].update({actor: pos(0), victim: pos(25)})
        await harness.persist()
        yield harness, weapon
    finally:
        await harness.close()


@pytest.mark.parametrize(("kind", "raw_damage", "cost"), [("basic", 5, 0), (DEVASTATING, 9, 3), (STRIKE, 5, 1)])
@pytest.mark.parametrize("held", [False, True], ids=["ordinary", "prepared"])
async def test_equipped_weapon_damage(
    fight: tuple[MawlingHarness, dict], kind: str, raw_damage: int, cost: int, held: bool
) -> None:
    harness, weapon = fight
    actor = harness.players[0]
    is_magical = weapon["id"] == ASHMARK
    opportunity = kind == STRIKE
    state = await harness.reload()
    action = next(a for a in participant(state, actor).action_pool if a["name"] == weapon["name"])
    assert action["id"] == weapon["id"] and "magical" not in action
    hp = participant(state, MOVER).hp_current
    before_stamina = await stamina(actor)
    if held:
        await favor(harness)

    if opportunity:
        waiting = (await advance_to_departure(harness))["next"]["waiting_on"]
        assert waiting["stage"] == "movement"
        (reaction,) = waiting["reactions"]
        assert (reaction["actor_id"], reaction["id"]) == (actor, STRIKE)
        await harness.command("activate", {"id": reaction["id"]})
    elif kind == DEVASTATING:
        await declare(harness, DEVASTATING, [MOVER])
    else:
        await declare_weapon(harness, MOVER, weapon["name"])

    faces = [18, 18 if held else 1] if opportunity else [18]
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(face) for face in faces]) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as damage,
    ):
        if held:
            offer = (await harness.command("resolve_phase", {}))["fate_offer"]
            assert (offer["roll_kind"], offer["roller_id"]) == ("attack", actor)
            rolls.assert_called_once()
            damage.assert_not_called()
            saved = await harness.reload()
            assert participant(saved, MOVER).hp_current == hp
            if opportunity:
                route = saved.held_actions[0]["opportunity_approach"]
                (spend,) = route["spends"]
                cursor = spend["attack"]
                saved_action = route["window"]["reactors"][actor]["action"]
            else:
                assert saved.ally_continuation is not None
                cursor = saved.ally_continuation["attack"]
                (saved_action,) = cursor["actions"]
            assert cursor["prepared"] and cursor["actions"][0]["id"] == weapon["id"]
            assert saved_action["id"] == weapon["id"]
            saved_action["magical"] = not is_magical
            await harness.persist()
            await reconnect(harness)

        packets = []
        if held and opportunity:
            resumed = await harness.command("resolve_phase", {})
            assert resumed["fate_offer"]["roller_id"] == MOVER
            damage.assert_called_once()
            packets.extend(resumed["packets"])
        packets.extend(await harness.drain())
        if held:
            assert "Call declare_phase first" in await harness.command("resolve_phase", {}, error=True)

    (attack,) = [packet for packet in packets if packet.get("actor_id") == actor and "hit" in packet]
    assert attack["hit"]
    assert attack.get("reaction") == (STRIKE if opportunity else None)
    expected = raw_damage if is_magical else raw_damage // 2
    assert attack["damage"] == expected
    assert participant(await harness.reload(), MOVER).hp_current == hp - expected
    assert await stamina(actor) == before_stamina - cost
    assert rolls.call_count == (2 if opportunity else 1)
    assert damage.call_count == 1 + (kind == DEVASTATING) + 2 * (held and opportunity)
