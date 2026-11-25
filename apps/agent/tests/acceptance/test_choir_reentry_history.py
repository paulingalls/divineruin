import json

import pytest
from acceptance._catalog_cutover_helpers import started as started
from acceptance._choir_spell_helpers import bolt
from acceptance.test_choir_encounter import search
from sample_fixtures import make_context

import choir_scene
import combat_end
import db_mutations
import db_queries
import mode_tools


async def _flee_and_reenter(ctx, *, history, drop_key=False):
    state = ctx.userdata.combat_state
    state.encounter_facts["party_aggressors"] = history
    location_id = state.location_id
    await combat_end._end_combat_impl(ctx, "fled")
    if drop_key:
        player = await db_queries.get_player(ctx.userdata.player_id)
        record = choir_scene.read(player, location_id)
        assert record is not None
        del record["party_aggressors"]
        await db_mutations.set_player_flag(ctx.userdata.player_id, choir_scene.key(location_id), json.dumps(record))
    fresh = make_context(ctx.userdata.player_id, room=ctx.userdata.room)
    fresh.userdata.location_id = location_id
    await mode_tools._enter_mode_impl(fresh, "combat", "hollow_choir", "voices return")
    return fresh.userdata.combat_state


@pytest.mark.parametrize("drop_key", [False, True], ids=["current", "prior_receipt"])
async def test_choir_reentry_carries_party_aggression(started, drop_key):
    ctx, _ = await started("hollow_choir", player_class="mage")
    await search(ctx)
    await bolt(ctx)
    follower = ctx.userdata.player_id
    reentered = await _flee_and_reenter(ctx, history={"choir_zone": [follower]}, drop_key=drop_key)
    assert reentered.choir_encounter["phase"] == "exposed"
    expected = None if drop_key else {"choir_zone": [follower]}
    assert reentered.encounter_facts["party_aggressors"] == expected
