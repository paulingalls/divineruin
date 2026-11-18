import json


async def configure(w, patron, archetype, *, index=0, **fields):
    await w.pool.execute(
        "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
        w.ids[index],
        json.dumps(
            {
                "player_id": w.ids[index],
                "class": archetype,
                "divine_favor": {"patron": patron, "level": 40, "max": 100},
                **fields,
            }
        ),
    )
    w.ctx.userdata.party.members[index].patron_id = patron
