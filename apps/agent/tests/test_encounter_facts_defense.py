"""Second Before through registered combat phases and checkpoint reloads."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, defend
from acceptance._capstone_helpers import _damage_die
from combat.test_synergy_spell_edges import configure_caster
from test_aelora_gift import _live_party
from test_encounter_facts_damage import GOBLIN, OTHER, dice, fight, goblin_strike
from voice_condition_fixtures import participant, place_actors

from _gods_content import load_gods

CLAUSE = "zhael_second_before"
FATE = "zhael_fates_thread"


async def guardian(world: SimpleNamespace, *, fate: bool = False) -> None:
    gifts = {"zhael_lucky": {"spent": True}}
    if not fate:
        gifts[FATE] = {"spent": True}
    await configure(world, "zhael", "guardian", index=1, patron_gifts=gifts)


def ability(actor: str, target: str, action: str) -> dict:
    return {**defend(actor), "kind": "ability", "action": action, "targets": [target]}


def receipt(packet: dict, ac: int, hit: bool, clause: str | None) -> None:
    assert (packet["target_ac"], packet["hit"]) == (ac, hit)
    assert packet["synergy_ac_clause_id"] == clause
    assert packet["synergy_ac_bonus"] == int(clause is not None)


def snapshot(stored: dict, ac: int) -> None:
    assert stored["prepared"]["d20"]["dc"] == ac
    assert stored["attacker_data"]["synergy_ac_clause_id"] == CLAUSE
    assert stored["attacker_data"]["synergy_ac_bonus"] == 1


async def zhael_second_before(world: SimpleNamespace) -> None:
    async with fight(world, "thyra", archetype="guardian", ally_hp=20) as f:
        await guardian(world)
        packets = await f.round(goblin_strike(GOBLIN, f.hero))
        receipt(next(p for p in packets if p["actor_id"] == GOBLIN), 16, True, None)
        assert f.session.combat_state.encounter_facts["attacked"] == [f.hero]

        participant(f.session.combat_state, GOBLIN).action_pool.append(
            {
                "name": "Dust",
                "resolution": "save",
                "save": "dex",
                "dc": 14,
                "damage": "1d6",
                "damage_type": "force",
                "type": "ranged",
                "reach": 60,
                "save_success_damage": "half",
                "conditions_on_failure": [],
                "conditions_on_success": [],
            }
        )
        with patch("combat_enemy_action.dice_roll", return_value=_damage_die(5)):
            packets = await f.round({**attack(GOBLIN, f.ally), "action": "Dust"}, faces=(1,))
        saved = next(p for p in packets if p["actor_id"] == GOBLIN)
        assert (saved["save_type"], saved["save_success"], saved["damage"]) == ("dexterity", False, 5)
        assert participant(f.session.combat_state, f.ally).hp_current == 15
        assert f.session.combat_state.encounter_facts["attacked"] == [f.hero]

        for goblin, ac, hit, clause, hp in ((GOBLIN, 15, False, CLAUSE, 15), (OTHER, 14, True, None, 10)):
            packets = await f.round(attack(f.ally, goblin), goblin_strike(goblin, f.ally), faces=(1, 13))
            packet = next(p for p in packets if p["actor_id"] == goblin)
            assert packet["attack_total"] == 14
            receipt(packet, ac, hit, clause)
            assert packet["damage"] == 15 - hp
            assert participant(f.session.combat_state, f.ally).hp_current == hp
            assert f.session.combat_state.encounter_facts["attacked"].count(f.ally) == 1

        authored = next(g for g in load_gods() if g["god_id"] == "zhael")["layer_4_synergy_matrix"]["guardian"]
        assert authored["type"] == "divine"
        assert [(c["status"], c["resolution"], c.get("implementation_id")) for c in authored["clauses"]] == [
            ("active", "engine", CLAUSE)
        ]
        lifecycle = _live_party(f.session, *world.ids)
        try:
            with f.session._bind_authenticated_actor(f.ally, 1, lifecycle.require_authorized):
                assert (await f.call("query_info", kind="patron"))["synergy"] == authored
        finally:
            await lifecycle.aclose()


SCENARIOS = {CLAUSE: ("patron_synergy_combat:first_attack_defense", zhael_second_before, [()])}


async def test_held_first_attack(world: SimpleNamespace) -> None:
    async with fight(world, "thyra", ally_hp=20) as f:
        await guardian(world)
        lifecycle = _live_party(f.session, *world.ids)
        try:
            await f.declare(attack(f.ally, GOBLIN), goblin_strike(GOBLIN, f.ally))
            with dice(1):
                await f.call("resolve_phase")
            await guardian(world, fate=True)
            with dice(13):
                offer = (await f.call("resolve_phase"))["fate_offer"]
                assert offer["roller_id"] == GOBLIN and offer["total"] == 14
                held = await f.reload()
                snapshot(held.held_actions[0]["fate_attack"], 15)
                assert f.ally not in held.encounter_facts["attacked"]
                assert participant(held, f.ally).hp_current == 20
                with f.session._bind_authenticated_actor(f.ally, 1, lifecycle.require_authorized):
                    settled = await f.call("activate", id=FATE, offer_id=offer["offer_id"], keep="original")
            receipt(settled["packets"][0], 15, False, CLAUSE)
            assert (await f.reload()).encounter_facts["attacked"].count(f.ally) == 1
            if settled["beat"] != "declaration":
                assert (await f.call("resolve_phase"))["beat"] == "declaration"
            await guardian(world)
            packets = await f.round(attack(f.ally, OTHER), goblin_strike(OTHER, f.ally), faces=(1, 13))
            receipt(next(p for p in packets if p["actor_id"] == OTHER), 14, True, None)
        finally:
            await lifecycle.aclose()


@pytest.mark.parametrize("spell", [False, True], ids=["weapon", "spell"])
async def test_ally_fate_prepares_guardian_defense(world: SimpleNamespace, spell: bool) -> None:
    async with fight(world, "zhael", ally_hp=20, hollowed=True) as f:
        await guardian(world)
        participant(f.session.combat_state, f.ally).type = "temporary_hollowed"
        place_actors(f.session.combat_state)
        if spell:
            await configure_caster(world, "zhael", "mage", "arcane_bolt")
        await configure(world, "zhael", "mage", patron_gifts={"zhael_lucky": {"spent": True}})
        lifecycle = _live_party(f.session, *world.ids)
        try:
            await f.declare(ability(f.hero, f.ally, "arcane_bolt") if spell else attack(f.hero, f.ally))
            with dice(1):
                offer = (await f.call("resolve_phase"))["fate_offer"]
                assert offer["roller_id"] == f.hero
                held = (await f.reload()).ally_continuation
                assert held is not None
                snapshot(held["steps"]["spell_damage"] if spell else held["attack"], 17)
                with f.session._bind_authenticated_actor(f.hero, 1, lifecycle.require_authorized):
                    settled = await f.call("activate", id=FATE, offer_id=offer["offer_id"], keep="original")
            packet = settled["packets"][0]
            receipt(packet["cast"]["damage_result"] if spell else packet, 17, False, CLAUSE)
        finally:
            await lifecycle.aclose()
