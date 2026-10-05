"""Revival eligibility belongs to the target, not the caster. Non-player targets retain the get_player limitation."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_mock_room
from voice_condition_fixtures import place_actors

import character_spells
import spell_casting
from combat_ability import AbilityCastOutcome, _resolve_ability_packet
from declarations import Declaration, DeclarationType
from session_data import CombatParticipant, CombatState
from spell_casting import _UNCHANGED, CastResult


def _player_participant() -> CombatParticipant:
    return CombatParticipant(id="caster_1", name="Lyra", type="player", initiative=15, hp_current=20, hp_max=20, ac=14)


def _cast_state(caster, *targets):
    return place_actors(
        CombatState(combat_id="targeting", participants=[caster], initiative_order=[caster.id]), *targets
    )


def _cast_resolver(packet: dict) -> MagicMock:
    """A cast_resolver stand-in whose _resolve_cast returns a minimal CastResult."""
    mod = MagicMock()
    mod._resolve_cast = AsyncMock(
        return_value=CastResult(
            packet=dict(packet), new_resonance=None, concentration_spell_id=_UNCHANGED, generated=0, events=[]
        )
    )
    return mod


class TestAbilityForwardsTargetId:
    @pytest.mark.asyncio
    async def test_forwards_explicit_target_id(self):
        session = make_context(player_id="caster_1").userdata
        decl = Declaration(type=DeclarationType.ABILITY, action="divine_revivify", target_id="ally_3")
        cast_resolver = _cast_resolver({"target_id": "ally_3"})
        outcome = AbilityCastOutcome()

        summary = await _resolve_ability_packet(
            session,
            _player_participant(),
            decl,
            state=_cast_state(_player_participant(), "ally_3"),
            cast_resolver=cast_resolver,
            conn=object(),
            player=None,
            cast_outcome=outcome,
        )

        assert summary["resolved"] is True
        _args, kwargs = cast_resolver._resolve_cast.call_args
        assert kwargs["target_id"] == "ally_3"  # the declaration's target reached the cast core

    @pytest.mark.asyncio
    async def test_normalizes_missing_target_to_self(self):
        session = make_context(player_id="caster_1").userdata
        decl = Declaration(type=DeclarationType.ABILITY, action="arcane_bolt")  # no target_id
        cast_resolver = _cast_resolver({})
        outcome = AbilityCastOutcome()

        await _resolve_ability_packet(
            session,
            _player_participant(),
            decl,
            state=_cast_state(_player_participant()),
            cast_resolver=cast_resolver,
            conn=object(),
            player=None,
            cast_outcome=outcome,
        )

        _args, kwargs = cast_resolver._resolve_cast.call_args
        assert kwargs["target_id"] == "caster_1"


class TestInCombatRevivalGateE2E:
    @staticmethod
    async def _seed(pool, player_id: str, **overrides) -> None:
        data = {"player_id": player_id, "class": "cleric", "level": 5, "focus": {"current": 10, "max": 10}}
        data.update(overrides)
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
        await pool.execute("INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb)", player_id, json.dumps(data))

    @pytest.mark.asyncio
    async def test_incombat_revival_keys_gate_on_target(self, dev_db_pool):
        pool = dev_db_pool
        caster_id, hollow_ally, living_ally = "s003_caster", "s003_hollow_ally", "s003_living_ally"
        await self._seed(pool, caster_id)  # living caster, full Focus
        await character_spells.record_learned(caster_id, "divine_revivify", "discovery", conn=pool)
        await self._seed(pool, hollow_ally, hollow_killed=True)
        await self._seed(pool, living_ally)
        session = make_context(player_id=caster_id, room=make_mock_room()).userdata
        caster = CombatParticipant(
            id=caster_id, name="Lyra", type="player", initiative=15, hp_current=20, hp_max=20, ac=14
        )
        try:
            decl_h = Declaration(type=DeclarationType.ABILITY, action="divine_revivify", target_id=hollow_ally)
            with pytest.raises(ToolError, match="Hollow-killed"):
                await _resolve_ability_packet(
                    session,
                    caster,
                    decl_h,
                    state=_cast_state(caster, hollow_ally, living_ally),
                    cast_resolver=spell_casting,
                    conn=pool,
                    player=None,
                    cast_outcome=AbilityCastOutcome(),
                )

            decl_l = Declaration(type=DeclarationType.ABILITY, action="divine_revivify", target_id=living_ally)
            summary = await _resolve_ability_packet(
                session,
                caster,
                decl_l,
                state=_cast_state(caster, hollow_ally, living_ally),
                cast_resolver=spell_casting,
                conn=pool,
                player=None,
                cast_outcome=AbilityCastOutcome(),
            )
            assert summary["resolved"] is True
            assert summary["cast"]["target_id"] == living_ally
        finally:
            for pid in (caster_id, hollow_ally, living_ally):
                await pool.execute("DELETE FROM players WHERE player_id = $1", pid)
