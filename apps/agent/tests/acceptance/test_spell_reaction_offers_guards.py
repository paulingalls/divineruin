"""Refusals and rollback through registered reaction and ordinary spell tools."""

from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from acceptance.defensive_reactions_harness import declare_attacks, defense_fight, player_row
from acceptance.disruption_reactions_harness import open_stage
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_guardian_intercept import tool_receipt
from acceptance.test_opportunity_strike import participant
from acceptance.test_slippery_restrain import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_spell_reaction_offers import BARK_SKIN, SHIELD, offered_id, resources

import character_spells
import combat_spatial
import db
import db_mutations
import db_queries
import resonance_events
import spell_cast_effects
from activate_tools import activate
from check_resolution import D20Roll

ORDINARY = "arcane_mage_hand"
FAITH = "divine_shield_of_faith"
UNWIRED = ("primal_natures_grasp", "arcane_counterspell")


@pytest.mark.parametrize("spell", [SHIELD, BARK_SKIN])
async def test_outside_combat_refuses_reaction_cast(reset_db_pool, spell):
    fight = MawlingHarness()
    try:
        await fight.prepare(companion=None, tools=(activate,))
        caster = fight.players[0]
        await fight.pool.execute(
            "UPDATE players SET data=jsonb_set(data,'{class}', '\"bard\"') WHERE player_id=$1", caster
        )
        for spell_id in (spell, ORDINARY):
            await character_spells.record_learned(caster, spell_id, "discovery", conn=fight.pool)
        before = await resources(fight, caster)
        with patch.object(spell_cast_effects, "publish_game_event") as events:
            assert "cast as a reaction" in await fight.command("activate", {"id": spell}, error=True)
            assert await resources(fight, caster) == before
            events.assert_not_called()
        await fight.command("activate", {"id": ORDINARY})
        assert await resources(fight, caster) == (before[0] - 1, before[1] + 1)
    finally:
        await fight.close()


@pytest.mark.parametrize("spell", [SHIELD, BARK_SKIN])
async def test_combat_refuses_ordinary_reaction_cast(reset_db_pool, spell):
    async with defense_fight("bard", library=((0, spell), (0, ORDINARY))) as fight:
        caster = fight.players[0]
        before = await player_row(caster)
        snapshot = (await fight.reload()).to_dict()
        assert "cast as a reaction" in await fight.command("activate", {"id": spell}, error=True)
        assert (await fight.reload()).to_dict() == snapshot
        assert await player_row(caster) == before
        declaration = {
            "kind": "ability",
            "actor_id": caster,
            "action": spell,
            "targets": [],
            "argument_type": "",
        }
        await fight.command("declare_phase", {"declarations": [declaration]})
        budget = (await fight.reload()).reactions_available
        assert "cast as a reaction" in await fight.command("resolve_phase", {}, error=True)
        state = await fight.reload()
        assert state.beat == "declaration" and not state.pending_declarations
        assert state.reactions_available == budget
        assert await player_row(caster) == before
        await fight.command("declare_phase", {"declarations": [{**declaration, "action": ORDINARY}]})
        packets = await fight.drain()
        (cast,) = [p for p in packets if p.get("action") == ORDINARY and "cast" in p]
        assert cast["cast"]["resonance_generated"] == 1
        assert (await resources(fight, caster))[0] == before["focus"]["current"] - 1


async def test_only_wired_spells_reach_windows(reset_db_pool):
    library = (SHIELD, BARK_SKIN, FAITH, *UNWIRED)
    async with defense_fight(
        "bard",
        ally_archetype="diplomat",
        library=tuple((1 if spell == FAITH else 0, spell) for spell in library),
    ) as fight:
        caster, ally = fight.players
        state = await fight.reload()
        assert set(participant(state, caster).reaction_ids) & set(library) == {SHIELD, BARK_SKIN}
        assert FAITH in participant(state, ally).reaction_ids
        await declare_attacks(fight, caster, fight.enemies[0])
        before = await resources(fight, caster)
        with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(16 - self.modifier)):
            await offered_id(fight, caster, "pre_roll", SHIELD)
            assert "fires on 'on_hit'" in await fight.command("activate", {"id": BARK_SKIN}, error=True)
            window, _ = await offered_id(fight, caster, "post_roll", BARK_SKIN)
            assert (ally, FAITH) in {(offer["actor_id"], offer["id"]) for offer in window["reactions"]}
            assert "fires on 'on_targeted'" in await fight.command("activate", {"id": SHIELD}, error=True)
            snapshot = (await fight.reload()).to_dict()
            for spell in UNWIRED:
                assert "does not own reaction" in await fight.command("activate", {"id": spell}, error=True)
            assert await resources(fight, caster) == before
            assert (await fight.reload()).to_dict() == snapshot
            await fight.drain()


@pytest.mark.parametrize(
    ("refusal", "reason"),
    [
        ("non_owner", "does not own reaction"),
        ("focus", "Not enough Focus"),
        ("generation", "no longer live"),
        ("save", "An internal error occurred"),
        ("commit", "An internal error occurred"),
    ],
)
async def test_refused_spend_preserves_checkpoint_and_resources(reset_db_pool, monkeypatch, refusal, reason):
    async with defense_fight("artificer", ally_archetype="mage", library=((0, SHIELD),)) as fight:
        caster, guest = fight.players
        if refusal == "focus":
            await fight.pool.execute(
                "UPDATE players SET data=jsonb_set(data,'{focus,current}','0') WHERE player_id=$1", caster
            )
        await declare_attacks(fight, caster, fight.enemies[0])
        _, offered = await offered_id(fight, caster, "pre_roll", SHIELD)
        before = await resources(fight, caster)
        guest_before = await resources(fight, guest)
        snapshot = (await fight.reload()).to_dict()
        events = []
        revoked = False
        original_transaction = db.transaction
        original_save = db_mutations.save_combat_state
        original_get = db_queries.get_players_for_update

        async def get_player(*args, **kwargs):
            nonlocal revoked
            result = await original_get(*args, **kwargs)
            revoked = True
            return result

        def validate(*_):
            if revoked:
                from livekit.agents.llm import ToolError

                raise ToolError("no longer live")

        async def save(*args, **kwargs):
            await original_save(*args, **kwargs)
            raise RuntimeError("after checkpoint write")

        @asynccontextmanager
        async def fail_at_exit():
            async with original_transaction() as conn:
                yield conn
                raise RuntimeError("transaction exit")

        async def publish(*args, **kwargs):
            events.append(args)

        monkeypatch.setattr(spell_cast_effects, "publish_game_event", publish)
        monkeypatch.setattr(resonance_events, "publish_game_event", publish)
        with monkeypatch.context() as fault:
            if refusal == "generation":
                fault.setattr(db_queries, "get_players_for_update", get_player)
                fight.model.commands.append(("activate", {"id": offered}))
                with fight.sd._bind_authenticated_actor(caster, 1, validate):
                    await fight.session.run(user_input="Execute the next command.")
                receipt = list(fight.model.receipts.values())[-1]
            else:
                if refusal == "save":
                    fault.setattr(db_mutations, "save_combat_state", save)
                if refusal == "commit":
                    fault.setattr(db, "transaction", fail_at_exit)
                receipt = await tool_receipt(
                    fight, guest if refusal == "non_owner" else caster, "activate", {"id": offered}
                )
            assert receipt.is_error and reason in receipt.output
        assert await resources(fight, caster) == before
        assert await resources(fight, guest) == guest_before
        assert (await fight.reload()).to_dict() == snapshot
        assert not events
        if refusal != "focus":
            packet = await fight.command("activate", {"id": offered})
            assert packet["resonance_generated"] == 1
            assert await resources(fight, caster) == (before[0] - 1, before[1] + 1)
            assert (await fight.reload()).reactions_available[caster]["ability_id"] == SHIELD
            assert events


@pytest.mark.parametrize("restriction", ["silence", "reactions_suppressed"])
async def test_restricted_library_caster_is_not_offered_shield(reset_db_pool, restriction):
    async with defense_fight("artificer", ally_archetype="diplomat", library=((0, SHIELD),)) as fight:
        caster, _ = fight.players
        state = await fight.reload()
        if restriction == "silence":
            combat_spatial.require_spatial(state)["zones"]["quiet"] = {
                "kind": "silence",
                "center_id": caster,
                "radius_ft": 1,
            }
        else:
            participant(state, caster).conditions.append({"type": restriction, "source": fight.enemies[0]})
        await fight.persist()
        await declare_attacks(fight, caster, fight.enemies[0])
        window = await open_stage(fight, "pre_roll")
        assert SHIELD not in {offer["id"] for offer in window["reactions"]}
        before = await resources(fight, caster)
        snapshot = (await fight.reload()).to_dict()
        refusal = await fight.command("activate", {"id": SHIELD}, error=True)
        assert ("silenced" if restriction == "silence" else "cannot take reactions") in refusal
        assert await resources(fight, caster) == before
        assert (await fight.reload()).to_dict() == snapshot
