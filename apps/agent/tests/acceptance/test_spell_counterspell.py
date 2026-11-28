from unittest.mock import patch

import pytest
from acceptance import defensive_reactions_harness as defense
from acceptance.disruption_reactions_harness import BARD
from acceptance.test_architect_fight import pos
from acceptance.test_bark_skin import keep_original
from acceptance.test_opportunity_strike import participant
from acceptance.test_slippery_restrain import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_still_anchors import strike

import conditions
from check_resolution import D20Roll
from combat_spatial import require_spatial
from db_mutations_resonance import read_player_resonance
from reaction_catalog import COUNTERSPELL, COUNTERSPELL_TWIN
from spells import get_spell

HOLD = "Hold Person"
DAGGER = "Ritual Dagger"
SHADOW = "Shadow Bolt"
LEADER = "cult_leader"
CULTIST = "cultist_1"


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(dict(face=10, wins=True), id="hold_success"),
        pytest.param(dict(face=9, wins=False), id="hold_failure"),
        pytest.param(dict(face=7, wins=True, action=SHADOW), id="shadow_zero_with_whisper"),
        pytest.param(dict(distance=65, offered=False), id="outside_range"),
        pytest.param(dict(action=DAGGER, offered=False), id="unmarked_weapon"),
        pytest.param(dict(face=10, wins=True, library=True), id="library_bard"),
        pytest.param(dict(face=9, wins=False, fate=True), id="enemy_fate_resume"),
        pytest.param(dict(face=10, winning_index=0), id="first_counterspeller_wins"),
        pytest.param(dict(face=10, winning_index=1), id="last_counterspeller_wins"),
    ],
)
async def test_counterspell(reset_db_pool, case: dict) -> None:
    action = case.get("action", HOLD)
    caster = CULTIST if action == DAGGER else LEADER
    library, fate = case.get("library", False), case.get("fate", False)
    second = "winning_index" in case
    shadow = action == SHADOW
    counter = COUNTERSPELL if library else COUNTERSPELL_TWIN
    learned = ((0 if library else 2, COUNTERSPELL),) if library or second else ()
    async with defense.defense_fight(
        "bard" if library else "mage",
        encounter="cult_cell",
        fate=fate,
        library=learned,
        ally_archetype="bard" if shadow else "guardian",
        extra_archetypes=("bard",) if second else (),
    ) as fight:
        reactor, target, *extra = fight.players
        state = await fight.reload()
        positions = {reactor: pos(case.get("distance", 40)), target: pos(5), **{actor: pos(40, 5) for actor in extra}}
        require_spatial(state)["positions"].update(positions, cult_leader=pos(0), cultist_1=pos(5, 5))
        leader = participant(state, LEADER)
        markers = {a["name"]: a["spell_focus_cost"] for a in leader.action_pool if "spell_focus_cost" in a}
        assert markers == {HOLD: 3, SHADOW: 0, "Dark Pulse": 2}
        assert markers[HOLD] == get_spell("arcane_hold_person").focus_cost
        reactors = {reactor: (counter, case.get("wins", False))}
        if second:
            # Both generated actor ids have equal length, so JSONB orders them lexicographically.
            winner = sorted([reactor, extra[0]])[case["winning_index"]]
            reactors = {reactor: (counter, winner == reactor), extra[0]: (COUNTERSPELL, winner == extra[0])}
        for actor, (_, wins) in reactors.items():
            score = 14 if second and not wins else 16
            await fight.pool.execute(
                "UPDATE players SET data=jsonb_set(data,'{attributes,intelligence}',to_jsonb($2::int)) WHERE player_id=$1",
                actor,
                score,
            )
            participant(state, actor).attributes["intelligence"] = score
        await fight.persist()
        before = await defense.hp(fight)
        attacks = {caster: action, **({CULTIST: DAGGER} if shadow else {})}
        declarations = [{"actor_id": actor, **strike(target, action=name)} for actor, name in attacks.items()]
        await fight.command("declare_phase", {"declarations": declarations})
        offered = case.get("offered", True)
        dc = 10 if shadow else 13
        faces = {10: 4, 12 + leader.dc_mod: 4} if action == HOLD else {}
        if offered:
            faces[dc] = case["face"]
        spell = get_spell(COUNTERSPELL)
        focus = {actor: (await defense.player_row(actor))["focus"]["current"] for actor in reactors}
        with patch.object(D20Roll, "roll", lambda roll, rng=None: roll.evaluate(faces.get(roll.dc, 18))):
            packets = (await fight.command("resolve_phase", {}))["packets"]
            opening = await fight.command("resolve_phase", {})
            window = opening["next"]["waiting_on"]
            packets += opening["packets"]
            if offered:
                assert window and "on_spell_cast" in window["triggers"]
                for actor, (ability, _) in reactors.items():
                    resonance = (await read_player_resonance(actor))["current"]
                    await fight.reload()
                    await defense.spend(
                        fight, ability, stage="pre_roll", actor=actor, cost=spell.focus_cost, opening=opening
                    )
                    assert (await fight.reload()).reactions_available[actor]["spent"]
                    if ability == COUNTERSPELL:
                        assert (await read_player_resonance(actor))["current"] == resonance + spell.resonance_by_source[
                            "arcane"
                        ]
                if shadow:
                    await defense.spend(fight, BARD, stage="pre_roll", actor=target, cost=2, opening=opening)
            else:
                assert counter not in {offer["id"] for offer in (window or {}).get("reactions", [])}
                entry = (await fight.reload()).reactions_available.get(reactor, {})
                assert not entry.get("spent", False)
            if fate:
                paused = await fight.command("resolve_phase", {})
                offer = paused["fate_offer"]
                assert (offer["roller_id"], offer["roll_kind"]) == (target, "save")
                packets += paused["packets"]
                await defense.reload_session(fight)
                faces[dc] = 18
                resumed = await fight.command("resolve_phase", {})
                packets += resumed["packets"]
                while offer := resumed.get("fate_offer"):
                    resumed = await keep_original(fight, offer)
                    packets += resumed["packets"]
            if (await fight.reload()).round_number == state.round_number:
                packets += await fight.drain()
        result = defense.action_packet(packets, caster, action)
        if offered:
            for actor, (ability, wins) in reactors.items():
                receipt = defense.reaction_packet(packets, ability)
                modifier = 2 if second and not wins else 3
                assert receipt["actor_id"] == actor
                face = case["face"]
                assert receipt["counterspell_check"] == dict(
                    roll=face, modifier=modifier, total=face + modifier, dc=dc, success=wins
                )
                if wins:
                    assert result["countered"]
                    assert (result["counterspell_id"], result["countered_by"]) == (ability, actor)
            if shadow:
                assert defense.reaction_packet(packets, BARD)["reason"] == result["reason"]
        negated = any(wins for _, wins in reactors.values())
        if negated:
            assert not {"save_roll", "roll", "damage"} & result.keys()
        elif action == HOLD:
            assert (result["save_roll"], result["save_success"]) == (4, False)
        if shadow or action == DAGGER:
            assert defense.action_packet(packets, CULTIST, DAGGER)["damage"] > 0
        after = await defense.hp(fight)
        assert after[1] < before[1] if shadow or action == DAGGER else after == before
        state = await fight.reload()
        assert conditions.has_condition(participant(state, target).conditions, "paralyzed") == (
            action == HOLD and not negated
        )
        assert not state.held_actions
        assert "Call declare_phase first" in await fight.command("resolve_phase", {}, error=True)
        for actor, balance in focus.items():
            assert (await defense.player_row(actor))["focus"]["current"] == balance - (
                spell.focus_cost if offered else 0
            )
