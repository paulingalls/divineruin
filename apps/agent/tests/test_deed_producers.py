"""Authored deeds through registered tools and caller-owned transactions."""

import asyncio
import json
from contextlib import asynccontextmanager
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from acceptance._capstone_helpers import _d20
from acceptance.mawling_harness import MawlingHarness
from acceptance.seeds import seed_player_with_pools
from livekit.agents import Agent, AgentSession
from livekit.agents.llm import ToolError
from test_aelora_gift import _live_party

import alignment_heartbeat
import db
import db_mutations_conditions
from _gods_content import load_gods
from activate_tools import activate
from caster_state import ConcentrationState, ResonanceTrack
from check_tools import check
from party_state import PartyMember
from patron_gifts import KNOWLEDGE_SKILLS
from unbound_autonomy import load_unbound

GIFT = "veythar_lorekeepers_insight"


@pytest.fixture
def mock_combat_agent_factory():
    yield


@pytest.fixture
async def walk(dev_db_pool):
    h = MawlingHarness()
    with (
        patch("combat_agent.CombatAgent._enter", new_callable=AsyncMock),
        patch("exploration_agent.ExplorationAgent._enter", new_callable=AsyncMock),
    ):
        try:
            await h.prepare((3, 3), companion="companion_kael")
            yield h
        finally:
            await h.close()


async def rows(h, conn=None):
    if conn is None:
        async with h.pool.acquire() as reader:
            return await rows(h, reader)
    return [json.loads(await conn.fetchval("SELECT data FROM players WHERE player_id=$1", p)) for p in h.players]


async def journals(h, expected, conn=None):
    for kind in {k for journal in expected for k in journal}:
        assert kind in load_unbound()[0] or any(
            a["action"] == kind for g in load_gods() for c in ("positive", "negative") for a in g["favor_actions"][c]
        ), kind
    assert [r.get("patron_deeds", {}) for r in await rows(h, conn)] == expected


async def terminal(h, route, outcome):
    await h.command("enter_mode", {"mode": "combat", "encounter_id": h.encounter_id})
    state = h.sd.combat_state
    assert state is not None
    nonplayers = [p.id for p in state.participants if p.type != "player"]
    if outcome == "victory":
        for p in state.participants:
            if p.type == "enemy":
                p.hp_current = 0
                p.is_fallen = True
    if outcome == "empty":
        state.participants = [p for p in state.participants if p.type != "enemy"]
        for key in ("positions", "speeds"):
            state.spatial[key] = {p.id: state.spatial[key][p.id] for p in state.participants}
        state.spatial["zones"] = {}
    if route == "resolve_phase":
        state.beat = "narration"
        state.deescalated = outcome == "deescalated"
        state.held_actions = []
    await h.persist()
    return nonplayers


def end_args(route, outcome):
    return {"outcome": "victory" if outcome in {"standing", "empty"} else outcome} if route == "end_combat" else {}


@pytest.mark.parametrize(
    "route,outcome,kind",
    [
        ("end_combat", "victory", "won_combat"),
        ("resolve_phase", "victory", "won_combat"),
        ("end_combat", "standing", None),
        ("end_combat", "empty", None),
        ("end_combat", "fled", "fled_combat"),
        ("resolve_phase", "deescalated", "offered_mercy"),
    ],
)
async def test_combat_participants(walk, route, outcome, kind):
    h = walk
    nonplayers = await terminal(h, route, outcome)
    spectator = f"spectator_{uuid4().hex}"
    await seed_player_with_pools(h.pool, player_id=spectator)
    h.players.append(spectator)
    h.sd.party.members.append(PartyMember(spectator, ResonanceTrack(), ConcentrationState()))
    await h.command(route, end_args(route, outcome))
    assert h.sd.combat_state is None
    await journals(h, [*([{kind: "pending"}] * 2 if kind else [{}, {}]), {}])
    assert await h.pool.fetchval("SELECT count(*) FROM players WHERE player_id=ANY($1)", nonplayers) == 0


async def checks(h, guest=True):
    await h.session.aclose()
    h.session = AgentSession(llm=h.model, userdata=h.sd)
    await h.session.start(Agent(instructions="Execute the command.", tools=[check, activate]))
    if guest:
        h.players.reverse()
    assert (h.sd.primary_player_id != h.players[0]) is guest


async def roll(h, skill, face=20, *, error=False):
    with patch("check_resolution.dice_roll", return_value=_d20(face)):
        return await h.command(
            "check",
            {
                "roll": {
                    "kind": "skill",
                    "skill": skill,
                    "difficulty": "hard",
                    "context_description": "Recall lore or pass unseen",
                    "hearing_only": False,
                }
            },
            error=error,
        )


@pytest.fixture
async def live_walk(walk):
    walk.sd.companion = None
    lifecycle = _live_party(walk.sd, *walk.players)
    try:
        assert all(walk.sd.ally_present_for(pid) for pid in walk.players)
        yield walk, lifecycle
    finally:
        await lifecycle.aclose()


def disconnect_ally(h, lifecycle):
    room = cast(MagicMock, lifecycle.room)
    handlers = dict(call.args for call in room.on.call_args_list)
    handlers["participant_disconnected"](room.remote_participants[h.players[1]])
    assert h.sd.party.contains(h.players[1])
    assert not h.sd.ally_present_for(h.players[0])


async def test_skill_deed_with_live_ally_then_disconnected(live_walk):
    h, lifecycle = live_walk
    await checks(h, guest=False)
    assert (await roll(h, "athletics"))["outcome"] == "success"
    await journals(h, [{}, {}])
    disconnect_ally(h, lifecycle)
    assert (await roll(h, "athletics"))["outcome"] == "success"
    await journals(h, [{"succeeded_alone": "pending"}, {}])


@pytest.mark.parametrize("route", ["end_combat", "resolve_phase"])
async def test_victory_deed_with_live_ally_then_disconnected(live_walk, route):
    h, lifecycle = live_walk
    await terminal(h, route, "victory")
    await h.command(route, end_args(route, "victory"))
    assert h.sd.combat_state is None
    await journals(h, [{"won_combat": "pending"}, {"won_combat": "pending"}])
    disconnect_ally(h, lifecycle)
    await terminal(h, route, "victory")
    await h.command(route, end_args(route, "victory"))
    assert h.sd.combat_state is None
    await journals(h, [{"won_combat": "pending", "won_alone": "pending"}, {"won_combat": "pending"}])


@pytest.mark.parametrize("skill", ["athletics", "stealth", *sorted(KNOWLEDGE_SKILLS)])
@pytest.mark.parametrize("face", [20, 1])
async def test_skill_deed(walk, skill, face):
    await checks(walk)
    walk.sd.companion = None
    result = await roll(walk, skill, face)
    assert (result["skill"], result["dc"]) == (skill, 16)
    assert "narrative_hint" in result
    assert result["outcome"] == ("success" if face == 20 else "failure")
    expected = {"succeeded_alone": "pending"}
    if skill != "athletics":
        expected["successful_stealth" if skill == "stealth" else "discovered_lore"] = "pending"
    await journals(walk, [expected if face == 20 else {}, {}])
    if skill == "stealth":
        assert (await rows(walk))[0]["flags"]["concealed"] is (face == 20)


@pytest.mark.parametrize("face", [20, 1])
async def test_primary_stealth(walk, face):
    await checks(walk, guest=False)
    assert (await roll(walk, "stealth", face))["outcome"] == ("success" if face == 20 else "failure")
    await journals(walk, [{"successful_stealth": "pending"} if face == 20 else {}, {}])
    assert (await rows(walk))[0]["flags"]["concealed"] is (face == 20)


async def patch_player(h, **data):
    await h.pool.execute("UPDATE players SET data=data || $2::jsonb WHERE player_id=$1", h.players[0], json.dumps(data))


async def advancement(h, conn=None):
    return await (conn or h.pool).fetch(
        "SELECT * FROM skill_advancement WHERE player_id=ANY($1) ORDER BY player_id, skill_id", h.players
    )


async def offer(h):
    await patch_player(h, divine_favor={"patron": "veythar"})
    failed = await roll(h, "history", 1)
    assert failed["outcome"] == "failure" and GIFT in failed["reroll_offer"]
    await journals(h, [{}, {}])


@pytest.mark.parametrize("face", [20, 1])
async def test_gift_deed(walk, face):
    await checks(walk)
    await offer(walk)
    before = await advancement(walk)
    with patch("check_resolution.dice_roll", return_value=_d20(face)):
        result = await walk.command("activate", {"id": GIFT})
    assert result["outcome"] == ("success" if face == 20 else "failure")
    await journals(walk, [{"discovered_lore": "pending"} if face == 20 else {}, {}])
    assert (await rows(walk))[0]["patron_gifts"][GIFT] == {"spent": True, "pending": None}
    assert await advancement(walk) == before


@asynccontextmanager
async def abort_after(inspect):
    transaction = db.transaction
    reached = []

    @asynccontextmanager
    async def injected():
        async with transaction() as conn:
            yield conn
            await inspect(conn)
            reached.append(True)
            raise ToolError("deed rollback probe")

    with patch.object(db, "transaction", injected):
        yield
    assert reached == [True]


@pytest.mark.parametrize(
    "route,outcome,kind", [("end_combat", "victory", "won_combat"), ("resolve_phase", "deescalated", "offered_mercy")]
)
async def test_combat_rollback(walk, route, outcome, kind):
    h = walk
    await terminal(h, route, outcome)
    cid = h.sd.combat_state.combat_id
    before = await rows(h)
    combat = await h.pool.fetchrow("SELECT * FROM combat_instances WHERE combat_id=$1", cid)
    skill_rows = await advancement(h)

    async def inspect(conn):
        await journals(h, [{kind: "pending"}] * 2, conn)
        assert await conn.fetchrow("SELECT * FROM combat_instances WHERE combat_id=$1", cid) is None

    h.sd.room.local_participant.publish_data.reset_mock()
    async with abort_after(inspect):
        result = await h.command(route, end_args(route, outcome), error=True)
    assert "deed rollback probe" in result
    assert await rows(h) == before
    assert await advancement(h) == skill_rows
    assert await h.pool.fetchrow("SELECT * FROM combat_instances WHERE combat_id=$1", cid) == combat
    h.sd.room.local_participant.publish_data.assert_not_called()
    await h.command(route, end_args(route, outcome))
    await journals(h, [{kind: "pending"}] * 2)
    assert await h.pool.fetchrow("SELECT * FROM combat_instances WHERE combat_id=$1", cid) is None


@pytest.mark.parametrize("producer", ["athletics", "stealth", "history", "gift"])
async def test_check_rollback(walk, producer):
    h = walk
    await checks(h)
    h.sd.companion = None
    if producer == "gift":
        await offer(h)
    if producer != "stealth":
        await patch_player(h, conditions=[{"type": "inspired", "duration": 2, "source": "ally"}])
    before = await rows(h)
    skill_rows = await advancement(h)
    expected = {"succeeded_alone": "pending"}
    if producer != "athletics":
        expected["successful_stealth" if producer == "stealth" else "discovered_lore"] = "pending"

    async def inspect(conn):
        await journals(h, [expected, {}], conn)
        current = await rows(h, conn)
        assert current[1] == before[1]
        if producer == "stealth":
            assert current[0]["flags"]["concealed"] is True
        else:
            assert current[0]["conditions"] == []
        advanced = await advancement(h, conn)
        if producer == "gift":
            assert current[0]["patron_gifts"][GIFT] == {"spent": True, "pending": None}
            assert advanced == skill_rows
        else:
            old_count = next(
                (r["use_counter"] for r in skill_rows if r["player_id"] == h.players[0] and r["skill_id"] == producer),
                0,
            )
            assert (
                next(r["use_counter"] for r in advanced if r["player_id"] == h.players[0] and r["skill_id"] == producer)
                == old_count + 1
            )

    async def invoke(error=False):
        with patch("condition_bonus.dice_roll", return_value=_d20(1)):
            if producer == "gift":
                with patch("check_resolution.dice_roll", return_value=_d20(20)):
                    return await h.command("activate", {"id": GIFT}, error=error)
            return await roll(h, producer, error=error)

    h.sd.room.local_participant.publish_data.reset_mock()
    async with abort_after(inspect):
        result = await invoke(error=True)
    assert "deed rollback probe" in result
    assert await rows(h) == before
    assert await advancement(h) == skill_rows
    h.sd.room.local_participant.publish_data.assert_not_called()
    assert (await invoke())["outcome"] == "success"
    await journals(h, [expected, {}])
    async with h.pool.acquire() as conn:
        await inspect(conn)


async def test_flight_condition_write_overlaps_due_judgment(walk, monkeypatch, caplog):
    h = walk
    await terminal(h, "end_combat", "fled")
    first, second = sorted(h.players)
    cs = h.sd.combat_state
    assert cs is not None
    cs.participants.sort(key=lambda p: p.id, reverse=True)
    exhausted = {"type": "exhausted", "stacks": 1, "duration": -1, "source": "combat"}
    next(p for p in cs.participants if p.id == second).conditions.append(exhausted)
    for pid in h.players:
        await h.pool.execute(
            "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
            pid,
            json.dumps({"divine_favor": {"patron": "kaelen", "level": 50, "max": 100}}),
        )
    monkeypatch.setattr(type(h.sd), "present_member_ids", property(lambda sd: tuple(h.players)))
    reached = asyncio.Event()

    class ObservedLock(asyncio.Lock):
        async def __aenter__(self):
            task = asyncio.current_task()
            if task is not None and task.get_name() == "due-judgment":
                reached.set()
            return await super().__aenter__()

    h.sd.combat_state_lock = ObservedLock()
    judge = alignment_heartbeat.judge_pending_deeds

    async def observed_judge(pid, **kwargs):
        grant = await judge(pid, **kwargs)
        if pid == first:
            reached.set()
        return grant

    monkeypatch.setattr(alignment_heartbeat, "judge_pending_deeds", observed_judge)
    now = 0
    heartbeat = alignment_heartbeat.AlignmentHeartbeat(h.sd, now=lambda: now)
    now = 1200
    save = db_mutations_conditions.save_player_conditions
    tick = None

    async def overlap(pid, conditions, **kwargs):
        nonlocal tick
        await save(pid, conditions, **kwargs)
        if pid == second:
            # Combat owns B; let the tick reach either the session lock or row A before continuing.
            tick = asyncio.create_task(heartbeat.maybe_tick(), name="due-judgment")
            await asyncio.wait_for(reached.wait(), 5)

    monkeypatch.setattr(db_mutations_conditions, "save_player_conditions", overlap)
    try:
        await asyncio.wait_for(h.command("end_combat", {"outcome": "fled"}), 15)
        assert tick is not None
        await asyncio.wait_for(tick, 15)
    finally:
        if tick is not None and not tick.done():
            tick.cancel()
            await asyncio.gather(tick, return_exceptions=True)
    assert "Patron deed judgment failed" not in caplog.text
    assert h.sd.combat_state is None
    await journals(h, [{}, {}])
    assert [r["divine_favor"]["level"] for r in await rows(h)] == [47, 47]
    assert exhausted in (await db_mutations_conditions.read_player_conditions(second))
    now = 2400
    await heartbeat.maybe_tick()
    assert [r["divine_favor"]["level"] for r in await rows(h)] == [47, 47]


@pytest.mark.parametrize("route", ["end_combat", "resolve_phase"])
@pytest.mark.parametrize("patron", ["none", "kaelen"])
async def test_lone_victory(dev_db_pool, route, patron):
    h = MawlingHarness()
    with (
        patch("combat_agent.CombatAgent._enter", new_callable=AsyncMock),
        patch("exploration_agent.ExplorationAgent._enter", new_callable=AsyncMock),
    ):
        try:
            await h.prepare((3,), companion="")
            await patch_player(h, divine_favor={"patron": patron, "level": 0, "max": 100})
            await terminal(h, route, "victory")
            await h.command(route, end_args(route, "victory"))
            await journals(h, [{"won_combat": "pending", "won_alone": "pending"}])
        finally:
            await h.close()


async def test_raw_channeling_rollback_and_retry(walk):
    h = walk
    await terminal(h, "end_combat", "standing")
    await checks(h)
    await patch_player(h, divine_favor={"patron": "none", "level": 0, "max": 100})
    member = h.sd.member_state(h.players[0])
    before = await rows(h)
    resonance = member.resonance.current

    async def inspect(conn):
        await journals(h, [{"channeled_raw": "pending"}, {}], conn)
        assert (await rows(h, conn))[0]["resonance"]["current"] == before[0].get("resonance", {}).get("current", 0) + 3

    h.sd.room.local_participant.publish_data.reset_mock()
    async with abort_after(inspect):
        result = await h.command("activate", {"id": "unbound_raw_channeling"}, error=True)
    assert "deed rollback probe" in result
    assert await rows(h) == before
    assert member.resonance.current == resonance and not member.unbound_raw_channeling_used
    h.sd.room.local_participant.publish_data.assert_not_called()
    result = await h.command("activate", {"id": "unbound_raw_channeling"})
    assert result["resonance_added"] == 3 and member.unbound_raw_channeling_used
    async with h.pool.acquire() as conn:
        await inspect(conn)
    result = await h.command("activate", {"id": "unbound_raw_channeling"}, error=True)
    assert "spent" in result
