from unittest.mock import patch

import pytest
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from sample_fixtures import published_payloads
from test_patron_engine_judgment import combat_rolls, declare_finish, judgment_fight, mark

import db_mutations
import db_queries
from ability_persistence import update_player_resources


async def test_judgment_checkpoint_failure_rolls_back_reward(world):
    async with judgment_fight(world, hp=1) as (call, state):
        source, ally = world.ids
        await update_player_resources(source, stamina=2, conn=world.pool)
        await mark(call)
        await declare_finish(call, state, ally)
        session = world.ctx.userdata
        before = session.combat_state.to_dict()
        events = published_payloads(session.room)
        save = db_mutations.save_combat_state

        async def fail_after_checkpoint(combat_id, data, *, conn):
            await save(combat_id, data, conn=conn)
            player = await db_queries.get_player(source, conn=conn)
            assert player is not None and player["stamina"]["current"] == 7
            assert data["judgment_rewards"][0]["stamina_restored"] == 5
            assert next(p["hp_current"] for p in data["participants"] if p["id"] == "foe") == 0
            raise RuntimeError("injected after Judgment checkpoint")

        rolls, damage = combat_rolls([3, 17] * 2, 1)
        with rolls, damage:
            with patch.object(db_mutations, "save_combat_state", fail_after_checkpoint):
                with pytest.raises(RuntimeError, match="injected after Judgment checkpoint"):
                    await call("resolve_phase")
            assert (await row(world, 0))["stamina"]["current"] == 2
            saved = await db_mutations.load_combat_state(state.combat_id, conn=world.pool)
            assert saved is not None and saved.to_dict() == before
            assert session.combat_state.to_dict() == before
            assert published_payloads(session.room) == events
            result = await call("resolve_phase")
        assert [r["stamina_restored"] for r in result["judgment_rewards"]] == [5]
        assert (await row(world, 0))["stamina"]["current"] == 7
