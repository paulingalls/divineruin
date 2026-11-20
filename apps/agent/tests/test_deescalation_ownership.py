"""De-escalation ownership through the registered combat and ability tools."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_skills_fixtures import argument
from livekit.agents.llm import ToolError
from test_encounter_facts_damage import fight
from voice_condition_fixtures import participant

import db_mutations

ABILITY_ID = "diplomat_de_escalate"


@pytest.mark.parametrize(("patron", "archetype"), [("kaelen", "warrior"), ("mortaen", "druid"), ("zhael", "bard")])
async def test_unlearned_deescalation_reopens_declaration(world: SimpleNamespace, patron: str, archetype: str) -> None:
    async with fight(world, patron, archetype=archetype) as f:
        await configure(world, patron, archetype, level=1, focus={"current": 10, "max": 10})
        state = f.session.combat_state
        participant(state, f.hero).archetype_id = "diplomat"
        participant(state, f.hero).level = 1
        before = state.to_dict()
        player_before = await row(world, 0)
        await db_mutations.save_combat_state(f.combat_id, before)
        listing = await f.call("query_info", kind="abilities")
        assert ABILITY_ID not in [ability["id"] for ability in listing["abilities"]]

        await f.declare(argument(f.hero))
        assert f.session.combat_state.beat == "resolution"
        with patch.object(db_mutations, "save_combat_state", wraps=db_mutations.save_combat_state) as save:
            with pytest.raises(ToolError, match="hasn't learned De-escalate"):
                await f.call("resolve_phase")

        save.assert_awaited_once()
        assert save.await_args is not None and save.await_args.args == (f.combat_id, before)
        assert await row(world, 0) == player_before
        assert f.session.combat_state.to_dict() == before
        assert (await f.reload()).to_dict() == before


async def test_level_one_diplomat_can_deescalate_for_three_focus(world: SimpleNamespace) -> None:
    async with fight(world, "aelora", archetype="diplomat") as f:
        await configure(world, "aelora", "diplomat", level=1, focus={"current": 10, "max": 10})
        state = f.session.combat_state
        participant(state, f.hero).level = 1
        await db_mutations.save_combat_state(f.combat_id, state.to_dict())
        listing = await f.call("query_info", kind="abilities")
        assert [ability["id"] for ability in listing["abilities"]].count(ABILITY_ID) == 1

        packets = await f.round(argument(f.hero), faces=(10,))

        assert any(packet.get("action") == "de_escalate" and packet["resolved"] for packet in packets)
        assert f.session.combat_state.deescalation_scene.round_counter == 1
        assert (await row(world, 0))["focus"]["current"] == 7
