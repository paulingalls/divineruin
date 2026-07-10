# Phase 11: World Simulation Loop (Living World)

> **Source docs:** `docs/world_data_simulation.md` §World Simulation Rules (L620-806) — canonical layer definitions; `docs/technical_architecture.md` §Agent Layer (L1072-1118, god-agent heartbeat pattern + background world simulation) and §DM Agent Architecture (L452-754, background process / warm layer / event bus consumption side); `docs/game_mechanics/economy/merchant_inventory_restock.md` (dawn restock, Decision 88); `docs/game_mechanics/economy/supply_demand_engine.md` §Simulation Tick Integration (event lifecycle on the 10-min tick); `docs/game_mechanics/game_mechanics_combat.md` L1044-1060 (gathering-node respawn cadences); `docs/game_mechanics/game_mechanics_patrons.md` (god personalities for heartbeat escalation).
>
> **Tracker mapping:** Supersedes the single tracker entry **M21 — World Simulation Loop**. That entry's own design_details said "likely spans multiple sprints or its own phase" — this is that phase. Replace M21 with a pointer to this file or renumber its slices M21.a-f to mirror M11.1-M11.6 (naming call at sprint-start).
>
> **Dependency note:** Depends on Phase 1 (core resolution), Phase 6 M6.1 (NPC schema + schedules), Phase 9 M9.6/M9.7 (restock + supply/demand specs), and the M16 pure gathering-respawn resolver (this phase is its first live caller). Phase 8 (patron profiles) must exist before M11.6. Nothing downstream blocks on this phase except the "living world between sessions" experience itself — but that experience is the product's core differentiator, so this phase is on the critical path to playtest.
>
> **Phase 12 coupling:** Phase 12 (Story & Content Architecture, `12_story_content.md`) authors content *for* this machinery and amends three milestones here — event scoping + campaign gates + drift clamps (M11.4), scope routing + reband authorization (M11.5), agenda-driven context + tier validation (M11.6). Amendments are inlined below tagged **[P12]**. Phase 12's M12.1 (event scope field) should ship *with* M11.4/M11.5, not after — retrofitting scope onto a live event system is avoidable work.

Builds the server-side world life-loop the design prescribes but the Phase 0-10 roadmap never homed: the real-time 1:1 world clock plus the four simulation layers — per-minute time-driven state (Layer 1), the 10-minute simulation/economy tick (Layer 2), the god-agent heartbeat (Layer 3), and the event-driven cascade engine (Layer 4). This is the harness that ticks the world forward between and during sessions: NPC schedules, corruption drift, disposition decay, weather, merchant restock, gathering-node respawn, supply/demand event lifecycle, god actions, and effect cascades routed to active sessions via the event bus. The per-session background process (already BUILT) is the *consumer* of everything this phase *emits*.

---

## Blocking design decisions (resolve before or at M11.1 sprint-start)

These are surfaced here rather than buried in milestones because each one changes schema or process shape.

**D-A — World-clock timezone anchor.** The spec makes two promises that conflict in multiplayer: (1) a single canonical clock (`world-clock-realtime-ssot`, shared `region_state`/`npc_state` with no per-player dimension) and (2) "players who play in the evening experience nighttime gameplay." Both cannot hold for players across timezones. Options:
- *(a) Global UTC-anchored clock with a fixed "Aethos Standard Time" offset* chosen so the launch audience's evening ≈ in-game night. MMO-correct, zero migration cost, circadian promise degrades gracefully for distant timezones. **Recommended.**
- *(b) Per-player clock offset in Phase 1* (each single-player world runs on the player's local time), collapse to shared clock at Phase 2. Honors the circadian promise now, but shared world-state tables (`npc_state`, `region_state`) would carry per-player forks or per-player time math — expensive retrofit, violates the SSOT decision.
- *(c) Regional sharding* — Phase 3 territory, premature.
Record the choice as a numbered game-design decision (it changes what players experience), not just a named implementation decision.

**D-B — Restock layer ownership reconciliation.** `merchant_inventory_restock.md` L239 + L517 assign the dawn restock to "simulation tick layer 1 (time-driven)." Layer 1 per `world_data_simulation.md` L644 is deterministic and does *no DB reads beyond the clock*; restock does DB writes and rolls randomness — it categorically cannot live in Layer 1. Resolution: restock runs in **Layer 2**, gated on a dawn-crossing check (`crossed_dawn(last_tick_game_time, now_game_time)`), preserving Decision 88's once-per-day-at-dawn player-facing behavior exactly. Spec doc needs a two-line amendment (add to Phase 0-style doc-updates backlog); Decision 88 gets a one-line amendment recording the layer correction.

**D-C — Tick worker placement (his draft's "server-vs-agent TBD").** Recommendation: **Python worker in `apps/agent/`, deployed as its own single-instance process** (sibling to the existing async-activity worker, reusing its `db_mutations.py` asyncpg plumbing and `POLL_INTERVAL` pattern). Reasoning: Layer 2 calls rules-engine pure functions (corruption formula, M16 respawn resolver) that are Python; Layer 3 needs the LLM plumbing that is Python; the Bun/TS server has neither. The TS server's only claim was "it's the always-on process" — a dedicated worker deployment answers that without splitting the sim across languages. Confirm at sprint-start; record as named decision `world-loop-worker-placement`.

**D-D — Catch-up semantics after worker downtime.** "Always running" meets reality: deploys, crashes, maintenance. Policy: Layer 1 needs no replay (state is computable from the clock — recompute on resume). Layer 2 runs **one consolidated catch-up tick** with elapsed-time-scaled deltas (corruption drift × elapsed ticks, disposition decay × elapsed in-game days, each missed dawn = one restock cycle, expired supply/demand events resolved) — never N replayed ticks. Layer 3 heartbeats simply resume (gods don't backfill decisions; the world state they read already reflects the catch-up tick). Record as named decision `world-loop-catchup-consolidated`.

**D-E — God heartbeat LLM budget governor.** The spec caps nothing: 10 gods × a 15-30-min heartbeat × 24/7 = 480-960 heartbeats/day *per world*, before Phase 1 has revenue to cover it. Policy: rule-based passes always run (cheap, no LLM); **LLM escalation is gated on relevance** — a complex case escalates only if (a) a player has been active in that god's domain within a trailing window (e.g., 48h), or (b) the case is flagged dramatic (domain under serious threat). Hard daily cap per god with overflow logged for review. The cost model gets a new line item either way. Record as named decision `god-heartbeat-llm-governor`; the specific window/cap numbers are tuning values, not locked.

**Decisions-log numbering:** the project-knowledge copy of `game_mechanics_decisions.md` ends at 128; terrain work locked 129-132 in the repo. Any numbered decision from this phase must verify the repo's current max first (standing practice after the split-file incident).

---

## Milestone Coverage Summary

| Milestone | Scope | Depends on | Spec source |
| --- | --- | --- | --- |
| M11.1 — World Clock (SSOT) | Wall-clock → game-time pure module, epoch, calendar, dawn/dusk periods | D-A resolved | world_data_simulation §World Clock |
| M11.2 — Tick Harness & Ops | Single-instance scheduler, watermarks, idempotency, catch-up, metrics | M11.1, D-C, D-D | (new — implied, never specified) |
| M11.3 — Layer 1: Time-Driven State | NPC schedules, lighting/atmosphere overlays, shop status, patrols; Redis write-through | M11.1, M11.2 | world_data_simulation §Layer 1 |
| M11.4 — Layer 2: Simulation & Economy Tick | Corruption drift, faction influence, disposition decay, weather, restock, node respawn (M16 first caller), supply/demand lifecycle, event evaluation (depth-0, scoped); [P12] drift clamp, campaign gates, delve respawn, contract boards | M11.2, M11.3 (dawn edge), M9.6/M9.7 specs, M16, D-B; P12 M12.1 | world_data_simulation §Layer 2 |
| M11.5 — Layer 4: Cascade Engine & Event Routing | ≤3-level cascade, atomic per tick, alphabetical order, world_events_log, cross-session event-bus routing; [P12] scope metadata, reband authorization | M11.4 | world_data_simulation §Layer 4 |
| M11.6 — Layer 3: God-Agent Heartbeat | Per-god evaluation, rule/LLM split, Hollow-as-actor, contested regions (deterministic arbitration), world_effects emission; [P12] agenda-versioned context, tier validation | M11.4, M11.5, Phase 8, D-E; P12 M12.5 agendas | world_data_simulation §Layer 3, tech_arch §Agent Layer |

Sequencing rationale: the first shippable slice is **M11.1 + M11.2 + the economy portion of M11.4** — exactly the draft milestone's "clock + Layer-2 economy tick that lights up M16." Cascades (M11.5) land before event firing becomes real; until then M11.4's event evaluation applies effects at depth-0 with would-be cascades logged. Gods (M11.6) come last because they emit *into* the cascade engine and read state the earlier layers maintain. Layer numbering (1-4) is the spec's taxonomy; milestone order is dependency order — they intentionally differ.

---

### Milestone 11.1 — World Clock (Single Source of Truth)

**Goal:** One canonical real-time world clock (1 game-minute = 1 real minute, always advancing) that every other system derives time from. No parallel in-game-day counter anywhere — day number, season, time-of-day period, and schedule state are all pure functions of wall-clock time plus one epoch constant.

**Inputs:** Decision D-A (timezone anchor) resolved.

**Deliverables:**
- `world_clock.py` module of pure functions (no DB, no I/O): `game_time(wall_now) -> GameTime`, `time_of_day_period(game_time) -> dawn|morning|afternoon|dusk|night`, `game_day_number(game_time) -> int`, `season(game_time)`, `crossed_boundary(prev, now, boundary) -> bool` (generic edge detector used for dawn restock, dusk lighting, etc.)
- World epoch constant (the wall-clock instant that is Day 1, 00:00 Aethos time) stored as configuration + a `world_flags` row, never recomputed
- Schedule evaluation helper: `location_for_schedule(schedule: dict, game_time) -> location_id` and `is_open(schedule, game_time) -> bool` against the NPC `schedule` field format (`"06:00-20:00": "wailing_market"`)
- Period boundary table (dawn = 06:00 per Decision 88's restock anchor; remaining boundaries proposed at implementation, recorded as tuning values)
- Both Python (agent/worker) and TS (server/client) can derive game time: publish epoch + offset via config/API so the client HUD clock needs no round-trip

**Acceptance criteria:**
- [ ] `game_time` is bijective with wall-clock time; no state beyond the epoch constant
- [ ] Day number, season, and period are consistent across Python and TS derivations for the same instant
- [ ] `crossed_boundary` correctly detects exactly-one crossing per boundary per day, including across DST transitions in the host timezone (clock is anchored to a fixed offset — DST must not double- or skip-fire dawn)
- [ ] Schedule helper handles overnight ranges (`20:00-06:00`) and gaps
- [ ] No other module defines or persists an independent day counter (grep-verifiable)
- [ ] Tests cover epoch math, period boundaries, overnight schedules, DST edges

**Key references:** *World Data & Simulation — The World Clock (L628-634)*; decision `world-clock-realtime-ssot`; Decision 88 (dawn anchor).

---

### Milestone 11.2 — Tick Harness & Operations

**Goal:** The always-running scheduler process that drives Layers 1-3 at their cadences, survives restarts sanely, and never double-runs. This is unglamorous and it is the hard part — the spec describes the layers but never the harness.

**Inputs:** M11.1; decisions D-C (placement) and D-D (catch-up) resolved.

**Deliverables:**
- Standalone worker process (per D-C: `apps/agent/world_loop_worker.py`, own deployment unit, sibling to the async-activity worker)
- Single-instance guarantee: PostgreSQL advisory lock (or equivalent) so a second instance idles instead of double-ticking
- Tick registry with cadences: Layer 1 (every game-minute), Layer 2 (every 10 min), Layer 3 (per-god, staggered 15-30 min so 10 gods don't heartbeat simultaneously)
- `world_tick_watermarks` table: per-layer `last_completed_tick` (game-time + wall-time), written transactionally with each tick's effects — this is the idempotency anchor
- Consolidated catch-up on startup (per D-D): compute elapsed since watermark, run one scaled Layer-2 catch-up, recompute Layer-1 state, resume Layer-3 schedule; log a catch-up summary
- Per-tick error isolation: one failing sub-job (e.g., weather) logs and continues; the tick's watermark advances only for completed sub-jobs (sub-job-level watermarks or a completed-jobs bitmap — implementation's choice, recorded)
- Observability: tick duration, tick lag (scheduled vs actual), sub-job failure counts, catch-up events — structured logs at minimum, metrics if the deploy stack has them
- Graceful shutdown: finish the in-flight tick, release the lock

**Acceptance criteria:**
- [ ] Two concurrent worker instances: exactly one ticks; the other waits and takes over on lock release
- [ ] Kill the worker mid-tick, restart: no double-application of the interrupted tick's completed sub-jobs, incomplete sub-jobs re-run
- [ ] Simulated 3-hour downtime: exactly one consolidated catch-up tick runs; deltas match elapsed time (drift × 18, one dawn restock if dawn was crossed, decayed dispositions scaled by elapsed in-game days)
- [ ] Layer-3 stagger: no two god heartbeats scheduled within the same minute by default
- [ ] Sub-job exception does not abort the tick or corrupt the watermark
- [ ] Tests cover lock contention, watermark idempotency, catch-up scaling, mid-tick crash recovery

**Key references:** draft milestone constraints (single-instance, placement); existing async-worker claim/revert pattern (`apps/agent/async_worker_claim.py`, `docs/runbooks/async-activity-reset.md`) as the in-repo precedent for claim semantics and operator runbooks — ship a matching runbook for stuck/lagging world ticks.

---

### Milestone 11.3 — Layer 1: Time-Driven Deterministic State

**Goal:** Every-game-minute state that is purely computable from the clock: NPC positions from schedules, time-of-day condition overlays on locations, shop open/closed, guard patrol positions. Deterministic — given the time, the state; no randomness, no DB reads beyond content loaded at startup.

**Inputs:** M11.1, M11.2; Phase 6 NPC schema (schedules populated).

**Deliverables:**
- Startup content load: all NPC schedules + all location `conditions` keyed on time (`time_night` etc.) into worker memory; content-change refresh hook (poll content-version or SIGHUP-style reload — cheapest viable)
- Per-minute pass: recompute `npc_state.current_location` for schedule-driven NPCs; write-through to Redis `npc:{npc_id}:location` (60s TTL per spec); write PostgreSQL `npc_state` only on change, not per minute
- Location state computation: base + active time conditions → Redis `location:{location_id}:state` (60s TTL); danger-level and atmosphere overlays applied per the `conditions` schema
- Shop status derivation (open/closed) exposed in computed location state
- Guard patrol deterministic rotation (position = f(route, game_time))
- Boundary-edge event emission: on period transitions (dawn/dusk/night), publish a `time_period_changed` event to the event bus so active sessions' background processes rebuild warm layers (the lighting change the player *hears* narrated)
- Dawn-edge signal consumed by M11.4's restock gate (per D-B, Layer 1 detects, Layer 2 acts)

**Acceptance criteria:**
- [ ] Given a fixed game time, NPC locations and location states are identical across runs (determinism)
- [ ] Maren Thell is at `wailing_market` 06:00-20:00 and `maren_house` otherwise; overnight-range NPCs resolve correctly
- [ ] `time_night` condition overlay applies/removes `description_override`, `npcs_remove`, `danger_level` exactly per the location schema
- [ ] Redis keys refresh within TTL; PostgreSQL `npc_state` writes occur only on location change
- [ ] `time_period_changed` events reach the event bus once per boundary (no per-minute spam)
- [ ] Per-minute pass completes well under one second at MVP content scale (~20 locations, ~25 NPCs) with headroom measured

**Key references:** *World Data & Simulation — Layer 1 (L635-644)*; location/NPC schemas (L29-160); Redis cache table (L858-872).

---

### Milestone 11.4 — Layer 2: Simulation & Economy Tick

**Goal:** The 10-minute tick that evolves slow world variables and runs the economy. This milestone is the phase's first player-visible payoff and the draft milestone's "first slice" target: nodes respawn, merchants restock, prices move, corruption creeps.

**Inputs:** M11.2, M11.3 (dawn edge); M16 pure respawn resolver; Phase 9 M9.6/M9.7 specs; D-B, D-D resolved.

**Deliverables:**
- **Corruption drift:** the spec formula verbatim (`base_drift − god_suppression + hollow_pressure + event_modifier`, clamped 0-10) per region; god influence terms read from `god_agent_state` (zeros until M11.6 populates them — formula ships complete, inputs arrive later)
- **Faction influence adjustments:** `world_state.current_strength` shifts from territory changes + recent `world_events_log` entries
- **NPC disposition decay:** per-player dispositions drift toward `default_disposition` at ~1 pt per in-game day (minor NPCs; slower for major — tier-scaled rate table), scaled correctly in catch-up ticks
- **Weather progression:** per-region probabilistic advance along season-appropriate patterns; feeds location `conditions`
- **Economy tick:**
  - Merchant restock, dawn-gated via `crossed_dawn` (per D-B): the full M9.6 `daily_restock_at_dawn` flow — tier-2 pool refresh, tier-3 probability/rotation checks, settlement modifiers, gold-pool reset, event-modified quantities
  - Gathering-node respawn: **first live caller of M16's pure resolver** — per-node cadence (ore 1-3d, herb 1-2d, crystal 3-7d, timber 7+d, salvage never) with depleted-at timestamps against game time
  - Supply/demand event lifecycle per M9.7 §Simulation Tick Integration: onset → peak → resolution phase transitions, `value_modifiers` recompute, expired-event cleanup
- **Event evaluation:** after all state updates, evaluate `events` whose triggers now match; roll `probability`, check `cooldown`/`max_occurrences`; fire eligible events. Until M11.5 lands, effects apply **depth-0** (direct effects only) and would-be cascades are logged — swap to the cascade engine in M11.5 with no other change
- **[P12] Scoped occurrence tracking:** evaluation consumes the `scope: per_player | per_world` field + `world_id` dimension (Phase 12 D-F / M12.1); `cooldown` and `max_occurrences` evaluate within scope
- **[P12] Drift clamp (D-H):** corruption drift and any ambient effect are clamped to the region's `level_band` intra-band range; band-crossing changes are rejected with a review-log entry — only a campaign-director beat carrying `reband` authorization crosses a boundary
- **[P12] Campaign-gate evaluation sub-job:** each tick, evaluate dormant campaign beats' gates (progress + time floor / time ceiling per D-I) against `campaign_state` + the world clock; arm/fire via the director (M12.3 owns beat semantics; this tick is just the pulse)
- **[P12] Economy-tick additions:** delve-site respawn with seed regeneration on respawn (M12.4 lifecycle, M16-resolver pattern); contract-board refresh on the same dawn edge as merchant restock
- All writes: PostgreSQL as SSOT, Redis write-through per the cache table, changes published to the event bus

**Acceptance criteria:**
- [ ] Corruption formula matches spec math; clamping verified at both bounds; catch-up tick scales drift by elapsed ticks
- [ ] Disposition decay reaches (never overshoots) `default_disposition`; major-NPC rate slower than minor
- [ ] Exactly one restock per in-game day per merchant, at the tick following dawn; downtime spanning dawn still yields exactly one
- [ ] A depleted ore node respawns within its 1-3-day window and not before; salvage sites never respawn; M16 resolver invoked (not reimplemented)
- [ ] A supply/demand event walks onset → peak → resolution across ticks with correct price-modifier values at each phase
- [ ] Event evaluation respects probability, cooldown, and max_occurrences; fired events land in `world_events_log`
- [ ] [P12] A `per_world` max_occurrences=1 event fires once per world; the `per_player` equivalent fires once per player; cooldowns isolate per scope
- [ ] [P12] Max ambient drift over 30 in-game days never crosses a band boundary (property test); a rejected band-crossing attempt is review-logged
- [ ] [P12] Gate-evaluation sub-job arms a beat on progress+floor and fires on ceiling (director integration smoke test; full paths in M12.3)
- [ ] [P12] Depleted delve site respawns on cadence with a regenerated seed; contract board refreshes exactly once per dawn
- [ ] Full Layer-2 tick at MVP content scale completes in single-digit seconds with timing logged

**Key references:** *World Data & Simulation — Layer 2 (L646-683)*, *Simulation tick query pattern (L896-906)*; *Merchant Inventory & Restock* (Decisions 88-89, `daily_restock_at_dawn`); *Supply & Demand Engine — Simulation Tick Integration (L486+)*; *Game Mechanics Combat L1044-1060* (node cadences); Decision 71 (node deplete/respawn rhythm).

---

### Milestone 11.5 — Layer 4: Cascade Engine & Event Routing

**Goal:** The ripple engine: when a `world_effect` fires — from player actions, tick results, or god decisions — resolve its consequences up to 3 levels deep, atomically, deterministically, then route the settled outcome to affected sessions.

**Inputs:** M11.4 (event evaluation is the primary in-loop caller; player-action mutation tools are the in-session caller).

**Deliverables:**
- Cascade resolver: level 0 (original effect) → evaluate all dependent events/conditions → level 1 → level 2 → level 3 (applies, does **not** cascade further); would-be level-4+ effects logged for content review
- Determinism rules per spec: each level resolves completely before the next; same-level effects apply in alphabetical effect-id order; contradictory same-level effects last-write-wins with a review log entry
- Atomicity: the full cascade applies within a single transaction (or a claim-marked unit consistent with worker patterns); no player-facing notification until the cascade settles — players see final state only
- `world_events_log` entries for every fired effect with cascade lineage (triggering event id, level) for debugging and content review
- Event-bus routing: settled effects published with region/location/player scoping so each active session's background process can filter relevance (the consumption side — warm-layer rebuild + proactive-speech classification — is BUILT; this delivers the emit contract it consumes)
- Cross-player routing shape (Phase 2-ready, Phase 1-exercised): effects carry affected-scope metadata; in Phase 1 the "other player" case simply has one subscriber
- **[P12]** Routing metadata carries the event `scope`/`world_id` (D-F); effects support a `reband` authorization flag honored only when the originating effect is a campaign-director beat — reband from any other source is rejected at the M11.4 clamp
- Callable from both contexts: the Layer-2 tick (in-worker) and mutation tools (in-session, e.g., "bandit_leader_killed" fired by a kill during play)

**Acceptance criteria:**
- [ ] The spec's worked example reproduces: `bandit_leader_killed` → threat cleared + caravans resume (L1) → prices drop + guild disposition +2 (L2) → L3 applies, L4 candidates logged, never applied
- [ ] Same-level ordering is alphabetical by effect id; reordering input order does not change outcomes
- [ ] Contradictory same-level effects: last write wins, review entry logged
- [ ] Mid-cascade failure rolls back the entire cascade; no partial state visible
- [ ] No event-bus publication until cascade settlement; scoped routing metadata present on every publication
- [ ] Cascade lineage reconstructable from `world_events_log` alone
- [ ] [P12] Publications carry scope/world_id; a director beat with `reband` crosses a band boundary while the identical non-director effect is rejected
- [ ] M11.4's depth-0 shim replaced; its event-evaluation tests pass unchanged with cascades live

**Key references:** *World Data & Simulation — Layer 4 / The Cascade Engine (L762-808)*; *Technical Architecture — Background Process (event bus consumption, proactive speech priority)*.

---

### Milestone 11.6 — Layer 3: God-Agent Heartbeat

**Goal:** The ten gods (plus the Hollow as an eleventh mechanical actor) periodically evaluate the world through their domains and act — the macro-narrative engine that makes the world feel authored while players sleep.

**Inputs:** M11.4 (state to read), M11.5 (world_effects emission path), Phase 8 (god profiles/personalities), D-E (LLM governor) resolved.

**Deliverables:**
- Per-god heartbeat job (staggered by M11.2): read domain state (region corruption/influence in territory, relevant `world_events_log` entries since last heartbeat, aligned/violating player actions, other gods' recent contesting actions)
- **Rule-based fast path (no LLM):** the spec's simple cases — corruption rising in territory → ward strength up; unchallenged influence → maintain; aligned quest completed → small blessing. Encoded per-god as rules referencing Phase 8 domain definitions. **→ M24 pointer:** the full-spec Veil Ward is scope-owned and duration-bound — model in `docs/game_mechanics/veil_ward_scope_model.md`. The **world-sim half — ambient territory Resonance, corruption-driven ward strength, seasonal escalation, and Sacred-site permanent world wards — rides Phase 11**, building on the M24 scope-model core. M24 defines a `sacred_site` entry in `WARD_SOURCES` and a `veil_wards` row with `expires_at IS NULL` (permanent) but **populates none**; this phase supplies the world entities. The "ward strength up" rule here is one such consumer. Note M24 needs no tick loop (location-ward expiry is a lazy `NOW()` compare); the tick this phase builds is for **proactive** ward events, and is the same tick `compute_node_respawn` awaits.
- **LLM escalation path:** complex cases (two gods contesting a region, unusual prayer, significant world event, domain under serious threat) built on the god's Phase 8 personality profile; governed by D-E (relevance gating + daily per-god cap + overflow log). Routine escalations use the smaller/faster model; dramatic moments may use the capable model per tech-arch guidance
- **[P12] Agenda-driven context:** escalation prompts are built from the god's **season agenda version in force** (M12.5 — Knows/Believes/Wrong-about is the epistemic state; withheld truths enter only via director beat injections per D-J). Phase 8 profiles supply personality; agendas supply knowledge and constraints
- **[P12] Tier validation at the emitter:** Tier A passes; Tier B magnitude-clamped (D-H) + budget-checked (D-E); Tier C requires an authored playbook reference — unlisted Tier C effects rejected and logged (D-K). Contested regions resolve by deterministic influence arbitration; the LLM colors narration only
- world_effects emission through M11.5: influence strengthen/weaken, omens (event triggers near players), location bless/curse (condition modifications), prayer responses (player-scoped proactive events), contest actions (tension events)
- `god_agent_state` persistence: current focus, recent-decisions ring buffer (consistency memory for future heartbeats and for the DM's warm layer), influence map
- **The Hollow as actor:** heartbeat probing weak points (low divine protection, recent trauma sites, Hollowmere-border proximity, tainted-artifact use) and applying `hollow_pressure` — the term the M11.4 corruption formula already consumes
- Contested-region tracking: competing influence values, dominant/contested flags, tension level — surfaced to `region_state` so the warm layer narrates unease
- Player-relevant effects flow the existing route: event bus → session background process → priority classification → proactive speech or prompt update (BUILT; verify end-to-end)

**Acceptance criteria:**
- [ ] Simple cases resolve with zero LLM calls (assertable in tests via call-count instrumentation)
- [ ] LLM escalation respects the D-E governor: no player activity in domain + no dramatic flag → no call; daily cap enforced with overflow logged
- [ ] A god's decision references its own recent-decisions buffer (a god does not contradict last heartbeat's stance without a state change)
- [ ] Hollow pressure raises corruption in an unprotected region across successive Layer-2 ticks; a protective god's suppression measurably counteracts it (the macro tension loop closes)
- [ ] Contested region produces correct dominant/contested/tension values per the spec's JSON shape; [P12] resolution is deterministic given identical influence state (LLM varies narration only)
- [ ] [P12] Heartbeat context contains exactly the agenda-version-in-force; bumping the version changes the god's response to the same stimulus
- [ ] [P12] Unlisted Tier C effect rejected + logged; playbook-listed equivalent passes; Tier B band-crossing rejected per D-H
- [ ] A prayer-response effect reaches an active session as proactive speech; an omen reaches it as a prompt update (priority classification verified)
- [ ] Cost instrumentation: LLM calls per god per day logged; a 24h soak at MVP scale lands within the D-E budget

**Key references:** *World Data & Simulation — Layer 3 (L685-761)*; *Technical Architecture — Agent Layer, Tier 4 God-Agents (L1090-1110)*; *Game Mechanics Patrons* (personality sources); *Cost Model* (new heartbeat line item).

---

## Decision log (this phase)

- **`world-clock-timezone-anchor`** (D-A — to be numbered in `game_mechanics_decisions.md` after verifying repo max, currently ≥132): recommended option (a), global fixed-offset Aethos Standard Time. Player-facing consequence: circadian alignment is strongest near the anchor timezone.
- **`restock-layer-2-dawn-gated`** (D-B, named): restock executes in Layer 2 gated on dawn-crossing; `merchant_inventory_restock.md` L239/L517 amended; Decision 88 gets a one-line layer correction. Player-facing behavior unchanged.
- **`world-loop-worker-placement`** (D-C, named): Python single-instance worker in `apps/agent/`, own deployment unit. Rationale: rules-engine pure functions and LLM plumbing are Python.
- **`world-loop-catchup-consolidated`** (D-D, named): one scaled catch-up tick after downtime; Layer 1 recomputes; Layer 3 resumes without backfill.
- **`god-heartbeat-llm-governor`** (D-E, named): rule pass always; LLM escalation gated on domain relevance or dramatic flag; daily per-god cap. Window/cap values are tuning, not locked.
- **`world-sim-loop-milestone`** (inherited from tracker): the loop is homed here as Phase 11; tracker M21 superseded.

## Cross-cutting follow-ups

- **Doc amendments (route to the Phase-0-style doc-updates backlog):** `merchant_inventory_restock.md` layer correction (D-B); `world_data_simulation.md` gains a short "Tick Harness & Catch-up" subsection under §World Simulation Rules (D-C/D-D — the spec currently describes layers with no process model); Cost Model gains the god-heartbeat line item (D-E); INDEX.md milestones table gains the `11_world_loop.md` row.
- **`game_mechanics_decisions.md` sync:** project-knowledge copy is stale at 128 vs repo ≥132; re-add after this phase's numbered decision lands (existing pending-housekeeping item).
- **Seasonal content hook:** `season(game_time)` (M11.1) is the natural anchor for the deferred seasonal-content LOW item — note the insertion point, build nothing.
- **Phase 2 multiplayer:** cross-player cascade routing (M11.5) ships the scoping metadata now so multiplayer adds subscribers, not schema. Multiplayer conversation-awareness (existing LOW item) consumes the same bus.
- **Phase 12 integration:** the [P12]-tagged items above originate in `12_story_content.md` (D-F through D-L). Sequence M12.1 (event scope) with M11.4/M11.5; M12.5 agendas must exist before M11.6's LLM path goes live against real players — the rule-based fast path can ship without them.
- **Playtest tuning surface:** drift rates, decay rates, heartbeat intervals, governor caps, and period boundaries are all tuning values — keep them in one config surface, not scattered constants, so playtest iteration doesn't require code changes.
