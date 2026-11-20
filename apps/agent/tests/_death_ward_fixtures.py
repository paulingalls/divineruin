import json

from _mortaen_threshold_fixtures import active, checkpoint

import conditions
from db_mutations_concentration import update_player_concentration
from db_queries import get_player_at_patron_revision
from patron_zero_hp import DEATH_WARD


def watch_spend(world, index=0):
    observed = []
    pid = world.ids[index]

    async def sent(data, **kwargs):
        event = json.loads(data)
        if event["type"] != "patron_abilities_updated":
            return
        player, revision = await get_player_at_patron_revision(pid, conn=world.pool)
        observed.append((event, kwargs["destination_identities"], player, revision))

    world.ctx.userdata.room.local_participant.publish_data.side_effect = sent
    return observed


def spent_projection(observed, pid):
    [(event, identities, player, revision)] = observed
    assert identities == [pid] and event["player_id"] == pid
    assert event["patron_revision"] == revision
    assert player["hp"]["current"] == 1 and player["patron_gifts"][DEATH_WARD]["spent"]
    ward = next(a for a in event["abilities"] if a["id"] == DEATH_WARD)
    assert ward["spent"] and ward["state"] == "spent"


async def concentrating(world, index=0):
    pid = world.ids[index]
    world.ctx.userdata.member_state(pid).concentration.spell_id = "divine_bless"
    await update_player_concentration(pid, "divine_bless", conn=world.pool)
    target = active(world).get_participant(pid)
    target.conditions = conditions.apply_condition(target.conditions, "blessed", source="divine_bless")
    await checkpoint(world)
