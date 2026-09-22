import asyncio
from typing import cast

import pytest

from session_data import AuthenticatedActor, SessionData


def party_session() -> SessionData:
    from caster_state import ConcentrationState, ResonanceTrack
    from party_state import PartyMember

    sd = SessionData(player_id="player-one", location_id="loc")
    sd.party.members.append(
        PartyMember(
            player_id="player-two",
            resonance=ResonanceTrack(),
            concentration=ConcentrationState(),
        )
    )
    return sd


async def test_actor_binding_survives_await_and_clears_after_success_and_failure() -> None:
    sd = SessionData(player_id="player-one", location_id="loc")
    from caster_state import ConcentrationState, ResonanceTrack
    from party_state import PartyMember

    sd.party.members.append(
        PartyMember(
            player_id="player-two",
            resonance=ResonanceTrack(),
            concentration=ConcentrationState(),
        )
    )

    with pytest.raises(RuntimeError, match="No actor"):
        _ = sd.actor_player_id
    with sd._bind_authenticated_actor("player-two", 1, lambda *_: None):
        assert sd.actor_player_id == "player-two"
        await asyncio.sleep(0)
        assert sd.actor_player_id == "player-two"
    with pytest.raises(RuntimeError, match="No actor"):
        _ = sd.actor_player_id

    with pytest.raises(LookupError):
        with sd._bind_authenticated_actor("player-two", 1, lambda *_: None):
            raise LookupError("tool failed")
    with pytest.raises(RuntimeError, match="No actor"):
        _ = sd.actor_player_id
    with sd._bind_authenticated_actor("player-one", 1, lambda *_: None):
        assert sd.actor_player_id == "player-one"


async def test_binding_refuses_an_identity_that_is_not_a_party_member() -> None:
    sd = party_session()

    with pytest.raises(ValueError, match="stranger"):
        with sd._bind_authenticated_actor("stranger", 1, lambda *_: None):
            pass  # pragma: no cover - the bind must refuse before the body runs
    with pytest.raises(RuntimeError, match="No actor"):
        _ = sd.actor_player_id


def test_authenticated_binding_refuses_an_identity_that_is_not_a_party_member() -> None:
    sd = party_session()

    with pytest.raises(ValueError, match="stranger"):
        with sd._bind_authenticated_actor("stranger", 1, lambda *_args: None):
            pass  # pragma: no cover - the bind must refuse before the body runs


def test_authenticated_actor_refuses_membership_removed_after_binding() -> None:
    sd = party_session()

    with sd._bind_authenticated_actor("player-two", 1, lambda *_args: None):
        sd.party.members = [sd.party.primary]
        with pytest.raises(ValueError, match="player-two"):
            sd.require_reaction_actor()


def test_string_binding_cannot_designate_even_a_party_member() -> None:
    sd = party_session()
    token = sd._actor_binding.set(cast(AuthenticatedActor, "player-two"))
    try:
        with pytest.raises(RuntimeError, match="Invalid actor binding"):
            _ = sd.actor_player_id
        with pytest.raises(RuntimeError, match="Invalid actor binding"):
            _ = sd.acting_player_id
        with pytest.raises(RuntimeError, match="Invalid actor binding"):
            sd.validate_acting_player("player-two")
        with pytest.raises(RuntimeError, match="Invalid actor binding"):
            _ = sd.player_id
    finally:
        sd._actor_binding.reset(token)
