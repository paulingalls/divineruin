"""Receipt presence across real Shield, concentration and condition-clearing saves."""

import pytest
from _unbound_path_fixtures import world as world
from _zhael_marshal_rally_fixtures import ability, bonus, pending
from acceptance._promised_hour_fixtures import promised_fight, select_oath, wrap
from acceptance.seeds import seed_known_spells
from acceptance.test_valdris_oath_breach import registered, swear
from creature_combat_helpers import participant as from_creature
from test_encounter_facts_damage import GOBLIN, fight, goblin_strike
from voice_condition_fixtures import participant

import choir_encounter
from conditions import apply_condition
from creature_combat_loader import load_creature_enemy
from db_mutations_concentration import update_player_concentration


@pytest.mark.parametrize("timed", [False, True])
async def test_shield_receipt_with_or_without_promised_hour(world, timed: bool) -> None:
    setup = promised_fight(world) if timed else fight(world, "none", archetype="mage")
    async with setup as f:
        if timed:
            oath = await select_oath(f)
            await f.round(faces=())
        await seed_known_spells(world.pool, f.hero, ("arcane_bolt",))
        state = f.session.combat_state
        spec = await load_creature_enemy("hollow_choir", encounter_id=f.combat_id, enemy_id=GOBLIN, role="standard")
        choir = participant(state, GOBLIN)
        state.participants[state.participants.index(choir)] = from_creature(spec)
        choir_encounter.initialize(state)
        state.choir_encounter["phase"] = "exposed"
        packets = await f.round(ability(f.hero, "arcane_bolt", GOBLIN), faces=(15,) * 8)
        cast = next(p["cast"] for p in packets if p["actor_id"] == f.hero)
        if timed:
            assert cast["harmonic_shield_saves"] == [
                {
                    "target_id": GOBLIN,
                    "roll": 15,
                    "total": 16,
                    "dc": 16,
                    "success": True,
                    "combat_id": f.combat_id,
                    "round_number": 3,
                    "oath_timed": {
                        "oath_id": oath["oath_id"],
                        "synergy_clause_id": "zhael_promised_hour",
                        "name": "Promised Hour",
                        "combat_id": f.combat_id,
                        "round_number": 3,
                        "modifier": 1,
                        "reason": "active_objective",
                    },
                }
            ]
        else:
            assert "harmonic_shield_saves" not in cast
            assert cast["damage_result"]["target_id"] == f.hero


async def test_ordinary_concentration_save_has_no_receipt(world) -> None:
    async with fight(world, "none", ally_hp=20) as f:
        f.session.member_state(f.ally).concentration.spell_id = "divine_bless"
        await update_player_concentration(f.ally, "divine_bless")
        packets = await f.round(goblin_strike(GOBLIN, f.ally), faces=(19, 1))
        attack = next(p for p in packets if p["actor_id"] == GOBLIN)
        assert attack["concentration_broken"] == "divine_bless"
        assert "concentration_save" not in attack


@pytest.mark.parametrize("justice", [False, True])
async def test_wrap_receipt_membership_for_neither_and_rally_with_justice(world, justice: bool) -> None:
    setup = fight(world, "valdris", archetype="paladin") if justice else fight(world, "none")
    async with setup as f:
        if justice:
            registered(f)
            oath = await swear(f.session)
            await f.round(goblin_strike(GOBLIN, f.hero), faces=(1,))
            pending(f.session.combat_state, f.hero, f.ally)
        hero = participant(f.session.combat_state, f.hero)
        hero.conditions = apply_condition(
            [], "frightened", source=GOBLIN, duration=3, originating_participant_id=GOBLIN
        )
        await f.declare()
        await f.call("resolve_phase")
        result = await wrap(f, 10)
        if justice:
            assert (
                result["rally_saves"]
                == result["oath_saves"]
                == [
                    {
                        "actor_id": f.hero,
                        "condition": "frightened",
                        "roll": 10,
                        "total": 13,
                        "dc": 10,
                        "success": True,
                        "combat_id": f.combat_id,
                        "round_number": 2,
                        "rally_bonuses": [bonus(f.ally, f.hero)],
                        "oath_justice": {
                            "oath_id": oath["oath_id"],
                            "context": "save",
                            "source_id": GOBLIN,
                            "modifier": 2,
                            "reason": "aggression",
                        },
                    }
                ]
            )
        else:
            assert "rally_saves" not in result and "oath_saves" not in result
        assert not participant(await f.reload(), f.hero).conditions
