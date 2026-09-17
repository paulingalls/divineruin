import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _resolution_state, _resolve_deps
from livekit.agents.llm import ToolError
from sample_fixtures import make_context

import combat_phase
import combat_turn
import reaction_gate
import reaction_spend
from combat_init import _start_combat_impl
from session_data import CombatParticipant, CombatState


def _roundtrip_with_ownership(state, ownership) -> CombatState:
    player = state.get_participant("player_1")
    assert player is not None
    player.has_reaction_ability = ownership
    serialized = state.to_dict()
    if ownership is None:
        for participant in serialized["participants"]:
            if participant["id"] == "player_1":
                participant.pop("has_reaction_ability")
    return CombatState.from_dict(json.loads(json.dumps(serialized)))


def _context(state):
    ctx = make_context()
    ctx.userdata.combat_state = state
    return ctx


async def _step(ctx, deps):
    result = await combat_turn._resolve_phase_impl(ctx, **deps)
    assert not isinstance(result, tuple)
    return json.loads(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ownership", "opens_window"),
    [
        pytest.param(True, True, id="true"),
        pytest.param(False, False, id="false"),
        pytest.param(None, True, id="absent"),
    ],
)
async def test_roundtripped_ownership_controls_the_window(ownership, opens_window):
    state = _resolution_state()
    state.reactions_available = {"player_1": reaction_spend.unspent()}
    ctx = _context(_roundtrip_with_ownership(state, ownership))
    deps = _resolve_deps(damage=3)

    await _step(ctx, deps)
    result = await _step(ctx, deps)

    if opens_window:
        assert result["next"]["waiting_on"]["stage"] == "pre_roll"
        return
    current = ctx.userdata.combat_state
    assert result["next"]["waiting_on"] is None
    assert current.get_participant("player_1").hp_current == 22
    assert current.held_actions == []
    assert result["beat"] == "declaration"


@pytest.mark.asyncio
async def test_mixed_party_skips_non_owner_budget_and_one_owner_opens_window():
    state = _resolution_state()
    non_owner = state.get_participant("player_1")
    assert non_owner is not None
    non_owner.has_reaction_ability = False
    owner = CombatParticipant(
        id="player_2",
        name="Bren",
        type="player",
        initiative=8,
        hp_current=20,
        hp_max=20,
        ac=14,
        has_reaction_ability=True,
    )
    state.participants.append(owner)
    state.initiative_order.append(owner.id)
    # is_spent({}) raises KeyError, so a gate that consults the non-owner reds here.
    state.reactions_available = {non_owner.id: {}, owner.id: reaction_spend.unspent()}
    ctx = _context(state)

    await _step(ctx, _resolve_deps())
    result = await _step(ctx, _resolve_deps())

    assert result["next"]["waiting_on"]["stage"] == "pre_roll"


@pytest.mark.asyncio
async def test_known_owner_with_spent_reaction_opens_no_window():
    state = _resolution_state()
    owner = state.get_participant("player_1")
    assert owner is not None
    owner.has_reaction_ability = True
    state.reactions_available = {
        owner.id: reaction_spend.spend(
            "warrior_parry",
            {"id": "r1-0-pre_roll", "stage": "pre_roll"},
            held_seq=0,
        )
    }
    assert state.reactions_available[owner.id]
    ctx = _context(state)
    deps = _resolve_deps(damage=3)

    await _step(ctx, deps)
    result = await _step(ctx, deps)

    assert result["next"]["waiting_on"] is None
    assert ctx.userdata.combat_state.get_participant(owner.id).hp_current == 22


def test_declaration_refresh_seeds_only_owners_and_legacy_unknowns():
    state = _resolution_state()
    state.beat = combat_phase.PhaseBeat.DECLARATION
    known_owner = state.get_participant("player_1")
    assert known_owner is not None
    known_owner.has_reaction_ability = True
    state.participants.extend(
        [
            CombatParticipant("player_2", "Bren", "player", 8, 20, 20, 14, has_reaction_ability=False),
            CombatParticipant("player_3", "Cyra", "player", 7, 20, 20, 14),
        ]
    )

    refreshed, _ = combat_phase.advance_combat_phase(state, {known_owner.id: {"type": "defend"}})

    assert set(refreshed.reactions_available) == {"player_1", "player_3"}


def _start_mocks(player_class, player_level=6):
    mutations = MagicMock(save_combat_state=AsyncMock())
    queries = MagicMock(
        get_player=AsyncMock(
            return_value={
                "player_id": "player_1",
                "name": "Kael",
                "class": player_class,
                "level": player_level,
                "hp": {"current": 25, "max": 25},
                "attributes": {"dexterity": 12},
                "equipment": {},
            }
        )
    )
    content = MagicMock(
        get_encounter_template=AsyncMock(return_value={"id": "empty_road", "name": "Empty Road", "enemies": []})
    )
    return mutations, queries, content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("player_class", "owns_reaction", "reaction_ids"),
    [
        pytest.param("warrior", True, ["warrior_brace_for_impact", "warrior_opportunity_strike"], id="warrior"),
        pytest.param("artificer", False, [], id="artificer"),
        pytest.param("beastcaller", False, [], id="beastcaller"),
        pytest.param("seeker", False, [], id="seeker"),
    ],
)
async def test_start_combat_derives_reaction_ownership_from_real_class_catalog(
    player_class, owns_reaction, reaction_ids, mock_combat_agent_factory
):
    mutations, queries, content = _start_mocks(player_class)
    ctx = make_context()

    await _start_combat_impl(
        ctx,
        encounter_id="empty_road",
        encounter_description="The road is quiet.",
        mutations=mutations,
        queries=queries,
        content=content,
    )

    participant = ctx.userdata.combat_state.get_participant("player_1")
    assert participant.has_reaction_ability is owns_reaction
    assert participant.reaction_ids == reaction_ids
    persisted = mutations.save_combat_state.await_args.args[1]
    assert persisted["participants"][0]["has_reaction_ability"] is owns_reaction
    assert persisted["participants"][0]["reaction_ids"] == reaction_ids


def test_a_saved_combat_without_reaction_ids_loads_an_empty_list():
    serialized = _resolution_state().to_dict()
    for participant in serialized["participants"]:
        participant.pop("reaction_ids")

    loaded = CombatState.from_dict(json.loads(json.dumps(serialized)))

    assert all(participant.reaction_ids == [] for participant in loaded.participants)


@pytest.mark.asyncio
async def test_each_window_names_only_the_reactions_the_gate_would_accept():
    state = _resolution_state()
    player = state.get_participant("player_1")
    assert player is not None
    player.has_reaction_ability = True
    player.reaction_ids = ["rogue_uncanny_dodge", "rogue_slippery"]
    state.reactions_available = {"player_1": reaction_spend.unspent()}
    ctx = _context(state)
    deps = _resolve_deps(damage=3)

    await _step(ctx, deps)
    pre_roll = (await _step(ctx, deps))["next"]["waiting_on"]
    post_roll = (await _step(ctx, deps))["next"]["waiting_on"]

    assert pre_roll["stage"] == "pre_roll"
    assert pre_roll["reactions"] == []
    assert post_roll["stage"] == "post_roll"
    assert post_roll["reactions"] == [{"actor_id": "player_1", "id": "rogue_uncanny_dodge", "name": "Uncanny Dodge"}]


@pytest.mark.asyncio
async def test_a_downed_player_is_offered_no_reaction_and_cannot_spend_one():
    state = _resolution_state()
    player = state.get_participant("player_1")
    assert player is not None
    player.has_reaction_ability = True
    player.reaction_ids = ["rogue_uncanny_dodge"]
    state.reactions_available = {"player_1": reaction_spend.unspent()}
    ctx = _context(state)
    deps = _resolve_deps(damage=3)
    await _step(ctx, deps)
    await _step(ctx, deps)
    await _step(ctx, deps)
    paused = ctx.userdata.combat_state
    assert paused.open_window is not None and paused.open_window["stage"] == "post_roll"
    downed = paused.get_participant("player_1")
    assert downed is not None
    downed.is_fallen = True

    assert reaction_gate.offered_reactions(paused) == []
    with pytest.raises(ValueError, match="down"):
        reaction_gate.validate_reaction_activation(paused, "player_1", "rogue_uncanny_dodge")


def test_a_stored_reaction_id_the_catalog_does_not_know_fails_loud():
    state = _resolution_state()
    player = state.get_participant("player_1")
    assert player is not None
    player.reaction_ids = ["rogue_no_such_reaction"]

    with pytest.raises(ValueError, match="Unknown ability"):
        reaction_gate.offered_reactions(state)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("player_class", "refusal"),
    [
        pytest.param("not_a_class", "'not_a_class' with no catalog abilities", id="unknown"),
        pytest.param(None, "invalid class None", id="missing"),
    ],
)
async def test_start_combat_refuses_a_class_with_no_catalog_rows(player_class, refusal, mock_combat_agent_factory):
    mutations, queries, content = _start_mocks(player_class)

    with pytest.raises(ToolError, match=refusal):
        await _start_combat_impl(
            make_context(),
            encounter_id="empty_road",
            encounter_description="The road is quiet.",
            mutations=mutations,
            queries=queries,
            content=content,
        )

    mutations.save_combat_state.assert_not_awaited()
