"""Each live boundary rejects before delegating to another owned guard."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from combat.test_voice_condition_restrictions import attack, charm_state
from sample_fixtures import make_context
from voice_condition_fixtures import place_actors

import abilities
import combat_ability
import combat_hold
import condition_voice_rules
from declarations import resolve_declaration


@pytest.mark.asyncio
async def test_spell_ability_boundary_refuses_before_cast_delegate():
    state = charm_state()
    ctx = make_context()
    ctx.userdata.combat_state = state
    caster = MagicMock(_resolve_cast=AsyncMock())
    decl = resolve_declaration({"type": "ability", "action": "arcane_bolt", "target_id": "goblin_scout_1"})
    with pytest.raises(ValueError, match="Charmed"):
        await combat_ability._resolve_ability_packet(
            ctx.userdata,
            state.participants[0],
            decl,
            state=state,
            cast_resolver=caster,
            conn=object(),
            player={},
            cast_outcome=combat_ability.AbilityCastOutcome(),
        )
    caster._resolve_cast.assert_not_awaited()


@pytest.mark.asyncio
async def test_hostile_condition_ability_boundary_refuses_before_cost():
    state = charm_state()
    actor = state.participants[0]
    ability = abilities.get_ability("warrior_unstoppable_charge")
    decl = resolve_declaration({"type": "ability", "action": ability.id, "target_id": "goblin_scout_1"})
    persistence = MagicMock(update_player_resources=AsyncMock())
    with pytest.raises(ValueError, match="Charmed"):
        await combat_ability._resolve_ability_condition_packet(
            make_context().userdata,
            actor,
            decl,
            (ability, None),
            state=state,
            conn=object(),
            player={"stamina": {"current": 20}},
            persistence=persistence,
        )
    persistence.update_player_resources.assert_not_awaited()


def test_held_attack_condition_gate_precedes_reaction_windows():
    state = charm_state()
    head = {"actor_id": "player_1", "declaration": attack()}
    assert combat_hold._is_wasted(state, head) is True
    assert combat_hold._opens_windows(state, head) is False
    state.participants[0].conditions = []
    assert combat_hold._is_wasted(state, head) is False
    assert combat_hold._opens_windows(state, head) is True


def test_partial_spoken_targets_and_nonspoken_control():
    state = charm_state()
    state.participants[0].conditions = []
    state.participants[1].conditions = [{"type": "deafened"}]
    assert condition_voice_rules.spoken_buff_targets(
        "inspired",
        state,
        "player_1",
        ["goblin_scout_1", "other"],
    ) == ["other"]
    assert condition_voice_rules.spoken_buff_targets(
        "blessed",
        state,
        "player_1",
        ["goblin_scout_1", "other"],
    ) == ["goblin_scout_1", "other"]
    assert state.spatial is not None
    state.spatial["zones"] = {"quiet": {"kind": "silence", "center_id": "player_1", "radius_ft": 0}}
    with pytest.raises(ValueError, match="silenced"):
        condition_voice_rules.spoken_buff_targets("inspired", state, "player_1", ["other"])


@pytest.mark.parametrize("kind", ["attack", "save", "skill"])
def test_position_scoped_inspired_retained_until_eligible(kind):
    from sample_fixtures import FixedRng

    import check_resolution
    import check_resolution_attack
    import check_resolution_save
    import conditions

    state = charm_state()
    assert state.spatial is not None
    actor = state.participants[0]
    actor.conditions = [{"type": "inspired"}, {"type": "blessed"}]
    state.spatial["zones"] = {"quiet": {"kind": "silence", "center_id": "other", "radius_ft": 0}}

    def roll():
        player = condition_voice_rules.roll_data({}, state, actor.id)
        if kind == "attack":
            return check_resolution_attack.resolve_attack(player, {"damage": "1d1"}, 10, 30, rng=FixedRng(10))
        if kind == "save":
            return check_resolution_save.resolve_saving_throw(player, "wisdom", 8, "stunned", rng=FixedRng(10))
        return check_resolution.resolve_skill_check_dc(
            player, "athletics", 8, rng=FixedRng(10), ally_present=False, hearing_only=False
        )

    result = roll()
    assert "inspired" not in result.consumed_conditions
    for consumed in result.consumed_conditions:
        actor.conditions = conditions.remove_condition(actor.conditions, consumed)
    assert any(c["type"] == "inspired" for c in actor.conditions)
    state.spatial["positions"][actor.id]["x"] = 40
    assert roll().consumed_conditions == ("inspired",)


def test_attack_producer_carries_position_eligibility_to_real_resolver():
    from combat_attack_roll import roll_attack

    state = charm_state()
    assert state.spatial is not None
    actor = state.participants[0]
    actor.conditions = [{"type": "inspired"}, {"type": "blessed"}]
    state.spatial["zones"] = {"quiet": {"kind": "silence", "center_id": "other", "radius_ft": 0}}
    result, _ = roll_attack(actor, actor.action_pool[0], state.participants[1], combat_state=state)
    assert result.consumed_conditions == ("blessed",)
    assert any(c["type"] == "inspired" for c in actor.conditions)


@pytest.mark.asyncio
async def test_public_condition_consumer_waits_for_combat_writer_lock(monkeypatch):
    import asyncio

    import check_tools

    ctx = make_context()
    ctx.userdata.combat_state = charm_state()
    queries = MagicMock(get_player=AsyncMock(return_value={"conditions": []}))
    monkeypatch.setattr(check_tools, "publish_game_event", AsyncMock())
    async with ctx.userdata.combat_state_lock:
        task = asyncio.create_task(check_tools._check_save_impl(ctx, "wisdom", 8, "stunned", queries=queries))
        await asyncio.sleep(0)
        queries.get_player.assert_not_awaited()
    await task
    queries.get_player.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    [
        attack(),
        {"type": "maneuver", "action": "shove", "target_id": "goblin_scout_1"},
        {"type": "ability", "action": "arcane_fireball", "target_id": "other"},
    ],
)
async def test_public_declaration_refusal_leaves_availability_and_pending_unchanged(raw):
    from livekit.agents.llm import ToolError

    from combat_turn import _declare_phase_impl

    state = charm_state()
    before = state.to_dict()
    ctx = make_context()
    ctx.userdata.combat_state = state
    mutations = MagicMock(save_combat_state=AsyncMock())
    with pytest.raises(ToolError, match="Charmed"):
        await _declare_phase_impl(ctx, {"player_1": raw}, mutations=mutations)
    assert ctx.userdata.combat_state.to_dict() == before
    mutations.save_combat_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_silenced_social_communication_refuses_before_queries():
    from livekit.agents.llm import ToolError

    from social_tools import _check_social_impl

    state = place_actors(charm_state(), "npc")
    assert state.spatial is not None
    state.spatial["zones"] = {"quiet": {"kind": "silence", "center_id": "other", "radius_ft": 0}}
    ctx = make_context()
    ctx.userdata.combat_state = state
    queries = MagicMock(get_player=AsyncMock())
    with pytest.raises(ToolError, match="silenced"):
        await _check_social_impl(ctx, "npc", "persuasion", "easy", queries=queries)
    queries.get_player.assert_not_awaited()


@pytest.mark.parametrize("restriction", ["deafened", "silenced"])
def test_condition_landing_independently_excludes_spoken_recipient(restriction):
    from combat_condition_landing import _land_condition_on_one

    state = charm_state()
    assert state.spatial is not None
    source, target = state.participants[0], state.participants[2]
    source.conditions = []
    if restriction == "deafened":
        target.conditions = [{"type": "deafened"}]
    else:
        state.spatial["positions"][target.id]["x"] = 40
        state.spatial["zones"] = {"quiet": {"kind": "silence", "center_id": target.id, "radius_ft": 0}}
    before = list(target.conditions)
    assert not _land_condition_on_one(state, target.id, source, "inspired", "bard_inspire", packet={})
    assert target.conditions == before


@pytest.mark.asyncio
async def test_ooc_landing_independently_excludes_spoken_recipient():
    from combat.test_inspire_producer import _bard

    from condition_produce import produce_ooc_condition

    writes = MagicMock(save_many_player_conditions=AsyncMock())
    caster = _bard("player_1")
    target = _bard("other", [{"type": "deafened"}])
    voiced = await produce_ooc_condition(
        "inspired",
        "bard_inspire",
        target_id="other",
        target_ids=None,
        companion_id=None,
        caster_row=caster,
        caster_id="player_1",
        party_member_ids=["player_1", "other"],
        conditions_mutations_mod=writes,
        locked_rows={"player_1": caster, "other": target},
        conn=object(),
    )
    assert voiced == []
    writes.save_many_player_conditions.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "producer", ["skill", "save", "discover_empty", "discover_candidate", "social", "gather", "travel"]
)
async def test_public_roll_producers_carry_current_combat_spoken_eligibility(producer, monkeypatch):
    import check_discovery
    import check_resolution
    import check_resolution_save
    import check_tools
    import gathering_tools
    import social_tools
    import travel_tools
    from tools._helpers import SAMPLE_PLAYER

    state = place_actors(charm_state(), "npc") if producer == "social" else charm_state()
    state.participants[0].conditions = [{"type": "deafened"}, {"type": "inspired"}]
    ctx = make_context()
    ctx.userdata.combat_state = state
    queries = MagicMock(get_player=AsyncMock(return_value={**SAMPLE_PLAYER, "conditions": []}))
    location = {
        "region": "greyvale",
        "resource_table": {"common": ["oak_wood"]},
        "terrain": "known_trail",
        "hidden_elements": [{"id": "secret", "discover_skill": "perception", "dc": 8}]
        if producer == "discover_candidate"
        else [],
    }
    content = MagicMock(
        get_location=AsyncMock(return_value=location), get_gathering_nodes_at_location=AsyncMock(return_value=[])
    )
    calls = []

    class ReachedResolver(Exception):
        pass

    def observe(player, *_args, **kwargs):
        calls.append(player)
        assert player.get("spoken_buffs_eligible") is False
        assert player["conditions"] == state.participants[0].conditions
        assert kwargs.get("hearing_only", False) is False
        raise ReachedResolver

    monkeypatch.setattr(check_resolution, "resolve_skill_check", observe)
    monkeypatch.setattr(check_resolution, "resolve_skill_check_dc", observe)
    monkeypatch.setattr(check_resolution_save, "resolve_saving_throw", observe)
    with pytest.raises(ReachedResolver):
        if producer == "skill":
            await check_tools._check_skill_impl(ctx, "athletics", "easy", "climb", hearing_only=False, queries=queries)
        elif producer == "save":
            await check_tools._check_save_impl(ctx, "wisdom", 8, "stunned", queries=queries)
        elif producer.startswith("discover"):
            await check_discovery._check_discover_impl(
                ctx, "perception", "wall", hearing_only=False, queries=queries, content=content
            )
        elif producer == "social":
            await social_tools._check_social_impl(ctx, "npc", "persuasion", "easy", queries=queries)
        elif producer == "gather":
            await gathering_tools._check_gather_impl(ctx, "", queries=queries, content=content)
        else:
            await travel_tools._travel_impl(ctx, "dest", "scenic", queries=queries, content=content)
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["held", "packet"])
@pytest.mark.parametrize("corruption", ["policy", "spatial", "source"])
async def test_resolution_preserves_loud_guard_integrity_errors(entry, corruption, monkeypatch):
    from combat._helpers import _resolve_deps

    import ability_voice_rules
    import combat_packet
    from combat_phase import ResolutionPacket

    state = charm_state()
    actor = state.participants[0]
    actor.conditions = []
    raw = {"type": "ability", "action": "warrior_taunt", "target_id": "other"}
    if corruption == "policy":
        monkeypatch.delitem(ability_voice_rules.POLICIES, "warrior_taunt")
        message = "Unclassified"
    elif corruption == "spatial":
        state.spatial = None
        message = "placement"
    else:
        actor.conditions = [{"type": "charmed", "source": "missing"}]
        message = "not a combat participant"
    deps = _resolve_deps()
    ctx = make_context()
    ctx.userdata.combat_state = state
    with pytest.raises(ValueError, match=message):
        if entry == "held":
            combat_hold._is_wasted(state, {"actor_id": actor.id, "declaration": raw})
        else:
            await combat_packet._resolve_one_packet(
                ctx.userdata,
                state,
                ResolutionPacket(actor.id, resolve_declaration(raw), 15),
                mutations=deps["mutations"],
                queries=deps["queries"],
                resolver=deps["resolver"],
                concentration_break_mod=deps["concentration_break_mod"],
            )
    deps["resolver"].resolve_attack.assert_not_called()
    deps["mutations"].update_player_hp.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("restriction", ["silence", "charm"])
async def test_combat_cast_uses_working_state_after_earlier_packet_changes(restriction):
    from copy import deepcopy
    from functools import partial
    from types import SimpleNamespace

    from _spell_casting_helpers import _known, _player

    import spell_casting
    import spells

    pristine = charm_state()
    actor = pristine.participants[0]
    actor.conditions = []
    if restriction == "silence":
        assert pristine.spatial is not None
        pristine.spatial["zones"] = {"quiet": {"kind": "silence", "center_id": "other", "radius_ft": 0}}
    else:
        actor.conditions = [{"type": "charmed", "source": "goblin_scout_1"}]
    working = deepcopy(pristine)
    if restriction == "silence":
        assert working.spatial is not None
        working.spatial["positions"]["other"]["x"] = 40
    else:
        working.participants[0].conditions = []
    ctx = make_context()
    ctx.userdata.combat_state = pristine
    persistence = MagicMock(update_player_resources=AsyncMock())
    mutations = MagicMock(update_player_resonance=AsyncMock())
    caster = SimpleNamespace(
        _resolve_cast=partial(
            spell_casting._resolve_cast,
            persistence_mod=persistence,
            resonance_mutations_mod=mutations,
            character_spells_mod=_known("arcane_bolt"),
            ward_resolution_mod=MagicMock(resolve_scope_ward=AsyncMock(return_value=None)),
        )
    )
    outcome = combat_ability.AbilityCastOutcome()
    result = await combat_ability._resolve_ability_packet(
        ctx.userdata,
        working.participants[0],
        resolve_declaration({"type": "ability", "action": "arcane_bolt", "target_id": "goblin_scout_1"}),
        state=working,
        cast_resolver=caster,
        conn=object(),
        player=_player(),
        cast_outcome=outcome,
    )
    assert result["resolved"] is True
    assert result["cast"]["effect"] == spells.get_spell("arcane_bolt").mechanics
    assert set(outcome.results) == {"player_1"}
    assert ctx.userdata.combat_state is pristine
    assert pristine.to_dict() != working.to_dict()
