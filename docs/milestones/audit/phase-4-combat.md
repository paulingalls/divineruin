# Phase 4 — Combat Audit (Sprint-003)

Read-only audit. Source: `docs/game_mechanics/game_mechanics_combat.md` (1060L) vs `docs/milestones/04_combat.md` M4.1-M4.6 (65 acceptance items). Bias is toward unchecking when evidence is weak — capstone will reconcile.

Status legend: **confirmed** (symbol/migration exists and matches spec scope), **partial** (some pieces exist but deliverable surface is incomplete), **aspirational** (no symbol/migration found), **divergent** (a related symbol exists but differs from spec wording in a way capstone should reconcile), **NOT_SHIPPED** (explicitly absent), **NEW** (gm_combat spec section without a milestone item).

## Summary

| Milestone | Confirmed | Partial | Divergent | Aspirational |
| --- | --- | --- | --- | --- |
| M4.1 — Phase-Based Combat Redesign (11) | 2 | 3 | 2 | 4 |
| M4.2 — Action Economy & Declarations (11) | 4 | 4 | 0 | 3 |
| M4.3 — Status Conditions (10) | 0 | 0 | 0 | 10 |
| M4.4 — Death, Dying & Resurrection (12) | 2 | 2 | 1 | 7 |
| M4.5 — Dramatic Dice System (9) | 0 | 0 | 0 | 9 |
| M4.6 — Social, Travel & Gathering (12) | 0 | 0 | 0 | 12 |

Cross-cutting:
- Combat is **turn-based** (round_number, current_turn_index, initiative_order) in `apps/agent/session_data.py:46-52`, not phase-based with 4 beats. The CombatAgent (`apps/agent/combat_agent.py:26-44`) drives the loop by free-form LLM tool calls (`resolve_enemy_turn`, `request_death_save`, `end_combat`), not a state machine.
- DB persistence uses table `combat_instances` (single `data JSONB` column, `scripts/migrations/001_initial_schema.sql:175-180`), not the spec's `combat_encounters` with phase tracking columns. State is stored in PostgreSQL, not Redis.
- No condition system exists at all: no `character_conditions` table, no `apply_condition`/`tick_conditions`/`get_condition_effects`, no condition data structures. Exhaustion only appears as narrative cue strings (`apps/agent/fatigue_narration.py:29-36`).
- No dramatic-dice flag on any roll result packet (`AttackResult`, `SavingThrowResult`, `DeathSaveResult`, `CheckResult` all lack `dramatic` / `context`). DICE_ROLL events emitted by `combat_turn.py` and `check_tools.py` carry roll/total/success but not `dramatic`.
- No social/travel/gathering systems: no `resolve_social_check`, `resolve_travel_segment`, `resolve_gathering`, `start_travel` symbols. `WildernessAgent` (`apps/agent/wilderness_agent.py:36-52`) is a 52-line stub that reuses the gameplay tool set — no travel mode, encounter table, navigation DC, or exhaustion logic.
- NPC disposition system exists (`apps/agent/tool_support.py:76-83` `DISPOSITION_ORDER = ["hostile", "wary", "neutral", "friendly", "trusted"]` + `db_mutations.set_npc_disposition`) but the tier name **"wary"** diverges from the spec's **"unfriendly"** (gm_combat L671). Capstone should reconcile naming.
- Mortaen mechanic surface is entirely aspirational: no `death_counter`, no `determine_death_cost`, no Mortaen scene wiring. The patron god is present only in lore/whisper data (`apps/agent/god_whisper_data.py`, `apps/agent/creation_deities.py`).

## Coverage matrix — spec section to milestone bucket

| gm_combat section (line range) | M4.x bucket | Notes |
| --- | --- | --- |
| Dramatic Dice System — design principle, always/contextual/never tables, `is_dramatic` pseudocode (L11-87) | M4.5 | All categories and `is_dramatic` are unimplemented (see M4.5 rows below). |
| Combat System — Phase-Based — design principle, Action Economy, Declaration categories table (L89-121) | M4.1 + M4.2 | Six declaration types live only in spec; no enum, no validation. |
| Combat System — Declaration Enhancers (L108-121) | M4.2 | Cunning Action, Extra Attack, Hit and Run, Command Lesser, Quick Change, Shield Bash — none implemented. |
| Combat System — Reactions / Voice Interrupts (L123-132) | M4.1 Beat 3 + **NEW** | "One reaction per phase," trigger types ("when hit"/"when ally hit"/"when enemy casts"), Stamina/Focus cost on reactions — none in code. Spec section as a whole has no dedicated acceptance row in M4.1. |
| Combat System — Companion Declaration (L134-136) | M4.1 Beat 1 + **NEW** | "Player can direct or let DM decide" — not enforced; companion turn is just `resolve_enemy_turn` with `enemy_id == companion.id`. |
| Combat System — Initiative (L138-157) | M4.1 | Basic d20+DEX confirmed. Surprise, Cunning Reflexes, Alert, Assassinate (L154-157) are NEW (no row in M4.1 acceptance). |
| Combat System — Combat Phase Flow / Four Beats (L159-191) | M4.1 | Spec source for Beat 1-4 acceptance criteria. Implementation is turn-based, not beat-based. |
| Combat System — Hesitation timer & defend fallback (L169) | M4.1 + **NEW** | 8s solo / 10-15s multi → automatic Defend declaration — not in code, not in acceptance. |
| Combat System — Simultaneous Resolution Shortcut (L193-195) | M4.1 + **NEW** | Order-dependent optimization — not in acceptance. |
| Combat System — Combat End (L197-199) | M4.1 | `end_combat` tool covers victory/defeat/fled (confirmed). |
| Combat Math — Attack Rolls (L203-210) | M4.2 | `resolve_attack` and `attack_modifier` in `check_resolution.py:240-304` confirmed. |
| Combat Math — Armor Class table (L212-220) | M4.2 | `calculate_ac` in `creation_rules.py:124-147` confirmed. |
| Combat Math — Weapon Damage table (L222-232) | M4.2 | 1d4-1d8 present; 1d10/1d12 absent (no greataxe/greatsword in `content/items.json` or `creation_classes.py:28-38`). |
| Combat Math — Cantrip Scaling (L234-242) | M4.2 + **NEW** | Level-scaled cantrip damage (1d6/2d6/3d6/4d6) — no scaling helper, no acceptance row. |
| Combat Math — Combat Pacing Target (L244-250) | **NEW (CONTEXT)** | 3-5 round target. Design directive, not a deliverable. |
| Combat Math — Saving Throws (L252-259) | M4.2 | `resolve_saving_throw` in `check_resolution.py:310-352` confirmed. |
| Status Effects — Combat / Environmental / Magical condition tables (L263-301) | M4.3 | All 20+ conditions exist only in spec prose; no enum, no DB. |
| Status Effects — Concentration (L303-312) | M4.3 + **NEW** | Concentration check after damage, one-at-a-time, Hollowmoth -1, etc. — no acceptance row in M4.3 (only Hollowed condition gets one). |
| Status Effects — Phase-Based Condition Interactions (L314-322) | M4.3 + **NEW** | Prone-costs-declaration, Grappled-costs-declaration, Stunned-skips-phase, Frightened/Charmed declaration restrictions — implicit in M4.3 but not called out in acceptance. |
| Resting (L326-338) | **NEW** | Short/Long rest exist as pure functions in `apps/agent/rest_mechanics.py` but are not in any M4.x acceptance — closest is M4.1 Beat 4 "stamina regen" line which is intra-phase not inter-encounter. |
| Death and Dying — Fallen state + instant death threshold (L342-350) | M4.4 | Fallen flag set in `combat_turn.py:113-115`; instant death not implemented. |
| Death and Dying — Death Saves (L352-371) | M4.4 | `combat_resolution.resolve_death_save` confirmed. |
| Death and Dying — Hollowed Death (L373-404) | M4.4 | Three sub-phases (Corruption Takes Hold / Hollow Rise / Resolution), Temporary Hollowed creature — none implemented. |
| Death and Dying — Mortaen's Domain (L406-414) | M4.4 | Narrative scene wiring — aspirational. |
| Death and Dying — Cost Engine (L416-480) | M4.4 | `determine_death_cost`, `select_cost`, all four tiers (Gentle/Moderate/Severe/Devastating) — aspirational. |
| Death and Dying — Resurrection Location (L482-506) | M4.4 | 4-priority anchor hierarchy + time cost table — aspirational. |
| Death and Dying — Party Death (L508-518) | M4.4 | Total wipe handling — aspirational. |
| Death and Dying — Companion Death in Combat (L520-526) | M4.4 | Spec: auto-stabilizes after 3 failures. Code: marks `is_conscious=False` on KO with no auto-stabilize logic — see M4.4 row. |
| Death and Dying — Mortaen's Patron Interaction (L528-536) | M4.4 | Deathsense / +2 death saves / free first death / domain-scene-as-follower / personalized Mortaen's Debt — aspirational. |
| Death and Dying — Death and Resurrection Spells (L538-548) | M4.4 + **NEW** | Heal Wounds, Revivify, Resurrection, Greater Restoration, Divine Intervention — cross-link to Phase 3 Magic. No acceptance row in M4.4. |
| Death and Dying — Implementation pseudocode (L550-611) | M4.4 (CONTEXT) | Reference shape for `DeathSystem` class — not implemented. |
| Social Encounter Resolution — Dramatic Dice Rule (L619-632) | M4.5 + M4.6 | Cross-link. |
| Social Encounter Resolution — Tier 1 Simple Checks (L636-688) | M4.6 | DISPOSITION_DC_MODIFIER table (L668-674), disposition shift table (L678-685) — aspirational. |
| Social Encounter Resolution — Intimidation double edge (L687) | M4.6 + **NEW** | Behavioral consequence after intimidation success — no acceptance row. |
| Social Encounter Resolution — Tier 2 Contested Exchanges (L689-729) | M4.6 + **NEW** | Contested skill resolution + failure consequences — implicit in "Diplomat de-escalation" acceptance but not its own row. |
| Social Encounter Resolution — Tier 3 Structured Social Scenes (L731-803) | M4.6 | "Structured social scenes with tension curve" acceptance covers this. Argument categories (L767-777), NPC resistance personality tags (L779-791), De-escalate-in-combat sub-flow (L793-803) — partially folded in. |
| Social Encounter Resolution — Social Abilities Quick Reference (L805-825) | **NEW** | Catalog of 17 archetype-attached social abilities (Diplomat, Spy, Bard) — belongs to M2.2 archetype-ability content, not M4.6. |
| Social Encounter Resolution — Disposition system feed (L826-836) | M4.6 + **NEW** | Pricing / knowledge gates / quest access / workspace access / mentor availability hookpoints — no acceptance row. |
| Social Encounter Resolution — What Social Encounters Do NOT Include (L838-844) | **NEW (CONTEXT)** | Negative design boundaries. |
| Travel and Exploration — Travel Modes table (L852-860) | M4.6 | Spec uses Compressed/Scenic/Dangerous tiers; M4.6 acceptance uses **Fast/Normal/Careful** — naming divergence noted below. |
| Travel and Exploration — Travel Time tables (L862-880) | M4.6 + **NEW** | Distance × Mode duration matrix + in-game time passed — no acceptance row. |
| Travel and Exploration — Travel Encounters + `roll_travel_encounter` pseudocode (L882-916) | M4.6 | Implicit in "Encounter triggers based on location danger rating" acceptance. |
| Travel and Exploration — Navigation and Getting Lost (L918-936) | M4.6 | "Navigation checks with failure consequences" acceptance covers this. |
| Travel and Exploration — Exhaustion During Travel (L938-951) | M4.6 + M4.3 | Forced march / no rations / extreme weather stack rules — depends on M4.3 Exhausted condition (also aspirational). |
| Travel and Exploration — Camp and Rest During Travel (L953-969) | **NEW** | Camp decisions (location/watch/campfire), Rest quality matrix — no acceptance row in M4.6 or M4.3. |
| Gathering and Resource Discovery — `resolve_gathering` pseudocode (L977-1014) | M4.6 | Skill-routing (Survival/Nature/Arcana) confirmed in spec; aspirational in code. |
| Gathering and Resource Discovery — Regional Resource Tables (L1016-1028) | M4.6 | Acceptance "Regional resource tables return location-appropriate resources" — aspirational. |
| Gathering and Resource Discovery — Gathering Rules (L1030-1042) | M4.6 + **NEW** | Time cost (30 min-2 hr), one-attempt-per-segment, skill-tier-gated materials, companion-errand gathering — only partly in acceptance. |
| Gathering and Resource Discovery — Gathering Nodes / Fixed Locations (L1044-1060) | M4.6 + **NEW** | Node types, respawn cadence (1-3 d / 1-2 d / 3-7 d / 7+ d / one-time / persistent), discovery via Perception, multiplayer competition — only the discovery line is in M4.6 acceptance. |

## M4.1 — Phase-Based Combat Redesign

| Acceptance item | Evidence | Status |
| --- | --- | --- |
| `narrative_hint()` fixed: no longer returns "critical success" for non-nat-20 rolls | `apps/agent/rules_engine.py:346-361` — d20==1 → "critical failure", d20==20 → "critical success", else margin-based ("failed" / "barely failed" / "barely succeeded" / "succeeded comfortably" / "succeeded overwhelmingly"). Spec's M1.1 tech debt is closed. | confirmed |
| `resolve_attack` and `resolve_saving_throw` use `CheckResult` critical flags | `CheckResult` carries `critical_success: bool` + `critical_failure: bool` (`check_resolution.py:36-37, 174-175`). **`AttackResult`** has a single `critical: bool` only (`check_resolution.py:54-65`) — no separate critical_failure. **`SavingThrowResult`** (`check_resolution.py:69-78`) has **neither** critical flag. Both still derive narrative-hint from raw d20 (lines 303, 351). | partial |
| Combat state machine transitions through all states in correct order (`idle → encounter_start → initiative_roll → [phase_loop] → combat_end`) | `apps/agent/session_data.py:46-52` `CombatState` exposes `combat_id`, `participants`, `initiative_order`, `round_number`, `current_turn_index`, `location_id`. No phase/beat field, no `encounter_start` state, no explicit state-machine enum. Lifecycle is driven by LLM tool sequence `start_combat → resolve_enemy_turn × N → end_combat` (`apps/agent/combat_agent.py:13-23`). | divergent |
| Initiative roll uses `d20 + DEX modifier` and correctly orders resolution within a phase | `apps/agent/combat_resolution.py:32-57` `roll_initiative` — d20 + `attribute_modifier(dexterity)`, sorts entries descending by total. Tests: `apps/agent/tests/test_rules_combat.py:24-56` cover sort/DEX/RNG/empty cases. | confirmed |
| Beat 1 collects declarations from player, companions, and enemies before any resolution | No declaration collection layer. Player intent → LLM → `resolve_enemy_turn` per actor sequentially. No `DECLARATION_TYPES` enum, no `pending_declarations` field on `CombatState`. | aspirational |
| Beat 2 resolves all actions without emitting narration, produces result packets with dramatic flags | `resolve_enemy_turn` (`combat_turn.py:33-172`) resolves and emits a DICE_ROLL event immediately — no silent batch resolution. AttackResult has no `dramatic` field. | aspirational |
| Beat 3 narration includes reaction windows where DM pauses for dramatic dice | No reaction infrastructure: no `Reaction` type, no `pause_for_dice` instruction in narration packets, no `reactions_available` field on CombatParticipant. | aspirational |
| Beat 4 processes death saves, stamina regen, and condition tick-downs | Death save: `request_death_save` tool exists (`combat_turn.py:175-270`) but is **invoked by the LLM**, not auto-fired at end-of-phase. Stamina regen: no per-round regen path in combat code (rest mechanics live in `rest_mechanics.py` for short/long rest only). Condition tick-down: no condition system. | partial |
| Phase loop repeats until combat_end is triggered (all enemies defeated, retreat, etc.) | `end_combat` tool (`combat_end.py:24-119`) accepts `victory`/`defeat`/`fled` outcomes — invoked by the LLM, not by an automatic end-condition check on the engine. Turn-based, not phase-loop. | divergent |
| `advance_combat_phase` is a pure function with no side effects | No such symbol anywhere in `apps/agent/`. | aspirational |
| Tests cover full combat lifecycle from encounter_start through combat_end | `apps/agent/tests/test_combat_tools.py` (717 lines) covers `start_combat`/`resolve_enemy_turn`/`request_death_save`/`end_combat` against the current turn-based model. No phase-loop test exists. | partial |

**Notes:**
- DB migration `combat_encounters` table updated with phase tracking columns (deliverable list, not numbered acceptance): table is named `combat_instances`, has a single `data JSONB` column (`scripts/migrations/001_initial_schema.sql:175-180`) and no phase columns. **divergent**.
- Combat state in Redis (deliverable list): state is persisted to PostgreSQL via `db_mutations.save_combat_state` (`apps/agent/db_mutations.py:203-211`), not Redis. **divergent**.

## M4.2 — Action Economy & Declarations

| Acceptance item | Evidence | Status |
| --- | --- | --- |
| All 6 declaration types are defined with validation rules (Attack/Ability/Interact/Maneuver/Defend/Retreat) | No `Declaration`/`DeclarationType` enum, no validation function. The six categories exist only in `docs/game_mechanics/game_mechanics_combat.md:99-106`. `system_prompts.COMBAT_SYSTEM_PROMPT` likely references these in prose, but the engine has no declaration model. | aspirational |
| Only one declaration per actor per phase (enhancers expand resolution, not declaration count) | No declaration count enforcement (because no declarations). | aspirational |
| Attack roll correctly applies proficiency bonus when weapon-proficient | `apps/agent/check_resolution.py:240-254` `attack_modifier` adds `proficiency_bonus(level)` unconditionally; weapon-proficiency lookup is **not gated** — every attacker gets proficiency. Spec wording allows "if proficient with weapon" (gm_combat L208) but the deliverable says "applies proficiency bonus when weapon-proficient." Code applies it always. **divergent** in strict reading but matches the "no proficiency gating in MVP" reality. | confirmed (with caveat) |
| AC calculation is correct for all armor categories (unarmored, light, medium, heavy) | `apps/agent/creation_rules.py:124-147` `calculate_ac` — unarmored = 10 + DEX, light (`ac_bonus < 12`) = full DEX, medium (`12-14`) = min(DEX, 2), heavy (`>= 15`) = no DEX, +shield bonus. Tests: `apps/agent/tests/test_creation_rules.py`. | confirmed |
| Weapon damage ranges from 1d4 to 1d12 + correct attribute modifier | Damage dice present in `apps/agent/creation_classes.py:28-38` and `content/items.json` (1d4 dagger, 1d6 shortbow/handaxe/quarterstaff/mace, 1d8 longsword/warhammer/rapier). **No 1d10 or 1d12 weapons** anywhere (no greataxe, greatsword, halberd). Attribute modifier on damage rolls is **not added** in `check_resolution.resolve_attack` (lines 257-304) — only weapon's `damage` notation is rolled (e.g. `1d4` → 1-4), no STR/DEX mod on damage. | partial |
| Critical hit (natural 20) doubles damage dice | `apps/agent/check_resolution.py:286-288` — on critical, rolls damage notation a second time and adds it. Confirmed. | confirmed |
| `request_attack` returns structured result with hit/miss/crit, damage, and dramatic flag | `apps/agent/check_tools.py:262-352` returns hit/roll/attack_total/target_ac/damage/damage_type/critical/target_hp_remaining/target_killed/narrative_hint. **No `dramatic` flag.** | partial |
| `request_save` returns structured result with success/fail and margin | `apps/agent/check_tools.py:355-430` `request_saving_throw` returns outcome/save_type/roll/modifier/total/dc/margin/effect_applied/narrative_hint. **No `dramatic` flag.** Tool is named `request_saving_throw`, not `request_save`. | partial |
| Declaration enhancers (Cunning Action, Extra Attack) correctly expand single declarations | No enhancer logic. No grep hits for `cunning_action`, `extra_attack`, `hit_and_run`, `shield_bash`, `command_lesser`, `quick_change`. Sprint-002 M2.3 narration mentions Extra Attack at L10 but no mechanic. | aspirational |
| All combat math functions are pure with no side effects | `attribute_modifier`, `proficiency_bonus`, `attack_modifier`, `resolve_attack`, `resolve_saving_throw`, `resolve_check`, `calculate_ac`, `roll_initiative`, `resolve_death_save`, `hp_threshold_status`, `calculate_combat_xp` are all pure (accept optional `rng`, no IO). | confirmed |
| Tests cover all declaration types, armor categories, and weapon damage ranges | `apps/agent/tests/test_rules_resolution.py`, `test_creation_rules.py`, `test_rules_combat.py` cover attack resolution, AC, damage dice, but **no declaration-type tests** (because no model). | partial |

**Other deliverables (not numbered acceptance):**
- Pure function `calculate_ac(armor, dex_modifier)`: confirmed at `apps/agent/creation_rules.py:124`. Signature is `(equipment, dexterity)` (passes equipment dict containing armor/shield, raw dex score) — wording differs from spec but the math is right.
- Pure function `resolve_attack(attacker_stats, target_ac, weapon)`: confirmed at `apps/agent/check_resolution.py:257`. Signature is `(attacker_data, weapon, target_ac, target_hp, rng)` — note the spec orders `attacker_stats, target_ac, weapon` while code is `attacker_data, weapon, target_ac, target_hp`. Wording divergence.
- Pure function `resolve_declaration(declaration_type, actor, targets, context)`: aspirational. No such function exists.
- Agent tool `request_attack(attacker_id, target_id, weapon_id)`: signature in code is `request_attack(context, target_id, weapon_or_spell)` — current player is implicit, no attacker_id; weapon is a string (looked up in equipment dict).
- Agent tool `request_save(target_id, save_type, dc)`: implementation is `request_saving_throw(context, save_type, dc, effect_on_fail)` — current player is implicit, no target_id.

## M4.3 — Status Conditions

| Acceptance item | Evidence | Status |
| --- | --- | --- |
| All 20+ conditions defined with mechanical effect, clearance method, and stack behavior | No condition catalog in code or content. The Combat / Environmental / Magical condition tables at `gm_combat:269-301` are documentation only. | aspirational |
| `apply_condition` correctly adds condition to character state with duration and source tracking | No such function in `apps/agent/`. | aspirational |
| `remove_condition` correctly removes specific condition instances | No such function. | aspirational |
| `tick_conditions` decrements duration-based conditions in Beat 4 (Wrap) and removes expired ones | No such function. Beat 4 itself is aspirational (see M4.1). | aspirational |
| Conditions requiring saves to clear trigger save checks during tick | Aspirational. | aspirational |
| `get_condition_effects` correctly aggregates effects from multiple simultaneous conditions | No such function. No condition modifier-aggregation surface anywhere in the rules engine. | aspirational |
| Hollowed condition has unique behavior distinct from standard conditions | No `hollowed_stage` field on player record or session state. Mentioned in spec at `gm_combat:299-300` and surfaced only in `rules_engine.py:171, 200` (Endurance/Medicine capability narration strings). | aspirational |
| DB migration creates `character_conditions` table with correct schema | No `character_conditions` table in any of `scripts/migrations/001-017_*.sql`. | aspirational |
| Client displays condition icons in combat tracker and persistent bar | No condition icon component under `apps/mobile/src/components/hud/`. | aspirational |
| Tests cover applying, stacking, ticking, and clearing every condition type | No condition tests. | aspirational |

**Adjacent state that exists but is not a condition system:**
- `CombatParticipant.is_fallen: bool` (`session_data.py:38`) is a single-purpose flag, not a generic condition.
- `apps/agent/fatigue_narration.py:59-63 get_exhaustion_narrative(stacks)` is a string lookup keyed on a stack count — but **no persisted stack count** exists on any character/session record. The function reads a parameter that nothing calls it with.

## M4.4 — Death, Dying & Resurrection

| Acceptance item | Evidence | Status |
| --- | --- | --- |
| 0 HP triggers Fallen state with death save requirement each phase | Fallen flag is set when HP hits 0 in `apps/agent/combat_turn.py:113-115` (`target.is_fallen = True`). **No automatic per-phase death save** — `request_death_save` is a separate LLM-invoked tool. No engine-side schedule. | partial |
| Death save uses d20 with no modifiers; 10+ is success, <10 is failure | `apps/agent/combat_resolution.py:60-106` `resolve_death_save` — `dice_roll("d20")` with no modifier, d20≥10 success, else failure. Confirmed. | confirmed |
| 3 successes stabilizes; 3 failures triggers death | `combat_resolution.py:93-94` — `stabilized = new_successes >= 3`, `dead = new_failures >= 3`. Confirmed. | confirmed |
| Instant death fires when excess damage >= max HP | No `excess_damage` calculation anywhere in `apps/agent/`. `resolve_attack` clamps `new_hp = max(0, target_hp - damage)` (`check_resolution.py:290`) — overflow is silently dropped, not converted into an instant-death path. | aspirational |
| Hollowed Death (Stage 2+) creates DM-controlled Temporary Hollowed with character abilities + 1d6 necrotic | No `hollowed_stage` field, no Temporary Hollowed creature spawn path, no necrotic damage type or 1d6 add. | aspirational |
| Death cost correctly escalates across all tiers (Gentle through Devastating) | No `death_counter` field on player record, no `determine_death_cost`, no `select_cost`, no cost-tier enum. | aspirational |
| Mortaen patron characters get +2 death saves and skip first death cost | `resolve_death_save` does not branch on patron. Death-save roll is unmodified d20 (`combat_resolution.py:70-71`) — no `+2` for Mortaen followers and no `is_first_death_free` skip. | aspirational |
| Resurrection places character at nearest valid anchor point with correct priority fallback | No anchor-point system, no `find_nearest_anchor`, no `resurrection_anchor_points` table. | aspirational |
| Party wipe processes all deaths independently and resurrects at shared anchor | No party-wipe handler. | aspirational |
| Companion death auto-stabilizes without permanent consequences | When companion target reaches 0 HP, `combat_turn.py:117-119` marks `session.companion.is_conscious = False` and records a companion memory. **No auto-stabilize logic** — the companion just stays unconscious; no auto-revive at end of combat, no narrative protection enforcement. Spec calls for explicit 3-failure → auto-stabilize behavior. | divergent |
| DB migrations create all three tables with correct schemas | No migrations for `death_saves`, `character_death_history`, or `resurrection_anchor_points`. (Death save counters are tracked on the in-memory `CombatParticipant` only: `session_data.py:39-40`.) | aspirational |
| Tests cover every death tier, Hollowed death, instant death, party wipe, and companion death | `apps/agent/tests/test_rules_combat.py:65-150` and `test_combat_tools.py:464-583` cover the basic death save mechanic (success/failure/stabilize/death/nat-20/nat-1). No tests for tiers, Hollowed Death, instant death, party wipe, or companion auto-stabilize. | partial |

**Other deliverables (not numbered acceptance):**
- Agent tool `resolve_death_save(character_id)`: implementation is `request_death_save(context)` (`combat_turn.py:175-270`) — operates on the current player implicitly, no character_id.
- Agent tool `get_death_cost(character_id)`: aspirational.
- Agent tool `trigger_character_death(character_id)`: aspirational. Currently when the player's death counter reaches 3 failures, `request_death_save` returns `dead: true` in its JSON but does **not** initiate the Mortaen scene, apply a cost, or handle resurrection — that flow is entirely missing.

## M4.5 — Dramatic Dice System

| Acceptance item | Evidence | Status |
| --- | --- | --- |
| `evaluate_dramatic_context` returns `True` for all always-dramatic scenarios | No such function anywhere in `apps/agent/`. (The only occurrences of "dramatic" in source are narrative-style adverbs in tool docstrings — `progression_tools.py:33`, `system_prompts.py:115/177/195`, `bg_event_handlers.py:153`, `combat_turn.py:43`.) | aspirational |
| `evaluate_dramatic_context` returns `True` for contextually dramatic scenarios when conditions met | Aspirational. | aspirational |
| `evaluate_dramatic_context` returns `False` for never-dramatic scenarios | Aspirational. | aspirational |
| All roll result packets include `dramatic` flag and `context` dict | `CheckResult`, `SkillCheckResult`, `AttackResult`, `SavingThrowResult`, `DeathSaveResult` in `check_resolution.py` and `combat_resolution.py` lack `dramatic: bool` and `context: dict` fields. | aspirational |
| Existing dice_result events updated to include dramatic flag without breaking consumers | DICE_ROLL events emitted from `combat_turn.py:131-143` (attack), `combat_turn.py:236-249` (death_save), `check_tools.py:82-93` (skill_check), `check_tools.py:312-324` (attack from player), `check_tools.py:394-405` (saving_throw), `check_tools.py:452-461` (narrative dice) — none include `dramatic`. | aspirational |
| Client animated d20 overlay fires only when `dramatic: True` | Mobile client renders DICE_ROLL events (see `apps/mobile/src/audio/event-types.ts`); no `dramatic` gating because the server-side flag does not exist. | aspirational |
| DM pauses narration during Beat 3 for dramatic roll reveals | Beat 3 itself is aspirational (see M4.1). No `pause_for_dice` instruction in narration packets. | aspirational |
| `evaluate_dramatic_context` is a pure function with no side effects | Function does not exist. | aspirational |
| Tests cover all always/contextual/never categories with representative game states | None. | aspirational |

## M4.6 — Social Encounters, Travel & Gathering

| Acceptance item | Evidence | Status |
| --- | --- | --- |
| Social DC correctly derived from NPC disposition (0-10 scale) | No social DC derivation function. NPC disposition exists as a five-name tier (`apps/agent/tool_support.py:76-78` `DISPOSITION_ORDER = ["hostile", "wary", "neutral", "friendly", "trusted"]`) — spec's 0-10 scale is not represented; spec's `DISPOSITION_DC_MODIFIER` table (gm_combat L668-674) using "unfriendly" diverges from code's "wary." | aspirational |
| Social encounters follow structured tension curve with distinct phases | No Tier 1 / Tier 2 / Tier 3 social-resolution layer in code. No "argument phase" structure. | aspirational |
| Diplomat archetype can attempt de-escalation during combat encounters | No `de_escalate` ability/tool. Diplomat archetype exists in chassis (`apps/agent/rules_engine.py:51` `ARCHETYPE_RESOURCE_CONFIG`) but has no combat-de-escalate path. | aspirational |
| All 3 travel modes produce correct encounter rates and foraging availability | No travel-mode enum. `apps/agent/wilderness_agent.py:36-52` is a 52-line stub that reuses the gameplay tool set. No "Fast/Normal/Careful" (or spec's "Compressed/Scenic/Dangerous") — naming divergence between milestone deliverables and gm_combat spec. | aspirational |
| Navigation failure leads to lost time or wrong-area consequences | No navigation check, no terrain DC table. | aspirational |
| Exhaustion accumulates over extended travel and affects checks | `fatigue_narration.get_exhaustion_narrative(stacks)` returns a string per stack count, but no character record stores stack count, no accumulator advances it on travel, no math hook reduces checks. | aspirational |
| Gathering checks are gated by appropriate skills (Perception, Survival, Nature) | No `resolve_gathering` function. The three skills exist in `apps/agent/rules_engine.py:89-113 SKILLS` (Perception/Survival/Nature) but no gathering-skill routing logic. | aspirational |
| Regional resource tables return location-appropriate resources | No `resource_table` field on any `content/locations.json` record. Spec's regional matrix (gm_combat L1020-1028) is documentation-only. | aspirational |
| Discovery moments trigger narrative beats for rare resource finds | No discovery-flag emission path. | aspirational |
| DB migrations create `travel_state` and `gathering_nodes` tables | No such migrations. | aspirational |
| All resolution functions are pure with no side effects | No resolution functions to test purity of. | aspirational |
| Tests cover social disposition ranges, all travel modes, and gathering skill gates | None. | aspirational |

**Adjacent state that exists but does not satisfy this milestone:**
- NPC disposition system has a working backbone: `db_mutations.set_npc_disposition`, `db_queries.get_npc_disposition`, `quest_tools._clamp_disposition_shift` for clamping, `session_tools.update_npc_disposition` agent tool. This is the **infrastructure** that a Tier-1 social-DC layer should sit on top of, but the social-check resolution itself is absent. **partial** for foundational data; **aspirational** for every M4.6 acceptance item.

## Material gaps surfaced

Consolidated list of items the capstone should consider unchecking or reframing in `docs/milestones/04_combat.md`. Suggested pointer comment for each row: `<!-- see audit/phase-4-combat.md -->`.

**M4.1 — Phase-Based Combat Redesign**
- The entire phase-loop architecture (Beats 1-4) is unshipped. Combat is turn-based with a free-form LLM tool loop. Capstone should either (a) acknowledge that M4.1 is a rewrite, not a refactor, or (b) close M4.1 as deferred and split into smaller milestones.
- Two items in the deliverable list are factually divergent: state is in PostgreSQL `combat_instances` (single JSONB), not Redis; the table is `combat_instances`, not `combat_encounters`. Capstone may rename the deliverable or pin a separate migration.
- `resolve_attack` and `resolve_saving_throw` only partially use CheckResult's critical flags. AttackResult has a single `critical: bool`; SavingThrowResult has none. Capstone may either add the missing fields (small change) or mark the acceptance row partial.

**M4.2 — Action Economy & Declarations**
- Six declaration types (Attack/Ability/Interact/Maneuver/Defend/Retreat) and the six declaration enhancers (Cunning Action, Extra Attack, Hit and Run, Command Lesser, Quick Change, Shield Bash) are not encoded anywhere. Capstone may carry this forward as a single deliverable.
- Weapon damage tops out at 1d8 in code; the spec's 1d12 (greataxe) and 1d10 entries are absent.
- Damage rolls do not add the attribute modifier (`check_resolution.resolve_attack:283-288` rolls only the weapon's damage notation). Spec calls for `1d8 + STR`, `1d4 + DEX/STR`, etc.
- Weapon proficiency gating is not enforced — every attacker gets the proficiency bonus on attack rolls. Spec wording uses "if proficient with weapon." Capstone decides whether to gate (rules-engine change) or relax wording.
- `request_attack` returns no dramatic flag; ditto `request_save`. Cross-link to M4.5.
- Tool naming divergence: agent tools are `request_attack(context, target_id, weapon_or_spell)` and `request_saving_throw(context, save_type, dc, effect_on_fail)`; spec uses `request_attack(attacker_id, target_id, weapon_id)` and `request_save(target_id, save_type, dc)`. Tools take the current player implicitly. Capstone reconciles.

**M4.3 — Status Conditions**
- Entire condition system is aspirational. No table, no apply/remove/tick/aggregate, no client UI. The 20+ conditions live only in spec prose.
- `fatigue_narration.get_exhaustion_narrative` is dead-end code — accepts a stack count that nothing computes or persists.

**M4.4 — Death, Dying & Resurrection**
- Mortaen scene + Cost Engine + tiered cost escalation + anchor-point hierarchy + party-wipe handler + Hollowed Death + instant-death threshold — all aspirational.
- Companion death is **divergent**: spec calls for auto-stabilize at 3 failures; code marks `is_conscious=False` and stops. No auto-stabilize path. No companion death-save tracker is invoked.
- Mortaen patron bonuses (+2 death saves, free first death) require a death-save modifier and a death-counter check that don't exist.
- The three DB tables (`death_saves`, `character_death_history`, `resurrection_anchor_points`) are absent. Death save counters live on the in-memory `CombatParticipant` only — they reset to 0 every encounter unless explicitly persisted. Capstone may want to flag this as a data-loss bug separate from the death-cost system.

**M4.5 — Dramatic Dice System**
- Entire system aspirational. No function, no flag, no event-payload field, no client gating. Capstone may consider this the highest-leverage M4 deliverable for audio-first tension (every other M4 milestone has more local impact).

**M4.6 — Social, Travel & Gathering**
- Three independent sub-systems, all aspirational. Disposition infrastructure (set/get/clamp + 5-tier order) is present but unused by social-resolution math.
- Naming divergence on travel modes: milestone says **Fast/Normal/Careful**; spec says **Compressed/Scenic/Dangerous**. Capstone reconciles.
- Naming divergence on disposition tiers: code uses **"wary"**; spec uses **"unfriendly"**. Capstone reconciles (also impacts M1.x social-DC work).
- Gathering nodes' respawn cadence, multiplayer competition, and node-discovery flow are NEW (see below).

## NEW spec sections without milestone items

These gm_combat sections are not covered by any M4.1-M4.6 acceptance row. Capstone should decide whether to fold each into an existing milestone (and add an acceptance row) or open a new deliverable.

**Combat structure (M4.1 territory)**
- **Reactions / Voice Interrupts (gm_combat:123-132)** — `one_reaction_per_phase` enforcement, named trigger types (`when_hit` / `when_ally_hit` / `when_enemy_casts` / `when_enemy_approaches`), Stamina/Focus cost on reactions. Currently only mentioned tangentially in Beat 3 acceptance.
- **Companion Declaration (gm_combat:134-136)** — "player can direct or DM decides" rule.
- **Hesitation timer + Defend fallback (gm_combat:169)** — 8s solo / 10-15s multi → auto-Defend declaration.
- **Surprise / Cunning Reflexes / Alert / Assassinate (gm_combat:154-157)** — initiative-time special-case rules.
- **Simultaneous Resolution Shortcut (gm_combat:193-195)** — order-irrelevant fast path.
- **Combat Pacing Target (gm_combat:244-250)** — 3-5 rounds per encounter (design directive, not a deliverable; worth pinning in M4.1 as a non-functional requirement).

**Combat math (M4.2 territory)**
- **Cantrip Scaling (gm_combat:234-242)** — 1d6/2d6/3d6/4d6 by level. Cross-link to Phase 3 Magic.

**Status (M4.3 territory)**
- **Concentration (gm_combat:303-312)** — concentration check after damage, one-spell-at-a-time, Hollowmoth -1 stack, etc.
- **Phase-Based Condition Interactions (gm_combat:314-322)** — Prone/Grappled cost declaration; Stunned/Paralyzed skip phase; Frightened/Charmed declaration restrictions. Implicit in M4.3 but not its own acceptance row.

**Resting (between M4.1 and M4.4 territory)**
- **Resting (gm_combat:326-338)** — short/long rest tables. `apps/agent/rest_mechanics.py` ships short/long rest as pure functions, but there is no acceptance row in M4.x. (Could be M1.x given the resource-pool tie-in, but currently unowned.)

**Death (M4.4 territory)**
- **Death and Resurrection Spells (gm_combat:538-548)** — Heal Wounds, Revivify, Resurrection, Greater Restoration, Divine Intervention all interact with the death system. Cross-link to Phase 3 Magic spell catalog.

**Social (M4.6 territory)**
- **Intimidation double edge (gm_combat:687)** — long-tail relationship damage from intimidation success.
- **Tier 2 Contested Exchanges as a standalone deliverable (gm_combat:689-729)** — currently folded into "structured tension curve" but is a distinct mechanic (player skill vs NPC opposing skill, failure consequence table).
- **Argument categories table (gm_combat:767-777)** and **NPC resistance personality tags (gm_combat:779-791)** — concrete data the Tier 3 resolver needs.
- **De-escalate-in-combat sub-flow (gm_combat:793-803)** — the player-actually-delivers-the-argument pattern. Touches M4.1 Beat 3.
- **Social Abilities Quick Reference (gm_combat:805-825)** — 17 archetype-attached social abilities. Belongs to M2.2 archetype-ability content, **not** M4.6. Capstone may want to move this row.
- **Disposition system feed (gm_combat:826-836)** — prices / knowledge gates / quest access / workspace access / mentor availability hookpoints that the social system should write to.

**Travel (M4.6 territory)**
- **Travel Time tables (gm_combat:862-880)** — distance × mode duration matrix + in-game time passed.
- **Camp and Rest During Travel (gm_combat:953-969)** — camp decisions (location/watch/campfire) + Rest quality matrix. Touches M4.3 (Exhausted condition) and M4.1 (rest mechanic).

**Gathering (M4.6 territory)**
- **Gathering Rules — one-attempt-per-segment, skill-tier gating, companion-errand alternative (gm_combat:1030-1042).**
- **Gathering Nodes — types, respawn cadence, discovery routes, multiplayer competition (gm_combat:1044-1060).**

## Cross-doc dependencies

- **M4.3 conditions ↔ M2.2 archetype reaction abilities (sprint-002 carryover)** — Reaction abilities need the reaction-trigger infrastructure that lives in M4.1 Beat 3. Phase-2 audit flagged this same dependency (`docs/milestones/audit/phase-2-archetypes.md:208`). Capstone may sequence M4.1 reactions before M2.2 reaction abilities.
- **M4.4 death-and-resurrection spells ↔ Phase 3 Magic spell catalog** — `Heal Wounds`, `Revivify`, `Resurrection`, `Greater Restoration`, `Divine Intervention` all need spell entries with focus cost + range + effect. Story-002 (Phase 3 audit) owns the spell catalog.
- **M4.4 Mortaen patron bonuses ↔ Phase 8 Patrons** — +2 death-save modifier, free first death, personalized Mortaen scene, Mortaen's Debt quest variant — all require the patron-attached-modifier hook from Phase 8 (currently aspirational per `docs/milestones/audit/phase-8-patrons.md`).
- **M4.6 social disposition feed ↔ Phase 6 NPCs + Phase 9 Economy** — knowledge gates, merchant pricing, quest access depend on the NPC/economy systems. Phase-9 (economy) ships disposition modifiers in pricing; the social-check resolver needs to write to that surface.
- **M4.6 travel ↔ Phase 5 World Simulation + Phase 7 Bestiary** — encounter tables, regional resource tables, world-time advancement, corruption levels — all live in world-data and bestiary territory. M4.6 cannot ship in isolation.
- **M4.3 Exhausted condition ↔ Phase 1 Skills (Endurance Master cap)** — Endurance Master narrates "Exhaustion caps at 3 stacks instead of 5" (`apps/agent/rules_engine.py:171-172`), but with no exhaustion stack tracking this is purely cosmetic. Cross-link to Sprint-001 phase-1-rules-engine audit.

## Capstone-transcludable notes

Short pointers safe to paste into `docs/milestones/04_combat.md` under the relevant acceptance bullets:

- **M4.1 overall:** the phase-loop architecture is unshipped; combat is turn-based with a free-form LLM tool loop. Only `narrative_hint` (deliverable 1) and `d20 + DEX` initiative (acceptance 4) are confirmed. State persisted to `combat_instances` (PostgreSQL JSONB), not Redis / `combat_encounters`. `<!-- see audit/phase-4-combat.md -->`
- **M4.2 overall:** combat math is mostly confirmed (`calculate_ac`, `resolve_attack`, `resolve_saving_throw`, critical doubling), but declarations + enhancers + 1d10/1d12 weapons + attribute-modifier-on-damage + dramatic flag are absent. `<!-- see audit/phase-4-combat.md -->`
- **M4.3 overall:** entire condition system is aspirational. `<!-- see audit/phase-4-combat.md -->`
- **M4.4 overall:** death save mechanic confirmed; Mortaen scene, cost engine, anchor points, Hollowed Death, instant death, party wipe, companion auto-stabilize, patron bonuses — all aspirational or divergent. Death-save counters are in-memory only (no DB persistence across encounters). `<!-- see audit/phase-4-combat.md -->`
- **M4.5 overall:** entire dramatic-dice system is aspirational. No `evaluate_dramatic_context`, no `dramatic` flag on any roll packet, no event-payload field. `<!-- see audit/phase-4-combat.md -->`
- **M4.6 overall:** social, travel, and gathering systems are all aspirational. NPC disposition infrastructure is present and working but unused by social resolution. Naming divergences to reconcile: travel modes (Fast/Normal/Careful vs Compressed/Scenic/Dangerous) and disposition tiers (wary vs unfriendly). `<!-- see audit/phase-4-combat.md -->`
