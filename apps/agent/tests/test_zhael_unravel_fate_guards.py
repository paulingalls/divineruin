from collections.abc import Mapping
from copy import deepcopy
from unittest.mock import patch

import pytest
from _zhael_fate_fixtures import defend, game_tools
from _zhael_unravel_fixtures import (
    GIFT,
    activate,
    adopt_opening,
    assert_restored,
    cached,
    discovered,
    durable,
    favor,
    opening,
    patch_player,
)
from _zhael_unravel_fixtures import unravel as unravel
from acceptance._capstone_helpers import _d20
from combat._round_checkpoint_helpers import Fight
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_mock_room
from test_aelora_gift import _live_party

from combat_agent import CombatAgent
from encounter_roles import EncounterRole
from exploration_agent import ExplorationAgent
from session_data import CompanionState
from session_hydration import hydrate_patron_ability_session


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("round_one", "no restorable checkpoint"),
        ("no_combat", "requires an active fight"),
        ("ended", "requires an active fight"),
        ("terminal", "requires an active fight"),
        ("stale", "fight opening changed"),
        ("wrong_combat", "fight opening changed"),
        ("declarations", "untouched declaration beat"),
        ("open_window", "reaction window"),
        ("held_actions", "held work"),
        ("ally_continuation", "held work"),
        ("wrap_continuation", "held work"),
        ("legendary_continuation", "held work"),
        ("inner_fire_continuation", "held work"),
        ("wrong_patron", "requires a follower of zhael"),
        ("lower_tier", "Exalted"),
        ("spent", "new session"),
    ],
)
async def test_refuses_without_changing_the_fight(unravel: Fight, case: str, reason: str) -> None:
    fight = unravel
    if case == "no_combat":
        await fight.start()
        fight.session.combat_state = None
        await assert_refused(fight, reason)
        return
    await opening(fight, 0 if case == "round_one" else 2)
    state = fight.session.combat_state
    assert state is not None
    if case == "ended":
        with patch("combat_end._build_handoff_agent", return_value=ExplorationAgent()):
            await fight.call("end_combat", outcome="fled")
        assert (await durable(fight))["combat"] is None
        fight.session.combat_state = state
    elif case == "terminal":
        state.deescalated = True
        await fight.write_row(state.to_dict())
    elif case == "stale":
        state.round_number -= 1
    elif case == "wrong_combat":
        row = await fight.row()
        row["combat_id"] += "_other"
        fight.combats.insert(0, row["combat_id"])
        for checkpoint in row["round_checkpoints"]:
            checkpoint["combat_id"] = checkpoint["combat"]["combat_id"] = row["combat_id"]
        await fight.write_row(row)
    elif case == "declarations":
        await fight.declare()
    elif case in {
        "open_window",
        "held_actions",
        "ally_continuation",
        "wrap_continuation",
        "legendary_continuation",
        "inner_fire_continuation",
    }:
        setattr(state, case, [{"held": True}] if case == "held_actions" else {"held": True})
    elif case == "wrong_patron":
        await favor(fight, fight.ids[0], "kaelen")
    elif case == "lower_tier":
        await favor(fight, fight.ids[0], level=30)
    elif case == "spent":
        await patch_player(fight, fight.ids[0], patron_gifts={GIFT: {"spent": True}})
    await assert_refused(fight, reason)


async def assert_refused(
    fight: Fight, reason: str, actor: str | None = None, *, selectors: Mapping[str, object] | None = None
) -> None:
    before, scratch = await durable(fight), cached(fight)
    state = fight.session.combat_state
    offer = fight.session.fate_offer
    with pytest.raises(ToolError, match=reason):
        await fight.call("activate", id=GIFT, actor=actor, **(selectors or {}))
    assert await durable(fight) == before
    assert fight.session.combat_state is state
    assert fight.session.fate_offer is offer
    assert cached(fight) == scratch


@pytest.mark.parametrize(
    ("patron", "ability"),
    [("valdris", "valdris_mark_of_justice"), ("syrath", "syrath_veilstep"), (None, "unbound_raw_channeling")],
)
async def test_effect_settled_at_opening_blocks_rewind(unravel: Fight, patron: str | None, ability: str) -> None:
    fight = unravel
    await opening(fight)
    guest = fight.ids[1]
    if patron is not None:
        await favor(fight, guest, patron, 70)
    arguments: dict[str, object] = {"target_id": "mawling_1"} if patron == "valdris" else {}
    if patron == "syrath":
        origin = fight.session.combat_state.spatial["positions"][guest]
        arguments["destination"] = {**origin, "y": origin["y"] + 5}
    await fight.call("activate", id=ability, actor=guest, **arguments)
    await assert_refused(fight, "untouched declaration beat")


async def test_rewind_accepts_no_entity_or_condition_selectors(unravel: Fight) -> None:
    fight = unravel
    await opening(fight)
    for selector in (
        {"target_id": fight.ids[1]},
        {"target_ids": [fight.ids[1]]},
        {"condition": "poisoned"},
    ):
        await assert_refused(fight, "Omit entity and condition selectors", selectors=selector)


async def test_fate_hold_and_settled_natural_twenty_block_rewind(unravel) -> None:
    fight = unravel
    await opening(fight)
    actor = fight.ids[0]
    faller = fight.session.combat_state.get_participant(actor)
    faller.hp_current, faller.is_fallen, faller.death_save_failures = 0, True, 2
    await patch_player(fight, actor, hp={"current": 0, "max": faller.hp_max})
    await fight.write_row(fight.session.combat_state.to_dict())
    with patch("combat_resolution.dice_roll", return_value=_d20(20)):
        result = await fight.call("request_death_save", player_id=actor)
        offer = result["fate_offer"]
        assert offer["die"] == 20
        await assert_refused(fight, "partially resolved round")
        settled = await fight.call("activate", id="zhael_fates_thread", keep="original", offer_id=offer["offer_id"])
    assert settled["revived"] and fight.session.fate_offer is None
    await fight.reload()
    assert fight.session.combat_state.get_participant(actor).death_save_failures == 0
    await assert_refused(fight, "untouched declaration beat")


async def test_settled_legendary_action_blocks_rewind_after_reload(unravel) -> None:
    fight = unravel
    await opening(fight)
    boss = fight.session.combat_state.get_participant("mawling_1")
    boss.role, boss.legendary_actions = EncounterRole.BOSS, 1
    result = await fight.call("consume_legendary_action", boss_id=boss.id, action_id="", target_id="", reshape=[])
    assert result["legendary_actions_remaining"] == 0
    await fight.reload()
    await assert_refused(fight, "untouched declaration beat")
    await fight.declare()
    await fight.finish_round(4)
    assert (await activate(fight))["round"] == 3


async def test_row_carrying_the_retired_settled_flag_still_loads(unravel) -> None:
    fight = unravel
    await opening(fight)
    await fight.write_row({**await fight.row(), "round_opening_settled": False})
    await fight.reload()
    assert (await activate(fight))["round"] == 2


async def test_refused_declaration_leaves_rewind_available(unravel) -> None:
    fight = unravel
    old = await opening(fight)
    actor, guest = fight.ids
    await fight.declare(
        {"kind": "consume", "actor_id": guest, "item_id": "healing_potion_minor", "target_id": actor},
        defend(actor),
        defend("mawling_1"),
        defend("mawling_2"),
    )
    potion = ("healing_potion_minor", guest)
    slot = await fight.pool.fetchrow("SELECT * FROM player_inventory WHERE item_id=$1 AND player_id=$2", *potion)
    await fight.pool.execute("DELETE FROM player_inventory WHERE item_id=$1 AND player_id=$2", *potion)
    with pytest.raises(ToolError, match="whole phase"):
        await fight.call("resolve_phase")
    await fight.pool.execute(
        "INSERT INTO player_inventory (player_id,item_id,tainted,data) VALUES ($1,$2,$3,$4)",
        slot["player_id"],
        slot["item_id"],
        slot["tainted"],
        slot["data"],
    )
    reopened = await fight.row()
    assert reopened["beat"] == "declaration" and reopened["pending_declarations"] == {}
    await activate(fight)
    assert_restored(fight, await durable(fight), old["round_checkpoints"][0], actor)


async def test_joiner_can_rewind_without_rewinding_joiner_or_departed_member(unravel) -> None:
    fight = unravel
    restorer, departing = fight.ids
    await opening(fight, 1)
    joiner = await fight.join()
    bystander = await fight.join()
    await favor(fight, joiner)
    await patch_player(fight, joiner, resonance={"current": 14, "flickering_bonus": 2})
    state = fight.session.combat_state
    for index, pid in enumerate((joiner, bystander), 1):
        participant = deepcopy(state.get_participant(departing))
        participant.id = pid
        state.participants.insert(index, participant)
        state.initiative_order.insert(index, pid)
        state.spatial["positions"][pid] = {"x": -7, "y": index, "z": 0}
        state.spatial["speeds"][pid] = state.spatial["speeds"][departing]
    await fight.lifecycle.aclose()
    fight.lifecycle = _live_party(fight.session, *fight.ids)
    await fight.declare()
    await fight.finish_round(3)

    fight.session.party.members = [member for member in fight.session.party.members if member.player_id != departing]
    state = fight.session.combat_state
    state.get_participant(departing).hp_current = 3
    state.spatial["positions"][departing] = {"x": -9, "y": 0, "z": 0}
    await patch_player(fight, departing, hp={"current": 3, "max": 20})
    await fight.write_row(state.to_dict())
    before = await durable(fight)
    joiner_member = deepcopy(fight.session.member_state(joiner))
    bystander_member = deepcopy(fight.session.member_state(bystander))
    await activate(fight, joiner)
    await fight.reload()
    after = await durable(fight)
    restored = fight.session.combat_state
    expected = deepcopy(before["players"][joiner]["data"])
    expected["resonance"]["current"] += 8
    expected["patron_gifts"][GIFT] = {"spent": True}
    assert after["players"][joiner]["data"] == expected
    joiner_member.resonance.current = expected["resonance"]["current"]
    joiner_member.resonance.flickering_bonus = expected["resonance"]["flickering_bonus"]
    assert fight.session.member_state(joiner) == joiner_member
    assert fight.session.member_state(bystander) == bystander_member
    assert after["players"][joiner]["inventory_revision"] == before["players"][joiner]["inventory_revision"]
    for pid in (departing, bystander):
        assert after["players"][pid] == before["players"][pid]
    retained = {departing, joiner, bystander}
    assert [slot for slot in after["slots"] if slot["player_id"] in retained] == [
        slot for slot in before["slots"] if slot["player_id"] in retained
    ]
    for pid in retained:
        assert restored.get_participant(pid) == state.get_participant(pid)
        assert restored.spatial["positions"][pid] == state.spatial["positions"][pid]
        assert restored.initiative_order.index(pid) == state.initiative_order.index(pid)
    assert len(restored.initiative_order) == len(set(restored.initiative_order))
    checkpoint = before["combat"]["round_checkpoints"][0]
    assert after["players"][restorer]["data"]["resonance"] == checkpoint["players"][restorer]["data"]["resonance"]


@pytest.mark.parametrize("departed", [False, True])
async def test_rewind_with_a_stolen_item_requires_restoring_its_owner(unravel: Fight, departed: bool) -> None:
    fight = unravel
    restorer, rogue = fight.ids
    await opening(fight, 1)
    state = fight.session.combat_state
    assert state is not None
    enemy = next(p for p in state.participants if p.type == "enemy")
    drop = {"item_id": "wolf_fangs", "quantity": 1, "tainted": False}
    row = next(p for p in state.round_checkpoints[-1]["combat"]["participants"] if p["id"] == enemy.id)
    row["carried_items"] = [drop]
    enemy.carried_items = []
    await fight.pool.execute(
        """INSERT INTO player_inventory (player_id,item_id,data) VALUES ($1,$2,'{"quantity":1}')""",
        rogue,
        drop["item_id"],
    )
    await fight.write_row(state.to_dict())
    await fight.declare()
    await fight.finish_round(3)
    if departed:
        fight.session.party.members = [fight.session.member_state(restorer)]
        await assert_refused(fight, "enemy pockets changed")
    else:
        await activate(fight)
        assert_restored(fight, await durable(fight), state.round_checkpoints[-1], restorer)


async def test_two_followers_cannot_rewind_twice_without_replay_and_keep_both_spends(unravel) -> None:
    fight = unravel
    first, second = fight.ids
    await favor(fight, second)
    await opening(fight)
    fight.session.member_state(first).weapon_used = True
    await activate(fight, first)
    assert not fight.session.member_state(first).weapon_used
    await assert_refused(fight, "no restorable checkpoint", second)

    await fight.declare()
    await fight.finish_round(3)
    state = fight.session.combat_state
    point = state.round_checkpoints[0]["players"][first]
    assert point["data"]["patron_gifts"][GIFT]["spent"]
    assert not point["session_flags"]["weapon_used"]
    point["data"]["patron_gifts"][GIFT]["spent"] = False
    point["data"].pop("temp_hp")
    point["data"].pop("flags", None)
    veil = {
        "shadow_veil": {"remaining_rounds": 1, "clause_id": "syrath_shadow_veil"},
        "concealed": True,
        "encounter_concealment": True,
    }
    await patch_player(
        fight,
        first,
        patron_gifts={GIFT: {"spent": True}, "zhael_lucky": {"spent": True}},
        temp_hp=4,
        flags={"met_oracle": True, **veil},
    )
    await adopt_opening(fight)
    fight.session.member_state(first).weapon_used = True
    await activate(fight, second)
    players = (await durable(fight))["players"]
    assert all(players[pid]["data"]["patron_gifts"][GIFT]["spent"] for pid in (first, second))
    assert "zhael_lucky" not in players[first]["data"]["patron_gifts"]
    assert "temp_hp" not in players[first]["data"]
    assert players[first]["data"]["flags"] == {"met_oracle": True}
    assert not fight.session.member_state(first).weapon_used

    await fight.declare()
    await fight.finish_round(3)
    await adopt_fresh_context(fight)
    for pid in (first, second):
        await hydrate_patron_ability_session(fight.session, pid, conn=fight.pool)
    assert (await discovered(fight, first))["available"]
    await fight.pool.execute(
        "UPDATE players SET data = data #- ARRAY['patron_gifts', $2] WHERE player_id=$1", first, GIFT
    )
    await activate(fight, second)
    assert (await discovered(fight, first))["available"]
    assert GIFT not in (await durable(fight))["players"][first]["data"]["patron_gifts"]


async def adopt_fresh_context(fight, *, same_session: bool = False) -> None:
    actor = fight.ids[0]
    previous = fight.session
    await fight.lifecycle.aclose()
    fight.session = make_context(
        actor, previous.location_id, room=make_mock_room(), party_member_ids=fight.ids
    ).userdata
    if previous.companion is not None:
        fight.session.companion = CompanionState(id=previous.companion.id, name=previous.companion.name)
    if same_session:
        fight.session.session_id = previous.session_id
        fight.session.patron_ability_entries = previous.patron_ability_entries.copy()
    fight.lifecycle = _live_party(fight.session, *fight.ids)
    fight.tools = game_tools(fight.session, agent=CombatAgent())
    await fight.reload()


async def test_persisted_checkpoint_rewinds_and_new_session_recharges(unravel) -> None:
    fight = unravel
    actor = fight.ids[0]
    fight.session.companion = CompanionState(id="companion_kael", name="Kael")
    await hydrate_patron_ability_session(fight.session, actor, conn=fight.pool)
    before = await opening(fight)
    await adopt_fresh_context(fight, same_session=True)
    await activate(fight)
    assert_restored(fight, await durable(fight), before["round_checkpoints"][0], actor)
    await hydrate_patron_ability_session(fight.session, actor, conn=fight.pool)
    assert (await discovered(fight))["spent"]

    await fight.declare()
    await fight.finish_round(3)
    await adopt_fresh_context(fight)
    assert (await discovered(fight))["spent"]
    await hydrate_patron_ability_session(fight.session, actor, conn=fight.pool)
    assert (await discovered(fight))["available"]
    await activate(fight)
    assert (await discovered(fight))["spent"]
