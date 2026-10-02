import copy
import random
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from combat._helpers import _make_combat_state
from sample_fixtures import make_context

import check_resolution_attack
import combat_hold
from declarations import Declaration, DeclarationType

LUNGE = {
    "name": "Lunge",
    "damage": "1d1",
    "damage_type": "piercing",
    "properties": ["grapple"],
    "escape_dc": 12,
    "advantage": True,
    "recharge": {"kind": "roll", "die": 6, "threshold": 5},
}


def deps(seed=0):
    resolver = MagicMock()
    resolver.resolve_attack.side_effect = lambda *a, **k: check_resolution_attack.resolve_attack(
        *a, **k, rng=random.Random(seed)
    )
    return dict(
        resolver=resolver,
        sink=MagicMock(emit=AsyncMock()),
        mutations=MagicMock(update_player_hp=AsyncMock()),
        queries=MagicMock(get_player_inventory=AsyncMock(return_value=[])),
        concentration_break_mod=MagicMock(break_concentration_on_damage=AsyncMock(return_value=None)),
    )


def setup(action=LUNGE):
    state = _make_combat_state(player_hp=25)
    actor = state.participants[1]
    actor.action_pool = [copy.deepcopy(action)]
    packet = SimpleNamespace(
        actor_id=actor.id,
        declaration=Declaration(type=DeclarationType.ATTACK, action=action["name"], target_id=state.participants[0].id),
    )
    return state, actor, packet


async def wrap(state):
    import combat_wrap
    from combat_ability import AbilityCastOutcome

    state.beat = "narration"
    result = await combat_wrap.wrap_phase(
        make_context().userdata,
        state,
        conn=None,
        sink=MagicMock(emit=AsyncMock()),
        cast_outcome=AbilityCastOutcome(),
        mutations=MagicMock(save_combat_state=AsyncMock()),
        queries=MagicMock(),
        save_resolver=MagicMock(),
        resonance_mutations=MagicMock(update_player_resonance=AsyncMock()),
    )
    return result[0]


def hold(state, actor):
    import reaction_spend

    player = state.participants[0]
    player.has_reaction_ability = True
    player.reaction_ids = ["skirmisher_sidestep", "rogue_uncanny_dodge"]
    state.reactions_available[player.id] = reaction_spend.unspent()
    state.pending_declarations = {
        actor.id: {"type": "attack", "action": actor.action_pool[0]["name"], "target_id": player.id}
    }
    state.held_actions = combat_hold.hold_enemy_packets(state, [SimpleNamespace(actor_id=actor.id, initiative=12)])
