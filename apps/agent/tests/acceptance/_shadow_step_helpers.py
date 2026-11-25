import json
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import WORKS, pos
from acceptance.test_self_buff_electives import equip
from creature_combat_helpers import participant as catalog_participant

import combat_recharge
import combat_spatial
import reaction_spend
from creature_catalog import query_creature_by_id
from creature_combat import translate_creature

STEP = "rogue_shadow_step"
DESTINATION = pos(25)


@pytest.fixture
async def shadow_fight(reset_db_pool: str) -> AsyncIterator[MawlingHarness]:
    walk = MawlingHarness()
    try:
        await walk.prepare((8, 8), companion=None, location=WORKS)
        rogue, ally = walk.players
        await walk.pool.execute("""UPDATE players SET data = data || '{"class":"rogue"}' WHERE player_id=$1""", rogue)
        await equip(walk, STEP)
        walk.encounter_id = f"shadow_{uuid4().hex}"
        walk.owns_template = True
        placements = {"architect": pos(3000)}
        await walk.pool.execute(
            "INSERT INTO encounter_templates (id, data) VALUES ($1,$2::jsonb)",
            walk.encounter_id,
            json.dumps(
                {
                    "id": walk.encounter_id,
                    "name": "Ambush at the works",
                    "description": "Boots scrape over slate.",
                    "difficulty": "hard",
                    "recommended_party_level": 8,
                    "enemies": [
                        {"id": "architect", "creature_id": "hollow_architect", "role": "named"},
                    ],
                    "scene_placement": {
                        "party_start": pos(0),
                        "companion_start": pos(0),
                        "actors": placements,
                        "zones": {},
                        "locations": {},
                    },
                }
            ),
        )
        await walk.command("enter_mode", {"mode": "combat", "encounter_id": walk.encounter_id})
        walk.enemies = ["architect", "bandit"]
        state = await walk.reload()
        spatial = combat_spatial.require_spatial(state)
        bandit = await query_creature_by_id("bandit")
        enemy = translate_creature(bandit, encounter_id=walk.encounter_id, enemy_id="bandit", role="standard")
        bandit_actor = catalog_participant(enemy)
        combat_recharge.initialize(bandit_actor)
        state.participants.append(bandit_actor)
        state.initiative_order.append("bandit")
        state.reactions_available["bandit"] = reaction_spend.unspent()
        spatial["positions"]["bandit"] = pos(0, -3)
        spatial["speeds"]["bandit"] = enemy["speed"]
        combat_spatial.place(state, rogue, pos(0))
        combat_spatial.place(state, ally, pos(25, 4))
        combat_spatial.require_spatial(state)["speeds"][rogue] = 30
        await walk.persist()
        yield walk
    finally:
        await walk.close()


def step(actor: str, destination: dict, *, action: str = STEP, kind: str = "ability_move") -> dict:
    return {"kind": kind, "actor_id": actor, "action": action, "destination": destination}
