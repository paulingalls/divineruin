from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from acceptance.seeds import seed_player_with_pools
from creature_combat_helpers import catalog, participant
from sample_fixtures import make_context
from voice_condition_fixtures import place_actors

import db_queries
import spell_casting
import spells
from combat_ability import AbilityCastOutcome, _resolve_ability_packet
from creature_combat import translate_creature
from declarations import Declaration, DeclarationType
from session_data import CombatParticipant, CombatState


@pytest.mark.parametrize("nonprimary", [False, True])
@pytest.mark.parametrize("multi", [False, True])
@pytest.mark.parametrize("success", [False, True])
async def test_shield_failed_wis16_redirects_real_spell(dev_db_pool, success, multi, nonprimary):
    pool = dev_db_pool
    pid = "choir_caster_" + uuid4().hex
    enemy = translate_creature(
        next(r for r in catalog() if r["id"] == "hollow_choir"),
        enemy_id="choir",
        encounter_id="choir_test",
        role="standard",
    )
    await seed_player_with_pools(pool, player_id=pid, class_="cleric", known_spells=("divine_bless",))
    try:
        caster = CombatParticipant(id=pid, name="Caster", type="player", initiative=15, hp_current=25, hp_max=25, ac=14)
        state = place_actors(
            CombatState(combat_id=pid, participants=[caster, participant(enemy)], initiative_order=[pid, "choir"])
        )
        if multi:
            ally = CombatParticipant(
                id="ally", name="Ally", type="companion", initiative=10, hp_current=25, hp_max=25, ac=14
            )
            state.participants.append(ally)
            place_actors(state)
        ctx = make_context("primary_unused" if nonprimary else pid)
        if nonprimary:
            from party_state import PartyState

            ctx.userdata.party.members.extend(PartyState.solo(pid).members)
        ctx.userdata.combat_state = state
        declaration = Declaration(
            type=DeclarationType.ABILITY,
            action="divine_bless",
            target_id=None if multi else "choir",
            target_ids=["choir", "ally"] if multi else None,
        )
        outcome = AbilityCastOutcome()
        player = await db_queries.get_player(pid, conn=pool)
        assert player is not None
        with patch(
            "check_resolution_save.roll_participant_save", return_value=SimpleNamespace(success=success)
        ) as save:
            result = await _resolve_ability_packet(
                ctx.userdata,
                caster,
                declaration,
                state=state,
                cast_resolver=spell_casting,
                conn=pool,
                player=player,
                cast_outcome=outcome,
            )
        assert save.call_args.args[1:3] == ("WIS", 16)
        target = "choir" if success else pid
        if multi:
            assert result["cast"]["condition_targets"] == [target, "ally"]
            ally_target = state.get_participant("ally")
            assert ally_target is not None and ally_target.conditions[0]["type"] == "blessed"
        else:
            assert result["cast"]["target_id"] == target
        assert next(p for p in state.participants if p.id == target).conditions[0]["type"] == "blessed"
        assert declaration.target_id == (None if multi else "choir")
        assert declaration.target_ids == (["choir", "ally"] if multi else None)
        assert len(outcome.results) == 1
        assert ctx.userdata.member_state(pid).concentration.spell_id == "divine_bless"
        if nonprimary:
            assert ctx.userdata.party.primary.concentration.spell_id is None
        row = await db_queries.get_player(pid, conn=pool)
        assert row is not None
        assert row["focus"]["current"] == player["focus"]["current"] - spells.get_spell("divine_bless").focus_cost
    finally:
        await pool.execute("DELETE FROM character_spells WHERE player_id = $1", pid)
        await pool.execute("DELETE FROM players WHERE player_id = $1", pid)


async def test_shield_nonverbal_nonspell_no_trigger():
    from dataclasses import replace

    from combat._catalog_fixtures import deps, setup

    from choir_reaction import effective_declaration
    from combat_packet import _resolve_one_packet

    state, choir, _ = setup()
    choir.creature_id = "hollow_choir"
    choir.choir_reaction = next(r for r in catalog() if r["id"] == "hollow_choir")["reactions"][0]
    caster = state.participants[0]
    declaration = Declaration(type=DeclarationType.ABILITY, action="divine_bless", target_id=choir.id)
    nonverbal = replace(spells.get_spell("divine_bless"), verbal=False)
    with (
        patch("spells.get_spell", return_value=nonverbal),
        patch("check_resolution_save.roll_participant_save") as saves,
    ):
        assert effective_declaration(state, caster, declaration) is declaration
        assert not saves.called
    attack = Declaration(type=DeclarationType.ATTACK, action=caster.action_pool[0]["name"], target_id=choir.id)
    with patch("check_resolution_save.roll_participant_save") as saves:
        result = await _resolve_one_packet(
            make_context().userdata, state, SimpleNamespace(actor_id=caster.id, declaration=attack), **deps()
        )
    assert result["resolved"] and not saves.called


async def test_held_melody_preserves_countercharm_subject_and_save():
    from combat._catalog_fixtures import deps, hold, setup

    import check_resolution_save
    import combat_hold

    action = next(r for r in catalog() if r["id"] == "hollow_choir")["actives"][0]
    state, actor, _ = setup(action)
    actor.creature_id = "hollow_choir"
    hold(state, actor)
    real_save = check_resolution_save.roll_participant_save
    with (
        patch("combat_hold.combat_reaction_effect.save_advantage", return_value=True) as subject,
        patch("check_resolution_save.roll_participant_save", wraps=real_save) as saves,
    ):
        result = await combat_hold._resolve_held(
            make_context().userdata, state, state.held_actions[0], packet_deps=deps(), mark_cancelled=False
        )
    assert subject.call_args.args[2] == "charmed"
    assert saves.call_args.kwargs["advantage"] is True
    assert result["save_advantage"] is True
