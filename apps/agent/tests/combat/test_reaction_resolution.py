"""Every reaction the DM can be told about, against every window the engine can open.

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
from combat._helpers import _activate, _call, _ctx_at_resolution, _make_combat_state, _resolve_deps
from sample_fixtures import make_context, make_mock_room, published_payloads

import event_types as E
import reaction_spend
import reaction_windows
from combat_phase import PhaseBeat, validate_reaction_activation
from query_tools import _query_abilities_impl

# The windows the real producer can emit, one entry per held-action shape it distinguishes.
# Built by calling reaction_windows, never transcribed: a trigger set copied into this file would
# certify the copy (constraint 9).
_PRODUCIBLE = {
    "pre_roll": reaction_windows.pre_roll_triggers({}),
    "post_roll_hit": reaction_windows.post_roll_triggers({}, hit=True),
    "post_roll_miss": reaction_windows.post_roll_triggers({}, hit=False),
    "post_roll_grapple": reaction_windows.post_roll_triggers(
        {"properties": [reaction_windows.GRAPPLE_PROPERTY]}, hit=True
    ),
}

NO_PRODUCER = {"on_enemy_move", "on_spell_cast"}


def _paused_state(triggers):
    state = _make_combat_state()
    state.beat = PhaseBeat.NARRATION
    state.open_window = reaction_windows.open_window_for(
        round_number=1,
        seq=0,
        stage="pre_roll",
        actor_id="goblin_scout_1",
        target_id="player_1",
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

    catalog = load_fixture_config().values()
    rows = {}
    for player_class in sorted({ability.archetype_id for ability in catalog}):
        queries.get_player = AsyncMock(return_value={"class": player_class})
        payload = json.loads(await _query_abilities_impl(context, queries=queries, persistence=persistence))
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
        answered = [name for name, triggers in _PRODUCIBLE.items() if window in triggers]
        assert answered, f"{ability_id} advertises {window!r}, which no held action ever opens"
        for name in answered:
            state = _paused_state(_PRODUCIBLE[name])
            assert validate_reaction_activation(state, "player_1", ability_id) is None, (ability_id, name)
        reachable[ability_id] = window

    assert reachable, "the sweep walked no reactions — the query producer went silent"


@pytest.mark.asyncio
async def test_a_reaction_whose_window_has_no_producer_is_refused_at_every_window():
    """Stated honestly rather than skipped: warrior_opportunity_strike (on_enemy_move) and
    mage_counterspell (on_spell_cast) cannot be spent, at any stage, on any held action."""
    unreachable = {i: w for i, w in (await _queried_reactions()).items() if w in NO_PRODUCER}
    assert unreachable.keys() == {"warrior_opportunity_strike", "mage_counterspell"}

    for ability_id, window in unreachable.items():
        for triggers in _PRODUCIBLE.values():
            state = _paused_state(triggers)
            with pytest.raises(ValueError, match=window):
                validate_reaction_activation(state, "player_1", ability_id)


@pytest.mark.asyncio
async def test_the_two_window_vocabularies_are_one():
    """reaction_windows emits nothing the ability catalog cannot consume, and the catalog
    advertises nothing outside abilities.REACTION_WINDOWS. Either drift ships a window the other
    side cannot read — the exact shape of the guess-among-nine defect constraint 6 names."""
    import abilities

    produced = {trigger for triggers in _PRODUCIBLE.values() for trigger in triggers}
    consumed = set((await _queried_reactions()).values())

    assert produced <= abilities.REACTION_WINDOWS
    assert produced == consumed - NO_PRODUCER


# --- the wired outcomes (story-018) ----------------------------------------------------------
#
# story-017 left a spend that named its ability and its blow and changed nothing. These are the
# two outcomes game_mechanics_combat.md:187 names and the tree did not have. The third
# (Counterspell) is NOT here: on_spell_cast has no producer (debt 08bc5548), and the sweep above
# pins it refused rather than shipping a vacuous guard for it.

UNCANNY_DODGE = "rogue_uncanny_dodge"


def _enemy_blow(packets: list[dict]) -> dict:
    """The held goblin attack's resolution summary — the one the reaction was spent against."""
    blows = [p for p in packets if p["actor_id"] == "goblin_scout_1" and "damage" in p]
    assert len(blows) == 1, f"expected exactly one resolved enemy blow, got {blows}"
    return blows[0]


async def _to_post_roll_pause(ctx, deps) -> dict:
    """Drive the round to the POST-ROLL, pre-damage pause on the held goblin blow.

    Three calls: the ally band (which holds the enemy action), the pre-roll window, then the roll
    plus the post-roll window. Nothing is spent at the pre-roll pause, so the post-roll one opens.
    """
    await _call(ctx, deps)
    await _call(ctx, deps)
    paused = await _call(ctx, deps)
    assert paused["next"]["waiting_on"]["stage"] == reaction_windows.POST_ROLL
    return paused


@pytest.mark.asyncio
async def test_uncanny_dodge_halves_the_damage_of_the_blow_it_answers():
    """AC1. The SAME seeded blow, run twice: the only difference is the spend.

    Asserted from BOTH ends on purpose. ``apply_attack_result`` writes HP from the roll's
    ABSOLUTE ``target_hp_remaining`` (combat_support.py:286) and never derives it from ``damage``,
    so halving the reported damage alone leaves hp_current at the unhalved value — and recomputing
    HP without rewriting the roll leaves the DICE_ROLL, the event line and the packet all
    narrating the full number at a player who took half.
    """
    room = make_mock_room()
    ctx = _ctx_at_resolution(room=room)
    deps = _resolve_deps(damage=6)
    await _to_post_roll_pause(ctx, deps)
    await _activate(ctx, UNCANNY_DODGE, player_class="rogue")
    final = await _call(ctx, deps)

    assert ctx.userdata.combat_state.get_participant("player_1").hp_current == 22
    assert _enemy_blow(final["packets"])["damage"] == 3
    dice = [p for p in published_payloads(room) if p.get("type") == E.DICE_ROLL and p.get("attacker") == "Goblin Scout"]
    assert [d["damage"] for d in dice] == [3]
    assert "Goblin Scout attacks Kael: hit, 3 damage" in ctx.userdata.recent_events


@pytest.mark.asyncio
async def test_the_same_blow_unanswered_deals_its_whole_damage():
    """The baseline half of AC1's "half what the SAME seeded roll deals without the reaction".

    Without it the test above pins a number, not a difference: a resolver that happened to deal 3
    would pass it while the reaction did nothing.
    """
    room = make_mock_room()
    ctx = _ctx_at_resolution(room=room)
    deps = _resolve_deps(damage=6)
    await _to_post_roll_pause(ctx, deps)
    final = await _call(ctx, deps)

    assert ctx.userdata.combat_state.get_participant("player_1").hp_current == 19
    assert _enemy_blow(final["packets"])["damage"] == 6
    dice = [p for p in published_payloads(room) if p.get("type") == E.DICE_ROLL and p.get("attacker") == "Goblin Scout"]
    assert [d["damage"] for d in dice] == [6]
