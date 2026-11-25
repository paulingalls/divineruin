import json
from contextlib import AsyncExitStack
from unittest.mock import patch
from uuid import uuid4

import pytest
from _zhael_fate_fixtures import defend
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import (
    WORKS,
    declare_attack,
    pos,
)
from acceptance.test_architect_fight import (
    enter as enter_architect,
)
from acceptance.test_architect_fight import (
    mock_combat_agent_factory as mock_combat_agent_factory,
)
from acceptance.test_architect_terrain import play

import combat_spatial
import db_queries


@pytest.fixture
async def enter_fight(reset_db_pool):
    async with AsyncExitStack() as cleanup:

        async def enter(creature: str | None = None):
            fight = MawlingHarness()
            cleanup.push_async_callback(fight.close)
            await fight.prepare(
                (20,), companion=None, location=WORKS if creature is None else "greyvale_wilderness_north"
            )
            if creature is None:
                await enter_architect(fight)
                return fight, []

            fight.encounter_id = f"creature_flight_{uuid4().hex}"
            template = {
                "id": fight.encounter_id,
                "name": "Open ground",
                "description": "Wind scrapes over stone.",
                "difficulty": "hard",
                "recommended_party_level": 20,
                "enemies": [{"id": creature, "creature_id": creature, "role": "standard"}],
                "scene_placement": {
                    "party_start": pos(60),
                    "companion_start": pos(60, 5),
                    "actors": {creature: pos(0)},
                    "zones": {},
                    "locations": {},
                },
            }
            await fight.pool.execute(
                "INSERT INTO encounter_templates (id, data) VALUES ($1,$2::jsonb)",
                fight.encounter_id,
                json.dumps(template),
            )
            fight.owns_template = True
            receipt = await fight.command("enter_mode", {"mode": "combat", "encounter_id": fight.encounter_id})
            return fight, receipt["participants"]

        yield enter


@pytest.mark.parametrize(
    "separation,ceiling,mode,moved,spent,hit",
    [
        (60, None, "flying", 55, 55, True),
        (95, "beyond", "flying", 80, 80, False),
        (60, "across", "ground", 10, 20, False),
    ],
)
async def test_thunderbird_melee_approach(enter_fight, separation, ceiling, mode, moved, spent, hit):
    fight, roster = await enter_fight("thunderbird")
    bird = "thunderbird"
    beak = next(
        action["id"]
        for actor in roster
        if actor["id"] == bird
        for action in actor["executable_actions"]
        if action["name"] == "Beak"
    )
    initial = fight.sd.combat_state.get_participant(bird)
    state = await fight.reload()
    reloaded = state.get_participant(bird)
    base = 0
    if ceiling is not None:
        # Named encounters are solitary at entry. Bring over the catalog-initialized bird.
        ground_speed = state.spatial["speeds"][bird]
        fight, _ = await enter_fight()
        state = await fight.reload()
        state.participants.append(reloaded)
        state.initiative_order.append(bird)
        state.spatial["speeds"][bird] = ground_speed
        state.spatial["positions"][bird] = pos(0)
        owner = state.architect_encounter["owner_id"]
        domain = state.spatial["movement_areas"][f"{owner}_domain"]
        base = domain["center"]["x"] + domain["radius_ft"] + 20
        combat_spatial.place(state, owner, pos(base, 30))
        architect = state.get_participant(owner)
        architect.hp_current = (architect.hp_max - 1) // 2
    target = fight.players[0]
    combat_spatial.place(state, bird, pos(base))
    combat_spatial.place(state, target, pos(base + separation))
    await fight.persist()
    if ceiling is not None:
        start = base - 1 if ceiling == "across" else base + 82
        section = {"kind": "lower_ceiling", "min": pos(start, -5), "max": pos(start + 20, 5)}
        lowered = await play(fight, owner, {**defend(owner), "reshape": [section]}, defend(target), defend(bird))
        assert len(lowered["reshape"]) == 1

    await declare_attack(fight, bird, target, beak)
    with (
        patch("check_resolution.dice_roll", return_value=_d20(15)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(8)) as rolls,
    ):
        packets = await fight.drain()
    packet = [packet for packet in packets if packet["actor_id"] == bird][-1]
    assert packet["moved_ft"] == pytest.approx(moved), packet
    assert packet["movement_spent_ft"] == pytest.approx(spent)
    assert packet["movement_mode"] == mode
    assert packet["destination"] == pytest.approx(pos(base + moved))
    assert packet["attack_resolved"] is hit, json.dumps(packet)
    assert rolls.call_count == int(hit)
    if hit:
        assert packet["hit"] is True and packet["damage"] == 8
    state = await fight.reload()
    assert combat_spatial.position(state.spatial, bird) == pytest.approx(pos(base + moved))
    assert state.spatial["speeds"][bird] == 20
    for participant in (initial, reloaded):
        assert participant.fly_speed == 80
        assert participant.flyby is True
    player = await db_queries.get_player(target)
    assert player is not None
    assert player["hp"]["current"] == state.get_participant(target).hp_current == (92 if hit else 100)


async def test_catalog_flight_owners_and_hollowmoth_round_trip(enter_fight):
    fight, _ = await enter_fight("hollow_hollowmoth")
    rows = await fight.pool.fetch("SELECT id, data FROM creatures")
    catalog = {row["id"]: json.loads(row["data"]) for row in rows}
    assert {key: row["fly_speed"] for key, row in catalog.items() if "fly_speed" in row} == {
        "hollow_hollowmoth": 30,
        "steppe_razorwing": 60,
        "thunderbird": 80,
    }
    assert {key for key, row in catalog.items() if any(p.get("flyby") is True for p in row["passives"])} == {
        "steppe_razorwing",
        "thunderbird",
    }
    moth = (await fight.reload()).get_participant("hollow_hollowmoth")
    assert moth.fly_speed == 30
    assert moth.flyby is False
