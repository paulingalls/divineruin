import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sample_fixtures import SAMPLE_PLAYER, FixedRng, make_context, make_db_mod

from check_discovery import _check_discover_impl
from check_tools import _check_save_impl, _check_skill_impl
from conditions import apply_condition
from gathering_tools import _check_gather_impl
from social_tools import _check_social_impl


def actors():
    host = deepcopy(SAMPLE_PLAYER)
    host.update(
        skill_tiers={
            "athletics": "untrained",
            "persuasion": "untrained",
            "perception": "untrained",
            "survival": "untrained",
        },
        flags={},
    )
    guest = deepcopy(SAMPLE_PLAYER)
    guest.update(
        player_id="player_2",
        skill_tiers={"athletics": "expert", "persuasion": "expert", "perception": "expert", "survival": "expert"},
        flags={},
    )
    guest["attributes"].update(strength=18, wisdom=18, charisma=18, dexterity=18)
    guest["saving_throw_proficiencies"] = ["wisdom"]
    return {"player_1": host, "player_2": guest}


def setup(rows):
    ctx = make_context(party_member_ids=["player_2"])
    ctx.userdata.event_bus = MagicMock()
    queries = MagicMock()
    queries.get_player = AsyncMock(side_effect=lambda pid: rows[pid])
    return ctx, queries


def bind(ctx, validator=lambda _pid, _gen: None):
    return ctx.userdata._bind_authenticated_actor("player_2", 1, validator)


NODE = {
    "id": "vein",
    "node_type": "ore_vein",
    "resource_type": "ore",
    "quantity": 2,
    "respawn_days": 2,
    "discovered": False,
}


def fixed_roll(n=15):
    return patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=n))


@pytest.mark.asyncio
async def test_guest_skill_roll_and_advancement():
    rows = actors()
    ctx, queries = setup(rows)
    queries.get_single_skill_advancement = AsyncMock(
        return_value={"tier": "expert", "use_counter": 2, "narrative_moment_ready": False}
    )
    mutations = MagicMock(update_skill_advancement=AsyncMock())
    with bind(ctx), fixed_roll():
        result = json.loads(
            await _check_skill_impl(ctx, "athletics", "moderate", "climb", queries=queries, mutations=mutations)
        )
    assert result["modifier"] > 5
    assert result["total"] == 15 + result["modifier"]
    queries.get_player.assert_awaited_once_with("player_2")
    assert queries.get_single_skill_advancement.await_args.args[0] == "player_2"
    assert mutations.update_skill_advancement.await_args.args[0] == "player_2"


@pytest.mark.asyncio
async def test_guest_skill_consumes_inspired():
    rows = actors()
    rows["player_2"]["conditions"] = apply_condition([], "inspired")
    ctx, queries = setup(rows)
    queries.get_single_skill_advancement = AsyncMock(
        return_value={"tier": "expert", "use_counter": 2, "narrative_moment_ready": False}
    )
    mutations = MagicMock(update_skill_advancement=AsyncMock())
    conditions_mutations = MagicMock(remove_player_conditions=AsyncMock())
    db_mod, _ = make_db_mod()
    with bind(ctx), fixed_roll():
        result = json.loads(
            await _check_skill_impl(
                ctx,
                "athletics",
                "moderate",
                "climb",
                queries=queries,
                mutations=mutations,
                conditions_mutations=conditions_mutations,
                db_mod=db_mod,
            )
        )
    assert result["modifier"] > 5
    assert mutations.update_skill_advancement.await_args.args[0] == "player_2"
    assert conditions_mutations.remove_player_conditions.await_args.args[:2] == ("player_2", ("inspired",))


@pytest.mark.asyncio
async def test_guest_save_uses_proficiency_and_consumes_blessed():
    rows = actors()
    rows["player_2"]["conditions"] = apply_condition([], "blessed")
    ctx, queries = setup(rows)
    conditions_mutations = MagicMock(remove_player_conditions=AsyncMock())
    with bind(ctx), fixed_roll():
        result = json.loads(
            await _check_save_impl(
                ctx, "wisdom", 12, "fear", queries=queries, conditions_mutations=conditions_mutations
            )
        )
    assert result["modifier"] >= 7
    assert result["total"] == 15 + result["modifier"]
    queries.get_player.assert_awaited_once_with("player_2")
    assert conditions_mutations.remove_player_conditions.await_args.args[:2] == ("player_2", ("blessed",))


@pytest.mark.asyncio
@pytest.mark.parametrize("inspired", [False, True])
async def test_guest_social_reads_and_writes_own_disposition(inspired):
    rows = actors()
    if inspired:
        rows["player_2"]["conditions"] = apply_condition([], "inspired")
    ctx, queries = setup(rows)
    conditions_mutations = MagicMock(remove_player_conditions=AsyncMock())
    db_mod, _ = make_db_mod()
    dispositions = {"player_1": "hostile", "player_2": "neutral"}
    queries.get_npc_disposition = AsyncMock(side_effect=lambda _npc, pid, **_kw: dispositions[pid])
    mutations = MagicMock(
        set_npc_disposition=AsyncMock(
            side_effect=lambda _npc, pid, value, _why, **_kw: dispositions.__setitem__(pid, value)
        )
    )
    content = MagicMock(get_npc=AsyncMock(return_value={"default_disposition": "neutral"}))
    with bind(ctx):
        result = json.loads(
            await _check_social_impl(
                ctx,
                "merchant",
                "persuasion",
                "easy",
                queries=queries,
                mutations=mutations,
                conditions_mutations=conditions_mutations,
                content=content,
                db_mod=db_mod,
                rng=FixedRng(19),
            )
        )
    assert result["previous_disposition"] == "neutral"
    assert result["new_disposition"] != "neutral"
    assert result["total"] > 20
    assert dispositions["player_1"] == "hostile"
    assert dispositions["player_2"] == result["new_disposition"]
    if inspired:
        assert conditions_mutations.remove_player_conditions.await_args.args[:2] == ("player_2", ("inspired",))
    else:
        conditions_mutations.remove_player_conditions.assert_not_awaited()
    queries.get_npc_disposition.assert_awaited_once()
    assert queries.get_npc_disposition.await_args.args[1] == "player_2"


@pytest.mark.asyncio
@pytest.mark.parametrize("inspired", [False, True])
async def test_guest_discover_writes_own_fact_and_host_can_search(inspired):
    rows = actors()
    if inspired:
        rows["player_2"]["conditions"] = apply_condition([], "inspired")
    ctx, queries = setup(rows)
    conditions_mutations = MagicMock(remove_player_conditions=AsyncMock())
    db_mod, _ = make_db_mod()
    location = {
        "name": "Hall",
        "hidden_elements": [{"id": "secret", "discover_skill": "perception", "dc": 10, "description": "Door"}],
    }
    content = MagicMock(get_location=AsyncMock(return_value=location))
    mutations = MagicMock(
        set_player_flag=AsyncMock(side_effect=lambda pid, key, value, **_kw: rows[pid]["flags"].__setitem__(key, value))
    )
    with fixed_roll(), bind(ctx):
        result = json.loads(
            await _check_discover_impl(
                ctx,
                "perception",
                "wall",
                content=content,
                queries=queries,
                mutations=mutations,
                conditions_mutations=conditions_mutations,
                db_mod=db_mod,
            )
        )
    assert result["outcome"] == "discovered"
    assert result["modifier"] > 5
    assert rows["player_2"]["flags"] == {"secret.discovered": True}
    if inspired:
        assert conditions_mutations.remove_player_conditions.await_args.args[:2] == ("player_2", ("inspired",))
    else:
        conditions_mutations.remove_player_conditions.assert_not_awaited()
    assert rows["player_1"]["flags"] == {}
    with fixed_roll(), bind(ctx):
        retry = json.loads(
            await _check_discover_impl(
                ctx,
                "perception",
                "wall",
                content=content,
                queries=queries,
                mutations=mutations,
                conditions_mutations=conditions_mutations,
            )
        )
    assert retry["outcome"] == "not_found"
    assert rows["player_2"]["flags"] == {"secret.discovered": True}
    with fixed_roll():
        host_result = json.loads(
            await _check_discover_impl(ctx, "perception", "wall", content=content, queries=queries, mutations=mutations)
        )
    assert host_result["roll"] == 15


@pytest.mark.asyncio
async def test_guest_gather_uses_own_tier_and_grants_own_materials():
    rows = actors()
    rows["player_2"]["conditions"] = apply_condition([], "inspired")
    ctx, queries = setup(rows)
    conditions_mutations = MagicMock(remove_player_conditions=AsyncMock())
    node = dict(NODE)
    ctx.userdata.location_id = "woods"
    content = MagicMock(
        get_location=AsyncMock(
            return_value={
                "region": "greyvale",
                "resource_table": {"common": ["herb"], "uncommon": ["root"], "rare": ["star"]},
            }
        ),
        get_gathering_nodes_at_location=AsyncMock(return_value=[node]),
        get_material_definition=AsyncMock(side_effect=lambda material_id: {"name": material_id.title()}),
    )
    inventory = {"player_1": [], "player_2": []}
    mutations = MagicMock(
        add_inventory_item=AsyncMock(side_effect=lambda pid, item, qty, **_kw: inventory[pid].extend([item] * qty))
    )
    db_mod, _ = make_db_mod()
    gather_mutations = MagicMock(mark_node_discovered=AsyncMock(), deplete_node_quantity=AsyncMock())
    with bind(ctx):
        result = json.loads(
            await _check_gather_impl(
                ctx,
                "",
                queries=queries,
                mutations=mutations,
                content=content,
                db_mod=db_mod,
                gather_mutations=gather_mutations,
                conditions_mutations=conditions_mutations,
                rng=FixedRng(19),
            )
        )
    assert result["result"] == "rich_find"
    assert result["materials"] == ["star", "star", "ore"]
    gather_mutations.mark_node_discovered.assert_awaited_once()
    gather_mutations.deplete_node_quantity.assert_awaited_once()
    assert conditions_mutations.remove_player_conditions.await_args.args[:2] == ("player_2", ("inspired",))
    assert result["total"] > 20
    assert inventory["player_2"] == result["materials"]
    assert ctx.userdata.player_summary_metrics["player_2"]["items_found"] == ["Star", "Ore"]
    assert ctx.userdata.session_items_found == []
    assert inventory["player_1"] == []


@pytest.mark.asyncio
async def test_guest_social_consumes_inspired_without_shift():
    rows = actors()
    rows["player_2"]["conditions"] = apply_condition([], "inspired")
    ctx, queries = setup(rows)
    queries.get_npc_disposition = AsyncMock(
        side_effect=lambda _npc, pid, **_kw: {"player_1": "hostile", "player_2": "neutral"}[pid]
    )
    mutations = MagicMock(set_npc_disposition=AsyncMock())
    conditions_mutations = MagicMock(remove_player_conditions=AsyncMock())
    content = MagicMock(get_npc=AsyncMock(return_value={"default_disposition": "neutral"}))
    with bind(ctx):
        result = json.loads(
            await _check_social_impl(
                ctx,
                "merchant",
                "persuasion",
                "easy",
                queries=queries,
                mutations=mutations,
                conditions_mutations=conditions_mutations,
                content=content,
                rng=FixedRng(1),
            )
        )
    assert result["previous_disposition"] == result["new_disposition"] == "neutral"
    assert result["total"] >= 10
    mutations.set_npc_disposition.assert_not_awaited()
    assert conditions_mutations.remove_player_conditions.await_args.args[:2] == ("player_2", ("inspired",))


@pytest.mark.asyncio
async def test_guest_discover_failed_roll_consumes_inspired():
    rows = actors()
    rows["player_2"]["conditions"] = apply_condition([], "inspired")
    ctx, queries = setup(rows)
    content = MagicMock(
        get_location=AsyncMock(
            return_value={"hidden_elements": [{"id": "secret", "discover_skill": "perception", "dc": 19}]}
        )
    )
    mutations = MagicMock(set_player_flag=AsyncMock())
    conditions_mutations = MagicMock(remove_player_conditions=AsyncMock())
    with bind(ctx), fixed_roll(1):
        result = json.loads(
            await _check_discover_impl(
                ctx,
                "perception",
                "wall",
                content=content,
                queries=queries,
                mutations=mutations,
                conditions_mutations=conditions_mutations,
            )
        )
    assert result["outcome"] == "not_found"
    assert result["roll"] == 1
    mutations.set_player_flag.assert_not_awaited()
    assert conditions_mutations.remove_player_conditions.await_args.args[:2] == ("player_2", ("inspired",))
    assert "player_2:perception:secret" in ctx.userdata.attempted_discoveries
    with bind(ctx), fixed_roll(15):
        retry = json.loads(
            await _check_discover_impl(
                ctx,
                "perception",
                "wall",
                content=content,
                queries=queries,
                mutations=mutations,
                conditions_mutations=conditions_mutations,
            )
        )
    assert retry["outcome"] == "not_found"
    mutations.set_player_flag.assert_not_awaited()
    assert rows["player_1"]["flags"] == {}


@pytest.mark.asyncio
async def test_guest_discover_reads_own_flags():
    rows = actors()
    rows["player_1"]["flags"] = {"secret.discovered": True}
    ctx, queries = setup(rows)
    content = MagicMock(
        get_location=AsyncMock(
            return_value={"hidden_elements": [{"id": "secret", "discover_skill": "perception", "dc": 10}]}
        )
    )
    mutations = MagicMock(set_player_flag=AsyncMock())
    with bind(ctx), fixed_roll():
        result = json.loads(
            await _check_discover_impl(ctx, "perception", "wall", content=content, queries=queries, mutations=mutations)
        )
    assert result["outcome"] == "discovered"
    assert result["roll"] == 15
    assert mutations.set_player_flag.await_args.args[:2] == ("player_2", "secret.discovered")


WRITES = (
    "update_skill_advancement",
    "clear_narrative_moment",
    "remove_player_conditions",
    "set_npc_disposition",
    "set_player_flag",
    "mark_node_discovered",
    "deplete_node_quantity",
    "add_inventory_item",
)
STALE_CASES = [
    # mode, d20, guest condition, call that revokes the guest, writes that must not land after it
    ("skill", 15, "inspired", "get_player", ["update_skill_advancement", "remove_player_conditions"]),
    ("skill", 15, None, "get_player", ["update_skill_advancement"]),
    ("save", 15, "blessed", "get_player", ["remove_player_conditions"]),
    ("social", 19, "inspired", "get_player", ["set_npc_disposition", "remove_player_conditions"]),
    ("social", 19, None, "get_player", ["set_npc_disposition"]),
    ("social", 1, "inspired", "get_player", ["remove_player_conditions"]),
    ("discover", 15, "inspired", "get_player", ["set_player_flag", "remove_player_conditions"]),
    ("discover", 15, None, "get_player", ["set_player_flag"]),
    ("discover", 1, "inspired", "get_player", ["remove_player_conditions"]),
    ("gather", 19, "inspired", "get_player", ["mark_node_discovered"]),
    ("gather", 19, "inspired", "mark_node_discovered", ["deplete_node_quantity"]),
    ("gather", 19, "inspired", "deplete_node_quantity", ["add_inventory_item"]),
    ("gather", 19, "inspired", "add_inventory_item", ["remove_player_conditions"]),
]


def call_check(mode, d20, ctx, queries, db_writes):
    content = MagicMock(
        get_location=AsyncMock(
            return_value={
                "region": "greyvale",
                "resource_table": {"common": ["herb"], "uncommon": ["root"], "rare": ["star"]},
                "hidden_elements": [{"id": "secret", "discover_skill": "perception", "dc": 19}],
            }
        ),
        get_npc=AsyncMock(return_value={"default_disposition": "neutral"}),
        # A star node makes the rich find one material id, so the grant is a single write and the
        # consume guard, not the grant loop's next guard, is the one after it.
        get_gathering_nodes_at_location=AsyncMock(return_value=[dict(NODE, resource_type="star")]),
        get_material_definition=AsyncMock(side_effect=lambda material_id: {"name": material_id.title()}),
    )
    db_mod, _ = make_db_mod()
    io = dict(queries=queries, mutations=db_writes, conditions_mutations=db_writes)
    if mode == "skill":
        return _check_skill_impl(ctx, "athletics", "moderate", "climb", db_mod=db_mod, **io)
    if mode == "save":
        return _check_save_impl(ctx, "wisdom", 12, "fear", queries=queries, conditions_mutations=db_writes)
    if mode == "social":
        return _check_social_impl(
            ctx, "merchant", "persuasion", "easy", content=content, db_mod=db_mod, rng=FixedRng(d20), **io
        )
    if mode == "discover":
        return _check_discover_impl(ctx, "perception", "wall", content=content, db_mod=db_mod, **io)
    return _check_gather_impl(
        ctx, "", content=content, db_mod=db_mod, gather_mutations=db_writes, rng=FixedRng(d20), **io
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("mode", "d20", "condition", "revoke_on", "blocked"), STALE_CASES)
async def test_stale_guest_generation_blocks_every_later_write(mode, d20, condition, revoke_on, blocked):
    rows = actors()
    if condition:
        rows["player_2"]["conditions"] = apply_condition([], condition)
    ctx, queries = setup(rows)
    queries.get_single_skill_advancement = AsyncMock(
        return_value={"tier": "expert", "use_counter": 2, "narrative_moment_ready": False}
    )
    queries.get_npc_disposition = AsyncMock(return_value="neutral")
    writes = {name: AsyncMock() for name in WRITES}
    live = True

    def validate(_pid, _gen):
        if not live:
            raise RuntimeError("stale actor generation")

    trigger = {"get_player": queries.get_player, **writes}[revoke_on]
    inner = trigger.side_effect

    def revoke(*args, **kwargs):
        nonlocal live
        live = False
        return inner(*args, **kwargs) if inner else None

    trigger.side_effect = revoke
    with bind(ctx, validate), fixed_roll(d20), pytest.raises(RuntimeError, match="stale"):
        await call_check(mode, d20, ctx, queries, MagicMock(**writes))
    for name in blocked:
        writes[name].assert_not_awaited()
