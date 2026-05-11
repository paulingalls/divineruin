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
- [x] `resolve_check` is a pure function with no side effects or DB calls
- [x] Modifier math matches `(attr - 10) // 2` for all attribute values 1-30
- [x] Auto-fail triggers correctly at DC 24+ for below Expert and DC 28+ for below Master
- [x] Proficiency bonus returns correct value for all 20 levels
- [x] Result packet includes margin, success/fail flag, critical flag, and narrative cue
- [x] All DC scale constants are defined and tested
- [x] 100% test coverage on resolution logic

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
- [x] All 20 skills defined with category, tier thresholds, and unlock descriptions
- [x] `record_skill_use` increments counter and triggers tier advancement at correct thresholds
- [x] Expert→Master requires 40 uses AND a narrative moment flag
- [x] `check_skill_capabilities` returns correct capabilities for each tier
- [x] Hybrid counter: both session use and Training increments share the same counter
- [x] DB migration creates `skill_advancement` table with correct schema
- [x] Tests cover all tier transitions including edge cases (counter at threshold - 1, at threshold)

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
- [x] Each archetype correctly assigned to Stamina-only, Focus-only, Focus-primary, or Split
- [x] HP formula uses CON modifier at half-rate per level and produces correct values L1-20
- [x] Short rest restores Stamina to full and Focus to 50%
- [x] Long rest restores all pools to full
- [x] Narrative state indicators trigger at correct thresholds
- [x] Resource pool calculations are pure functions with no side effects
- [x] Tests cover all 18 archetypes and both rest types

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
- [x] `XP_FOR_LEVEL` updated from D&D 5e values to canonical scale
- [x] XP thresholds produce correct levels for all 20 levels
- [x] Attribute increase events fire at levels 4, 8, 12, 16, 20 with +2 points each
- [x] Specialization fork at L4/L5 is flagged in level-up rewards
- [x] Unified progression table covers all 20 levels with correct HP gains, attribute points, and milestones
- [x] Level-up triggers a narration event that the DM agent can consume
- [x] DB migration creates progression table with correct schema
- [x] Tests cover level boundaries, multi-level jumps, and milestone triggers

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
- [x] Training cycle advances through all states: initiated → first_half → midpoint → second_half → complete
- [x] Each activity type has defined duration ranges and micro-bonus options
- [x] Midpoint decision is mandatory — cycle cannot advance without it
- [x] Skill practice training increments the same use counter as session use (M1.2 hybrid advancement)
- [x] DB migration creates `training_activities` table with correct schema
- [x] Client training panel shows progress, prompts midpoint decisions, and notifies on completion
- [x] Tests cover full cycle for each activity type, including midpoint decision branches

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
- [x] All 4 errand types defined with duration ranges, risk levels, and possible outcomes
- [x] Risk-based return produces correct outcome distribution per risk level
- [x] Return narration is pre-rendered and stored for Catch-Up feed delivery
- [x] Concurrency enforced: 3 independent slots (Training + Crafting + Companion). Artificer can craft in Training slot
- [x] Cannot dispatch errand if companion errand slot is full
- [x] Errands persist in `async_activities` (shared with crafting — no separate table)
- [x] Tests cover all errand types, risk outcomes, and concurrency limits

**Key references:**
- *Game Mechanics Core — Companion Errands*
- *Game Mechanics Core — Errand Types & Risk*
- *Game Mechanics Core — Async Concurrency Slots*
