import json
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import pos

from combat_spatial import require_spatial


@pytest.fixture
async def fight(reset_db_pool: str, request: pytest.FixtureRequest) -> AsyncIterator[MawlingHarness]:
    harness = MawlingHarness()
    try:
        await harness.prepare((6, 6), companion=None)
        mover, ally = harness.players
        options = getattr(request, "param", {})
        for actor, key in ((mover, "player"), (ally, "ally")):
            if player := options.get(key):
                await harness.pool.execute(
                    "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1", actor, json.dumps(player)
                )
        placements = {"bandit": pos(0), "lookout": pos(25)}
        if options.get("include_second_bandit"):
            placements["second_bandit"] = pos(0)
        harness.encounter_id = f"roadside_{uuid4().hex}"
        harness.owns_template = True
        await harness.pool.execute(
            "INSERT INTO encounter_templates (id, data) VALUES ($1,$2::jsonb)",
            harness.encounter_id,
            json.dumps(
                {
                    "id": harness.encounter_id,
                    "name": "Roadside ambush",
                    "description": "A boot scrapes gravel.",
                    "difficulty": "hard",
                    "recommended_party_level": 6,
                    "enemies": [
                        {"id": enemy, "creature_id": options.get(enemy, "bandit"), "role": "standard"}
                        for enemy in placements
                    ],
                    "scene_placement": {
                        "party_start": pos(3),
                        "companion_start": pos(3),
                        "actors": placements,
                        "zones": {},
                        "locations": {},
                    },
                }
            ),
        )
        await harness.command("enter_mode", {"mode": "combat", "encounter_id": harness.encounter_id})
        harness.enemies = list(placements)
        state = await harness.reload()
        require_spatial(state)["positions"].update({mover: pos(3), ally: pos(-30)})
        await harness.persist()
        yield harness
    finally:
        await harness.close()


def move(actor: str, x: float) -> dict:
    return {"kind": "move", "actor_id": actor, "destination": pos(x), "movement_mode": "ground", "reshape": []}


async def declare(fight: MawlingHarness, *actions: dict) -> None:
    actors = {action["actor_id"] for action in actions}
    await fight.command(
        "declare_phase",
        {
            "declarations": [
                *actions,
                *(
                    {"kind": "defend", "actor_id": actor, "reshape": []}
                    for actor in (*fight.players, *fight.enemies)
                    if actor not in actors
                ),
            ]
        },
    )


def attack(actor: str, target: str, action: str, *, rider: str = "") -> dict:
    return {
        "kind": "attack",
        "actor_id": actor,
        "target_id": target,
        "action": action,
        "held_item_id": "",
        "rider": rider,
        "reshape": [],
    }


async def resolve_allies(fight: MawlingHarness) -> list[dict]:
    packets = []
    for _ in range(12):
        result = await fight.command("resolve_phase", {})
        packets.extend(result["packets"])
        if result["next"]["waiting_on"] is None:
            assert result["beat"] == "narration", result
            return packets
    raise AssertionError("ally declarations did not finish")


def strikes(packets: list[dict]) -> list[dict]:
    return [packet for packet in packets if packet.get("opportunity_attack")]


async def activate_as(fight: MawlingHarness, actor: str, ability: str) -> None:
    fight.model.commands.append(("activate", {"id": ability}))
    with fight.sd._bind_authenticated_actor(actor, 1, lambda *_: None):
        await fight.session.run(user_input="Execute the next command.")
    receipt = list(fight.model.receipts.values())[-1]
    assert receipt.name == "activate" and not receipt.is_error, receipt.output
