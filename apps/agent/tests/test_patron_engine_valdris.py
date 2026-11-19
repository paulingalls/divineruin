from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import defend, game_tools
from acceptance._capstone_helpers import _d20, _damage_die
from livekit.agents.llm import ToolError
from sample_fixtures import published_payloads
from test_aelora_gift import _live_party
from voice_condition_fixtures import participant

import character_spells
import check_resolution_save
import db_mutations
from ability_persistence import set_elective_equipped
from activate_tools import activate
from combat_condition_landing import _land_condition_on_one
from combat_end import end_combat
from combat_turn import declare_phase, resolve_phase
from mode_tools import enter_mode
from query_tools import query_info

GIFT = "valdris_mark_of_justice"
TARGET = "mawling_1"
FLAME = "divine_sacred_flame"
CHARGE = "warrior_unstoppable_charge"
MARK = "mark_of_justice"
OTHER_GIFTS = {"valdris_weight_of_truth": {"spent": True}}


@asynccontextmanager
async def fight(world, *, action=FLAME, second_follower=False, favor=40, spent=False):
    host, guest = world.ids
    session = world.ctx.userdata
    _live_party(session, host, guest)
    for index, patron in enumerate(("valdris", "valdris" if second_follower else "kaelen")):
        warrior = index == 0 and action == CHARGE
        actor = world.ids[index]
        await configure(
            world,
            patron,
            "warrior" if warrior else "cleric",
            index=index,
            name=["Rook", "Iris"][index],
            level=8,
            speed=30,
            ac=14,
            hp={"current": 100, "max": 100},
            focus={"current": 10, "max": 10},
            stamina={"current": 10, "max": 10},
            attributes={"wisdom": 18, "strength": 18},
            resonance={"current": 0},
            divine_favor={"patron": patron, "level": favor if index == 0 else 40, "max": 100},
            patron_gifts={**OTHER_GIFTS, **({GIFT: {"spent": True}} if spent and index == 0 else {})},
        )
        session.party.members[index].resonance.current = 0
        if warrior:
            await set_elective_equipped(actor, CHARGE, True, conn=world.pool)
        else:
            await character_spells.record_learned(actor, FLAME, "training", is_prepared=True, conn=world.pool)
    call = game_tools(session, query_info, activate, enter_mode, declare_phase, resolve_phase, end_combat)
    await call("enter_mode", mode="combat", encounter_id="ruins_mawling_pair")
    try:
        yield call
    finally:
        if session.combat_state is not None:
            await db_mutations.delete_combat_state(session.combat_state.combat_id, conn=world.pool)


async def reload_state(world):
    session = world.ctx.userdata
    state = await db_mutations.load_combat_state(session.combat_state.combat_id, conn=world.pool)
    assert state is not None
    session.combat_state = state
    return state


async def mark(world, call, index=0):
    session = world.ctx.userdata
    previous = {p.id: p.conditions for p in session.combat_state.participants}
    target = session.combat_state.get_participant(TARGET)
    before = await row(world, index)
    projection = (await call("query_info", kind="patron"))["abilities"]
    gift = next(a for a in projection if a["name"] == "Mark of Justice")
    assert (gift["tier"], gift["available"], gift["spent"], gift["recharge"]) == ("Devoted", True, False, "long_rest")
    result = await call("activate", id=gift["id"], target_id=TARGET)
    assert result["marked_target"] == {"id": TARGET, "name": target.name}
    expected_gifts = {**before["patron_gifts"], GIFT: {"spent": True}}
    after = await row(world, index)
    assert after["patron_gifts"] == expected_gifts
    assert {key: after.get(key) for key in ("focus", "stamina")} == {
        key: before.get(key) for key in ("focus", "stamina")
    }
    previous[TARGET] = [*previous[TARGET], {"type": MARK, "source": world.ids[index], "duration": None, "stacks": 1}]
    saved = await reload_state(world)
    assert {p.id: p.conditions for p in saved.participants} == previous


async def checkpoint(world):
    state = world.ctx.userdata.combat_state
    await db_mutations.save_combat_state(state.combat_id, state.to_dict(), conn=world.pool)
    return await reload_state(world)


async def play_round(world, call, face, *, actor=None, action=None):
    session = world.ctx.userdata
    state = session.combat_state
    round_number = state.round_number
    declarations = [defend(p.id) for p in state.participants if not p.is_fallen]
    if action is not None:
        next(d for d in declarations if d["actor_id"] == actor).update(kind="ability", action=action, targets=[TARGET])
    await call("declare_phase", declarations=declarations)
    packets = []
    saves = []
    original = check_resolution_save.resolve_saving_throw

    def record(*args, **kwargs):
        save = original(*args, **kwargs)
        saves.append(save)
        return save

    with (
        patch("check_resolution.dice_roll", return_value=_d20(face)),
        patch("dice.roll", return_value=_damage_die(5)),
        patch.object(check_resolution_save, "resolve_saving_throw", side_effect=record),
    ):
        for _ in range(6):
            result = await call("resolve_phase")
            packets.extend(result.get("packets", []))
            if session.combat_state.round_number > round_number:
                return packets, saves
    pytest.fail("Resolution failed to wrap the round")


async def threshold(world, call, actor, action, total):
    state = world.ctx.userdata.combat_state
    target = participant(state, TARGET)
    hp = target.hp_current
    target.attributes.update(wisdom=10, strength=10)
    target.saving_throw_proficiencies = []
    if action == CHARGE:
        state.spatial["positions"][TARGET] = {"x": 5, "y": 0, "z": 0}
    await checkpoint(world)
    packets, saves = await play_round(world, call, 14, actor=actor, action=action)
    target = participant(await reload_state(world), TARGET)
    success = total == 14
    if action == FLAME:
        damage = next(p["cast"]["damage_result"] for p in packets if "cast" in p)
        save = damage["save"]
        assert (save["roll"], save["dc"], save["total"], save["success"]) == (14, 14, total, success)
        assert hp - target.hp_current == damage["damage"] == (0 if success else 18)
    else:
        (save,) = saves
        assert (save.roll, save.dc, save.total, save.success) == (14, 14, total, success)
        assert any(c["type"] == "prone" for c in target.conditions) is (not success)


async def immediate(world, action, second_follower=False, expiry=False):
    async with fight(world, action=action, second_follower=second_follower) as call:
        host, guest = world.ids
        session = world.ctx.userdata
        await mark(world, call)
        target = participant(session.combat_state, TARGET)
        target.hp_current = target.hp_max = 40
        await checkpoint(world)
        if second_follower:
            with session._bind_authenticated_actor(guest, 4, lambda *_: None):
                await mark(world, call, 1)
        await threshold(world, call, host, action, 12)
        if action == FLAME and not expiry:
            await threshold(world, call, guest, FLAME, 12 if second_follower else 14)
        if expiry:
            first = session.combat_state
            creature_id = participant(first, TARGET).creature_id
            await call("end_combat", outcome="fled")
            assert await db_mutations.load_combat_state(first.combat_id, conn=world.pool) is None
            for index in range(2):
                assert all(c["type"] != MARK for c in (await row(world, index)).get("conditions", []))
            await call("enter_mode", mode="combat", encounter_id="ruins_mawling_pair")
            state = await reload_state(world)
            assert state.combat_id != first.combat_id
            assert participant(state, TARGET).creature_id == creature_id
            assert all(c["type"] != MARK for p in state.participants for c in p.conditions)
            await threshold(world, call, host, FLAME, 14)
            assert (await row(world, 0))["patron_gifts"][GIFT] == {"spent": True}


async def deferred(world, origin):
    async with fight(world) as call:
        await mark(world, call)
        session = world.ctx.userdata
        state = session.combat_state
        target = participant(state, TARGET)
        target.attributes["wisdom"] = 10
        host, guest = world.ids
        action_label = "fixture_ability_label"
        if origin in ("legacy", "legacy_actor_label"):
            if origin == "legacy_actor_label":
                action_label = host
            target.conditions.append({"type": "frightened", "source": action_label, "duration": None, "stacks": 1})
        else:
            actors = (host, guest) if origin == "refresh" else (host if origin == "follower" else guest,)
            for actor in actors:
                assert _land_condition_on_one(
                    state,
                    TARGET,
                    participant(state, actor),
                    "frightened",
                    "prior_ability" if origin == "refresh" and actor == host else action_label,
                    packet={},
                )
        state = await checkpoint(world)
        fear = next(c for c in participant(state, TARGET).conditions if c["type"] == "frightened")
        assert fear["source"] == action_label
        _, saves = await play_round(world, call, 10)
        (save,) = saves
        success = origin != "follower"
        assert (save.roll, save.dc, save.total, save.success) == (10, 10, 10 if success else 8, success)
        assert fear.get("originating_participant_id") == (
            None if origin.startswith("legacy") else host if origin == "follower" else guest
        )
        target = participant(await reload_state(world), TARGET)
        assert any(c["type"] == "frightened" for c in target.conditions) is (not success)


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("tier", "Devoted"),
        ("spent", "Already spent"),
        ("unknown", "living enemy"),
        ("omitted", "living enemy"),
        ("ally", "living enemy"),
        ("fallen", "living enemy"),
    ],
)
async def test_mark_refusal_keeps_checkpoint_and_gifts(world, case, reason):
    async with fight(world, favor=39 if case == "tier" else 40, spent=case == "spent") as call:
        session = world.ctx.userdata
        if case == "fallen":
            foe = participant(session.combat_state, TARGET)
            foe.hp_current, foe.is_fallen = 0, True
        state = await checkpoint(world)
        player = await row(world, 0)
        events = published_payloads(session.room)
        before = state.to_dict()
        target_id = {"unknown": "missing", "ally": world.ids[1], "omitted": None}.get(case, TARGET)
        args = {} if target_id is None else {"target_id": target_id}
        with pytest.raises(ToolError, match=reason):
            await call("activate", id=GIFT, **args)
        assert session.combat_state.to_dict() == before
        assert (await reload_state(world)).to_dict() == before
        assert await row(world, 0) == player
        assert published_payloads(session.room) == events


async def scenario(world, kind, *args):
    await (deferred if kind == "deferred" else immediate)(world, *args)


SCENARIOS = {
    GIFT: (
        "patron_combat_edges:mark_of_justice",
        scenario,
        [
            ("immediate", FLAME),
            ("immediate", CHARGE),
            ("immediate", FLAME, True),
            ("immediate", FLAME, False, True),
            *(("deferred", origin) for origin in ("follower", "other", "legacy", "legacy_actor_label", "refresh")),
        ],
    ),
}
