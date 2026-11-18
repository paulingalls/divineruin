"""Absorption and casting share the phase commit and recovery boundary."""

from copy import deepcopy
from dataclasses import asdict
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _resolve_round
from combat.test_spell_damage_lands import load_combat, saved_player
from combat.test_spell_damage_lands import spell_fight as spell_fight
from combat.test_veilrender_absorb import ally_cast, prepare_absorb
from voice_condition_fixtures import participant

import db
import db_mutations


@pytest.fixture
async def dev_db_pool(reset_db_pool):
    return await db.get_pool()


async def test_absorb_rollback_and_retry_once(spell_fight, monkeypatch):
    ctx = spell_fight
    spell = await prepare_absorb(ctx)
    state = deepcopy(ctx.userdata.combat_state.to_dict())
    player = await saved_player(ctx.userdata.player_id)
    mirrors = asdict(ctx.userdata.party)
    ctx.userdata.room.local_participant.publish_data.reset_mock()
    original = db_mutations.save_combat_state
    observed = []

    async def fail_after_write(combat_id, data, *, conn=None):
        await original(combat_id, data, conn=conn)
        written = await load_combat(combat_id, conn=conn)
        changed = await saved_player(ctx.userdata.player_id, conn=conn)
        assert participant(written, "foe").hp_current == 76
        assert changed["focus"]["current"] == player["focus"]["current"] - spell.focus_cost
        assert changed["resonance"]["current"] == 2
        observed.append(True)
        raise RuntimeError("injected after absorption writes")

    with monkeypatch.context() as fault:
        fault.setattr(db_mutations, "save_combat_state", fail_after_write)
        with pytest.raises(RuntimeError, match="injected after absorption"):
            await ally_cast(ctx)
    assert observed == [True]
    assert (await load_combat(state["combat_id"])).to_dict() == state
    assert await saved_player(ctx.userdata.player_id) == player
    assert ctx.userdata.combat_state.to_dict() == state and asdict(ctx.userdata.party) == mirrors
    ctx.userdata.room.local_participant.publish_data.assert_not_called()
    cast = await ally_cast(ctx)
    assert cast["absorbed"][0]["healed"] == 6
    assert participant(await load_combat(state["combat_id"]), "foe").hp_current == 76
    assert (await saved_player(ctx.userdata.player_id))["focus"]["current"] == player["focus"]["current"] - 2
    with patch("check_resolution.dice_roll", return_value=_d20(20)):
        result = await _resolve_round(ctx)
    assert all("absorbed" not in p.get("cast", {}) for p in result["packets"])
    assert participant(await load_combat(state["combat_id"]), "foe").hp_current == 86
