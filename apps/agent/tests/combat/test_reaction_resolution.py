"""Reaction declaration, activation, and resolution packet contract."""

import json
from unittest.mock import AsyncMock, MagicMock

from _combat_end_fixtures import combat_end_mutations
from combat._helpers import _damage_resolver, _fake_db_mod, _make_combat_state
from sample_fixtures import make_context, make_db_mod

from ability_tools import _request_ability_activation_impl
from combat_turn import _declare_phase_impl, _resolve_phase_impl


def _declarations():
    return {
        "player_1": {
            "type": "reaction",
            "action": "warrior_opportunity_strike",
            "trigger": "on_enemy_move",
        },
        "goblin_scout_1": {
            "type": "attack",
            "action": "Scimitar",
            "target_id": "player_1",
        },
    }


def _mutations():
    mutations = combat_end_mutations()
    mutations.save_combat_state = AsyncMock()
    mutations.update_player_hp = AsyncMock()
    return mutations


def _resolve_deps(mutations):
    queries = MagicMock()
    queries.get_player_inventory = AsyncMock(return_value=[])
    break_mod = MagicMock()
    break_mod.break_concentration_on_damage = AsyncMock(return_value=None)
    return {
        "mutations": mutations,
        "queries": queries,
        "resolver": _damage_resolver(3),
        "concentration_break_mod": break_mod,
        "db_mod": _fake_db_mod(),
    }


async def _activate_reaction(ctx):
    db_mod, _conn = make_db_mod()
    queries = MagicMock()
    queries.get_players_for_update = AsyncMock(
        return_value={
            "player_1": {
                "player_id": "player_1",
                "class": "warrior",
                "stamina": {"current": 5, "max": 10},
                "focus": {"current": 5, "max": 10},
            }
        }
    )
    persistence = MagicMock()
    persistence.update_player_resources = AsyncMock()
    persistence.get_active_variant = AsyncMock(return_value=None)
    persistence.owns_elective = AsyncMock(return_value=False)
    await _request_ability_activation_impl(
        ctx,
        "warrior_opportunity_strike",
        db_mod=db_mod,
        queries_mod=queries,
        persistence_mod=persistence,
    )


async def test_activated_reaction_resolves_in_phase_packet():
    ctx = make_context()
    ctx.userdata.combat_state = _make_combat_state()
    mutations = _mutations()
    await _declare_phase_impl(ctx, _declarations(), mutations=mutations)
    await _activate_reaction(ctx)

    raw = await _resolve_phase_impl(ctx, **_resolve_deps(mutations))
    assert isinstance(raw, str)
    result = json.loads(raw)

    reaction = next(packet for packet in result["packets"] if packet["actor_id"] == "player_1")
    assert reaction == {
        "actor_id": "player_1",
        "resolved": True,
        "declaration_type": "reaction",
        "ability_id": "warrior_opportunity_strike",
    }


async def test_unactivated_reaction_remains_unresolved_in_phase_packet():
    ctx = make_context()
    ctx.userdata.combat_state = _make_combat_state()
    mutations = _mutations()
    await _declare_phase_impl(ctx, _declarations(), mutations=mutations)

    raw = await _resolve_phase_impl(ctx, **_resolve_deps(mutations))
    assert isinstance(raw, str)
    result = json.loads(raw)

    reaction = next(packet for packet in result["packets"] if packet["actor_id"] == "player_1")
    assert reaction["resolved"] is False
    assert reaction["reason"] == "reaction was declared but not activated"


async def test_actor_absent_from_the_budget_map_never_resolves_for_free():
    """Absent actor => unspent => unresolved. The packet reader's lookup default is the ONLY
    thing standing between a declaration made by someone with no budget entry -- a companion,
    or a combat persisted before the map existed -- and a free, uncosted reaction."""
    ctx = make_context()
    ctx.userdata.combat_state = _make_combat_state()
    mutations = _mutations()
    await _declare_phase_impl(ctx, _declarations(), mutations=mutations)
    ctx.userdata.combat_state.reactions_available.clear()

    raw = await _resolve_phase_impl(ctx, **_resolve_deps(mutations))
    assert isinstance(raw, str)
    result = json.loads(raw)

    reaction = next(packet for packet in result["packets"] if packet["actor_id"] == "player_1")
    assert reaction["resolved"] is False
    assert reaction["reason"] == "reaction was declared but not activated"
