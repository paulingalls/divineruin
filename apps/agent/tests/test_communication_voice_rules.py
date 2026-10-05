from typing import cast
from unittest.mock import patch

import pytest
from combat._reaction_helpers import _guarded_ally_state
from livekit.agents.llm import ToolError
from sample_fixtures import FixedRng
from voice_condition_fixtures import participant, place_actors, spatial_record

import communication_voice_rules as voice
from check_tools import _check_impl
from conditions import apply_condition
from tools._helpers import _ctx_with_bus, _social_mocks


def silence(state, actor_id):
    spatial_record(state)["positions"][actor_id]["x"] = 100
    spatial_record(state)["zones"]["quiet"] = {"kind": "silence", "center_id": actor_id, "radius_ft": 5}


@pytest.mark.parametrize("kind", [voice.CommunicationKind.VISUAL, voice.CommunicationKind.OTHER])
def test_nonspoken_delivery_preserves_legitimate_route(kind):
    state = _guarded_ally_state()
    silence(state, "player_1")
    participant(state, "player_2").conditions = apply_condition([], "deafened", source="test")
    voice.require_delivery(kind, state, "player_1", ["player_2"])


def test_unknown_kind_and_corrupt_condition_refuse_loudly():
    with pytest.raises(ValueError, match="kind"):
        voice.require_delivery(cast(voice.CommunicationKind, "invented"), None, "speaker", ["target"])
    with pytest.raises(ValueError):
        voice.require_delivery(
            voice.CommunicationKind.SPOKEN,
            None,
            "speaker",
            ["target"],
            rows={"target": {"conditions": [{"type": "bad"}]}},
        )


@pytest.mark.parametrize("refusal", ["source", "deafened", "silence", "absent", "placement"])
@pytest.mark.asyncio
async def test_public_social_refuses_before_roll_mutation_and_events(refusal):
    ctx = _ctx_with_bus()
    state = place_actors(_guarded_ally_state(), "merchant_1")
    ctx.userdata.combat_state = state
    if refusal == "source":
        silence(state, "player_1")
    elif refusal == "deafened":
        participant(state, "merchant_1").conditions = apply_condition([], "deafened", source="test")
    elif refusal == "silence":
        silence(state, "merchant_1")
    elif refusal == "absent":
        state.participants = [p for p in state.participants if p.id != "merchant_1"]
        del spatial_record(state)["positions"]["merchant_1"]
        del spatial_record(state)["speeds"]["merchant_1"]
        spatial_record(state)["locations"]["merchant_1"] = {"x": 50, "y": 0, "z": 0}
    else:
        del spatial_record(state)["positions"]["merchant_1"]
    queries, mutations, content = _social_mocks()
    with patch("social_tools.check_resolution.resolve_skill_check_dc", side_effect=AssertionError("rolled")) as roll:
        with pytest.raises(ToolError, match=r"speak|hear|participant|actor|spatial"):
            await _check_impl(
                ctx,
                "social",
                npc_id="merchant_1",
                skill="persuasion",
                difficulty="moderate",
                queries=queries,
                mutations=mutations,
                content=content,
            )
    roll.assert_not_called()
    mutations.set_npc_disposition.assert_not_awaited()
    assert not ctx.userdata.event_bus.emit.called


@pytest.mark.parametrize("combat", [False, True])
@pytest.mark.asyncio
async def test_deafened_speaker_can_converse_with_eligible_recipient(combat):
    from social_tools import _check_social_impl

    ctx = _ctx_with_bus()
    queries, mutations, content = _social_mocks()
    queries.get_player.return_value = {
        **queries.get_player.return_value,
        "conditions": apply_condition([], "deafened", source="test"),
    }
    if combat:
        state = place_actors(_guarded_ally_state(), "merchant_1")
        participant(state, "player_1").conditions = apply_condition([], "deafened", source="test")
        silence(state, "goblin_scout_1")
        ctx.userdata.combat_state = state
    result = await _check_social_impl(
        ctx,
        "merchant_1",
        "persuasion",
        "moderate",
        queries=queries,
        mutations=mutations,
        content=content,
        rng=FixedRng(11),
    )
    assert "narrative_cue" in result


@pytest.mark.parametrize("kind", list(voice.CommunicationKind))
def test_nonspoken_modes_bypass_only_delivery_not_actor_integrity(kind):
    state = _guarded_ally_state()
    with pytest.raises(ValueError, match="participant"):
        voice.require_delivery(kind, state, "player_1", ["absent"])


@pytest.mark.parametrize("restriction", ["source_silence", "recipient_silence", "recipient_deafened"])
def test_typed_spoken_seam_checks_each_delivery_requirement(restriction):
    state = _guarded_ally_state()
    if restriction == "source_silence":
        silence(state, "player_1")
    elif restriction == "recipient_silence":
        silence(state, "player_2")
    else:
        participant(state, "player_2").conditions = apply_condition([], "deafened", source="test")
    with pytest.raises(voice.DeliveryRefused):
        voice.require_delivery(voice.CommunicationKind.SPOKEN, state, "player_1", ["player_2"])
