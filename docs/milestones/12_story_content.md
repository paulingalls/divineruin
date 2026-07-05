# Phase 12: Story & Content Architecture (Living Narrative)

> **Source docs:** `docs/game_design_doc.md` §Seasonal Arc Structure (L1187-1211) + §The Slow Burn + §Collective Discovery; `docs/aethos_lore.md` (the Wellspring mystery, Preservationists vs. Reclaimers, per-god personalities, Hollow expressions); `docs/mvp_spec.md` §The Greyvale Anomaly (the arc pattern this generalizes); `docs/world_data_simulation.md` (event schema, tier 1/2 content model, on-demand generation, dm_instructions style); `docs/game_mechanics/game_mechanics_bestiary.md` (regional catalogs — band-assignment input); `docs/game_mechanics/economy/` M9.3/M9.4 (reward tables delve rewards plug into); `11_world_loop.md` (the machinery this phase authors content *for*).
>
> **Dependency note:** Depends on Phase 11 (campaign gates evaluate on the Layer-2 tick; delve respawn rides M11.4; agendas feed M11.6; beats fire through M11.5 cascades). Phase 11 requires three small amendments from this phase — see §Phase 11 Amendments. Machinery milestones (M12.1-M12.5, M12.7) can largely parallel Phase 11 development; M12.6 (Season 1 content) needs the machinery shapes stable.
>
> **What this phase is:** the system that turns the world loop from a simulation into a *story*. Phase 11 makes the world move; Phase 12 decides what it moves toward. It homes four things the roadmap never did: the campaign director (who advances the story), the content taxonomy (what kinds of content exist and how each is scoped), the repeatable-content engine (what grinding feels like in a voice game), and god season agendas (how ten autonomous agents add color without running the story off the road).

**Core stance (locked this session):** the seasonal arc is human-authored and machine-gated, not emergent. Gods are actors inside an authored spine — they improvise texture, never plot. Autonomy is the *feel*; the authored spine is the *reality*. This is a deliberate narrowing of the tech-arch's original OpenClaw framing, accepted knowingly: color and presence, not agency over canon.

---

## Content taxonomy (the vocabulary everything below uses)

| Class | Scope | Repeats? | Examples | Pipeline |
|---|---|---|---|---|
| **Systemic repeatables** | per-player | infinitely | delves, contracts, bounties, gathering | generated from templates (M12.4) |
| **Leveling spine** | per-player | once per player | Greyvale Anomaly-style quest arcs | authored tier-1 + generated tier-2 |
| **World beats** | per-world | once, canonical | Ashmark expansion, the Reveal | authored, director-fired (M12.3) |
| **God texture** | per-world, transient | continuous | omens, blessings, contested-region unease | M11.6 heartbeats under M12.5 agendas |

**Seasons are weather; the leveling spine is the road.** World beats recolor the world every player moves through; they never replace level-gated personal content. A level-4 player in Season 2 plays level-4 content colored by Season 2. This decoupling is what makes the time-ceiling gate (below) dramatically correct instead of punishing.

---

## Blocking design decisions (resolve before or at M12.1 sprint-start)

**D-F — Event scope field.** The `events` schema gains `scope: per_player | per_world` (+ `world_id` dimension on occurrence tracking). `max_occurrences` and `cooldown` evaluate within scope. Phase 11 M11.4/M11.5 consume this — the one schema change that can't wait. In Phase 1, `world_id` is per-player-world; Phase 2 collapses to shared worlds by parameter, not redesign (same pattern as the clock and campaign-gate decisions).

**D-G — Static zone banding via protection gradient.** The world does not level-scale. Regions carry fixed level bands, and the *fiction* for the gradient is protection, not monsters: safety is actively held (wards, patrols, garrisons) and danger scales with distance from protection. This reuses Phase 11 machinery literally — ward strength and god influence are the suppression terms in the corruption formula; the fiction and the simulation are the same system. Non-Hollow danger sources (bandit reaches, contested faction territory, deep mines, ancient ruins) keep 20 levels from being a monotonic corruption slog. Numbered game-design decision.

**D-H — Drift cannot re-band.** Ambient simulation (corruption drift, god Tier-B actions) may move a zone's danger *within* its band range only; crossing a band boundary is a story event reserved to the campaign director as an authored beat. Without this clamp the simulation eventually strands a low-level player's local map. Enforced in code (M11.4 clamp + M11.6 effect validation), not convention. Numbered decision.

**D-I — Hybrid campaign gates: progress-primary, time floor + time ceiling.** A beat arms when (player/population progress threshold met AND time floor elapsed) OR time ceiling elapsed. Floor prevents speedrunning the reveal; ceiling prevents the story petering out; ceiling-fires are on-tone (the Hollow doesn't wait). Phase 1: progress = the single player of that world. Phase 2: percentage-based over recently-active players ("X% of 30-day-actives ≥ level Y") — never absolute counts. Numbered decision.

**D-J — Season-versioned god knowledge.** An LLM cannot keep a secret it knows; therefore gods *do not know their own secrets* until the season that needs them. Agenda docs define per-season epistemic state (Knows/Believes/Wrong-about); withheld truths live only in director beat content and enter a god's context when the relevant beat arms. Gods are explicitly barred from inventing specifics inside their blind spots (anti-confabulation clause). Numbered decision — this is the load-bearing wall of the slow burn.

**D-K — God action tiers with playbook-only Tier C.** Tier A (ambient texture: omens, whispers, small blessings) — free, mostly rule-based. Tier B (regional: ward strength, spawn pressure, bless/curse, faction nudges) — magnitude-clamped per D-H, budgeted per D-E governor. Tier C (anything touching campaign state, canon, or public inter-god conflict) — the heartbeat LLM **chooses from an authored playbook menu; it never writes the menu.** Emitter-side validation rejects and logs unlisted Tier C effects. Numbered decision.

**D-L — Repeatables sit below spine XP-efficiency.** Delves/contracts are reliable and always available but slightly less XP-efficient than the leveling spine, so the authored story is never the suboptimal path. Real-time respawn cadences are the farm cap — no daily caps or diminishing-returns mechanics needed. Numbered decision (tuning value: the efficiency gap %, not the principle).

**Numbering note:** verify current repo max in `game_mechanics_decisions.md` (≥132 after terrain) before assigning numbers to D-F through D-L.

---

## Milestone Coverage Summary

| Milestone | Scope | Depends on |
|---|---|---|
| M12.1 — Content Taxonomy & Event Scoping | scope field, per-world occurrence tracking, taxonomy encoded | D-F; feeds Phase 11 M11.4/M11.5 |
| M12.2 — Zone Banding & Protection Gradient | region band map, bestiary band pass, drift clamps, discovery gating | D-G, D-H; Phase 7 bestiary |
| M12.3 — Campaign Director | campaign_state, beat schema, hybrid gates, arming/firing, rehearsal | D-I; M12.1; M11.2/M11.4/M11.5 |
| M12.4 — Delve & Contract Generator | site templates, complication tables, delve DM posture, lifecycle, boards | D-L; M12.2 bands; M11.4 tick; M16 pattern |
| M12.5 — God Season Agendas & Action Tiers | agenda schema, versioned knowledge injection, tier validation, arbitration, Hollow agenda | D-J, D-K; M11.6; Phase 8 |
| M12.6 — Season 1 Content Pass | authored beats, 10+1 agendas, Tells, complications, band-appropriate spine coverage | all machinery above |
| M12.7 — Content Ops & Telemetry | beat rehearsal env, content calendar, volume math, live metrics | M12.3, M12.4 |

---

### Milestone 12.1 — Content Taxonomy & Event Scoping

**Goal:** Encode the four content classes and make event scope first-class, so per-player and per-world content stop sharing one ambiguous occurrence model.

**Deliverables:**
- `events` schema: `scope` field; occurrence tracking keyed `(event_id, world_id)` for per_world and `(event_id, player_id)` for per_player; `cooldown`/`max_occurrences` evaluate within scope
- `world_id` concept introduced: Phase 1, one world per player; Phase 2, shared — all queries written world-scoped now
- Content-class tag on quests/events/encounter templates (`repeatable | spine | beat | texture`) so telemetry, reward tables, and the director can filter by class
- Migration for existing MVP events (Greyvale arc events → spine/per_player; ambient → texture)

**Acceptance criteria:**
- [ ] A per_world max_occurrences=1 event fires once per world and never again; per_player equivalent fires once per player
- [ ] Cooldowns isolate across worlds and across players per scope
- [ ] Existing Greyvale content migrated and class-tagged; no untagged content ships
- [ ] Phase 11 M11.4 evaluation + M11.5 routing consume scope without special-casing

---

### Milestone 12.2 — Zone Banding & Protection Gradient

**Goal:** A static, level-banded world map with the protection-gradient fiction wired into the simulation, and hard clamps keeping ambient drift inside bands.

**Deliverables:**
- Region band map: every region (and sub-zone where needed) assigned a level band; Greyvale = 1-5 anchors the ladder; full 1-20 ladder sketched across the lore's geography with a mix of Hollow and non-Hollow danger sources per band
- `region.level_band` + `region.protection_sources[]` schema (wards, garrisons, patrols — each mapping to suppression terms the corruption formula reads)
- Bestiary band pass: all 28 creatures assigned band ranges; regional catalogs validated against their region's band
- Drift clamps (D-H): Layer-2 corruption drift and Tier-B god effects clamped to intra-band range; band-crossing changes rejected at the effect validator with review log — only director beats carry a `reband` authorization
- Content-discovery gating: higher-band zone entrances/rumors surfaced through the Decision-71 pattern (exploration, NPC tips, companion scouting, contract escalation) so "finding level-appropriate content" is play, not a menu
- Danger telegraphing style guide (audio-first): how the DM signals "you are under-leveled for this place" before it kills you — protection thinning is *audible* (fewer patrols, ward-hum fading, wrongness creeping in)

**Acceptance criteria:**
- [ ] Every region has a band; every creature has a band range; no regional catalog contains a creature outside its region's band ± authored exceptions
- [ ] Simulated max ambient drift over 30 in-game days never crosses a band boundary (property test)
- [ ] A director beat with reband authorization crosses a boundary; the identical effect without it is rejected and logged
- [ ] Protection sources feed the corruption formula's suppression terms (fiction = simulation verified)

---

### Milestone 12.3 — Campaign Director

**Goal:** The authored-spine state machine: seasons → acts → beats, hybrid-gated, fired deterministically through the cascade engine. The single authority over canon.

**Deliverables:**
- `campaign_state` (per world): current season/act, per-beat status (`dormant | armed | fired`), gate progress metrics, agenda versions in force
- Beat schema: id, narrative content (dm_instructions style), world_effects payload (fired via M11.5, may carry `reband`), gate spec (progress conditions + time floor + time ceiling per D-I), agenda-version bumps it triggers, injection payloads (the withheld truths that enter god contexts per D-J)
- Gate evaluation as a Layer-2 sub-job (the Phase 11 amendment): each tick, evaluate dormant beats' gates against campaign_state + world clock; arm/fire accordingly
- Progress metrics: player level milestones + **Tell discoveries** (M12.5) as first-class gate inputs — the collective-discovery loop made mechanical: gods plant authored Tells → players find them → gates advance → beats fire → agendas version up
- Firing path: beat effects enter the cascade engine like any world_effect; beat narration reaches active sessions via the event bus / proactive-speech path; offline players get it via session-entry catch-up (warm layer reads campaign_state)
- Armed-beat safety: a beat fires exactly once per world (D-F scoping), transactionally with its campaign_state transition
- Rehearsal hooks (consumed by M12.7): any beat dry-runnable against a staging world with effects applied and rolled back

**Acceptance criteria:**
- [ ] Progress gate + unmet floor → dormant; progress + floor → armed/fired; ceiling alone → fired (all three paths tested)
- [ ] Beat fires exactly once per world under concurrent tick contention; campaign_state and effects commit atomically
- [ ] Tell-discovery events advance gate metrics; a gate specced on Tells arms when the threshold is hit
- [ ] Firing a beat bumps agenda versions and delivers injection payloads to the specified gods' next heartbeats
- [ ] Phase 1 single-player world walks Season 1 dormant→fired end-to-end on its own timeline
- [ ] A ceiling-fire with the population under-leveled changes world state but leaves spine level-gating untouched (weather-vs-road verified)

---

### Milestone 12.4 — Delve & Contract Generator

**Goal:** The repeatable-content engine tuned for voice: short, seeded, structurally simple, narratively varied. What grinding feels like in this game.

**Deliverables:**
- **Delve DM posture** (new behavioral mode alongside the GDD's session modes): brisk narration, minimal social, compressed transitions, 3-5 beats, 20-30 min session target — encoded in the mode's prompt directives
- Spatial model: 3-5 chambers in sequence (approach → 1-2 encounters → objective beat → exit, optionally complicated); no branching mazes; each chamber gets a distinct audio identity from the region's soundscape palette
- Seed generator: pure function over (site template, level band, creature palette from regional catalog, objective ∈ {clear, retrieve, rescue, hunt, seal}, 1-2 complications, narrative stance) → structured delve brief in dm_instructions style. Direction, not script; rules engine resolves everything
- **Complication tables — the authoring investment.** Structured entries (hook, mechanical twist, narration cues, band constraints). Target ~50 excellent entries over volume of anything else; layouts and creature mixes are cheap permutation, complications are why run twelve doesn't feel like run three
- Lifecycle (the Phase 11 rides): delve sites as discoverable/depletable/respawning nodes (Decision-71 pattern, M16-style resolver); **seed regenerates on respawn, not on entry** — mid-run persistence works, warm layer stays coherent, next visit is genuinely different. Contract boards refresh on the dawn edge alongside restock; queried by voice
- Rewards: deterministic from band + objective + complications, plugged into M9.3/M9.4 tables; XP tuned below spine efficiency per D-L
- Telemetry hooks (for M12.7): per-delve completion, duration, repeat-rate per player

**Acceptance criteria:**
- [ ] Same site, two respawn cycles → different seeds (objective/complications/stance vary); same seed → identical brief (determinism)
- [ ] Generated briefs validate: creatures within band, complications band-legal, chambers 3-5
- [ ] Delve posture measurably compresses narration in transcript tests vs standard exploration mode
- [ ] Depleted site respawns on cadence via the Layer-2 tick; mid-run departure preserves the current seed
- [ ] Contract board refreshes exactly once per dawn; posted contracts reference live sites/bounties
- [ ] Reward output matches M9.3/M9.4 tables; delve XP/hour < spine XP/hour at equal band (tuning gap recorded)

---

### Milestone 12.5 — God Season Agendas & Action Tiers

**Goal:** Gods that are felt everywhere and in control of nothing canonical: versioned knowledge, authored cracks, tiered action validation.

**Deliverables:**
- Agenda schema (one per god per season, 1-2 pages): **Knows / Believes / Wrong-about** (this section *is* the heartbeat LLM context — absent means nonexistent), **Wants** (2-3 goals), **Won't** (prohibitions + deflection behaviors + the anti-confabulation clause), **Tells** (authored cracks with placement conditions; discovery emits the gate-feeding event), **Relationships** (Preservationist/Reclaimer stances by season), **Voice anchors**
- Knowledge injection: M11.6 escalation prompts built from agenda-version-in-force; director beat payloads (M12.3) are the only path by which withheld truths enter a god's context
- Tier validation at the world_effects emitter: Tier A passes; Tier B magnitude-clamped (D-H) and budget-checked (D-E); Tier C requires a playbook reference — unlisted Tier C rejected and logged (D-K)
- Per-season Tier-C playbooks: the authored menu of story-relevant actions each god may select among
- Contested-region arbitration: influence math resolves who yields deterministically; the LLM colors narration only — one arbitration, never two dueling heartbeats
- Hollow agenda: same schema, adversarial content — Season 1 probes chaotic, Season 2 probes carry authored discoverable patterns ("Patterns Emerge" requires patterns we planted)

**Acceptance criteria:**
- [ ] Red-team transcript suite: Season-1 Veythar under direct/social-engineered questioning about the Sundering deflects per Won't behaviors and never states or *invents* specifics (confabulation checked, not just leakage)
- [ ] Beat-driven agenda version bump changes the same god's response to the same question across versions
- [ ] Tell placement conditions met → Tell surfaces; discovery event advances the M12.3 gate metric
- [ ] Unlisted Tier C effect rejected + logged; playbook-listed equivalent passes; Tier B band-crossing rejected per D-H
- [ ] Contested region resolves identically given identical influence state (determinism), with varied narration
- [ ] All heartbeat tests run within the D-E governor budget

---

### Milestone 12.6 — Season 1 Content Pass ("First Contact")

**Goal:** Fill the machinery: the actual authored Season 1. Content sprint, not code sprint — machinery shapes (M12.1-M12.5) must be stable first.

**Deliverables:**
- Season 1 beat set: the First Contact arc from the GDD table, Greyvale Anomaly integrated as the opening act; each beat with gates, effects, injections
- 11 agendas (10 gods + the Hollow), Veythar's carrying the full Won't/Tells load for the slow burn's first act
- Tell set placed across factions/regions such that no single player path surfaces the whole picture (collective-discovery spread)
- Complication tables to the ~50-entry target across the shipped band range
- Site templates + contract content for bands 1-5 (playtest range); spine coverage audit: authored+generated hours per band vs the M12.7 volume targets, gaps triaged
- Danger-telegraph content for every band-1-5 boundary zone

**Acceptance criteria:**
- [ ] Season 1 playable end-to-end in a Phase-1 world: spine + delves + texture + at least one director beat firing on progress and one on ceiling (test worlds)
- [ ] Every beat rehearsed in staging (M12.7) before arming in any real world
- [ ] Veythar red-team suite passes against the shipped Season 1 agenda
- [ ] Band 1-5 spine coverage meets volume targets or gaps are explicitly accepted

---

### Milestone 12.7 — Content Ops & Telemetry

**Goal:** The manage-it-over-time layer: one-shot canon is unforgiving, so beats get rehearsed, content gets a calendar, and the questions only players can answer get instrumented from day one.

**Deliverables:**
- Beat rehearsal environment: staging world snapshot, dry-run fire (full cascade), diff report of world-state changes, rollback; **no beat arms in production unrehearsed** (process rule, CI-enforceable via a rehearsal-stamp on the beat record)
- Content calendar: season/act timeline, beat floor/ceiling dates, agenda version schedule, authoring lead times
- Content-volume math (the existential spreadsheet): hours-to-cap target × sessions-per-level → authored-tier-1 vs generated-tier-2 budget per band; small-team viability check — thin authored spine, heavy generation is the standing strategy
- Telemetry: level distribution over time (content-gap early warning), spine-vs-delve time split, delve repeat-rate and completion-rate (the "do repeatables hold past run ten" question — a playtest answer, instrumented not assumed), Tell discovery rates (gate pacing), beat-fire mode ratio (progress vs ceiling — persistent ceiling-fires mean gates are mistuned), god LLM spend per D-E
- Live-tuning surface: gate thresholds, floors/ceilings, respawn cadences, XP-efficiency gap, governor caps — config, not code (extends the Phase 11 tuning-surface rule)

**Acceptance criteria:**
- [ ] A beat cannot arm in production without a rehearsal stamp; rehearsal diff report human-readable
- [ ] Telemetry dashboards (or minimum: structured queries) answer: where is the population, what content class holds them, are gates pacing correctly
- [ ] All listed tuning values changeable without deploy
- [ ] Volume-math doc reviewed and its per-band targets adopted by M12.6

---

## Decision log (this phase)

Numbered (game-design, verify repo max ≥132 before assigning): **D-G** static banding via protection gradient; **D-H** drift cannot re-band; **D-I** hybrid gates (progress-primary, floor + ceiling; per-world Phase 1, percentage Phase 2); **D-J** season-versioned god knowledge (secrets withheld, not guarded; anti-confabulation clause); **D-K** action tiers, playbook-only Tier C; **D-L** repeatables below spine XP-efficiency.

Named (implementation): **D-F** `event-scope-field`; `delve-posture-dm-mode`; `delve-linear-chambers` (3-5, no mazes); `delve-seed-on-respawn`; `complication-tables-authoring-priority`; `contested-region-single-arbitration`; `campaign-director-sole-canon-authority` (records the deliberate narrowing of god autonomy from the tech-arch's OpenClaw framing — signed off, not accreted).

## Phase 11 Amendments (apply to `11_world_loop.md`)

1. **M11.4:** event evaluation consumes `scope`/`world_id` (D-F); add campaign-gate evaluation as a Layer-2 sub-job; add drift clamp per D-H; add delve-site respawn + seed-regeneration and contract-board dawn refresh as economy-tick sub-jobs.
2. **M11.5:** routing metadata carries scope; cascade effects support the `reband` authorization flag (director-only).
3. **M11.6:** heartbeat LLM context is built from the agenda-version-in-force (M12.5), and the world_effects emitter enforces tier validation — add one AC each.

## Cross-cutting follow-ups

- **Late-joiner problem (deferred, noted):** a Season-3 joiner needs a catch-up story for why the early world state isn't theirs — Phase 2 design work, insertion point is campaign_state + session-entry catch-up.
- **Doc amendments backlog:** GDD Seasonal Arc section gains a pointer to the director model; tech-arch Agent Layer gains the tier/playbook constraint (the autonomy narrowing recorded in canon, not just here); lore doc unchanged (it was already written as authored spine — this phase just believes it).
- **LLM narration tics at delve volume:** stance variation mitigates, playtest decides; M12.7's repeat-rate/completion telemetry is the tripwire. If it fails past run ten, next levers are stance-pool expansion and per-run prompt salting — design later, only if needed.
- **Voice cost of delve volume:** repeatables multiply TTS minutes; confirm the cost model's session assumptions cover a delve-heavy player profile.
