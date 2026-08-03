"""Combat-end reward passes — ROLL the encounter's spoils, then DISTRIBUTE them across the party.

Extracted from combat_end.py (decision dcc9c1cc1221): the victory branch had outgrown the file's
500-line ceiling, and the passes share enough semantics that they belong together rather than
inlined among the death/condition/ward teardown.

Every pass runs INSIDE the caller's combat-end transaction (the phase tx or end_combat's own) and
buffers its player-facing events into the caller's ``RewardChannel``, so a rolled-back phase
un-grants the reward AND drops the unflushed event. Helpers take explicit args — no session or
module-global reach-through — so the caller owns the transaction and the event lifetime.

Two invariants the passes share; neither may drift:

  - ROLL is fully upstream of DISTRIBUTE. Distribution consumes no RNG, so the roll sequence stays
    byte-identical to the pre-M18 per-enemy path and a seeded run reproduces exactly.
  - Every distribution walks ``seat_order`` — the ascending player_id of the player PARTICIPANTS who
    fought. It is both the round-robin order and the FOR UPDATE lock order (deadlock-free SSOT
    5da95d657255). Keying on participants rather than session.party.member_ids keeps a mid-combat
    room joiner from diluting or stealing the haul. An EMPTY seat_order means no player-life is left
    to receive anything (a manual end_combat('victory') declared by a risen echo, concern
    ab4ced4c2110), so each pass skips rather than dividing by zero.
"""

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import combat_resolution
import encounter_loot
import event_types as E
from combat_events import EventSink, emit_or_publish

if TYPE_CHECKING:
    from livekit import rtc

    from event_bus import EventBus


@dataclass(frozen=True)
class RewardChannel:
    """Where a reward pass sends its player-facing events: buffered into ``sink`` for the life of
    the transaction, replayed to ``room`` / ``event_bus`` once it commits."""

    sink: EventSink
    room: "rtc.Room | None"
    event_bus: "EventBus | None" = None

    async def emit(self, event_type: str, payload: dict) -> None:
        await emit_or_publish(self.sink, self.room, event_type, payload, event_bus=self.event_bus)


@dataclass
class EncounterSpoils:
    """Everything the defeated enemies yielded, rolled but not yet granted to anyone."""

    xp_total: int = 0
    currency_silver: int = 0
    loot_pool: list[dict] = field(default_factory=list)
    defeated_enemies: list[str] = field(default_factory=list)


def seat_order_for(participants) -> list[str]:
    """The ascending player_id of the player PARTICIPANTS who fought — the round-robin seat order
    AND the FOR UPDATE lock order every distribution pass acquires its rows in."""
    return sorted(p.id for p in participants if p.type == "player")


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


async def roll_encounter_spoils(participants, rng: random.Random, *, content) -> EncounterSpoils:
    """ROLL pass (M18 story-003): walk the defeated enemies in participant order, rolling each one's
    currency + loot into a SHARED pool and summing the encounter XP.

    Rolling is kept fully upstream of distribution so the RNG consumption sequence is byte-identical
    to the pre-M18 per-enemy path. Each enemy's xp_value is ALREADY role-scaled at combat init, so
    calculate_combat_xp only sums — it must not re-apply the role multiplier."""
    spoils = EncounterSpoils()
    enemy_dicts = []
    for p in participants:
        if p.type != "enemy":
            continue
        enemy_dicts.append({"xp_value": p.xp_value})
        spoils.defeated_enemies.append(p.name)
        enemy_silver, enemy_drops = await _roll_enemy_loot(p, rng, content=content)
        spoils.currency_silver += enemy_silver
        spoils.loot_pool.extend(enemy_drops)
    spoils.xp_total = combat_resolution.calculate_combat_xp(enemy_dicts)
    return spoils


async def distribute_loot(
    loot_pool: list[dict],
    seat_order: list[str],
    *,
    primary_id: str,
    mutations,
    conn,
    channel: RewardChannel,
) -> list[dict]:
    """DISTRIBUTE pass — items: round-robin the shared pool across the seats (customer decision
    f437f4475a40). Each rolled drop lands in exactly ONE participant's inventory, so items stay
    scarce (no per-member duplication). Solo = 1 seat, so every drop goes to the primary.

    Returns the PRIMARY's own drops — what the single-session handoff narrates — not the party haul.
    """
    primary_loot: list[dict] = []
    for i, drop in enumerate(loot_pool if seat_order else []):
        recipient = seat_order[i % len(seat_order)]
        await mutations.add_inventory_item(recipient, drop["item_id"], drop["quantity"], conn=conn)
        if recipient == primary_id:
            primary_loot.append(drop)
        await channel.emit(
            E.ITEM_ACQUIRED,
            {
                "item_id": drop["item_id"],
                "quantity": drop["quantity"],
                "source": "combat_loot",
                "player_id": recipient,
            },
        )
    return primary_loot


async def distribute_currency(
    currency_silver: int,
    seat_order: list[str],
    *,
    primary_id: str,
    mutations,
    queries,
    pricing,
    conn,
    channel: RewardChannel,
) -> float:
    """DISTRIBUTE pass — currency: the party's enemy-silver haul gets a party multiplier (rewards
    grouping without N x farming, customer decision f437f4475a40) then splits evenly; each member's
    share converts to gold crowns at its own grant boundary (the silver_per_gold SSOT, symmetric
    with repair/crafting). Each grant is a FOR UPDATE read-modify-write, locked in seat order. One
    CURRENCY_GAINED per member. Minions contribute 0 (D79). Solo N=1 -> multiplier 1.0, one member:
    byte-identical to the pre-party path.

    Returns the PRIMARY's own share, never the summed party gold — the DM's single-session handoff
    narrates the primary's own haul.
    """
    if currency_silver <= 0 or not seat_order:
        return 0
    silver_per_gold = (await pricing.get_economy_pricing())["silver_per_gold"]
    share_silver = currency_silver * encounter_loot.party_currency_multiplier(len(seat_order)) / len(seat_order)
    share_gold = share_silver / silver_per_gold  # loop-invariant — every participant's share is equal
    primary_currency_gold: float = 0
    for pid in seat_order:
        player = await queries.get_player(pid, conn=conn, for_update=True)
        prior_gold = (player or {}).get("gold", 0) or 0
        new_balance = prior_gold + share_gold
        await mutations.update_player_gold(pid, new_balance, conn=conn)
        if pid == primary_id:
            primary_currency_gold = share_gold
        await channel.emit(
            E.CURRENCY_GAINED,
            {
                "player_id": pid,
                "amount": share_gold,
                "currency": "gold",
                "source": "combat",
                "new_balance": new_balance,
            },
        )
    return primary_currency_gold
