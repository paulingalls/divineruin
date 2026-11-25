"""Moment to Rally at the registered combat boundaries."""

from unittest.mock import patch

import pytest
from _unbound_path_fixtures import world as world
from _zhael_marshal_rally_fixtures import CLAUSE, INTERCEDE, ability, bonus, save_action
from acceptance._capstone_helpers import _damage_die
from acceptance.test_architect_reshape_reload import set_favor
from combat.test_marshal_orders import DIRECT, MEDIC, ORDERS, REPOSITION, SACRIFICE, declare, enter
from combat.test_marshal_orders import marshal as marshal
from combat.test_marshal_orders import mock_combat_agent_factory as mock_combat_agent_factory
from test_encounter_facts_damage import GOBLIN, dice, fight, goblin_strike

import reaction_spend
from _gods_content import load_gods


async def intercede_then_save(world) -> None:
    async with fight(world, "zhael", archetype="marshal", ally_hp=20) as f:
        state = f.session.combat_state
        marshal = state.get_participant(f.hero)
        ally = state.get_participant(f.ally)
        assert marshal is not None and ally is not None
        marshal.has_reaction_ability = True
        marshal.reaction_ids = [INTERCEDE]
        state.reactions_available[f.hero] = reaction_spend.unspent()
        base_ac = ally.ac + 2
        await f.declare(goblin_strike(GOBLIN, f.ally))
        assert (await f.reload()).encounter_facts["rally_pending"] == {}
        response = await f.call("resolve_phase")
        window = response["next"]["waiting_on"]
        if window is None:
            window = (await f.call("resolve_phase"))["next"]["waiting_on"]
        assert any(r["id"] == INTERCEDE for r in window["reactions"])
        with f.session._bind_authenticated_actor(f.hero, 1, lambda *_: None):
            await f.call("activate", id=INTERCEDE, target_id=f.ally)
        assert (await f.reload()).encounter_facts["rally_pending"] == {}
        with dice(11):
            result = await f.call("resolve_phase")
            packets = result["packets"]
            while result["beat"] != "declaration":
                result = await f.call("resolve_phase")
                packets.extend(result.get("packets", []))
        reaction = next(p for p in packets if p.get("ability_id") == INTERCEDE)
        assert reaction["mechanical_effect"] == "target_ac_bonus"
        blow = next(p for p in packets if p.get("actor_id") == GOBLIN and "target_ac" in p)
        assert blow["target_ac"] == base_ac + 2
        assert reaction["rally_grant"] == bonus(f.hero, f.ally)
        assert (await f.reload()).encounter_facts["rally_pending"] == {f.hero: f.ally}

        with patch("combat_enemy_action.dice_roll", return_value=_damage_die(4)):
            for first in (True, False):
                packets = await f.round(save_action(f, f.ally), faces=(10,))
                save = next(p for p in packets if "save_total" in p)
                assert (save["save_total"], save["save_success"], save["damage"]) == (
                    11 if first else 10,
                    first,
                    2 if first else 4,
                )
                assert save.get("rally_bonuses") == ([bonus(f.hero, f.ally)] if first else None)
                assert (await f.reload()).encounter_facts["rally_pending"] == {}

        packets = await f.round(ability(f.hero, DIRECT, f.ally, GOBLIN), faces=())
        assert "rally_grant" not in next(p for p in packets if p.get("action") == DIRECT)
        assert (await f.reload()).encounter_facts["once_spent"][CLAUSE] == [f.hero]

        zhael = next(g for g in load_gods() if g["god_id"] == "zhael")
        [clause] = zhael["layer_4_synergy_matrix"]["marshal"]["clauses"]
        assert (clause["status"], clause["resolution"], clause["implementation_id"]) == ("active", "engine", CLAUSE)


SCENARIOS = {CLAUSE: ("patron_synergy_combat:grant_marshal_rally", intercede_then_save, [()])}


@pytest.mark.parametrize("order,level,slots,focus,stamina", ORDERS)
async def test_declared_order_rallies_its_first_ally(marshal, order, level, slots, focus, stamina) -> None:
    harness = await marshal(level, owned=(order,) if order in (MEDIC, SACRIFICE) else ())
    await set_favor(harness, "zhael", 40)
    await enter(harness)
    source, ally, other = harness.players
    targets = [[*harness.players, *harness.enemies][slot] for slot in slots]
    await declare(harness, order, targets)
    assert (await harness.reload()).encounter_facts["rally_pending"] == {}
    packets = (await harness.command("resolve_phase", {}))["packets"]
    receipt = next(p for p in packets if p.get("action") == order)
    assert receipt["rally_grant"] == bonus(source, targets[0])
    await harness.drain()
    assert (await harness.reload()).encounter_facts["rally_pending"] == {source: targets[0]}
    second = DIRECT if order == REPOSITION else REPOSITION
    recipient = other if targets[0] == ally else ally
    await declare(harness, second, [recipient, harness.enemies[0]] if second == DIRECT else [recipient])
    packets = (await harness.command("resolve_phase", {}))["packets"]
    assert "rally_grant" not in next(p for p in packets if p.get("action") == second)
    assert (await harness.reload()).encounter_facts["rally_pending"] == {source: targets[0]}
    if order == DIRECT:
        await harness.drain()
        await harness.command("end_combat", {"outcome": "fled"})
        await enter(harness)
        assert (await harness.reload()).encounter_facts["rally_pending"] == {}
        await declare(harness, REPOSITION, [ally])
        receipt = next(
            p for p in (await harness.command("resolve_phase", {}))["packets"] if p.get("action") == REPOSITION
        )
        assert receipt["rally_grant"] == bonus(source, ally)


async def test_two_marshals_stack_and_keep_their_spent_budget(world) -> None:
    from _patron_engine_fixtures import configure
    from acceptance._capstone_helpers import _player
    from voice_condition_fixtures import place_actors

    async with fight(world, "zhael", archetype="marshal", ally_hp=20) as f:
        gifts = {key: {"spent": True} for key in ("zhael_fates_thread", "zhael_lucky")}
        await configure(world, "zhael", "marshal", index=1, patron_gifts=gifts)
        state = f.session.combat_state
        companion = _player("rallied-companion", 20)
        companion.type = "companion"
        state.participants.append(companion)
        state.initiative_order.append(companion.id)
        place_actors(state)
        sources = (f.hero, f.ally)
        receipt = await f.round(*(ability(source, DIRECT, companion.id, GOBLIN) for source in sources), faces=())
        grants = [p["rally_grant"] for p in receipt if "rally_grant" in p]
        assert grants == [bonus(source, companion.id) for source in sources]
        with patch("combat_enemy_action.dice_roll", return_value=_damage_die(4)):
            for first in (True, False):
                packets = await f.round(save_action(f, companion.id), faces=(9,))
                save = next(p for p in packets if "save_total" in p)
                assert (save["save_total"], save["save_success"]) == (11 if first else 9, first)
                assert save.get("rally_bonuses") == (
                    sorted(grants, key=lambda grant: grant["marshal_id"]) if first else None
                )
                facts = (await f.reload()).encounter_facts
                assert facts["rally_pending"] == {}
                assert facts["once_spent"][CLAUSE] == list(sources)
        packet = next(
            p for p in await f.round(ability(f.hero, DIRECT, f.ally, GOBLIN), faces=()) if p.get("action") == DIRECT
        )
        assert "rally_grant" not in packet
