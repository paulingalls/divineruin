"""Inventory materials across the database, DM, HUD, and combat boundaries."""

import json

from acceptance.seeds import seed_player
from sample_fixtures import make_context

import combat_init
import db
import db_queries
import db_session_queries
from query_tools import _query_info_impl


async def _seed_inventory(pool, player_id, entries):
    await seed_player(pool, player_id=player_id)
    for item_id, slot in entries.items():
        await pool.execute(
            "INSERT INTO player_inventory (player_id, item_id, data) VALUES ($1, $2, $3::jsonb)",
            player_id,
            item_id,
            json.dumps(slot),
        )


async def test_material_reaches_inventory_dm_and_session(reset_db_pool):
    pool = await db.get_pool()
    player_id = "material_inventory_listing"
    await _seed_inventory(pool, player_id, {"wolf_pelt": {"quantity": 3, "equipped": False}})

    inventory = await db_queries.get_player_inventory(player_id)
    assert [(row["id"], row["name"], row["type"], row["slot_info"]["quantity"]) for row in inventory] == [
        ("wolf_pelt", "Wolf Pelt", "material", 3)
    ]
    dm = json.loads(await _query_info_impl(make_context(player_id), "inventory"))
    assert [(row["name"], row["type"], row["quantity"]) for row in dm["items"]] == [("Wolf Pelt", "material", 3)]
    payload = await db_session_queries.get_session_init_payload(player_id)
    assert [(row["name"], row["type"], row["slot_info"]["quantity"]) for row in payload["inventory"]] == [
        ("Wolf Pelt", "material", 3)
    ]


async def test_flask_prefers_item_catalog(reset_db_pool):
    pool = await db.get_pool()
    player_id = "material_inventory_flask"
    await _seed_inventory(pool, player_id, {"crystal_flask": {"quantity": 1}})
    rows = await db_queries.get_player_inventory(player_id)
    assert len(rows) == 1
    assert rows[0]["id"] == "crystal_flask"
    assert rows[0]["type"] == "equipment"
    assert rows[0]["effects"]
    assert rows[0]["description"].startswith("Thin glass")


async def test_material_does_not_enter_combat_traits(reset_db_pool):
    pool = await db.get_pool()
    player_id = "material_inventory_combat"
    await _seed_inventory(
        pool,
        player_id,
        {
            "wolf_pelt": {"quantity": 3},
            "shortsword_basic": {"quantity": 1, "equipped": True},
            "stillheart": {"quantity": 1},
        },
    )
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{equipment}', $2::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps({"main_hand": {"name": "Shortsword", "damage": "1d6", "damage_type": "piercing", "properties": []}}),
    )
    context = make_context(player_id)
    result = await combat_init._start_combat_impl(context, "hollow_wisp", "A wisp appears.")
    assert isinstance(result, tuple)
    participant = next(p for p in context.userdata.combat_state.participants if p.id == player_id)
    assert participant.condition_immunities == {"charmed": "Stillheart"}
    assert participant.save_advantages == {"wisdom": "Stillheart"}
