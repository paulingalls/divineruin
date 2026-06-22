"""Travel agent tool (M4.6b / story-003).

`_travel_impl` is the IO half of travel: it reads the player + destination, rolls a Survival
navigation check, drives the pure `travel_engine.resolve_travel_segment` engine, applies the returned
exhaustion via the `apply_condition` SSOT (capped by `rules_engine.exhaustion_stack_cap`),
persists `travel_state`, relocates the player on a successful (non-lost) journey by reusing
`db_mutations.update_player_location` (the same setter move_player uses — not a parallel
relocation path), emits a DICE_ROLL event, and returns a narration cue for the DM. Resolution
math is reused unchanged from travel_engine.py / check_resolution.py; this module only does plumbing + IO,
mirroring social_tools.py.

Spec: docs/game_mechanics/game_mechanics_combat.md §Travel and Exploration (L852-969).
"""

import json
import logging
import random

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import check_resolution
import conditions
import db_content_queries
import db_mutations
import db_queries
import event_types as E
import rules_engine
import travel as travel_engine
from db_errors import db_tool, validated_player_conditions
from game_events import publish_game_event
from session_data import SessionData
from tool_support import _validate_id

logger = logging.getLogger("divineruin.tools")

# Per-segment base travel time when the DM gives no estimate. The spec's distance-by-mode time
# matrix (L862-878, distance x mode) needs per-route distance data that doesn't exist yet, so the DM supplies an
# hours estimate (or this default). Forced march only bites past the 8h threshold (travel_engine.py).
_DEFAULT_SEGMENT_HOURS = 4
_NAV_SKILL = "survival"


@function_tool()
@db_tool
async def travel(
    context: RunContext[SessionData],
    destination_id: str,
    mode: str,
    hours: int = _DEFAULT_SEGMENT_HOURS,
    forced_march: bool = False,
) -> str:
    """Resolve a journey to a travel-reachable wilderness/road location. `mode` is one of
    'compressed' (safe montage), 'scenic' (narrated journey), or 'dangerous' (full gameplay) —
    pick from the player's intent ('quickly'/'a careful trip'/'push through the wilds'). Rolls a
    Survival navigation check against the destination's terrain, may cost time or get the party
    lost, accrues Exhaustion on a forced march or a bad miss in harsh terrain, and on a successful
    journey moves the player to the destination. Pass `forced_march=True` (and an `hours` estimate)
    when the party pushes on without rest."""
    return await _travel_impl(context, destination_id, mode, hours=hours, forced_march=forced_march)


async def _travel_impl(
    context: RunContext[SessionData],
    destination_id: str,
    mode: str,
    hours: int = _DEFAULT_SEGMENT_HOURS,
    forced_march: bool = False,
    *,
    queries=db_queries,
    mutations=db_mutations,
    content=db_content_queries,
    rng: random.Random | None = None,
) -> str:
    logger.info("travel: destination=%s, mode=%s, hours=%d, forced_march=%s", destination_id, mode, hours, forced_march)
    _validate_id(destination_id, "destination_id")
    mode_lower = mode.lower()
    # Fail loud off-catalog the same way the pure engine does — an unknown mode is a caller bug.
    try:
        travel_engine.travel_mode_params(mode_lower)
    except ValueError as e:
        raise ToolError(str(e)) from e

    session: SessionData = context.userdata
    player = await queries.get_player(session.player_id)
    if player is None:
        raise ToolError(f"Player '{session.player_id}' not found.")
    # Read-boundary guard (M4.4 story-008): a corrupt conditions row becomes a DM-narratable error,
    # and the validated list is the base the exhaustion producer applies onto.
    player_conditions = validated_player_conditions(player, session.player_id)

    destination = await content.get_location(destination_id)
    if destination is None:
        raise ToolError(f"Destination '{destination_id}' not found.")
    terrain = destination.get("terrain")
    if not terrain:
        raise ToolError(f"Destination '{destination_id}' has no terrain — not a travel-reachable location.")

    # navigation_dc fail-louds on an unknown terrain key (content drift); narrate it.
    try:
        dc = travel_engine.navigation_dc(terrain)
    except ValueError as e:
        raise ToolError(str(e)) from e

    roll = None
    if dc is not None:
        roll = check_resolution.resolve_skill_check_dc(player, _NAV_SKILL, dc, rng)

    result = travel_engine.resolve_travel_segment(
        mode=mode_lower,
        terrain=terrain,
        roll_total=roll.total if roll else 0,
        base_hours=hours,
        forced_march=forced_march,
        raw_die=roll.roll if roll else None,
    )

    # Exhaustion producer: apply the raw delta via the SSOT, capped by the character's stack cap
    # (the Iron-Constitution hook — rules_engine.exhaustion_stack_cap). Persist to players.data.conditions.
    if result.exhaustion_delta > 0:
        cap = rules_engine.exhaustion_stack_cap(player)
        new_conditions = player_conditions
        for _ in range(result.exhaustion_delta):
            new_conditions = conditions.apply_condition(new_conditions, "exhausted", source="travel", max_stacks=cap)
        await mutations.update_player_conditions(session.player_id, new_conditions)

    arrived = result.success and not result.wrong_area
    if arrived:
        await mutations.update_player_location(session.player_id, destination_id)
        session.location_id = destination_id
        await mutations.update_player_travel_state(session.player_id, None)
    else:
        # Lost: the party is off-course (no relocation); record the journey it was attempting.
        await mutations.update_player_travel_state(
            session.player_id, {"destination": destination_id, "mode": mode_lower, "wrong_area": result.wrong_area}
        )

    if roll is not None:
        await publish_game_event(
            session.room,
            E.DICE_ROLL,
            {
                "roll_type": "navigation_check",
                "skill": _NAV_SKILL,
                "roll": roll.roll,
                "total": roll.total,
                "success": result.success,
                "dramatic": result.dramatic,
                "context": result.context,
            },
            event_bus=session.event_bus,
        )

    session.record_event(f"Travel to {destination_id} ({mode_lower}): {result.narrative_cue}")
    payload = {
        "outcome": "success" if result.success else "failure",
        "destination": destination_id,
        "mode": mode_lower,
        "arrived": arrived,
        "dramatic": result.dramatic,
        "context": result.context,
        "narrative_cue": result.narrative_cue,
        "time_cost": result.time_cost,
        "exhaustion_gained": result.exhaustion_delta,
        "encounter_rate": result.encounter_rate,
        "foraging_available": result.foraging_available,
        "wrong_area": result.wrong_area,
    }
    if roll is not None:
        payload.update({"roll": roll.roll, "total": roll.total, "dc": result.dc, "margin": result.margin})
    return json.dumps(payload)
