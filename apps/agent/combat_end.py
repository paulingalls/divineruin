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
import db_queries
import encounter_loot
import event_types as E
import pricing_queries
import resurrection
from combat_durability import _accrue_durability, _find_equipped
from combat_events import EventSink, emit_or_publish
from combat_support import _publish_sounds, _require_combat
from db_errors import db_tool
from region_types import REGION_CITY
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


def _conditions_changed(before: list[dict], after: list[dict]) -> bool:
    """True when two condition lists differ as multisets (order-independent). Guards the combat-end
    writeback from a redundant DB write when a reconciliation leaves the stored set unchanged."""

    def _key(conds: list[dict]) -> list[str]:
        return sorted(json.dumps(c, sort_keys=True) for c in conds)

    return _key(before) != _key(after)


async def _grant_enemy_loot(
    session: SessionData,
    p,
    rng: random.Random,
    *,
    mutations,
    content,
    conn,
    sink: EventSink,
    into: list[dict],
) -> int:
    """Roll + grant ONE defeated enemy's role-scaled loot, returning its currency contribution.

    Each rolled drop is added to the player's inventory, appended to ``into`` (for the narration
    summary), and buffered as an ITEM_ACQUIRED chip. Currency is the role-scaled silver for this
    enemy (0 for a Minion, D79). Untagged/legacy enemies (no category / loot_table_id) are inert —
    the empty-string defaults mean pre-story-002 content drops nothing rather than crashing."""
    currency = 0
    if p.category:
        tier = encounter_loot.tier_for_level(p.level)
        currency = encounter_loot.calculate_currency_drop(p.category, tier, p.role, rng)
    if p.loot_table_id:
        table = await content.get_loot_table(p.loot_table_id)
        if table is not None:
            for drop in encounter_loot.derive_role_loot(table, p.role, rng):
                await mutations.add_inventory_item(session.player_id, drop["item_id"], drop["quantity"], conn=conn)
                into.append(drop)
                await emit_or_publish(
                    sink,
                    session.room,
                    E.ITEM_ACQUIRED,
                    {"item_id": drop["item_id"], "quantity": drop["quantity"], "source": "combat_loot"},
                    event_bus=session.event_bus,
                )
    return currency


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
    loot_granted: list[dict] = []
    currency_silver = 0
    currency_gold: float = 0
    if outcome == "victory":
        enemy_dicts = []
        for p in cs.participants:
            if p.type != "enemy":
                continue
            enemy_dicts.append({"xp_value": p.xp_value})
            defeated_enemies.append(p.name)
            currency_silver += await _grant_enemy_loot(
                session, p, rng, mutations=mutations, content=content, conn=conn, sink=sink, into=loot_granted
            )
        xp_total = combat_resolution.calculate_combat_xp(enemy_dicts)

        # The enemy loot rolls accrue silver (the pricing baseline); convert to gold crowns at the
        # grant boundary — symmetric with how repair/crafting convert sp costs to gp via the same
        # silver_per_gold SSOT — so the wallet (players.data.gold, gold crowns) stays coherent.
        # Grant in one read-modify-write (FOR UPDATE so concurrent writers can't clobber the
        # balance), then buffer a single CURRENCY_GAINED chip for the whole haul. Inside this tx — a
        # rollback un-grants the coin and drops the unflushed event. Minions contribute 0 (D79); a
        # fight of only Minions emits nothing.
        if currency_silver > 0:
            silver_per_gold = (await pricing.get_economy_pricing())["silver_per_gold"]
            currency_gold = currency_silver / silver_per_gold
            player = await queries.get_player(session.player_id, conn=conn, for_update=True)
            prior_gold = (player or {}).get("gold", 0) or 0
            new_balance = prior_gold + currency_gold
            await mutations.update_player_gold(session.player_id, new_balance, conn=conn)
            await emit_or_publish(
                sink,
                session.room,
                E.CURRENCY_GAINED,
                {
                    "player_id": session.player_id,
                    "amount": currency_gold,
                    "currency": "gold",
                    "source": "combat",
                    "new_balance": new_balance,
                },
                event_bus=session.event_bus,
            )

    # Accrue per-encounter weapon durability (1 hit, 2 on a crit vs a heavily-armored target),
    # hollow-doubled. Reads each member's own weapon flags (set live during the loop); the flag
    # RESET is deferred to _end_combat_finish so a rolled-back phase keeps them set for the retry.
    # M18 story-003: EVERY player member who swung accrues their OWN equipped weapon's durability,
    # keyed on their own corruption_level for the hollow-zone doubling. The primary's result is
    # surfaced in the response (single-session handoff); non-primary accrual lands in the DB.
    weapon_durability: dict = {}
    for member in session.party.members:
        if not member.weapon_used:
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

    # Persist the player's cross-encounter conditions (M4.3, story-004): the persists_across_encounters
    # ones acquired this fight (Wounded/Exhausted/Hollowed) MERGE into players.data; phase-scoped ones
    # (Prone/Stunned/…) drop with the combat row. Combat only ACCRUES persistent conditions (rest
    # clears them, a later milestone), so we union with the existing store rather than overwrite — else
    # a fight would clobber a pre-combat Wounded. The read runs every combat end (a consumed buff
    # leaves no trace on the participant), but a change-gate skips the write when nothing moved. Same
    # tx as the row delete (atomic).
    player_part = next((p for p in cs.participants if p.type == "player"), None)
    if player_part is not None:
        acquired = [
            c for c in player_part.conditions if conditions.CONDITION_CATALOG[c["type"]].persists_across_encounters
        ]
        # Reconcile the player's OOC beneficial dice (Blessed/Inspired) back to players.data: they
        # load from the store onto the participant at combat-start (combat_init, M4.4 story-005) and
        # are consumed-on-use, so the participant's FINAL set is authoritative — a die spent in combat
        # must be dropped post-combat, and one granted mid-combat that survives must persist (concern
        # ab37d4fc61c6). Keyed on bonus_die (the only consumed-on-use character buffs); phase-scoped
        # combat conditions (Prone/Stunned) carry no bonus_die and correctly stay dropped. Broader
        # OOC-condition reconciliation (Poisoned/Charmed) waits on an in-combat applier (M13).
        surviving_buffs = [
            c for c in player_part.conditions if conditions.CONDITION_CATALOG[c["type"]].bonus_die is not None
        ]
        existing = await db_mutations_conditions.read_player_conditions(session.player_id, conn=conn)
        existing_non_buff = [c for c in existing if conditions.CONDITION_CATALOG[c["type"]].bonus_die is None]
        reconciled = _merge_persistent_conditions(existing_non_buff, acquired) + surviving_buffs
        if _conditions_changed(existing, reconciled):
            await db_mutations_conditions.save_player_conditions(session.player_id, reconciled, conn=conn)

    await mutations.delete_combat_state(cs.combat_id, conn=conn)

    # Death & resurrection (M4.4 story-003): on defeat the player died — auto-return them via Mortaen.
    # trigger_character_death records the death, applies the escalating cost, resolves the nearest
    # anchor, and revives the character (atomic with this combat-teardown tx). Hollowed-death is
    # story-007. combat_cleared = the area is no longer hostile (all enemies down even though the
    # player fell) — feeds the tier-1 cleared-battlefield anchor.
    death_context: dict | None = None
    if outcome == "defeat":
        enemies = [p for p in cs.participants if p.type == "enemy"]
        combat_cleared = bool(enemies) and all(p.is_fallen for p in enemies)
        # M14 story-006: a party wipe collects EVERY fallen player participant so ALL of them are
        # resurrected — each at their own 4-tier anchor (resurrect_party_on_defeat, story-005) —
        # not just the primary. For a player participant id == player_id (combat_init). A member
        # who survived the wipe is left alive (not collected); solo defeat collects exactly one.
        fallen = [
            (p.id, await queries.get_player(p.id, conn=conn))
            for p in cs.participants
            if p.type == "player" and p.is_fallen
        ]
        party = [(pid, row) for pid, row in fallen if row is not None]
        contexts = await resurrection.resurrect_party_on_defeat(
            [row for _, row in party], combat_cleared=combat_cleared, conn=conn
        )
        # The session's location follows the PRIMARY's anchor (single-session handoff, synced in
        # _end_combat_finish); non-primary members revive at their own anchors in the DB. Contexts
        # align with `party` by order (the engine iterates the list it was passed).
        death_context = next(
            (ctx for (pid, _), ctx in zip(party, contexts, strict=True) if pid == session.player_id), None
        )
        # Preserve the pre-M14 invariant that the session's PRIMARY is always resurrected on a
        # defeat, even when it isn't a plain fallen `player` participant. A Stage-2+ Hollowed rise
        # flips the primary's type to `temporary_hollowed` in place (combat_support, keeping
        # id == player_id), so the `player` collector above excludes it — yet the echo's destruction
        # IS the player's death. Resurrect it here (records hollow_killed, revives) inside this same
        # defeat tx. Skipped when the primary was already collected above.
        if death_context is None:
            primary_row = await queries.get_player(session.player_id, conn=conn)
            if primary_row is not None:
                death_context = await resurrection.resurrect_on_defeat(
                    primary_row, combat_cleared=combat_cleared, conn=conn
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
        "loot": loot_granted,
        "currency_gold": currency_gold,
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

    # On a defeat-resurrection the character was revived AT the anchor (resurrect_on_defeat wrote
    # players.data.location_id = anchor). Sync the live session so the post-death handoff agent is
    # built at the anchor, not the stale death site — AC3: the character returns at the anchor.
    death_context = end_data.get("death_context")
    if death_context is not None:
        session.location_id = death_context["anchor"]

    session.record_event(f"Combat ended: {outcome}")
    if defeated_enemies:
        session.record_companion_memory(f"Fought {', '.join(defeated_enemies)} at {cs.location_id}: {outcome}")

    loot = end_data.get("loot", [])
    currency_gold = end_data.get("currency_gold", 0)
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
