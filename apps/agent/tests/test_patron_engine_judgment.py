from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, defend
from acceptance._capstone_helpers import _d20, _damage_die, _enemy
from livekit.agents.llm import ToolError
from sample_fixtures import published_payloads
from test_patron_engine_kaelen import BATTLE_CRY, COMPANION, battle_cry_setup

import db_mutations
from ability_persistence import set_elective_equipped

JUDGMENT = "kaelen_kaelens_judgment"
OTHER_GIFTS = {BATTLE_CRY: {"spent": True}}
CHARGE = "warrior_unstoppable_charge"


@asynccontextmanager
async def judgment_fight(world, *, favor=75, hp=100, victory=False):
    extra = [] if victory else [_enemy("control", 100)]
    call = await battle_cry_setup(world, favor=favor, patron_gifts=OTHER_GIFTS, foe_hp=hp, other_enemies=extra)
    state = world.ctx.userdata.combat_state
    try:
        yield call, state
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=world.pool)


async def mark(call):
    projected = next(a for a in (await call("query_info", kind="patron"))["abilities"] if a["id"] == JUDGMENT)
    assert (projected["available"], projected["tier"]) == (True, "Exalted")
    assert (await call("activate", id=projected["id"], target_id="foe"))["worthy_foe"] == {"id": "foe", "name": "Foe"}


def combat_rolls(faces, damage):
    return (
        patch("check_resolution.dice_roll", side_effect=[_d20(face) for face in faces]),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(damage)),
    )


async def finish_phase(world, call, round_number):
    for _ in range(5):
        result = await call("resolve_phase")
        if isinstance(result, tuple) or world.ctx.userdata.combat_state.round_number > round_number:
            return result
        assert not result.get("judgment_rewards")
    pytest.fail("Resolution failed to finish the round")


async def advantage_scenario(world):
    async with judgment_fight(world) as (call, state):
        companion = state.get_participant(COMPANION)
        companion.action_pool = [{**companion.action_pool[0], "name": "Shortbow", "ranged": True}]
        await mark(call)
        session = world.ctx.userdata
        saved = await db_mutations.load_combat_state(state.combat_id, conn=world.pool)
        assert saved is not None
        expected = [{"type": "worthy_foe", "source": world.ids[0], "duration": None, "stacks": 1}]
        for snapshot in (session.combat_state, saved):
            assert {p.id: p.conditions for p in snapshot.participants} == {
                p.id: expected if p.id == "foe" else [] for p in state.participants
            }
        assert (await row(world, 0))["patron_gifts"] == {**OTHER_GIFTS, JUDGMENT: {"spent": True}}
        for target, faces, retained in [("foe", [3, 17] * 4, 17), ("foe", [3, 17] * 4, 17), ("control", [3] * 4, 3)]:
            state = session.combat_state
            before = len(published_payloads(session.room))
            declarations = [attack(p.id, target) if p.is_ally else defend(p.id) for p in state.participants]
            next(d for d in declarations if d["actor_id"] == COMPANION)["action"] = "Shortbow"
            await call("declare_phase", declarations=declarations)
            rolls, damage = combat_rolls(faces, 1)
            with rolls as dice, damage:
                await finish_phase(world, call, state.round_number)
            assert [c.args[0] for c in dice.call_args_list] == ["d20"] * len(faces)
            events = [e for e in published_payloads(session.room)[before:] if e.get("roll_type") == "attack"]
            assert [(e["attacker"], e["roll"], e["success"]) for e in events] == [
                (name, retained, target == "foe") for name in ("Rook", "Rook", "Iris", "Kael")
            ]


async def declare_finish(call, state, ally, charge=False):
    declarations = [attack(p.id, "foe") if p.id == ally else defend(p.id) for p in state.participants]
    if charge:
        actor = state.participants[0].id
        declarations[0] = {**defend(actor), "kind": "ability", "action": CHARGE, "targets": ["control"]}
    await call("declare_phase", declarations=declarations)


async def reward_scenario(world, current, restored, victory, charge=False):
    async with judgment_fight(world, hp=4 if charge else 1, victory=victory) as (call, state):
        follower, ally = world.ids
        await configure(
            world,
            "kaelen",
            "mage" if current is None else "warrior",
            level=8,
            stamina={"current": current, "max": 11},
            divine_favor={"patron": "kaelen", "level": 75, "max": 100},
            patron_gifts=OTHER_GIFTS,
        )
        if current is None:
            await world.pool.execute("UPDATE players SET data = data - 'stamina' WHERE player_id = $1", follower)
        if charge:
            await set_elective_equipped(follower, CHARGE, True)
            state.get_participant(follower).level = 8
            finisher = state.get_participant(ally)
            finisher.enhancers = ["extra_attack"]
            finisher.initiative = state.get_participant(follower).initiative + 1
            state.initiative_order[:2] = [ally, follower]
        before, ally_before = await row(world, 0), await row(world, 1)
        await mark(call)
        await declare_finish(call, state, ally, charge)
        rolls, damage = combat_rolls([3, 17] * (2 if charge else 1) + ([8] if charge else []), 1)
        with rolls, damage:
            result = await call("resolve_phase")
        paid = await row(world, 0)
        if current is None:
            assert "stamina" not in paid
        else:
            assert paid["stamina"] == {"current": current + restored - (4 if charge else 0), "max": 11}
        assert (paid["focus"], paid.get("resonance")) == (before["focus"], before.get("resonance"))
        assert paid["patron_gifts"] == {**OTHER_GIFTS, JUDGMENT: {"spent": True}}
        assert (await row(world, 1))["stamina"] == ally_before["stamina"]
        receipt = {"ability_id": JUDGMENT, "player_id": follower, "target_id": "foe", "stamina_restored": restored}
        assert result["judgment_rewards"] == [receipt]
        saved = await db_mutations.load_combat_state(state.combat_id, conn=world.pool)
        assert saved is not None and saved.judgment_rewards == [receipt]
        wrapped = await finish_phase(world, call, state.round_number)
        if victory:
            agent, response = wrapped
            assert agent is not None and response["outcome"] == "victory"
            assert "judgment_rewards" not in response
        else:
            assert isinstance(wrapped, dict) and not wrapped.get("judgment_rewards")
            if current == 2:
                session = world.ctx.userdata
                session.combat_state = await db_mutations.load_combat_state(state.combat_id, conn=world.pool)
                state = session.combat_state
                assert state is not None
                foe = state.get_participant("foe")
                assert foe is not None and foe.is_fallen and foe.hp_current == 0
                foe.hp_current = 1
                foe.is_fallen = False
                await declare_finish(call, state, ally)
                rolls, damage = combat_rolls([3, 17], 1)
                with rolls, damage:
                    continued = await call("resolve_phase")
                saved = await db_mutations.load_combat_state(state.combat_id, conn=world.pool)
                assert saved is not None and saved.judgment_rewards == [receipt]
                foe = saved.get_participant("foe")
                assert foe is not None and foe.is_fallen and foe.hp_current == 0
                assert isinstance(continued, dict) and not continued.get("judgment_rewards")
        assert (await row(world, 0)).get("stamina") == paid.get("stamina")


@pytest.mark.parametrize(
    "case,reason",
    [
        ("outside", "in combat"),
        ("absent", "player participant"),
        ("tier", "Exalted"),
        ("spent", "Already spent"),
        ("unknown", "living enemy"),
        ("omitted", "living enemy"),
        ("ally", "living enemy"),
        ("fallen", "living enemy"),
        ("marked", "already.*Worthy Foe"),
    ],
)
async def test_judgment_refuses_without_writes(world, case, reason):
    async with judgment_fight(world, favor=74 if case == "tier" else 75, hp=0 if case == "fallen" else 100) as (
        call,
        state,
    ):
        session = world.ctx.userdata
        actor = int(case == "marked")
        target = {"unknown": "elsewhere", "ally": world.ids[1]}.get(case, "foe")
        if case == "spent":
            await mark(call)
        elif case == "marked":
            await mark(call)
            await configure(
                world,
                "kaelen",
                "warrior",
                index=actor,
                divine_favor={"patron": "kaelen", "level": 75, "max": 100},
            )
        elif case == "outside":
            session.combat_state = None
        elif case == "absent":
            state.participants.pop(0)
        saved = await db_mutations.load_combat_state(state.combat_id, conn=world.pool)
        live = session.combat_state.to_dict() if session.combat_state else None
        player = await row(world, actor)
        events = published_payloads(session.room)
        with session._bind_authenticated_actor(world.ids[actor], 0, lambda *_: None):
            with pytest.raises(ToolError, match=reason):
                await call("activate", id=JUDGMENT, **({} if case == "omitted" else {"target_id": target}))
        assert await row(world, actor) == player
        assert await db_mutations.load_combat_state(state.combat_id, conn=world.pool) == saved
        assert (session.combat_state.to_dict() if session.combat_state else None) == live
        assert published_payloads(session.room) == events


async def judgment_scenario(world, *args):
    if args:
        await reward_scenario(world, *args)
    else:
        await advantage_scenario(world)


SCENARIOS = {
    JUDGMENT: (
        "patron_combat_edges:kaelens_judgment",
        judgment_scenario,
        [(), (2, 5, False), (9, 2, False, True), (9, 2, True), (11, 0, False), (None, 0, False)],
    ),
}
