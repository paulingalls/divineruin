"""Patron standing, abilities, and ecosystem cues for world queries."""

import json

from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import db_mutations_resonance
import db_queries
import unbound_tools
from _gods_content import load_gods
from combat_terrain import resolve_terrain
from patron_ability_tools import project_abilities
from patron_favor import get_patron_tier
from patron_gifts import UNBOUND_ALONE_BONUS, thyra_gift
from patron_synergy import synergy_for_patron
from session_data import SessionData
from terrain import is_natural


async def query_patron(
    context: RunContext[SessionData],
    *,
    queries=db_queries,
    gods_loader=load_gods,
) -> str:
    session: SessionData = context.userdata
    player_id = session.acting_player_id
    player = await queries.get_player(player_id)
    favor = player.get("divine_favor") if player else None
    if favor is None:
        raise ToolError("Cannot query patron: current player has no divine_favor row.")

    track = await db_mutations_resonance.read_player_resonance(player_id)
    tier = get_patron_tier(favor)
    if tier is None:
        return json.dumps(
            {
                **unbound_tools.patron_query(track),
                "synergy": None,
                "alone_bonus": {
                    "amount": UNBOUND_ALONE_BONUS,
                    "description": "+1 to all skill checks when no ally is present.",
                    "applies_now": not session.ally_present_for(player_id),
                },
            }
        )

    patron_id = favor["patron"]
    patron = next((row for row in gods_loader() if row["god_id"] == patron_id), None)
    if patron is None:
        raise ToolError(f"Cannot query patron: unknown patron id {patron_id!r}.")

    try:
        synergy = synergy_for_patron(player.get("class"), patron)
    except ValueError as error:
        raise ToolError(f"Cannot query patron: {error}") from error

    next_tier = None
    favor_needed = None
    for level in range(favor["level"] + 1, favor["max"] + 1):
        candidate_tier = get_patron_tier({**favor, "level": level})
        if candidate_tier != tier:
            next_tier = candidate_tier
            favor_needed = level - favor["level"]
            break

    return json.dumps(
        {
            "patron_id": patron_id,
            "synergy": synergy,
            "resonance": {"state": track["state"]},
            "short_name": patron["short_name"],
            "title": patron["title"],
            "tier": tier,
            "level": favor["level"],
            "max": favor["max"],
            "next_tier": next_tier,
            "favor_needed_to_next_tier": favor_needed,
            "favor_actions": patron["favor_actions"],
            "layer_1_gift": patron["layer_1_gift"],
            "abilities": project_abilities(player, patron),
            **await ecosystem_cue(session, favor),
        }
    )


async def ecosystem_cue(session: SessionData, favor: dict) -> dict:
    gift = thyra_gift(favor)
    if gift is None or not is_natural(await resolve_terrain(session)):
        return {}
    location_id = session.combat_state.location_id if session.combat_state is not None else session.location_id
    return {
        "ecosystem_health_cue": {
            "gift_name": gift["name"],
            "location_id": location_id,
            "instruction": "Narrate the ecosystem health sensed by Nature's Pulse without a check, using available location facts.",
        }
    }
