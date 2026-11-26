"""Hollowed Wisdom loss and recovery through registered gameplay tools."""

import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from acceptance.rest_walk import RestWalk
from acceptance.voice_condition_harness import ScenarioModel
from livekit.agents import Agent, AgentSession

import db_mutations
import db_mutations_resurrection
import event_types as E
from attribute_increase_persistence import patch_player
from attribute_increases import recompute
from combat_end import end_combat
from session_data import CombatParticipant, CombatState

OTHER_CONDITION = {"type": "exhausted", "stacks": 1}
HOLLOWED = {"type": "hollowed", "stage": 3, "source": "knight", "duration": 8}


async def seed_bearer(walk: RestWalk, pid: str, wisdom: int, *, class_: str = "druid", drained: int = 0) -> None:
    row = await walk.row(pid)
    row["attributes"]["wisdom"] = wisdom
    row.update({"class": class_, "level": 5})
    if class_ == "warrior":
        row.pop("focus", None)
        await walk.pool.execute("UPDATE players SET data=data-'focus' WHERE player_id=$1", pid)
    condition = {**HOLLOWED, "wis_drained": drained} if drained else HOLLOWED
    await patch_player(
        pid,
        {**recompute(row), "class": class_, "level": 5, "conditions": [condition, OTHER_CONDITION]},
        conn=walk.pool,
    )


async def rest(walk: RestWalk, kind: str = "long") -> list[dict]:
    receipt = await walk.command(kind)
    assert receipt.name == "rest" and not receipt.is_error, receipt.output
    return json.loads(receipt.output)["hollowed_changes"]


def test_registered_rests_drain_wisdom_and_publish_committed_pools(harness: SimpleNamespace) -> None:
    async def check() -> None:
        walk = await RestWalk().setup(harness)
        host, guest, remote, offline, warrior = walk.ids
        for pid in (host, guest, remote, offline):
            await seed_bearer(walk, pid, 12)
        await seed_bearer(walk, warrior, 12, class_="warrior")
        before = await walk.rows()
        assert before[host]["focus"]["max"] == 14
        assert await rest(walk, "short") == []
        for pid, row in (await walk.rows()).items():
            assert row["attributes"] == before[pid]["attributes"]
            assert row["conditions"] == before[pid]["conditions"]

        room = walk.sd.room
        assert room is not None
        publish = cast(AsyncMock, room.local_participant.publish_data)
        for drained, wisdom in enumerate((11, 10), start=1):
            walk.events.clear()
            publish.reset_mock()
            changes = await rest(walk)
            by_id = {change["player_id"]: change for change in changes}
            assert len(changes) == 3 and set(by_id) == {host, guest, warrior}
            rows = await walk.rows()
            for pid in (host, guest, warrior):
                row = rows[pid]
                assert row["attributes"] == {**before[pid]["attributes"], "wisdom": wisdom}
                assert row["conditions"] == [{**HOLLOWED, "wis_drained": drained}, OTHER_CONDITION]
                assert row["hp"]["current"] == row["hp"]["max"] == before[pid]["hp"]["max"]
                if pid == warrior:
                    assert "focus" not in row
                    assert row["stamina"]["current"] == row["stamina"]["max"] == before[pid]["stamina"]["max"]
                else:
                    assert row["focus"] == {"current": 13, "max": 13}
                    assert row["stamina"] == {"current": 6, "max": 6}
                fields = by_id[pid].copy()
                assert "Wisdom" in fields.pop("narration_cue")
                assert fields == {
                    "player_id": pid,
                    "name": row["name"],
                    "from_stage": 3,
                    "to_stage": 3,
                    "attribute": "wisdom",
                    "drained": 1,
                    "wisdom_after": wisdom,
                }
            assert rows[remote] == before[remote] and rows[offline] == before[offline]
            snapshots = [
                (json.loads(call.args[0])["character"]["player_id"], call.kwargs["destination_identities"])
                for call in publish.call_args_list
                if json.loads(call.args[0])["type"] == E.SESSION_INIT
            ]
            assert sorted(snapshots) == sorted((pid, [pid]) for pid in (host, guest, warrior))

    harness.run_sync(check())


def test_rest_at_wisdom_floor_preserves_the_ledger_and_the_player(harness: SimpleNamespace) -> None:
    async def check() -> None:
        walk = await RestWalk().setup(harness)
        await walk.solo()
        await seed_bearer(walk, walk.player, 2, drained=4)
        for expected_loss in (1, 0):
            changes = await rest(walk)
            assert [change["drained"] for change in changes] == ([expected_loss] if expected_loss else [])
            row = await walk.row(walk.player)
            assert row["attributes"]["wisdom"] == 1
            assert row["conditions"] == [{**HOLLOWED, "wis_drained": 5}, OTHER_CONDITION]
            assert row["hp"]["current"] > 0
            assert row["focus"] == {"current": 8, "max": 8}
            assert row["stamina"] == {"current": 6, "max": 6}
            assert row.get("death_history", {}).get("count", 0) == 0
            assert not await db_mutations_resurrection.read_hollow_killed(walk.player)

    harness.run_sync(check())


async def defeat(walk: RestWalk, row: dict) -> dict:
    pid = walk.player
    await db_mutations.update_player_hp(pid, 0)
    echo = CombatParticipant(
        id=pid,
        name=row["name"],
        type="temporary_hollowed",
        initiative=15,
        hp_current=0,
        hp_max=row["hp"]["max"],
        ac=row["ac"],
        is_fallen=True,
        conditions=row["conditions"],
    )
    state = CombatState("hollowed_defeat", [echo], [pid], location_id=walk.sd.location_id)
    walk.sd.combat_state = state
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    await walk.session.aclose()
    walk.model = ScenarioModel([("end_combat", {"outcome": "defeat"})])
    walk.session = AgentSession(llm=walk.model, userdata=walk.sd)
    await walk.session.start(Agent(instructions="End the fight.", tools=[end_combat]))
    with (
        patch("combat_end._build_handoff_agent", return_value=Agent(instructions="Narrate the defeat.")),
        walk.sd._bind_authenticated_actor(pid, 1, walk.validator),
    ):
        await walk.session.run(user_input="End the fight.")
    receipt = list(walk.model.receipts.values())[-1]
    assert receipt.name == "end_combat" and not receipt.is_error, receipt.output
    assert json.loads(receipt.output)["outcome"] == "defeat"
    return await walk.row(pid)


@pytest.mark.parametrize(
    ("start", "rests", "previous_deaths", "increase", "expected", "focus_max"),
    [(15, 3, 0, False, 15, 15), (16, 3, 2, False, 15, 15), (19, 1, 0, True, 20, 18)],
    ids=("restore", "permanent-wisdom-cost", "cap"),
)
def test_death_clears_hollowed_and_restores_only_its_wisdom_loss(
    harness: SimpleNamespace,
    start: int,
    rests: int,
    previous_deaths: int,
    increase: bool,
    expected: int,
    focus_max: int,
) -> None:
    async def check() -> None:
        walk = await RestWalk().setup(harness)
        await walk.solo()
        pid = walk.player
        await seed_bearer(walk, pid, start)
        for _ in range(rests):
            await rest(walk)
        row = await walk.row(pid)
        assert row["attributes"]["wisdom"] == start - rests
        assert row["conditions"][0]["wis_drained"] == rests
        row["focus"]["current"] = 2
        row["stamina"]["current"] = 1
        updates: dict[str, object] = {"focus": row["focus"], "stamina": row["stamina"]}
        if increase:
            row["attributes"]["wisdom"] = 20
            updates.update(recompute(row))
        if previous_deaths:
            updates["death_history"] = {"count": previous_deaths, "costs": []}
        await patch_player(pid, updates, conn=walk.pool)

        revived = await defeat(walk, row)
        assert revived["attributes"] == {**row["attributes"], "wisdom": expected}
        assert revived["conditions"] == [OTHER_CONDITION]
        assert revived["focus"] == {"current": 2, "max": focus_max}
        assert revived["stamina"] == {"current": 1, "max": 6}
        assert revived["hp"]["current"] == revived["hp"]["max"] > 0
        assert revived["last_rested_settlement_id"] == walk.anchor
        assert revived["location_id"] == walk.anchor
        assert revived["death_history"]["count"] == previous_deaths + 1
        assert revived["death_history"]["costs"][-1]["attribute_penalty"] == (1 if previous_deaths else 0)
        assert await db_mutations_resurrection.read_hollow_killed(pid)

    harness.run_sync(check())
