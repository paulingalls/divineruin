import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._reaction_helpers import _guarded_ally_state
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod
from voice_condition_fixtures import participant, spatial_record

import abilities
import ability_tools
import ability_voice_rules as voice
import mentor_variants
import reaction_windows
from conditions import apply_condition

ROWS = json.loads((Path(__file__).resolve().parents[3] / "content/archetype_abilities.json").read_text())
APPROVED = json.loads((Path(__file__).parent / "fixtures/approved_ability_delivery.json").read_text())
SPEAKERS = sorted(key for key, policy in APPROVED.items() if policy in {"both", "source", "preparation", "spell"})
LISTENERS = sorted(key for key, policy in APPROVED.items() if policy in {"both", "hearing"})


async def activate(
    ability_id, *, combat=False, source_silent=False, source_deaf=False, target_deaf=False, variant=None, entry=None
):
    ability = abilities.get_ability(ability_id)
    ctx = make_context(party_member_ids=["player_2"])
    conditions = apply_condition([], "deafened", source="test")
    rows = {
        pid: {
            "player_id": pid,
            "class": ability.archetype_id,
            "level": 20,
            "stamina": {"current": 100},
            "focus": {"current": 100},
            "conditions": conditions if deaf else [],
        }
        for pid, deaf in [("player_1", source_deaf), ("player_2", target_deaf)]
    }
    if combat:
        state = _guarded_ally_state()
        participant(state, "player_1").conditions = rows["player_1"]["conditions"]
        participant(state, "player_2").conditions = rows["player_2"]["conditions"]
        state.open_window = reaction_windows.open_window_for(
            round_number=1,
            seq=0,
            stage="pre_roll",
            actor_id="goblin_scout_1",
            target_id="player_2",
            action_kind="attack",
            triggers=(ability.window,) if ability.window else ("on_ally_targeted",),
        )
        if source_silent:
            spatial_record(state)["positions"]["player_1"]["x"] = 100
            spatial_record(state)["zones"]["quiet"] = {"kind": "silence", "center_id": "player_1", "radius_ft": 5}
        ctx.userdata.combat_state = state
    db_mod, _ = make_db_mod()
    queries = MagicMock(get_players_for_update=AsyncMock(return_value=rows))
    persistence = MagicMock(
        owns_elective=AsyncMock(return_value=True),
        get_active_variant=AsyncMock(return_value=variant),
        update_player_resources=AsyncMock(),
    )
    mutations = MagicMock(save_many_player_conditions=AsyncMock())
    function = entry or ability_tools._request_ability_activation_impl
    with ctx.userdata._bind_authenticated_actor("player_1", 1, lambda *_: None):
        try:
            result = await function(
                ctx,
                ability_id,
                target_id="player_2",
                variant_id=variant,
                db_mod=db_mod,
                queries_mod=queries,
                persistence_mod=persistence,
                conditions_mutations_mod=mutations,
            )
        except ToolError:
            persistence.update_player_resources.assert_not_awaited()
            mutations.save_many_player_conditions.assert_not_awaited()
            raise
    return json.loads(result), persistence, queries


@pytest.mark.parametrize("ability_id", SPEAKERS)
@pytest.mark.asyncio
async def test_unlocked_packet_requires_source_speech_for_every_authored_id(ability_id):
    with pytest.raises(ToolError, match=r"silenced|speak"):
        await activate(
            ability_id, combat=True, source_silent=True, entry=ability_tools._request_ability_activation_unlocked
        )


@pytest.mark.parametrize("ability_id", LISTENERS)
@pytest.mark.asyncio
async def test_actual_ooc_packets_require_target_hearing_and_lock_target(ability_id):
    with pytest.raises(ToolError, match=r"hear|eligible"):
        await activate(ability_id, target_deaf=True)


@pytest.mark.parametrize("ability_id", sorted(voice.POLICIES))
@pytest.mark.asyncio
async def test_existing_eligible_packets_preserve_authored_effect(ability_id):
    if abilities.get_ability(ability_id).save is not None:
        with pytest.raises(ToolError, match="needs a foe"):
            await activate(ability_id)
        return
    result, _, queries = await activate(ability_id, source_deaf=True)
    assert result["effect"] == abilities.get_ability(ability_id).effect
    assert result["narration_cue"]
    if ability_id in LISTENERS:
        assert queries.get_players_for_update.call_args.args[0] == ["player_1", "player_2"]


@pytest.mark.parametrize("ability_id", sorted(voice.PREPARATION | voice.SOURCE))
@pytest.mark.asyncio
async def test_source_only_and_preparation_packets_do_not_invent_self_hearing(ability_id):
    result, _, _ = await activate(ability_id, source_deaf=True, target_deaf=True)
    assert result["effect"]


@pytest.mark.parametrize("ability_id", ["guardian_fortify", "warrior_taunt", "bard_silver_tongue"])
@pytest.mark.asyncio
async def test_mentor_form_inherits_guard_and_existing_packet(ability_id):
    variant = mentor_variants.get_variants_for_ability(ability_id)[0]
    with pytest.raises(ToolError, match=r"silenced|speak"):
        await activate(
            ability_id,
            combat=True,
            source_silent=True,
            variant=variant.id,
            entry=ability_tools._request_ability_activation_unlocked,
        )
    result, _, _ = await activate(ability_id, variant=variant.id)
    assert result["effect"] == variant.effect
    assert result["cultural_attribution"] == variant.cultural_attribution


@pytest.mark.parametrize("entry", ["declaration", "resolution"])
@pytest.mark.parametrize("restriction", ["source_silence", "recipient_deafened", "recipient_silence"])
@pytest.mark.asyncio
async def test_spoken_combat_boundaries_refuse_before_mutations_or_delegate(entry, restriction):
    import combat_ability
    from combat_turn import _declare_phase_impl
    from declarations import resolve_declaration

    state = _guarded_ally_state()
    state.beat = "declaration"
    ctx = make_context()
    ctx.userdata.combat_state = state
    if restriction.endswith("silence"):
        actor_id = "player_1" if restriction.startswith("source") else "player_2"
        spatial_record(state)["positions"][actor_id]["x"] = 100
        spatial_record(state)["zones"]["quiet"] = {"kind": "silence", "center_id": actor_id, "radius_ft": 5}
    else:
        participant(state, "player_2").conditions = apply_condition([], "deafened", source="test")
    raw = {"type": "ability", "action": "warrior_taunt", "target_id": "player_2"}
    before = state.to_dict()
    mutations = MagicMock(save_combat_state=AsyncMock())
    caster = MagicMock(_resolve_cast=AsyncMock(side_effect=AssertionError("delegated")))
    with pytest.raises((ValueError, ToolError), match=r"speak|silenced|hear"):
        if entry == "declaration":
            await _declare_phase_impl(ctx, {"player_1": raw}, mutations=mutations)
        else:
            await combat_ability._resolve_ability_packet(
                ctx.userdata,
                participant(state, "player_1"),
                resolve_declaration(raw),
                state=state,
                cast_resolver=caster,
                conn=None,
                player={"stamina": {"current": 100}},
                cast_outcome=combat_ability.AbilityCastOutcome(),
            )
    assert state.to_dict() == before
    mutations.save_combat_state.assert_not_awaited()
    caster._resolve_cast.assert_not_awaited()


@pytest.mark.parametrize("ability_id", ["guardian_inspiring_presence", "beastcaller_command_companion"])
@pytest.mark.asyncio
async def test_authored_nonspoken_sources_remain_usable_when_silenced(ability_id):
    result, _, _ = await activate(
        ability_id,
        combat=True,
        source_silent=True,
        source_deaf=True,
        entry=ability_tools._request_ability_activation_unlocked,
    )
    assert result["effect"] == abilities.get_ability(ability_id).effect
