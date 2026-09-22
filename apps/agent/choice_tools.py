"""Choice resolution tools — the generic ``select`` verb (M4, ADR 0007).

select resolves a pending player choice surfaced by a Resolve. Today the only
pending choice is the L5 specialization fork that ``_award_xp_core`` surfaces on
level-up (the SPECIALIZATION_CHOICE event's ``milestone_id`` is the id select
resolves against — it arrives from the tap/voice call, not from hand-off state
on the Resolve's result). select absorbed the
with-choice path of ``resolve_milestone``, which M4 story-004 removed; it enforces
immutability via the FOR UPDATE read, so a duplicate or concurrent resolution
loses cleanly.

Rewards are party-wide (M28 story-001), so the fork belongs to the authenticated speaker.

No event is published on resolution: the client dismisses the HUD overlay locally
on tap (the present-options SPECIALIZATION_CHOICE event is owned by the level-up
path in progression_tools).
"""

import json
import logging
import time

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import db
import db_queries
import milestone_persistence
import milestones
from db_errors import db_tool
from milestones import Milestone
from session_data import SessionData, SpecializationTap
from tool_support import _validate_id

logger = logging.getLogger("divineruin.tools")

# A ticket that the DM never consumes must eventually expire. It only labels the
# current speaker's matching tap; it never grants authority over another player.
SPECIALIZATION_TAP_TTL_S = 120.0


@function_tool()
@db_tool
async def select(
    context: RunContext[SessionData],
    choice_id: str,
    option: str,
) -> str:
    """Resolve a pending choice the HUD surfaced — today, the level-5 specialization
    fork. Pass the choice_id from the pending choice and the chosen option id. The
    choice is permanent. Do NOT call for the level 10/15/20 grants; those apply
    automatically on level-up."""
    return await _select_impl(context, choice_id, option)


def _fork_block_reason(player_id: str, player: dict | None, milestone: Milestone) -> str | None:
    """Why this speaker may not resolve this milestone, or None if they may."""
    if player is None:
        return f"Unknown player: {player_id}"
    if milestone.archetype_id != player.get("class"):
        return f"Choice '{milestone.id}' is not your specialization."
    if player.get("level", 1) < milestone.level:
        return f"You have not yet reached the milestone for '{milestone.id}'."
    existing = player.get("specialization")
    if existing:
        return f"Specialization already chosen ({existing}); it cannot be changed."
    return None


def _matched_ticket(session: SessionData, player_id: str, choice_id: str, option: str) -> SpecializationTap | None:
    """The fresh tap from this speaker for this choice, if present."""
    ticket = session.pending_specialization_tap
    if ticket is None:
        return None
    age = time.monotonic() - ticket.created_at
    if age > SPECIALIZATION_TAP_TTL_S:
        # Drop it rather than merely ignoring it: an expired ticket is dead evidence, and leaving
        # it in place would make every later call re-measure the same staleness.
        logger.info("Discarding stale specialization tap from %s (%.0fs old)", ticket.player_id, age)
        session.pending_specialization_tap = None
        return None
    if (
        ticket.milestone_id == choice_id
        and ticket.specialization_id == option
        and ticket.player_id == player_id
        and session.party.contains(ticket.player_id)
    ):
        return ticket
    return None


async def _select_impl(
    context: RunContext[SessionData],
    choice_id: str,
    option: str,
    *,
    db_mod=db,
    queries_mod=db_queries,
    persistence_mod=milestone_persistence,
    milestones_mod=milestones,
) -> str:
    context.disallow_interruptions()
    # Validate at the boundary before opening a transaction — choice_id/option are
    # externally supplied (DM voice tool-call or, in story-005, a HUD tap).
    _validate_id(choice_id, "choice_id")
    _validate_id(option, "option")
    session: SessionData = context.userdata
    target_id = session.acting_player_id
    logger.info("select called: choice_id=%s option=%s caller=%s", choice_id, option, target_id)

    # A second synchronous tap can replace the ticket at an await. Keep this
    # object's identity so this call cannot clear the replacement after commit.
    ticket = _matched_ticket(session, target_id, choice_id, option)

    async with db_mod.transaction() as conn:
        try:
            milestone = milestones_mod.get_milestone(choice_id)
        except ValueError as e:
            raise ToolError(f"Unknown choice: {choice_id}") from e

        # choice_id is external, so verify the milestone before the player row.
        if milestone.kind != "specialization_fork":
            raise ToolError(f"Choice '{choice_id}' is not a selectable choice.")
        if milestone.patron_deferred:
            raise ToolError(
                "Your specialization is shaped by your patron — available when the Patron system arrives (Phase 8)."
            )

        # This helper uses the same deterministic lock order as the party batch readers.
        rows = await queries_mod.get_players_for_update([target_id], conn=conn)

        if reason := _fork_block_reason(target_id, rows.get(target_id), milestone):
            raise ToolError(reason)

        valid_ids = {o.id for o in milestone.specialization_options}
        if option not in valid_ids:
            raise ToolError(f"Invalid option: {option}. Options: {sorted(valid_ids)}")

        session.validate_acting_player(target_id)
        await persistence_mod.set_player_specialization(target_id, option, conn=conn)

    # Clear only after commit, and only the ticket this call observed.
    if ticket is not None and session.pending_specialization_tap is ticket:
        session.pending_specialization_tap = None

    result = {
        "choice_id": choice_id,
        "chosen": option,
        "player_id": target_id,
        "narration_cue": milestone.narration_cue,
    }
    logger.info("select result: %s -> %s for %s", choice_id, option, target_id)
    return json.dumps(result)
