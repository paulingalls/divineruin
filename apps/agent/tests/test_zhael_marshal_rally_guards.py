"""Rules that keep rally from being spent without a roll or an eligible order."""

from unittest.mock import patch

import pytest
from _unbound_path_fixtures import world as world
from _zhael_marshal_rally_fixtures import CLAUSE, INTERCEDE, bonus, pending, save_action
from acceptance._capstone_helpers import _damage_die
from test_encounter_facts_damage import GOBLIN, dice, fight, goblin_strike
from voice_condition_fixtures import participant

import reaction_spend
from conditions import apply_condition


@pytest.mark.parametrize("patron, own_blow", [("thyra", False), ("zhael", True)])
async def test_interceding_applies_ac_without_rally(world, patron, own_blow) -> None:
    async with fight(world, patron, archetype="marshal", ally_hp=20) as f:
        state = f.session.combat_state
        marshal = participant(state, f.hero)
        marshal.has_reaction_ability, marshal.reaction_ids = True, [INTERCEDE]
        state.reactions_available[f.hero] = reaction_spend.unspent()
        target = f.hero if own_blow else f.ally
        await f.declare(goblin_strike(GOBLIN, target))
        result = await f.call("resolve_phase")
        if result["next"]["waiting_on"] is None:
            result = await f.call("resolve_phase")
        assert any(r["id"] == INTERCEDE for r in result["next"]["waiting_on"]["reactions"])
        with f.session._bind_authenticated_actor(f.hero, 1, lambda *_: None):
            await f.call("activate", id=INTERCEDE, target_id=target)
        with dice(11):
            result = await f.call("resolve_phase")
        packet = next(p for p in result["packets"] if p.get("ability_id") == INTERCEDE)
        assert packet["mechanical_effect"] == "target_ac_bonus"
        assert "rally_grant" not in packet
        facts = (await f.reload()).encounter_facts
        assert facts["rally_pending"] == {} and CLAUSE not in facts["once_spent"]


async def test_auto_failed_save_keeps_bonus_for_next_rolled_save(world) -> None:
    async with fight(world, "thyra", ally_hp=20) as f:
        state = f.session.combat_state
        pending(state, f.ally, f.hero)
        stunned = participant(state, f.ally)
        stunned.conditions = apply_condition([], "stunned", source=GOBLIN, duration=2)
        with patch("combat_enemy_action.dice_roll", return_value=_damage_die(4)):
            packets = await f.round(save_action(f, f.ally, save="DEX"), faces=())
            save = next(p for p in packets if "save_total" in p)
            assert (save["save_roll"], save.get("rally_bonuses")) == (0, None)
            assert (await f.reload()).encounter_facts["rally_pending"] == {f.hero: f.ally}
            participant(f.session.combat_state, f.ally).conditions = []
            packets = await f.round(save_action(f, f.ally, save="DEX"), faces=(10,))
        save = next(p for p in packets if "save_total" in p)
        assert (save["save_total"], save["rally_bonuses"]) == (11, [bonus(f.hero, f.ally)])
        assert (await f.reload()).encounter_facts["rally_pending"] == {}


@pytest.mark.parametrize("other_reaction", ["cleric_shield_of_faith", "diplomat_objection"])
async def test_interceding_that_does_not_change_ac_does_not_spend_rally(world, other_reaction) -> None:
    from _patron_engine_fixtures import configure
    from _zhael_marshal_rally_fixtures import ability

    async with fight(world, "zhael", archetype="marshal", ally_hp=20) as f:
        cls = other_reaction.split("_")[0]
        await configure(world, "thyra", cls, index=1, stamina={"current": 8})
        state = f.session.combat_state
        for pid, reaction in ((f.hero, INTERCEDE), (f.ally, other_reaction)):
            actor = participant(state, pid)
            actor.has_reaction_ability, actor.reaction_ids = True, [reaction]
        state.participants.sort(key=lambda p: p.id != f.ally)
        participant(state, f.ally).attributes["charisma"] = 10
        participant(state, GOBLIN).attributes["wisdom"] = 10
        await f.declare(goblin_strike(GOBLIN, f.ally))
        await f.call("resolve_phase")
        result = await f.call("resolve_phase")
        offered = result["next"]["waiting_on"]["reactions"]
        assert {r["id"] for r in offered} == {other_reaction, INTERCEDE}
        with f.session._bind_authenticated_actor(f.ally, 2, lambda *_: None):
            await f.call("activate", id=other_reaction, target_id=GOBLIN if cls == "diplomat" else f.ally)
        with f.session._bind_authenticated_actor(f.hero, 1, lambda *_: None):
            await f.call("activate", id=INTERCEDE, target_id=f.ally)
        with dice(11), patch("combat_reaction_contest.random.randint", side_effect=[20, 1]):
            result = await f.call("resolve_phase")
            packets = list(result["packets"])
            while result["beat"] != "declaration":
                result = await f.call("resolve_phase")
                packets.extend(result.get("packets", []))
        interceding = next(p for p in packets if p.get("ability_id") == INTERCEDE)
        competing = next(p for p in packets if p.get("ability_id") == other_reaction)
        assert competing["mechanical_effect"] == ("action_hesitated" if cls == "diplomat" else "target_ac_bonus")
        assert interceding["mechanical_effect"] is None and "rally_grant" not in interceding
        facts = (await f.reload()).encounter_facts
        assert facts["rally_pending"] == {} and CLAUSE not in facts["once_spent"]
        packets = await f.round(ability(f.hero, "marshal_direct_strike", f.ally, GOBLIN), faces=())
        assert next(p for p in packets if p.get("action") == "marshal_direct_strike")["rally_grant"] == bonus(
            f.hero, f.ally
        )


async def test_zhael_warrior_cannot_declare_an_order(world) -> None:
    from _unbound_path_fixtures import row
    from _zhael_marshal_rally_fixtures import ability
    from livekit.agents.llm import ToolError

    async with fight(world, "zhael", archetype="warrior", ally_hp=20) as f:
        before = await row(world, 0)
        with pytest.raises(ToolError, match=r"learned|declare|marshal"):
            await f.declare(ability(f.hero, "marshal_direct_strike", f.ally, GOBLIN))
            await f.call("resolve_phase")
        assert await row(world, 0) == before
        facts = f.session.combat_state.encounter_facts
        assert facts["rally_pending"] == {} and CLAUSE not in facts["once_spent"]


async def test_order_before_interceding_shares_rally_budget(world) -> None:
    from _zhael_marshal_rally_fixtures import ability

    async with fight(world, "zhael", archetype="marshal", ally_hp=20) as f:
        state = f.session.combat_state
        marshal = participant(state, f.hero)
        marshal.has_reaction_ability, marshal.reaction_ids = True, [INTERCEDE]
        await f.declare(ability(f.hero, "marshal_direct_strike", f.ally, GOBLIN), goblin_strike(GOBLIN, f.ally))
        packets = (await f.call("resolve_phase"))["packets"]
        order = next(p for p in packets if p.get("action") == "marshal_direct_strike")
        assert order["rally_grant"] == bonus(f.hero, f.ally)
        wait = (await f.call("resolve_phase"))["next"]["waiting_on"]
        assert any(reaction["id"] == INTERCEDE for reaction in wait["reactions"])
        with f.session._bind_authenticated_actor(f.hero, 1, lambda *_: None):
            await f.call("activate", id=INTERCEDE, target_id=f.ally)
        with dice(11):
            packets = (await f.call("resolve_phase"))["packets"]
        reaction = next(p for p in packets if p.get("ability_id") == INTERCEDE)
        assert reaction["mechanical_effect"] == "target_ac_bonus" and "rally_grant" not in reaction
        facts = (await f.reload()).encounter_facts
        assert facts["rally_pending"] == {f.hero: f.ally} and facts["once_spent"][CLAUSE] == [f.hero]


@pytest.mark.parametrize("mismatch", [False, True], ids=["missing", "wrong-recipient"])
async def test_stale_held_rally_fails_loudly(world, mismatch) -> None:
    from _patron_engine_fixtures import configure
    from test_zhael_fate_sprint_saves import _settle

    import db_mutations

    async with fight(world, "zhael", archetype="marshal", ally_hp=20) as f:
        await configure(world, "zhael", "marshal", patron_gifts={"zhael_lucky": {"spent": True}})
        pending(f.session.combat_state, f.ally, f.hero)
        await f.declare(save_action(f, f.ally))
        with dice(10):
            await f.call("resolve_phase")
            held = (await f.call("resolve_phase"))["fate_offer"]
        assert held["roll_kind"] == "save"
        state = await f.reload()
        state.encounter_facts["rally_pending"] = {f.hero: f.hero} if mismatch else {}
        await db_mutations.save_combat_state(f.combat_id, state.to_dict())
        with pytest.raises(ValueError, match="Cannot consume rally"):
            await _settle(world, f.session, state, f.call, held, reload=True)
        assert (await f.reload()).to_dict() == state.to_dict()
