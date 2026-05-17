# Phase 6 Audit — NPCs M6.3 (Mentor Registry & Training)

Sprint-005 / Milestone 5 (story-003). Read-only audit of `docs/milestones/06_npcs.md` §M6.3 (L78-108) against `docs/game_mechanics/game_mechanics_npcs.md` §Mentor Registry (L379-542) and shipped code in `apps/agent/`, `apps/server/`, `packages/shared/src/entities/`, `content/`, and `scripts/migrations/`. Status legend (matches sprint-004 audit/README.md L49-58): **BUILT** = code present and matches spec; **DESIGNED** = spec well-defined and partial code exists, but the symbol/feature is missing, renamed, or diverges; **NOT_SHIPPED** = no implementation found. Sibling sprint-005 audit files: `docs/milestones/audit/phase-6-schema-archetypes.md` (M6.1), `phase-6-settlements.md` (M6.2). Cross-reference: `docs/milestones/audit/phase-2-archetypes.md` (sprint-002 M2.5 audit — confirms M2.5 Martial Mentor System is 0/1/6 confirmed/aspirational/NOT_SHIPPED).

## Summary

| Section | BUILT | DESIGNED | NOT_SHIPPED |
| --- | --- | --- | --- |
| M6.3 — Mentor Registry & Training (9 acceptance items) | 0 | 2 | 7 |
| Warrior mentor coverage (8 technique rows, 16 spec variants enumerated within) | 0 | 0 | 8 |
| Rogue mentor coverage (6 techniques, 6 spec variants) | 0 | 0 | 6 |
| Guardian/Skirmisher/Spy/Bard coverage (6 rows: Guardian L4+L8, Skirmisher, Spy, Bard, Diplomat NEW) | 0 | 0 | 6 |
| Generation/check surfaces (3 functions/tool) | 0 | 2 | 1 |
| M2.5 ability-link coverage (8 Warrior + 6 Rogue technique_ids = 14 rows) | 0 | 0 | 14 |

**Headline finding:** The mentor registry is **almost entirely unshipped**, but the training-cycle infrastructure underneath it is real. What ships: a generic 5-state async-training state machine (migration 016 `training_activities`), 8 training activity types including `technique_base` and `technique_mentor` (migration 017 + `content/training_activity_types.json`), 4 training programs in `content/training_programs.json` with a `mentor_id` field referencing 2 NPC mentor shims (`guildmaster_torin`, `scholar_emris`), and narration-shape data in `apps/agent/activity_templates.py:14-28` `TRAINING_MENTORS` dict (same 2 mentors, narration personality only). What does NOT ship: the mentor-variant registry table, any spec mentor data (0 of 21+ named spec mentors seeded), `check_mentor_requirements` / `enroll_mentor_training` surfaces, per-variant cycle persistence, and the M2.5 ability symbols (Cleaving Blow, Precision Strike, etc.) that mentor entries would link to. **Compound dependency:** the M2.5 audit at `docs/milestones/audit/phase-2-archetypes.md` already established that M2.5 itself is 0/1/6 — M6.3 acceptance bullet 8 ("Mentor data links correctly to Phase 2 M2.5 ability definitions") is structurally NOT_SHIPPED because M2.5's ability surface is itself NOT_SHIPPED.

Honesty note: One spec mentor has a likely name match in shipped content. Spec L505 names "Seeker-Agent Emris (Accord of Tides, research quarter, Aelindran scholarly)" as the Rogue L8 Exploit Weakness / Analytical Strike mentor; `content/npcs.json` has `scholar_emris` ("Emris of the Diaspora", role "Aelindran scholar, artifact expert"). Probable same character, but the NPC carries no mentor-variant binding (story-001 audit M6.1 row 1: NPC schema has no `mentor{}` field). Treated as NOT_SHIPPED for variant data; flagged for capstone as a binding opportunity once M6.1 schema lands.

## Coverage matrix

Spec sections under §Mentor Registry mapped to milestone items. **NEW** = spec content with no corresponding M6.3 bullet.

| Spec section (file:line) | Milestone item | Notes |
| --- | --- | --- |
| Mentor Schema nested in NPC (npcs.md:385-399) | M6.3 — mentor nested data per variant | Spec fields: `technique`, `variant_name`, `variant_effect`, `culture`, `training_cycles`, `requirements{disposition,quest,gold,skill}`, `narration_cue`. Milestone deliverable L88 lists same 7 fields. Cross-doc with M6.1 NPC schema (story-001 audit: `mentor{}` field NOT_SHIPPED on the npc.ts Npc interface). |
| Warrior Technique Mentors L4+L8 (npcs.md:402-463) | M6.3 — Warrior 8+ mentors | Spec ships 16 variants across 8 techniques (10 L4 + 6 L8). Milestone says "8+ mentors" — spec exceeds by ~8. **Capstone should record that "8+" is conservative; the real coverage target is 16.** |
| Rogue Technique Mentors L4+L8 (npcs.md:464-505) | M6.3 — Rogue 5+ mentors | Spec ships 6 variants across 6 techniques (4 L4 + 2 L8). Milestone says "5+" — spec hits 6. Matches. |
| Guardian / Skirmisher / Spy / Bard / Diplomat mentors (npcs.md:508-541) | M6.3 — "each have at least 2 representative mentors" | **Milestone/spec divergence:** Milestone says "each have at least 2"; spec ships exactly **1** representative per archetype (Village Elder Greta = Guardian L4 Taunt; Warden-Captain = Guardian L8 Living Fortress; Elari Blade-Singer Isara = Skirmisher L4 Dual Strike; Apothecary Old Vaen = Spy L4 Poison Craft; Drathian Keeper of Songs = Bard L4 Song of Rest). Spec ALSO names a **Diplomat** archetype with mentors — NEW vs milestone (which enumerates only 4: Guardian/Skirmisher/Spy/Bard). **Two flags for capstone.** |
| Mentor `culture` field (npcs.md:390) | NEW | `culture: str` field naming the cultural origin of the style variant. Milestone deliverable list L88 enumerates the other 6 fields but omits `culture`. |
| Requirement: quest completion (npcs.md:394) | M6.3 — `check_mentor_requirements` evaluates quest completion | Spec gives concrete quest gates ("mounted combat trial", "Thornwarden patrol", "Vigil of Greyhaven quest chain"). Cross-doc with `content/quests.json` (exists but no completion-check function in apps/agent). |
| Requirement: skill tier (npcs.md:395) | M6.3 — `check_mentor_requirements` evaluates skill tier | Spec gates use strings like "Athletics: Trained", "Sleight of Hand: Expert". Cross-doc with Phase 1 skill-tier persistence and Phase 2 M2.2 ability system. |
| Cultural attribution callouts on every variant (npcs.md:407+) | NEW | Variant cards explicitly tagged Drathian / Keldaran / Thornwarden / Tidecaller / Ashmark / Aelindran / Vaelti / criminal-underworld / etc. Milestone doesn't enumerate this even though spec carries it on every row. **Capstone should flag for inclusion or deferral.** |

## M6.3 — Mentor Registry & Training

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Mentor registry covers all Warrior L4 and L8 technique variants (8+ mentors) | No registry exists. `grep -rn 'mentor_registry\|mentor_variants\|MentorVariant' apps/ packages/` → 0 matches. No `content/mentor_variants.json`; no `apps/agent/mentor_registry.py`. The 16 spec Warrior variants (Steppe Wind, Stone Splitter, Thornveld Sweep, Tide Breaker, Hawk's Eye, Quiet Blade, Blood Challenge, Shield Provocation, Berserker's Momentum, Cornered Fury, Thunderclap, Commander's Voice, Avalanche, Eye of the Storm, Mountain's Root, Last Wall) have zero shipped binding to mentor NPCs. | None | NOT_SHIPPED |
| Rogue mentors cover 5+ technique variants | Same registry absence. Spec's 6 Rogue variants (Gutter Fighting, Magpie's Touch, Flash Powder, Tendon Slash, Veil Walk, Analytical Strike) have zero shipped binding. | None | NOT_SHIPPED |
| Guardian, Skirmisher, Bard, and Spy archetypes each have at least 2 representative mentors | Same registry absence. Additional divergence: spec ships only 1 representative per archetype (npcs.md:512-541) so even when M6.3 implementation lands, the spec source itself is short by 1 mentor per archetype vs milestone's "at least 2". **Capstone must reconcile** — either trim milestone target or extend spec with a 2nd representative each. | None | NOT_SHIPPED |
| `check_mentor_requirements` correctly evaluates disposition threshold, quest completion, gold, and skill tier | No symbol. `grep -rn 'check_mentor_requirements' apps/ packages/` → 0 matches. Existing partial pieces: disposition resolution at `apps/agent/db_queries.py:22-52` (`get_npc_disposition` returns string tier); skill tier at `apps/agent/rules_engine.py:194-196` (per-tier ability text); gold tracking exists in inventory system; quest tracking exists in `content/quests.json` + agent tools. The infrastructure to feed the function exists; the function itself does not. | None | NOT_SHIPPED |
| `check_mentor_requirements` returns specific unmet requirements (not just pass/fail) | No function exists (above), so the unmet-requirement-return shape is undefined. | None | NOT_SHIPPED |
| `enroll_mentor_training` validates requirements before enrollment and returns error if unmet | **Partial infrastructure ships, requirement-gating + variant binding do not.** `apps/agent/activity_templates.py:14-28` `TRAINING_MENTORS` dict carries narration data for `guildmaster_torin` + `scholar_emris`. `content/training_programs.json` (4 entries) wires a `mentor_id` field on each program → mentor NPC. `apps/agent/training_rules.py` + `apps/agent/db_training.py` + migration 016 `training_activities` table together provide a 5-state async training cycle. `content/training_activity_types.json` already includes a `technique_mentor` activity type alongside `technique_base`. **But:** no `enroll_mentor_training` agent tool is registered in `apps/agent/city_agent.py:18-45` CITY_TOOLS; no requirement-gate check; the 4 shipped programs all carry stat-trainings (combat_basics/endurance_training/arcane_study/perception_drills), not technique variants. | None for `enroll_mentor_training` itself; tests cover the underlying state machine. | DESIGNED |
| Training cycles are tracked per player per variant | **Partial.** `scripts/migrations/016_training_activities.sql` creates `training_activities (id, player_id, activity_type, state, data JSONB, transition_at, ...)` — cycle tracking per player exists. The `data JSONB` field could carry `variant_id` per-row but no shipping code stores it there; no typed `variant_id` column or index. The cycle dimension is BUILT for activity_id; the variant dimension is NOT_SHIPPED. | None for variant-cycle tracking specifically. | DESIGNED |
| Mentor data links correctly to Phase 2 M2.5 ability definitions | **Compound NOT_SHIPPED.** Per sprint-002 audit (`docs/milestones/audit/phase-2-archetypes.md` M2.5 row): M2.5 is 0/1/6 — only the generic state machine + 2 NPC stubs exist; `mentor_variants` table, variant data, attribution, multi-session loop, agent integration, tests all NOT_SHIPPED. No ability symbol exists for "Cleaving Blow", "Precision Strike", "Taunt", "Reckless Assault", "War Cry", "Unstoppable Charge", "Whirlwind", "Iron Stance" (Warrior) or "Dirty Trick", "Quick Fingers", "Smoke Bomb", "Crippling Strike", "Shadow Step", "Exploit Weakness" (Rogue). `grep -rn 'cleaving_blow\|precision_strike\|whirlwind\|exploit_weakness' apps/agent` → 0 matches. M6.3 cannot link to definitions that don't exist. | None | NOT_SHIPPED |
| Tests cover requirement combinations (all met, one unmet, multiple unmet) | No mentor-registry tests. `grep -rln 'mentor_registry\|check_mentor_requirements\|enroll_mentor_training' apps/agent/tests` → 0 matches. The shipped training tests (`apps/agent/tests/test_training_*.py`) cover cycle transitions, not requirement gating. | None | NOT_SHIPPED |

**Deliverables status (per 06_npcs.md M6.3 §Deliverables L84-92):**
- Mentor registry data structure (technique_id → variant list → mentor data): **NOT_SHIPPED**.
- Warrior technique mentors (8+ variants per spec): **NOT_SHIPPED** (16 designed in spec, 0 seeded).
- Rogue technique mentors (5+ variants per spec): **NOT_SHIPPED** (6 designed, 0 seeded).
- Representative mentors for Guardian/Skirmisher/Bard/Spy (and Diplomat per spec, NEW vs milestone): **NOT_SHIPPED** (1 per archetype designed, 0 seeded).
- Mentor nested data per variant (7-field shape): **NOT_SHIPPED** at content layer; **DESIGNED** at schema layer (spec L385-399 well-formed; npc.ts has no `mentor{}` field per story-001 audit).
- DB migration `mentor_registry` table: **NOT_SHIPPED**.
- Rules engine `check_mentor_requirements(player, mentor, variant)`: **NOT_SHIPPED**.
- Agent tools `check_mentor_requirements` + `enroll_mentor_training`: **NOT_SHIPPED** as tools; **DESIGNED** for the enrollment async pipeline beneath it.

## Warrior mentor coverage

8 techniques + 16 spec variants (npcs.md:402-463). Milestone says "8+ mentors"; spec ships 16 named NPCs as mentors.

| Technique | Tier | Variants spec'd | Mentor NPCs spec'd | Variant in code? | Mentor NPC in content/npcs.json? | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Cleaving Blow | L4 | 4 (Steppe Wind, Stone Splitter, Thornveld Sweep, Tide Breaker) | War Captain Dreva, Forge-Sergeant Brak, Elder Thornwarden Asha, Bosun Krath | No | No | NOT_SHIPPED |
| Precision Strike | L4 | 2 (Hawk's Eye, Quiet Blade) | Scout-Marshal Rynn, "Whisper" (retired assassin) | No | No | NOT_SHIPPED |
| Taunt | L4 | 2 (Blood Challenge, Shield Provocation) | Clan Duel-Keeper Voss, Garrison Master Tull | No | No | NOT_SHIPPED |
| Reckless Assault | L4 | 2 (Berserker's Momentum, Cornered Fury) | Shaman-Warrior Grul, "Red Mira" (pit fighter) | No | No | NOT_SHIPPED |
| War Cry | L8 | 2 (Thunderclap, Commander's Voice) | Steppe Storm-Singer Kelva, General Aldra Vane | No | No | NOT_SHIPPED |
| Unstoppable Charge | L8 | 1 (Avalanche) | Keldaran Mountain Guard Captain | No | No | NOT_SHIPPED |
| Whirlwind | L8 | 1 (Eye of the Storm) | Retired Gladiator Ser Orin | No | No | NOT_SHIPPED |
| Iron Stance | L8 | 2 (Mountain's Root, Last Wall) | Elder Guardian Thane Durrak, Ashmark Sergeant Kael Thornridge | No | No | NOT_SHIPPED |

## Rogue mentor coverage

6 techniques + 6 spec variants (npcs.md:464-505). 1 variant per technique.

| Technique | Tier | Variant spec'd | Mentor NPC spec'd | Variant in code? | Mentor NPC in content/npcs.json? | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Dirty Trick | L4 | Gutter Fighting | Street Boss Pell | No | No | NOT_SHIPPED |
| Quick Fingers | L4 | Magpie's Touch | Master Thief "Silk" | No | No | NOT_SHIPPED |
| Smoke Bomb | L4 | Flash Powder | Alchemist Tomas Vey | No | No | NOT_SHIPPED |
| Crippling Strike | L4 | Tendon Slash | Ashmark Field Surgeon Lira | No | No | NOT_SHIPPED |
| Shadow Step | L8 | Veil Walk | Vaelti shadow-dancer (name unknown) | No | No | NOT_SHIPPED |
| Exploit Weakness | L8 | Analytical Strike | Seeker-Agent Emris | No | **Probable match: `scholar_emris` ("Emris of the Diaspora") in content/npcs.json** — same character, no mentor-variant binding | NOT_SHIPPED (NPC shipped, variant data not) |

## Other-archetype mentor coverage

Milestone L97 enumerates Guardian/Skirmisher/Bard/Spy. Spec L508-541 ships 1 representative per archetype plus a Diplomat archetype (NEW vs milestone). Milestone wants "at least 2 representative mentors" per archetype — spec is short by 1 each.

| Archetype | Mentor spec'd | Variant spec'd | Mentor NPC in content? | Status |
| --- | --- | --- | --- | --- |
| Guardian (L4) | Village Elder Greta | Taunt → Stand-Firm | No | NOT_SHIPPED |
| Guardian (L8) | Warden-Captain (unnamed) | Living Fortress | No | NOT_SHIPPED |
| Skirmisher (L4) | Elari Blade-Singer Isara | Dual Strike | No | NOT_SHIPPED |
| Spy (L4) | Apothecary Old Vaen | Poison Craft | No | NOT_SHIPPED |
| Bard (L4) | Drathian Keeper of Songs | Song of Rest | No | NOT_SHIPPED |
| **Diplomat (NEW)** — spec section heading (npcs.md:508) lists "Guardian, Skirmisher, Spy, Bard, Diplomat Mentors" but milestone bullet enumerates only 4 archetypes | (spec content varies) | — | No | NOT_SHIPPED |

## Generation/check surfaces

| Surface | Expected signature | Evidence | Status |
| --- | --- | --- | --- |
| `check_mentor_requirements` (pure function + agent tool) | `(player, mentor, variant) -> {pass: bool, unmet: list[str]}` per milestone L91-100 | `grep -rn 'check_mentor_requirements' apps/ packages/` → 0 matches. Disposition + skill-tier + gold + quest subsystems exist independently; integration into a single requirement-evaluator does not. | NOT_SHIPPED |
| `enroll_mentor_training` (agent tool, mutation) | Starts training cycle after `check_mentor_requirements` passes (milestone L92, L100) | Async-training pipeline shipped (state machine + 4 programs + 8 activity types + `training_activities` table). `mentor_id` field on programs exists. Missing: variant binding, requirement-gate check, agent-tool registration in CITY_TOOLS. | DESIGNED |
| Training cycles tracked per player per variant | `training_activities` row per player+variant with cycle progression | `training_activities` table (migration 016) tracks per-player cycles via `player_id` + `activity_type`. `data JSONB` field could carry `variant_id` but no shipping code stores it there. The cycle dimension is BUILT; the variant dimension is NOT_SHIPPED. | DESIGNED |

## M2.5 ability-link coverage

Acceptance bullet 8 requires "Mentor data links correctly to Phase 2 M2.5 ability definitions". Per sprint-002 audit, M2.5 is 0/1/6 — only generic state machine + 2 NPC stubs ship; no ability symbol exists for any technique_id.

| technique_id (spec) | Ability symbol in apps/agent? | Linkable? | Status |
| --- | --- | --- | --- |
| cleaving_blow | `grep -rn 'cleaving_blow\|Cleaving Blow' apps/agent` → 0 matches | No | NOT_SHIPPED |
| precision_strike | No | No | NOT_SHIPPED |
| taunt | No (false positives in narration text only) | No | NOT_SHIPPED |
| reckless_assault | No | No | NOT_SHIPPED |
| war_cry | No | No | NOT_SHIPPED |
| unstoppable_charge | No | No | NOT_SHIPPED |
| whirlwind | No | No | NOT_SHIPPED |
| iron_stance | No | No | NOT_SHIPPED |
| dirty_trick | No | No | NOT_SHIPPED |
| quick_fingers | No | No | NOT_SHIPPED |
| smoke_bomb | No | No | NOT_SHIPPED |
| crippling_strike | No | No | NOT_SHIPPED |
| shadow_step | No | No | NOT_SHIPPED |
| exploit_weakness | No | No | NOT_SHIPPED |

All 14 are NOT_SHIPPED. The link target itself (M2.5 abilities) is unbuilt — see `docs/milestones/audit/phase-2-archetypes.md` row M2.5.

## Material gaps

1. **`content/mentor_variants.json`** (or migration-seeded `mentor_registry` table) — does not exist. Spec defines 22+ named variants across Warrior (16) + Rogue (6), plus ~5 for other archetypes.
2. **`mentor_registry` DB table** — no migration creates it. The 17 shipped migrations include 016/017 for training infrastructure but no mentor-variant store.
3. **`mentor{}` field on the NPC schema** — story-001 audit M6.1 row 1: not on TS Npc interface, not in content/npcs.json entries. M6.3 cannot bind variant data to NPCs without M6.1 schema landing first.
4. **`variant_id` dimension on `training_activities`** — table exists with `data JSONB` but no shipping code stores variant_id there; per-variant cycle tracking is unbuilt.
5. **Mentor NPC entries in `content/npcs.json`** — 0 of 21+ named spec mentors are seeded. (Likely match for Seeker-Agent Emris = `scholar_emris` is one possible binding but its `mentor{}` field can't be set until M6.1 schema lands.)
6. **`check_mentor_requirements` pure function** — 0 hits in apps/agent.
7. **`enroll_mentor_training` agent tool** — not in CITY_TOOLS.
8. **M2.5 ability symbols** — 14 technique_ids referenced by mentor variants have 0 ability binding in apps/agent (chain failure with sprint-002 M2.5 audit).
9. **Quest-completion check function** — `requirements.quest` field references quest ids; no `check_quest_completed(player_id, quest_id)` pure function exists in apps/agent (quest update tools exist; completion query for gating does not).

## Cross-doc deps

- **M6.3 → M6.1 (NPC schema).** The mentor registry binds variant data to NPCs via the `mentor{}` nested field on the NPC schema (spec npcs.md:48-56). Story-001 audit found this field NOT_SHIPPED on `packages/shared/src/entities/npc.ts`. M6.1 schema must land first.
- **M6.3 → Phase 2 M2.5 (Martial Mentor System).** Compound dependency: M2.5 itself is 0/1/6 per sprint-002 audit. Mentor variants modify base techniques (Cleaving Blow → Steppe Wind, etc.) — the base abilities must exist before variants can reference them.
- **M6.3 → Phase 2 M2.2 (Ability System).** M2.5 in turn depends on M2.2 (ability data tables + content); chain: M6.3 → M2.5 → M2.2.
- **M6.3 → M6.2 (Settlement Templates).** Settlement role-distribution table (spec npcs.md:578) gates mentor availability by settlement tier (Hamlet 0 mentors → City 3-6 mentors). Story-002 audit found M6.2 NOT_SHIPPED.
- **M6.3 → Phase 1 (skill tiers + disposition).** Skill-tier persistence + NPC disposition (`apps/agent/db_queries.py:22-52`) feed `check_mentor_requirements`. Skill tiers are BUILT (per sprint-001); disposition is BUILT (per story-001 audit row 4). The integration function is the gap.
- **M6.3 → quest system.** Mentor requirements include quest completion (npcs.md:394). Quest tooling exists in `apps/agent` but no quest-completion gate function for mentor enrollment.
- **M6.3 → faction system.** Mentor culture field (spec npcs.md:390) names Drathian / Keldaran / Thornwarden / Ashmark / Aelindran / Vaelti / etc. — overlaps `content/factions.json` content but no shipping faction→mentor binding.

## Out-of-scope findings (Sprint-spec-cleanup punch list)

- **Spec exceeds milestone on Warrior mentor count.** Milestone says "8+ mentors"; spec ships 16 variants across 8 techniques. The "8+" undercount is the loose floor; the actual coverage target should be 16. Capstone should record so M6.3 implementation knows the real surface size.
- **Spec/milestone Guardian/Skirmisher/Spy/Bard divergence.** Milestone L97 says "each have at least 2 representative mentors"; spec ships exactly 1 per archetype. Either spec needs to add a 2nd representative each or milestone target should be relaxed to "1+ per archetype". Capstone for customer resolution.
- **Diplomat archetype NEW vs milestone.** Spec section heading L508 enumerates "Guardian, Skirmisher, Spy, Bard, Diplomat Mentors" — milestone's M6.3 bullet drops Diplomat. Either add Diplomat to the milestone (with variant data) or document the deferral.
- **`culture` field NEW vs milestone deliverables list.** Mentor schema spec L390 carries `culture: str` field on every variant; milestone L88 enumerates the other 6 schema fields but omits culture. Capstone should record for schema-completeness.
- **`seeker_emris` ≠ `scholar_emris` name disambiguation.** Spec L505 names "Seeker-Agent Emris"; shipped NPC id is `scholar_emris` ("Emris of the Diaspora"). Same character per role match (Aelindran scholar, Accord of Tides research quarter). Capstone should record the rename or alias once M6.1 schema lands.
- **Training-program `mentor_id` field is partial overlap.** `content/training_programs.json` already wires `mentor_id` per program but to non-spec mentors (`guildmaster_torin`/`scholar_emris`) and to stat-training programs, not technique variants. M6.3 implementation should either reuse this binding pattern at the variant level or document why technique-mentor training diverges from program-mentor training.
- **`training_activities.data JSONB`** has unused capacity for variant_id. M6.3 implementation should decide whether to (a) add a typed `variant_id` column with migration, or (b) namespace under the existing JSONB. Either is workable; capstone should record the choice.
- **`training_activity_types.json` already includes `technique_mentor`** (alongside `technique_base`). Activity type name suggests M6.3 territory but no per-variant data is wired to it. Implementation pattern: extend `technique_mentor` rows to carry variant_id + requirements.

**Hand-off:** every bullet above is consumed by story-005 (sprint-005 capstone), which adds the Sprint-005 section + Sprint-spec-cleanup punch list to `docs/milestones/audit/README.md` per sprint.json's story-005 `file_domain`. This audit file is the source-of-truth for capstone consolidation of M6.3 findings.

## Verification reproducibility

The NOT_SHIPPED claims above rest on negative-grep evidence. Re-run these from the repo root to verify the audit didn't go stale (run as of sprint-005 sprint branch tip with stories 001-002 merged):

```bash
# 1. No mentor-registry symbols anywhere
grep -rn 'mentor_registry\|mentor_variants\|MentorVariant\|check_mentor_requirements\|enroll_mentor_training' apps/ packages/

# 2. No mentor-registry table
grep -l 'mentor_registry\|mentor_variants' scripts/migrations/*.sql

# 3. No M2.5 ability symbols (Warrior + Rogue technique_ids)
grep -rnE 'cleaving_blow|precision_strike|reckless_assault|unstoppable_charge|iron_stance|dirty_trick|quick_fingers|crippling_strike|shadow_step|exploit_weakness' apps/agent

# 4. Training-cycle infra shipped, variant_id dimension absent
grep -nE 'variant_id|variant_name' scripts/migrations/016_training_activities.sql

# 5. content/training_programs.json wires mentor_id but only to 2 narration-shim mentors
python3 -c "import json; d=json.load(open('content/training_programs.json')); print('programs:', [(e['id'], e['mentor_id']) for e in d])"

# 6. content/training_activity_types.json includes technique_mentor type but no variant binding
python3 -c "import json; d=json.load(open('content/training_activity_types.json')); print('types:', [e['id'] for e in d])"
```

Expected outputs as of this audit:
- #1: 0 matches.
- #2: 0 lines.
- #3: 0 matches.
- #4: 0 matches in migration 016.
- #5: 4 programs all wired to `guildmaster_torin` or `scholar_emris`.
- #6: 8 activity-type IDs including `technique_base` and `technique_mentor`.

A non-empty result on #1-#4 means downstream M6.3 implementation has landed code that this audit's NOT_SHIPPED verdicts should be re-evaluated against.
