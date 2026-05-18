# Phase 9 Audit — Economy / Player-to-Player Trade (Sprint-006 story-007)

Sprint-006 / Milestone 6 (story-007). Read-only audit of `docs/game_mechanics/economy/game_mechanics_p2p_trade.md` (226 lines, 1 H2 with 9 major subsections covering design intent, inherited constraints, direct trade, remote trade, auction house, fees/taxes, anti-fraud guardrails, Phase 1 infrastructure checklist, and 7 design decisions) against shipped code in `apps/agent/`, `apps/server/src/`, `packages/shared/src/entities/`, `content/`, and `scripts/migrations/`. Status legend (matches sprint-004 audit/README.md L49-58): **BUILT** = code present and matches spec; **DESIGNED** = spec well-defined and partial code exists, but the symbol/feature is missing, renamed, or diverges; **NOT_SHIPPED** = no implementation found. Sibling sprint-006 audit files: `phase-9-economy.md` (story-001), `phase-9-supply-demand.md` (story-002), `phase-9-faction-pricing.md` (story-003), `phase-9-restock.md` (story-004), `phase-9-gold-sink.md` (story-005), `phase-9-inflation.md` (story-006).

Verified-at: 82c4f593b53191dfa7fbfd7654f79e1d2715ae16

## Summary

| Section | BUILT | DESIGNED | NOT_SHIPPED |
| --- | --- | --- | --- |
| Design Intent + Inherited Constraints (5 constraints) | 0 | 0 | 5 |
| Direct Trade — Same Location (5 design questions, all open) | 0 | 0 | 5 |
| Remote Trade (3 transport mechanisms + 4 design questions) | 0 | 0 | 7 |
| Auction House / Marketplace (5 design questions, all open) | 0 | 0 | 5 |
| Trade Fees and Taxes (4 fee structures + tax avoidance) | 0 | 0 | 5 |
| Anti-Fraud & Anti-Exploit Guardrails (6 mechanisms) | 0 | 1 | 5 |
| Phase 1 Supporting Infrastructure (4 must-haves) | 0 | 2 | 2 |
| Design Decisions 122-128 (7 decisions) | 0 | 0 | 7 |

**Headline finding:** P2P trade is **entirely NOT_SHIPPED** — and that is precisely what the spec prescribes. The spec opens (L3) with "**Phase scope:** This system is **Phase 2+ deferred**. Phase 1 is single-player, so player-to-player trade does not exist yet." The audit's job is **not** to find missing trade mechanics — those are intentionally absent — but to verify the **4 Phase 1 supporting-infrastructure items** the spec L178-194 says should ship now to avoid Phase 2 retrofitting: item provenance, atomic transaction primitives, settlement-aware inventory APIs, and transaction logging schema. Of those 4: (1) **item provenance — DESIGNED↔aspirational** — `apps/agent/inventory_tools.py:24-33` ships `add_to_inventory(item_id, quantity, source: str)` with a free-text source field ("looted from goblin", "purchased from merchant"). The provenance *seam* exists; the *structured queryable trail* (spec calls for "A weapon's history (created by player X via crafting, sold to merchant Y, looted by player Z) is queryable") does not — `source` is a single per-acquisition string, not a typed history list, and `Item` schema has no `created_by` / `previous_owner` / `provenance_trail` field; (2) **atomic transaction primitives — DESIGNED↔aspirational** — `apps/agent/db_mutations.py:42` accepts a `conn` parameter that *could* support transaction-scoping for atomicity, but `add_to_inventory` / `remove_from_inventory` are independent operations and **no multi-item-multi-currency atomic transfer primitive exists**. The Postgres connection plumbing is BUILT; the atomic-trade API is NOT_SHIPPED; (3) **settlement-aware inventory APIs — NOT_SHIPPED** — `apps/agent/db_mutations.py:42` `update_player_location(player_id, location_id)` ships and `players.data->location_id` is queryable, but **`Location` has no `settlement_id` or `size` field** (per story-004 audit honesty note 4), so "these two players are in the same settlement" is not directly queryable — only `location_id` equality (granular: `accord_market_square` vs the broader Accord settlement). Settlement membership requires either a typed `Location.settlement_id` field or a tag→settlement mapping convention. NOT_SHIPPED at the settlement-grouping layer; (4) **transaction logging schema — NOT_SHIPPED** — cross-ref story-005 + story-006: neither `sink_event_log` nor `faucet_event_log` ships. P2P transfer event type (logged at 0 sp from sink perspective in Phase 1 per spec L186) inherits NOT_SHIPPED. Beyond the 4 infrastructure items: **zero shipping for multiplayer** (`grep -rnE 'multiplayer|multi_player' apps/agent/ apps/server/src/` → 0 matches), zero auction-house surface, zero fee/tax mechanism, zero of 6 anti-fraud guardrails (atomic transactions partially DESIGNED via conn plumbing), zero of 7 design decisions 122-128 encoded.

**Honesty note 1 — `add_to_inventory.source` is provenance-shaped but not provenance-structured.** Spec L171 envisions querying a weapon's history: "created by player X via crafting, sold to merchant Y, looted by player Z." Shipped `add_to_inventory(item_id, quantity, source: str)` records a **single free-text string** per acquisition (`source` examples in the docstring: `"looted from goblin"`, `"purchased from merchant"`, `"quest reward"`). The data shape mismatches: spec needs an **ordered list of typed events** with structured actors/timestamps; shipped is a **single mutable string** on the inventory row. The seam is real (every acquisition records *something*); the queryable provenance trail is not. Capstone-routed: when P2P trade activates, schema needs `Item` to grow a typed `provenance: ProvenanceEvent[]` field OR a sibling `item_history` table keyed on a per-item UUID (current item ids are content-id strings, not per-copy UUIDs — multiple players can hold a `healing_potion` and there's no per-instance handle).

**Honesty note 2 — `db_mutations.py:42` `conn` parameter is atomic-ready but no atomic primitive exists.** The shipped `update_player_location(player_id, location_id, *, conn=None)` and parallel mutations accept an optional `asyncpg.Connection | Pool` — calling code can wrap multiple mutations in a single transaction by passing the same `conn` through. This is **infrastructure to support atomicity**, not an atomic-trade primitive itself. The spec's `atomic_p2p_transfer(from_player, to_player, items, gold)` does not exist as a function. **DESIGNED↔aspirational** — the substrate (asyncpg transaction plumbing) is BUILT; the trade-specific atomic API is NOT_SHIPPED.

**Honesty note 3 — Player→location ships, player→settlement does not.** `update_player_location` (db_mutations.py:42) writes `players.data->location_id` and `Location` ships in shared schema. But `Location.id` is **granular** (e.g., `accord_market_square`, `accord_guild_hall`, `accord_dockside` are all separate locations). The spec's "same settlement" predicate (L184) needs a **settlement-grouping concept** that doesn't exist: no `Location.settlement_id` field, no `Settlement` entity type. Story-004 audit already flagged this as `Location.size` + `Location.personality` gap for the inventory-restock spec; P2P trade compounds the same gap. **NOT_SHIPPED** for settlement membership; cross-ref story-004 punch-list item 3.

**Honesty note 4 — Phase 1 has no item-instance identity.** `content/items.json` ships item *templates* (`healing_potion` content_id) with `value_base`, `value_modifiers`, etc. `player_inventory` rows key on `(player_id, item_id, data JSONB)` — that's `(player, template, json)`, not `(player, item-instance-id)`. Two players holding the same content template share an item-id; there's **no per-instance identity** to anchor a per-item provenance trail to. Spec example "the blade with Ashmark seal — where did you get it?" requires per-instance UUIDs. Schema change required at the player_inventory layer (`item_instance_id UUID` column) OR a per-copy UUID surfaced via `data.instance_id`. Capstone-routed.

**Honesty note 5 — Sixth sprint-006 audit story to find the false decision-extraction pattern.** Spec L212 claims decisions 122-128 are "Extracted to `game_mechanics_decisions.md` for canonical reference." **They are not** — canonical decisions log terminates at Decision 72 (Economy Reconciliation). Same pattern as stories 002 (96-104), 003 (82-86), 004 (87-95), 005 (105-113), 006 (114-121). Combined implied undocumented decisions: 73-81 + 82-86 + 87-95 + 96-104 + 105-113 + 114-121 + 122-128 = **56 decisions (9+5+9+9+9+8+7)** spec-local but not in canonical log. **Sixth consecutive sprint-006 audit** finding this pattern — capstone bulk-fix is critical-overdue.

## Coverage matrix

Spec sections under §Player-to-Player Trade mapped to existing `09_economy.md` milestone items. **NEW** = spec content with no corresponding M9.x bullet. All rows are NEW since 09_economy.md predates this subsystem doc; entire surface is also spec-marked Phase 2+ deferred.

| Spec section (file:line) | Milestone item | Notes |
| --- | --- | --- |
| Design Intent + Inherited Constraints (game_mechanics_p2p_trade.md:11-49) | NEW [Phase 2+] | 5 inherited constraints (voice-first, faction territory, supply/demand, gold sinks, settlement size). All cross-ref prior subsystem audits. |
| Direct Trade — Same Location (game_mechanics_p2p_trade.md:53-71) | NEW [Phase 2+] | 5 open design questions (witness, fee structure, trust mechanics, consent, combat restrictions). Spec L70 "likely direction": free or near-free, voice-driven, DM-facilitated, atomic exchange. |
| Remote Trade (game_mechanics_p2p_trade.md:75-98) | NEW [Phase 2+] | 4 questions + 3 transport mechanisms (faction couriers, NPC merchant network, player-driven transport). Spec L94 "likely direction": gate behind faction services. |
| Auction House / Marketplace (game_mechanics_p2p_trade.md:102-122) | NEW [Phase 2+] | 5 questions, spec L118 leans toward "deliberately constrained" per-faction marketplaces. Decision 127 explicitly defers final call to Phase 2 design time. |
| Trade Fees and Taxes (game_mechanics_p2p_trade.md:126-142) | NEW [Phase 2+] | 4 fee structures + tax-avoidance gameplay (smuggling/frontier markets). Cross-ref story-005 sink_event_log NOT_SHIPPED; fees would inherit. |
| Anti-Fraud and Anti-Exploit Guardrails (game_mechanics_p2p_trade.md:146-172) | NEW [Phase 2+] | 6 mechanisms: atomic transactions, transaction logs, velocity limits, value asymmetry detection, new-account restrictions, item provenance. Phase 1 supports a subset (atomic primitives + provenance + transaction log). |
| Phase 1 Supporting Infrastructure — 4 must-haves (game_mechanics_p2p_trade.md:176-194) | NEW (Phase 1) | (1) Item provenance, (2) atomic transaction primitives, (3) settlement-aware inventory APIs, (4) transaction logging schema. **Capstone must record which of these ship as Phase 1 deliverables.** |
| Phase 2 Design Process (game_mechanics_p2p_trade.md:198-206) | NEW [Phase 2+] | Process guidance: start with constraints, resolve direct→remote→auction order, RMT/griefing stress-test, voice-first validate, integrate with existing systems. |
| Design Decisions 122-128 (game_mechanics_p2p_trade.md:210-226) | NEW | 7 decisions. Spec L212 false-extraction claim — sixth audit story to find this pattern (honesty note 5). |

## Audit Status (Sprint-006) — Design Intent + Inherited Constraints

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Voice-first communication: no menu-driven trade interfaces; DM as witness/notary | Cross-ref voice-first architecture (per CLAUDE.md golden rule 1 + system_context). No menu-driven trade UI ships; positive form (voice-driven trade flow) not built. | None | NOT_SHIPPED |
| Faction territory affects all trade | Cross-ref story-003: faction reputation pipeline NOT_SHIPPED end-to-end. P2P faction-tax/witness mechanics inherit. | None | NOT_SHIPPED |
| Supply/demand affects item value | Cross-ref story-002: supply/demand engine NOT_SHIPPED. P2P market-context anchor inherits. | None | NOT_SHIPPED |
| Gold sinks must be preserved | Cross-ref story-005: sink event logging NOT_SHIPPED. P2P trade-specific sinks inherit. | None | NOT_SHIPPED |
| Settlement size affects trade capacity | Cross-ref story-004 + honesty note 3: `Location` schema lacks `settlement_id`/`size`; player→settlement query path NOT_SHIPPED. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Direct Trade — Same Location

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Two-player same-location item/gold exchange — witness, fee structure, trust mechanics, consent semantics, combat restrictions (5 open design questions) | Phase 2+ deferred per spec. No multiplayer infrastructure ships. `grep -rnE 'multiplayer|multi_player|trade_with_player' apps/agent/ apps/server/src/` → 0 matches. | None | NOT_SHIPPED |
| Atomic exchange via DM-facilitated transaction (both parties confirm; transfer happens simultaneously) | Cross-ref Phase 1 Infrastructure row #2 (atomic transaction primitives) — substrate exists (conn plumbing), primitive does not. See honesty note 2. | None | NOT_SHIPPED |
| Free or near-free direct trade in non-faction territory (Decision 128) | Spec L226 records direction; no fee surface to vary. | None | NOT_SHIPPED |
| Explicit consent always (coercion stays narrative) | No consent flow. | None | NOT_SHIPPED |
| Combat phase restrictions (no trade during combat per spec L67 lean) | No phase-aware trade gating. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Remote Trade

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Existence question: should remote trade exist at all (vs. geography-meaningful proximity restriction) | Phase 2+ design decision deferred. | None | NOT_SHIPPED |
| Faction-courier transport mechanism (distance-scaled fees, caravan ambush risk) | Cross-ref story-003 faction services: NOT_SHIPPED. | None | NOT_SHIPPED |
| Merchant Guild cross-city delivery service (Trusted+ reputation reduces fees) | Cross-ref story-003: Merchant Guild faction not in `content/factions.json` (4 shipped: accord_guild + 3 others). NOT_SHIPPED. | None | NOT_SHIPPED |
| Player-driven transport (third-party player physically carries) — Phase 3 territory | Phase 3 deferred. | None | NOT_SHIPPED |
| Time delay (1-3 in-game days delivery), "in transit" state, estimated arrival | No in-transit item state. | None | NOT_SHIPPED |
| Loss/theft risk during transit + insurance system | No transit-loss mechanic. | None | NOT_SHIPPED |
| Anti-RMT protection (transaction caps, velocity limits, behavioral analysis) | Cross-ref Anti-Fraud row below. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Auction House / Marketplace

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Existence question (auction houses fundamentally reshape economies — voice-first compatibility, RMT scaling) | Decision 127 explicitly defers to Phase 2 design time. | None | NOT_SHIPPED |
| Voice-first auction: faction-agent verbal listings + verbal queries ("how much are healing potions in Tideholm?") | No voice-driven auction flow. | None | NOT_SHIPPED |
| Listing fees + commission (spec floats 5% listing + 10% commission) | No fee structure. | None | NOT_SHIPPED |
| Geographic scope (global vs per-city vs per-faction marketplaces) | Open question — capstone-routed. | None | NOT_SHIPPED |
| Rare item handling (auctionable vs direct-trade-only) | Open question — capstone-routed. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Trade Fees and Taxes

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Faction transaction tax (1-5%) — faction reputation reduces/waives | Cross-ref story-003: faction tier modifiers NOT_SHIPPED. | None | NOT_SHIPPED |
| Transport fees (per-distance courier costs) | No courier mechanic. | None | NOT_SHIPPED |
| Auction fees (listing + commission) | No auction. | None | NOT_SHIPPED |
| Witness fees (authorized witness for high-value direct trades; trades without witnesses legally challengeable in faction courts) | No notary/witness mechanic. | None | NOT_SHIPPED |
| Tax avoidance gameplay (smuggling, frontier markets) — legitimate gameplay vector | Phase 2+ emergent gameplay; depends on tax system existing first. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Anti-Fraud and Anti-Exploit Guardrails

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Atomic transactions: both parties get what they agreed to, or neither does (no partial transfers) | `apps/agent/db_mutations.py:42` `update_player_location(*, conn=None)` and parallel mutations accept asyncpg conn — substrate for transaction-scoping is BUILT. But the **atomic-trade primitive itself** (`atomic_p2p_transfer(from, to, items, gold)`) does not exist. See honesty note 2. | None | DESIGNED |
| Transaction logs (who, what, when, where, how much) with full provenance | Cross-ref story-005 + story-006: sink_event_log + faucet_event_log NOT_SHIPPED. P2P log inherits. | None | NOT_SHIPPED |
| Velocity limits (flag unusual trade-frequency patterns) | No rate-limiting code. | None | NOT_SHIPPED |
| Value asymmetry detection (5000-sp-sword-for-1-cp flagged for review) | No asymmetry detector. | None | NOT_SHIPPED |
| New-account restrictions (must reach level 5 or complete tutorial before trading) | No account-tier gating. | None | NOT_SHIPPED |
| Item provenance: queryable history per item | Cross-ref Phase 1 Infrastructure row #1 below + honesty note 1+4: `source` string exists per-acquisition, structured trail + per-instance identity NOT_SHIPPED. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Phase 1 Supporting Infrastructure (4 must-haves)

This is the **load-bearing section for this story** — spec L178-194 explicitly lists these as Phase 1 ship-now-to-avoid-retrofit items. Findings here are the audit's primary contribution.

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| 1. Item provenance tracking infrastructure (every item created/transferred logs its history) | `apps/agent/inventory_tools.py:24-33` ships `add_to_inventory(item_id, quantity, source: str)` with free-text `source` parameter — examples: `"looted from goblin"`, `"purchased from merchant"`, `"quest reward"`. **The seam to record provenance exists on the acquisition path**, but: (a) `source` is a single string per acquisition, not a structured/typed list; (b) `Item` schema (per story-001) has no `created_by` / `previous_owner` / `provenance_trail` field; (c) `player_inventory` keys on `(player_id, item_id, data JSONB)` where `item_id` is a content template (`healing_potion`), not per-instance UUID (honesty note 4) — provenance has no per-copy anchor. The seam is BUILT, the structured trail is NOT_SHIPPED. | None | DESIGNED |
| 2. Atomic transaction primitives (`add_to_inventory`/`remove_from_inventory` API shape should accommodate Phase 2 trade execution) | `apps/agent/db_mutations.py:42` `update_player_location(player_id, location_id, *, conn=None)` and sibling mutations accept asyncpg `Connection \| Pool` — calling code can wrap multiple mutations in a single transaction by passing the same `conn` through. This is **infrastructure to support atomicity** (BUILT). The atomic-trade primitive itself (`atomic_p2p_transfer(from, to, items, gold)` — moves items from sender, gold from receiver, in one Postgres transaction) does not exist as a function. See honesty note 2. | None | DESIGNED |
| 3. Settlement-aware inventory APIs (queryable: "are these two players in the same settlement?") | `apps/agent/db_mutations.py:42` ships `update_player_location` writing `players.data->location_id`. **Player→location query path BUILT**. But `Location.id` is granular (e.g., `accord_market_square` ≠ `accord_guild_hall` even though both are in Accord). No `Location.settlement_id` field, no `Settlement` entity type. **Player→settlement query path NOT_SHIPPED**. See honesty note 3. Cross-ref story-004 punch-list item 3. | None | NOT_SHIPPED |
| 4. Transaction logging schema (event types for player-to-player transfers — logged at 0 sp from sink perspective in Phase 1) | Cross-ref story-005 (sink_event_log NOT_SHIPPED) + story-006 (faucet_event_log NOT_SHIPPED). The P2P transfer event type would slot into the unified event_log surface — but that surface doesn't ship. NOT_SHIPPED. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Design Decisions 122-128

Spec L210-226 records 7 architectural decisions. Spec L212 claims "Extracted to `game_mechanics_decisions.md` for canonical reference" — **sixth audit story to find the same false-extraction pattern** (stories 002 found 96-104, 003 found 82-86, 004 found 87-95, 005 found 105-113, 006 found 114-121, this story finds 122-128). Decisions log terminates at Decision 72 (Economy Reconciliation). Combined implied undocumented decisions across sprint-006: **56 entries**. None encoded.

| Decision | Item (verbatim) | Status |
| --- | --- | --- |
| 122 | P2P trade is Phase 2+ deferred; Phase 1 implements supporting infrastructure only | NOT_SHIPPED (rows above quantify the partial DESIGNED state of Phase 1 infrastructure) |
| 123 | P2P trade must obey the same world rules as merchant trade | NOT_SHIPPED (parallel-economy bypass is a Phase 2+ enforcement concern; nothing to enforce yet) |
| 124 | P2P trade is voice-first; no menu-driven trade interfaces | Structurally honored by absence (no trade UI ships); positive form unverifiable until Phase 2 |
| 125 | Item provenance must be tracked from Phase 1 | DESIGNED↔aspirational — seam exists, structured trail NOT_SHIPPED (see row above) |
| 126 | Atomic transaction primitives are required infrastructure | DESIGNED↔aspirational — asyncpg conn plumbing exists, atomic-trade primitive NOT_SHIPPED |
| 127 | Auction house design is genuinely uncertain and worth real debate at Phase 2 planning | NOT_SHIPPED by design (deferred decision) |
| 128 | Direct trade in non-faction territory carries no fee | NOT_SHIPPED (no fee mechanism, no territory-typed taxonomy) |

## Deliverables status (per 09_economy.md M9.x §Deliverables, cross-doc)

This audit story is doc-only and does not own M9.x deliverables directly — the capstone (story-008) will. Mapping for the capstone:

- 4 Phase 1 must-have infrastructure items:
  - Item provenance — **DESIGNED↔aspirational** (seam exists, trail + per-instance UUID NOT_SHIPPED)
  - Atomic transaction primitives — **DESIGNED↔aspirational** (conn plumbing exists, atomic-trade primitive NOT_SHIPPED)
  - Settlement-aware APIs — **NOT_SHIPPED** (`Location.settlement_id` missing)
  - Transaction logging schema — **NOT_SHIPPED** (cross-ref stories 005/006)
- 6 anti-fraud guardrails: 1 DESIGNED (atomic), 5 NOT_SHIPPED
- All Phase 2+ trade mechanics (direct/remote/auction/fees/anti-fraud rest): **NOT_SHIPPED** by design
- 7 design decisions 122-128: **NOT_SHIPPED** as encoded constants

## Out-of-scope findings (Sprint-spec-cleanup punch list)

Routed to `audit/README.md` Sprint-006 section by capstone (story-008) per wisdom `d0715b09a1df`:

1. **Provenance trail needs per-instance item identity.** Current `player_inventory` keys on `(player_id, item_id)` where `item_id` is a content template. Spec L171 example "a weapon's history (created by player X, sold to merchant Y, looted by player Z)" requires per-copy UUIDs. Capstone should plan a `data.instance_id` UUID convention or a new `item_instance_id` column.
2. **Promote `add_to_inventory.source: str` to typed provenance.** Replace single free-text string with a structured `provenance: ProvenanceEvent[]` field (or sibling `item_history` table). Each event captures `{actor_type: 'player'|'merchant'|'creature', actor_id, action: 'crafted'|'looted'|'purchased'|..., timestamp, context?}`. Migration converts existing source strings into a 1-event seed history.
3. **Add `atomic_p2p_transfer(from_player, to_player, items, gold)` primitive.** Wraps current `add_to_inventory` / `remove_from_inventory` / gold debit/credit in a single asyncpg transaction. The `conn` parameter plumbing (BUILT) is the substrate; this is the API on top.
4. **Add `Location.settlement_id` field (cross-ref story-004 punch-list item 3).** Enables "are these two players in the same settlement?" query in O(1). Without it, P2P proximity logic has to traverse the location-tag-or-prefix approximation.
5. **Resolve `Settlement` as an entity vs `Location.settlement_id` field.** Two design choices: (a) tag locations with a settlement_id string (lightweight, no new entity), (b) introduce `Settlement` as a typed entity with size/personality/population (heavier, supports story-004 spec gap directly). Capstone should pick one — current state is "neither shipped, both implied across story-004 + story-007".
6. **Add P2P transfer event type to the unified event log (faucet/sink/transfer).** Cross-ref stories 005+006: faucet_event_log + sink_event_log both NOT_SHIPPED. When they land, include `transfer_event` with `from_player_id`, `to_player_id`, `items[]`, `amount_sp`, `location_id`, `settlement_id`, `faction_id` columns. Spec L186: "logged as 0 sp from sink perspective in Phase 1; activated for real values in Phase 2+."
7. **Decisions 122-128 are NOT extracted to `game_mechanics_decisions.md`.** Sixth audit story finding the same false-extraction pattern. Combined undocumented decision count across sprint-006 audits: **56 entries** (73-81 + 82-86 + 87-95 + 96-104 + 105-113 + 114-121 + 122-128). This is now a systemic gap — capstone bulk extraction is the **single highest-priority spec-cleanup item** identified by sprint-006.
8. **Decision 127 (auction-house deferral) is explicit.** Capstone should preserve the deferred state rather than picking a direction — the spec's intent is for Phase 2 design to make this call with full context.

## Verification

Verified-at: 82c4f593b53191dfa7fbfd7654f79e1d2715ae16

Grep commands used (all from repo root; 0 matches unless noted):

```bash
# Item provenance
grep -rnE 'item_provenance|item_history|provenance_trail|created_by|previous_owner' apps/ packages/ scripts/migrations/

# Atomic transaction primitives (for P2P)
grep -rnE 'atomic_transaction|atomic_transfer|atomic_p2p|p2p_transfer|player_transfer' apps/ packages/

# Settlement / settlement_id
grep -rnE 'settlement_id|current_settlement|Settlement\b' apps/ packages/ content/

# Transaction logging / trade logs
grep -rnE 'transaction_log|trade_log|transfer_event' apps/ packages/ scripts/migrations/

# Multiplayer surface
grep -rnE 'multiplayer|multi_player|trade_with_player|guild_party|raid_group' apps/agent/ apps/server/src/

# Confirmed-present substrate (returned matches):
grep -nE 'def add_to_inventory|def remove_from_inventory' apps/agent/inventory_tools.py    # L24, L36, L105, L114
grep -nE 'source: str' apps/agent/inventory_tools.py                                        # L28, L40 (free-text provenance string)
grep -nE 'def update_player_location' apps/agent/db_mutations.py                            # L42
grep -nE 'conn: asyncpg' apps/agent/db_mutations.py                                         # 22 sites — atomic-substrate plumbing

# Item instance identity probe (per-copy UUID absence)
grep -nE "PRIMARY KEY \(player_id, item_id\)" scripts/migrations/001_initial_schema.sql      # L118 (composite key on template id, not instance)

# Decisions log terminates at Decision 72 (6th audit to verify)
grep -nE '^## ' docs/game_mechanics/game_mechanics_decisions.md | tail -3
# "## Economy Reconciliation (Decision 72)" is the last
```
