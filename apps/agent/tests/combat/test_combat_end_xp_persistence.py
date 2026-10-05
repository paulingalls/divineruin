import json
from unittest.mock import AsyncMock, MagicMock

from combat._end_multiplayer_helpers import _restore_condition_module  # noqa: F401
from combat._helpers import _damage_resolver, _resolve_round
from inventory_snapshot_fixture import snapshot_query
from voice_condition_fixtures import place_actors

import db_mutations
import db_queries
from session_data import CombatParticipant, CombatState, SessionData


async def test_resolve_phase_victory_persists_exactly_one_grant(dev_db_pool):
    pool = dev_db_pool
    player_id = "m28_s001_xp_phase_player"
    combat_id = "combat_m28_s001_xp"
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        json.dumps(
            {"player_id": player_id, "class": "warrior", "level": 3, "xp": 500, "hp": {"current": 25, "max": 25}}
        ),
    )
    enemy_id = "m28_s001_xp_enemy"
    cs = place_actors(
        CombatState(
            combat_id=combat_id,
            participants=[
                CombatParticipant(
                    id=player_id,
                    name="Kael",
                    type="player",
                    initiative=15,
                    hp_current=25,
                    hp_max=25,
                    ac=14,
                    action_pool=[{"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}],
                ),
                CombatParticipant(
                    id=enemy_id,
                    name="Goblin",
                    type="enemy",
                    initiative=12,
                    hp_current=3,  # one fixed 3-damage hit from death -> the wrap sees victory
                    hp_max=7,
                    ac=13,
                    action_pool=[{"name": "Scimitar", "damage": "1d6", "damage_type": "slashing"}],
                    xp_value=50,
                ),
            ],
            initiative_order=[player_id, enemy_id],
            beat="resolution",
            pending_declarations={player_id: {"type": "attack", "action": "Longsword", "target_id": enemy_id}},
        )
    )

    ctx = MagicMock()
    ctx.session.current_agent = None
    ctx.userdata = SessionData(player_id=player_id, location_id="accord_guild_hall", room=None)
    ctx.userdata.combat_state = cs
    queries = MagicMock(
        get_player_inventory=AsyncMock(return_value=[]), get_inventory_snapshot=snapshot_query([])
    )  # no equipped items -> no durability
    queries.get_player = db_queries.get_player  # the grant needs the REAL row read
    break_mod = MagicMock(break_concentration_on_damage=AsyncMock(return_value=None))

    try:
        result = await _resolve_round(
            ctx, queries=queries, resolver=_damage_resolver(3), concentration_break_mod=break_mod
        )
        assert json.loads(result[1])["outcome"] == "victory"

        row = await pool.fetchrow("SELECT (data->>'xp')::int AS xp FROM players WHERE player_id = $1", player_id)
        assert row["xp"] == 550  # 500 seeded + the solo encounter's whole 50, granted exactly once
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
        await db_mutations.delete_combat_state(combat_id, conn=pool)
