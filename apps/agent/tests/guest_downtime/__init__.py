from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from sample_fixtures import make_context


def guest_context(validator=lambda _player, _generation: None):
    context = make_context(party_member_ids=["player_2"])
    return context, context.userdata._bind_authenticated_actor("player_2", 1, validator)


def seam(**attrs) -> Any:
    return SimpleNamespace(**attrs)


def module(**methods) -> Any:
    return SimpleNamespace(**{key: AsyncMock(return_value=value) for key, value in methods.items()})


def player_by_id(player_id, **_):
    return {
        "player_id": player_id,
        "class": "mage" if player_id == "player_2" else "warrior",
        "level": 5,
        "gold": 20 if player_id == "player_2" else 1,
        "skill_tiers": {"crafting": "master" if player_id == "player_2" else "untrained"},
    }


def pricing():
    return module(
        get_economy_pricing={
            "disposition_multipliers": {"friendly": 0.8, "trusted": 0.6},
            "silver_per_gold": 10,
            "repair_cost_sp": {"common": 2},
        }
    )


def smith_queries(guest_disposition="trusted"):
    queries = module(get_player=None, get_npcs_at_location=[{"id": "grimjaw"}], get_npc_disposition=None)
    queries.get_player.side_effect = player_by_id
    queries.get_npc_disposition.side_effect = lambda _npc, player_id, **_: (
        guest_disposition if player_id == "player_2" else "neutral"
    )
    return queries


def revocable_context():
    state = {"revoked": False}

    def validate(_player, _generation):
        if state["revoked"]:
            raise RuntimeError("stale generation")

    context, actor = guest_context(validate)
    return context, actor, state


def revoke_after(mock, state):
    prior = mock.side_effect

    async def call(*args, **kwargs):
        result = prior(*args, **kwargs) if prior is not None else mock.return_value
        if hasattr(result, "__await__"):
            result = await result
        state["revoked"] = True
        return result

    mock.side_effect = call


def transaction_probe():
    from contextlib import asynccontextmanager

    state = {"rolled_back": False, "committed": False}

    @asynccontextmanager
    async def transaction():
        try:
            yield object()
        except BaseException:
            state["rolled_back"] = True
            raise
        else:
            state["committed"] = True

    return seam(transaction=transaction), state
