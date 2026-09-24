import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from check_discovery import _check_discover_impl
from conditions import apply_condition
from tools._discover_fixtures import DISCOVER_PLAYER, _make_discover_mocks, _roll
from tools._helpers import _make_context, _make_mock_room

FIXTURE = json.loads((Path(__file__).resolve().parents[4] / "packages/shared/fixtures/event_wire.json").read_text())[
    "events"
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "die", "player", "expected"),
    [
        ("failed", 3, DISCOVER_PLAYER, ["discover_failed"]),
        (
            "no_candidate",
            3,
            {**DISCOVER_PLAYER, "flags": {"secret_door.discovered": True}},
            ["discover_no_candidate"],
        ),
        ("success", 15, DISCOVER_PLAYER, ["discover_success", "discover_reveal_cue"]),
    ],
)
async def test_live_discover_wire_matches_fixture(case, die, player, expected):
    room = _make_mock_room()
    room.isconnected.return_value = True
    ctx = _make_context(location_id="test_location", room=room)
    content, queries, mutations = _make_discover_mocks(player=player)
    with patch("check_resolution.dice_roll", return_value=_roll(die)):
        result = json.loads(
            await _check_discover_impl(
                ctx, "perception", "bookshelf", content=content, queries=queries, mutations=mutations
            )
        )
    packets = [json.loads(call.args[0]) for call in room.local_participant.publish_data.await_args_list]
    client_packets = [packet for packet in packets if packet["type"] != "hidden_revealed"]
    assert client_packets == [FIXTURE[name] for name in expected]
    if case == "success":
        assert result["outcome"] == "discovered"
        assert [packet["type"] for packet in packets] == ["dice_roll", "play_sound", "hidden_revealed"]
        mutations.set_player_flag.assert_awaited_once()
    else:
        assert result["outcome"] == "not_found"
        mutations.set_player_flag.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_search_keeps_flat_penalty():
    conditions = apply_condition(apply_condition([], "exhausted"), "exhausted")
    player = {**DISCOVER_PLAYER, "conditions": conditions}
    empty_player = {**player, "flags": {"secret_door.discovered": True}}
    packets = []
    for candidate_player in (player, empty_player):
        content, queries, mutations = _make_discover_mocks(player=candidate_player)
        ctx = _make_context(location_id="test_location")
        ctx.userdata.event_bus = MagicMock()
        condition_writes = MagicMock(remove_player_conditions=AsyncMock())
        with patch("check_resolution.dice_roll", return_value=_roll(3)) as dice:
            await _check_discover_impl(
                ctx,
                "perception",
                "bookshelf",
                content=content,
                queries=queries,
                mutations=mutations,
                conditions_mutations=condition_writes,
            )
        event = ctx.userdata.event_bus.publish.call_args_list[0].args[0]
        packets.append(event.payload)
        if candidate_player is empty_player:
            assert dice.call_count == 1
            condition_writes.remove_player_conditions.assert_not_awaited()
            mutations.set_player_flag.assert_not_awaited()
    assert packets[0]["total"] - packets[0]["roll"] == packets[1]["total"] - packets[1]["roll"]
    assert packets[1]["total"] - packets[1]["roll"] == 4


@pytest.mark.asyncio
async def test_empty_search_never_spends_inspired():
    player = {
        **DISCOVER_PLAYER,
        "conditions": apply_condition([], "inspired"),
        "flags": {"secret_door.discovered": True},
    }
    content, queries, mutations = _make_discover_mocks(player=player)
    condition_writes = MagicMock(remove_player_conditions=AsyncMock())
    ctx = _make_context(location_id="test_location")
    with patch("check_resolution.dice_roll", return_value=_roll(3)) as dice:
        await _check_discover_impl(
            ctx,
            "perception",
            "bookshelf",
            content=content,
            queries=queries,
            mutations=mutations,
            conditions_mutations=condition_writes,
        )
    assert dice.call_count == 1
    condition_writes.remove_player_conditions.assert_not_awaited()
    mutations.set_player_flag.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_search_uses_blinded_disadvantage():
    player = {
        **DISCOVER_PLAYER,
        "conditions": apply_condition([], "blinded"),
        "flags": {"secret_door.discovered": True},
    }
    content, queries, mutations = _make_discover_mocks(player=player)
    ctx = _make_context(location_id="test_location")
    ctx.userdata.event_bus = MagicMock()
    with patch("check_resolution.dice_roll", side_effect=[_roll(17), _roll(4)]) as dice:
        await _check_discover_impl(
            ctx, "perception", "bookshelf", content=content, queries=queries, mutations=mutations
        )
    assert dice.call_count == 2
    assert ctx.userdata.event_bus.publish.call_args.args[0].payload["roll"] == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(("die", "context"), [(1, "natural_1"), (20, "natural_20")])
async def test_empty_search_keeps_natural_dramatic_metadata(die, context):
    player = {**DISCOVER_PLAYER, "flags": {"secret_door.discovered": True}}
    content, queries, mutations = _make_discover_mocks(player=player)
    ctx = _make_context(location_id="test_location")
    ctx.userdata.event_bus = MagicMock()
    with patch("check_resolution.dice_roll", return_value=_roll(die)):
        await _check_discover_impl(
            ctx, "perception", "bookshelf", content=content, queries=queries, mutations=mutations
        )
    packet = ctx.userdata.event_bus.publish.call_args.args[0].payload
    assert packet["dramatic"] is True
    assert packet["context"] == context


@pytest.mark.asyncio
@pytest.mark.parametrize("rollback", [False, True])
async def test_reveal_cue_waits_for_condition_transaction_commit(rollback):
    player = {**DISCOVER_PLAYER, "conditions": apply_condition([], "inspired")}
    content, queries, mutations = _make_discover_mocks(player=player)
    condition_writes = MagicMock(remove_player_conditions=AsyncMock())
    ctx = _make_context(location_id="test_location")
    state = {"flag_written": False, "committed": False}

    async def set_flag(*_args, **_kwargs):
        state["flag_written"] = True

    @asynccontextmanager
    async def transaction():
        yield object()
        if rollback:
            raise RuntimeError("rollback")
        state["committed"] = True

    async def cue(*_args):
        assert state == {"flag_written": True, "committed": True}

    mutations.set_player_flag.side_effect = set_flag
    db_mod = MagicMock(transaction=transaction)
    with (
        patch("check_resolution.dice_roll", side_effect=[_roll(1), _roll(15)]),
        patch("check_discovery.publish_action_sound", new_callable=AsyncMock, side_effect=cue) as sound,
    ):
        if rollback:
            with pytest.raises(RuntimeError, match="rollback"):
                await _check_discover_impl(
                    ctx,
                    "perception",
                    "bookshelf",
                    content=content,
                    queries=queries,
                    mutations=mutations,
                    conditions_mutations=condition_writes,
                    db_mod=db_mod,
                )
            sound.assert_not_awaited()
            assert not ctx.userdata.attempted_discoveries
        else:
            await _check_discover_impl(
                ctx,
                "perception",
                "bookshelf",
                content=content,
                queries=queries,
                mutations=mutations,
                conditions_mutations=condition_writes,
                db_mod=db_mod,
            )
            sound.assert_awaited_once()
            assert sound.await_args is not None
            assert sound.await_args.args[1] == "action_discover_reveal"
    condition_writes.remove_player_conditions.assert_awaited_once()
