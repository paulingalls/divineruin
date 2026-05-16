# Phase 2 Audit — Archetypes (M2.1 + M2.2 + M2.3 + M2.4 + M2.5)

Sprint-002 / Milestone 2. Section-by-section walk of `docs/game_mechanics/game_mechanics_archetypes.md` against the milestone deliverables in `docs/milestones/02_archetypes.md` and shipped code under `apps/agent/`, `apps/server/`, `apps/mobile/`, `packages/shared/`, `content/`, and `scripts/migrations/`. Bias is toward unchecking when evidence is weak — capstone (story-004) will reconcile. Status legend: **confirmed** (DB/symbol exists and matches spec scope), **partial** (some pieces exist but the deliverable's surface area is incomplete), **aspirational** (no symbol/migration found; only narrative references), **divergent** (a related symbol exists but differs from spec wording in a way capstone should reconcile).

## Summary

| Milestone | Confirmed | Partial | Aspirational | Divergent |
| --- | --- | --- | --- | --- |
| M2.1 — Archetype Chassis | 1 (HP scaling + creation classes) | 1 (chassis surface scattered across two modules) | 3 (DB table, content seed, `get_archetype_chassis`) | 0 |
| M2.2 — Ability System | 0 | 1 (L4/L8 milestone markers in `LEVEL_PROGRESSION`) | 7 (both DB tables, content seed, electives, reactions, agent tool, swap logic) | 0 |
| M2.3 — Specialization & Milestones | 1 (L5 `specialization_fork` flag + milestone narrations) | 1 (narrative-only mentions of Extra Attack / capstone) | 4 (DB table, content seed, `resolve_milestone` tool, mobile UI) | 1 (L4 emits an `elective_techniques` milestone — see Sprint-001 finding) |
| M2.4 — Spell Acquisition | 0 | 1 (spell-tier training activity types in `content/`) | 8 (both DB tables, core spell map, scroll/mentor/discovery, prep rules, tier unlock gates, `learn_spell_from_scroll`, `prepare_spells`) | 1 (training durations are real-time seconds, not the spec's "cycles") |
| M2.5 — Martial Mentor System | 0 | 1 (generic training state machine + 2 mentor NPC stubs) | 6 (mentor_variants table, variant data, cultural attribution, training session loop bound to a base technique, agent integration, tests) | 0 |

Cross-cutting:
- No `content/archetypes/` directory (Sprint-001 finding, still true).
- `packages/shared/src/entities/` exports `Location, Npc, Item, Quest, GameEvent, Faction` only — no `Archetype | Ability | Spell | Milestone` types.
- No mobile screen exists for L5 specialization choice. Only `level-up-overlay.tsx` exists, and it renders "LEVEL UP / <newLevel> / <className>" with no fork affordance.

## Coverage matrix

Each spec section is tagged to an M2.x deliverable, marked **NEW** if not represented in `02_archetypes.md`, or **CONTEXT** if it is exposition with no per-section deliverable. Sections are listed in source-doc order.

| Spec section (line range) | M2.x bucket | Notes |
| --- | --- | --- |
| Archetype Profiles → Chassis Components (L9-22) | M2.1 | Lists the seven chassis components. M2.1 deliverables ("HP category, armor proficiencies, weapon proficiencies, save proficiencies, resource type, starting skill proficiencies") cover 6 of the 7; "Passive abilities," "Active abilities," "Reaction abilities," and "Archetype milestones" are deferred to M2.2/M2.3. |
| Warrior profile (L25-89) | M2.1 + M2.2 + M2.3 | HP/armor/weapon/saves/skills are M2.1. Passive + Core + Reaction + Elective L4 + Elective L8 tables are M2.2. Milestones table is M2.3. |
| Mage profile (L93-152) | M2.1 + M2.2 + M2.3 + M2.4 | Adds elective spell progression table → M2.4 spell tier unlock gates. |
| Druid profile (L156-210) | M2.1 + M2.2 + M2.3 + M2.4 | Spec calls out terrain-restricted preparation (M2.4 acceptance). |
| Cleric profile (L214-268) | M2.1 + M2.2 + M2.3 + M2.4 | Domain core/supreme determined by patron — cross-doc dep on Phase 8. |
| Rogue profile (L272-335) | M2.1 + M2.2 + M2.3 | Martial pattern (no spell progression). |
| Bard profile (L339-413) | M2.1 + M2.2 + M2.3 + M2.4 | Cross-source elective catalog access. Magical Secrets L10 cross-archetype steal. |
| Guardian / Skirmisher / Artificer / Seeker / Beastcaller / Warden / Paladin / Oracle / Spy / Whisper / Diplomat / Marshal profiles (L423-1144) | M2.1 + M2.2 + M2.3 + M2.4 (per archetype) | Same shape as the first 6. Paladin spell-tier cap (Major) and Diplomat/Marshal Major cap are explicit M2.4 acceptance items. |
| Core + Elective Ability Model — Overview (L1149-1158) | M2.2 (CONTEXT) | Establishes ~5 core + 2 electives shape — already encoded in `LEVEL_PROGRESSION` L4/L8 markers. |
| Caster Model: Core + Elective (L1159-1196) | M2.2 + M2.4 | Per-archetype "5 core" pattern (Core1 cantrip / Core2 reaction / Core3 role / Core4 spec / Core5 supreme). No code mirror exists. |
| Martial Model: Core + Elective Techniques (L1198-1209) | M2.2 | L4 / L8 pool-of-4 + swap-on-long-rest rule. |
| Hybrid and Support Models (L1211-1219) | M2.2 | Per-archetype core/elective counts. No code mirror exists. |
| Spell Acquisition System — Track 1 Slots (L1226-1228) | M2.4 | Spell slot capacity per level — no `character_spells.slots` column exists. |
| Spell Acquisition System — Track 2 Knowledge (L1230-1253) | M2.4 | Training cycles by tier (1/2/3/5/8). Discovery via scrolls, mentors, observation. |
| Spell Acquisition System — Track 3 Preparation (L1255-1264) | M2.4 | Long-rest preparation; Druid terrain rule; Paladin tier cap. |
| Spell Acquisition System — Why Three Tracks (L1266-1283) | M2.4 (CONTEXT) | Design rationale + example `can_prepare_spell()` pseudocode. |
| Martial Mentor-Style System — How It Works (L1287-1296) | M2.5 | 5-6 base + 3-4 mentor cycles. |
| Martial Mentor-Style System — Base vs. Variant (L1297-1305) | M2.5 | Property matrix. |
| Martial Mentor-Style System — Example Cleaving Blow Variants (L1307-1316) | M2.5 + **NEW** | Spec offers 4 named variants — not in `02_archetypes.md` acceptance, but is a concrete content target. |
| Martial Mentor-Style System — Mentor Integration (L1318-1337) | M2.5 | `TechniquesMentor` dataclass pseudocode. |
| Martial Mentor-Style System — Character Sheet Display (L1339-1347) | M2.5 + **NEW** | Attribution line display — not in `02_archetypes.md` acceptance. |
| Martial Mentor-Style System — Variant Design Principles (L1349-1354) | M2.5 (CONTEXT) | "Situationally stronger, not universally better"; one variant per technique. |

## M2.1 — Archetype Chassis

| Deliverable / Acceptance item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| `archetypes` DB table with columns for HP category, armor/weapon/save/skill proficiencies, resource type | No `CREATE TABLE archetypes` in `scripts/migrations/` (last migration is `017_training_content.sql`) | — | aspirational |
| Content seed `content/archetypes.json` with 18 entries | No `content/archetypes.json` and no `content/archetypes/` directory | — | aspirational |
| Migration to create + seed `archetypes` table | None | — | aspirational |
| Pure function `get_archetype_chassis(archetype_id)` returning full chassis | No grep hits anywhere in `apps/agent/` | — | aspirational |
| HP computation helpers: hit die by category (Martial 12/5, Primal-Divine 10/4, Arcane-Shadow-Support 8/3) | `apps/agent/hp_scaling.py:6-37` `ARCHETYPE_HP_CONFIG` — all 18 archetypes. Martial (warrior/guardian/skirmisher) = 12/5; Primal-Divine + Marshal (druid/beastcaller/warden/cleric/paladin/oracle/marshal) = 10/4; Arcane/Shadow/Support (mage/artificer/seeker/rogue/spy/whisper/bard/diplomat) = 8/3. Sprint-001 confirmed exhaustive L1-L20 coverage. | `apps/agent/tests/test_hp_scaling.py` (full file) | confirmed |
| 18 archetypes seeded in DB | DB seed not present; archetypes encoded in code: `ARCHETYPE_HP_CONFIG` + `apps/agent/rules_engine.py:30-53 ARCHETYPE_RESOURCE_CONFIG` + `apps/agent/creation_classes.py:51-372 CLASSES` (all 18 in each) | `test_hp_scaling.py`, `test_rules_pools.py`, `test_creation_tools.py` | partial — present in code, not in DB. Same situation Sprint-001 documented for M1.3. |
| Each archetype record specifies HP category + armor + weapon + saves + resource type + 3-5 starting skills | Split across three modules: HP in `hp_scaling.py`; saves + skill pool + starting equipment (armor + main_hand + shield) in `creation_classes.py:51-372`; resource type in `rules_engine.py:ARCHETYPE_RESOURCE_CONFIG`. Weapon proficiencies are encoded only as a `starting_equipment.main_hand` weapon item, not as a "what you may wield without disadvantage" proficiency list. | (see above) | partial — chassis is materialized but never assembled into a single record/function. The "what you may wield without disadvantage" surface area is not represented. |
| `get_archetype_chassis()` returns the correct chassis for each archetype (unit tests for all 18) | No such function exists | — | aspirational |
| HP at L1 and per-level HP gain match the category formula | `apps/agent/hp_scaling.py:41 calculate_hp` — `(level - 1) * (growth + (con_mod + 1) // 2)`; Sprint-001 confirmed exhaustively. | `test_hp_scaling.py` covers L1-L20, all 18 archetypes, CON ± | confirmed |
| Resource type assignment correct (martial → Stamina, arcane/divine → Focus, hybrid → both) | `rules_engine.py:30-53 ARCHETYPE_RESOURCE_CONFIG` (stamina_only / focus_only / focus_primary / split). Sprint-001 confirmed all 18. | `test_rules_pools.py:57 TestArchetypeResourceConfig` | confirmed |

**Reuse from Sprint-001 (do not re-litigate):** Sprint-001 finding "No `content/archetypes/` directory — 18 archetypes encoded in `ARCHETYPE_RESOURCE_CONFIG` + `ARCHETYPE_HP_CONFIG`" applies directly to M2.1 deliverables 1-3.

**Naming caveat for capstone:** `creation_classes.py:ClassData` exposes `hit_die: int` (e.g. Warrior=10, Guardian=12) which appears to be a D&D-style hit die value carried over from a previous design. It does not match either the spec's HP base (Warrior=12 base / 5 growth) or growth. The authoritative HP surface lives in `hp_scaling.py:ARCHETYPE_HP_CONFIG`. Capstone should decide whether to drop `ClassData.hit_die` or document it as cosmetic/legacy.

## M2.2 — Ability System (Core & Elective)

| Deliverable / Acceptance item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| `archetype_abilities` DB table | No `CREATE TABLE archetype_abilities` in any migration | — | aspirational |
| `character_abilities` DB table | No `CREATE TABLE character_abilities` in any migration | — | aspirational |
| Content seed for core abilities (≥1-2 per archetype) | No `content/abilities*` and no `content/archetype_abilities*` files | — | aspirational |
| Elective ability pool: L4 / L8 technique choices (4 per archetype at each level) | Spec narration markers exist: `apps/agent/leveling.py:76-84` L4 entry `milestone_type="elective_techniques"` ("L4 Elective techniques — martials choose from pool of 4. Standard spells unlock"); `:112-120` L8 entry identical milestone_type. **No pool content data exists** — the four-option pools per martial archetype (Warrior, Guardian, Skirmisher, Rogue, Spy, Bard, Paladin, Diplomat, Marshal — per spec L60-81, L306-327, etc.) are nowhere in code or `content/`. | `apps/agent/tests/test_leveling.py:27-33` verifies attribute-point timing at L4/L8 but no test asserts pool size/content | partial — milestone markers in place; pool data missing |
| Reaction ability support: interrupt-triggered abilities tied to combat windows | No grep hits for "reaction" abilities as a distinct ability category, no combat-window enforcement code | — | aspirational |
| Agent tool `request_ability_activation` — validates cost, applies effect, returns narration cue | No grep hits in `apps/agent/` (no `@function_tool` of this name) | — | aspirational |
| Ability swap on long rest (elective techniques swappable) | `apps/agent/rest_mechanics.py` only restores pools; no swap logic | `test_rest_mechanics.py` covers pool restore only | aspirational |
| Acquisition paths: Training (async), scrolls, mentors | Training scaffolding exists (`apps/server/src/training_state_machine.ts`) but is generic, not bound to abilities. No scroll system. Mentors are NPC stubs only (see M2.5). | — | aspirational for abilities (training infra exists for unrelated activities) |
| Every archetype has ≥1 core ability seeded | None — see "Content seed for core abilities" above | — | aspirational |
| `request_ability_activation` deducts correct Stamina/Focus, rejects on insufficient resources | Tool does not exist | — | aspirational |
| Elective L4 / L8 present exactly 4 choices per archetype | Pools not encoded | — | aspirational |
| Characters can swap elective techniques on long rest without losing the technique | Swap logic missing | — | aspirational |
| Reaction abilities only trigger during defined combat window | No reaction infrastructure | — | aspirational |
| `request_ability_activation` returns a narration cue string | Tool does not exist | — | aspirational |
| Unit tests cover core activation, elective activation, insufficient resources, reaction timing | None — no ability system to test | — | aspirational |

**Sprint-001 reference applicable here:** Sprint-001 noted that `validateSlotAvailability` in `apps/server/src/slot_validation.ts:37-67` accepts an `archetype` + `hasPortableLab` Artificer exception that is *dead code* (call sites pass neither). This sits in the M2.2 territory ("acquisition paths → training slot") and should be reconciled by capstone — either wire the Artificer flag through or remove it. Reference Sprint-001 phase-1 audit, "Cross-cutting observations" section.

## M2.3 — Specialization & Milestone Progression

| Deliverable / Acceptance item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| `archetype_milestones` DB table | No `CREATE TABLE archetype_milestones` migration | — | aspirational |
| Content seed for milestone abilities (all 18 archetypes) | No `content/milestones*` or `content/archetype_milestones*` | — | aspirational |
| Specialization fork at L5: 2 paths per archetype, fork data | `apps/agent/leveling.py:29` `specialization_fork: bool` field; `:85-93` L5 entry has `specialization_fork=True, milestone_type="specialization"`; `:236-239` L5 narration template ("You stand at the crossroads…"). **The two paths per archetype are NOT encoded** — Warrior's "Battle Master/Berserker", Mage's "Elementalist/Arcanist", etc. (spec L86, L149, L207, L265, L332, L410, etc.) exist only in the spec prose. `content/level_progression.json` row 5 (the seed for `LEVEL_PROGRESSION`) carries the fork bool but not the per-archetype option pair. | `test_leveling.py:39-45 test_specialization_fork_only_at_l5`; `test_rules_leveling.py:113-135` (L5 fork emit, L4 no-emit, multi-level inclusion) | partial — fork flag and narration exist; per-archetype option content does not |
| Agent tool `resolve_milestone` — grants milestone abilities, triggers L5 spec choice | No `resolve_milestone` grep hits | — | aspirational |
| Client: leveling screen with specialization choice UI at L5 | `apps/mobile/src/components/hud/level-up-overlay.tsx:12-32` is a generic "LEVEL UP / <newLevel> / <className>" animation overlay — no fork/choice affordance, no specialization options surfaced. No other mobile screen references `specialization` or `specialization_fork`. | — | aspirational |
| Auto-grant logic for L10 / L15 / L20 milestones (no player choice) | `LEVEL_PROGRESSION` has entries at L10, L15, L20 (`apps/agent/leveling.py:130-138`, `:175-183`, `:220-228`) with `archetype_milestone` / `archetype_capstone` types and narration text, but no "grant ability X to character Y" code path. Narration is emitted; abilities are not granted. | `test_leveling.py:140-153` verify L10 mentions "Companion major upgrade" and L20 mentions "Companion legendary" in narration only | partial — milestone fires as a narration event; no ability is actually granted |
| Each archetype has milestone entries at L5/10/15/20 | `LEVEL_PROGRESSION` is archetype-agnostic. Per-archetype milestones (Warrior L15 Indomitable, Mage L15 Arcane Recovery, etc. — spec L88, L150, etc.) are not in any structured data. | — | aspirational |
| `resolve_milestone` at L5 presents exactly 2 spec options + requires player choice before granting | Tool absent | — | aspirational |
| `resolve_milestone` at L10/15/20 auto-grants without input | Tool absent | — | aspirational |
| L10 grants Extra Attack for martial archetypes | `leveling.py:136` narration string mentions "Extra Attack for Warrior, Skirmisher, Paladin" — **narrative reference only**, no `extra_attack` flag on a character record or combat math hook. Note: spec lists Extra Attack at L10 for Warrior (L87), Skirmisher (L545), Paladin (L818). Guardian (L482 "Shield Mastery") and Bard L10 (L411 "Magical Secrets") do not get Extra Attack — implementation narration matches spec. | — | aspirational mechanic / confirmed copy |
| L20 grants capstone + legendary companion unlock | `leveling.py:225-228` `archetype_capstone` milestone with narration "Companion legendary"; no capstone ability data, no legendary companion record/migration | `test_leveling.py:140-144` | aspirational |
| Specialization choice at L5 persisted, not changeable | No `character.specialization` column / JSONB field / persistence path found | — | aspirational |
| Client displays specialization choice UI when L5 milestone triggers | No such UI; see "Client: leveling screen" above | — | aspirational |
| Unit tests verify milestone grants at each tier for ≥3 archetypes | Tests cover milestone *narration* (archetype-agnostic) but no per-archetype milestone grant exists to test | — | aspirational |

**Divergent (carry from Sprint-001):** Sprint-001 documented that `LEVEL_PROGRESSION` flags L5 (only) with `specialization_fork=True`, while L4 emits a separate `elective_techniques` milestone. M2.3's acceptance language "Specialization fork at L4/L5" was already discussed in Sprint-001 phase-1 audit; capstone should decide whether to (a) reword M2.3 to "L5 only" or (b) extend `specialization_fork` to L4. Do **not** re-litigate the implementation choice — it was a deliberate split. Reference: `docs/milestones/audit/phase-1-characters.md` M1.4 row "Specialization fork at L4/L5 is flagged in level-up rewards."

## M2.4 — Spell Acquisition (3 Tracks)

| Deliverable / Acceptance item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| `character_spells` DB table (character_id, spell_id, acquisition_track, is_prepared, date_learned) | No `CREATE TABLE character_spells` migration | — | aspirational |
| `spell_learning_progress` DB table (character_id, spell_id, cycles_completed, cycles_required, midpoint_decision, started_at) | No `CREATE TABLE spell_learning_progress` migration | — | aspirational |
| Core spell assignment: fixed per archetype, always prepared, no elective slot cost | No per-archetype "core spell list" in code or content. The spec defines core spells in prose (Mage: Arcane Bolt + Shield Spell + Counterspell + spec core + spec supreme; Cleric: Sacred Flame + Heal Wounds + Shield of Faith + domain core + domain supreme; etc.). None of this is materialized. | — | aspirational |
| Training track: spell-study cycle in async loop with tier-based durations (cantrip 1 / Minor 2 / Standard 3 / Major 5 / Supreme 8 cycles) | `content/training_activity_types.json` defines `spell_cantrip` (3-5h first half / 2-4h second half), `spell_standard`, `spell_major`, `spell_supreme`. **No `spell_minor` entry.** Durations are in seconds (real time), not "cycles." Generic state machine in `apps/server/src/training_state_machine.ts:43-149` consumes these but has no concept of "cycles required." | `apps/server/src/training_state_machine.test.ts` | partial / divergent — three of five tiers present (cantrip, standard, major, supreme); Minor missing; duration model uses seconds-per-half-cycle, not the spec's discrete cycle counts |
| Midpoint decision support during training | `apps/server/src/training_state_machine.ts:24-32 MidpointDecision`, `:124-129 getMidpointDecision`. `content/training_activity_types.json` ships midpoint prompts for spell_cantrip ("speed or precision"), spell_standard ("power or control"), spell_major ("push or work around"), spell_supreme (same). | `training_state_machine.test.ts` | confirmed for infrastructure; **partial** for spec coverage — midpoint decision is generic to any training activity, not specifically modifying a learned spell's "bonus variant." There is no `learned_spell.midpoint_bonus_variant` persisted on completion. |
| Discovery track: scrolls + NPC mentors (including mentor-exclusive variants) | No scroll system. Mentor NPCs exist as personality stubs (`apps/agent/activity_templates.py:72-83 TRAINING_MENTORS` — guildmaster_torin, scholar_emris) but are not bound to specific spells/abilities. | — | aspirational |
| Spell preparation: prepare from known pool on long rest; Druid terrain restriction; Paladin tier cap | No `prepare_spells` function, no `character.prepared_spells` column/JSONB, no Druid-terrain branch, no Paladin-Major-cap branch. Spec restriction (Paladin caps at Major tier — spec L803-811, also flagged for Diplomat L1060 and Marshal L1135 with "No Supreme access") is not enforced anywhere. | — | aspirational |
| Spell tier unlock by level: Cantrip L1, Minor L1, Standard L4, Major L7, Supreme L13 | `leveling.py:82` "Standard spells unlock" (in L4 milestone description string); `:109` "Major spells unlock" (L7); `:163` "Supreme spells unlock" (L13). **No `MAX_SPELL_TIER_BY_LEVEL` constant**, no gating function. `LEVEL_PROGRESSION` does not have a `max_spell_tier` field. | — | partial / aspirational — present as narration substrings only |
| Agent tool `learn_spell_from_scroll` | No grep hits | — | aspirational |
| Agent tool `prepare_spells` | No grep hits | — | aspirational |
| Core spells auto-assigned at character creation + always show as prepared | `apps/agent/tests/test_creation_tools.py` confirms character creation flow but no spell auto-assignment | — | aspirational |
| `learn_spell_from_scroll` adds to known pool + marks track="discovery" | Tool absent | — | aspirational |
| `prepare_spells` enforces prep limits + Druid/Paladin restrictions | Tool absent | — | aspirational |
| Spell tier unlock gates prevent learning above level allowance | Gate function absent | — | aspirational |
| Unit tests cover all three acquisition tracks, preparation rules, tier gating | None — no spell system to test | — | aspirational |

**Notable spec content not in milestone acceptance:** Per-archetype "Elective Spell Progression" tables (Mage spec L127-143, Druid L191-201, Cleric L249-259, Artificer L584-591, Seeker L639-645, Beastcaller L691-698, Warden L744-751, Paladin L805-811, Oracle L857-864, Bard L391-402, Whisper L982-986, Diplomat L1056-1060, Marshal L1130-1135) define total elective slot counts and cantrip counts at every level. None of these per-archetype progressions are in `content/` or code. M2.4 acceptance does not name these tables explicitly — capstone may want to add a deliverable, since they are concrete data the runtime needs.

## M2.5 — Martial Mentor System

| Deliverable / Acceptance item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| `mentor_variants` DB table (variant_id, base_ability_id, npc_mentor_id, variant_name, cost_override, effect_override, cultural_attribution, training_sessions_required) | No `CREATE TABLE mentor_variants` in any migration | — | aspirational |
| 2-3 session training loop: progress tracking, completion check, variant unlock | Generic training state machine exists: `apps/server/src/training_state_machine.ts:43-149` (two-half cycle, `transition_at`, first/second-half durations). Loop is not bound to a base ability nor a variant unlock — there is no "training_sessions_required" parameter, no "session_count" tracker for mentor lessons. | `training_state_machine.test.ts` (generic, not mentor-variant-bound) | partial — infrastructure exists for a one-shot two-half activity; not a multi-session variant-training loop |
| Style variant data: ≥1 variant per martial base technique (L4 + L8 choices) | No variant content found. Spec example (Cleaving Blow L1309-1316: Steppe Wind / Stone Splitter / Thornveld Sweep / Tide Breaker) is unimplemented. | — | aspirational |
| Example variant: Cleaving Blow base → Whirlwind Style variant | Not in code or content | — | aspirational |
| Cultural attribution field linking variant styles to in-world cultures | No `cultural_attribution` field anywhere | — | aspirational |
| Agent integration: mentor NPC offers training, tracks progress across sessions, grants variant on completion | `apps/agent/activity_templates.py:72-83 TRAINING_MENTORS` defines two mentors (guildmaster_torin, scholar_emris) with personality / speech_style / voice_id — not bound to abilities or variants. `apps/agent/activity_templates.py:143-153 get_training_mentor` is a lookup helper. `content/npcs.json` carries the two mentor NPC records. **No "session count" persisted on a character-mentor relationship.** | — | partial — NPC scaffolding only; the mentor-as-trainer-of-a-specific-variant binding is absent |
| `mentor_variants` table stores variant overrides (cost, effect) linked to base ability + NPC | Table absent | — | aspirational |
| Training loop tracks session count, unlocks variant only after required sessions (2-3) | Loop is one-shot two-half, not multi-session | — | aspirational |
| Unlocked variant replaces or supplements base technique at player's choice | No replace/supplement logic | — | aspirational |
| Each variant has cultural attribution string for DM narration | No variant data | — | aspirational |
| Variant cost/effect overrides apply when variant activated | No ability activation path (M2.2 dep), no variant data | — | aspirational |
| Training cannot begin without valid mentor NPC relationship (depends on Phase 6 NPC data) | Mentor NPCs exist (2 stubs); no "relationship" / disposition check on training start | — | aspirational |
| Unit tests cover training progress, variant unlock, cost/effect override application | None | — | aspirational |

## Material gaps

Consolidated list of items the capstone (story-004) should consider unchecking or reframing in `docs/milestones/02_archetypes.md`. Suggested pointer comment for each row: `<!-- see audit/phase-2-archetypes.md -->`.

**M2.1 — Archetype Chassis**
- DB table `archetypes`: aspirational. Encoding lives in three Python modules (`hp_scaling.py`, `rules_engine.py`, `creation_classes.py`) — no DB row.
- Content seed `content/archetypes.json`: aspirational. No file, no directory.
- `get_archetype_chassis(archetype_id)` pure function: aspirational. Capstone may either uncheck or rephrase as "chassis surface materialized across `ARCHETYPE_HP_CONFIG` + `ARCHETYPE_RESOURCE_CONFIG` + `CLASSES`."
- "Each archetype record specifies HP + armor + weapon + saves + resource + 3-5 skills" — weapon proficiencies are encoded only as a single starting weapon, not a proficiency list. Partial.
- Stale `ClassData.hit_die` field (e.g. Warrior=10) does not align with `ARCHETYPE_HP_CONFIG` (Warrior base=12) — capstone may want to drop the field or document it as cosmetic.

**M2.2 — Ability System**
- Both DB tables (`archetype_abilities`, `character_abilities`): aspirational.
- Content seed for core abilities: aspirational.
- Elective L4 / L8 pool data: aspirational. Milestone *markers* exist in `LEVEL_PROGRESSION`, content does not.
- Reaction ability infrastructure: aspirational.
- Agent tool `request_ability_activation`: aspirational.
- Ability swap on long rest: aspirational.
- Acquisition paths (training, scrolls, mentors): aspirational for abilities (training infra is unrelated).
- All 7 M2.2 acceptance criteria depend on the above and are aspirational.
- Sprint-001 carryover: `validateSlotAvailability` Artificer dead-code exception — capstone to resolve (wire or remove).

**M2.3 — Specialization & Milestones**
- DB table `archetype_milestones`: aspirational.
- Content seed for milestone abilities: aspirational. The per-archetype L5 fork option pair (Battle Master/Berserker etc.) is unencoded.
- Agent tool `resolve_milestone`: aspirational.
- Mobile leveling screen with L5 spec choice UI: aspirational. `level-up-overlay.tsx` is a generic announcement, not a choice screen.
- L10 "Extra Attack" / L15 / L20 / capstone abilities: present only as narration substrings, no granted mechanic.
- Specialization choice persistence: no `character.specialization` field/column.
- Sprint-001 carryover: L4 fork divergence — `specialization_fork=True` is L5-only by design. Capstone decides reword vs extend. Do NOT re-litigate.

**M2.4 — Spell Acquisition**
- Both DB tables (`character_spells`, `spell_learning_progress`): aspirational.
- Core spell assignment: aspirational. Per-archetype core spell lists are spec-only.
- Training cycle durations: divergent. Implementation uses seconds-per-half-cycle, not the spec's "1/2/3/5/8 cycles." `spell_minor` activity type missing entirely.
- Midpoint decision support: partial — generic infrastructure exists, no spell-bonus-variant persistence.
- Discovery track: aspirational — no scroll system, mentors not bound to spells.
- Spell preparation rules (Druid terrain, Paladin Major cap, Diplomat/Marshal Major cap): aspirational.
- Spell tier unlock by level: aspirational — substrings in milestone descriptions, no gate.
- Agent tools `learn_spell_from_scroll`, `prepare_spells`: aspirational.
- Suggested **NEW** deliverable: per-archetype elective spell progression tables (slot counts + cantrip counts per level for all 13 caster/hybrid archetypes) are unimplemented and not currently named in M2.4 acceptance.

**M2.5 — Martial Mentor System**
- DB table `mentor_variants`: aspirational.
- Multi-session training loop bound to a base ability + variant unlock: aspirational. Generic state machine is one-shot two-half, not multi-session-mentor.
- Variant content (Cleaving Blow's four variants etc.): aspirational.
- Cultural attribution: aspirational.
- Mentor-as-trainer-of-a-variant integration: aspirational. Two mentor NPC personality stubs exist but are not bound to abilities.
- All 7 M2.5 acceptance criteria depend on the above and are aspirational.
- Suggested **NEW** deliverables (not in M2.5 acceptance today): per-variant character-sheet attribution display (spec L1339-1347); "one variant per technique, swap requires re-training" rule (spec L1354).

## Cross-doc dependencies

- **M2.4 spell acquisition ↔ Phase 3 Magic (`08_magic_and_companions.md` / `game_mechanics_magic.md`)** — Story-002 audits Phase 3 and will catalog the actual spell content (Arcane / Divine / Primal catalogs). M2.4's `character_spells.spell_id` foreign key only resolves once that catalog exists. Spec references "Arcane Spell Catalog in `game_mechanics_magic.md`" repeatedly (e.g. archetypes spec L102, L560, L614, L667, L774). Resonance rates (Arcane 0.6×, Primal 0.1-0.8×, Divine 0.3×, Bard 0.4×, Whisper 0.5×) are also Magic-phase concerns.
- **M2.3 L5 specialization options ↔ Phase 8 Patrons (`docs/game_mechanics/game_mechanics_patrons.md`)** — Cleric L5 "Domain Specialization" is determined by divine patron (spec L265: Kaelen / Orenthel / Syrath / Veythar). Paladin L5 "Oath Specialization" is patron-driven (spec L817: Kaelen Champion / Valdris Inquisitor / Orenthel Redeemer / Syrath Shadow Knight). Oracle's "dual allegiance" (spec L833 — Oracle can serve Zhael AND another patron) is also patron-system territory. Story-003 audits Patrons.
- **M2.5 mentors ↔ Phase 6 NPCs** — Acceptance criterion "training cannot begin without a valid mentor NPC relationship" depends on the Phase 6 NPC relationship/disposition system. Two mentor NPC stubs exist (`apps/agent/activity_templates.py:72-83`, `content/npcs.json`) but the relationship binding is absent. Mentor cultural attribution (Drathian Clans, Keldaran Holds, Thornwardens, Tidecallers — spec L1313) also depends on Phase 5/6 (regions/cultures) content.
- **M2.2 reaction abilities ↔ Combat phase** — The "reaction abilities tied to combat windows" deliverable requires a combat-window enforcement mechanism (initiative + interrupt phase). That belongs to the combat phase audit (whichever sprint owns Phase 4); M2.2 cannot ship reactions alone.
- **M2.5 ↔ Async activity system (Phase 4 or training infra)** — `apps/server/src/training_state_machine.ts` exists in current shape; M2.5's multi-session training loop is an extension of that state machine. Whether to keep two state machines or extend the existing one is an architecture call for capstone + the training phase owner.

## Capstone-transcludable notes

These are short pointers safe to paste into `docs/milestones/02_archetypes.md` under the relevant acceptance bullets:

- M2.1: deliverables 1-4 are aspirational; HP helper (deliverable 5) and resource-type assignment (acceptance 5) are confirmed via `apps/agent/hp_scaling.py` and `apps/agent/rules_engine.py:ARCHETYPE_RESOURCE_CONFIG`. `<!-- see audit/phase-2-archetypes.md -->`
- M2.2: entire milestone is aspirational; only L4/L8 milestone markers in `apps/agent/leveling.py:LEVEL_PROGRESSION` exist. `<!-- see audit/phase-2-archetypes.md -->`
- M2.3: L5 specialization-fork *flag* is confirmed (`leveling.py:29` + L5 entry), but per-archetype option pairs, agent tool, and mobile UI are aspirational. Sprint-001 documented the L4/L5 wording divergence — see phase-1-characters.md. `<!-- see audit/phase-2-archetypes.md -->`
- M2.4: entire milestone is aspirational except partial training-activity infrastructure. `spell_minor` tier missing from training activity types. Training durations are real-time seconds, not the spec's discrete cycle counts. `<!-- see audit/phase-2-archetypes.md -->`
- M2.5: entire milestone is aspirational except two mentor NPC personality stubs and a generic training state machine that is not bound to abilities or variants. `<!-- see audit/phase-2-archetypes.md -->`
