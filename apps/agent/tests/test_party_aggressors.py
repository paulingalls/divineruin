from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from _zhael_fate_fixtures import attack, defend, game_tools
from acceptance._capstone_helpers import _d20, _player
from acceptance.mawling_harness import MawlingHarness
from acceptance.seeds import seed_player_with_pools
from acceptance.test_choir_action_contract import choir, reload
from acceptance.test_choir_action_contract import runtime as runtime
from acceptance.test_still_actions import reveal_and_wake
from acceptance.test_still_anchors import declare, strike
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from asyncpg import Pool
from combat.test_handle_hp_zero import _hollowed
from sample_fixtures import published_payloads
from test_encounter_facts_damage import GOBLIN, OTHER, fight, goblin_strike
from test_encounter_facts_damage import world as world
from voice_condition_fixtures import participant, place_actors

import choir_encounter
import combat_turn
import db
import encounter_facts
from check_resolution import D20Roll
from combat_wrongdoing import aggression_facts
from db_mutations_concentration import update_player_concentration
from session_data import SessionData


async def test_ordered_attempts_and_retaliation(world: SimpleNamespace) -> None:
    async with fight(world, "mortaen", ally_hp=20) as f:
        state = f.session.combat_state
        companion = _player("companion_test")
        companion.type = "companion"
        state.participants.append(companion)
        state.initiative_order.append(companion.id)
        place_actors(state)

        participant(state, GOBLIN).action_pool.append(
            {
                "name": "Save Strike",
                "kind": "attack",
                "damage": "1d4",
                "damage_type": "force",
                "resolution": "save",
                "type": "ranged",
                "reach": 30,
                "conditions_on_failure": [],
                "conditions_on_success": [],
                "save": "DEX",
                "dc": 10,
                "save_success_damage": "none",
            }
        )
        await f.round(attack(f.hero, GOBLIN), faces=(15,))
        state = f.session.combat_state
        assert state.first_hostility[GOBLIN] == "ally"
        assert aggression_facts(state) == []
        assert state.encounter_facts["party_aggressors"] == {}
        assert not encounter_facts.has_attacked_party(state, GOBLIN)
        assert not encounter_facts.has_attacked_party(state, OTHER)

        for victim, face, expected in [(f.hero, 15, [f.hero]), (companion.id, 1, [f.hero, companion.id])]:
            packets = await f.round(goblin_strike(GOBLIN, victim), faces=(face,))
            assert next(p for p in packets if p["actor_id"] == GOBLIN)["hit"] is (face == 15)
            state = f.session.combat_state
            assert encounter_facts.party_victims(state, GOBLIN) == expected
            assert encounter_facts.has_attacked_party(state, GOBLIN)

        packets = await f.round({**attack(GOBLIN, f.ally), "action": "Save Strike"}, faces=(20,))
        saved = next(p for p in packets if p["actor_id"] == GOBLIN)
        assert saved["save_success"] and saved["damage"] == 0
        with patch("combat_maneuver.random.randint", side_effect=[1, 20]):
            packets = await f.round({"kind": "maneuver", "actor_id": OTHER, "target_id": f.ally}, faces=())
        assert next(p for p in packets if p["actor_id"] == OTHER)["shove"] == "resisted"
        assert encounter_facts.party_victims(f.session.combat_state, OTHER) == [f.ally]
        await f.round(goblin_strike(GOBLIN, f.hero), faces=(1,))
        state = f.session.combat_state
        victims = encounter_facts.party_victims(state, GOBLIN)
        assert victims == [f.hero, companion.id, f.ally]
        victims.clear()
        assert encounter_facts.party_victims(state, GOBLIN) == [f.hero, companion.id, f.ally]
        assert state.first_hostility[GOBLIN] == "ally"
        assert aggression_facts(state) == []


@pytest.fixture
def reset_db_pool(dev_db_pool: Pool) -> Pool:
    return dev_db_pool


@pytest.fixture
async def still_party(dev_db_pool: Pool) -> AsyncIterator[MawlingHarness]:
    harness = MawlingHarness()
    try:
        await harness.prepare((18, 18), companion=None, location="ashmark_still")
        yield harness
    finally:
        await harness.close()


async def test_automatic_hit_records_player_before_echo_turns_hostile(still_party) -> None:
    state = await reveal_and_wake(still_party)
    owner = state.still_encounter["owner_id"]
    victim = still_party.players[1]
    target = participant(state, victim)
    target.hp_current, target.conditions = 1, _hollowed(2)
    state.spatial["positions"][victim] = {**state.spatial["positions"][owner], "x": 120}
    await still_party.persist()

    await declare(still_party, actor_id=owner, **strike(victim, action="Serenity's Touch"))
    with (
        patch("dice.roll", return_value=SimpleNamespace(total=7)),
        patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(20)),
        patch("check_resolution_attack.resolve_attack", side_effect=AssertionError("Touch rolled to hit")),
    ):
        packets = await still_party.drain()
    touch = next(p for p in packets if p.get("action") == "Serenity's Touch")
    assert touch["target_rose_hollowed"] and touch["damage"] == 7
    state = await still_party.reload()
    assert participant(state, victim).type == "temporary_hollowed"
    assert state.encounter_facts["party_aggressors"] == {owner: [victim]}


async def round_packets(session: SessionData, *declarations: dict, face: int = 20) -> list[dict]:
    call = game_tools(session, combat_turn.declare_phase, combat_turn.resolve_phase)
    await call("declare_phase", declarations=list(declarations))
    packets = []
    with patch("check_resolution.dice_roll", return_value=_d20(face)):
        for _ in range(5):
            result = await call("resolve_phase")
            packets.extend(result.get("packets", []))
            if result["beat"] == "declaration":
                return packets
    raise AssertionError("round did not wrap")


@pytest.mark.parametrize("shield_success", [False, True])
async def test_choir_aura_and_harmonic_shield_do_not_record_attempts(runtime, shield_success: bool) -> None:
    ctx, pid, eid = await choir(runtime)
    session = ctx.userdata
    spell = "arcane_magic_missile"
    await seed_player_with_pools(await db.get_pool(), player_id=pid, class_="mage", known_spells=(spell,))
    await update_player_concentration(pid, "divine_bless")
    session.concentration.spell_id = "divine_bless"
    await round_packets(session, defend(pid), defend(eid), face=1)
    assert session.concentration.spell_id is None
    assert any(p.get("roll_type") == "choir_aura" for p in published_payloads(session.room))

    facts = await choir_encounter.facts(session.combat_state)
    assert facts is not None
    search = facts["search_actions"][1]
    await round_packets(session, {"kind": "interact", "actor_id": pid, "action": search["action"]}, defend(eid))
    cast = {"kind": "ability", "actor_id": pid, "action": spell, "targets": [eid], "argument_type": ""}
    packets = await round_packets(session, cast, defend(eid), face=20 if shield_success else 1)
    result = next(p["cast"] for p in packets if "cast" in p)
    expected = eid if shield_success else pid
    assert {receipt["target_id"] for receipt in result["damage_results"]} == {expected}
    assert sum(receipt["damage"] for receipt in result["damage_results"]) > 0
    state = await reload(ctx)
    assert state.encounter_facts["party_aggressors"] == {}
    assert state.first_hostility == {}
