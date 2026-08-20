"""Choice resolution tools — the generic ``select`` verb (M4, ADR 0007).

select resolves a pending player choice surfaced by a Resolve. Today the only
pending choice is the L5 specialization fork that ``_award_xp_core`` surfaces on
level-up (the SPECIALIZATION_CHOICE event's ``milestone_id`` is the id select
resolves against — it arrives from the tap/voice call, not from hand-off state
on the Resolve's result). select absorbed the
with-choice path of ``resolve_milestone``, which M4 story-004 removed; it enforces
immutability via the FOR UPDATE read, so a duplicate or concurrent resolution
loses cleanly.

Rewards are party-wide (M28 story-001), so the fork belongs to whichever member
crossed level 5 — NOT necessarily the session's primary. See ``_resolve_owner``
for how the owner is determined.

No event is published on resolution: the client dismisses the HUD overlay locally
on tap (the present-options SPECIALIZATION_CHOICE event is owned by the level-up
path in progression_tools).
"""

import json
import logging

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
    """Why ``player`` may not resolve ``milestone``, or None if they may.

    ONE predicate serving both the sole-claimant scan and the chosen target's raise path
    (concern 952048921755). Written out twice, the "nobody is eligible" fallback in
    ``_resolve_owner`` would be safe only by coincidence, and anyone later relaxing one
    copy would silently convert a refusal into an irreversible cross-write onto another
    member's write-once specialization. As one predicate it is a tautology.

    Milestone-level checks (``kind``, ``patron_deferred``) are deliberately NOT here: they
    are properties of the choice rather than of any player, and must reject before the scan
    runs — otherwise a patron-deferred fork would report "nobody has this pending".

    The message strings are the ones select has always raised; eight tests match on them.
    """
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


def _matched_ticket(session: SessionData, choice_id: str, option: str) -> SpecializationTap | None:
    """The recorded tap iff it is the one this call is resolving, else None.

    Deliberately strict: BOTH the milestone and the option must match, and the sender must
    still be in the party. A coincidental voice call cannot consume another member's ticket
    without naming the same choice AND the same option.
    """
    ticket = session.pending_specialization_tap
    if ticket is None:
        return None
    if (
        ticket.milestone_id == choice_id
        and ticket.specialization_id == option
        and session.party.contains(ticket.player_id)
    ):
        return ticket
    return None


def _resolve_owner(
    session: SessionData,
    rows: dict[str, dict],
    milestone: Milestone,
    choice_id: str,
    option: str,
) -> str:
    """Whose fork this call resolves.

    Two sources, in order:

    1. The tap ticket on SessionData — the LiveKit-verified sender of the HUD tap. This is
       the path that genuinely CONSUMES the recipient story-001 stamped onto the
       SPECIALIZATION_CHOICE event, rather than re-deriving it (concern d14ca8e0e733).
    2. A sole-claimant scan of the party. The voice path has to re-derive here, because no
       pending-choice record is persisted anywhere — ``PendingChoice`` was deleted as dead
       in story-003, and no per-speaker identity reaches the LLM. Exactly one claimant is
       unambiguous; two or more is not, and guessing would irreversibly write one member's
       choice onto another's row, so we refuse instead.
    """
    if ticket := _matched_ticket(session, choice_id, option):
        return ticket.player_id

    eligible = [pid for pid in session.party.member_ids if _fork_block_reason(pid, rows.get(pid), milestone) is None]
    if len(eligible) == 1:
        return eligible[0]
    if len(eligible) > 1:
        raise ToolError(
            f"More than one party member can still choose '{choice_id}' ({', '.join(eligible)}), "
            "and there is no way to tell whose choice this is. Ask them to tap their own "
            "specialization card."
        )
    # Nobody is eligible: fall back to the session's own player so the raise path below
    # reports the precise reason instead of a vague "nobody has this pending". Safe by
    # construction — had the primary no blocking reason, they would have been eligible
    # above, so this branch can never reach the write.
    return session.player_id


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
    logger.info("select called: choice_id=%s option=%s caller=%s", choice_id, option, session.player_id)

    async with db_mod.transaction() as conn:
        try:
            milestone = milestones_mod.get_milestone(choice_id)
        except ValueError as e:
            raise ToolError(f"Unknown choice: {choice_id}") from e

        # choice_id is external, so the guarantees resolve_milestone got from deriving
        # the milestone from player state are explicit checks here. These two are properties
        # of the MILESTONE, so they reject before any owner is picked.
        if milestone.kind != "specialization_fork":
            raise ToolError(f"Choice '{choice_id}' is not a selectable choice.")
        if milestone.patron_deferred:
            raise ToolError(
                "Your specialization is shaped by your patron — available when the Patron system arrives (Phase 8)."
            )

        # One batch FOR UPDATE fetch for the whole party: get_players_for_update's
        # ORDER BY player_id is this repo's deterministic lock order, which is what keeps
        # this from deadlocking against the OOC/combat batch fetches. Do not loop get_player.
        rows = await queries_mod.get_players_for_update(session.party.member_ids, conn=conn)
        target_id = _resolve_owner(session, rows, milestone, choice_id, option)

        if reason := _fork_block_reason(target_id, rows.get(target_id), milestone):
            raise ToolError(reason)

        valid_ids = {o.id for o in milestone.specialization_options}
        if option not in valid_ids:
            raise ToolError(f"Invalid option: {option}. Options: {sorted(valid_ids)}")

        await persistence_mod.set_player_specialization(target_id, option, conn=conn)

    # Clear the one-shot ticket only AFTER the commit. Clearing it on match would let a
    # transient DB error consume it, silently degrading the retry to the sole-claimant scan.
    if _matched_ticket(session, choice_id, option) is not None:
        session.pending_specialization_tap = None

    result = {
        "choice_id": choice_id,
        "chosen": option,
        "player_id": target_id,
        "narration_cue": milestone.narration_cue,
    }
    logger.info("select result: %s -> %s for %s", choice_id, option, target_id)
    return json.dumps(result)
