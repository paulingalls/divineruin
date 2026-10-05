"""on_enemy_move and on_spell_cast have no producer and remain refused, not silently treated as supported."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from archetype_abilities_config_fixture import load_fixture_config
from combat._helpers import _make_combat_state, _own_reaction
from sample_fixtures import make_context

import reaction_spend
import reaction_windows
from combat_phase import PhaseBeat
from query_tools import _query_abilities_impl
from reaction_gate import validate_reaction_activation

# The windows the real producer can emit, one entry per held-action shape it distinguishes.
# Built by calling reaction_windows, never transcribed: a trigger set copied into this file would
# certify the copy (constraint 9).
_PRODUCIBLE = {
    "pre_roll_attack": ("pre_roll", "attack", "player_1", reaction_windows.pre_roll_triggers({})),
    "pre_roll_command": ("pre_roll", "command", "player_1", reaction_windows.pre_roll_triggers({})),
    "pre_roll_accusation": ("pre_roll", "accusation", "player_1", reaction_windows.pre_roll_triggers({})),
    "post_roll_hit": ("post_roll", "attack", "player_1", reaction_windows.post_roll_triggers({}, hit=True)),
    "post_roll_miss": ("post_roll", "attack", "player_1", reaction_windows.post_roll_triggers({}, hit=False)),
    "post_roll_grapple": (
        "post_roll",
        "attack",
        "player_1",
        reaction_windows.post_roll_triggers({"properties": [reaction_windows.GRAPPLE_PROPERTY]}, hit=True),
    ),
}

NO_PRODUCER = {"on_enemy_move", "on_spell_cast"}


def _paused_state(shape):
    stage, kind, target_id, triggers = shape
    state = _make_combat_state()
    state.beat = PhaseBeat.NARRATION
    state.open_window = reaction_windows.open_window_for(
        round_number=1,
        seq=0,
        stage=stage,
        actor_id="goblin_scout_1",
        target_id=target_id,
        action_kind=kind,
        triggers=triggers,
    )
    state.reactions_available = {"player_1": reaction_spend.unspent()}
    return state


async def _queried_reactions():
    """Every reaction row the DM can be shown, for every archetype — the producer's own output."""
    context = make_context()
    queries = MagicMock()
    persistence = MagicMock()
    persistence.get_character_abilities = AsyncMock(return_value=[])
    persistence.get_active_variant = AsyncMock(return_value=None)
    library = MagicMock()
    library.get_known = AsyncMock(return_value=[])

    catalog = load_fixture_config().values()
    rows = {}
    for player_class in sorted({ability.archetype_id for ability in catalog}):
        queries.get_player = AsyncMock(return_value={"class": player_class, "level": 6})
        payload = json.loads(
            await _query_abilities_impl(context, queries=queries, persistence=persistence, character_spells_mod=library)
        )
        for row in payload["abilities"]:
            if row["ability_type"] == "reaction":
                rows[row["id"]] = row["window"]
    assert rows.keys() == {a.id for a in catalog if a.ability_type == "reaction"}
    return rows


@pytest.mark.asyncio
async def test_every_queried_reaction_window_is_answered_by_a_real_open_window():
    """Match each advertised id to its actual trigger; a constant accepting on_hit would hide other broken windows."""
    reachable = {}
    for ability_id, window in (await _queried_reactions()).items():
        if window in NO_PRODUCER:
            continue
        answered = [name for name, shape in _PRODUCIBLE.items() if window in shape[3]]
        assert answered, f"{ability_id} advertises {window!r}, which no held action ever opens"
        for name in answered:
            state = _paused_state(_PRODUCIBLE[name])
            _own_reaction(state, ability_id)
            try:
                validate_reaction_activation(state, "player_1", ability_id)
            except ValueError:
                continue
            break
        else:
            raise AssertionError(f"{ability_id} fits none of {answered}")
        reachable[ability_id] = window

    assert reachable, "the sweep walked no reactions — the query producer went silent"


@pytest.mark.asyncio
async def test_a_reaction_whose_window_has_no_producer_is_refused_at_every_window():
    unreachable = {i: w for i, w in (await _queried_reactions()).items() if w in NO_PRODUCER}
    assert unreachable.keys() == {"warrior_opportunity_strike", "mage_counterspell"}

    for ability_id, window in unreachable.items():
        for shape in _PRODUCIBLE.values():
            state = _paused_state(shape)
            _own_reaction(state, ability_id)
            with pytest.raises(ValueError, match=window):
                validate_reaction_activation(state, "player_1", ability_id)


@pytest.mark.asyncio
async def test_the_two_window_vocabularies_are_one():
    import abilities

    produced = {trigger for shape in _PRODUCIBLE.values() for trigger in shape[3]}
    consumed = set((await _queried_reactions()).values())

    assert produced <= abilities.REACTION_WINDOWS
    assert produced == consumed - NO_PRODUCER
