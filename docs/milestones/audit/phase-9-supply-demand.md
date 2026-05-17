# Phase 9 Audit — Economy / Supply & Demand Engine (Sprint-006 story-002)

Sprint-006 / Milestone 6 (story-002). Read-only audit of `docs/game_mechanics/economy/supply_demand_engine.md` (597 lines, 1 H2 with 9 major subsections) against shipped code in `apps/agent/`, `apps/server/src/`, `packages/shared/src/entities/`, `content/`, and `scripts/migrations/`. Status legend (matches sprint-004 audit/README.md L49-58): **BUILT** = code present and matches spec; **DESIGNED** = spec well-defined and partial code exists, but the symbol/feature is missing, renamed, or diverges; **NOT_SHIPPED** = no implementation found. Sibling sprint-006 audit files: `phase-9-economy.md` (story-001, base spec), `phase-9-faction-pricing.md` (story-003, planned), `phase-9-restock.md` (story-004, planned).

Verified-at: 434df7da37adaf5ea67bb2aa63d6d01cdfdd6338

## Summary

| Section | BUILT | DESIGNED | NOT_SHIPPED |
| --- | --- | --- | --- |
| Magnitude & Stacking (0.5×–3.0× clamp + multiplicative stacking) | 0 | 0 | 2 |
| Item Tag Taxonomy (11 economic tags + tag inheritance) | 0 | 1 | 1 |
| Event Lifecycle (3 phases: Active / Recovery / Resolved) | 0 | 0 | 3 |
| Standard Event Catalog (15 events: 6 demand + 5 supply incl. embargo + 4 surplus) | 0 | 1 | 15 |
| Worked Example (multi-event crisis pricing) | 0 | 0 | 1 |
| Implementation Reference (event-instance schema + `compute_item_price` + simulation tick + Redis price cache) | 0 | 2 | 4 |
| DM Narration Patterns | 0 | 0 | 4 |
| Design Decisions 96-104 (9 design decisions) | 0 | 0 | 9 |

**Headline finding:** The supply & demand engine is **entirely NOT_SHIPPED at the mechanical layer**. What ships is the **event-logging substrate**: a `world_events_log` table (`scripts/migrations/001_initial_schema.sql:184-189`) with indexes (`scripts/migrations/002_add_indexes.sql:9-10`), an `events` table for event content (`001:48-54`), 8 records in `content/events.json` (4 `scripted`, 3 `world_event`, 1 `god_whisper` — none typed `economic`), `apps/agent/db_mutations.py:228` writing to world_events_log, and `apps/agent/world_news.py:39-83` reading recent events to generate **post-event narrative news summaries** for the catch-up feed. The substrate exists. The supply/demand engine *on top of it* — event templates with `active_multipliers`, three-phase lifecycle (`phase: active|recovery|resolved`), economic-tag-based item matching, multiplicative stacking with 0.5×–3.0× clamp, `compute_item_price`, `economy_simulation_tick`, recovery decay math, Redis 60s price cache — is **0% shipped**. Zero of 15 spec event types exist as content records, zero of 9 design decisions are encoded, zero of the four DM narration patterns are scaffolded as templates.

**Honesty note 1 — Event substrate vs supply/demand engine.** The `world_events_log` table + `world_news.py` shipping is **real infrastructure**, but it serves the narrative news-feed use case (player catches up on what happened while offline), not the spec's price-impact use case. The spec needs event records with `event_template`, `phase`, `phase_started_at`, `active_duration_seconds`, `recovery_duration_seconds`, `affected_regions`, `active_multipliers` (`supply_demand_engine.md:399-421`); the shipped table has `id`, `event_id`, `timestamp`, `data JSONB`. The JSONB blob could theoretically carry the spec schema, but no code reads it that way — `world_news.py:52-55` extracts only `type` and `description` from the JSONB blob. The substrate is generalizable, but the spec schema is unshipped on top of it.

**Honesty note 2 — Item economic tags are not a separate field.** `packages/shared/src/entities/item.ts:17` ships `tags: string[]` as a single narrative+economic tag array. 3 items carry the `healing` tag (`healing_potion`, `antidote_basic`, `restoration_salve`) which **happens to match the spec's `healing` economic tag** (`supply_demand_engine.md:63`). One of 11 spec economic tags (`anti-hollow`, `divine`, `weapons`, `armor`, `food`, `travel`, `luxury`, `crafting_material`, `imported`, `military`, `healing`) appears organically. There is no `economic_tags: string[]` field separate from narrative tags, no tag-inheritance computation at item generation time (spec L77-79), and no event-modifier lookup keyed by tag. The tag taxonomy is **DESIGNED↔aspirational** — schema accommodates string tags, content uses `healing` correctly, but the formal economic taxonomy is unshipped.

**Honesty note 3 — `content/events.json` events are scripted, not economic.** All 8 entries carry `type: "scripted"` (4), `type: "world_event"` (3), or `type: "god_whisper"` (1) — e.g. `market_disruption`, `hollow_patrol_encounter`, `ruins_discovery_ripple` — and reference quest/location triggers, not `type: "economic"` with `active_multipliers`. The `market_disruption` event id is misleading — it's a scripted narrative beat (rider crashes through market gates), not an economic event template per the spec. Zero `type: "economic"` events ship.

**Honesty note 4 — `compute_item_price` and `economy_simulation_tick` are completely absent.** `grep -rnE 'def.*compute_item_price|def.*economy_simulation|def.*apply_event_modifier|def.*compute_recovery' apps/agent/` → 0 matches. The price-calculation pipeline that consumes `Item.value_base`, `disposition_mod`, `faction_mod`, `event_mod`, `context_mod`, and clamps to `[0.5×, 3.0×]` does not exist anywhere in the codebase. No tick loop instantiates events or transitions phases. No Redis key `region:{region}:prices` is ever written or invalidated.

## Coverage matrix

Spec sections under §Supply & Demand Engine mapped to existing `09_economy.md` milestone items. **NEW** = spec content with no corresponding M9.x bullet. Note: 09_economy.md L207-234 (Merchant Pricing Formula) names the event-modifier hook and the 0.5×–3.0× clamp but defers detail to this subsystem doc.

| Spec section (file:line) | Milestone item | Notes |
| --- | --- | --- |
| Magnitude & Stacking — 0.5×–3.0× clamp (supply_demand_engine.md:19-28) | M9.2 — merchant pricing engine + clamp | Cross-doc: gm_economy.md:213-214 also names the clamp. Story-001 marked clamp NOT_SHIPPED. |
| Magnitude & Stacking — Multiplicative stacking rule (supply_demand_engine.md:30-52) | M9.2 — modifier composition | Spec equation `event_modifier = product of all active event multipliers`. Decision 97 (L583) records rationale. |
| Item Tag Taxonomy — 11 economic tags (supply_demand_engine.md:55-75) | NEW | Milestone 9.x scope does not enumerate economic tags. **Capstone should add as new M9.x.** |
| Item Tag Taxonomy — Tag inheritance from materials (supply_demand_engine.md:77-79) | NEW | Inheritance computed at item generation time. **Capstone should add.** |
| Event Lifecycle — Phase 1: Active (supply_demand_engine.md:87-93) | NEW | Three-phase model not in existing milestone. **Capstone should add.** |
| Event Lifecycle — Phase 2: Recovery + linear decay (supply_demand_engine.md:95-114) | NEW | Includes recovery duration formula (`half active, min 2 days`) and `recovery_multiplier` linear-decay equation. **Capstone should add.** |
| Event Lifecycle — Phase 3: Resolved (supply_demand_engine.md:116-122) | NEW | **Capstone should add.** |
| Standard Event Catalog (supply_demand_engine.md:130-349) | NEW | 15 events across 3 categories (Demand-Driven: 6, Supply-Driven: 5 incl. Faction Embargo, Surplus: 4). **Capstone should add as a single subsystem subsection or split per category.** |
| Worked Example: Multi-Event Crisis (supply_demand_engine.md:353-391) | NEW | Illustrative only, but the example's price math is the canonical validation case. **Capstone should preserve as a regression-test anchor when M9.x compute_item_price lands.** |
| Implementation Reference — event-instance schema (supply_demand_engine.md:399-421) | NEW | Defines the JSONB shape that should live in `world_events_log.data` for economic events. **Capstone should add.** |
| Implementation Reference — `compute_item_price` (supply_demand_engine.md:425-484) | M9.2 — merchant pricing function | Function signature `compute_item_price(item, merchant, player) -> int`. Matches M9.2 deliverable. |
| Implementation Reference — Simulation tick (supply_demand_engine.md:488-520) | NEW | `economy_simulation_tick()` every 10 min. **Capstone should add or cross-ref a world-tick milestone.** |
| Implementation Reference — Redis price cache (supply_demand_engine.md:518-522) | NEW | 60s TTL invalidation on event state changes. **Capstone should add.** |
| DM Narration Patterns (supply_demand_engine.md:526-573) | NEW | 4 narration patterns (event onset, item inquiry by phase, cross-settlement awareness, intervention acknowledgment). **Capstone should add or fold into a content/narration_templates milestone.** |
| Design Decisions 96-104 (supply_demand_engine.md:577-597) | NEW | 9 architectural decisions. Spec L579 claims "Extracted to `game_mechanics_decisions.md` for canonical reference", but the decisions file only goes through Decision 72 (Economy Reconciliation) — decisions 96-104 are **NOT** extracted. **Capstone should either extract them or correct the spec's misleading claim.** |

## Audit Status (Sprint-006) — Magnitude & Stacking Rules

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Final computed prices clamped to 0.5×–3.0× of `value_base` (combined modifier output) | No clamp function. `grep -rnE 'clamp.*price\|clamp.*value_base\|0\.5.*3\.0\|max\(.*0\.5.*min\(.*3\.0' apps/agent/ packages/` → 0 matches. Story-001 already recorded clamp NOT_SHIPPED at the M9.2 deliverables layer; reaffirmed here in detail. | None | NOT_SHIPPED |
| Multiplicative stacking: `event_modifier = product of all active event multipliers`; combined with disposition × faction × event × context | No `apply_event_modifier`, no `compute_event_modifier`, no stacking helper. `grep -rnE 'event_modifier\|event_mod\b\|apply_event' apps/agent/` → 0 matches. The 4 modifiers (disposition, faction, event, context) don't compose anywhere — the formula has no callers because no caller exists. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Item Tag Taxonomy

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| 11 economic tags (`healing`, `anti-hollow`, `divine`, `weapons`, `armor`, `food`, `travel`, `luxury`, `crafting_material`, `imported`, `military`) | `Item.tags: string[]` (`packages/shared/src/entities/item.ts:17`) is a generic narrative+economic tag array. 1 of 11 spec tags (`healing`) appears organically on 3 items (`healing_potion`, `antidote_basic`, `restoration_salve` in `content/items.json`). The other 10 economic tags are **not enumerated as a taxonomy** and **do not appear consistently** on the items that would carry them in the spec (e.g. weapons carry `martial`/`simple`, not `weapons`; armor carries no `armor` tag; no item carries `anti-hollow` or `military` or `imported` or `luxury`). No separate `economic_tags: string[]` field on the schema. No tag-matching event-modifier lookup. | None | DESIGNED |
| Tag inheritance from material composition (computed at item-generation time, not runtime) | No item-generation pipeline encodes tag inheritance. The 29 items in `content/items.json` are hand-authored without a material-to-tag derivation step. `grep -rnE 'tag_inheritance\|inherit_tags\|derive_economic_tags' apps/ packages/` → 0 matches. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Event Lifecycle (Three Phases)

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Phase 1: Active — full multiplier; variable duration (1-3 days minor, 1-3 weeks major) | No `phase: active` field anywhere. `world_events_log` schema (`scripts/migrations/001:184-189`) has no `phase` column; data JSONB is unstructured for economy purposes. No `active_duration_seconds` is read or written. | None | NOT_SHIPPED |
| Phase 2: Recovery — linear decay from active multiplier toward 1.0× over recovery duration (half active, min 2 days) | No `compute_recovery_multipliers` function. `grep -rnE 'def.*recovery\|recovery_progress\|recovery_multiplier\|recovery_duration' apps/agent/` → 0 matches. Linear decay equation (`active_multiplier + (1.0 - active_multiplier) × recovery_progress`) is unencoded. | None | NOT_SHIPPED |
| Phase 3: Resolved — historical log, no mechanical effect | No phase enum, no transition. `world_events_log` retains all rows (it's an append-only log) which satisfies the "historical reference" requirement structurally — but the **phase semantics that would make a row "Resolved" instead of "Active"** are not represented anywhere. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Standard Event Catalog (15 events)

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Event substrate: `world_events_log` table + content/events.json | `scripts/migrations/001_initial_schema.sql:184-189` ships `world_events_log (id, event_id, timestamp, data JSONB)` with timestamp index (`002:9-10`). `content/events.json` ships 8 records (4 `scripted`, 3 `world_event`, 1 `god_whisper` — none `economic`). `apps/agent/db_mutations.py:228` writes; `apps/agent/world_news.py:39-83` reads for catch-up news. Substrate is **BUILT** for narrative use; the economic-event schema atop it (with `active_multipliers`, `phase`, `recovery_duration_seconds`) is **NOT_SHIPPED**. | None for economy-event semantics. | DESIGNED↔aspirational |
| 6 Demand-Driven events (Hollow Incursion, Bandit Activity, Disease Outbreak, War/Mobilization, Religious Pilgrimage/Divine Crisis, Refugee Influx) | 0 of 6 in `content/events.json`. The closest entry is `market_disruption` ("The Wounded Rider") — a scripted narrative beat, not an economic event template. | None | NOT_SHIPPED |
| 5 Supply-Driven events (Trade Route Disrupted, Mine Closure, Forest Corruption, Drought, Faction Embargo) | 0 of 5. | None | NOT_SHIPPED |
| 4 Surplus events (Bumper Harvest, Successful Mining Operation, Festival, Faction Surplus) | 0 of 4. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Worked Example

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Multi-event crisis: Hollow Incursion + Trade Route Disrupted + Refugee Influx → effective per-tag multipliers + final per-item prices (Healing Potion 25 sp → 39 sp, Hollow-Ward Amulet 150 sp → 243 sp, etc.) | No regression-test fixture, no canonical price-computation assertion file. The example is unverified in code because nothing computes price. `value_base` values in the example (25 sp Healing Potion, 150 sp Hollow-Ward Amulet) don't match `content/items.json` (Healing Potion `value_base=50`, no Hollow-Ward Amulet entry). The example is **internally consistent with the spec** but **disconnected from shipped content**. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Implementation Reference

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Event-instance schema (event_id, event_template, phase, started_at, phase_started_at, active_duration_seconds, recovery_duration_seconds, affected_regions, active_multipliers, resolution_conditions) | `world_events_log.data: JSONB` could carry this schema — table is BUILT — but no shipped writer constructs an event with these fields, and no reader extracts them. **DESIGNED↔confirmed for substrate, NOT_SHIPPED for the schema**. | None | DESIGNED |
| `compute_item_price(item, merchant, player) -> int` | Function does not exist. `grep -rnE 'def.*compute_item_price\|def.*compute_price\|def.*calc_price' apps/agent/` → 0 matches. The 5-modifier composition + clamp pipeline is unshipped end-to-end. | None | NOT_SHIPPED |
| `compute_recovery_multipliers(event)` linear-decay helper | Function does not exist. 0 matches. | None | NOT_SHIPPED |
| `economy_simulation_tick()` every 10 minutes (event phase progression + new event instantiation + price cache invalidation) | No `economy_simulation_tick`, no scheduler entry for economy. `grep -rnE 'def.*economy_simulation\|def.*economy_tick\|economy_tick' apps/agent/ apps/server/` → 0 matches. The agent has `apps/agent/async_rules.py` for cycle-based training but no economy tick. | None | NOT_SHIPPED |
| Event-resolution-conditions checker (`event_resolution_conditions_met`) | Function does not exist. | None | NOT_SHIPPED |
| Redis price cache (`region:{region}:prices`, 60s TTL, invalidated on event state change) | No Redis key with the spec-named pattern. `grep -rnE 'region:.*prices\|redis.delete.*price\|REDIS.*price\|price_cache' apps/agent/ apps/server/` → 0 matches. **DESIGNED↔aspirational only insofar as Bun.redis ships** as architectural baseline; the specific cache key + TTL + invalidation contract is NOT_SHIPPED. | None | DESIGNED |

## Audit Status (Sprint-006) — DM Narration Patterns

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Event-onset narration templates (Hollow Incursion, Bandit Activity, Disease Outbreak, Bumper Harvest worked examples) | No narration template registry for economy events. `grep -rnE 'event_onset_narration\|narrate_event_onset\|economy.*narration' apps/agent/` → 0 matches. The `world_news.py` LLM call generates news from raw event data via prompt, not from templated narration patterns. Phase 6 audit found `activity_templates.py:31-78` carries companion/training narration shims — no parallel shim for economic events. | None | NOT_SHIPPED |
| Per-phase specific-item-inquiry narration (active/recovery/resolved) | Not implemented. | None | NOT_SHIPPED |
| Cross-settlement awareness narration ("anti-Hollow gear is going to cost you a fortune here; try Tideholm") | Not implemented. No comparative pricing query exists. | None | NOT_SHIPPED |
| Player-intervention acknowledgment narration ("Heard about what you did at the breach") | Not implemented. Quest-completion + disposition shifts ship (see story-001 quest reward processing); the **price-recovery narrative tie-in** that would credit the player does not. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Design Decisions 96-104

Spec L577-597 records 9 architectural decisions. Spec L579 claims "Extracted to `game_mechanics_decisions.md` for canonical reference" — **but this extraction has not happened**. The canonical decisions log (`docs/game_mechanics/game_mechanics_decisions.md`, 186L) terminates at Decision 72 (Economy Reconciliation). The 9 decisions below are still spec-local. Each answers a design question the implementation must encode. None are encoded.

| Decision | Item (verbatim) | Status |
| --- | --- | --- |
| 96 | Hard price bounds clamp to [0.5×, 3.0×] of base | NOT_SHIPPED (no clamp function) |
| 97 | Event modifiers stack multiplicatively, not additively | NOT_SHIPPED (no stacking function) |
| 98 | Item granularity is tag-based, not category-based | NOT_SHIPPED (no economic-tag field; 1 of 11 spec tags appears organically) |
| 99 | Tag matching is once-per-event (strongest applicable tag wins) | NOT_SHIPPED (no matcher) |
| 100 | Three-phase lifecycle with linear recovery decay | NOT_SHIPPED (no phase enum, no decay) |
| 101 | Recovery duration is half active duration, minimum 2 in-game days | NOT_SHIPPED (no recovery duration field) |
| 102 | Player intervention can resolve events early; time-based resolution is the fallback | NOT_SHIPPED (no resolution-conditions checker) |
| 103 | DM narrates causes; character sheet shows numbers | NOT_SHIPPED for the narration patterns; the **division of labor** (DM voices narrative, HUD shows price) is structurally how the rest of the system works — so the principle is honored by design even though the specific narration patterns aren't built |
| 104 | Event narration should reference player intervention for resolved events | NOT_SHIPPED (no resolved-event narration path) |

## Deliverables status (per 09_economy.md M9.2 §Deliverables L55-71, cross-doc)

This audit story is doc-only and does not own M9.x deliverables directly — the capstone (story-008) will. Mapping for the capstone:

- Event-modifier hook on the merchant pricing formula: **NOT_SHIPPED** (no event_mod, no compute_item_price)
- 0.5×–3.0× price clamp: **NOT_SHIPPED** (no clamp function)
- 11 economic tags on items: **DESIGNED↔aspirational** (Item.tags exists; `healing` shipped, 10 others absent)
- 3-phase event lifecycle (Active/Recovery/Resolved): **NOT_SHIPPED**
- 15 standard event content records: **NOT_SHIPPED** (substrate BUILT, content typed as scripted/world_event not economic)
- `compute_item_price` + `compute_recovery_multipliers` + `economy_simulation_tick`: **NOT_SHIPPED**
- Redis price cache (60s TTL, region-keyed): **DESIGNED↔aspirational** (Bun.redis ships; specific cache contract not encoded)
- DM narration templates (4 patterns): **NOT_SHIPPED**

## Out-of-scope findings (Sprint-spec-cleanup punch list)

Routed to `audit/README.md` Sprint-006 section by capstone (story-008) per wisdom `d0715b09a1df`:

1. **Add 11 economic tags + tag-inheritance as a new M9.x subsection** (cross-ref Item schema). The taxonomy is sufficiently distinct from narrative tags that a separate `economic_tags: string[]` field on Item is worth proposing rather than overloading `tags`.
2. **Add three-phase event lifecycle as a new M9.x subsection** (Active/Recovery/Resolved + linear decay + half-duration min-2-day recovery).
3. **Add 15 standard event content records as a new M9.x subsection** — 6 demand-driven + 5 supply-driven (Trade Route Disrupted, Mine Closure, Forest Corruption, Drought, Faction Embargo) + 4 surplus. Distinct from `world_events_log` substrate; this is content-authoring work.
4. **Add `compute_item_price` + `economy_simulation_tick` + Redis price cache as M9.x — split or combine with M9.2** (the existing merchant pricing engine milestone names the function but not the tick or cache).
5. **Add DM narration patterns as a new M9.x subsection** OR cross-ref a `content/narration_templates` milestone (current narration shims live in `apps/agent/activity_templates.py`).
6. **Decisions 96-104 are NOT extracted to `game_mechanics_decisions.md`** despite spec L579 claiming they are. The decisions file ends at Decision 72. Capstone should either extract 96-104 (preserving the spec→decisions ID continuity) or fix the spec's misleading claim. Note the gap: spec uses 96-104, but the decisions log's next free number is 73 — renumbering may be required.
7. **Reconcile `content/events.json`'s `market_disruption` entry**: the id reads as economic but the type is `scripted`. Either rename the event or upgrade its type — current state is misleading.
8. **`world_events_log.data` schema is unstructured.** When the economy engine lands, decide whether to enforce a JSONB schema for `type: "economic"` events or to introduce a sibling table `economy_events` with explicit columns. Spec L399-421 implies the former; tradeoff with indexability and query ergonomics.

## Verification

Verified-at: 434df7da37adaf5ea67bb2aa63d6d01cdfdd6338

Grep commands used (all from repo root; 0 matches unless noted):

```bash
# Magnitude & Stacking
grep -rnE 'clamp.*price|clamp.*value_base|0\.5.*3\.0|max\(.*0\.5.*min\(.*3\.0' apps/agent/ packages/
grep -rnE 'event_modifier|event_mod\b|apply_event' apps/agent/

# Tag taxonomy
grep -rnE 'economic_tags|tag_inheritance|inherit_tags|derive_economic_tags' apps/ packages/

# Three-phase lifecycle
grep -rnE 'def.*recovery|recovery_progress|recovery_multiplier|recovery_duration|phase.*active.*recovery' apps/agent/

# Compute price + tick
grep -rnE 'def.*compute_item_price|def.*compute_price|def.*calc_price|def.*economy_simulation|def.*economy_tick|def.*apply_event_modifier|def.*compute_recovery' apps/agent/

# Narration templates
grep -rnE 'event_onset_narration|narrate_event_onset|economy.*narration' apps/agent/

# Redis price cache
grep -rnE 'region:.*prices|redis.delete.*price|REDIS.*price|price_cache' apps/agent/ apps/server/

# Confirmed-present substrate (returned matches):
grep -nE 'CREATE TABLE world_events_log' scripts/migrations/001_initial_schema.sql       # L184
grep -nE 'CREATE TABLE events' scripts/migrations/001_initial_schema.sql                  # L48
grep -nE 'idx_world_events_log' scripts/migrations/002_add_indexes.sql                    # L9-10
grep -nE 'INSERT INTO world_events_log' apps/agent/db_mutations.py                        # L228
grep -nE 'FROM world_events_log' apps/agent/world_news.py                                 # L39

# Item tag taxonomy sample
python3 -c "import json; d=json.load(open('content/items.json')); items=d['items'] if isinstance(d,dict) else d; print('healing tag count:', sum(1 for i in items if 'healing' in i.get('tags',[])))"   # 3

# content/events.json type distribution
python3 -c "import json; d=json.load(open('content/events.json')); evs=d if isinstance(d,list) else d.get('events',[]); print({e.get('type','?') for e in evs})"   # {'scripted', 'world_event', 'god_whisper'} — no 'economic' (counts: 4/3/1)
```
