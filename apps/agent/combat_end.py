"""Combat teardown — end_combat tool."""

import json
import logging
import random

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import combat_resolution
import combat_rewards
import db
import db_content_queries
import db_mutations
import db_mutations_reputation
import db_mutations_veil_ward
import db_queries
import event_types as E
import pricing_queries
from combat_conditions_persist import reconcile_member_conditions
from combat_durability import _accrue_durability, _find_equipped
from combat_end_lives import settle_lives
from combat_events import EventSink, emit_or_publish, isolated_publish
from combat_support import _publish_sounds, _require_combat
from db_errors import db_tool
from region_types import REGION_CITY
from reputation import reputation_shift
from session_data import CombatState, SessionData
from tool_support import SOUND_COMBAT_DEFEAT, SOUND_COMBAT_FLED, SOUND_COMBAT_VICTORY
from veil_ward import WardScope
from veil_ward_events import veil_ward_payload

logger = logging.getLogger("divineruin.tools")

_VALID_OUTCOMES = ("victory", "defeat", "fled")
_STINGER_SOUND = {
    "victory": SOUND_COMBAT_VICTORY,
    "defeat": SOUND_COMBAT_DEFEAT,
    "fled": SOUND_COMBAT_FLED,
    # A Diplomat talked the enemies down (M4.6a story-004): a non-violent end, closest to a
    # withdrawal — reuse the fled stinger. No loot/resurrection (those gate on victory/defeat).
    "deescalated": SOUND_COMBAT_FLED,
}


@function_tool()
@db_tool
async def end_combat(
    context: RunContext[SessionData],
    outcome: str,
) -> str | tuple:
    """End the current combat. Outcome must be 'victory', 'defeat', or 'fled'.
    On victory, XP and loot from the defeated enemies are granted automatically —
    narrate the returned xp_granted, any milestone_grants, and the specialization
    fork if one opened. Clears all combat state."""
    return await _end_combat_impl(context, outcome)


async def _end_combat_impl(context: RunContext[SessionData], outcome: str, **di) -> str | tuple:
    """Serialise the end against the other path that can end this fight (resolve_phase's WRAP).

    `combat_state` is the only re-entry guard and cannot be released until the transaction commits
    (an earlier release would let a retried end pay the party twice), so two overlapping ends would
    both pass `_require_combat` and both run grant_victory_rewards — the encounter paid out twice,
    level-ups and milestone grants included. Under the lock the waiter re-reads `combat_state` after
    the holder cleared it and raises "Not in combat". See SessionData.combat_state_lock.
    """
    session: SessionData = context.userdata
    async with session.combat_state_lock:
        return await _end_combat_locked(context, outcome, **di)


async def _end_combat_locked(
    context: RunContext[SessionData],
    outcome: str,
    *,
    mutations=db_mutations,
    queries=db_queries,
    db_mod=db,
) -> str | tuple:
    """Standalone end_combat tool entry: validate, run the DB writes in their OWN transaction, apply
    the in-memory teardown + agent handoff the instant it commits, then flush the buffered events.

    The resolve_phase path does NOT call this — it shares its phase transaction by invoking
    _end_combat_db (in-tx) and _end_combat_finish (post-commit) directly (story-005, Seam 1)."""
    logger.info("end_combat called: outcome=%s", outcome)
    session: SessionData = context.userdata
    cs = _require_combat(session)

    # A round is TWO commits (M29, story-016), and combat_state_lock cannot cover the GAP between
    # them: after the ally commit the enemy actions sit persisted as pending, and ending here would
    # pay the party and delete the combat row with an enemy's turn still queued. Refuse loud and
    # name the next action rather than force-end into a silent data loss (constraint 4). The cost,
    # on the record: end_combat("fled") is unavailable for one beat.
    if cs.held_actions:
        raise ToolError(
            f"{len(cs.held_actions)} enemy action(s) are still held pending at the narration beat — "
            "call resolve_phase to close the beat, then end combat."
        )

    if outcome.lower() not in _VALID_OUTCOMES:
        raise ToolError(f"Invalid outcome. Must be one of: {_VALID_OUTCOMES}")
    outcome = outcome.lower()

    sink = EventSink()
    async with db_mod.transaction() as conn:
        end_data = await _end_combat_db(
            session, cs, outcome, mutations=mutations, queries=queries, conn=conn, sink=sink
        )
    # The COMMIT is what makes the party's XP/loot/coin durable, so the guard against a second end
    # (session.combat_state, which _require_combat reads) must be released with it — story-010.
    # Anything fallible left between the commit and the teardown is a window where the rewards are
    # banked but a retried end_combat would pay the whole party AGAIN. On rollback the exception
    # propagates out of the `async with` and skips this, so combat_state survives and the end stays
    # retryable. _end_combat_finish does no awaits, no DB and no events, so hoisting it above the
    # flush costs nothing; its one fallible step (building the handoff agent) is isolated and
    # fallback-guarded in _build_handoff_agent so it cannot strand the session either.
    result = _end_combat_finish(session, cs, outcome, end_data)
    with isolated_publish("end_combat"):
        await sink.flush()
    return result


async def _end_combat_db(
    session: SessionData,
    cs: CombatState,
    outcome: str,
    *,
    mutations,
    queries,
    conn,
    sink: EventSink,
    content=db_content_queries,
    pricing=pricing_queries,
    reputation_mutations=db_mutations_reputation,
    ward_mutations_mod=db_mutations_veil_ward,
    rng: random.Random | None = None,
) -> dict:
    """The DB-mutating + event-emitting half of end_combat, run INSIDE a transaction (the phase
    tx when invoked from resolve_phase, or end_combat's own). Accrues weapon durability, grants
    role-scaled loot + currency on victory, deletes the combat row, and buffers COMBAT_ENDED + the
    stinger into ``sink`` (released post-commit). Touches NO in-memory session state — that is
    _end_combat_finish's job, deferred to post-commit so a rollback leaves the session pristine.
    Returns the data finish needs to build the response.

    ``content`` resolves loot tables (db_content_queries by default; injectable for tests);
    ``rng`` seeds the loot/currency rolls (a fresh system Random by default)."""
    rng = rng or random.Random()
    actor_id = session.acting_player_id
    primary_id = session.primary_player_id
    # Loot, coin and XP live in combat_rewards (decision dcc9c1cc1221). All of it runs in THIS
    # transaction and buffers into ``sink``, so a rolled-back phase un-grants every reward and drops
    # the unflushed events. XP is a Resolve now (M28 story-001), not a "call an award tool with
    # this total" note to the LLM — transactional with the fight that earned it, so it can't be
    # forgotten, doubled, or invented, and every player participant is paid, not just the primary.
    rewards = combat_rewards.VictoryRewards()
    if outcome == "victory":
        rewards = await combat_rewards.grant_victory_rewards(
            cs.participants,
            rng,
            recipient_id=actor_id,
            summary_player_id=primary_id,
            reason=f"Victory at {cs.location_id}",
            mutations=mutations,
            queries=queries,
            pricing=pricing,
            content=content,
            conn=conn,
            channel=combat_rewards.RewardChannel(sink, session.room, session.event_bus),
        )

    # Accrue per-encounter weapon durability (1 hit, 2 on a crit vs a heavily-armored target),
    # hollow-doubled. Reads each member's own weapon flags (set live during the loop); the flag
    # RESET is deferred to _end_combat_finish so a rolled-back phase keeps them set for the retry.
    # M18 story-003: EVERY player PARTICIPANT who swung accrues their OWN equipped weapon's
    # durability, keyed on their own corruption_level for the hollow-zone doubling. Iterates the
    # combat participants (uniform with the loot/currency/conditions/resurrection recipient sets),
    # so a mid-combat joiner is excluded. The speaker's result is surfaced in the response
    # (single-session handoff); other members' accrual lands in the DB.
    weapon_durability: dict = {}
    for p in cs.participants:
        if p.type != "player":
            continue
        # Durability needs the PartyMember (weapon_used lives there, unlike the other paths that key
        # on the participant id directly). Non-raising member() + skip: a player participant is a
        # party member in prod (combat_init), but skipping a stray one is a fail-safe for a
        # non-critical accrual rather than aborting the whole combat-end tx.
        member = session.party.member(p.id)
        if member is None or not member.weapon_used:
            continue
        inventory = await queries.get_player_inventory(member.player_id, conn=conn)
        weapon = _find_equipped(inventory, "weapon")
        if weapon is None:
            continue
        member_durability = await _accrue_durability(
            session,
            member.player_id,
            weapon,
            combat_resolution.weapon_hits_for_encounter(member.weapon_crit_vs_heavy),
            # The zone is the PARTY's, not the member's. corruption_level is location-derived and
            # never persisted; a joiner snapshots it once and movement only ever refreshes the
            # primary's. Reading the member's copy spared a joiner's weapon the doubled hollow-zone
            # wear their armor (which reads this same party value) correctly took.
            is_hollow_zone=combat_resolution.is_hollow_zone(session.corruption_level),
            conn=conn,
            sink=sink,
        )
        if member.player_id == actor_id:
            weapon_durability = member_durability

    # Persist cross-encounter conditions (M4.3, story-004; per-member M18 story-003): reconcile
    # EVERY player member's persistent conditions + surviving beneficial dice into their OWN
    # players.data row, not just the primary's — see reconcile_member_conditions. Same tx as the
    # row delete (atomic). Solo = one player participant, byte-identical to the single-player path.
    for player_part in cs.participants:
        if player_part.type != "player":
            continue
        await reconcile_member_conditions(player_part, conn=conn)

    await mutations.delete_combat_state(cs.combat_id, conn=conn)

    # Deleting the combat row IS the encounter ward's expiry (scope_model.md §2), so the HUD must be
    # told — but with the RESOLVED state, not "the ward you had is gone" (§3). Only an encounter ward's
    # death can change wardedness here; an unwarded fight's end changes nothing and says nothing.
    #
    # Read the LOCATION scope explicitly rather than routing through resolve_scope_ward: this runs
    # INSIDE the tx, and session.combat_state is not cleared until _end_combat_finish (post-commit),
    # so the resolver would still see the ward we just deleted. Once the encounter scope is gone the only
    # scope that can still cover the party is the location — a Sacred site, or a pre-fight row. Same
    # shape as the dismiss path in veil_ward_tools.
    ward_light_synced = False
    resolved_location_ward: dict | None = None
    if cs.veil_ward is not None:
        location_scope = WardScope.location(session.location_id)
        location_ward = await ward_mutations_mod.read_active_ward(location_scope, conn=conn)
        # The session mirror is synced post-commit in _end_combat_finish (like combat_state), so a
        # rolled-back phase leaves session.location_ward pristine — this half touches no session
        # state. The EMITTED event may still be lost if the post-commit flush fails; the mirror is
        # the mirror, the committed delete is the truth (combat_events.POST_COMMIT_PUBLISH_FAILED).
        resolved_location_ward = location_ward
        ward_light_synced = True
        await sink.emit(
            session.room,
            E.VEIL_WARD_CHANGED,
            veil_ward_payload(location_ward, location_scope if location_ward is not None else None),
            event_bus=session.event_bus,
        )

    enemies = [p for p in cs.participants if p.type == "enemy"]
    combat_cleared = bool(enemies) and all(p.is_fallen for p in enemies)
    death_context = await settle_lives(cs, outcome, primary_id, combat_cleared, queries, mutations, conn)

    # Faction reputation from the combat OUTCOME (story-002 inc 5/6): killing an encounter
    # faction's members (victory) lowers standing; talking them down (deescalated) raises it.
    # Keyed on cs.faction_id (set at combat_init from the stance gate); one aggregate shift per
    # fight, atomic with the end tx. The KILL penalty only applies when the battlefield is
    # actually cleared (combat_cleared = all enemies fallen) — a DM-declared 'victory' with
    # faction enemies still standing must NOT dock killed_faction_member for kills that didn't
    # happen. De-escalation is a talk-down, so it gates on non-empty enemies, not on kills.
    # Homed here rather than in combat_deescalation because the outcome-driven write belongs with
    # the end transaction (player_id + faction_id + conn all in scope), not mid-combat.
    faction_outcome_applies = combat_cleared if outcome == "victory" else (outcome == "deescalated" and bool(enemies))
    if cs.faction_id and faction_outcome_applies:
        rep_event = "deescalated_faction" if outcome == "deescalated" else "killed_faction_member"
        for member_id in sorted(session.party.member_ids):
            await reputation_mutations.adjust_player_faction_reputation(
                member_id,
                cs.faction_id,
                reputation_shift(rep_event),
                f"combat_{outcome}",
                conn=conn,
            )

    await emit_or_publish(
        sink,
        session.room,
        E.COMBAT_ENDED,
        {"combat_id": cs.combat_id, "outcome": outcome, "xp_total": rewards.spoils.xp_total},
        event_bus=session.event_bus,
    )
    await _publish_sounds(session, [_STINGER_SOUND[outcome]], sink=sink)

    return {
        "xp_total": rewards.spoils.xp_total,
        "xp_granted": rewards.xp.xp_granted,
        "summary_xp_granted": rewards.xp.summary_xp_granted,
        "xp_by_player": rewards.xp.granted_by_player,
        "milestone_grants": rewards.xp.milestone_grants,
        "specialization_fork": rewards.xp.specialization_fork,
        "defeated_enemies": rewards.spoils.defeated_enemies,
        "weapon_durability": weapon_durability,
        "death_context": death_context,
        "primary_loot": rewards.primary_loot,
        "item_recipients": rewards.item_recipients,
        "primary_currency_gold": rewards.primary_currency_gold,
        "ward_light_synced": ward_light_synced,
        "resolved_location_ward": resolved_location_ward,
    }


def _end_combat_finish(
    session: SessionData,
    cs: CombatState,
    outcome: str,
    end_data: dict,
) -> tuple:
    """The in-memory + handoff half of end_combat, run ONLY after the transaction commits. Resets
    the per-encounter flags, clears combat_state, records the event/memory, and returns the
    (gameplay_agent, json) handoff. No DB, no events — nothing here is reachable on a rollback.

    Not await-free by accident: every state mutation below is synchronous, and the one step that
    can genuinely raise — constructing the handoff agent — is isolated in _build_handoff_agent,
    which never lets a failure escape past the already-cleared combat_state."""
    xp_total = end_data["xp_total"]
    xp_granted = end_data["xp_granted"]
    defeated_enemies = end_data["defeated_enemies"]

    # M18 story-003: reset EVERY member's per-encounter weapon flags (mirror combat_init).
    for member in session.party.members:
        member.weapon_used = False
        member.weapon_crit_vs_heavy = False
        member.draethar_inner_fire_used = False
    session.combat_state = None

    # Post-commit sync of the location-ward mirror: only when the dying encounter ward changed
    # wardedness (the in-tx half resolved and emitted the covering location scope). Deferred here so
    # a rolled-back phase leaves session.location_ward untouched, matching the combat_state contract.
    if end_data.get("ward_light_synced"):
        session.location_ward = end_data["resolved_location_ward"]

    # When the primary died (any outcome — the dead-life collector or the standing-primary defeat
    # fallback set death_context), it was revived AT its anchor (players.data.location_id = anchor).
    # Sync the live session so the post-death handoff agent is built at the anchor, not the stale
    # death site — the character returns at the anchor. death_context is None on a clean survival.
    death_context = end_data.get("death_context")
    if death_context is not None:
        session.location_id = death_context["anchor"]

    session.record_event(f"Combat ended: {outcome}")
    # Folding award_xp onto the combat-exit Resolve (story-003) took its `record_event` with it,
    # so the DM's warm `[Recent: ...]` layer and the session-summary transcript fallback lost every
    # XP grant (debt fb14dced76f6). The speaker's own share, matching session_xp_earned below.
    if xp_granted > 0:
        session.record_event(f"Awarded {xp_granted} XP: combat at {cs.location_id}")
    if defeated_enemies:
        session.record_companion_memory(f"Fought {', '.join(defeated_enemies)} at {cs.location_id}: {outcome}")

    session.session_xp_earned += end_data["summary_xp_granted"]
    for pid, share in end_data["xp_by_player"].items():
        session.record_player_metric(pid, "xp_earned", share)
    for pid, name in end_data["item_recipients"]:
        session.record_player_metric(pid, "items_found", name)
        if pid == session.primary_player_id and name not in session.session_items_found:
            session.session_items_found.append(name)

    loot = end_data.get("primary_loot", [])
    currency_gold = end_data.get("primary_currency_gold", 0)
    response = {
        "outcome": outcome,
        "xp_total": xp_total,
        # The XP is already GRANTED (M28 story-001) — there is no follow-up award call to cue.
        # The DM narrates the level-up beats from this response, not from the event bus:
        # milestone_grants voices each L10/15/20 auto-grant, and specialization_fork cues the L5
        # choice the generic select verb resolves.
        "xp_granted": xp_granted,
        "milestone_grants": end_data["milestone_grants"],
        "specialization_fork": end_data["specialization_fork"],
        "defeated_enemies": defeated_enemies,
        "weapon_durability": end_data["weapon_durability"],
        "loot": loot,
        "currency_gold": currency_gold,
    }
    logger.info(
        "end_combat result: %s, xp=%d granted (encounter total %d), loot=%d item(s), currency=%.1fgp",
        outcome,
        xp_granted,
        xp_total,
        len(loot),
        currency_gold,
    )

    # Build gameplay agent with combat summary context for handoff
    from livekit.agents.llm import ChatContext

    summary_parts = [f"Combat resolved: {outcome}."]
    # The player's OWN share, not the encounter total — in a party the two differ, and narrating
    # the total would promise XP nobody received.
    if xp_granted > 0:
        summary_parts.append(f"XP earned: {xp_granted}.")
    if defeated_enemies:
        summary_parts.append(f"Defeated: {', '.join(defeated_enemies)}.")
    # Surface the haul so the DM can voice it (loot is a headline beat). Quantities collapse per
    # item id so a "2x Cured Hide" reads naturally rather than as two lines.
    if loot:
        qty_by_item: dict[str, int] = {}
        for drop in loot:
            qty_by_item[drop["item_id"]] = qty_by_item.get(drop["item_id"], 0) + drop["quantity"]
        summary_parts.append("Loot: " + ", ".join(f"{q}x {item}" for item, q in qty_by_item.items()) + ".")
    if currency_gold > 0:
        summary_parts.append(f"Currency: {currency_gold:.1f} gold.")

    summary_ctx = ChatContext()
    summary_ctx.add_message(role="system", content=" ".join(summary_parts))

    agent_type = session.pre_combat_agent_type or REGION_CITY
    session.pre_combat_agent_type = None
    return _build_handoff_agent(session, agent_type, summary_ctx), json.dumps(response)


def _build_handoff_agent(session: SessionData, agent_type: str, summary_ctx):
    """Construct the exploration agent the party returns to — the ONE fallible step in an
    otherwise in-memory teardown, isolated here with a fallback (concern 9e2685165f07).

    It runs AFTER ``combat_state`` has been cleared (which it must, or a retried end pays the
    party twice), and the agent it returns is the only exit from CombatAgent. So a raise out of
    here would strand the session in combat forever with its rewards already banked — the exact
    outcome the post-commit ordering exists to prevent. Agent construction reaches real work
    (system-prompt assembly over the companion profile, toolset composition, the summary
    ChatContext), so "it is just a constructor" is not a guarantee.

    The fallback drops every optional input and rebuilds at the default region: losing the combat
    summary and the companion's voice for one turn is survivable, being unable to leave combat is
    not. If even that raises, the process is broken and the exception is the honest answer.
    """
    from gameplay_agent import create_gameplay_agent

    try:
        return create_gameplay_agent(agent_type, session.location_id, companion=session.companion, chat_ctx=summary_ctx)
    except Exception:
        logger.exception(
            "Combat handoff agent (%s) failed to build; falling back to a bare exploration agent so the "
            "party can leave combat. The combat summary and companion context are lost for this handoff.",
            agent_type,
        )
        return create_gameplay_agent(REGION_CITY, session.location_id)
