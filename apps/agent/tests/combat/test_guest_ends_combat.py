import copy
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from _combat_end_fixtures import combat_end_mutations, combat_end_queries
from combat._helpers import _ctx_at_resolution, _fake_db_mod, _make_combat_state, _resolution_state, _resolve_deps
from combat.test_combat_init_multiplayer import _add_second_member, _second_member_row
from combat.test_start_combat import _make_start_combat_mocks, _stance_mocks
from livekit.agents.llm import ToolError
from sample_fixtures import SAMPLE_PLAYER, make_context, make_mock_room

from combat_end import _end_combat_db, _end_combat_impl
from combat_events import EventSink
from combat_init import _start_combat_impl
from combat_rewards import EncounterSpoils
from session_end import run_guest_departure, run_session_end
from session_summary import generate_session_summary


async def named_recap(sd, player_id):
    with (
        patch("session_summary._call_llm_summary", new_callable=AsyncMock, return_value=None),
        patch("db_activity_queries.get_session_story_moments", new_callable=AsyncMock, return_value=[]),
    ):
        return await generate_session_summary(sd, None, player_id=player_id)


async def saved_party_recaps(sd):
    sd.room = make_mock_room()
    sd.room.name = "test-room"
    sd.multiplayer_owner = SimpleNamespace(lifecycle=MagicMock())
    sd.departing_player_id = "player_2"
    with (
        patch("session_summary._call_llm_summary", new_callable=AsyncMock, return_value=None),
        patch("db_activity_queries.get_session_story_moments", new_callable=AsyncMock, return_value=[]),
        patch("session_end.publish_game_event", new_callable=AsyncMock),
        patch("session_end.room_admin.remove_player", new_callable=AsyncMock),
        patch("session_end.db_mutations.save_session_summary", new_callable=AsyncMock) as save,
    ):
        await run_guest_departure(sd, "player_2", MagicMock())
        await run_session_end(sd)
    return {call.args[0]: call.args[2]["items_found"] for call in save.await_args_list}


@pytest.mark.asyncio
async def test_guest_enters_combat_with_both_members():
    mutations, queries, content = _make_start_combat_mocks()
    ctx = make_context()
    _add_second_member(ctx)
    queries.get_player = AsyncMock(side_effect=lambda pid: _second_member_row() if pid == "player_2" else None)
    queries.get_players_for_update = AsyncMock(return_value={"player_1": _second_member_row()})
    with ctx.userdata._bind_authenticated_actor("player_2", 1, lambda *_: None):
        await _start_combat_impl(
            ctx, "goblin_patrol", "A goblin patrol.", mutations=mutations, queries=queries, content=content
        )
    state = mutations.save_combat_state.call_args.args[1]
    assert {p["id"] for p in state["participants"] if p["type"] == "player"} == {"player_1", "player_2"}


@pytest.mark.asyncio
async def test_guest_stance_gate_reads_guest_reputation():
    mutations, queries, content = _stance_mocks(4)
    ctx = make_context()
    _add_second_member(ctx)
    queries.get_player = AsyncMock(return_value=_second_member_row())
    queries.get_players_for_update = AsyncMock(return_value={"player_1": _second_member_row()})
    with ctx.userdata._bind_authenticated_actor("player_2", 1, lambda *_: None):
        await _start_combat_impl(
            ctx, "ashmark_patrol", "A patrol approaches.", mutations=mutations, queries=queries, content=content
        )
    queries.get_player_faction_reputation.assert_awaited_once_with("player_2", "thornwatch")


@pytest.mark.asyncio
async def test_guest_revoked_before_combat_save_starts_nothing():
    mutations, queries, content = _make_start_combat_mocks()
    ctx = make_context()
    _add_second_member(ctx)
    queries.get_player = AsyncMock(return_value=_second_member_row())
    queries.get_players_for_update = AsyncMock(return_value={"player_1": SAMPLE_PLAYER})
    checks = []

    def validate(*_):
        checks.append(1)
        if len(checks) > 1:
            raise RuntimeError("stale")

    with ctx.userdata._bind_authenticated_actor("player_2", 1, validate):
        with pytest.raises(RuntimeError, match="stale"):
            await _start_combat_impl(
                ctx, "goblin_patrol", "A goblin patrol.", mutations=mutations, queries=queries, content=content
            )
    mutations.save_combat_state.assert_not_awaited()
    assert ctx.userdata.combat_state is None


@pytest.mark.asyncio
async def test_guest_started_combat_scales_companion_to_its_owner():
    mutations, queries, content = _make_start_combat_mocks()
    ctx = make_context(companion_id="companion_kael")
    _add_second_member(ctx)
    queries.get_player = AsyncMock(return_value=_second_member_row())
    queries.get_players_for_update = AsyncMock(return_value={"player_1": SAMPLE_PLAYER})
    with ctx.userdata._bind_authenticated_actor("player_2", 1, lambda *_: None):
        await _start_combat_impl(
            ctx, "goblin_patrol", "A goblin patrol.", mutations=mutations, queries=queries, content=content
        )
    state = mutations.save_combat_state.call_args.args[1]
    kael = next(p for p in state["participants"] if p["id"] == "companion_kael")
    assert kael["hp_max"] == 21


@pytest.mark.asyncio
async def test_guest_end_combat_commits_and_cannot_pay_twice():
    ctx = make_context()
    _add_second_member(ctx)
    cs = _make_combat_state(enemy_fallen=True)
    guest = copy.deepcopy(cs.participants[0])
    guest.id = "player_2"
    cs.participants.insert(1, guest)
    ctx.userdata.combat_state = cs
    mutations = combat_end_mutations()
    with ctx.userdata._bind_authenticated_actor("player_2", 1, lambda *_: None):
        _, raw = await _end_combat_impl(ctx, "victory", mutations=mutations, db_mod=_fake_db_mod())
        with pytest.raises(ToolError, match="Not in combat"):
            await _end_combat_impl(ctx, "victory", mutations=mutations, db_mod=_fake_db_mod())
    assert json.loads(raw)["outcome"] == "victory"
    assert ctx.userdata.combat_state is None
    mutations.delete_combat_state.assert_awaited_once()
    assert {call.args[0] for call in mutations.update_player_xp.await_args_list} == {"player_1", "player_2"}
    # Each member's goodbye recap counts their own share, not only the host's.
    earned = {pid: ctx.userdata.player_summary_metrics[pid]["xp_earned"] for pid in ("player_1", "player_2")}
    assert earned["player_1"] == earned["player_2"] > 0


@pytest.mark.asyncio
async def test_guest_combat_xp_does_not_enter_host_summary_when_host_receives_none():
    ctx = make_context()
    _add_second_member(ctx)
    cs = _make_combat_state(enemy_fallen=True)
    guest = copy.deepcopy(cs.participants[0])
    guest.id = "player_2"
    cs.participants.insert(1, guest)
    ctx.userdata.combat_state = cs
    queries = combat_end_queries(
        get_player=AsyncMock(side_effect=lambda pid, **_kw: None if pid == "player_1" else _second_member_row())
    )
    mutations = combat_end_mutations()
    with ctx.userdata._bind_authenticated_actor("player_2", 1, lambda *_: None):
        _, raw = await _end_combat_impl(ctx, "victory", mutations=mutations, queries=queries, db_mod=_fake_db_mod())
    assert json.loads(raw)["xp_granted"] > 0
    assert [call.args[0] for call in mutations.update_player_xp.await_args_list] == ["player_2"]
    assert ctx.userdata.session_xp_earned == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("speaker", ["player_1", "player_2"])
@pytest.mark.parametrize("outcome,enemy_fallen", [("victory", True), ("deescalated", False)])
async def test_combat_faction_outcome_reaches_each_member(speaker, outcome, enemy_fallen):
    ctx = make_context()
    _add_second_member(ctx)
    cs = _make_combat_state(enemy_fallen=enemy_fallen)
    guest = copy.deepcopy(cs.participants[0])
    guest.id = "player_2"
    cs.participants.insert(1, guest)
    cs.faction_id = "thornwatch"
    ctx.userdata.combat_state = cs
    reputation = AsyncMock()
    with patch("combat_end.db_mutations_reputation.adjust_player_faction_reputation", reputation):
        with ctx.userdata._bind_authenticated_actor(speaker, 1, lambda *_: None):
            if outcome == "deescalated":
                await _end_combat_db(
                    ctx.userdata,
                    cs,
                    outcome,
                    conn=AsyncMock(),
                    sink=EventSink(),
                    mutations=combat_end_mutations(),
                    queries=combat_end_queries(),
                )
            else:
                await _end_combat_impl(ctx, outcome, mutations=combat_end_mutations(), db_mod=_fake_db_mod())
    assert [call.args[0] for call in reputation.await_args_list] == ["player_1", "player_2"]
    assert all(call.args[1] == "thornwatch" and call.kwargs["conn"] is not None for call in reputation.await_args_list)


@pytest.mark.asyncio
async def test_guest_end_combat_grants_each_members_loot_and_coin():
    ctx = make_context()
    _add_second_member(ctx)
    cs = _make_combat_state(enemy_fallen=True)
    guest = copy.deepcopy(cs.participants[0])
    guest.id = "player_2"
    cs.participants.insert(1, guest)
    ctx.userdata.combat_state = cs
    mutations = combat_end_mutations()
    mutations.add_inventory_item = AsyncMock()
    mutations.update_player_gold = AsyncMock()
    spoils = EncounterSpoils(
        xp_total=50,
        currency_silver=20,
        loot_pool=[{"item_id": "relic", "quantity": 1}, {"item_id": "gem", "quantity": 1}],
        defeated_enemies=["Goblin Scout"],
    )
    with patch("combat_end.combat_rewards.roll_encounter_spoils", AsyncMock(return_value=spoils)):
        with patch("pricing_queries.get_economy_pricing", AsyncMock(return_value={"silver_per_gold": 10})):
            with patch(
                "db_content_queries.get_item",
                AsyncMock(side_effect=lambda item_id: {"name": {"relic": "Sun Relic", "gem": "Blue Gem"}[item_id]}),
            ):
                with ctx.userdata._bind_authenticated_actor("player_2", 1, lambda *_: None):
                    _, raw = await _end_combat_impl(
                        ctx, "victory", mutations=mutations, queries=combat_end_queries(), db_mod=_fake_db_mod()
                    )
    assert [call.args[:2] for call in mutations.add_inventory_item.await_args_list] == [
        ("player_1", "relic"),
        ("player_2", "gem"),
    ]
    assert ctx.userdata.player_summary_metrics["player_1"]["items_found"] == ["Sun Relic"]
    assert ctx.userdata.player_summary_metrics["player_2"]["items_found"] == ["Blue Gem"]
    assert ctx.userdata.session_items_found == ["Sun Relic"]
    assert (await named_recap(ctx.userdata, "player_1"))["items_found"] == ["Sun Relic"]
    assert (await named_recap(ctx.userdata, "player_2"))["items_found"] == ["Blue Gem"]
    assert await saved_party_recaps(ctx.userdata) == {
        "player_1": ["Sun Relic"],
        "player_2": ["Blue Gem"],
    }
    assert {call.args[0] for call in mutations.update_player_gold.await_args_list} == {"player_1", "player_2"}
    assert json.loads(raw)["loot"] == [{"item_id": "gem", "quantity": 1}]
    assert json.loads(raw)["currency_gold"] > 0


@pytest.mark.asyncio
async def test_guest_final_blow_ends_resolve_phase_and_pays_both():
    state = _resolution_state(player_id="player_2", enemy_hp=4)
    host = copy.deepcopy(state.participants[0])
    host.id = "player_1"
    state.participants.insert(0, host)
    state.initiative_order.insert(0, "player_1")
    state.pending_declarations["player_1"] = {"type": "defend"}
    ctx = _ctx_at_resolution(state=state)
    _add_second_member(ctx)
    deps = _resolve_deps(damage=10)
    spoils = EncounterSpoils(
        xp_total=50, loot_pool=[{"item_id": "relic", "quantity": 1}, {"item_id": "gem", "quantity": 1}]
    )
    deps["mutations"].add_inventory_item = AsyncMock()
    with ctx.userdata._bind_authenticated_actor("player_2", 1, lambda *_: None):
        import combat_turn

        with patch("combat_end.combat_rewards.roll_encounter_spoils", AsyncMock(return_value=spoils)):
            with patch(
                "db_content_queries.get_item",
                AsyncMock(side_effect=lambda item_id: {"name": {"relic": "Sun Relic", "gem": "Blue Gem"}[item_id]}),
            ):
                await combat_turn._resolve_phase_impl(ctx, **deps)
                result = await combat_turn._resolve_phase_impl(ctx, **deps)
    assert isinstance(result, tuple)
    assert ctx.userdata.combat_state is None
    deps["mutations"].delete_combat_state.assert_awaited_once()
    assert {call.args[0] for call in deps["mutations"].update_player_xp.await_args_list} == {"player_1", "player_2"}
    assert [call.args[:2] for call in deps["mutations"].add_inventory_item.await_args_list] == [
        ("player_1", "relic"),
        ("player_2", "gem"),
    ]
    assert ctx.userdata.player_summary_metrics["player_1"]["items_found"] == ["Sun Relic"]
    assert ctx.userdata.player_summary_metrics["player_2"]["items_found"] == ["Blue Gem"]
    assert (await named_recap(ctx.userdata, "player_1"))["items_found"] == ["Sun Relic"]
    assert (await named_recap(ctx.userdata, "player_2"))["items_found"] == ["Blue Gem"]
    assert await saved_party_recaps(ctx.userdata) == {
        "player_1": ["Sun Relic"],
        "player_2": ["Blue Gem"],
    }


@pytest.mark.asyncio
async def test_identical_combat_drops_count_one_display_name():
    ctx = make_context()
    ctx.userdata.combat_state = _make_combat_state(enemy_fallen=True)
    mutations = combat_end_mutations()
    mutations.add_inventory_item = AsyncMock()
    spoils = EncounterSpoils(loot_pool=[{"item_id": "relic", "quantity": 1}] * 2)
    with (
        patch("combat_end.combat_rewards.roll_encounter_spoils", AsyncMock(return_value=spoils)),
        patch("db_content_queries.get_item", AsyncMock(return_value={"name": "Sun Relic"})),
    ):
        await _end_combat_impl(ctx, "victory", mutations=mutations, db_mod=_fake_db_mod())
    assert mutations.add_inventory_item.await_count == 2
    assert ctx.userdata.player_summary_metrics["player_1"]["items_found"] == ["Sun Relic"]
    assert ctx.userdata.session_items_found == ["Sun Relic"]
    assert (await named_recap(ctx.userdata, "player_1"))["items_found"] == ["Sun Relic"]


@pytest.mark.asyncio
async def test_combat_commit_failure_records_no_items():
    ctx = make_context()
    _add_second_member(ctx)
    cs = _make_combat_state(enemy_fallen=True)
    guest = copy.deepcopy(cs.participants[0])
    guest.id = "player_2"
    cs.participants.insert(1, guest)
    ctx.userdata.combat_state = cs
    mutations = combat_end_mutations()
    mutations.add_inventory_item = AsyncMock()
    spoils = EncounterSpoils(loot_pool=[{"item_id": "relic", "quantity": 1}, {"item_id": "gem", "quantity": 1}])

    @asynccontextmanager
    async def failed_transaction():
        yield AsyncMock()
        raise RuntimeError("commit failed")

    db_mod = MagicMock(transaction=failed_transaction)
    with (
        patch("combat_end.combat_rewards.roll_encounter_spoils", AsyncMock(return_value=spoils)),
        patch("db_content_queries.get_item", AsyncMock(side_effect=lambda item_id: {"name": item_id.title()})),
    ):
        with pytest.raises(RuntimeError, match="commit failed"):
            await _end_combat_impl(ctx, "victory", mutations=mutations, db_mod=db_mod)
    assert mutations.add_inventory_item.await_count == 2
    assert ctx.userdata.combat_state is cs
    assert ctx.userdata.session_items_found == []
    for pid in ("player_1", "player_2"):
        assert ctx.userdata.player_summary_metrics.get(pid, {}).get("items_found", []) == []
        assert (await named_recap(ctx.userdata, pid))["items_found"] == []


@pytest.mark.asyncio
async def test_guest_declared_defeat_uses_primary_anchor():
    ctx = make_context()
    _add_second_member(ctx)
    cs = _make_combat_state()
    guest = copy.deepcopy(cs.participants[0])
    guest.id = "player_2"
    cs.participants.insert(1, guest)
    ctx.userdata.combat_state = cs
    queries = combat_end_queries()
    with patch(
        "combat_end_lives.resurrection.resurrect_on_defeat", AsyncMock(return_value={"anchor": "accord_guild_hall"})
    ) as revive:
        with ctx.userdata._bind_authenticated_actor("player_2", 1, lambda *_: None):
            await _end_combat_impl(
                ctx, "defeat", mutations=combat_end_mutations(), queries=queries, db_mod=_fake_db_mod()
            )
    assert revive.await_args is not None
    assert revive.await_args.args[0]["player_id"] == "player_1"
    assert ctx.userdata.combat_state is None
