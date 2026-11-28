"""Match every catalog reaction to the windows the held-action producers open."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from archetype_abilities_config_fixture import load_fixture_config
from combat._helpers import _make_combat_state, _own_reaction
from combat.test_reaction_window_census import movement_state
from sample_fixtures import catalog_encounters, make_context
from voice_condition_fixtures import place_actors

import combat_hold
import reaction_spend
import reaction_windows
from combat_phase import PhaseBeat
from query_tools import _query_abilities_impl
from reaction_gate import validate_reaction_activation

_CULT_CELL = next(encounter for encounter in catalog_encounters() if encounter["id"] == "cult_cell")
_LEADER = next(enemy for enemy in _CULT_CELL["enemies"] if enemy["id"] == "cult_leader")
_HOLD_PERSON = next(action for action in _LEADER["action_pool"] if action["name"] == "Hold Person")

# The windows the real producer can emit, one entry per held-action shape it distinguishes.
# Built by calling reaction_windows, never transcribed: a trigger set copied into this file would
# certify the copy (constraint 9).
_PRODUCIBLE = {
    "pre_roll_attack": ("pre_roll", "attack", "player_1", reaction_windows.pre_roll_triggers({})),
    "pre_roll_command": ("pre_roll", "command", "player_1", reaction_windows.pre_roll_triggers({})),
    "pre_roll_accusation": ("pre_roll", "accusation", "player_1", reaction_windows.pre_roll_triggers({})),
    "post_roll_hit": ("post_roll", "attack", "player_1", reaction_windows.post_roll_triggers({}, hit=True)),
    "post_roll_ally_hit": ("post_roll", "attack", "player_2", reaction_windows.post_roll_triggers({}, hit=True)),
    "post_roll_miss": ("post_roll", "attack", "player_1", reaction_windows.post_roll_triggers({}, hit=False)),
    "post_roll_grapple": (
        "post_roll",
        "attack",
        "player_1",
        reaction_windows.post_roll_triggers({"properties": [reaction_windows.GRAPPLE_PROPERTY]}, hit=True),
    ),
}


def _paused_state(shape, *, action=None):
    if shape is None:
        state = movement_state()
    else:
        stage, kind, target_id, triggers = shape
        state = _make_combat_state()
        if target_id == "player_2":
            place_actors(state, target_id)
        action_name = action["name"] if action else "Scimitar"
        if action:
            enemy = state.get_participant("goblin_scout_1")
            assert enemy is not None
            enemy.action_pool = [action]
        state.held_actions = [
            combat_hold.new_head(
                state, "goblin_scout_1", 12, {"type": "attack", "action": action_name, "target_id": target_id}
            )
        ]
        state.open_window = reaction_windows.open_window_for(
            round_number=1,
            seq=0,
            stage=stage,
            actor_id="goblin_scout_1",
            target_id=target_id,
            action_kind=kind,
            triggers=triggers,
        )
    state.beat = PhaseBeat.NARRATION
    state.reactions_available = {"player_1": reaction_spend.unspent()}
    return state


def _produced_states():
    states = {name: _paused_state(shape) for name, shape in {**_PRODUCIBLE, "movement": None}.items()}
    states["spell"] = _paused_state(
        ("pre_roll", "attack", "player_1", reaction_windows.pre_roll_triggers(_HOLD_PERSON)), action=_HOLD_PERSON
    )
    return states


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
    states = _produced_states()
    reachable = {}
    for ability_id, window in (await _queried_reactions()).items():
        answered = {
            name: state
            for name, state in states.items()
            if state.open_window is not None and window in state.open_window["triggers"]
        }
        assert answered, f"{ability_id} advertises {window!r}, which no held action ever opens"
        for state in answered.values():
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
async def test_the_two_window_vocabularies_are_one():
    import abilities

    produced = set()
    for state in _produced_states().values():
        assert state.open_window is not None
        produced.update(state.open_window["triggers"])
    consumed = set((await _queried_reactions()).values())

    assert produced <= abilities.REACTION_WINDOWS
    assert produced == consumed
