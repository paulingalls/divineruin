# Phase 4: Combat System

> Source doc: `docs/game_mechanics/game_mechanics_combat.md`

Redesigns the existing basic combat state machine into a 4-beat phase-based system with no turn order or grids, adds action economy, status conditions, death mechanics, dramatic dice, and non-combat encounter resolution. Depends on Phase 1 (Core Systems) and Phase 2 (Archetypes).

---

### Milestone 4.1 — Phase-Based Combat Redesign (4 Beats)

**Goal:** Replace the existing combat agent's basic state machine with a 4-beat flowing scene structure where each round plays as declaration, resolution, narration, and wrap — no turn order, no grids.

**Inputs:** Existing `CombatAgent` with basic combat state machine, Phase 1 (core resolution), Phase 2 (archetypes for class-specific behavior).

**Deliverables:**
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
- [ ] Combat state machine transitions through all states in correct order
- [ ] Initiative roll uses `d20 + DEX modifier` and correctly orders resolution within a phase
- [ ] Beat 1 collects declarations from player, companions, and enemies before any resolution
- [ ] Beat 2 resolves all actions without emitting narration, produces result packets with dramatic flags
- [ ] Beat 3 narration includes reaction windows where DM pauses for dramatic dice
- [ ] Beat 4 processes death saves, stamina regen, and condition tick-downs
- [ ] Phase loop repeats until combat_end is triggered (all enemies defeated, retreat, etc.)
- [ ] `advance_combat_phase` is a pure function with no side effects
- [ ] Tests cover full combat lifecycle from encounter_start through combat_end

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
- [ ] All 6 declaration types are defined with validation rules
- [ ] Only one declaration per actor per phase (enhancers expand resolution, not declaration count)
- [ ] Attack roll correctly applies proficiency bonus when weapon-proficient
- [ ] AC calculation is correct for all armor categories (unarmored, light, medium, heavy)
- [ ] Weapon damage ranges from 1d4 to 1d12 + correct attribute modifier
- [ ] Critical hit (natural 20) doubles damage dice
- [ ] `request_attack` returns structured result with hit/miss/crit, damage, and dramatic flag
- [ ] `request_save` returns structured result with success/fail and margin
- [ ] Declaration enhancers (Cunning Action, Extra Attack) correctly expand single declarations
- [ ] All combat math functions are pure with no side effects
- [ ] Tests cover all declaration types, armor categories, and weapon damage ranges

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
- [ ] All 20+ conditions defined with mechanical effect, clearance method, and stack behavior
- [ ] `apply_condition` correctly adds condition to character state with duration and source tracking
- [ ] `remove_condition` correctly removes specific condition instances
- [ ] `tick_conditions` decrements duration-based conditions in Beat 4 (Wrap) and removes expired ones
- [ ] Conditions requiring saves to clear trigger save checks during tick
- [ ] `get_condition_effects` correctly aggregates effects from multiple simultaneous conditions
- [ ] Hollowed condition has unique behavior distinct from standard conditions
- [ ] DB migration creates `character_conditions` table with correct schema
- [ ] Client displays condition icons in combat tracker and persistent bar
- [ ] Tests cover applying, stacking, ticking, and clearing every condition type

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
- [ ] 0 HP triggers Fallen state with death save requirement each phase
- [ ] Death save uses d20 with no modifiers; 10+ is success, <10 is failure
- [ ] 3 successes stabilizes; 3 failures triggers death
- [ ] Instant death fires when excess damage >= max HP
- [ ] Hollowed Death (Stage 2+) creates DM-controlled Temporary Hollowed with character abilities + 1d6 necrotic
- [ ] Death cost correctly escalates across all tiers (Gentle through Devastating)
- [ ] Mortaen patron characters get +2 death saves and skip first death cost
- [ ] Resurrection places character at nearest valid anchor point with correct priority fallback
- [ ] Party wipe processes all deaths independently and resurrects at shared anchor
- [ ] Companion death auto-stabilizes without permanent consequences
- [ ] DB migrations create all three tables with correct schemas
- [ ] Tests cover every death tier, Hollowed death, instant death, party wipe, and companion death

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
- [ ] `evaluate_dramatic_context` returns `True` for all always-dramatic scenarios
- [ ] `evaluate_dramatic_context` returns `True` for contextually dramatic scenarios when conditions met
- [ ] `evaluate_dramatic_context` returns `False` for never-dramatic scenarios
- [ ] All roll result packets include `dramatic` flag and `context` dict
- [ ] Existing dice_result events updated to include dramatic flag without breaking consumers
- [ ] Client animated d20 overlay fires only when `dramatic: True`
- [ ] DM pauses narration during Beat 3 for dramatic roll reveals
- [ ] `evaluate_dramatic_context` is a pure function with no side effects
- [ ] Tests cover all always/contextual/never categories with representative game states

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
- [ ] Social DC correctly derived from NPC disposition (0-10 scale)
- [ ] Social encounters follow structured tension curve with distinct phases
- [ ] Diplomat archetype can attempt de-escalation during combat encounters
- [ ] All 3 travel modes produce correct encounter rates and foraging availability
- [ ] Navigation failure leads to lost time or wrong-area consequences
- [ ] Exhaustion accumulates over extended travel and affects checks
- [ ] Gathering checks are gated by appropriate skills (Perception, Survival, Nature)
- [ ] Regional resource tables return location-appropriate resources
- [ ] Discovery moments trigger narrative beats for rare resource finds
- [ ] DB migrations create `travel_state` and `gathering_nodes` tables
- [ ] All resolution functions are pure with no side effects
- [ ] Tests cover social disposition ranges, all travel modes, and gathering skill gates

**Key references:**
- *Game Mechanics Combat — Social Encounter Resolution*
- *Game Mechanics Combat — Travel Modes & Encounters*
- *Game Mechanics Combat — Gathering System*
