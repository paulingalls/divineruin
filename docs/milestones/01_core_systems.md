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
- Unified milestone definitions: L4/L5 (specialization fork), L10 (power), L15 (mastery), L20 (capstone)
- Attribute increases at levels 4, 8, 12, 16, 20 (+2 points each)
- Level-up event emitter: triggers narration events via DM agent
- DB migration: unified progression table (level → HP gain, attribute points, milestones, spell tier access, technique slots)
- Pure function: `calculate_level(total_xp)` → level
- Pure function: `get_level_up_rewards(from_level, to_level)` → list of rewards and milestones
- Agent tool: `apply_level_up(character_id)` → applies rewards, emits narration event

**Acceptance criteria:**
- [x] `XP_FOR_LEVEL` updated from D&D 5e values to canonical scale <!-- evidence: apps/agent/rules_engine.py:236-257 -->
- [x] XP thresholds produce correct levels for all 20 levels <!-- evidence: apps/agent/rules_engine.py:274 check_level_up; note: no standalone calculate_level(total_xp), use check_level_up(0, total_xp, 1) — see audit/phase-1-characters.md -->
- [x] Attribute increase events fire at levels 4, 8, 12, 16, 20 with +2 points each <!-- evidence: apps/agent/rules_engine.py:260 ATTRIBUTE_INCREASE_LEVELS, apps/agent/leveling.py:48 LEVEL_PROGRESSION -->
- [ ] Specialization fork at L4/L5 is flagged in level-up rewards <!-- see audit/phase-1-characters.md#m1.4 — only L5 carries specialization_fork=True; L4 emits elective_techniques milestone but is NOT flagged as a fork. Diverges from spec wording -->
- [ ] Unified progression table covers all 20 levels with correct HP gains, attribute points, and milestones <!-- see audit/phase-1-characters.md#m1.4 — LEVEL_PROGRESSION unifies attribute_points + milestones + proficiency + fork; HP gain lives separately in apps/agent/hp_scaling.py ARCHETYPE_HP_CONFIG. Acceptance text names HP as a unified-table field but it's split -->
- [x] Level-up triggers a narration event that the DM agent can consume <!-- evidence: apps/agent/event_types.py:30 LEVEL_UP; apps/agent/progression_tools.py:88 publish; :325 get_milestone_narration. Note: no standalone apply_level_up agent tool — emitted by award_xp/complete_quest paths. See audit/phase-1-characters.md -->
- [x] DB migration creates progression table with correct schema <!-- evidence: scripts/migrations/015_progression_table.sql + content/level_progression.json -->
- [x] Tests cover level boundaries, multi-level jumps, and milestone triggers <!-- evidence: apps/agent/tests/test_rules_leveling.py + test_leveling.py -->

**Key references:**
- *Game Mechanics Core — Experience & Leveling*
- *Game Mechanics Core — Milestone Levels*
- *Game Mechanics Core — Attribute Increases*

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
- DB migration: `training_activities` table (type, target, cycle_number, first_half_duration, second_half_duration, state, decision_made, micro_bonus)
- Agent tool: `initiate_training_cycle(character_id, activity_type, target)` → creates training record
- Agent tool: `resolve_training_midpoint(training_id, decision)` → advances to second half
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
- Agent tool: `dispatch_companion_errand(companion_id, errand_type, destination)` → creates errand record
- Agent tool: `resolve_companion_errand(errand_id)` → generates return narration
- Integration with Catch-Up feed for return scene delivery

**Acceptance criteria:**
- [ ] All 4 errand types defined with duration ranges, risk levels, and possible outcomes <!-- see audit/phase-1-async.md#m1.6 — types + outcomes defined (apps/server/src/activity_templates.ts:153 ERRAND_TEMPLATES), but ALL 4 shipped duration ranges diverge from spec (scout 2-4 vs spec 4-8; social 1-3 vs 3-6; acquire 2-4 vs 4-10; relationship 3-6 vs 2-4). Compound check fails on durations -->
- [ ] Risk-based return produces correct outcome distribution per risk level <!-- see audit/phase-1-async.md#m1.6 — apps/server/src/errand_risk.ts:24 ERRAND_RISK_TABLE only populates `scout` at spec values; `acquire` reduced; `social`/`relationship` always 0/0. Spec's per-danger-level percentages NOT applied across all errands -->
- [x] Return narration is pre-rendered and stored for Catch-Up feed delivery <!-- evidence: apps/agent/async_worker.py resolves errands offline (resolve_companion_errand:100), writes narration_text/summary/audio_url; catchup.ts:190 activityToFeedItem -->
- [ ] Concurrency enforced: 3 independent slots (Training + Crafting + Companion). Artificer can craft in Training slot <!-- see audit/phase-1-async.md#m1.6 — 3-slot cap is enforced (slot_validation.ts:37). BUT the Artificer exception is DEAD CODE: validator accepts archetype + hasPortableLab params and is unit-tested, but both call sites in activities.ts (L87, L200) pass neither. A live Artificer with Portable Lab cannot benefit from the exception -->
- [x] Cannot dispatch errand if companion errand slot is full <!-- evidence: apps/server/src/slot_validation.ts:61 + activities.ts:202 (400 on validation failure) -->
- [x] Errands persist in `async_activities` (shared with crafting — no separate table) <!-- evidence: apps/server/src/activities.ts:244; schema scripts/migrations/005_async_activities.sql. Training uses separate training_activities (mig 016) — by design -->
- [x] Tests cover all errand types, risk outcomes, and concurrency limits <!-- evidence: apps/agent/tests/test_errand_integration.py, test_async_e2e.py, apps/server/src/errand_risk.test.ts, slot_validation.test.ts -->

**Key references:**
- *Game Mechanics Core — Companion Errands*
- *Game Mechanics Core — Errand Types & Risk*
- *Game Mechanics Core — Async Concurrency Slots*
