from copy import deepcopy
from unittest.mock import patch

import pytest
from _zhael_fate_fixtures import defend, game_tools
from _zhael_unravel_fixtures import (
    GIFT,
    activate,
    adopt_fresh_context,
    adopt_opening,
    assert_refused,
    assert_restored,
    discovered,
    durable,
    favor,
    opening,
    patch_player,
)
from _zhael_unravel_fixtures import unravel as unravel
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance._spell_hostile_condition_helpers import receipt
from acceptance.test_departed_member_leaves_fight_guards import leave_unravel_guest
from acceptance.test_still_anchors import strike
from combat._round_checkpoint_helpers import Fight
from livekit.agents.llm import ToolError
from test_aelora_gift import _live_party

import character_spells
import conditions
from check_resolution import D20Roll
from combat_zero_hp import _handle_hp_zero
from encounter_roles import EncounterRole
from session_data import CompanionState
from session_hydration import hydrate_patron_ability_session

JOINER_REFUSAL = "Unravel Fate cannot rewind this round. Someone joined the fight after it began."


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


async def join_combat(fight: Fight) -> str:
    joiner = await fight.join()
    state = fight.session.combat_state
    assert state is not None and state.spatial is not None
    host, ally = fight.ids[:2]
    participant = deepcopy(state.get_participant(ally))
    assert participant is not None
    participant.id = joiner
    participant.hp_current = 3
    await patch_player(fight, joiner, hp={"current": participant.hp_current, "max": participant.hp_max})
    state.participants.insert(1, participant)
    state.initiative_order.insert(1, joiner)
    state.spatial["positions"][joiner] = dict(state.spatial["positions"][host], y=1)
    state.spatial["speeds"][joiner] = state.spatial["speeds"][ally]
    assert fight.lifecycle is not None
    await fight.lifecycle.aclose()
    fight.lifecycle = _live_party(fight.session, *fight.ids)
    await fight.write_row(state.to_dict())
    return joiner


@pytest.mark.parametrize(("spell", "cost"), [("divine_heal_wounds", 2), ("divine_divine_ward", 4)])
async def test_rewind_refuses_to_split_a_cast_on_a_mid_round_joiner(unravel: Fight, spell: str, cost: int) -> None:
    fight = unravel
    host = fight.ids[0]
    await patch_player(fight, host, **{"class": "cleric", "level": 10, "focus": {"current": 10, "max": 10}})
    await character_spells.record_learned(host, spell, "training", is_prepared=True, conn=fight.pool)
    opening_row = await opening(fight, 1)
    start = opening_row["round_checkpoints"][-1]
    starting_focus = start["players"][host]["data"]["focus"]["current"]
    joiner = await join_combat(fight)
    await fight.declare(
        {"kind": "ability", "actor_id": host, "action": spell, "targets": [joiner], "argument_type": ""},
        *(defend(pid) for pid in (*fight.ids[1:], "mawling_1", "mawling_2")),
    )
    cast = receipt((await fight.call("resolve_phase"))["packets"], host)
    await fight.finish_round(3)
    await fight.reload()
    before = await durable(fight)
    previous, current = before["combat"]["round_checkpoints"]
    assert previous == start and joiner not in previous["players"] and joiner in current["players"]
    assert before["players"][host]["data"]["focus"]["current"] == starting_focus - cost
    participant = fight.session.combat_state.get_participant(joiner)
    if spell == "divine_heal_wounds":
        (heal,) = cast["healing_results"]
        assert heal["target_id"] == joiner and heal["healed"] > 0
        assert before["players"][joiner]["data"]["hp"]["current"] == participant.hp_current == 3 + heal["healed"]
    else:
        assert cast["condition_targets"] == [joiner]
        assert any(c["type"] == "divine_ward" for c in participant.conditions)

    try:
        await assert_refused(fight, JOINER_REFUSAL, host)
    finally:
        await fight.reload()
        assert await durable(fight) == before


@pytest.mark.parametrize("arrival", ["previous", "current", "echo"])
async def test_rewind_refuses_even_when_joiner_spent_nothing(unravel: Fight, arrival: str) -> None:
    fight = unravel
    await opening(fight, 2 if arrival == "current" else 1)
    joiner = await join_combat(fight)
    await favor(fight, joiner)
    before_turn = (await durable(fight))["players"][joiner]["data"]
    if arrival == "echo":
        state = fight.session.combat_state
        guest = state.get_participant(joiner)
        guest.conditions = conditions.apply_condition(conditions.apply_condition([], "hollowed"), "hollowed")
        guest.hp_current = 0
        _handle_hp_zero(fight.session, state, guest, overkill=0, was_fallen=False, hp_status="fallen", sounds=[])
        await fight.write_row(state.to_dict())
    if arrival != "current":
        await fight.declare()
        await fight.finish_round(3)

    await fight.reload()
    before = await durable(fight)
    previous, current = before["combat"]["round_checkpoints"]
    assert joiner not in previous["players"] and (joiner in current["players"]) == (arrival != "current")
    assert fight.session.combat_state.get_participant(joiner).type == (
        "temporary_hollowed" if arrival == "echo" else "player"
    )
    if arrival != "echo":
        assert before["players"][joiner]["data"] == before_turn
    try:
        await assert_refused(fight, JOINER_REFUSAL)
        if arrival == "previous":
            assert (await discovered(fight, joiner))["available"]
            await assert_refused(fight, JOINER_REFUSAL, joiner)
    finally:
        await fight.reload()
        assert await durable(fight) == before


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
        await leave_unravel_guest(fight, rogue)
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


async def test_unravel_restores_bless_casters_and_saved_conditions(unravel: Fight) -> None:
    import character_spells
    from activate_tools import activate as cast
    from check_tools import check
    from combat_end import end_combat

    fight = unravel
    recipient, caster = fight.ids
    for spell in ("divine_bless", "arcane_detect_magic"):
        await character_spells.record_learned(caster, spell, "discovery", conn=fight.pool)
    await fight.invoke(
        game_tools(fight.session, cast), "activate", actor=caster, id="divine_bless", target_id=recipient
    )
    await fight.start()
    before = await durable(fight)
    saved_conditions = before["players"][recipient]["data"]["conditions"]
    assert saved_conditions[0]["sustaining_caster_ids"] == [caster]

    await fight.declare(
        {"kind": "ability", "actor_id": caster, "action": "arcane_detect_magic", "targets": [], "argument_type": ""},
        *(defend(p.id) for p in fight.session.combat_state.participants if p.id != caster),
    )
    await fight.finish_round(2)
    released = await durable(fight)
    assert released["players"][caster]["data"]["concentration"]["spell_id"] == "arcane_detect_magic"
    assert released["players"][recipient]["data"]["conditions"] == saved_conditions
    assert fight.session.combat_state.get_participant(recipient).conditions == []

    assert (await activate(fight))["round"] == 1
    restored = await durable(fight)
    assert restored["players"][caster]["data"]["concentration"]["spell_id"] == "divine_bless"
    assert restored["players"][recipient]["data"]["conditions"] == saved_conditions
    assert fight.session.combat_state.get_participant(recipient).conditions == saved_conditions
    with (
        patch("check_resolution.dice_roll", return_value=_d20(10)),
        patch("condition_bonus.dice_roll", return_value=_d20(3)),
    ):
        receipt = await fight.invoke(
            game_tools(fight.session, check),
            "check",
            actor=recipient,
            roll={"kind": "save", "save_type": "wisdom", "dc": 24, "effect_on_fail": "resist"},
        )
    offer_id = receipt["fate_offer"]["offer_id"]
    kept = await fight.call("activate", id="zhael_fates_thread", offer_id=offer_id, keep="original")
    assert kept["total"] == 14
    await fight.invoke(game_tools(fight.session, end_combat), "end_combat", outcome="fled")
    assert (await durable(fight))["players"][recipient]["data"]["conditions"] == []


@pytest.mark.parametrize(
    ("spell", "archetype", "stage", "cost", "flag"),
    [
        ("arcane_shield_spell", "artificer", "pre_roll", 1, "shield_spell_active"),
        ("primal_bark_skin", "beastcaller", "post_roll", 2, "bark_skin_active"),
    ],
)
async def test_catalog_reaction_rewinds_resources_and_defense(unravel: Fight, spell, archetype, stage, cost, flag):
    fight = unravel
    restorer, caster = fight.ids
    await patch_player(fight, caster, **{"class": archetype})
    await character_spells.record_learned(caster, spell, "discovery", conn=fight.pool)
    await fight.start()
    state = fight.session.combat_state
    enemy = state.get_participant("mawling_1")
    target = state.get_participant(caster)
    assert spell in target.reaction_ids
    target.ac = 16
    enemy.initiative = 40
    state.initiative_order.remove(enemy.id)
    state.initiative_order.insert(0, enemy.id)
    state.terrain = "forest"
    position = state.spatial["positions"][caster]
    state.spatial["positions"][enemy.id] = {**position, "x": position["x"] + 5}
    start = state.round_checkpoints[-1]
    before = start["players"][caster]["data"]
    await fight.write_row(state.to_dict())
    await fight.declare({"actor_id": enemy.id, **strike(caster, action="Claw")})
    with (
        patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(self.dc - self.modifier)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(3)),
    ):
        result = {}
        window = None
        for _ in range(5):
            if offer := result.get("fate_offer"):
                result = await fight.call(
                    "activate", id="zhael_fates_thread", offer_id=offer["offer_id"], keep="original"
                )
            else:
                result = await fight.call("resolve_phase")
            if window := result["next"]["waiting_on"]:
                break
        assert window is not None and window["stage"] == stage, (result["packets"], result["next"])
        (offered,) = [r["id"] for r in window["reactions"] if r["actor_id"] == caster]
        assert offered == spell
        result = await fight.call("activate", actor=caster, id=offered)
        generated = result["resonance_generated"]
        assert generated > 0
        spent = await durable(fight)
        assert spent["combat"]["reactions_available"][caster]["ability_id"] == spell
        data = spent["players"][caster]["data"]
        assert data["focus"]["current"] == before["focus"]["current"] - cost
        assert data["resonance"]["current"] == before["resonance"]["current"] + generated
        assert fight.session.member_state(caster).resonance.current == data["resonance"]["current"]
        result = await fight.call("resolve_phase")
        packets = result["packets"]
        if offer := result.get("fate_offer"):
            resumed = await fight.call("activate", id="zhael_fates_thread", offer_id=offer["offer_id"], keep="original")
            packets += resumed["packets"]
        (defense,) = [packet for packet in packets if packet.get("ability_id") == spell]
        assert defense["mechanical_effect"] == ("target_ac_bonus" if stage == "pre_roll" else "round_ac_bonus")
        if stage == "pre_roll":
            assert getattr(fight.session.combat_state.get_participant(target.id), flag)
        await fight.finish_round(start["round_number"] + 1)
    await activate(fight, restorer)
    await fight.reload()
    assert_restored(fight, await durable(fight), start, restorer)


@pytest.mark.parametrize("departed", [False, True])
async def test_rally_rewind_keeps_player_row_and_participant_pool_together(unravel: Fight, departed: bool) -> None:
    from acceptance.test_marshal_rally import rally
    from acceptance.test_war_cry import point
    from voice_condition_fixtures import participant

    import combat_spatial

    marshal, ally = unravel.ids
    unravel.session.companion = CompanionState(id="companion_kael", name="Kael")
    await patch_player(
        unravel,
        marshal,
        **{
            "class": "marshal",
            "level": 3,
            "attributes": {"charisma": 14},
            "focus": {"current": 10, "max": 10},
        },
    )
    await patch_player(unravel, ally, temp_hp=2)
    await unravel.start()
    state = unravel.session.combat_state
    companion = participant(state, "companion_kael")
    companion.temp_hp = 2
    for pid in (marshal, ally, companion.id):
        combat_spatial.place(state, pid, point(0))
    await unravel.declare()
    await unravel.finish_round(2)

    async def cast() -> None:
        current = unravel.session.combat_state
        await unravel.declare(rally(marshal), *(defend(p.id) for p in current.participants if p.id != marshal))
        await unravel.finish_round(3)

    async def assert_pools(player_pool: int, companion_pool: int, *, ally_left: bool = False) -> None:
        saved = await durable(unravel)
        assert saved["players"][ally]["data"]["temp_hp"] == player_pool
        amounts = {p["id"]: p["temp_hp"] for p in saved["combat"]["participants"]}
        assert amounts[companion.id] == companion_pool
        ally_in_combat = unravel.session.combat_state.get_participant(ally)
        if ally_left:
            assert ally not in amounts and ally_in_combat is None
        else:
            assert amounts[ally] == ally_in_combat.temp_hp == player_pool
        assert participant(unravel.session.combat_state, companion.id).temp_hp == companion_pool

    await assert_pools(2, 2)
    await cast()
    await assert_pools(5, 5)
    await unravel.reload()
    if departed:
        await leave_unravel_guest(unravel, ally)
    assert (await activate(unravel))["round"] == 2
    await assert_pools(5 if departed else 2, 2, ally_left=departed)
    if not departed:
        await cast()
        await assert_pools(5, 5)
