import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import FixedRng, make_context, mock_txn, published_events

import conditions
import event_types as E
import movement_tools
from movement_tools import _move_player_impl
from scene_tools import _enter_location_impl
from travel_tools import _travel_impl

# The guest sorts before the host, so party order and lock order differ.
IDS = ("player_1", "player_0")
LOCK_ORDER = sorted(IDS)
START = "accord_guild_hall"
DEST = "greyvale_ruins_inner"


def _ctx():
    ctx = make_context(location_id=START, party_member_ids=[IDS[1]])
    ctx.userdata.event_bus = MagicMock()
    ctx.userdata.member_state(IDS[0]).corruption_level = 1
    ctx.userdata.member_state(IDS[1]).corruption_level = 2
    return ctx


def _mocks(*, terrain="established_road", requires=None, players=None):
    start = {
        "id": START,
        "name": "Guild Hall",
        "exits": {"north": {"destination": DEST, **({"requires": requires} if requires else {})}},
    }
    dest = {"id": DEST, "name": "Ruins", "terrain": terrain, "exits": {"south": START}}
    locations = {START: start, DEST: dest}
    db_mod = MagicMock()
    conn = MagicMock()
    db_mod.transaction = lambda: mock_txn(conn)
    db_mod.extract_exit_connections = lambda exits: [
        entry if isinstance(entry, str) else entry["destination"] for entry in exits.values()
    ]
    mutations = SimpleNamespace(update_player_location=AsyncMock(), upsert_map_progress=AsyncMock())
    travel_mutations = SimpleNamespace(update_player_travel_state=AsyncMock())
    conditions_mutations = SimpleNamespace(save_player_conditions=AsyncMock())
    content = SimpleNamespace(get_location=AsyncMock(side_effect=lambda loc: locations[loc]))
    rows = players or {
        pid: {"player_id": pid, "name": pid, "conditions": [], "attributes": {"wisdom": 12}, "proficiencies": []}
        for pid in IDS
    }
    queries = SimpleNamespace(
        get_player=AsyncMock(side_effect=lambda pid, **_: rows[pid]),
        get_player_flag=AsyncMock(return_value=False),
        get_npcs_at_location=AsyncMock(return_value=[]),
        get_targets_at_location=AsyncMock(return_value=[]),
        get_npc_dispositions=AsyncMock(return_value={}),
    )
    return SimpleNamespace(
        db_mod=db_mod,
        conn=conn,
        mutations=mutations,
        travel_mutations=travel_mutations,
        conditions_mutations=conditions_mutations,
        content=content,
        queries=queries,
    )


def _arrival_calls(m):
    assert m.mutations.update_player_location.await_args_list == [call(pid, DEST, conn=m.conn) for pid in LOCK_ORDER]
    assert m.mutations.upsert_map_progress.await_args_list == [
        call(pid, DEST, [START], conn=m.conn) for pid in LOCK_ORDER
    ]
    assert m.travel_mutations.update_player_travel_state.await_args_list == [
        call(pid, None, conn=m.conn) for pid in LOCK_ORDER
    ]


async def _move(ctx, m):
    with patch.object(
        movement_tools.ward_resolution, "resolve_scope_ward_with_scope", AsyncMock(return_value=(None, None))
    ):
        return json.loads(
            await _move_player_impl(
                ctx,
                DEST,
                db_mod=m.db_mod,
                mutations=m.mutations,
                travel_mutations=m.travel_mutations,
                queries=m.queries,
                content=m.content,
            )
        )


async def _travel(ctx, m, *, mode="scenic", hours=4, forced_march=False, rng=20):
    with patch.object(
        movement_tools.ward_resolution, "resolve_scope_ward_with_scope", AsyncMock(return_value=(None, None))
    ):
        return json.loads(
            await _travel_impl(
                ctx,
                DEST,
                mode,
                hours=hours,
                forced_march=forced_march,
                queries=m.queries,
                mutations=m.mutations,
                travel_mutations=m.travel_mutations,
                conditions_mutations=m.conditions_mutations,
                content=m.content,
                db_mod=m.db_mod,
                rng=FixedRng(rng),
            )
        )


@pytest.mark.parametrize("speaker", IDS)
async def test_move_fans_out_from_either_turn(speaker):
    ctx, m = _ctx(), _mocks()
    with ctx.userdata._bind_authenticated_actor(speaker, 4, lambda *_: None):
        result = await _move(ctx, m)
    assert result["moved"] is True
    _arrival_calls(m)
    assert ctx.userdata.location_id == DEST
    assert [ctx.userdata.member_state(pid).corruption_level for pid in IDS] == [3, 3]
    assert [e.event_type for e in published_events(ctx)].count(E.LOCATION_CHANGED) == 1


@pytest.mark.parametrize("speaker", IDS)
@pytest.mark.parametrize("flag_owner", IDS)
async def test_gated_exit_opens_for_either_speaker(speaker, flag_owner):
    ctx, m = _ctx(), _mocks(requires="seal.discovered")
    m.queries.get_player_flag.side_effect = lambda pid, _: pid == flag_owner
    with ctx.userdata._bind_authenticated_actor(speaker, 4, lambda *_: None):
        result = await _move(ctx, m)
    assert result["moved"] is True
    _arrival_calls(m)


@pytest.mark.parametrize("speaker", IDS)
async def test_travel_arrival_clears_every_members_state(speaker):
    ctx, m = _ctx(), _mocks()
    with ctx.userdata._bind_authenticated_actor(speaker, 4, lambda *_: None):
        result = await _travel(ctx, m, mode="compressed")
    assert result["arrived"] is True
    _arrival_calls(m)
    assert ctx.userdata.location_id == DEST
    assert [e.event_type for e in published_events(ctx)].count(E.LOCATION_CHANGED) == 1


@pytest.mark.parametrize("speaker", IDS)
async def test_lost_travel_records_every_members_state(speaker):
    ctx, m = _ctx(), _mocks(terrain="unmarked_wilderness")
    with ctx.userdata._bind_authenticated_actor(speaker, 4, lambda *_: None):
        result = await _travel(ctx, m, rng=1)
    assert result["arrived"] is False
    assert m.travel_mutations.update_player_travel_state.await_args_list == [
        call(pid, {"destination": DEST, "mode": "scenic", "wrong_area": True}, conn=m.conn) for pid in LOCK_ORDER
    ]
    m.mutations.update_player_location.assert_not_awaited()
    m.mutations.upsert_map_progress.assert_not_awaited()
    assert ctx.userdata.location_id == START
    assert [ctx.userdata.member_state(pid).corruption_level for pid in IDS] == [1, 2]


@pytest.mark.parametrize("speaker", IDS)
async def test_forced_march_uses_each_members_rules(speaker):
    def prior(stacks):
        return [{"type": "exhausted", "duration": None, "source": "prior", "stacks": stacks}]

    players = {
        IDS[0]: {"player_id": IDS[0], "conditions": prior(2), "attributes": {"wisdom": 12}, "proficiencies": []},
        IDS[1]: {
            "player_id": IDS[1],
            "conditions": prior(3),
            "skill_tiers": {"endurance": "master"},
            "attributes": {"wisdom": 12},
            "proficiencies": [],
        },
    }
    ctx, m = _ctx(), _mocks(terrain="underground", players=players)
    with ctx.userdata._bind_authenticated_actor(speaker, 4, lambda *_: None):
        result = await _travel(ctx, m, mode="dangerous", hours=12, forced_march=True, rng=1)
    assert result["arrived"] is False
    saves = m.conditions_mutations.save_player_conditions.await_args_list
    assert [entry.args[0] for entry in saves] == LOCK_ORDER
    stacks = {entry.args[0]: next(c["stacks"] for c in entry.args[1] if c["type"] == "exhausted") for entry in saves}
    assert stacks == {IDS[0]: 4, IDS[1]: 3}
    assert all(entry.kwargs["conn"] is m.conn for entry in saves)
    locked = [entry.args[0] for entry in m.queries.get_player.await_args_list if entry.kwargs.get("for_update")]
    assert locked == LOCK_ORDER


async def test_forced_march_fails_loud_on_missing_member_row():
    ctx, m = _ctx(), _mocks(terrain="underground")

    async def get_player(pid, *, for_update=False, **_):
        return (
            None if pid == IDS[1] and for_update else {"player_id": pid, "conditions": [], "attributes": {"wisdom": 12}}
        )

    m.queries.get_player.side_effect = get_player
    with ctx.userdata._bind_authenticated_actor(IDS[0], 4, lambda *_: None):
        with pytest.raises(ToolError, match=rf"{IDS[1]}.*not found"):
            await _travel(ctx, m, mode="dangerous", hours=12, forced_march=True, rng=1)


async def test_guest_scene_uses_speaking_member():
    ctx, m = _ctx(), _mocks()
    m.queries.get_npcs_at_location.return_value = [{"id": "keeper", "name": "Keeper"}]
    m.queries.get_npc_dispositions.side_effect = lambda _, pid: {"keeper": "friendly" if pid == IDS[1] else "hostile"}
    with ctx.userdata._bind_authenticated_actor(IDS[1], 4, lambda *_: None):
        scene = json.loads(await _enter_location_impl(ctx, DEST, content=m.content, queries=m.queries))
        moved = await _move(ctx, m)
    assert scene["player"]["name"] == IDS[1]
    assert moved["player"]["name"] == IDS[1]
    assert scene["npcs"][0]["disposition"] == moved["npcs"][0]["disposition"] == "friendly"
    assert m.queries.get_npc_dispositions.await_args_list == [call(["keeper"], IDS[1])] * 2
    _arrival_calls(m)


async def test_revoked_guest_cannot_move_party():
    ctx, m = _ctx(), _mocks()
    revoked = False

    async def get_location(loc):
        nonlocal revoked
        if loc == DEST:
            revoked = True
        return {START: {"id": START, "exits": {"north": DEST}}, DEST: {"id": DEST}}[loc]

    def validate(*_):
        if revoked:
            raise RuntimeError("revoked")

    m.content.get_location.side_effect = get_location
    with ctx.userdata._bind_authenticated_actor(IDS[1], 4, validate):
        with pytest.raises(RuntimeError, match="revoked"):
            await _move(ctx, m)
    m.mutations.update_player_location.assert_not_awaited()
    m.mutations.upsert_map_progress.assert_not_awaited()
    m.travel_mutations.update_player_travel_state.assert_not_awaited()


@pytest.mark.parametrize("forced_march", [False, True])
@pytest.mark.parametrize("speaker", IDS)
async def test_only_the_speakers_inspired_die_is_spent(speaker, forced_march):
    inspired = conditions.apply_condition([], "inspired")
    players = {
        pid: {"player_id": pid, "conditions": inspired, "attributes": {"wisdom": 12}, "proficiencies": []}
        for pid in IDS
    }
    ctx, m = _ctx(), _mocks(terrain="unmarked_wilderness", players=players)
    with ctx.userdata._bind_authenticated_actor(speaker, 4, lambda *_: None):
        await _travel(ctx, m, hours=12, forced_march=forced_march, rng=20)
    saved = {
        entry.args[0]: [c["type"] for c in entry.args[1]]
        for entry in m.conditions_mutations.save_player_conditions.await_args_list
    }
    assert sorted(saved) == sorted(IDS if forced_march else (speaker,))
    assert {pid: "inspired" in types for pid, types in saved.items()} == {pid: pid != speaker for pid in saved}


@pytest.mark.parametrize(
    ("terrain", "forced_march"),
    [("established_road", False), ("unmarked_wilderness", False), ("underground", True)],
    ids=["arrival", "lost", "forced-march"],
)
async def test_revoked_guest_cannot_travel_party(terrain, forced_march):
    ctx, m = _ctx(), _mocks(terrain=terrain)
    revoked = False
    locations = m.content.get_location.side_effect

    async def get_location(loc):
        nonlocal revoked
        revoked = True
        return locations(loc)

    def validate(*_):
        if revoked:
            raise RuntimeError("revoked")

    m.content.get_location.side_effect = get_location
    with ctx.userdata._bind_authenticated_actor(IDS[1], 4, validate):
        with pytest.raises(RuntimeError, match="revoked"):
            await _travel(ctx, m, hours=12, forced_march=forced_march, rng=1)
    m.conditions_mutations.save_player_conditions.assert_not_awaited()
    m.mutations.update_player_location.assert_not_awaited()
    m.travel_mutations.update_player_travel_state.assert_not_awaited()
