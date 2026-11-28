"""Unravel Fate refuses to rewind across a Valdris Oath of Justice breach."""

from unittest.mock import patch

import pytest
from _zhael_fate_fixtures import attack, defend
from _zhael_unravel_fixtures import activate, cached, durable, favor, patch_player
from _zhael_unravel_fixtures import unravel as unravel
from acceptance.test_departed_member_leaves_fight_guards import leave_unravel_guest
from combat._round_checkpoint_helpers import Fight
from livekit.agents.llm import ToolError
from weapon_fixtures import DAGGER

from exploration_agent import ExplorationAgent


@pytest.mark.parametrize("scope", ["breach_round", "departed_breacher", "later_round", "other_combat"])
async def test_oath_breach_rewind_after_checkpoint_reload(unravel: Fight, scope: str) -> None:
    fight = unravel
    _, paladin = fight.ids
    await favor(fight, paladin, "valdris")
    await patch_player(fight, paladin, **{"class": "paladin", "equipment": {"main_hand": DAGGER}})
    await fight.start()
    offer = (await fight.call("query_info", kind="abilities", actor=paladin))["oath_choice"]
    await fight.call("select", actor=paladin, choice_id=offer["choice_id"], option="justice")
    state = fight.session.combat_state
    foe = next(p.id for p in state.participants if p.type == "enemy")
    await fight.declare(attack(paladin, foe), *(defend(pid) for pid in state.initiative_order if pid != paladin))
    await fight.finish_round(2)
    row = await fight.reload()
    assert row["encounter_facts"]["opening_actors"][foe] == paladin
    assert (await durable(fight))["players"][paladin]["data"]["oaths"]["records"][0]["status"] == "broken"
    if scope in ("breach_round", "departed_breacher"):
        if scope == "departed_breacher":
            await leave_unravel_guest(fight, paladin)
            assert paladin in (await fight.reload())["departed_player_ids"]
        before, scratch = await durable(fight), cached(fight)
        refusal = None
        try:
            await activate(fight)
        except ToolError as error:
            refusal = str(error)
        assert await durable(fight) == before
        assert cached(fight) == scratch
        assert refusal == "Unravel Fate cannot rewind across a broken Oath of Justice."
        return

    if scope == "other_combat":
        with patch("combat_end._build_handoff_agent", return_value=ExplorationAgent()):
            await fight.call("end_combat", outcome="fled")
        await fight.start()
        assert fight.session.combat_state.combat_id != state.combat_id
    rewind_round = fight.session.combat_state.round_number
    await fight.declare()
    await fight.finish_round(rewind_round + 1)
    await fight.reload()
    await activate(fight)
    saved = await durable(fight)
    assert saved["combat"]["round_number"] == rewind_round
    assert saved["players"][paladin]["data"]["oaths"]["records"][0]["status"] == "broken"
