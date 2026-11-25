"""Patron standing, abilities, and ecosystem cues for world queries."""

import json

from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import db_mutations_resonance
import db_queries
import patron_gateway
import patron_senses
import unbound_tools
import veythar_wellspring
import zhael_fate
from _gods_content import load_gods
from combat_terrain import resolve_terrain
from patron_ability_tools import project_abilities
from patron_combat_edges import COMMUNITY_SHIELD, SCALES_VERDICT, VEILSTEP, VEILSTEP_RANGE_FT, WILDMOTHERS_WRATH
from patron_favor import get_patron_tier
from patron_gifts import UNBOUND_ALONE_BONUS, thyra_gift
from patron_synergy import synergy_for_patron
from patron_zero_hp import DAWNS_EMBRACE, DEATH_WARD
from session_data import SessionData
from terrain import is_natural
from thyra_thornwall import GIFT as THORNWALL


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
                **unbound_tools.patron_query(track, player),
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

    gift = patron["layer_1_gift"]
    if gift["id"] == zhael_fate.FATE:
        gift = {**gift, **zhael_fate.availability(player, gift)}
    abilities = project_abilities(player, patron)
    for ability in abilities:
        if ability["id"] == veythar_wellspring.ECHO:
            if veythar_wellspring.state(player).get("armed"):
                ability["activation_hint"] = "Wellspring Echo is armed. " + veythar_wellspring.ARMED_HINT
            elif ability["available"]:
                ability["activation_hint"] = (
                    f'Use activate(id="{veythar_wellspring.ECHO}") to arm Wellspring Echo. '
                    + veythar_wellspring.ARMED_HINT
                )
        elif ability["id"] == DEATH_WARD:
            ability["activation_hint"] = (
                "Triggers automatically when damage reduces you from above 0 HP to 0 HP. You stay at 1 HP."
            )
        elif ability["id"] == DAWNS_EMBRACE:
            ability["activation_hint"] = (
                "Triggers automatically when damage drops another party player or the companion to 0 HP. "
                "They stand at half maximum HP, rounded down with a minimum of 1."
            )
        elif ability["id"] == COMMUNITY_SHIELD:
            ability["activation_hint"] = (
                f'Use activate(id="{COMMUNITY_SHIELD}", target_id=<other present party player id>). '
                "Grants temporary HP immediately in or out of combat, equal to your level plus your Charisma "
                "modifier, at least 1. Refuses if it would not increase the target's pool."
            )
        elif ability["id"] == VEILSTEP:
            ability["activation_hint"] = (
                f'Use activate(id="{VEILSTEP}", destination={{x,y,z}}). '
                f"Choose a visible shadow within {VEILSTEP_RANGE_FT} feet. Coordinates are in feet. "
                "Full movement is retained. A queued move is removed and can be redeclared at the next declaration beat. "
                "Omit destination without fight geometry and narrate the step."
            )
        elif ability["id"] == THORNWALL:
            ability["activation_hint"] = (
                f'Use activate(id="{THORNWALL}", destination={{start:{{x,y,z}},end:{{x,y,z}}}}) in combat. '
                "Use feet. The wall can be up to 30 feet long, with its nearest point within 30 feet, clear of creatures."
            )
        elif ability["id"] == WILDMOTHERS_WRATH:
            ability["activation_hint"] = (
                f'Use activate(id="{WILDMOTHERS_WRATH}") in combat on natural ground. '
                "The gift lands immediately on every living, unprotected foe."
            )
        elif ability["id"] == SCALES_VERDICT:
            ability["activation_hint"] = (
                f'Use activate(id="{SCALES_VERDICT}", target_id=<living hostile creature id in this fight>).'
            )
        elif ability["id"] == patron_gateway.GATEWAY and ability["available"]:
            ability["destinations"] = await patron_gateway.destinations(player_id, session.location_id)
            ability["activation_hint"] = (
                f'Use activate(id="{patron_gateway.GATEWAY}", target_id=<visited location id>).'
            )

    senses = {}
    if patron_id == "mortaen":
        senses["deaths_awareness"] = await patron_senses.deaths_awareness(session, player, queries=queries)
    elif patron_id == "nythera":
        senses["horizon_sense"] = await patron_senses.horizon_sense(session, player)
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
            "layer_1_gift": gift,
            "abilities": abilities,
            **await ecosystem_cue(session, favor),
            **senses,
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
