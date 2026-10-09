"""Selected player gear corrodes through public commands and committed events."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_mawling_multiattack import drain

import check_resolution_save
import db_mutations
import db_mutations_inventory
import db_queries
import event_types as E
from declarations import resolve_declaration


@pytest.fixture
def mock_combat_agent_factory():
    return None


@pytest.fixture
async def maw(reset_db_pool, request):
    harness = MawlingHarness()
    try:
        await harness.start(gear=True, reactions=getattr(request, "param", False))
        yield harness
    finally:
        if hasattr(harness, "session"):
            await harness.close()


@pytest.fixture
def events():
    published = []

    async def capture(room, kind, data, **kw):
        published.append((kind, data))

    with patch("combat_events.publish_game_event", side_effect=capture):
        yield published


@pytest.fixture
def rolls():
    original_save = check_resolution_save.roll_participant_save
    control = SimpleNamespace(save_roll=1, attack_roll=15)

    def save(*args, **kwargs):
        with patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=control.save_roll)):
            return original_save(*args, **kwargs)

    with (
        patch("check_resolution.dice_roll", side_effect=lambda *a, **kw: SimpleNamespace(total=control.attack_roll)),
        patch(
            "check_resolution_attack.dice_roll",
            side_effect=lambda expr, **kw: SimpleNamespace(total=12 if expr == "2d6+2" else 8),
        ),
        patch("check_resolution_save.roll_participant_save", side_effect=save),
        patch("combat_item_rider.dice_roll", return_value=SimpleNamespace(total=3)) as rider,
    ):
        control.rider = rider
        yield control


async def facts(maw):
    guest = maw.players[1]
    inventory = await maw.command("query_info", {"kind": "inventory", "target_id": guest})
    assert inventory["target_id"] == guest
    assert inventory["eligible_held_item_ids"] == ["shortsword_basic", "veil_ward_anchor_large"]
    assert {item["id"] for item in inventory["items"]} == {
        "shortsword_basic",
        "veil_ward_anchor_large",
        "chain_mail",
        "club_wooden",
    }
    actor = next(p for p in maw.roster if p["id"] == maw.enemies[0])
    return guest, inventory["eligible_held_item_ids"][1], actor


def payload(maw, form, target, item):
    if form == "composite":
        decl = maw.composite([target, target])
        decl["strikes"][0]["held_item_id"] = ""
        decl["strikes"][1]["held_item_id"] = item
        return decl
    return {
        "kind": "attack",
        "actor_id": maw.enemies[0],
        "action": "Dissolution Maw",
        "target_id": target,
        "rider": "",
        "held_item_id": item,
    }


async def declare(maw, decl):
    return await maw.command(
        "declare_phase",
        {"declarations": [decl, *[{"kind": "defend", "actor_id": p} for p in [*maw.players, maw.enemies[1]]]]},
    )


async def snapshot(maw):
    return await maw.snapshot(), [await db_queries.get_player_inventory(p) for p in maw.players]


@pytest.mark.parametrize("form", ["standalone", "composite"])
async def test_guest_public_selection_survives_binding(maw, form):
    guest, item, actor = await facts(maw)
    action = next(a for a in actor["executable_actions"] if a["name"] == "Dissolution Maw")
    assert action["durability_rider"]["target"] == "selected_player_held_item"
    composite = next(a for a in actor["executable_actions"] if a["kind"] == "multiattack")
    assert composite["strikes"][1]["durability_rider"] == action["durability_rider"]
    await declare(maw, payload(maw, form, guest, item))
    state = await maw.reload()
    raw = state.pending_declarations[maw.enemies[0]]
    typed = resolve_declaration(raw)
    if form == "standalone":
        assert typed.held_item_id == item
    else:
        assert typed.strikes is not None and typed.strikes[1]["held_item_id"] == item


@pytest.mark.parametrize("form", ["standalone", "composite"])
@pytest.mark.parametrize("bad", ["foreign", "unknown", "unequipped", "armor", "missing", "empty", "no_rider"])
async def test_bad_selection_refused_before_mutation(maw, events, form, bad):
    guest, item, _ = await facts(maw)
    await maw.pool.execute("DELETE FROM player_inventory WHERE player_id=$1 AND item_id='shortsword_basic'", guest)
    chosen = {
        "foreign": "shortsword_basic",
        "unknown": "unknown",
        "unequipped": "club_wooden",
        "armor": "chain_mail",
        "missing": item,
        "empty": "",
        "no_rider": item,
    }[bad]
    decl = payload(maw, form, guest, chosen)
    selected = decl if form == "standalone" else decl["strikes"][1]
    if bad == "missing":
        selected.pop("held_item_id")
    if bad == "no_rider":
        if form == "standalone":
            decl["action"] = "Claw"
        else:
            decl["strikes"][0]["held_item_id"] = chosen
    before = await snapshot(maw), list(events)
    error = await maw.command("declare_phase", {"declarations": [decl]}, error=True)
    assert (await snapshot(maw), events) == before
    if bad not in ("missing", "no_rider"):
        assert "veil_ward_anchor_large" in error


@pytest.mark.parametrize("form", ["standalone", "composite"])
@pytest.mark.parametrize("hollow", [False, True])
async def test_selected_guest_item_receives_one_doubled_roll(maw, rolls, form, hollow):
    guest, item, _ = await facts(maw)
    state = maw.sd.combat_state
    target = state.get_participant(guest)
    target.attributes.update(constitution=10, wisdom=18)
    target.saving_throw_proficiencies = []
    rolls.save_roll = 11
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    await maw.reload()
    maw.sd.corruption_level = 4 if hollow else 0
    events = []

    async def published(room, kind, data, **kw):
        if kind == E.ITEM_DURABILITY_HIT:
            saved = await db_queries.get_player_inventory(guest)
            assert (
                next(i for i in saved if i["id"] == data["item_id"])["slot_info"]["current_hits"]
                == data["current_hits"]
            )
            events.append(data)

    await declare(maw, payload(maw, form, guest, item))
    with patch("combat_events.publish_game_event", side_effect=published):
        packets, _ = await drain(maw)
    attack = next(p for p in packets if p.get("action") == "Dissolution Maw")
    assert attack["damage"] == 12
    assert attack["durability_rider"]["save_dc"] == 13
    assert attack["durability_rider"]["save_type"] == "constitution"
    assert attack["durability_rider"]["save_total"] == 11
    assert not attack["durability_rider"]["save_success"]
    assert attack["durability_rider"]["base_hits"] == 3
    rolls.rider.assert_called_once_with("1d4")
    inventory = await db_queries.get_player_inventory(guest)
    assert next(i for i in inventory if i["id"] == item)["slot_info"]["current_hits"] == 19
    assert next(i for i in inventory if i["id"] == "shortsword_basic")["slot_info"]["current_hits"] == 10
    assert (
        next(i for i in await db_queries.get_player_inventory(maw.players[0]) if i["id"] == item)["slot_info"][
            "current_hits"
        ]
        == 25
    )
    assert [e["current_hits"] for e in events if e["item_id"] == item] == [19]
    player = await db_queries.get_player(guest)
    assert player is not None and player["hp"]["current"] == (80 if form == "composite" else 88)


@pytest.mark.parametrize("case", ["no_gear", "companion", "unequipped", "removed", "miss", "save", "fallen"])
async def test_nonapplication_preserves_hp_and_independent_armor_wear(maw, rolls, events, case):
    guest, item, _ = await facts(maw)
    state = maw.sd.combat_state
    if case == "no_gear":
        await maw.pool.execute("DELETE FROM player_inventory WHERE player_id=$1 AND item_id <> 'chain_mail'", guest)
        inventory = await maw.command("query_info", {"kind": "inventory", "target_id": guest})
        assert inventory["eligible_held_item_ids"] == []
        item = ""
    if case == "companion":
        state.participants.append(
            replace(state.get_participant(guest), id="companion148", type="companion", reaction_ids=[])
        )
        state.spatial["positions"]["companion148"] = state.spatial["positions"][guest]
        state.spatial["speeds"]["companion148"] = state.spatial["speeds"][guest]
        guest, item = "companion148", ""
        await maw.command("query_info", {"kind": "inventory", "target_id": guest}, error=True)
        await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    if case == "fallen":
        state.get_participant(guest).hp_current = 5
        await maw.pool.execute("UPDATE players SET data=jsonb_set(data,'{hp,current}','5') WHERE player_id=$1", guest)
        await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    if case == "miss":
        rolls.attack_roll = 1
    if case == "save":
        rolls.save_roll = 20
        state.get_participant(maw.enemies[0]).dc_mod = -1
        await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    await declare(maw, payload(maw, "standalone", guest, item))
    await maw.command("resolve_phase", {})
    await maw.reload()
    if case in ("unequipped", "removed"):
        if case == "removed":
            await maw.pool.execute("DELETE FROM player_inventory WHERE player_id=$1 AND item_id=$2", guest, item)
        else:
            await maw.pool.execute(
                "UPDATE player_inventory SET data=jsonb_set(data,'{equipped}','false') WHERE player_id=$1 AND item_id=$2",
                guest,
                item,
            )
    packets, _ = await drain(maw)
    attack = next(p for p in packets if p.get("action") == "Dissolution Maw")
    assert attack["damage"] == (0 if case == "miss" else 12)
    remaining = 0 if case == "fallen" else 100 if case == "miss" else 88
    assert (await maw.reload()).get_participant(guest).hp_current == remaining
    if case != "companion":
        player = await db_queries.get_player(guest)
        assert player is not None and player["hp"]["current"] == remaining
    if case == "save":
        assert attack["durability_rider"]["save_dc"] == 12
    if case == "fallen":
        assert attack["target_fallen"] and attack["durability_rider"]["applied"]
        rolls.rider.assert_called_once_with("1d4")
    else:
        assert (
            attack["durability_rider"]["reason"]
            == {
                "no_gear": "no_eligible_item",
                "companion": "companion_target",
                "unequipped": "selected_item_unavailable",
                "removed": "selected_item_unavailable",
                "miss": "miss",
                "save": "save_succeeded",
            }[case]
        )
        rolls.rider.assert_not_called()
        assert not any(kind == E.ITEM_DURABILITY_HIT and data["item_id"] == item for kind, data in events)
    if case not in ("no_gear", "companion", "removed", "fallen"):
        inventory = await db_queries.get_player_inventory(guest)
        assert next(i for i in inventory if i["id"] == item)["slot_info"]["current_hits"] == 25
        assert next(i for i in inventory if i["id"] == "shortsword_basic")["slot_info"]["current_hits"] == 10
    assert (attack["durability"].get("armor") or {}).get("current_hits") == (
        None if case in ("companion", "miss") else 24
    )


@pytest.mark.parametrize("maw", [True], indirect=True)
@pytest.mark.parametrize("form", ["standalone", "composite"])
async def test_paused_selection_reloads_once_and_rollback_retries_atomically(maw, rolls, form):
    target = maw.players[0]
    inventory = await maw.command("query_info", {"kind": "inventory", "target_id": target})
    item = inventory["eligible_held_item_ids"][1]
    await declare(maw, payload(maw, form, target, item))
    for _ in range(7):
        result = await maw.command("resolve_phase", {})
        state = await maw.reload()
        head = state.held_actions[0]
        if head["declaration"].get("action") == "Dissolution Maw" and result["next"]["waiting_on"]:
            assert head["declaration"]["held_item_id"] == item
            assert resolve_declaration(head["declaration"]).held_item_id == item
            rolls.rider.assert_not_called()
            if result["next"]["waiting_on"]["stage"] == "post_roll":
                break
    else:
        pytest.fail("Maw never paused after its committed roll")
    before = await snapshot(maw)
    events = []

    async def published(room, kind, data, **kw):
        if kind == E.ITEM_DURABILITY_HIT:
            events.append(data)

    original = db_mutations.save_combat_state

    async def fail_after_checkpoint(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("resolution checkpoint rollback")

    with patch("combat_events.publish_game_event", side_effect=published):
        with patch("db_mutations.save_combat_state", side_effect=fail_after_checkpoint):
            await maw.command("resolve_phase", {}, error=True)
        assert await snapshot(maw) == before and events == []
        rolls.rider.assert_called_once_with("1d4")
        rolls.rider.reset_mock()
        rolls.attack_roll = None
        with patch("check_resolution.dice_roll", side_effect=AssertionError("committed attack rerolled")):
            packets, _ = await drain(maw)
        assert next(p for p in packets if p.get("action") == "Dissolution Maw")["damage"] == 12
        rolls.rider.assert_called_once_with("1d4")
        assert [e["current_hits"] for e in events if e["item_id"] == item] == [19]
        state = await maw.reload()
        assert state.held_actions == []
        player = await db_queries.get_player(target)
        assert player is not None and player["hp"]["current"] == (80 if form == "composite" else 88)
        committed = await snapshot(maw), list(events)
        await maw.command("resolve_phase", {}, error=True)
        assert (await snapshot(maw), events) == committed


@pytest.mark.parametrize("maw", ["shield"], indirect=True)
@pytest.mark.parametrize("hollow", [False, True])
async def test_selected_reaction_shield_losses_accumulate(maw, rolls, hollow):
    guest = maw.players[0]
    item = "thornveld_guardian_shield"
    await maw.pool.execute(
        "INSERT INTO player_inventory (player_id,item_id,data) VALUES ($1,$2,$3::jsonb)",
        guest,
        item,
        '{"equipped":true,"current_hits":25}',
    )
    maw.sd.corruption_level = 4 if hollow else 0
    facts = await maw.command("query_info", {"kind": "inventory", "target_id": guest})
    assert item in facts["eligible_held_item_ids"]
    await declare(maw, payload(maw, "standalone", guest, item))
    for _ in range(4):
        result = await maw.command("resolve_phase", {})
        await maw.reload()
        window = result["next"]["waiting_on"]
        if window and window["stage"] == "post_roll":
            assert "guardian_retaliating_shield" in [r["id"] for r in window["reactions"]]
            break
    else:
        pytest.fail("shield reaction not offered")
    await maw.command("activate", {"id": "guardian_retaliating_shield"})
    writes, events = [], []
    original = db_mutations_inventory.update_item_durability

    async def observe(*args, **kwargs):
        await original(*args, **kwargs)
        if args[1] == item:
            current = next(
                i for i in await db_queries.get_player_inventory(guest, conn=kwargs["conn"]) if i["id"] == item
            )
            assert current["slot_info"]["current_hits"] == args[2]
            writes.append(args[2])

    async def published(room, kind, data, **kw):
        if kind == E.ITEM_DURABILITY_HIT and data["item_id"] == item:
            events.append(data["current_hits"])

    with (
        patch("db_mutations_inventory.update_item_durability", side_effect=observe),
        patch("combat_events.publish_game_event", side_effect=published),
    ):
        packets, _ = await drain(maw)
    assert writes == events == ([23, 17] if hollow else [24, 18])
    saved = next(i for i in await db_queries.get_player_inventory(guest) if i["id"] == item)
    assert saved["slot_info"]["current_hits"] == events[-1]
    attack = next(p for p in packets if p.get("action") == "Dissolution Maw")
    assert attack["durability"]["armor"]["current_hits"] == (23 if hollow else 24)
    assert attack["durability"]["shield"]["current_hits"] == writes[0]
