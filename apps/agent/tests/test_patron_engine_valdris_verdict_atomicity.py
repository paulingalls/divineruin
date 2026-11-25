from unittest.mock import patch

import pytest
from _mortaen_threshold_fixtures import active
from _thyra_wrath_fixtures import saved, snapshot
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _valdris_verdict_fixtures import FOE, GIFT, activate, fight, set_health, verdict_roll
from livekit.agents.llm import ToolError

import db_mutations
import db_queries


async def test_verdict_checkpoint_failure_rolls_back_damage_and_spend(world) -> None:
    async with fight(world) as call:
        await set_health(world, 20, temp_hp=5)
        original = active(world)
        before = await snapshot(world)
        session = world.ctx.userdata
        scratch = [
            (member.concentration.spell_id, member.weapon_used, member.weapon_crit_vs_heavy)
            for member in session.party.members
        ]
        save = db_mutations.save_combat_state
        actor_id = world.ids[0]

        async def fail_after_checkpoint(combat_id: str, data: dict, *, conn) -> None:
            await save(combat_id, data, conn=conn)
            staged = await db_mutations.load_combat_state(combat_id, conn=conn)
            assert staged is not None
            actor = staged.get_participant(actor_id)
            player = await db_queries.get_player(actor_id, conn=conn)
            assert actor is not None and player is not None
            assert (actor.hp_current, actor.temp_hp, player["hp"]["current"], player["temp_hp"]) == (18, 0, 18, 0)
            assert player["patron_gifts"][GIFT] == {"spent": True}
            raise ToolError("injected after Verdict checkpoint")

        with (
            patch.object(db_mutations, "save_combat_state", side_effect=fail_after_checkpoint) as injection,
            verdict_roll() as roll,
            pytest.raises(ToolError, match="injected after Verdict checkpoint"),
        ):
            await call("activate", id=GIFT, target_id=FOE)
        injection.assert_awaited_once()
        roll.assert_called_once_with("2d8")
        assert active(world) is original
        assert await snapshot(world) == before
        assert [
            (member.concentration.spell_id, member.weapon_used, member.weapon_crit_vs_heavy)
            for member in session.party.members
        ] == scratch

        result = await activate(call)
        assert result["damage"] == 7
        assert (await row(world, 0))["patron_gifts"][GIFT] == {"spent": True}
        assert (await saved(world)).to_dict() == active(world).to_dict()
