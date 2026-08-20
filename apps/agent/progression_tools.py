"""Progression Resolves — the XP/milestone grant and the divine-favor grant.

Neither is an LLM-callable tool: M28 folded both onto deterministic Resolves (combat exit,
quest completion) so rewards are calculated by the rules engine and only NARRATED by the DM.
"""

import logging
from dataclasses import dataclass

import asyncpg

import db_activity_queries
import db_mutations
import db_mutations_divine
import event_types as E
import milestone_tools
import milestones
import rules_engine
from leveling import build_level_up_payload_for_archetype, get_level_up_rewards
from tool_support import con_mod_for_player

logger = logging.getLogger("divineruin.tools")


@dataclass(frozen=True)
class FavorGrant:
    """Outcome of the divine-favor Resolve — what the caller needs to narrate the grant.
    ``previous_level`` is kept alongside ``new_level`` because a clamp at the patron's max
    makes the delta differ from the amount asked for."""

    new_level: int
    previous_level: int
    patron_id: str


@dataclass(frozen=True)
class AwardXpResult:
    """Outcome of the shared XP/milestone Resolve. Both fields are read by every award path
    (update_quest, the combat-end Resolve) to build its tool response.

    Carries no L5-fork hand-off state: select re-derives the fork from the player's own
    committed level/class under FOR UPDATE, so the fork reaches the player as the
    SPECIALIZATION_CHOICE event plus the response's ``specialization_fork`` flag."""

    result: "rules_engine.LevelUpResult"
    milestone_grants: list[dict]


async def _award_xp_core(
    *,
    player_id: str,
    player: dict,
    amount: int,
    reason: str,
    conn: asyncpg.Connection,
    pending_events: list[tuple[str, dict]],
    mutations=db_mutations,
    milestones_mod=milestones,
) -> AwardXpResult:
    """The single XP/milestone Resolve all award paths route through (update_quest and the
    combat-end Resolve — there is no LLM-callable award verb). Runs inside the caller's
    transaction and operates
    on an already-FOR-UPDATE-locked ``player`` row, appending XP_AWARDED / LEVEL_UP /
    SPECIALIZATION_CHOICE to the caller-owned ``pending_events`` for publish-after-commit.

    ``player_id`` is the RECIPIENT — explicitly passed rather than read off the session, because
    combat-end grants party-wide XP to every player participant, not just the session primary
    (story-001). It is stamped into every emitted payload so each client can tell whose award it
    is; without it a teammate's XP would land on every client's own bar and a non-primary's L5
    fork would pop the choice UI everywhere.

    Applies L10/15/20 auto-grants deterministically (the single leveling chokepoint —
    not an LLM tool call, concern 3c02318dfa99) and surfaces the L5 specialization fork
    as a SPECIALIZATION_CHOICE cue for the select verb. Persists no choice — the L5 fork
    stays unresolved until select round-trips it.
    """
    current_xp = player.get("xp", 0)
    current_level = player.get("level", 1)

    result = rules_engine.check_level_up(current_xp, amount, current_level)
    await mutations.update_player_xp(player_id, result.new_xp, result.new_level, conn=conn)
    logger.info(
        "xp awarded: %s +%d XP → %d total, level %d (leveled_up=%s)",
        player_id,
        amount,
        result.new_xp,
        result.new_level,
        result.leveled_up,
    )

    pending_events.append(
        (
            E.XP_AWARDED,
            {
                "amount": amount,
                "reason": reason,
                "new_xp": result.new_xp,
                "new_level": result.new_level,
                "leveled_up": result.leveled_up,
                "attribute_points": result.attribute_points,
                "specialization_fork": result.specialization_fork,
                "player_id": player_id,
            },
        )
    )

    milestone_grants: list[dict] = []

    if result.leveled_up:
        rewards = get_level_up_rewards(current_level, result.new_level)
        con_mod = con_mod_for_player(player)
        payload = build_level_up_payload_for_archetype(current_level, rewards, player["class"], con_mod=con_mod)
        pending_events.append((E.LEVEL_UP, {**payload, "player_id": player_id}))

        # Iterate every level crossed so a multi-level jump still resolves each intervening
        # milestone: auto-grants apply in-transaction, the L5 fork surfaces as a pending choice.
        for lvl in range(current_level + 1, result.new_level + 1):
            milestone = milestones_mod.get_milestone_by_level(player["class"], lvl)
            if milestone is None:
                continue
            if milestone.kind == "auto_grant":
                await milestone_tools.apply_milestone_grant(milestone, player_id, conn=conn, flags_mod=mutations)
                # Surface the grant so the DM can voice it (audio-first, concern 4bf3efecdc8a);
                # includes narrative-only grants (flag=None).
                grant = milestone.grant
                milestone_grants.append(
                    {
                        "name": grant.name if grant else None,
                        "effect": grant.effect if grant else None,
                        "narration_cue": milestone.narration_cue,
                    }
                )
            # Pure predicate on the milestone — call the real module, NOT milestones_mod
            # (that seam only mocks the DB-backed get_milestone_by_level lookup).
            elif milestones.is_selectable_fork(milestone):
                # Present the L5 fork (presentation moved off resolve_milestone, concern
                # c515f47bf2c5). Patron-driven forks (Phase 8) never reach here at all —
                # is_selectable_fork is False for patron_deferred, so the elif does not fire and
                # no event is emitted for them. Persist nothing.
                options = [
                    {"id": o.id, "name": o.name, "description": o.description} for o in milestone.specialization_options
                ]
                pending_events.append(
                    (
                        E.SPECIALIZATION_CHOICE,
                        {"milestone_id": milestone.id, "options": options, "player_id": player_id},
                    )
                )

    return AwardXpResult(result=result, milestone_grants=milestone_grants)


async def _award_divine_favor_core(
    player_id: str,
    amount: int,
    reason: str,
    *,
    conn: asyncpg.Connection,
    pending_events: list[tuple[str, dict]],
    mutations=db_mutations_divine,
    activities=db_activity_queries,
) -> "FavorGrant | None":
    """The divine-favor Resolve: raise ``player_id``'s favor by ``amount``, clamped to their
    patron's max, inside the CALLER's transaction.

    Mirrors ``_award_xp_core``: no transaction of its own and no publish — the
    DIVINE_FAVOR_CHANGED cue is buffered into the caller-owned ``pending_events`` and released
    post-commit, so a rolled-back stage never announces favor the database does not hold. That
    is what lets a quest grant XP and favor atomically (M28).

    Returns ``None`` — rather than raising — when the player has no favor row or no patron, so a
    party-wide quest grant SKIPS an unaligned member instead of aborting the whole stage
    transaction. Every caller must handle that None; none of them treats it as an error.
    """
    favor = await activities.get_divine_favor(player_id, conn=conn)
    if favor is None or favor.get("patron", "none") == "none":
        return None

    current_level = favor.get("level", 0)
    max_level = favor.get("max", 100)
    new_level = min(current_level + amount, max_level)
    await mutations.update_divine_favor(player_id, new_level, conn=conn)

    pending_events.append(
        (
            E.DIVINE_FAVOR_CHANGED,
            {
                "new_level": new_level,
                "previous_level": current_level,
                "patron_id": favor["patron"],
                "last_whisper_level": favor.get("last_whisper_level", 0),
                # The REAL gain, never the amount ASKED for: a grant that hits the patron's max
                # moves the bar less than the reward declared, and the mobile handler pops its
                # "+N favor" toast off this field alone. Publishing the request made a player at
                # max favor watch a "+5" celebrate a bar that never moved — while update_quest's
                # own rewards_applied entry reported the honest 0 to the DM.
                "amount": new_level - current_level,
                "reason": reason,
                # `max` is the favor bar's DENOMINATOR: the mobile handler reads it and falls back
                # to 100, so dropping it (as this payload used to) fabricated the bar's scale for
                # any patron whose cap is not 100. `player_id` is the RECIPIENT — quest favor is
                # party-wide, so without it a teammate's grant moves every client's bar.
                "max": max_level,
                "player_id": player_id,
            },
        )
    )
    logger.info(
        "divine favor awarded: %s +%d → %d (patron=%s)",
        player_id,
        amount,
        new_level,
        favor["patron"],
    )
    return FavorGrant(new_level=new_level, previous_level=current_level, patron_id=favor["patron"])
