# Phase 9 Audit — Economy / Inflation Targets & Controls (Sprint-006 story-006)

Sprint-006 / Milestone 6 (story-006). Read-only audit of `docs/game_mechanics/economy/inflation_targets_controls.md` (275 lines, 1 H2 with 8 major subsections covering Phase 1 wealth curves, analytics infrastructure, Phase 2+ global controls, god-agent intervention, seasonal events, parameter tuning, control loop, and 8 design decisions) against shipped code in `apps/agent/`, `apps/server/src/`, `packages/shared/src/entities/`, `content/`, and `scripts/migrations/`. Status legend (matches sprint-004 audit/README.md L49-58): **BUILT** = code present and matches spec; **DESIGNED** = spec well-defined and partial code exists, but the symbol/feature is missing, renamed, or diverges; **NOT_SHIPPED** = no implementation found. Sibling sprint-006 audit files: `phase-9-economy.md` (story-001), `phase-9-supply-demand.md` (story-002), `phase-9-faction-pricing.md` (story-003), `phase-9-restock.md` (story-004), `phase-9-gold-sink.md` (story-005).

Verified-at: 0214d3b9ee92f0632ed4d5e78d1c8cd37ad9d3a2

## Summary

| Section | BUILT | DESIGNED | NOT_SHIPPED |
| --- | --- | --- | --- |
| Phase 1 Wealth Curve (8 level bands, 3 growth phases) | 0 | 0 | 11 |
| Per-Session Balance Target (net +50-150 sp) | 0 | 0 | 1 |
| Player-Driven Variance (hoarder/spender/crafter archetypes) | 0 | 0 | 1 |
| Analytics Infrastructure — Faucet Event Logging (8 categories) | 0 | 0 | 9 |
| Aggregate Metrics (5 metrics × rolling windows) | 0 | 0 | 5 |
| Phase 2+ Global Faucet/Sink Ratio Targets (4 windows: 24h/7d/30d/90d) | 0 | 0 | 4 |
| God-Agent Economic Intervention (4 named gods + heartbeat hook) | 0 | 2 | 4 |
| Seasonal Economic Events (6 seasons: Lantern/Forge Day/Veil Wane/Veil Wax/Harvest/Long Dark) | 0 | 0 | 6 |
| Parameter Tuning (manual ops lever) | 0 | 0 | 1 |
| Phase 2+ Inflation Control Loop (6-step pipeline) | 0 | 0 | 6 |
| What Phase 1 Needs (5-item infrastructure checklist) | 0 | 1 | 4 |
| Design Decisions 114-121 (8 decisions) | 0 | 0 | 8 |

**Headline finding:** Inflation control is **entirely NOT_SHIPPED** at the mechanical layer. What ships across the surface is **adjacent infrastructure**, not the inflation systems themselves: (1) `content/gods.json` ships 10 gods (`veythar`, `mortaen`, `aelora`, `kaelen`, `syrath`, `thyra`, `valdris`, `nythera`, `orenthel`, `zhael`) with rich domain/whisper/favor data — but **the god-agent economic-intervention heartbeat the spec relies on does not exist**; (2) `scripts/migrations/009_god_whispers.sql` ships the `god_whispers` table; `apps/agent/god_whisper_generator.py:16` ships `generate_god_whisper`; `apps/agent/async_worker.py:396-426` invokes it on patron-id triggers — but **none of these consume an economic-state signal**, so the spec's "Mortaen demands tribute when death-spell spending is high" / "Aelindra grants visions when wealth is low" intervention loop has no trigger; (3) `apps/agent/quest_tools.py:138-167` processes quest rewards (faucet side, BUILT per story-001) — but **no faucet_event_log table** exists to record amounts per category, so the spec's 8-category faucet taxonomy + aggregate-metrics layer has nothing to ingest; (4) `content/events.json` ships 8 scripted/world_event records per story-002 audit, but **0 of 6 spec seasonal events** (Lantern Festival, Forge Day, Veil Wane, Veil Wax, Harvest Time, Long Dark) are authored. What does NOT ship: zero of 11 wealth-curve targets as code constants, zero of 8 faucet categories enumerated, zero of 5 aggregate metrics computed, zero of 4 ratio-window thresholds, zero of 6 seasonal events authored, zero of 6 control-loop steps wired, zero of 8 design decisions 114-121 encoded.

**Honesty note 1 — God roster diverges from spec.** Spec L151-174 names specific gods for economic intervention: **Aelindra** (Preservation/Memory/Value), **Mortaen** (Death/Endings), **Veythar** (Knowledge/Magic), and "A War God (TBD)". Shipped roster (`content/gods.json`): **Veythar** ✓ (matches spec exactly — Knowledge/discovery/memory/arcane), **Mortaen** ✓ (Death/afterlife/transition), and **Kaelen** (War/conflict/valor) fills the "War God TBD" slot. **But Aelindra is NOT in the god roster** — `aelindra` appears only as a faction name (`aelindran_diaspora` per story-003 + story-004 audits). The closest god analogue is **Aelora** (Civilization, commerce, crafting, community) — domain-wise sympathetic to "Preservation/Memory/Value" but a different deity. **Content/spec naming gap**: spec example reads "Aelindra has granted you a vision of an old Aelindran cache" — `Aelindran` (faction) ships, `Aelindra` (god) does not. Capstone must reconcile: rename one, or accept that "Aelora" plays the Aelindra-shaped role in shipped content.

**Honesty note 2 — God-whisper generation ships, economic-state-driven trigger does not.** `apps/agent/god_whisper_generator.py:16` ships `async def generate_god_whisper(player_id, patron_id)`. `apps/agent/async_worker.py:396-426` calls it as an async background task. The infrastructure for "god takes action that affects the player" is **BUILT** at the substrate level. But the trigger pipeline is patron-id-driven (player has a patron → patron-specific whisper) — **not economic-state-driven** (faucet/sink ratio drifts → affected god triggers). Spec's intervention model needs the heartbeat to evaluate an economic signal, choose an affected god, and emit a whisper *plus* an economic event (per story-002 supply/demand engine — also NOT_SHIPPED). The whisper-emission half is **DESIGNED↔confirmed**; the economic-state-evaluation half and the economic-event-emission half are NOT_SHIPPED.

**Honesty note 3 — Patron heartbeat is referenced but its mechanical state is unverified from this audit.** Spec L242 says "The patron heartbeat system already exists. Adding 'evaluate economic state' as a heartbeat consideration means the framework is ready for Phase 2+ activation." This audit did not verify the patron heartbeat itself end-to-end (`grep -rnE 'patron_heartbeat\|god_heartbeat' apps/` → 0 matches as a named symbol). The async_worker invokes `generate_god_whisper` but its scheduling cadence (every 15-30 minutes per spec) is not surfaced as a "heartbeat" concept in code. **Cross-ref Phase 6 audit (phase-6-companions.md / phase-8-patrons.md) for definitive patron-heartbeat status.** This audit conservatively marks the heartbeat as DESIGNED based on the whisper-generation BUILT substrate, with the qualifier that the scheduling layer was not separately verified.

**Honesty note 4 — Phase 1 wealth-curve targets are not encoded.** Spec L34-43 gives 8 level-band targets (Level 1: 10sp → Level 19-20: 6,000-15,000sp). No code constant table. `grep -rnE 'expected_wealth\|wealth_by_level\|target_wealth' apps/ packages/` → 0 matches. The starting-gold-by-archetype values (`apps/agent/creation_classes.py:21` per story-001 BUILT finding) cover Level 1 only and **diverge from spec** (spec says 10sp baseline / 15sp Diplomat; code ships 4 values 10/15/20/25 with Diplomat=25 per story-001 honesty note 3). Beyond Level 1, the curve has **no representation in code**.

**Honesty note 5 — Fifth sprint-006 audit story to find the false decision-extraction pattern.** Spec L259 claims decisions 114-121 are "Extracted to `game_mechanics_decisions.md` for canonical reference." **They are not** — the canonical decisions log terminates at Decision 72 (Economy Reconciliation). Same pattern as stories 002 (96-104), 003 (82-86), 004 (87-95), 005 (105-113). Combined implied undocumented decisions: 73-81 + 82-86 + 87-95 + 96-104 + 105-113 + 114-121 = **at least 44 decisions** spec-local but not in canonical log. This is the **fifth consecutive sprint-006 audit** to find this pattern — capstone bulk-fix is well overdue.

## Coverage matrix

Spec sections under §Inflation Targets & Controls mapped to existing `09_economy.md` milestone items. **NEW** = spec content with no corresponding M9.x bullet. Most rows are NEW since 09_economy.md predates this subsystem doc.

| Spec section (file:line) | Milestone item | Notes |
| --- | --- | --- |
| Design Philosophy + Phase 1/2+ split (inflation_targets_controls.md:11-23) | NEW | Per-character balance (Phase 1) vs global macro (Phase 2+). **Capstone should add as M9.x preamble.** |
| Phase 1 Target Wealth Curve — 8 level-bands (inflation_targets_controls.md:30-49) | NEW | 8 expected-wealth ranges + 3 growth phases. **Capstone should add as M9.x.** |
| Per-Session Balance Target (inflation_targets_controls.md:58-66) | NEW | Net +50-150 sp typical. Requires both faucet + sink instrumentation. |
| Player-Driven Variance (inflation_targets_controls.md:68-76) | NEW | Hoarders/spenders/crafters acceptable variance. Cross-ref story-005 (crafter sinks: workspace rental NOT_SHIPPED). |
| Analytics Infrastructure — Faucet Event Logging (inflation_targets_controls.md:80-106) | NEW | 8 faucet categories (quest_reward, loot_sale, material_sale, crafted_sale, faction_bounty, service_income, currency_drop, consignment_payout). Cross-ref story-005 sink_event_log schema (parallel, also NOT_SHIPPED). |
| Aggregate Metrics (inflation_targets_controls.md:108-120) | NEW | 5 metrics × rolling windows. Requires both event_log tables (faucet + sink) before aggregation can run. |
| Phase 2+ Global Ratio Targets (inflation_targets_controls.md:128-141) | NEW [Phase 2+] | 4 acceptable-range windows + escalation policy. |
| God-Agent Economic Intervention (inflation_targets_controls.md:147-175) | NEW [Phase 2+] | 4 named gods + heartbeat hook + narrative-as-mechanic principle. Cross-ref `phase-6-companions.md` / `phase-8-patrons.md` for patron heartbeat status. Honesty notes 1+2+3 detail divergence. |
| Seasonal Economic Events (inflation_targets_controls.md:177-194) | NEW [Phase 2+] | 6 seasons authored as content + calendar triggers. Cross-ref story-002 (supply_demand_engine event schema also NOT_SHIPPED). |
| Parameter Tuning (manual ops) (inflation_targets_controls.md:196-205) | NEW | Server-side config for quest rewards, sink magnitudes, loot rates. Not a Phase 1 ship requirement. |
| Phase 2+ Inflation Control Loop (inflation_targets_controls.md:209-232) | NEW [Phase 2+] | 6-step pipeline from data ingestion → drift detection → intervention → narration. |
| What Phase 1 Needs — 5-item checklist (inflation_targets_controls.md:236-253) | NEW | Per-event logging, aggregate metrics, god-agent stubs, seasonal schema, parameter config. **Capstone owns this checklist directly.** |
| Design Decisions 114-121 (inflation_targets_controls.md:257-275) | NEW | 8 architectural decisions. Spec L259 false-extraction claim — fifth audit story to find this pattern (honesty note 5). |

## Audit Status (Sprint-006) — Phase 1 Wealth Curve

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Target wealth by level — 8 bands (L1: 10sp / L2-3: 30-80sp / L4-6: 100-300sp / L7-9: 300-700sp / L10-12: 700-1500sp / L13-15: 1500-3000sp / L16-18: 3000-6000sp / L19-20: 6000-15000sp) | No `wealth_curve` / `expected_wealth_by_level` constant table. `grep -rnE 'wealth_curve\|wealth_by_level\|liquid_wealth\|expected_wealth' apps/ packages/` → 0 matches. Level 1 only has `starting_gold` (BUILT per story-001 but diverges from spec — 10/15/20/25 spread vs spec 10/15). Levels 2-20 unmodeled. | None | NOT_SHIPPED |
| 3 growth phases (steep 1-9 / moderate 10-15 / plateau 16-20) | No phase boundaries encoded. No per-phase target net wealth growth. | None | NOT_SHIPPED |
| Per-level net wealth growth targets (~50-100sp/level @ L1-9, ~150-300sp/level @ L10-15, tapering @ L16-20) | No per-level targets in code. Levelling system ships (`apps/agent/leveling.py` per story-001) for XP-driven progression; **no wealth-by-level coupling**. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Per-Session Balance Target & Variance

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Per-session net +50-150 sp typical, with acceptable outliers (net negative after death, net positive 500+ after rare loot) | No session-level wealth-delta tracker. No `session_net_wealth` metric. Cross-ref story-005: sink event logging NOT_SHIPPED → the "net" computation has neither side instrumented. | None | NOT_SHIPPED |
| Player-driven variance (hoarders 2-3× target, spenders 0.5× target, crafters with different gear/wealth tradeoffs) | Variance modeling NOT_SHIPPED. Not surprising: the substrate (wealth-curve targets + per-session tracking) doesn't ship, so deviation-from-typical is undefined. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Analytics Infrastructure (Faucet Event Logging)

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| `faucet_event` log schema {player_id, faucet_category, faucet_type, quest_id?, amount_sp, context, timestamp} | No `faucet_event_log` table. `grep -rnE 'CREATE TABLE.*faucet\|faucet_event\|faucet_category' scripts/migrations/*.sql apps/ packages/` → 0 matches. New table needed (parallel to story-005's NOT_SHIPPED sink_event_log). | None | NOT_SHIPPED |
| 8 faucet categories (quest_reward, loot_sale, material_sale, crafted_sale, faction_bounty, service_income, currency_drop, consignment_payout) | 0 of 8 enumerated as code constants. No `FaucetCategory` enum. | None | NOT_SHIPPED |
| Faucet logging hooked into shipped surfaces: quest reward processing (`apps/agent/quest_tools.py:138-167` per story-001), inventory mutations (`add_to_inventory` / `remove_from_inventory` per story-004), training-cycle payouts, etc. | The shipped surfaces exist (BUILT per other audits). Faucet-event emission **not wired** — the quest_tools reward handler mutates state but does not emit a `faucet_event` row. Equivalent wiring needed everywhere a sale/reward/drop happens. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Aggregate Metrics

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Player session net (faucet - sink) per-session | No metric. Requires both event_log tables. | None | NOT_SHIPPED |
| Player wealth by level (snapshot) | No metric. No wealth-by-level query. | None | NOT_SHIPPED |
| Faucet category distribution (30d window) | No aggregation. | None | NOT_SHIPPED |
| Sink category distribution (30d window) | No aggregation. Cross-ref story-005: sink_event_log NOT_SHIPPED. | None | NOT_SHIPPED |
| Net wealth velocity by level (30d window) | No metric. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Phase 2+ Global Faucet/Sink Ratio Targets

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| 24h window 0.7-1.4 (monitor only) | No window aggregator. | None | NOT_SHIPPED |
| 7d window 0.85-1.2 (light intervention) | No window aggregator. | None | NOT_SHIPPED |
| 30d window 0.95-1.1 (active intervention required) | No window aggregator. | None | NOT_SHIPPED |
| 90d window 0.98-1.05 (balance crisis trigger) | No window aggregator. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — God-Agent Economic Intervention

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| 10 gods in `content/gods.json` with rich schema (favor_actions, layer_1_gift, whisper_profile, etc.) | `content/gods.json` ships 10 gods: veythar, kaelen, aelora, syrath, mortaen, thyra, valdris, nythera, orenthel, zhael. Schema includes `favor_actions`, `whisper_themes`, `whisper_profile`, etc. **BUILT** at the content layer (per Phase 6 + Phase 8 audits). | None re-verified in this audit | DESIGNED↔confirmed |
| Aelindra (Preservation/Memory/Value) — economic-intervention god | **Aelindra is not in the god roster.** `aelindra` appears only as a faction name (`aelindran_diaspora`). The closest god analogue is `aelora` (Civilization/commerce/crafting/community) — sympathetic but distinct deity. See honesty note 1. **Spec/content naming gap**: spec example "Aelindra's vision" cannot be authored against shipped roster as-is. | None | NOT_SHIPPED (specifically — `aelora` exists but spec target god does not) |
| Mortaen (Death/Endings) — economic-intervention god | `mortaen` ships in `content/gods.json` (domain: Death/afterlife/transition). Matches spec. | None | DESIGNED↔confirmed |
| Veythar (Knowledge/Magic) — economic-intervention god | `veythar` ships (domain: Knowledge/discovery/memory/arcane). Matches spec exactly. | None | DESIGNED↔confirmed |
| War God (TBD per spec) — economic-intervention god | Shipped roster includes `kaelen` (War/conflict/valor/martial discipline). Fills the "TBD" slot cleanly. Capstone should record this as the canonical War God. | None | DESIGNED↔confirmed |
| God-whisper generation infrastructure (`generate_god_whisper`) | `apps/agent/god_whisper_generator.py:16` ships `generate_god_whisper(player_id, patron_id)`. `apps/agent/async_worker.py:396-426` invokes it. `scripts/migrations/009_god_whispers.sql` ships the `god_whispers` table with `idx_god_whispers_player`. **Substrate BUILT** for the "god takes action that affects the player" half of the spec. | None re-verified in this audit | DESIGNED↔confirmed |
| Economic-state-driven heartbeat trigger (faucet/sink drift → affected god takes action) | The whisper trigger pipeline is **patron-id-driven**, not economic-state-driven. No `evaluate_economic_state` consideration in the async_worker. No economic-signal-to-god routing. See honesty note 2. | None | NOT_SHIPPED |
| Per-god intervention action types (Aelindra grants visions, Mortaen demands tribute, Veythar creates research opportunities, War God triggers conflict) | 0 of 4 intervention action handlers. The whisper-text generation could in principle carry these semantics but **no economic event is emitted alongside** (spec needs a sibling supply/demand event per story-002 — also NOT_SHIPPED). | None | NOT_SHIPPED |
| Patron heartbeat scheduling (15-30 min cadence per spec) | Not surfaced as a named symbol in this audit's grep pass. Async worker invokes `generate_god_whisper` but cadence not verified end-to-end here. **See honesty note 3** — conservatively marked DESIGNED based on whisper substrate, with the qualifier that the scheduling layer was not separately verified. Cross-ref `phase-8-patrons.md` for definitive heartbeat status. | None | DESIGNED |

## Audit Status (Sprint-006) — Seasonal Economic Events

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| 6 seasons with authored event content (Lantern Festival, Forge Day, Veil Wane, Veil Wax, Harvest Time, Long Dark) | `content/events.json` ships 8 records per story-002 audit (all `type: "scripted"` or `"world_event"` or `"god_whisper"` — none typed `economic` or `seasonal`). 0 of 6 spec seasons ship. | None | NOT_SHIPPED |
| Calendar-based event triggers (annual/semi-annual cadence) | No calendar layer. No cron/schedule-based event firing. | None | NOT_SHIPPED |
| Seasonal events authored as standard economic events (per `supply_demand_engine.md` schema) | Cross-ref story-002: supply/demand engine + economic event schema NOT_SHIPPED. Seasons inherit. | None | NOT_SHIPPED |
| Lantern Festival (Aelindran, 1 in-game week, annual): -15% luxury, +15% divine | Not authored. Note: spec credits this to **Aelindran** culture — that part ships (`aelindran_diaspora` faction per story-003 audit). The festival event itself doesn't. | None | NOT_SHIPPED |
| Forge Day (Keldaran, 1 in-game week, annual): -15% weapons/armor, -25% Tier 1-2 commissions | Not authored. **Keldaran faction is NOT in `content/factions.json`** (4 shipped: accord_guild, aelindran_diaspora, independent, temple_authority per story-003). Multi-layer gap. | None | NOT_SHIPPED |
| Veil Wane / Veil Wax (semi-annual): Hollow-related demand cycles | Not authored. Hollow corruption mechanics exist narratively but no Veil-cycle clock. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Parameter Tuning & Control Loop

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Server-side parameter config (quest reward values, sink magnitudes, loot drop rates, currency drop formulas) | No `economy_config.json` / server-side tunable parameter file. Quest rewards are hardcoded in `content/quests.json` stages; sink magnitudes are spec-only (no code constants). Tuning would require content edits, not parameter changes. | None | NOT_SHIPPED |
| 6-step Phase 2+ inflation control loop (data ingestion → aggregation → drift detection → escalation by window → effect propagation → narration → loop) | 0 of 6 steps wired. Most steps depend on faucet/sink event_log tables (also NOT_SHIPPED). | None | NOT_SHIPPED |
| Effects narrated to players naturally (no economic UI dashboard) — principle of "macroeconomics expressed as worldbuilding" (Decision 120) | **Structurally honored by absence**: there's no inflation UI in shipped HUD. But the positive-form-honoring (Mortaen's tribute demands, Aelindra's visions, Forge Day approach) is also not built, so the principle is unverifiable in practice. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — What Phase 1 Needs (5-item checklist)

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| 1. Per-event logging infrastructure (faucet + sink) | Cross-ref story-005 (sink_event_log NOT_SHIPPED) + faucet_event_log row above. Both halves absent. | None | NOT_SHIPPED |
| 2. Aggregate metrics computation (5 rolling-window metrics) | Cross-ref Aggregate Metrics rows above. NOT_SHIPPED. | None | NOT_SHIPPED |
| 3. God-agent economic action stubs (heartbeat + per-god intervention handlers) | God whisper substrate BUILT (whisper generator + table); economic-state-driven heartbeat trigger NOT_SHIPPED. **DESIGNED** at substrate, **NOT_SHIPPED** at the activation layer. | None | DESIGNED |
| 4. Seasonal event content data structure (authored + calendar-triggered) | Cross-ref Seasonal Events rows above. NOT_SHIPPED. | None | NOT_SHIPPED |
| 5. Parameter tuning capability (server-side config for rewards/sinks/loot) | Cross-ref Parameter Tuning row above. NOT_SHIPPED. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Design Decisions 114-121

Spec L257-275 records 8 architectural decisions. Spec L259 claims "Extracted to `game_mechanics_decisions.md` for canonical reference" — **fifth audit story to find the same false-extraction pattern** (stories 002 found 96-104, 003 found 82-86, 004 found 87-95, 005 found 105-113). The canonical decisions log terminates at Decision 72 (Economy Reconciliation). Decisions 114-121 are still spec-local. Combined undocumented range across sprint-006 audits: 73-81 + 82-86 + 87-95 + 96-104 + 105-113 + 114-121 = **44+ decisions** spec-local but not in canonical log. None encoded.

| Decision | Item (verbatim) | Status |
| --- | --- | --- |
| 114 | Inflation control is Phase 2+ primary concern; Phase 1 implements data infrastructure only | NOT_SHIPPED |
| 115 | Wealth-by-level curve has 3 phases (steep 1-9 / moderate 10-15 / plateau 16-20) | NOT_SHIPPED |
| 116 | Per-session balance target is net positive 50-150 sp | NOT_SHIPPED |
| 117 | Long-term faucet/sink ratio target is 1.0 with controlled variance | NOT_SHIPPED |
| 118 | God-agent economic intervention is the primary Phase 2+ control mechanism | NOT_SHIPPED (whisper substrate BUILT, intervention trigger NOT_SHIPPED) |
| 119 | Seasonal economic events are authored content with calendar triggers, not procedural | NOT_SHIPPED |
| 120 | Player must never see the inflation control system directly | Structurally honored by absence; positive form (narration patterns) NOT_SHIPPED |
| 121 | Wealth variance from player choice is not a bug | NOT_SHIPPED (no variance modeling because no wealth tracking) |

## Deliverables status (per 09_economy.md M9.x §Deliverables, cross-doc)

This audit story is doc-only and does not own M9.x deliverables directly — the capstone (story-008) will. Mapping for the capstone:

- 8-band wealth-by-level curve constants: **NOT_SHIPPED**
- Per-session balance target tracker: **NOT_SHIPPED**
- `faucet_event_log` table + 8-category enum: **NOT_SHIPPED**
- 5 aggregate metrics × rolling-window queries: **NOT_SHIPPED**
- Phase 2+ ratio-target enforcement: **NOT_SHIPPED**
- God-agent economic intervention pipeline (heartbeat → state evaluation → affected god → action): **DESIGNED** (whisper substrate BUILT; economic-state trigger + per-god handler NOT_SHIPPED)
- Seasonal economic event content + calendar trigger: **NOT_SHIPPED**
- Parameter tuning config: **NOT_SHIPPED**
- 8 design decisions 114-121 encoded as constants: **NOT_SHIPPED**

## Out-of-scope findings (Sprint-spec-cleanup punch list)

Routed to `audit/README.md` Sprint-006 section by capstone (story-008) per wisdom `d0715b09a1df`:

1. **Reconcile god roster: Aelindra (spec) vs Aelora (content).** Spec names Aelindra as an economic-intervention god; shipped roster has Aelora (commerce/civilization) + faction Aelindran. Capstone must pick: (a) rename `aelora` → `aelindra` in content, (b) rename spec references to use `aelora`, or (c) accept that Aelora plays the Aelindra-shaped role with explicit mapping doc.
2. **Add `faucet_event_log` table** (migration) parallel to story-005's NOT_SHIPPED `sink_event_log`. Schema per spec L86-95. **High-leverage low-cost**: both tables are required for ALL aggregate-metrics work.
3. **Wire faucet-event emission into shipped surfaces**: `quest_tools.py:138-167` reward handler must emit `faucet_event` rows; loot/material/crafted/consignment sale paths must too. Most call sites already exist (per story-001, story-004) — just need the emission hook.
4. **Add `evaluate_economic_state` consideration to patron heartbeat**: the god-whisper generator + async_worker substrate is BUILT (per honesty note 2); needs a hook that reads aggregate metrics, identifies drift, picks an affected god, and emits an economic event alongside the whisper.
5. **Author Phase 1 seasonal-event proof-of-concept** (spec recommends 1-2 seasons as POC, defer comprehensive content to Phase 2+). Easiest candidate: **Forge Day** (Keldaran) **OR Harvest Time** — both are content-authoring tasks that exercise the calendar trigger layer once supply/demand event schema (story-002) lands.
6. **Reconcile Keldaran faction**: spec references Keldaran as a culture (Forge Day, Keldaran-forged weapons per story-003 audit). Keldaran is NOT in `content/factions.json`. Capstone should bundle with story-003 punch-list item 2 (Thornwatch + Merchant Guild content reconciliation) — multiple spec-cultural references need faction backing.
7. **Decisions 114-121 are NOT extracted to `game_mechanics_decisions.md`.** Fifth audit story finding the same false-extraction pattern. Combined undocumented decision count is now 44+ across sprint-006 audits. Bulk fix at capstone overdue.
8. **Wealth-by-level constants need a home**: capstone should decide between (a) `apps/agent/economy_config.py` constants table, (b) JSON file (`content/economy_targets.json`), or (c) DB table. Spec implies it's tunable (Decision 118 parameter tuning lever), so (b) or (c) is preferable to (a).
9. **Patron heartbeat cadence verification deferred to phase-8-patrons.md cross-ref.** This audit conservatively marked the heartbeat DESIGNED based on whisper substrate but did not verify the 15-30 min cadence end-to-end (honesty note 3). Capstone should reconcile against phase-8 audit findings.

## Verification

Verified-at: 0214d3b9ee92f0632ed4d5e78d1c8cd37ad9d3a2

Grep commands used (all from repo root; 0 matches unless noted):

```bash
# Faucet event logging
grep -rnE 'faucet_event|faucet_category|faucet_type|faucet_log|FaucetCategory' apps/ packages/ scripts/migrations/

# Wealth curve / level wealth
grep -rnE 'wealth_curve|wealth_by_level|liquid_wealth|expected_wealth|target_wealth' apps/ packages/

# Economic intervention / heartbeat
grep -rnE 'god_heartbeat|patron_heartbeat|economic_intervention|evaluate_economic_state' apps/ packages/
grep -rnE 'aggregate_metric|economic_ratio|sink_ratio|faucet_ratio|net_velocity' apps/ packages/

# Seasonal events
grep -rnE 'seasonal_event|cultural_calendar|lantern_festival|forge_day|veil_wane|veil_wax|harvest_time|long_dark' apps/ packages/ content/

# Confirmed-present substrate (returned matches):
grep -nE 'CREATE TABLE god_whispers' scripts/migrations/009_god_whispers.sql      # L1
grep -nE 'async def generate_god_whisper' apps/agent/god_whisper_generator.py     # L16
grep -nE 'generate_god_whisper' apps/agent/async_worker.py                         # L396-426

# Gods roster
python3 -c "import json; gs = json.load(open('content/gods.json')); gs = gs['gods'] if isinstance(gs, dict) else gs; print([g.get('god_id') for g in gs])"
# ['veythar', 'kaelen', 'aelora', 'syrath', 'mortaen', 'thyra', 'valdris', 'nythera', 'orenthel', 'zhael']
# Note: 'aelindra' is absent; 'aelora' is the closest analogue (commerce/civilization)

# Spec-named gods presence
python3 -c "import json; gs = json.load(open('content/gods.json')); gs = gs['gods'] if isinstance(gs, dict) else gs; ids = {g.get('god_id') for g in gs}; print({'aelindra in roster': 'aelindra' in ids, 'mortaen': 'mortaen' in ids, 'veythar': 'veythar' in ids, 'kaelen (war god)': 'kaelen' in ids})"
# {'aelindra in roster': False, 'mortaen': True, 'veythar': True, 'kaelen (war god)': True}

# Decisions log terminates at Decision 72 (5th audit to verify)
grep -nE '^## ' docs/game_mechanics/game_mechanics_decisions.md | tail -3
# "## Economy Reconciliation (Decision 72)" is the last
```
