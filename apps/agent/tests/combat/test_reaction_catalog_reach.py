"""Every reaction the DM can be told about, against every window the engine can open.

The catalog/window VOCABULARY half. What a spent reaction then does to the blow is
test_reaction_resolution.py — a different concern, and keeping both in one file put it over the
500-line cap (constraint 2).

story-017 made a reaction an INTERRUPT: the permission is the open Beat-3 window, not a Beat-1
declaration. So the contract to hold is between two producers that must share one vocabulary —
``query_tools._query_abilities_impl``, which surfaces each reaction's ``window`` to the DM, and
``reaction_windows``, which mints the ``triggers`` a held enemy action offers. A reaction whose
advertised window no producible window ever carries is a capability the DM can name and never
spend (constraint 6), so this walks the WHOLE catalog rather than one class's first reaction.

Two windows have no producer at all and are asserted REFUSED rather than papered over:
``on_enemy_move`` (no movement model — debt d3ff4ff4) and ``on_spell_cast`` (no enemy casting —
debt 08bc5548). Their reactions are unreachable by design until those land.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from archetype_abilities_config_fixture import load_fixture_config
from combat._helpers import _make_combat_state
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
    """The accept half, catalog-wide: each advertised window is one the engine actually opens.

    A gate that read a constant "on_hit" would still accept the reactions carrying that window,
    so the sweep has to name which producible window answered each id — and refuse to accept a
    reaction at a window that does not carry its trigger."""
    reachable = {}
    for ability_id, window in (await _queried_reactions()).items():
        if window in NO_PRODUCER:
            continue
        answered = [name for name, shape in _PRODUCIBLE.items() if window in shape[3]]
        assert answered, f"{ability_id} advertises {window!r}, which no held action ever opens"
        for name in answered:
            state = _paused_state(_PRODUCIBLE[name])
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
    """Stated honestly rather than skipped: warrior_opportunity_strike (on_enemy_move) and
    mage_counterspell (on_spell_cast) cannot be spent, at any stage, on any held action."""
    unreachable = {i: w for i, w in (await _queried_reactions()).items() if w in NO_PRODUCER}
    assert unreachable.keys() == {"warrior_opportunity_strike", "mage_counterspell"}

    for ability_id, window in unreachable.items():
        for shape in _PRODUCIBLE.values():
            state = _paused_state(shape)
            with pytest.raises(ValueError, match=window):
                validate_reaction_activation(state, "player_1", ability_id)


@pytest.mark.asyncio
async def test_the_two_window_vocabularies_are_one():
    """reaction_windows emits nothing the ability catalog cannot consume, and the catalog
    advertises nothing outside abilities.REACTION_WINDOWS. Either drift ships a window the other
    side cannot read — the exact shape of the guess-among-nine defect constraint 6 names."""
    import abilities

    produced = {trigger for shape in _PRODUCIBLE.values() for trigger in shape[3]}
    consumed = set((await _queried_reactions()).values())

    assert produced <= abilities.REACTION_WINDOWS
    assert produced == consumed - NO_PRODUCER
