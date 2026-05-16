# Milestone Audit — Findings Index

Read-only audit of `docs/milestones/` against shipped code and current spec docs. Sprint-001 covered Phases 0 + 1; Sprint-002 covered Phases 2 + 3 + 8 (Group A); Sprint-003 covered Phases 4 + 7 + encounter_roles overlay (Group B). Findings are consolidated into the milestone files by each sprint's capstone story.

Bias is toward unchecking when evidence is weak — Honesty over optimistic tracking.

## Sprint-001 findings files (Phases 0 + 1)

| File | Scope | Confirmed | Aspirational | Unverified |
| --- | --- | --- | --- | --- |
| [phase-0.md](./phase-0.md) | M0.1–M0.4 doc updates (CLAUDE.md, INDEX.md, gp→gc, cross-refs) | 18 | 4 | 1 |
| [phase-1-rules-engine.md](./phase-1-rules-engine.md) | M1.1 d20 resolution + M1.2 skill tiers | 14 | 0 | 0 |
| [phase-1-characters.md](./phase-1-characters.md) | M1.3 resource pools (incl. 18 archetypes) + M1.4 leveling | 30 | 1 | 2 |
| [phase-1-async.md](./phase-1-async.md) | M1.5 async training + M1.6 companion errands | 11 | 5 | 0 |
| [dependency-versions.md](./dependency-versions.md) | Companion audit: Python, Bun/TS, Expo/RN pinned vs upstream | informational | — | — |

`dependency-versions.md` is informational — not consumed by the capstone; surfaces upgrade recommendations (now / next-sprint / hold) for separate planning.

## Sprint-002 findings files (Phases 2 + 3 + 8 — Group A)

| File | Scope | Confirmed | Partial | Aspirational | Divergent / NOT_SHIPPED |
| --- | --- | --- | --- | --- | --- |
| [phase-2-archetypes.md](./phase-2-archetypes.md) | M2.1 chassis + M2.2 abilities + M2.3 specialization + M2.4 spells + M2.5 mentors | 2 | 5 | 28 | 2 divergent |
| [phase-3-magic.md](./phase-3-magic.md) | M3.1 Resonance + M3.2 Hollow Echo + M3.3 spell catalog + M3.4 concentration / racial | 0 | 0 | 0 | 34 NOT_SHIPPED |
| [phase-8-patrons.md](./phase-8-patrons.md) | M8.1 profiles + favor + M8.2 tier abilities + M8.3 synergies + Unbound | 0 | — | 33 | 1 unverified |

Sprint-002 headline: Group A is **almost entirely unshipped**. Phase 3 Magic is fully NOT_SHIPPED (blocks Phase 8 Layer 2). Phase 8 Patrons has only a thin `divine_favor` integer + god-whisper layer. Phase 2 Archetypes has HP scaling + resource-type assignment confirmed; everything else (DB tables, content seeds, agent tools, mobile UI) is aspirational.

## Sprint-003 findings files (Phases 4 + 7 + encounter_roles — Group B)

| File | Scope | Confirmed | Partial | Divergent | Aspirational / NOT_SHIPPED |
| --- | --- | --- | --- | --- | --- |
| [phase-4-combat.md](./phase-4-combat.md) | M4.1 phase combat + M4.2 action economy + M4.3 conditions + M4.4 death + M4.5 dramatic dice + M4.6 social/travel/gathering | 8 | 9 | 3 | 45 |
| [phase-7-bestiary.md](./phase-7-bestiary.md) | M7.1 stat block schema + M7.2 regional catalog + M7.3 Hollow special mechanics + M7.4 loot/harvesting/encounter builder | 0 | 1 | — | 40 NOT_SHIPPED |
| [phase-encounter-roles.md](./phase-encounter-roles.md) | 790L gm_encounter_roles overlay; ownership map across phases 04 (primary) / 07 / 09 | 0 | 1 | — | 30 NOT_SHIPPED |

Sprint-003 headline: Group B is **almost entirely unshipped**. Phase 4 ships core combat math (AC, attack roll, damage doubling, death save) + a turn-based LLM tool loop — but the spec's 4-beat phase machine, full condition system, dramatic-dice flag, social/travel/gathering, and Mortaen scene wiring are aspirational. Phase 7 is unshipped at every layer (no `content/creatures.json`, no schema, no agent tools). encounter_roles overlay (added after the original milestones) is 0% built across all 9 spec sections.

## Material gaps surfaced (capstone annotations)

These were unchecked in `00_doc_updates.md` / `01_core_systems.md` with `<!-- see audit/<file> -->` pointers:

**Phase 0 documentation**
- `game_mechanics_magic.md:423,432` retains `gp` references (Revivify/Resurrection diamond components, explicitly named M0.3 targets); `economy/game_mechanics_p2p_trade.md:160` has a third instance.
- `INDEX.md` line ranges for `game_mechanics_archetypes.md` are off by ~133 lines (file is 1357 lines, INDEX claims 1224).
- `game_mechanics/` docs are not listed in CLAUDE.md's Knowledge System section — reachable only transitively via `INDEX.md`.
- M0.4 "no existing content deleted" cannot be verified positively without a pre-M0.4 baseline.

**Phase 1 leveling (M1.4)**
- Specialization fork: only L5 carries `specialization_fork=True`; L4 emits `elective_techniques` milestone but is NOT flagged as a fork. Spec wording says "L4/L5".
- "Unified" progression table covers attribute points + milestones + proficiency + fork in `leveling.py:LEVEL_PROGRESSION`, but HP gain lives separately in `hp_scaling.py:ARCHETYPE_HP_CONFIG`. Acceptance text names HP as a unified-table field.
- No standalone `apply_level_up(character_id)` agent tool. Level-up is folded into `award_xp` via `check_level_up` + `LEVEL_UP` event; AC narration is satisfied; the named tool deliverable is aspirational.
- No standalone `calculate_level(total_xp)` function; available via `check_level_up(0, total_xp, 1)` workaround (untested).
- 18 archetypes encoded in `apps/agent/rules_engine.py` + `hp_scaling.py`, not in `content/archetypes/` (no such directory).

**Phase 1 async (M1.5/M1.6)**
- Companion errand duration ranges: ALL 4 diverge from spec (scout 2–4 vs 4–8 hr; social 1–3 vs 3–6; acquire 2–4 vs 4–10; relationship 3–6 vs 2–4).
- Risk distribution table partial: only `scout` populated at full spec values; `acquire` reduced; `social`/`relationship` always 0/0; several danger×errand combos blocked at validation.
- **Artificer slot exception is dead code:** `validateSlotAvailability` accepts `archetype` + `hasPortableLab` params and is unit-tested, but both call sites in `activities.ts` pass neither. A live Artificer with a Portable Lab cannot benefit from the exception.
- 4 agent-tool deliverables missing as `@function_tool`s — HTTP-only paths: `initiate_training_cycle`, `resolve_training_midpoint`, `dispatch_companion_errand`, `resolve_companion_errand`.
- `training_activities` schema flattens spec's typed columns into `data JSONB` (behavioral fields present in payload).
- Client training "panel" is delivered as Catch-Up feed integration, not a stand-alone screen.

## Sprint-002 capstone annotations (Phases 2 + 3 + 8)

These were captured as "Audit Status (Sprint-002)" blocks at the top of `02_archetypes.md`, `03_magic.md`, `08_patrons.md` with `<!-- see audit/<file> -->` pointers. No M2.x / M3.x / M8.x acceptance boxes were unchecked because all were already `[ ]` — the milestone-level status was re-flagged as DEFERRED / NOT_STARTED in each file.

**Phase 2 — Archetypes (Group A)**
- M2.1: DB table, `content/archetypes.json`, `get_archetype_chassis()` aspirational. HP scaling + resource-type assignment confirmed (Sprint-001 carryover). Stale `ClassData.hit_die` field diverges from `ARCHETYPE_HP_CONFIG`.
- M2.2: Entire ability system aspirational. Only L4/L8 milestone *markers* exist in `LEVEL_PROGRESSION`.
- M2.3: L5 `specialization_fork=True` flag confirmed; per-archetype option pairs (Battle Master / Berserker etc.), `resolve_milestone` tool, mobile UI aspirational.
- M2.4: Spell system aspirational. Training infra uses real-time seconds, not spec's discrete "cycles". `spell_minor` tier missing from training activity types.
- M2.5: Mentor system aspirational. 2 mentor NPC personality stubs + generic state machine exist but are not bound to abilities or variants.

**Phase 3 — Magic (Group A)**
- All M3.1–M3.4 NOT_SHIPPED (34 / 34 criteria). No Resonance state, no spell catalog, no concentration, no racial Resonance bonuses, no Hollow Echo table, no Veil Ward mechanics.
- `content/spells.json` does not exist. Spec is internally consistent at 87 spells.
- `request_attack(target_id, weapon_or_spell)` at `apps/agent/combat_tools.py:275` is NOT a spell-cast tool (no catalog validation, no Focus/Resonance/concentration interaction).
- Spec/milestone divergence on Draethar Inner Fire cost: spec says "1d6 fire damage", milestone says "HP or Focus".
- Stale `gp` refs at `magic.md:423, 432` (Revivify + Resurrection diamonds) carried over from sprint-001 phase-0 audit — still on the M0.3 cleanup punch list.

**Phase 8 — Patrons (Group A)**
- All M8.1–M8.3 aspirational except Unbound Path *selectable* (M8.1 row "unverified").
- `content/gods.json` 60% incomplete (4 of 10 patrons present, no mechanical layer data).
- 4-layer architecture not encoded. Favor is a single-integer 0-100 scale, not tiered. Alignment evaluation is LLM-driven (`award_divine_favor`), not rules-engine-driven (`evaluate_patron_alignment`).
- Layer 4 synergy in `DeityData.synergy_classes` is a flat tuple — needs (11 × 18) matrix with Natural/Divine/Unexpected tagging.

## Sprint-003 capstone annotations (Phases 4 + 7 + encounter_roles)

These were captured as "Audit Status (Sprint-003)" blocks at the top of `04_combat.md`, `07_bestiary.md`, and `09_economy.md` (cross-ref) with `<!-- see audit/<file> -->` pointers. No M4.x / M7.x acceptance boxes were unchecked because all were already `[ ]` — the milestone-level status was re-flagged as DEFERRED / NOT_STARTED in each file.

**Phase 4 — Combat (Group B)**
- M4.1: Turn-based free-form LLM tool loop shipped (`combat_agent.py:26-44`, `session_data.py:46-52`); 4-beat phase machine + Redis state + `advance_combat_phase` aspirational. Initiative (d20+DEX) confirmed. State persistence in `combat_instances` JSONB diverges from spec's `combat_encounters` schema.
- M4.2: Core math confirmed — `calculate_ac`, `resolve_attack` (with crit doubling), proficiency bonus. Weapon damage tops at 1d8 (spec calls for 1d12); damage adds no attribute modifier (spec calls for it). 6 declaration types + enhancers absent.
- M4.3: Entire condition system aspirational — no `character_conditions` table, no apply/tick/remove. `fatigue_narration` is dead-end narrative cue code.
- M4.4: Death save mechanic confirmed (3 success/3 fail, d20 no modifier). Mortaen scene, cost engine, anchor points, Hollowed death, instant death, party wipe, companion auto-stabilize all aspirational.
- M4.5: Entirely aspirational. No `evaluate_dramatic_context`, no `dramatic` flag on any roll result.
- M4.6: All aspirational. NPC disposition infrastructure exists (5-tier `["hostile","wary","neutral","friendly","trusted"]`) but unused; naming divergences flagged (wary↔unfriendly, Fast/Normal/Careful↔Compressed/Scenic/Dangerous).
- **M4.7 proposed (capstone decision `m4-7-overlay-status`)**: new milestone for the encounter_roles overlay (Minion/Standard/Elite/Boss/Named) with stat-modifier table, Elite enhancement, Boss signature/legendary, encounter budget points, role-derivation functions. Author in a future sprint.

**Phase 7 — Bestiary (Group B)**
- M7.1-M7.4: ALL NOT_SHIPPED (40/40 acceptance items). `content/creatures.json` does not exist; no schema validators; no agent tools.
- Only shipped artifact: `content/encounter_templates.json` (6 templates) with flat enemy schema divergent from the M7.1 universal stat block.
- **M7.2 region-count gap (decision `m7-2-creature-count-gap`)**: narrow milestone text to "19+ natural creatures" (path b) — spec authors 19, milestone claims 38+; Ashmark Soldier and Cult Acolyte missing stat blocks despite lore references.
- **M7.1 schema must extend** with optional `role` field and Boss-only `signature_ability` + `legendary_actions[]` for M4.7 alignment.
- **M7.4 `build_encounter` signature (decision `m7-4-build-encounter-signature`)**: capstone records both `(tier, combatant_count, environment)` and `(tier, budget_points, environment)` shapes; final choice deferred to the M4.7/M7.4 implementation sprint.
- M7.3 blocked on Phase 3 Resonance NOT_SHIPPED (sprint-002 carryover).

**encounter_roles overlay (Group B, primary owner Phase 04)**
- 0% built across all 9 spec sections (Role Definitions, Combat Stat Modifiers, Loot Modifiers + Currency Drops + Material Sell Values, XP Modifiers, Encounter Budget System, Worked Examples, DM Narration Guidance, Derivation Formula, Design Decisions 73-81).
- `EncounterRole` enum, role modifier tables, Boss signature/legendary action handlers, encounter budget calculator, material sell-value lookup — all aspirational.
- Phase 04 primary; Phase 07 cross-refs schema; Phase 09 owns currency drops + material sell values (deferred to Phase 09 rewrite per decision `m9-4-loot-economy-status`).

## Sprint-spec-cleanup punch list

Out-of-scope-but-real findings surfaced by audits that don't fit any active milestone — collected here so they don't drift between sprints. Add new items at the bottom.

- **Stale `gp` references** in `game_mechanics_magic.md:423` (Revivify diamond "50 gp") and `:432` (Resurrection diamond "500 gp"). Original M0.3 gp→gc cleanup missed these two. Plus a third instance at `economy/game_mechanics_p2p_trade.md:160`. (sprint-001 phase-0 audit; reaffirmed sprint-002 phase-3 audit; concern `027196d5b06f`)
- **`INDEX.md` line ranges off** for `game_mechanics_archetypes.md` (~133 lines drift; file is 1357L, INDEX claims 1224L). (sprint-001 phase-0)
- **`game_mechanics/` docs unlisted in CLAUDE.md** Knowledge System section — reachable only transitively via `INDEX.md`. Remediation: add a bullet under CLAUDE.md "Knowledge System" naming `docs/game_mechanics/` + `docs/game_mechanics/economy/` as the source-of-truth for mechanics specs, with `docs/INDEX.md` as the entry-point. (sprint-001 phase-0)

## Sprint-004 follow-up candidates

Sprint-003 carry-forwards (still open):

- Author **M4.7 "Encounter Role Overlay"** as a numbered milestone in `04_combat.md` (capstone surfaced; not yet authored in the file's milestone list). Scope: `EncounterRole` enum, role modifier table, Elite/Boss enhancement rules, encounter budget points, role-derivation functions.
- Pair **M4.7 + M7.4** implementation in a single sprint so the `build_encounter` signature choice can be resolved with full context (decision `m7-4-build-encounter-signature` is deferred).
- Reconcile **M7.2 milestone text** to "19+ natural creatures" + add Ashmark Soldier / Cult Acolyte stat blocks to spec OR remove them from lore prompts.
- Reconcile **disposition tier naming** (`wary` in code vs `unfriendly` in spec) and **travel-mode naming** (Fast/Normal/Careful in spec vs Compressed/Scenic/Dangerous narrative text) before Phase 4 social/travel work.
- Cross-cut prerequisite: Phase 3 Magic (Resonance system) before M7.3 Hollow creature mechanics can ship.

Sprint-001/002 carry-forwards (still open):

- Resolve surviving `gp` references in `game_mechanics_magic.md` (M0.3 cleanup); update `INDEX.md` line ranges for archetypes.
- Decide M1.4 spec vs code: either rename the fork to L5-only and split HP from the unified table, or update code to match (add `specialization_fork` to L4, fold HP into `LEVEL_PROGRESSION`).
- Decide M1.6 spec vs code: either reduce duration spec to match shipped values, OR widen the shipped risk table to cover all 4 errand types at all danger levels.
- Fix the Artificer slot dead code: pass `archetype` + `hasPortableLab` from `activities.ts` call sites OR remove the unused validator params.
- Add the 4 missing agent tools (initiate_training_cycle, resolve_training_midpoint, dispatch_companion_errand, resolve_companion_errand) OR formally remove them from the deliverable list.

New from sprint-002 audits:

- **Phase 2 capstone work** (large): seed `archetypes` DB table + `content/archetypes.json`; implement `get_archetype_chassis`; ship `archetype_abilities` + `character_abilities` tables + `request_ability_activation` agent tool; encode L4/L8 elective pools; build `resolve_milestone` + mobile L5 fork UI; ship spell tracks (M2.4) — note training durations need conversion from seconds to discrete cycles; ship mentor-variant system (M2.5).
- **Phase 3 capstone work** (largest, blocks Phase 8 Layer 2): ship the entire Resonance system + Hollow Echo + Veil Ward + spell catalog + concentration + racial Resonance. Decide on spec-superset deliverables (Bard 0.4× multiplier, Veythar post-reveal 0.7×, cantrip 0-Resonance, rest reset, Veil Fracture event, Arcana sensing ladder, Druid prep constraint, per-archetype Veil Ward sources).
- **Phase 8 capstone work**: complete `content/gods.json` (6 missing patrons + Layer 1-4 fields for all 10); add tier model + thresholds + decay; ship `evaluate_patron_alignment` / `get_patron_tier` / `activate_patron_ability` / `check_patron_tier` / `get_archetype_synergy` / `apply_unbound_resonance_push` / `query_patron_synergy`; create `patron_ability_unlock` + `archetype_synergy` migrations; build Unbound mechanics (Veil Clarity, voluntary +3 push, Veil Mastery, Self-Reliance milestones).
- **Spec/milestone divergences to reconcile** (capstone choices): M3.4 Draethar Inner Fire cost (spec: fire damage; milestone: HP or Focus — recommend tightening milestone to spec); M2.3 L4/L5 fork wording (Sprint-001 finding still open); M2.4 training durations (seconds vs cycles).
- **Workers=4 e2e investigation** (debt 40ce8a9d3fcc): rate-limit bypass works at workers=3 but workers=4 still 429s. Determine whether `reuseExistingServer` masks a fresh server respawn OR a second bottleneck appears past workers=3.

## Method

Per execution_plan.json (§Milestone 1 for sprint-001; §Milestone 2 for sprint-002; §Milestone 3 for sprint-003): for items with action verbs (add/implement/create), grep for the named symbol or file in `apps/agent/`, `apps/server/`, `packages/shared/src/entities/`, `content/`. For doc items, confirm the referenced doc/section exists and reflects the change. For spec sections without a milestone item, mark NEW with rationale. Output: table per phase with item → evidence → status (confirmed / partial / aspirational / divergent / NOT_SHIPPED).
