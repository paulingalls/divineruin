import json
from collections.abc import AsyncIterator
from unittest.mock import patch
from uuid import uuid4

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import pos
from acceptance.test_guardian_intercept import BANDIT, INTERCEPT, SWORD, pools, tool_receipt
from acceptance.test_opportunity_strike import participant
from acceptance.test_slippery_restrain import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_slippery_restrain import strike

import combat_spatial
import db_mutations_concentration
import db_queries
from declarations import DEFEND_AC_BONUS

TREANT = "treant"
SLAM = "Slam"
SPELL = "arcane_fly"


@pytest.fixture
async def fight(reset_db_pool: str, scenario: str) -> AsyncIterator[MawlingHarness]:
    harness = MawlingHarness()
    try:
        await harness.prepare((6, 6), companion=None)
        target, ally = harness.players
        classes = ("druid" if scenario == "druid" else "warden", "guardian" if scenario == "intercept" else "mage")
        for actor, archetype in zip(harness.players, classes, strict=True):
            await harness.pool.execute(
                "UPDATE players SET data = jsonb_set(data, '{class}', $2::jsonb) WHERE player_id = $1",
                actor,
                json.dumps(archetype),
            )
        if scenario == "reload":
            await harness.pool.execute(
                "UPDATE players SET data=jsonb_set(data,'{divine_favor}',$2::jsonb) WHERE player_id=$1",
                target,
                '{"patron":"zhael","level":0,"max":100,"last_whisper_level":0}',
            )
            harness.sd.concentration.spell_id = SPELL
            await db_mutations_concentration.update_player_concentration(target, SPELL, conn=harness.pool)

        harness.encounter_id = f"bark_{uuid4().hex}"
        harness.owns_template = True
        template = {
            "id": harness.encounter_id,
            "name": "Forest edge",
            "description": "A branch snaps.",
            "difficulty": "hard",
            "recommended_party_level": 6,
            "enemies": [
                {"id": BANDIT, "creature_id": BANDIT, "role": "standard"},
                {"id": TREANT, "creature_id": "corrupted_treant", "role": "standard"},
            ],
            "scene_placement": {
                "party_start": pos(0),
                "companion_start": pos(0),
                "actors": {BANDIT: pos(-5), TREANT: pos(0, 5)},
                "zones": {},
                "locations": {},
            },
        }
        await harness.pool.execute(
            "INSERT INTO encounter_templates (id, data) VALUES ($1,$2::jsonb)",
            harness.encounter_id,
            json.dumps(template),
        )
        await harness.command("enter_mode", {"mode": "combat", "encounter_id": harness.encounter_id})
        state = await harness.reload()
        combat_spatial.require_spatial(state)["positions"].update({target: pos(0), ally: pos(5)})
        defender = participant(state, target)
        defender.ac = (24 if scenario == "natural" else 20) - DEFEND_AC_BONUS
        if scenario == "lethal":
            defender.hp_current = 3
            sword = next(action for action in participant(state, BANDIT).action_pool if action["name"] == SWORD)
            sword["bonus_damage"] = {"dice": "1d6", "damage_type": "necrotic"}
        for actor, initiative in ((BANDIT, 30), (TREANT, 29)):
            participant(state, actor).initiative = initiative
        state.initiative_order = [BANDIT, TREANT, target, ally]
        await harness.persist()
        yield harness
    finally:
        await harness.close()


async def declare(fight: MawlingHarness, *attackers: str) -> None:
    target = fight.players[0]
    actions = {BANDIT: SWORD, TREANT: SLAM}
    await fight.command(
        "declare_phase",
        {
            "declarations": [
                strike(actor, target, actions[actor])
                if actor in attackers
                else {"reshape": [], "kind": "defend", "actor_id": actor}
                for actor in [BANDIT, TREANT, *fight.players]
            ]
        },
    )


def attack_face(fight: MawlingHarness, actor: str, margin: int) -> tuple[int, int, int]:
    state = fight.sd.combat_state
    assert state is not None
    ac = participant(state, fight.players[0]).ac + DEFEND_AC_BONUS
    action_name = SWORD if actor == BANDIT else SLAM
    action = next(action for action in participant(state, actor).action_pool if action["name"] == action_name)
    return ac + margin - action["to_hit"], ac + margin, ac


async def keep_original(fight: MawlingHarness, offer: dict) -> dict:
    return await fight.command(
        "activate", {"id": "zhael_fates_thread", "offer_id": offer["offer_id"], "keep": "original"}
    )


async def opening(fight: MawlingHarness, expected_roll: tuple[int, int, int]) -> tuple[dict, dict]:
    for _ in range(4):
        result = await fight.command("resolve_phase", {})
        if "fate_offer" in result:
            assert result["fate_offer"]["roller_id"] == BANDIT
            result = await keep_original(fight, result["fate_offer"])
        if window := result["next"]["waiting_on"]:
            assert window["stage"] == "post_roll" and "on_hit" in window["triggers"], window
            head = (await fight.reload()).held_actions[0]
            original = head["roll"]["attack_result"]
            assert original["hit"]
            face, total, ac = expected_roll
            assert (original["roll"], original["attack_total"], head["roll"]["effective_ac"]) == (face, total, ac)
            assert original["attack_modifier"] == total - face
            return window, original
    raise AssertionError("no post-roll hit window")


async def focus(fight: MawlingHarness) -> int:
    row = await db_queries.get_player(fight.players[0])
    assert row is not None
    return row["focus"]["current"]


async def spend(fight: MawlingHarness, window: dict, archetype: str = "warden") -> str:
    (ability_id,) = [r["id"] for r in window["reactions"] if r["id"] == f"{archetype}_bark_skin"]
    before = await focus(fight)
    await fight.command("activate", {"id": ability_id})
    assert await focus(fight) == before - 2
    state = await fight.reload()
    assert state.reactions_available[fight.players[0]]["window_id"] == window["window_id"]
    return ability_id


def blow(packets: list[dict], actor: str = BANDIT) -> dict:
    (packet,) = [p for p in packets if p["actor_id"] == actor and "hit" in p]
    return packet


def effect(packets: list[dict], ability_id: str) -> str | None:
    (packet,) = [p for p in packets if p.get("ability_id") == ability_id]
    return packet["mechanical_effect"]


@pytest.mark.parametrize(("scenario", "margin"), [("lethal", 0), ("plain", 1), ("druid", 1), ("intercept", 1)])
async def test_turn_hit(fight: MawlingHarness, scenario: str, margin: int) -> None:
    before = await pools(fight)
    expected = attack_face(fight, BANDIT, margin)
    face, total, ac = expected
    await declare(fight, BANDIT)
    with (
        patch("check_resolution.dice_roll", return_value=_d20(face)) as dice,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(7)),
    ):
        window, original = await opening(fight, expected)
        if scenario == "lethal":
            assert original["target_killed"] and original["context"] == "killing_blow"
            assert original["bonus_damage"] == 7
        ability_id = await spend(fight, window, "druid" if scenario == "druid" else "warden")
        if scenario == "intercept":
            assert any(r["id"] == INTERCEPT for r in window["reactions"])
            receipt = await tool_receipt(fight, fight.players[1], "activate", {"id": INTERCEPT})
            assert not receipt.is_error, receipt.output
        packets = await fight.drain()
        assert dice.call_count == 1

    attack = blow(packets)
    assert (attack["roll"], attack["attack_total"], attack["target_ac"], attack["hit"]) == (face, total, ac + 2, False)
    assert attack["damage"] == attack["bonus_damage"] == attack["rider_damage"] == 0
    assert not attack["target_fallen"] and attack["context"] != "killing_blow"
    assert await pools(fight) == before
    assert not participant(await fight.reload(), fight.players[0]).is_dead
    assert effect(packets, ability_id) == "round_ac_bonus"
    if scenario == "intercept":
        assert effect(packets, INTERCEPT) is None


@pytest.mark.parametrize("scenario", ["reload"])
async def test_applied_hit_survives_reload(fight: MawlingHarness, scenario: str) -> None:
    expected = attack_face(fight, BANDIT, 2)
    face, total, ac = expected
    followup, _, _ = attack_face(fight, TREANT, 1)
    before = await pools(fight)
    focus_before = await focus(fight)
    await declare(fight, BANDIT, TREANT)
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(face), _d20(7), _d20(followup)]) as dice,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(7)) as damage,
    ):
        window, original = await opening(fight, expected)
        ability_id = await spend(fight, window)
        paused = await fight.command("resolve_phase", {})
        offer = paused["fate_offer"]
        assert (offer["roller_id"], offer["roll_kind"], offer["die"]) == (fight.players[0], "save", 7)
        state = await fight.reload()
        head = state.held_actions[0]
        saved = head["roll"]["attack_result"]
        assert (saved["roll"], saved["attack_total"], saved["target_ac"], head["roll"]["effective_ac"]) == (
            face,
            total,
            ac + 2,
            ac + 2,
        )
        assert saved["hit"] and saved["damage"] == original["damage"]
        assert participant(state, fight.players[0]).bark_skin_active
        assert effect(head["pending_reaction_packets"], ability_id) == "round_ac_bonus"
        assert (await pools(fight))[0][0] == before[0][0] - original["damage"]
        resumed = await keep_original(fight, offer)
        packets = resumed["packets"]
        if next_offer := resumed.get("fate_offer"):
            packets += (await keep_original(fight, next_offer))["packets"]
        if (await fight.reload()).round_number == state.round_number:
            packets += await fight.drain()
        assert dice.call_count == 3 and damage.call_count == 1

    attack = blow(packets)
    assert (attack["roll"], attack["attack_total"], attack["target_ac"], attack["damage"]) == (
        face,
        total,
        ac + 2,
        original["damage"],
    )
    assert attack["concentration_broken"] == SPELL
    assert effect(packets, ability_id) == "round_ac_bonus"
    assert (blow(packets, TREANT)["hit"], blow(packets, TREANT)["target_ac"]) == (False, ac + 2)
    assert (await pools(fight))[0][0] == before[0][0] - original["damage"]
    assert await focus(fight) == focus_before - 2
