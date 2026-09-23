import asyncio
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from combat._helpers import _make_combat_state
from livekit.agents.llm import ToolError
from sample_fixtures import FixedRng, make_context, published_events

import event_types as E
import movement_tools
import veil_ward
from ability_tools import _request_ability_activation_impl
from action_sound_content import ACTION_SOUND_IDS
from activate_tools import _activate_impl
from gathering_tools import _check_gather_impl
from movement_tools import _move_player_impl
from travel_tools import _travel_impl
from veil_anchor_tools import _deploy_veil_anchor_impl
from veil_ward_tools import _activate_veil_ward_impl

CASES = {
    "travel": "action_travel",
    "move": "action_move",
    "ward_raise": "action_veil_ward_raise",
    "ward_dismiss": "action_veil_ward_dismiss",
    "anchor": "action_veil_anchor",
    "ability": "action_ability",
    "gather": "action_gather",
}


def test_fixed_seven_cases_cover_the_loaded_catalog():
    assert len(CASES) == 7
    assert set(CASES.values()) == ACTION_SOUND_IDS


def recorded_context():
    ctx = make_context()
    log = []
    original = ctx.userdata.event_bus.publish

    def record(event):
        if event.event_type == E.PLAY_SOUND:
            log.append(("cue", event.payload["sound_name"]))
        return original(event)

    ctx.userdata.event_bus.publish = MagicMock(side_effect=record)
    return ctx, log


def db_with_commit(log):
    db = MagicMock()
    conn = MagicMock()

    @asynccontextmanager
    async def transaction():
        yield conn
        log.append(("commit", None))

    db.transaction = transaction
    db.extract_exit_connections = lambda exits: []
    return db, conn


def cues(ctx):
    return [e.payload["sound_name"] for e in published_events(ctx) if e.event_type == E.PLAY_SOUND]


def assert_committed_cue(ctx, log, expected):
    assert cues(ctx) == [expected]
    assert log.index(("commit", None)) < log.index(("cue", expected))


def arrival_mocks(log, *, exit=True, requires=None):
    db, conn = db_with_commit(log)
    start = {
        "id": "accord_guild_hall",
        "exits": {"north": {"destination": "dest", **({"requires": requires} if requires else {})}} if exit else {},
    }
    dest = {"id": "dest", "name": "Destination", "terrain": "established_road", "exits": {}}
    content = MagicMock(get_location=AsyncMock(side_effect=lambda id: {"accord_guild_hall": start, "dest": dest}[id]))
    mutations = MagicMock(update_player_location=AsyncMock(), upsert_map_progress=AsyncMock())
    travel = MagicMock(update_player_travel_state=AsyncMock())
    queries = MagicMock(
        get_player=AsyncMock(return_value={"player_id": "player_1", "conditions": []}),
        get_player_flag=AsyncMock(return_value=False),
    )
    return MagicMock(db=db, conn=conn, content=content, mutations=mutations, travel=travel, queries=queries)


async def move(ctx, m):
    with patch.object(
        movement_tools.ward_resolution, "resolve_scope_ward_with_scope", AsyncMock(return_value=(None, None))
    ):
        return await _move_player_impl(
            ctx,
            "dest",
            db_mod=m.db,
            mutations=m.mutations,
            travel_mutations=m.travel,
            queries=m.queries,
            content=m.content,
        )


async def travel(ctx, m):
    with patch.object(
        movement_tools.ward_resolution, "resolve_scope_ward_with_scope", AsyncMock(return_value=(None, None))
    ):
        return await _travel_impl(
            ctx,
            "dest",
            "compressed",
            queries=m.queries,
            mutations=m.mutations,
            travel_mutations=m.travel,
            content=m.content,
            db_mod=m.db,
            rng=FixedRng(1),
        )


async def test_travel_cue_follows_arrival_commit_and_survives_later_failure():
    ctx, log = recorded_context()
    m = arrival_mocks(log)
    result = json.loads(await travel(ctx, m))
    assert result["arrived"] is True
    m.mutations.update_player_location.assert_awaited_once()
    assert_committed_cue(ctx, log, CASES["travel"])
    ctx, log = recorded_context()
    m = arrival_mocks(log)
    ctx.userdata.record_event = MagicMock(side_effect=RuntimeError("later"))
    with pytest.raises(RuntimeError, match="later"):
        await travel(ctx, m)
    assert_committed_cue(ctx, log, CASES["travel"])


async def test_move_cue_precedes_delayed_scene_and_survives_later_failure():
    ctx, log = recorded_context()
    m = arrival_mocks(log)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def delayed_scene(*args, **kwargs):
        entered.set()
        await release.wait()
        return {"npcs": [], "targets": []}

    with patch("scene_tools._build_scene_context", delayed_scene):
        task = asyncio.create_task(move(ctx, m))
        await asyncio.wait_for(entered.wait(), 2)
        assert_committed_cue(ctx, log, CASES["move"])
        assert not task.done()
        release.set()
        moved = await task
        assert isinstance(moved, str)
        result = json.loads(moved)
    assert result["moved"] is True
    m.mutations.update_player_location.assert_awaited_once()
    ctx, log = recorded_context()
    m = arrival_mocks(log)
    with patch("scene_tools._build_scene_context", AsyncMock(side_effect=RuntimeError("later"))):
        with pytest.raises(RuntimeError, match="later"):
            await move(ctx, m)
    assert_committed_cue(ctx, log, CASES["move"])


async def test_move_refusals_publish_no_action_cue():
    for m_args, error in [({"exit": False}, True), ({"requires": "locked.discovered"}, False)]:
        ctx, log = recorded_context()
        m = arrival_mocks(log, **m_args)
        if error:
            with pytest.raises(ToolError, match="No exit"):
                await move(ctx, m)
        else:
            blocked = await move(ctx, m)
            assert isinstance(blocked, str)
            assert json.loads(blocked)["blocked"] is True
            m.queries.get_player_flag.assert_awaited()
        m.mutations.update_player_location.assert_not_awaited()
        assert cues(ctx) == []


def ward_mocks(log):
    db, _conn = db_with_commit(log)
    queries = MagicMock(
        get_player=AsyncMock(
            return_value={"class": "cleric", "level": 7, "focus": {"current": 10}, "stamina": {"current": 10}}
        )
    )
    persistence = MagicMock(update_player_resources=AsyncMock())
    ward = MagicMock(
        write_ward=AsyncMock(), dismiss_ward=AsyncMock(return_value=1), read_active_ward=AsyncMock(return_value=None)
    )
    resolution = MagicMock(resolve_scope_ward=AsyncMock(return_value=None))
    combat = MagicMock(save_combat_state=AsyncMock())
    return db, queries, persistence, ward, resolution, combat


async def test_ward_raise_and_dismiss_publish_after_commit():
    for active, key in [(True, "ward_raise"), (False, "ward_dismiss")]:
        ctx, log = recorded_context()
        db, queries, persistence, ward, resolution, combat = ward_mocks(log)
        raw = await _activate_veil_ward_impl(
            ctx,
            active,
            db_mod=db,
            queries_mod=queries,
            persistence_mod=persistence,
            ward_mutations_mod=ward,
            resolution_mod=resolution,
            combat_mod=combat,
        )
        assert json.loads(raw)["active"] is active
        (ward.write_ward if active else ward.dismiss_ward).assert_awaited_once()
        assert_committed_cue(ctx, log, CASES[key])


async def test_anchor_publishes_after_commit_and_refusal_does_not():
    ctx, log = recorded_context()
    db, _conn = db_with_commit(log)
    queries = MagicMock(get_inventory_item=AsyncMock(return_value={"quantity": 1}))
    inventory = MagicMock(transact_inventory=AsyncMock())
    ward = MagicMock(write_ward=AsyncMock(), read_active_ward=AsyncMock(return_value=None))
    resolution = MagicMock(resolve_scope_ward=AsyncMock(return_value=None))
    item_id = next(iter(veil_ward.VEIL_ANCHORS))
    raw = await _deploy_veil_anchor_impl(
        ctx,
        item_id,
        db_mod=db,
        queries_mod=queries,
        inventory_mutations_mod=inventory,
        ward_mutations_mod=ward,
        resolution_mod=resolution,
    )
    assert json.loads(raw)["active"] is True
    ward.write_ward.assert_awaited_once()
    assert_committed_cue(ctx, log, CASES["anchor"])
    ctx, log = recorded_context()
    queries.get_inventory_item = AsyncMock(return_value=None)
    with pytest.raises(ToolError, match="not in inventory"):
        await _deploy_veil_anchor_impl(
            ctx,
            item_id,
            db_mod=db,
            queries_mod=queries,
            inventory_mutations_mod=inventory,
            ward_mutations_mod=ward,
            resolution_mod=resolution,
        )
    assert queries.get_inventory_item.await_count == 1
    assert cues(ctx) == []


async def test_ability_success_and_router_or_delegate_refusals():
    ctx, _log = recorded_context()
    ability = MagicMock(_request_ability_activation_impl=AsyncMock(return_value='{"activated": true}'))
    raw = await _activate_impl(ctx, "warrior_devastating_strike", ability_mod=ability)
    assert json.loads(raw)["activated"] is True
    ability._request_ability_activation_impl.assert_awaited_once()
    assert cues(ctx) == [CASES["ability"]]
    ctx, _log = recorded_context()
    with pytest.raises(ToolError, match="not an activatable"):
        await _activate_impl(ctx, "unknown_action_ability")
    assert cues(ctx) == []
    ability._request_ability_activation_impl = AsyncMock(side_effect=ToolError("delegate refused"))
    with pytest.raises(ToolError, match="delegate refused"):
        await _activate_impl(ctx, "warrior_devastating_strike", ability_mod=ability)
    ability._request_ability_activation_impl.assert_awaited_once()
    assert cues(ctx) == []


async def test_real_ability_debit_commits_before_cue():
    ctx, log = recorded_context()
    db, conn = db_with_commit(log)
    player = {
        "player_id": "player_1",
        "name": "Kael",
        "class": "warrior",
        "level": 5,
        "stamina": {"current": 10, "max": 10},
        "focus": {"current": 10, "max": 10},
    }
    queries = MagicMock(get_players_for_update=AsyncMock(return_value={"player_1": player}))
    persistence = MagicMock(
        update_player_resources=AsyncMock(side_effect=lambda *a, **k: log.append(("debit", k["stamina"]))),
        get_active_variant=AsyncMock(return_value=None),
        owns_elective=AsyncMock(return_value=False),
    )

    async def activate_ability(context, ability_id, **kwargs):
        return await _request_ability_activation_impl(
            context, ability_id, db_mod=db, queries_mod=queries, persistence_mod=persistence, **kwargs
        )

    with ctx.userdata._bind_authenticated_actor("player_1", 1, lambda *_: None):
        raw = await _activate_impl(
            ctx,
            "warrior_devastating_strike",
            ability_mod=MagicMock(_request_ability_activation_impl=activate_ability),
        )
    assert json.loads(raw)["deducted"]["stamina"] > 0
    persistence.update_player_resources.assert_awaited_once()
    assert persistence.update_player_resources.await_args.kwargs["conn"] is conn
    assert log.index(next(entry for entry in log if entry[0] == "debit")) < log.index(("commit", None))
    assert_committed_cue(ctx, log, CASES["ability"])


async def test_in_combat_ability_activates_without_action_cue():
    ctx, _log = recorded_context()
    ctx.userdata.combat_state = _make_combat_state()
    ability = MagicMock(_request_ability_activation_impl=AsyncMock(return_value='{"activated": true}'))
    raw = await _activate_impl(ctx, "warrior_devastating_strike", ability_mod=ability)
    assert json.loads(raw)["activated"] is True
    ability._request_ability_activation_impl.assert_awaited_once()
    assert cues(ctx) == []


async def test_spell_backed_ability_uses_spell_sound_only():
    ctx, _log = recorded_context()
    spell = MagicMock(_cast_spell_impl=AsyncMock(return_value='{"cast": true}'))
    raw = await _activate_impl(ctx, "mage_arcane_bolt", cast_spell_mod=spell)
    assert json.loads(raw)["cast"] is True
    spell._cast_spell_impl.assert_awaited_once_with(ctx, "arcane_bolt", target_id=None, target_ids=None)
    assert not set(cues(ctx)) & ACTION_SOUND_IDS


async def test_gather_cue_follows_grant_commit_and_absence_branches():
    from tools._helpers import SAMPLE_PLAYER

    location = {"region": "greyvale", "resource_table": {"common": ["medicinal_herb"], "uncommon": [], "rare": []}}

    async def invoke(ctx, log, *, roll, available=True):
        db, _conn = db_with_commit(log)
        queries = MagicMock(get_player=AsyncMock(return_value=SAMPLE_PLAYER))
        mutations = MagicMock(add_inventory_item=AsyncMock(side_effect=lambda *a, **k: log.append(("grant", a[1]))))
        content = MagicMock(
            get_location=AsyncMock(return_value=location if available else {"region": "greyvale"}),
            get_gathering_nodes_at_location=AsyncMock(return_value=[]),
        )
        gathering = MagicMock(mark_node_discovered=AsyncMock(), deplete_node_quantity=AsyncMock())
        raw = await _check_gather_impl(
            ctx,
            "",
            queries=queries,
            mutations=mutations,
            content=content,
            gather_mutations=gathering,
            db_mod=db,
            rng=FixedRng(roll),
        )
        return json.loads(raw), mutations

    ctx, log = recorded_context()
    result, mutations = await invoke(ctx, log, roll=20)
    assert result["materials"]
    mutations.add_inventory_item.assert_awaited()
    assert log.index(next(entry for entry in log if entry[0] == "grant")) < log.index(("commit", None))
    assert_committed_cue(ctx, log, CASES["gather"])
    ctx, log = recorded_context()
    with patch("gathering_tools.check_resolution.resolve_skill_check_dc") as resolver:
        with pytest.raises(ToolError, match="Nothing to forage"):
            await invoke(ctx, log, roll=20, available=False)
        resolver.assert_not_called()
    assert cues(ctx) == []
    ctx, log = recorded_context()
    result, mutations = await invoke(ctx, log, roll=1)
    assert result["materials"] == []
    mutations.add_inventory_item.assert_not_awaited()
    assert cues(ctx) == []
