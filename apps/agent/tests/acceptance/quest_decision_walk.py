"""Registered decision commands and committed database snapshots."""

import json
from typing import cast

from acceptance.greyvale_finish_line import WarmArc, assert_finish, refresh, start_warm

import db_content_queries
import db_mutations
import db_queries


class DecisionWalk(WarmArc):
    quest: str
    stage: int
    line: str


async def decision_walk(harness, quest="greyvale_anomaly", stage=6):
    arc = cast(DecisionWalk, await start_warm(harness))
    arc.quest = quest
    arc.stage = stage
    await arc.pool.execute("UPDATE players SET data=data || '{\"xp\":100}'::jsonb WHERE player_id=$1", arc.player)
    assert arc.sd.companion is not None
    await db_mutations.set_npc_disposition(arc.sd.companion.id, arc.player, "hostile", "setup")
    await db_mutations.add_inventory_item(arc.player, "veythar_sealed_artifact", 1, tainted=False)
    line = await refresh(arc, quest, stage)
    authored = await db_content_queries.get_quest(quest)
    assert authored is not None
    assert_finish(line, authored, stage)
    arc.line = line
    return arc


async def command(arc, destination, option=None, *, actor=None):
    args = {"quest_id": arc.quest, "new_stage_id": destination}
    if option is not None:
        args["option_id"] = option
    arc.model.commands.append(("update_quest", args))
    with arc.sd._bind_authenticated_actor(actor or arc.player, 1, lambda *_: None):
        await arc.session.run(user_input="Execute the chosen quest command.")
    receipt = list(arc.model.receipts.values())[-1]
    assert receipt.name == "update_quest"
    return receipt


async def snapshot(arc, player=None):
    pid = player or arc.player
    return (
        await arc.pool.fetchval("SELECT data::text FROM players WHERE player_id=$1", pid),
        await arc.pool.fetchval(
            "SELECT data::text FROM player_quests WHERE player_id=$1 AND quest_id=$2", pid, arc.quest
        ),
        await db_queries.get_npc_disposition(arc.sd.companion.id, pid),
        [
            tuple(r)
            for r in await arc.pool.fetch("SELECT * FROM player_inventory WHERE player_id=$1 ORDER BY item_id", pid)
        ],
    )


async def assert_choice(arc, option):
    before = await snapshot(arc)
    decision = "artifact_choice" if arc.quest == "greyvale_anomaly" else "fortification_choice"
    if decision == "artifact_choice":
        assert f'option_id="{option}"' in arc.line
    receipt = await command(arc, arc.stage + 1, option)
    assert not receipt.is_error, receipt.output
    player = await db_queries.get_player(arc.player)
    row = await db_queries.get_player_quest(arc.player, arc.quest)
    assert player is not None and row is not None
    assert row["current_stage"] == arc.stage + 1
    assert row["decisions"] == {decision: option}
    flags = player["flags"]
    if decision == "artifact_choice":
        show = option == "show_companion"
        assert flags.get("companion_knows_artifact") is (True if show else None)
        assert flags.get("player_has_veythar_artifact") is (None if show else True)
        assert await db_queries.get_npc_disposition(arc.sd.companion.id, arc.player) == (
            "friendly" if show else "hostile"
        )
        assert player["xp"] == 100
        assert row.get("status", "active") == "active"
    else:
        assert flags["millhaven_fortification"] == option
        expected = {"north_barricade": (3, 0, 0), "watchtower": (0, 3, 0), "evacuation_supplies": (0, 0, 3)}[option]
        assert tuple(flags[f"millhaven_{key}"] for key in ("defense", "warning", "evacuation")) == expected
        assert row["status"] == "completed" and player["xp"] == json.loads(before[0])["xp"] + 100
    after = await snapshot(arc)
    assert after != before
    count = len(arc.events)
    for replay in (option, "keep_artifact" if option == "show_companion" else "show_companion"):
        assert (await command(arc, arc.stage + 1, replay)).is_error
        assert await snapshot(arc) == after and len(arc.events) == count
    if decision == "artifact_choice":
        receipt = await command(arc, 8)
        assert not receipt.is_error, receipt.output
        row = await db_queries.get_player_quest(arc.player, arc.quest)
        assert row is not None
        assert row["decisions"] == {decision: option} and row["status"] == "completed"
        player = await db_queries.get_player(arc.player)
        assert player is not None and player["xp"] == 300
