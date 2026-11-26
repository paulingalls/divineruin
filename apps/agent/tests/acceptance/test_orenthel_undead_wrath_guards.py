"""Ineligible attacks at the Dawnward Strike combat boundary."""

from types import SimpleNamespace

import pytest
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack
from acceptance.test_orenthel_undead_wrath import checkpoint, set_target
from acceptance.test_orenthel_undead_wrath import dev_db_pool as dev_db_pool
from sample_fixtures import published_payloads
from test_encounter_facts_damage import GOBLIN, OTHER, fight
from voice_condition_fixtures import participant


@pytest.mark.parametrize("control", ["half", "self", "enemy", "fallen", "living_target", "other_patron"])
async def test_ineligible_hit_deals_base_damage(world: SimpleNamespace, control: str) -> None:
    patron = "mortaen" if control == "other_patron" else "orenthel"
    ally_hp = {"half": 10, "self": 20, "enemy": 20, "fallen": 0}.get(control, 9)
    async with fight(world, patron, ally_hp=ally_hp) as f:
        await set_target(f, "bandit" if control == "living_target" else "hollow_knight")
        state = f.session.combat_state
        if control == "self":
            participant(state, f.hero).hp_current = 9
        if control == "enemy":
            participant(state, OTHER).hp_current = 9
        if control == "fallen":
            participant(state, f.ally).is_fallen = True
        await checkpoint(f)
        await f.hit(None)


async def test_miss_deals_no_damage_and_emits_no_bonus(world: SimpleNamespace) -> None:
    async with fight(world, "orenthel", ally_hp=9) as f:
        target = await set_target(f, "hollow_knight")
        hp = target.hp_current
        await checkpoint(f)
        packets = await f.round(attack(f.hero, GOBLIN), faces=(1,))
        packet = next(p for p in packets if p["actor_id"] == f.hero)
        assert (packet["hit"], packet["damage"]) == (False, 0)
        assert participant(f.session.combat_state, GOBLIN).hp_current == hp
        receipt = [e for e in published_payloads(f.session.room) if e.get("roll_type") == "attack"][-1]
        for event in (packet, receipt):
            assert (
                event.get("synergy_damage") or 0,
                event.get("synergy_damage_type"),
                event.get("synergy_clause_id"),
            ) == (
                0,
                None,
                None,
            )
