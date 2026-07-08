"""Combat teardown — end_combat tool."""

import json
import logging
import random

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import combat_resolution
import conditions
import db
import db_content_queries
import db_mutations
import db_mutations_conditions
import db_mutations_reputation
import db_queries
import encounter_loot
import event_types as E
import pricing_queries
import resurrection
from combat_durability import _accrue_durability, _find_equipped
from combat_events import EventSink, emit_or_publish
from combat_phase import is_terminally_down
from combat_support import _publish_sounds, _require_combat
from db_errors import db_tool
from region_types import REGION_CITY
from reputation import reputation_shift
from session_data import CombatState, SessionData
from tool_support import SOUND_COMBAT_DEFEAT, SOUND_COMBAT_FLED, SOUND_COMBAT_VICTORY

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


def _merge_persistent_conditions(existing: list[dict], acquired: list[dict]) -> list[dict]:
    """Union the player's stored cross-encounter conditions with those acquired this fight.

    Combat only ACCRUES (rest clears, a later milestone), so a fight never drops a pre-existing
    condition. On a type conflict, keep the instance with the higher accrual — more ``stacks``
    (Exhausted), or higher ``stage`` (Hollowed) — so a fight that deepens an already-persisted
    Exhausted isn't silently discarded. combat-START load (M4.4 story-005, combat_init) now carries
    the prior store onto the participant, so a combat-gained instance already folds in the prior
    accrual; max() stays the safe floor guarding against ever regressing to the lesser of the two."""

    def _severity(c: dict) -> int:
        return c.get("stacks", c.get("stage", 1))

    merged = {c["type"]: c for c in existing}
    for c in acquired:
        prior = merged.get(c["type"])
        if prior is None or _severity(c) > _severity(prior):
            merged[c["type"]] = c
    return list(merged.values())


async def _reconcile_member_conditions(player_part, *, conn) -> None:
    """Reconcile one player participant's cross-encounter conditions + beneficial dice into THEIR
    own players.data row (keyed on ``player_part.id`` == that member's player_id).

    The persists_across_encounters conditions acquired this fight (Wounded/Exhausted/Hollowed)
    MERGE into the member's store; phase-scoped ones (Prone/Stunned/…) drop with the combat row.
    Combat only ACCRUES persistent conditions (rest clears them, a later milestone), so we union
    with the existing store rather than overwrite — else a fight would clobber a pre-combat Wounded.

    Beneficial OOC dice (Blessed/Inspired) load from the store onto the participant at combat-start
    (combat_init, M4.4 story-005) and are consumed-on-use, so the participant's FINAL set is
    authoritative — a die spent in combat must be dropped post-combat, and one granted mid-combat
    that survives must persist (concern ab37d4fc61c6). Keyed on bonus_die (the only consumed-on-use
    character buffs); phase-scoped combat conditions carry no bonus_die and correctly stay dropped.
    Broader OOC-condition reconciliation (Poisoned/Charmed) waits on an in-combat applier (M13).

    The read runs every combat end (a consumed buff leaves no trace on the participant), but a
    change-gate skips the write when nothing moved."""
    acquired = [c for c in player_part.conditions if conditions.CONDITION_CATALOG[c["type"]].persists_across_encounters]
    surviving_buffs = [
        c for c in player_part.conditions if conditions.CONDITION_CATALOG[c["type"]].bonus_die is not None
    ]
    existing = await db_mutations_conditions.read_player_conditions(player_part.id, conn=conn)
    existing_non_buff = [c for c in existing if conditions.CONDITION_CATALOG[c["type"]].bonus_die is None]
    reconciled = _merge_persistent_conditions(existing_non_buff, acquired) + surviving_buffs
    if _conditions_changed(existing, reconciled):
        await db_mutations_conditions.save_player_conditions(player_part.id, reconciled, conn=conn)


def _conditions_changed(before: list[dict], after: list[dict]) -> bool:
    """True when two condition lists differ as multisets (order-independent). Guards the combat-end
    writeback from a redundant DB write when a reconciliation leaves the stored set unchanged."""

    def _key(conds: list[dict]) -> list[str]:
        return sorted(json.dumps(c, sort_keys=True) for c in conds)

    return _key(before) != _key(after)


async def _roll_enemy_loot(p, rng: random.Random, *, content) -> tuple[int, list[dict]]:
    """Roll ONE defeated enemy's role-scaled currency + loot drops WITHOUT granting them.

    Returns (silver, drops). Currency is rolled BEFORE loot, preserving the pre-M18 per-enemy RNG
    consumption order so a seeded run is byte-identical — the caller distributes the returned drops
    across the party (M18 story-003), which consumes no RNG. Currency is 0 for a Minion (D79).
    Untagged/legacy enemies (no category / loot_table_id) are inert — the empty-string defaults mean
    pre-story-002 content drops nothing rather than crashing."""
    currency = 0
    if p.category:
        tier = encounter_loot.tier_for_level(p.level)
        currency = encounter_loot.calculate_currency_drop(p.category, tier, p.role, rng)
    drops: list[dict] = []
    if p.loot_table_id:
        table = await content.get_loot_table(p.loot_table_id)
        if table is not None:
            drops = encounter_loot.derive_role_loot(table, p.role, rng)
    return currency, drops


@function_tool()
@db_tool
async def end_combat(
    context: RunContext[SessionData],
    outcome: str,
) -> str | tuple:
    """End the current combat. Outcome must be 'victory', 'defeat', or 'fled'.
    On victory, calculates XP from defeated enemies (call award_xp separately
    with the returned total). Clears all combat state."""
    return await _end_combat_impl(context, outcome)


async def _end_combat_impl(
    context: RunContext[SessionData],
    outcome: str,
    *,
    mutations=db_mutations,
    queries=db_queries,
    db_mod=db,
) -> str | tuple:
    """Standalone end_combat tool entry: validate, run the DB writes in their OWN transaction,
    flush the buffered events post-commit, then apply the in-memory teardown + agent handoff.

    The resolve_phase path does NOT call this — it shares its phase transaction by invoking
    _end_combat_db (in-tx) and _end_combat_finish (post-commit) directly (story-005, Seam 1)."""
    logger.info("end_combat called: outcome=%s", outcome)
    session: SessionData = context.userdata
    cs = _require_combat(session)

    if outcome.lower() not in _VALID_OUTCOMES:
        raise ToolError(f"Invalid outcome. Must be one of: {_VALID_OUTCOMES}")
    outcome = outcome.lower()

    sink = EventSink()
    async with db_mod.transaction() as conn:
        end_data = await _end_combat_db(
            session, cs, outcome, mutations=mutations, queries=queries, conn=conn, sink=sink
        )
    await sink.flush()
    return _end_combat_finish(session, cs, outcome, end_data)


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
    xp_total = 0
    defeated_enemies: list[str] = []
    primary_loot: list[dict] = []
    currency_silver = 0
    primary_currency_gold: float = 0
    if outcome == "victory":
        # ROLL pass (M18 story-003): iterate the defeated enemies in participant order, rolling each
        # one's currency + loot into a SHARED pool. Rolling is kept fully upstream of distribution so
        # the RNG consumption sequence is byte-identical to the pre-M18 per-enemy path.
        enemy_dicts = []
        loot_pool: list[dict] = []
        for p in cs.participants:
            if p.type != "enemy":
                continue
            enemy_dicts.append({"xp_value": p.xp_value})
            defeated_enemies.append(p.name)
            enemy_silver, enemy_drops = await _roll_enemy_loot(p, rng, content=content)
            currency_silver += enemy_silver
            loot_pool.extend(enemy_drops)
        xp_total = combat_resolution.calculate_combat_xp(enemy_dicts)

        # DISTRIBUTE pass — items: round-robin the shared pool across members in ascending player_id
        # seat order (customer decision f437f4475a40). Keyed on the player PARTICIPANTS who fought —
        # NOT session.party.member_ids — so a mid-combat room joiner (appended to the party by
        # participant_lifecycle but never a combatant) can't dilute or steal the haul. Each rolled
        # drop lands in ONE participant's inventory, so items stay scarce (no per-member duplication).
        # Distribution consumes no RNG. Solo = 1 participant, so every drop goes to the primary.
        seat_order = sorted(p.id for p in cs.participants if p.type == "player")
        # Defensive (concern ab4ced4c2110): _wrap guarantees >=1 standing player on an auto victory
        # (any_player_standing gate), but a MANUAL end_combat('victory') is ungated — a solo primary
        # that rose as an echo leaves seat_order empty. Skip distribution rather than divide by zero:
        # there is no player-life to receive the haul.
        for i, drop in enumerate(loot_pool if seat_order else []):
            recipient = seat_order[i % len(seat_order)]
            await mutations.add_inventory_item(recipient, drop["item_id"], drop["quantity"], conn=conn)
            if recipient == session.player_id:
                primary_loot.append(drop)
            await emit_or_publish(
                sink,
                session.room,
                E.ITEM_ACQUIRED,
                {
                    "item_id": drop["item_id"],
                    "quantity": drop["quantity"],
                    "source": "combat_loot",
                    "player_id": recipient,
                },
                event_bus=session.event_bus,
            )

        # DISTRIBUTE pass — currency: the party's enemy-silver haul gets a party multiplier (rewards
        # grouping without N x farming, customer decision f437f4475a40) then splits evenly; each
        # member's share converts to gold crowns at its own grant boundary (the silver_per_gold SSOT,
        # symmetric with repair/crafting). Each grant is a FOR UPDATE read-modify-write; the locks
        # are acquired in ASCENDING player_id order (deadlock-free SSOT 5da95d657255). One
        # CURRENCY_GAINED per member; end_data.primary_currency_gold is only the PRIMARY's own
        # share, not the party total — the DM's single-session handoff narrates the primary's own
        # haul (story-001), never the summed party gold. Inside this tx — a rollback un-grants the
        # coin and drops the unflushed events. Minions contribute 0 (D79). Solo N=1 -> multiplier
        # 1.0, one member: byte-identical.
        if currency_silver > 0 and seat_order:  # seat_order guard: see the loot-distribution note above
            silver_per_gold = (await pricing.get_economy_pricing())["silver_per_gold"]
            share_silver = currency_silver * encounter_loot.party_currency_multiplier(len(seat_order)) / len(seat_order)
            share_gold = share_silver / silver_per_gold  # loop-invariant — every participant's share is equal
            for pid in seat_order:
                player = await queries.get_player(pid, conn=conn, for_update=True)
                prior_gold = (player or {}).get("gold", 0) or 0
                new_balance = prior_gold + share_gold
                await mutations.update_player_gold(pid, new_balance, conn=conn)
                if pid == session.player_id:
                    primary_currency_gold = share_gold
                await emit_or_publish(
                    sink,
                    session.room,
                    E.CURRENCY_GAINED,
                    {
                        "player_id": pid,
                        "amount": share_gold,
                        "currency": "gold",
                        "source": "combat",
                        "new_balance": new_balance,
                    },
                    event_bus=session.event_bus,
                )

    # Accrue per-encounter weapon durability (1 hit, 2 on a crit vs a heavily-armored target),
    # hollow-doubled. Reads each member's own weapon flags (set live during the loop); the flag
    # RESET is deferred to _end_combat_finish so a rolled-back phase keeps them set for the retry.
    # M18 story-003: EVERY player PARTICIPANT who swung accrues their OWN equipped weapon's
    # durability, keyed on their own corruption_level for the hollow-zone doubling. Iterates the
    # combat participants (uniform with the loot/currency/conditions/resurrection recipient sets),
    # so a mid-combat joiner is excluded. The primary's result is surfaced in the response
    # (single-session handoff); non-primary accrual lands in the DB.
    weapon_durability: dict = {}
    for p in cs.participants:
        if p.type != "player":
            continue
        # Durability needs the PartyMember (weapon_used / corruption_level live there, unlike the
        # other paths that key on the participant id directly). Non-raising member() + skip: a
        # player participant is a party member in prod (combat_init), but skipping a stray one is a
        # fail-safe for a non-critical accrual rather than aborting the whole combat-end tx.
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
            is_hollow_zone=combat_resolution.is_hollow_zone(member.corruption_level),
            conn=conn,
            sink=sink,
        )
        if member.player_id == session.player_id:
            weapon_durability = member_durability

    # Persist cross-encounter conditions (M4.3, story-004; per-member M18 story-003): reconcile
    # EVERY player member's persistent conditions + surviving beneficial dice into their OWN
    # players.data row, not just the primary's — see _reconcile_member_conditions. Same tx as the
    # row delete (atomic). Solo = one player participant, byte-identical to the single-player path.
    for player_part in cs.participants:
        if player_part.type != "player":
            continue
        await _reconcile_member_conditions(player_part, conn=conn)

    await mutations.delete_combat_state(cs.combat_id, conn=conn)

    # Death, resurrection & stabilization (M4.4 story-003; M20 story-004/005; M15 story-003):
    # - TRULY DEAD lives — an is_terminally_down player (is_dead overkill OR 3 failed death saves) and
    #   ANY temporary_hollowed echo (a player who already died to rise as a Hollowed monster) — return
    #   via Mortaen on ANY outcome (death always returns the character). trigger_character_death records
    #   the death + escalating cost + nearest anchor + revive, and marks hollow_killed from an echo's
    #   persisted Hollowed condition. Scoping this to victory/defeat would STRAND a destroyed
    #   echo-primary on a fled/deescalated end — the character loss this saga exists to fix.
    # - On a DEFEAT (party wipe) the merely-FALLEN also die — no ally was left to drag them clear.
    # - On a FLED the merely-FALLEN also die — left behind when the party withdrew (M15 decision 498f0df12b14).
    # - On a VICTORY (and only victory) a merely-fallen (savable) ally is instead STABILIZED by the
    #   party (comes to at 1 HP; combat wrote their players.data HP to 0 per-hit, so this is a real
    #   write). deescalated also stabilizes (peaceful win, party holds the field).
    # combat_cleared (all enemies down) feeds the tier-1 cleared-battlefield anchor. Atomic with the tx.
    enemies = [p for p in cs.participants if p.type == "enemy"]
    combat_cleared = bool(enemies) and all(p.is_fallen for p in enemies)

    def _is_truly_dead(p) -> bool:
        # A player is truly dead when terminally down; any echo already died to rise. Shares
        # combat_phase.is_terminally_down so the wrap gate and this collector never disagree.
        return (p.type == "player" and is_terminally_down(p)) or p.type == "temporary_hollowed"

    def _fallen_savable(p) -> bool:
        # Dying but still savable: fell to 0 (is_fallen) and NOT terminally down. A member who died on
        # the grind or to overkill is _is_truly_dead, not savable.
        return p.type == "player" and p.is_fallen and not is_terminally_down(p)

    death_context: dict | None = None
    # Dead-life collector (any outcome). Picks up the primary echo (id == player_id, temporary_hollowed)
    # DIRECTLY — the Stage-2+ Hollowed rise flips the primary's type in place (combat_support), so no
    # special-case primary rescue is needed — AND any non-primary echo. On defeat and fled the merely-fallen
    # are added (party wipe/abandonment — nobody left to save them).
    dead_lives = [
        p for p in cs.participants if _is_truly_dead(p) or (outcome in ("defeat", "fled") and _fallen_savable(p))
    ]
    if dead_lives:
        # Fail-loud on a missing row (concern 2a646ecf0b4b): a dead player participant with no
        # players.data row is corruption — resurrection can't proceed and a silent skip would strand
        # the character. Raise inside the tx so it rolls back atomically. Each member resurrects at
        # its OWN 4-tier anchor (resurrect_party_on_defeat, M14 story-005/006).
        rows = [(p.id, await queries.get_player(p.id, conn=conn)) for p in dead_lives]
        missing = [pid for pid, row in rows if row is None]
        if missing:
            raise RuntimeError(f"Dead player participant(s) {missing} have no players.data row")
        contexts = await resurrection.resurrect_party_on_defeat(
            [row for _, row in rows], combat_cleared=combat_cleared, conn=conn
        )
        # The session follows the PRIMARY's anchor when the primary died (single-session handoff,
        # synced in _end_combat_finish); it stays put on a clean win where the primary survived.
        # Contexts align with `rows` by order (the engine iterates the list it was passed).
        death_context = next(
            (ctx for (pid, _), ctx in zip(rows, contexts, strict=True) if pid == session.player_id), None
        )

    # Standing-primary defeat (story-005 finding 4): a DM-declared defeat (end_combat(outcome='defeat'))
    # can leave the primary standing — not collected above. Preserve the invariant that a defeat always
    # returns the primary via Mortaen: resurrect it here when the collector didn't already.
    if outcome == "defeat" and death_context is None:
        primary_row = await queries.get_player(session.player_id, conn=conn)
        if primary_row is None:
            raise RuntimeError(f"Primary player {session.player_id!r} has no players.data row on defeat")
        death_context = await resurrection.resurrect_on_defeat(primary_row, combat_cleared=combat_cleared, conn=conn)

    # VICTORY and DEESCALATED: a merely-fallen (savable) ally is stabilized by the party (comes to at 1 HP);
    # normal regen/rest handles the gradual recovery (M15 decision 498f0df12b14: deescalated stabilizes like victory,
    # a peaceful win where the party holds the field). Fled and defeat do not stabilize.
    if outcome in ("victory", "deescalated"):
        for p in cs.participants:
            if _fallen_savable(p):
                # Fail-loud on a missing row (concern 2a646ecf0b4b), symmetric with the resurrection
                # collector: a downed player with no players.data row is corruption — a blind UPDATE
                # would silently no-op and strand the ally at 0 HP. Raise inside the tx (rollback).
                if await queries.get_player(p.id, conn=conn) is None:
                    raise RuntimeError(f"Fallen player {p.id!r} has no players.data row to stabilize")
                await mutations.update_player_hp(p.id, 1, conn=conn)

    # Faction reputation from the combat OUTCOME (story-002 inc 5/6): killing an encounter
    # faction's members (victory) lowers standing; talking them down (deescalated) raises it.
    # Keyed on cs.faction_id (set at combat_init from the stance gate); one aggregate shift per
    # fight, atomic with the end tx. `enemies` gates out a factionless/enemyless end. Homed here
    # rather than in combat_deescalation because the outcome-driven write belongs with the end
    # transaction (player_id + faction_id + conn all in scope), not mid-combat.
    if cs.faction_id and outcome in ("victory", "deescalated") and enemies:
        rep_event = "deescalated_faction" if outcome == "deescalated" else "killed_faction_member"
        await reputation_mutations.adjust_player_faction_reputation(
            session.player_id,
            cs.faction_id,
            reputation_shift(rep_event),
            f"combat_{outcome}",
            conn=conn,
        )

    await emit_or_publish(
        sink,
        session.room,
        E.COMBAT_ENDED,
        {"combat_id": cs.combat_id, "outcome": outcome, "xp_total": xp_total},
        event_bus=session.event_bus,
    )
    await _publish_sounds(session, [_STINGER_SOUND[outcome]], sink=sink)

    return {
        "xp_total": xp_total,
        "defeated_enemies": defeated_enemies,
        "weapon_durability": weapon_durability,
        "death_context": death_context,
        "primary_loot": primary_loot,
        "primary_currency_gold": primary_currency_gold,
    }


def _end_combat_finish(
    session: SessionData,
    cs: CombatState,
    outcome: str,
    end_data: dict,
) -> tuple:
    """The in-memory + handoff half of end_combat, run ONLY after the transaction commits. Resets
    the per-encounter flags, clears combat_state, records the event/memory, and returns the
    (gameplay_agent, json) handoff. No DB, no events — nothing here is reachable on a rollback."""
    xp_total = end_data["xp_total"]
    defeated_enemies = end_data["defeated_enemies"]

    # M18 story-003: reset EVERY member's per-encounter weapon flags (mirror combat_init).
    for member in session.party.members:
        member.weapon_used = False
        member.weapon_crit_vs_heavy = False
    session.draethar_inner_fire_used = False  # Inner Fire resets each encounter (M3.4)
    session.combat_state = None

    # When the primary died (any outcome — the dead-life collector or the standing-primary defeat
    # fallback set death_context), it was revived AT its anchor (players.data.location_id = anchor).
    # Sync the live session so the post-death handoff agent is built at the anchor, not the stale
    # death site — the character returns at the anchor. death_context is None on a clean survival.
    death_context = end_data.get("death_context")
    if death_context is not None:
        session.location_id = death_context["anchor"]

    session.record_event(f"Combat ended: {outcome}")
    if defeated_enemies:
        session.record_companion_memory(f"Fought {', '.join(defeated_enemies)} at {cs.location_id}: {outcome}")

    loot = end_data.get("primary_loot", [])
    currency_gold = end_data.get("primary_currency_gold", 0)
    response = {
        "outcome": outcome,
        "xp_total": xp_total,
        "defeated_enemies": defeated_enemies,
        "weapon_durability": end_data["weapon_durability"],
        "loot": loot,
        "currency_gold": currency_gold,
        "note": "Call award_xp with the xp_total to grant experience to the player." if xp_total > 0 else None,
    }
    logger.info(
        "end_combat result: %s, xp=%d, loot=%d item(s), currency=%.1fgp",
        outcome,
        xp_total,
        len(loot),
        currency_gold,
    )

    # Build gameplay agent with combat summary context for handoff
    from livekit.agents.llm import ChatContext

    from gameplay_agent import create_gameplay_agent

    summary_parts = [f"Combat resolved: {outcome}."]
    if xp_total > 0:
        summary_parts.append(f"XP earned: {xp_total}.")
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
    return create_gameplay_agent(
        agent_type, session.location_id, companion=session.companion, chat_ctx=summary_ctx
    ), json.dumps(response)
