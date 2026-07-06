# Phase 4: Combat System

> Source doc: `docs/game_mechanics/game_mechanics_combat.md`

Redesigns the existing basic combat state machine into a 4-beat phase-based system with no turn order or grids, adds action economy, status conditions, death mechanics, dramatic dice, and non-combat encounter resolution. Depends on Phase 1 (Core Systems) and Phase 2 (Archetypes).

## Audit Status (Sprint-003)

<!-- see audit/phase-4-combat.md and audit/phase-encounter-roles.md -->

**Status: DELIVERED.** (The Sprint-003 audit below is retained for historical context; its "DEFERRED / NOT_STARTED" assessment is now superseded.) Combat shipped across sprints 018-037. M4.1-M4.8 are all delivered and each is proven end-to-end by a passing acceptance capstone (`apps/agent/tests/acceptance/test_m4*_capstone.py`): the 4-beat phase machine, action economy, 21-condition system, death/dying/resurrection + Mortaen scene + Hollowed death, dramatic-dice signal, and social/travel/gathering. The combat/multiplayer/social/audio extensions M11-M20 (spell targeting, combat-HUD conditions, enemy conditions, multiplayer combat, social/de-escalation scenes, node respawn, audio SFX, multiplayer completeness, room join, MP combat II) also shipped and are tracked in `execution_plan.json` (plan `plan-phase-4-combat`) with their own capstones.

| Milestone | Confirmed | Partial | Divergent | Aspirational |
| --- | --- | --- | --- | --- |
| M4.1 — Phase-Based Combat Redesign (11) | 2 | 3 | 2 | 4 |
| M4.2 — Action Economy & Declarations (11) | 4 | 4 | 0 | 3 |
| M4.3 — Status Conditions (10) | 0 | 0 | 0 | 10 |
| M4.4 — Death, Dying & Resurrection (12) | 2 | 2 | 1 | 7 |
| M4.5 — Dramatic Dice System (9) | 0 | 0 | 0 | 9 |
| M4.6 — Social, Travel & Gathering (12) | 0 | 0 | 0 | 12 |

**Material gaps (cross-cutting):**
- Combat is **turn-based**, not phase-based with 4 beats. State lives in `combat_instances` (single `data JSONB`, PostgreSQL) — not spec's `combat_encounters` with phase columns in Redis.
- No condition system at all: no `character_conditions` table, no `apply_condition`/`tick_conditions`/`get_condition_effects`. `apps/agent/fatigue_narration.py:29-36` is narrative-cue only.
- No dramatic-dice flag on any roll result packet (`AttackResult`, `SavingThrowResult`, `DeathSaveResult`, `CheckResult` all lack `dramatic`).
- No social/travel/gathering systems shipped. `apps/agent/wilderness_agent.py:36-52` is a 52-line stub.
- NPC disposition system exists but uses `"wary"` where spec uses `"unfriendly"` (`apps/agent/tool_support.py:76-83` vs `gm_combat:L671`) — spec/code naming divergence.
- Mortaen mechanic surface entirely aspirational: no `death_counter`, no `determine_death_cost`, no Mortaen scene wiring.

**encounter_roles primary ownership (capstone decision `m4-7-overlay-status`):** Phase 04 owns the encounter_roles overlay per `execution_plan.json §Milestone 3`. The audit recommends a **new milestone M4.7 "Encounter Role Overlay"** (Minion / Standard / Elite / Boss / Named) — not yet authored as a numbered section below; scope lives in `audit/phase-encounter-roles.md`.

**Cross-refs:**
- **M7.1 (Bestiary)** must extend stat block schema with optional `role` field and Boss-only `signature_ability`/`legendary_actions[]` fields.
- **M7.4 (Encounter Builder)** `build_encounter` signature is in flux: spec uses `(tier, combatant_count, environment)`; encounter_roles work needs `(tier, budget_points, environment)`. Final choice deferred to the M4.7/M7.4 implementation sprint (decision `m7-4-build-encounter-signature` recorded).
- **Phase 09 Economy** owns currency drops and material sell values from encounter_roles §Loot Modifiers; see `09_economy.md` Sprint-003 cross-ref.

See `audit/phase-4-combat.md` for the full 65-item coverage matrix.

---

### Milestone 4.1 — Phase-Based Combat Redesign (4 Beats)

**Goal:** Replace the existing combat agent's basic state machine with a 4-beat flowing scene structure where each round plays as declaration, resolution, narration, and wrap — no turn order, no grids.

**Inputs:** Existing `CombatAgent` with basic combat state machine, Phase 1 (core resolution), Phase 2 (archetypes for class-specific behavior).

**Deliverables:**
- Fix `narrative_hint()` in `rules_engine.py`: returns "critical success" for margin > 5, which is misleading (not a nat 20). `resolve_check` has proper `critical_success`/`critical_failure` booleans — update `resolve_attack` and `resolve_saving_throw` to use them (tech debt from M1.1)
- Combat state machine: `idle → encounter_start → initiative_roll → [phase_loop: declaration → resolution → narration → wrap] → combat_end`
- Beat 1 (Declaration): player + companion + enemies all declare intended actions simultaneously
- Beat 2 (Resolution): engine resolves all declared actions silently, flags dramatic results for narration
- Beat 3 (Narration): DM narrates outcomes with reaction windows, pauses for dramatic dice reveals
- Beat 4 (Wrap): death saves, stamina regen, condition tick-down, end-of-phase bookkeeping
- Initiative: single `d20 + DEX modifier` roll at combat start determines resolution priority within phases
- Updated `CombatAgent` session with phase-loop orchestration
- Combat state tracking in Redis for fast phase transitions
- Pure function: `advance_combat_phase(current_state, declarations)` → next state + resolution results
- DB migration: `combat_encounters` table updated with phase tracking columns

**Acceptance criteria:**
- [x] `narrative_hint()` fixed: no longer returns "critical success" for non-nat-20 rolls
- [x] `resolve_attack` and `resolve_saving_throw` use `CheckResult` critical flags
- [x] Combat state machine transitions through all states in correct order
- [x] Initiative roll uses `d20 + DEX modifier` and correctly orders resolution within a phase
- [x] Beat 1 collects declarations from player, companions, and enemies before any resolution
- [x] Beat 2 resolves all actions without emitting narration, produces result packets with dramatic flags
- [x] Beat 3 narration includes reaction windows where DM pauses for dramatic dice
- [x] Beat 4 processes death saves, stamina regen, and condition tick-downs
- [x] Phase loop repeats until combat_end is triggered (all enemies defeated, retreat, etc.)
- [x] `advance_combat_phase` is a pure function with no side effects
- [x] Tests cover full combat lifecycle from encounter_start through combat_end

**Key references:**
- *Game Mechanics Combat — 4-Beat Phase Structure*
- *Game Mechanics Combat — Initiative & Resolution Order*
- *Game Mechanics Combat — Combat State Machine*

---

### Milestone 4.2 — Action Economy & Declarations

**Goal:** Implement the one-declaration-per-phase action system with 6 action types and full combat math for attacks, AC, and weapon damage.

**Inputs:** M4.1 (phase-based combat), Phase 1 (core resolution and attribute system), Phase 2 (archetypes for declaration enhancers).

**Deliverables:**
- 6 declaration types: Attack, Ability, Interact, Maneuver, Defend, Retreat
- Declaration enhancers: Cunning Action (Rogue), Extra Attack (Warrior) expand what one declaration resolves into, not separate actions
- Attack roll: `d20 + attribute modifier + proficiency bonus` (if weapon-proficient) vs AC
- AC calculation by armor type: Unarmored (`10 + DEX`), Light (`12 + DEX`), Medium (`14 + DEX max 2`), Heavy (`16-18, no DEX`)
- Weapon damage table: `1d4` (dagger) through `1d12` (greataxe) `+ attribute modifier`
- Player intent interpretation: player speaks freely, DM agent interprets intent and calls appropriate mechanics tools
- Agent tool: `request_attack(attacker_id, target_id, weapon_id)` → hit/miss/crit result with damage and dramatic flag
- Agent tool: `request_save(target_id, save_type, dc)` → success/fail with margin and dramatic flag
- Pure function: `calculate_ac(armor, dex_modifier)` → AC value
- Pure function: `resolve_attack(attacker_stats, target_ac, weapon)` → attack result packet
- Pure function: `resolve_declaration(declaration_type, actor, targets, context)` → resolution result

**Acceptance criteria:**
- [x] All 6 declaration types are defined with validation rules
- [x] Only one declaration per actor per phase (enhancers expand resolution, not declaration count)
- [x] Attack roll correctly applies proficiency bonus when weapon-proficient
- [x] AC calculation is correct for all armor categories (unarmored, light, medium, heavy)
- [x] Weapon damage ranges from 1d4 to 1d12 + correct attribute modifier
- [x] Critical hit (natural 20) doubles damage dice
- [x] `request_attack` returns structured result with hit/miss/crit, damage, and dramatic flag
- [x] `request_save` returns structured result with success/fail and margin
- [x] Declaration enhancers (Cunning Action, Extra Attack) correctly expand single declarations
- [x] All combat math functions are pure with no side effects
- [x] Tests cover all declaration types, armor categories, and weapon damage ranges

**Key references:**
- *Game Mechanics Combat — Action Economy*
- *Game Mechanics Combat — Declaration Types*
- *Game Mechanics Combat — Attack Resolution & AC*
- *Game Mechanics Combat — Weapon Damage Table*

---

### Milestone 4.3 — Status Conditions

**Goal:** Implement 20+ status conditions with mechanical effects, duration tracking, and clearance rules that integrate with the combat phase loop.

**Inputs:** M4.1 (phase-based combat for wrap-phase tick-down), M4.2 (action economy for condition effects on declarations).

**Deliverables:**
- Physical conditions: Wounded, Stunned, Prone, Grappled, Restrained, Incapacitated, Paralyzed, Exhausted
- Mental conditions: Frightened, Charmed, Shaken
- Sensory conditions: Blinded, Deafened
- Magical conditions: Poisoned, Blessed, Shielded, Enraged, Inspired, Cursed, Petrified
- Hollow conditions: Hollowed (special, from corruption — unique clearance rules)
- Each condition defines: mechanical effect (modifier changes, action restrictions), clearance method (save, duration, rest, spell), stack behavior
- DB migration: `character_conditions` table (`character_id`, `condition_type`, `applied_at_phase`, `duration`, `source_id`)
- Pure function: `apply_condition(character_state, condition_type, duration, source)` → updated state
- Pure function: `remove_condition(character_state, condition_type)` → updated state
- Pure function: `tick_conditions(character_state, phase_number)` → updated state with expired conditions removed
- Pure function: `get_condition_effects(conditions)` → aggregated modifier changes and action restrictions
- Client component: condition icons in combat tracker and persistent status bar

**Acceptance criteria:**
- [x] All 20+ conditions defined with mechanical effect, clearance method, and stack behavior
- [x] `apply_condition` correctly adds condition to character state with duration and source tracking
- [x] `remove_condition` correctly removes specific condition instances
- [x] `tick_conditions` decrements duration-based conditions in Beat 4 (Wrap) and removes expired ones
- [x] Conditions requiring saves to clear trigger save checks during tick
- [x] `get_condition_effects` correctly aggregates effects from multiple simultaneous conditions
- [x] Hollowed condition has unique behavior distinct from standard conditions
- [x] DB migration creates `character_conditions` table with correct schema
- [x] Client displays condition icons in combat tracker and persistent bar
- [x] Tests cover applying, stacking, ticking, and clearing every condition type

**Key references:**
- *Game Mechanics Combat — Status Conditions*
- *Game Mechanics Combat — Condition Effects & Clearance*
- *Game Mechanics Combat — Hollowed Condition*

---

### Milestone 4.4 — Death, Dying & Resurrection

**Goal:** Implement the full death system with escalating costs per death, Mortaen's domain scene, Hollowed death variant, and resurrection anchoring.

**Inputs:** M4.1 (combat phases for death save timing), M4.3 (conditions for Hollowed state), existing scene system.

**Deliverables:**
- Fallen state: 0 HP triggers unconscious, begin death saves each phase
- Death save mechanic: `d20` (no modifiers) — 10+ success, <10 failure; 3 successes = Stabilized, 3 failures = Dead
- Instant death: excess damage >= max HP kills instantly (no saves)
- Hollowed Death (Stage 2+ Hollowed): character rises as Temporary Hollowed — DM-controlled, attacks allies using character abilities + `1d6` necrotic damage
- Death cost escalation by tier:
  - Gentle (1st death): memory/trinket loss
  - Moderate (2nd): -1 to lowest attribute OR Mark of Mortaen
  - Severe (3rd-4th): -1 primary attribute, quest consequence, or item loss
  - Devastating (5th+): -2 primary attribute + Warning; 7th+: -1 max HP per level
- Mortaen's domain: narrative scene at death where cost is applied and resurrection offered
- Mortaen patron bonus: +2 to death saves, first death is free, skip Mortaen meeting
- Resurrection location: nearest safe anchor — battlefield (if cleared), camp, settlement, starter zone as final fallback
- Party wipe: all characters die simultaneously, each pays own death cost, all resurrect at highest-priority anchor
- Companion death: temporary Hollowed-like state but auto-stabilizes (narrative protection, not permanent)
- DB migration: `death_saves` tracker, `character_death_history` (death count, costs paid), `resurrection_anchor_points`
- Agent tool: `resolve_death_save(character_id)` → save result, check for stabilize/death
- Agent tool: `get_death_cost(character_id)` → cost tier and specific cost based on death count
- Agent tool: `trigger_character_death(character_id)` → initiates Mortaen scene, applies cost, handles resurrection

**Acceptance criteria:**
- [x] 0 HP triggers Fallen state with death save requirement each phase
- [x] Death save uses d20 with no modifiers; 10+ is success, <10 is failure
- [x] 3 successes stabilizes; 3 failures triggers death
- [x] Instant death fires when excess damage >= max HP
- [x] Hollowed Death (Stage 2+) creates DM-controlled Temporary Hollowed with character abilities + 1d6 necrotic
- [x] Death cost correctly escalates across all tiers (Gentle through Devastating)
- [x] Mortaen patron characters get +2 death saves and skip first death cost
- [x] Resurrection places character at nearest valid anchor point with correct priority fallback
- [x] Party wipe processes all deaths independently and resurrects at shared anchor
- [x] Companion death auto-stabilizes without permanent consequences
- [x] DB migrations create all three tables with correct schemas
- [x] Tests cover every death tier, Hollowed death, instant death, party wipe, and companion death

**Key references:**
- *Game Mechanics Combat — Death & Dying*
- *Game Mechanics Combat — Resurrection Costs*
- *Game Mechanics Combat — Hollowed Death*
- *Game Mechanics Combat — Party Wipe Rules*

---

### Milestone 4.5 — Dramatic Dice System

**Goal:** Implement a scarcity-based dramatic dice system that selectively triggers animated d20 overlays for high-stakes rolls, with DM narration pauses for reaction windows.

**Inputs:** M4.1 (combat phases for narration pauses), M4.4 (death saves as always-dramatic), existing dice_result event system.

**Deliverables:**
- Always dramatic: death saves, Natural 20, Natural 1, boss attacks, counterspells
- Contextually dramatic: target near death, player near death, first attack of combat, last enemy standing
- Never dramatic: minor damage, NPC initiative, routine exploration checks
- Pure function: `evaluate_dramatic_context(roll_type, game_state)` → `bool`
- Dramatic flag added to all roll result packets: `{dramatic: bool, context: dict}`
- Updated existing `dice_result` events to include dramatic flag
- Client component: animated d20 overlay triggered only for dramatic rolls
- DM narration pauses: Beat 3 reaction windows timed to dramatic roll reveals

**Acceptance criteria:**
- [x] `evaluate_dramatic_context` returns `True` for all always-dramatic scenarios
- [x] `evaluate_dramatic_context` returns `True` for contextually dramatic scenarios when conditions met
- [x] `evaluate_dramatic_context` returns `False` for never-dramatic scenarios
- [x] All roll result packets include `dramatic` flag and `context` dict
- [x] Existing dice_result events updated to include dramatic flag without breaking consumers
- [x] Client animated d20 overlay fires only when `dramatic: True`
- [x] DM pauses narration during Beat 3 for dramatic roll reveals
- [x] `evaluate_dramatic_context` is a pure function with no side effects
- [x] Tests cover all always/contextual/never categories with representative game states

**Key references:**
- *Game Mechanics Combat — Dramatic Dice System*
- *Game Mechanics Combat — Reaction Windows*
- *Game Mechanics Combat — Roll Categorization*

---

### Milestone 4.6 — Social Encounters, Travel & Gathering

**Goal:** Implement the three non-combat encounter systems — social resolution, travel mechanics, and resource gathering — that share the exploration phase of gameplay.

**Inputs:** M4.2 (action resolution patterns), Phase 1 (skill tiers for gathering DCs), Phase 2 (Diplomat archetype for social de-escalation).

**Deliverables:**
- **Social encounters:**
  - 3-tier social resolution system with disposition-as-damage (NPC disposition 0-10 mapped to social DC)
  - Structured social scenes with tension curve (opening, escalation, climax, resolution)
  - Diplomat archetype can de-escalate combat situations through social checks
  - Pure function: `resolve_social_check(character_skills, npc_disposition, approach)` → disposition change + narrative cue
- **Travel:**
  - 3 travel modes: Fast (high encounter rate, no foraging), Normal (balanced), Careful (low encounter rate, foraging possible)
  - Navigation checks with failure consequences (lost time, wrong area)
  - Exhaustion tracking over extended travel
  - Encounter triggers based on location danger rating and travel mode
  - Pure function: `resolve_travel_segment(party, mode, route, danger_level)` → events + exhaustion changes
- **Gathering:**
  - Skill-gated resource collection: Perception (spotting), Survival (harvesting), Nature (identifying)
  - Regional resource tables with fixed nodes and discoverable nodes
  - Discovery moments: narrative beats when finding rare resources
  - Pure function: `resolve_gathering(character_skills, location, resource_table)` → gathered items + discovery flag
- DB migration: `travel_state` table (party route, mode, progress, exhaustion), `gathering_nodes` table (location_id, resource_type, quantity, discovered)
- Agent tool: `resolve_social_check(character_id, npc_id, approach)` → social outcome
- Agent tool: `start_travel(party_id, destination, mode)` → travel state with encounter schedule
- Agent tool: `resolve_gathering(character_id, location_id)` → gathered resources

**Acceptance criteria:**
- [x] Social DC correctly derived from NPC disposition (0-10 scale)
- [x] Social encounters follow structured tension curve with distinct phases
- [x] Diplomat archetype can attempt de-escalation during combat encounters
- [x] All 3 travel modes produce correct encounter rates and foraging availability
- [x] Navigation failure leads to lost time or wrong-area consequences
- [x] Exhaustion accumulates over extended travel and affects checks
- [x] Gathering checks are gated by appropriate skills (Perception, Survival, Nature)
- [x] Regional resource tables return location-appropriate resources
- [x] Discovery moments trigger narrative beats for rare resource finds
- [x] DB migrations create `travel_state` and `gathering_nodes` tables
- [x] All resolution functions are pure with no side effects
- [x] Tests cover social disposition ranges, all travel modes, and gathering skill gates

**Key references:**
- *Game Mechanics Combat — Social Encounter Resolution*
- *Game Mechanics Combat — Travel Modes & Encounters*
- *Game Mechanics Combat — Gathering System*
