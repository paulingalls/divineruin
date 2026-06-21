"""M11 story-003 — in-combat ABILITY target_id wiring.

story-001 threaded target_id through the out-of-combat cast path; this closes the in-combat seam
(concern 3fe0ef128425): the in-combat ABILITY caller combat_support._resolve_ability_packet forwards
the declaration's optional target_id into the shared _resolve_cast, so an in-combat cast carries
target_id into the packet and a revival ABILITY keys the Hollow-killed gate on the TARGET (not the
caster) — matching cast_spell. Companion/non-player revival targets keep the pre-existing
get_player-based limitation (shared with out-of-combat), unchanged here.

Forwarding is a mock-resolver unit; the revival-gate-on-target behavior is one real-PG e2e (dev DB).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sample_fixtures import make_context

from combat_support import AbilityCastOutcome, _resolve_ability_packet
from declarations import Declaration, DeclarationType
from session_data import CombatParticipant
from spell_casting import _UNCHANGED, CastResult


def _player_participant() -> CombatParticipant:
    return CombatParticipant(id="caster_1", name="Lyra", type="player", initiative=15, hp_current=20, hp_max=20, ac=14)


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
    """The in-combat ABILITY path forwards Declaration.target_id into the shared _resolve_cast."""

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
            cast_resolver=cast_resolver,
            conn=object(),
            player=None,
            cast_outcome=outcome,
        )

        assert summary["resolved"] is True
        _args, kwargs = cast_resolver._resolve_cast.call_args
        assert kwargs["target_id"] == "ally_3"  # the declaration's target reached the cast core

    @pytest.mark.asyncio
    async def test_forwards_none_for_self_cast_ability(self):
        session = make_context(player_id="caster_1").userdata
        decl = Declaration(type=DeclarationType.ABILITY, action="arcane_bolt")  # no target_id
        cast_resolver = _cast_resolver({})
        outcome = AbilityCastOutcome()

        await _resolve_ability_packet(
            session,
            _player_participant(),
            decl,
            cast_resolver=cast_resolver,
            conn=object(),
            player=None,
            cast_outcome=outcome,
        )

        _args, kwargs = cast_resolver._resolve_cast.call_args
        assert kwargs["target_id"] is None  # self-cast ABILITY stays target-less
