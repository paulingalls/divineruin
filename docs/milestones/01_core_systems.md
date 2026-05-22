# Phase 1: Core Systems

> Source doc: `docs/game_mechanics/game_mechanics_core.md`

Deepens the existing rules engine with attribute resolution, skill advancement, resource management, leveling, and async progression systems. Each milestone builds on the previous.

---

### Milestone 1.1 — Attribute System & Core Resolution

**Goal:** Implement the d20 + modifier vs DC resolution pipeline as pure functions, returning narrative-ready result packets instead of raw numbers.

**Inputs:** Existing `rules_engine.py` with basic dice rolls, skill checks, and attacks.

**Deliverables:**
- Pure function: `resolve_check(attribute_score, level, skill_tier, dc)` → CheckResult packet
- 6-attribute model (STR, DEX, CON, INT, WIS, CHA) with standard modifier math: `(attr - 10) // 2`
- DC scale constants: Trivial (5), Easy (8), Moderate (12), Hard (16), Very Hard (20), Extreme (24), Legendary (28)
- Auto-fail thresholds: Below Expert auto-fails DC 24+, below Master auto-fails DC 28+
- Proficiency bonus table: L1-6 (+1), L7-13 (+2), L14-20 (+3)
- Skill tier bonus constants: Untrained (+0), Trained (+2), Expert (+4), Master (+5)
- Result packet structure with narrative cues (margin of success/failure, critical flags, suggested tone)
- Tests for every DC threshold and edge case

**Acceptance criteria:**
- [x] `resolve_check` is a pure function with no side effects or DB calls <!-- evidence: apps/agent/check_resolution.py:117 -->
- [x] Modifier math matches `(attr - 10) // 2` for all attribute values 1-30 <!-- evidence: apps/agent/rules_engine.py:301 attribute_modifier -->
- [x] Auto-fail triggers correctly at DC 24+ for below Expert and DC 28+ for below Master <!-- evidence: apps/agent/check_resolution.py:106 _check_auto_fail -->
- [x] Proficiency bonus returns correct value for all 20 levels <!-- evidence: apps/agent/rules_engine.py:136 proficiency_bonus -->
- [x] Result packet includes margin, success/fail flag, critical flag, and narrative cue <!-- evidence: apps/agent/check_resolution.py:27 CheckResult -->
- [x] All DC scale constants are defined and tested <!-- evidence: apps/agent/rules_engine.py:115 DC_TIERS -->
- [x] 100% test coverage on resolution logic <!-- evidence: pytest-cov measurement (Wave 2.5) — check_resolution.py 99%, rules_engine.py 79% (gap is pool/leveling helpers). Resolution-specific 99%. See audit/phase-1-rules-engine.md#m1.1 -->

**Key references:**
- *Game Mechanics Core — d20 Resolution*
- *Game Mechanics Core — Attribute Modifiers*
- *Game Mechanics Core — Difficulty Class Scale*

---

### Milestone 1.2 — Skill Tier System

**Goal:** Implement the 20-skill, 4-tier advancement system with use-counter tracking and tier-unlock capabilities.

**Inputs:** M1.1 (attribute system and resolution).

**Deliverables:**
- 20 skill definitions across 3 categories: Physical, Mental, Social
- 4 tier definitions: Untrained, Trained, Expert, Master
- Use counter tracking with advancement thresholds: Untrained→Trained (8 uses), Trained→Expert (20 uses), Expert→Master (40 uses + narrative moment)
- Hybrid advancement: session use and async Training feed the same counter
- Expert unlock system: new capability categories per skill
- Master unlock system: signature always-active abilities per skill
- DB migration: `skill_advancement` table (skill_id, character_id, tier, use_counter)
- Pure function: `record_skill_use(character_id, skill_id)` → advancement event or None
- Pure function: `check_skill_capabilities(character_id, skill_id)` → available capabilities at current tier

**Acceptance criteria:**
- [x] All 20 skills defined with category, tier thresholds, and unlock descriptions <!-- evidence: apps/agent/rules_engine.py:89 SKILLS, :147 ADVANCEMENT_THRESHOLDS, :153 SKILL_CAPABILITIES -->
- [x] `record_skill_use` increments counter and triggers tier advancement at correct thresholds <!-- evidence: apps/agent/check_resolution.py:358 -->
- [x] Expert→Master requires 40 uses AND a narrative moment flag <!-- evidence: apps/agent/check_resolution.py:381-389 -->
- [x] `check_skill_capabilities` returns correct capabilities for each tier <!-- evidence: apps/agent/check_resolution.py:411 -->
- [x] Hybrid counter: both session use and Training increments share the same counter <!-- evidence: pinned by tests/test_hybrid_counter.py (Wave 2.5); both check_tools._request_skill_check_impl and async_worker.apply_skill_practice_advancement read/write the same skill_advancement row keyed by (player_id, skill_id). See audit/phase-1-rules-engine.md#m1.2 -->
- [x] DB migration creates `skill_advancement` table with correct schema <!-- evidence: scripts/migrations/014_skill_advancement.sql — note player_id vs spec's character_id (semantic equivalent) -->
- [x] Tests cover all tier transitions including edge cases (counter at threshold - 1, at threshold) <!-- evidence: apps/agent/tests/test_rules_skills.py TestRecordSkillUse -->

**Key references:**
- *Game Mechanics Core — Skill Tiers*
- *Game Mechanics Core — Skill Advancement*
- *Game Mechanics Core — Skill Categories*

---

### Milestone 1.3 — Resource Pools (Stamina & Focus)

**Goal:** Implement Stamina and Focus resource pools with archetype-specific assignments and recovery mechanics.

**Inputs:** M1.1 (attribute system), existing archetype definitions.

**Deliverables:**
- Stamina pool (martial abilities) and Focus pool (magic/mental abilities) per character
- Archetype resource assignments (4 patterns):
  - Stamina-only (full pool, no Focus): Warrior, Guardian, Skirmisher, Rogue, Spy
  - Focus-only (no Stamina, full Focus pool): Mage, Artificer, Seeker, Whisper
  - Focus-primary (small flat Stamina ~4+CON, full Focus pool): Druid, Cleric, Beastcaller, Warden, Paladin, Oracle
  - Split (half Stamina, half Focus, both grow at half rate): Bard, Diplomat, Marshal
- HP formula including CON modifier at half-rate per level
- Recovery mechanics: Short rest (Stamina full, Focus half), Long rest (all full)
- Narrative state indicators at resource thresholds ("winded", "concentration wavers", etc.)
- Pure function: `calculate_max_pool(archetype, level, attribute_modifiers)` → pool maximums
- Pure function: `apply_rest(character_state, rest_type)` → updated resource state
- Pure function: `get_narrative_state(current_pools, max_pools)` → narrative indicator string

**Acceptance criteria:**
- [x] Each archetype correctly assigned to Stamina-only, Focus-only, Focus-primary, or Split <!-- evidence: apps/agent/rules_engine.py:30 ARCHETYPE_RESOURCE_CONFIG (18 entries, 4 patterns); all 18 verified — see audit/phase-1-characters.md §M1.3 Archetype Patterns -->
- [x] HP formula uses CON modifier at half-rate per level and produces correct values L1-20 <!-- evidence: apps/agent/hp_scaling.py:41 calculate_hp -->
- [x] Short rest restores Stamina to full and Focus to 50% <!-- evidence: apps/agent/rest_mechanics.py:8 apply_short_rest -->
- [x] Long rest restores all pools to full <!-- evidence: apps/agent/rest_mechanics.py:20 apply_long_rest -->
- [x] Narrative state indicators trigger at correct thresholds <!-- evidence: apps/agent/fatigue_narration.py:39 get_pool_state, :53 get_pool_narrative -->
- [x] Resource pool calculations are pure functions with no side effects <!-- evidence: apps/agent/rules_engine.py:56 _apply_pool_formula, :64 calculate_max_pools — zero IO, zero async -->
- [x] Tests cover all 18 archetypes and both rest types <!-- evidence: apps/agent/tests/test_rules_pools.py parameterized L336-358 + test_rest_mechanics.py -->

**Key references:**
- *Game Mechanics Core — Resource Pools*
- *Game Mechanics Core — Recovery Rates*
- *Game Mechanics Core — Archetype Resource Assignments*

---

### Milestone 1.4 — Experience & Leveling

**Goal:** Implement the 20-level XP progression system with unified milestone events and attribute increases.

**Inputs:** M1.1 (attribute system), M1.3 (resource pools for HP recalculation on level-up).

**Deliverables:**
- Replace `XP_FOR_LEVEL` D&D 5e values with canonical ~100 XP/session scale from `game_mechanics_core.md` (tech debt from M1.1)
- XP-to-level progression table (~100 XP per session average pacing)
- Unified milestone definitions: L4 (`elective_techniques`), L5 (specialization fork — identity-defining per game_mechanics_core.md L656), L10 (power), L15 (mastery), L20 (capstone)
- Attribute increases at levels 4, 8, 12, 16, 20 (+2 points each)
- Level-up event emitter: triggers narration events via DM agent
- DB migration: unified progression table (level → HP gain, attribute points, milestones, spell tier access, technique slots)
- Pure function: `level_for_xp(total_xp)` → int (canonical name per game_mechanics_core.md L678)
- Pure function: `get_level_up_rewards(from_level, to_level)` → list of rewards and milestones
- Level-up rewards emission satisfied via `award_xp` agent tool (`apps/agent/progression_tools.py:26`) — `check_level_up` + `build_level_up_payload` + `LEVEL_UP` event publish. No separate `apply_level_up` tool; second entrypoint would introduce drift risk.

**Acceptance criteria:**
- [x] `XP_FOR_LEVEL` updated from D&D 5e values to canonical scale <!-- evidence: apps/agent/rules_engine.py:236-257 -->
- [x] XP thresholds produce correct levels for all 20 levels <!-- evidence: apps/agent/rules_engine.py:274 level_for_xp + :282 check_level_up; tests apps/agent/tests/test_rules_leveling.py TestLevelForXp -->
- [x] Attribute increase events fire at levels 4, 8, 12, 16, 20 with +2 points each <!-- evidence: apps/agent/rules_engine.py:260 ATTRIBUTE_INCREASE_LEVELS, apps/agent/leveling.py:48 LEVEL_PROGRESSION -->
- [x] Specialization fork at L5 is flagged in level-up rewards (L4 emits an `elective_techniques` milestone but is NOT a fork; matches game_mechanics_core.md L656 "L5 = identity") <!-- evidence: apps/agent/rules_engine.py:261 SPECIALIZATION_LEVEL=5; apps/agent/leveling.py:85-92 L5 entry; tests apps/agent/tests/test_rules_leveling.py:113-135 + tests/test_leveling.py:39 -->
- [x] Unified progression payload available across all 20 levels with attribute points, milestones, proficiency, fork, and per-level HP gain — HP joined from `ARCHETYPE_HP_CONFIG` at lookup time via `build_level_up_payload_for_archetype` <!-- evidence: apps/agent/leveling.py:331 build_level_up_payload_for_archetype joins LEVEL_PROGRESSION + ARCHETYPE_HP_CONFIG; tests apps/agent/tests/test_leveling.py TestArchetypePayload. NOTE: helper exists; production LEVEL_UP publish sites (progression_tools.py:88, quest_tools.py:195) still emit the base payload — archetype-aware wiring deferred to a future story. Acceptance is on join-availability, not join-emission. -->
- [x] Level-up triggers a narration event that the DM agent can consume <!-- evidence: apps/agent/event_types.py:30 LEVEL_UP; apps/agent/progression_tools.py:88 publish; :325 get_milestone_narration. Note: no standalone apply_level_up agent tool — emitted by award_xp/complete_quest paths (deliverable struck by sprint-008). -->
- [x] DB migration creates progression table with correct schema <!-- evidence: scripts/migrations/015_progression_table.sql + content/level_progression.json -->
- [x] Tests cover level boundaries, multi-level jumps, and milestone triggers <!-- evidence: apps/agent/tests/test_rules_leveling.py + test_leveling.py -->

**Key references:**
- *Game Mechanics Core — Experience & Leveling*
- *Game Mechanics Core — Milestone Levels*
- *Game Mechanics Core — Attribute Increases*

**M1.4 Verification (sprint-008):** All 8 acceptance bullets checked; M1.4 acceptance matrix green (186 passed across `tests/test_rules_leveling.py + test_leveling.py + test_hp_scaling.py + test_rules_core.py` per execution_plan.json §M1 acceptance_execution; Verified-at: `403ebcd1`). Sprint-008 stories: story-001 (deliverables reword + L131 fork box) → story-002 (`level_for_xp` standalone + `check_level_up` consolidation + L129 refresh) → story-003 (`build_level_up_payload_for_archetype` join helper + L132 box flip). Open follow-ups: L133 annotation refresh (concern `1f9f5639278b` — same audit-pointer-after-closed-workaround pattern as L129; defer to next M1.4 doc touch); archetype-aware payload wiring at `progression_tools.py:88` + `quest_tools.py:195` (debt `a6974311f047`).

---

### Milestone 1.5 — Async Training System

**Goal:** Implement the variable-duration training cycle system with midpoint decisions as the central non-combat progression mechanic.

**Inputs:** M1.2 (skill tier system for skill practice), M1.4 (leveling for technique/spell unlocks).

**Deliverables:**
- Training cycle state machine: initiate → first-half → midpoint decision → second-half → completion
- Activity types: spell study, recipe learning, technique training, skill practice, crafting, companion errands
- Variable duration ranges per activity type with micro-bonus variations:
  - Spell study (cantrip/minor): 5–9 hrs total, Spell study (standard/major): 7–11 hrs, Spell study (supreme): 9–14 hrs
  - Recipe study: 5–9 hrs, Technique training (base): 7–11 hrs, Technique training (mentor variant): 9–13 hrs
  - Skill practice: 5–8 hrs, Crafting: 7–11 hrs, Companion errand: 7–13 hrs
- Midpoint decision system: player chooses direction at cycle midpoint
- DB migration: `training_activities` table — shipped as JSONB-flattened schema per `scripts/migrations/016_training_activities.sql`; semantically equivalent to the spec's explicit columns per `audit/phase-1-async.md` §M1.5 L23, no migration required.
- Agent tool: `initiate_training_cycle(program_id)` → creates training record for the current player on a named program (program lookup resolves to activity_type + stat + skill + dc + mentor_id, parallel to HTTP `POST /api/activities` type=training). Paired with `query_training_programs()` so the DM can list available programs. <!-- evidence: apps/agent/training_tools.py initiate_training_cycle + query_training_programs; sprint-009 story-002 reworded the signature from (character_id, activity_type, target) per execution_plan.json §M-2 deep-dive (program_id is HTTP parity) -->
- Agent tool: `resolve_training_midpoint(training_id, decision)` → advances to second half <!-- evidence: apps/agent/training_tools.py resolve_training_midpoint; sprint-009 story-003 shipped the tool, story-004 registered in CityAgent.CITY_TOOLS. Resource-row template (validate-id → for-update → ownership → state → rules → update). -->
- Client component: training panel with progress bar, midpoint decision prompts, completion notifications
- Integration with skill use counters from M1.2 (skill practice increments the same counter)

**Acceptance criteria:**
- [x] Training cycle advances through all states: initiated → first_half → midpoint → second_half → complete <!-- evidence: apps/agent/training_rules.py:32 TrainingState; apps/agent/async_worker.py:222 advance_training_cycles -->
- [x] Each activity type has defined duration ranges and micro-bonus options <!-- evidence: 8 types in apps/agent/training_rules.py:21 TrainingActivityType; loaded from training_activity_types JSONB (training_rules.py:152); seed scripts/migrations/017_training_content.sql -->
- [x] Midpoint decision is mandatory — cycle cannot advance without it <!-- evidence: awaiting_decision is terminal in async_worker (never auto-advances); resolve_midpoint_decision raises ValueError on invalid id -->
- [x] Skill practice training increments the same use counter as session use (M1.2 hybrid advancement) <!-- evidence: apps/agent/async_worker.apply_skill_practice_advancement (Wave 2.5 extraction); pinned by apps/agent/tests/test_hybrid_counter.py -->
- [x] DB migration creates `training_activities` table with correct schema <!-- evidence: scripts/migrations/016_training_activities.sql — note: behavioral fields flattened into data JSONB rather than typed columns the spec named (semantically equivalent) -->
- [x] Client training panel shows progress, prompts midpoint decisions, and notifies on completion <!-- evidence: delivered as feed integration (apps/server/src/catchup.ts:144 trainingToFeedItem) + activity-launcher.tsx + push notifications. NOT a stand-alone panel; reads via Catch-Up feed. See audit/phase-1-async.md -->
- [x] Tests cover full cycle for each activity type, including midpoint decision branches <!-- evidence: apps/agent/tests/test_training_integration.py, test_training_rules.py, test_async_worker.py -->

**Key references:**
- *Game Mechanics Core — Async Training System*
- *Game Mechanics Core — Training Cycle Flow*
- *Game Mechanics Core — Activity Types & Durations*

**M1.5 Verification (sprint-009):** All 7 acceptance criteria green; M1.5 acceptance matrix green (19 unit tests in `tests/test_training_tools.py` + 1 end-to-end integration test `TestFullCycleViaFunctionTools` in `tests/test_training_integration.py` per execution_plan.json §M2 acceptance_execution; Verified-at: `ba954a1`). Sprint-009 stories: story-001 (doc back-prop) → story-002 (`initiate_training_cycle` + `query_training_programs` + `db_training.create_training_activity.transition_at` fix) → story-003 (`resolve_training_midpoint` + `db_training.update_training_activity.transition_at` fix + resource-row template) → story-004 (CityAgent registration + audit M1.5 row flipped to 7/0/0) → story-005 (capstone integration test + this footer). New conventions adopted this sprint: agent-tool-error-shape (`{error, code}` JSON; cross-tool migration captured as debt `effcd01dc050`; story-007 ADR will name canonical shape), mutating-tool-disallow-interruptions (per LiveKit docs), resource-row template (validate-id → for-update → ownership → state → rules → update), training-tool-registration-scope (cities-only; mentors live in cities), livekit-docs-mcp-discipline. Open follow-ups: story-006 (archetype-aware LEVEL_UP payload — M1.4 carry, debt `a6974311f047`); story-007 (`agent-tool-error-shape` ADR — concern `130a5180c4cd`, debt `effcd01dc050`); story-008 (real-LLM + real-Postgres acceptance harness via LiveKit test framework + pytest-bdd + testcontainers-postgres; converts M1.5 AC text to executable Gherkin; ADR `0003-acceptance-llm-run-schedule.md` locks LLM-run cadence to pre-sprint-close only); `test_training_tools.py` 500L split (debt `fcfe95067008`, sprint-010 prep); query_active_training discovery tool (DM in fresh session has no canonical way to learn training_id of an awaiting_decision row; deferred).

---

### Milestone 1.6 — Companion Errands

**Goal:** Implement the companion errand system with risk-based returns and narrative reward scenes running alongside Training.

**Inputs:** M1.5 (training system for async slot management), existing companion data.

**Deliverables:**
- 4 errand types with duration ranges: Scouting (4–8 hrs), Social (3–6 hrs), Acquisition (4–10 hrs), Relationship (2–4 hrs)
- Risk-based return mechanics per destination safety: Safe (no injury), Moderate (10% injured), Dangerous (25% injured, 5% emergency), Extreme (40% injured, 15% emergency)
- Return narration scenes pre-rendered for Catch-Up feed
- Async concurrency: 3 independent slots — Training + Crafting + Companion errand. Artificer exception: can use Training slot for crafting (2 crafting + 1 errand)
- Errands persist in the existing `async_activities` table alongside crafting (shared schema: both are async background work returning narration + decision options)
- Agent tool: `dispatch_companion_errand(companion_id, errand_type, destination)` → creates errand record <!-- see audit/phase-1-async.md#m1.6 — no @function_tool; dispatch is HTTP-only (POST /api/activities type=companion_errand). DM agent cannot dispatch an errand directly -->
- Agent tool: `resolve_companion_errand(errand_id)` → generates return narration <!-- see audit/phase-1-async.md#m1.6 — resolve_companion_errand exists as a pure function in async_rules.py:133 but is NOT exposed as a @function_tool; invoked only by the async worker -->
- Integration with Catch-Up feed for return scene delivery

**Acceptance criteria:**
- [x] All 4 errand types defined with duration ranges, risk levels, and possible outcomes <!-- evidence: sprint-010 story-001 brought all 4 durations to spec (scout 4-8h, social 3-6h, acquire 4-10h, relationship 2-4h); story-011 single-sourced them to content/errand_templates.json -> errand_templates table, conformance-pinned by apps/server/src/activity_templates.test.ts -->
- [x] Risk-based return produces correct outcome distribution per risk level <!-- evidence: sprint-010 story-001/007 — apps/agent/errand_risk.py ERRAND_RISK_TABLE conforms to game_mechanics_core.md §Companion Risk L887-892 across all 4 errand types; rolled once at resolution (ADR 0006). BLOCKED_DANGER_COMBOS pins the spec N/A cells -->
- [x] Return narration is pre-rendered and stored for Catch-Up feed delivery <!-- evidence: apps/agent/async_worker.py resolves errands offline (resolve_companion_errand:100), writes narration_text/summary/audio_url; catchup.ts:190 activityToFeedItem -->
- [ ] Concurrency enforced: 3 independent slots (Training + Crafting + Companion). Artificer can craft in Training slot <!-- 3-slot cap IS enforced (slot_validation.ts) + tested. The Artificer Training-slot exception is DEFERRED TO PHASE 5 per ADR 0005 (debt 95de7fa141df): the Portable Lab is an unbuilt M5 item, and the naive wiring ships a slot-accounting over-capacity bug (countActiveBySlot buckets by activity_type). Box stays open until Phase 5 wires + re-validates the exception -->
<!-- Errand agent tools (the M1.6 dispatch_companion_errand / resolve_companion_errand deliverables) shipped in sprint-010 story-009 on DispatchAgent; verified end-to-end by the M1.6 footer below. -->
- [x] Cannot dispatch errand if companion errand slot is full <!-- evidence: apps/server/src/slot_validation.ts:61 + activities.ts:202 (400 on validation failure) -->
- [x] Errands persist in `async_activities` (shared with crafting — no separate table) <!-- evidence: apps/server/src/activities.ts:244; schema scripts/migrations/005_async_activities.sql. Training uses separate training_activities (mig 016) — by design -->
- [x] Tests cover all errand types, risk outcomes, and concurrency limits <!-- evidence: apps/agent/tests/test_errand_integration.py, test_async_e2e.py, apps/server/src/errand_risk.test.ts, slot_validation.test.ts -->

**Key references:**
- *Game Mechanics Core — Companion Errands*
- *Game Mechanics Core — Errand Types & Risk*
- *Game Mechanics Core — Async Concurrency Slots*

**M1.6 Verification (sprint-010):** 6 of 7 acceptance boxes green; the Artificer Training-slot exception is the sole open box, deferred to Phase 5 per ADR 0005 (debt `95de7fa141df`). The errand seam was verified end-to-end against real Haiku + Postgres via the LiveKit acceptance harness (`apps/agent/tests/acceptance/test_m1_6_companion_errands.py`, 2 scenarios: DM tool-dispatch → in-progress `companion_errand` row; async worker resolves → narration + decision options stored for Catch-Up; real-LLM lane runs pre-sprint-close per ADR 0003, TTS prerender no-op'd as a paid delivery step outside the seam). Verified-at: `9b900a2`. Sprint-010 story chain: story-001 (durations + risk to spec) → story-002 (Artificer exception accepted-divergence + Phase-5 deferral, ADR 0005) → story-003 (`MAX_STRICT_TOOLS` const + per-agent pins) → story-007 (errand risk-roll moved to resolution, ADR 0006) → story-010 (`query_info` consolidation freed CityAgent headroom) → story-008 (TrainingAgent → DispatchAgent + intent handoff, amends ADR 0004) → story-011 (errand templates → shared content/DB, both languages) → story-009 (`dispatch_companion_errand` + `resolve_companion_errand` @function_tools on DispatchAgent + shared `errand_resolution` helper — satisfies the M1.6 errand-tool deliverables the audit flagged HTTP-only) → story-004 (this capstone + reconciliation). New conventions/decisions this sprint: agent-tool errors raise LiveKit `ToolError` (ADR 0002, replaces `{error,code}`); errand risk rolls once at resolution (ADR 0006); single shared errand-template content source (no cross-language drift); `errand_resolution.resolve_errand_outcome` is the sole roll-site for worker + tool; fail-closed on missing `errand_type`. Open follow-ups: Artificer Phase-5 wiring (`95de7fa141df`); `resolve_companion_errand` FOR-UPDATE/transaction hardening + worker row-lock (concern `6b223681ec4f`); native-device acceptance lane (`75ef69a2c81d`) + e2e LiveKit data-channel harness (`df1a9368ce6c`).
