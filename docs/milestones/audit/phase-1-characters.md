# Phase 1 Audit — Character Systems (M1.3 + M1.4)

Sprint-001 / Milestone 1. Read-only audit of M1.3 and M1.4 acceptance items in `docs/milestones/01_core_systems.md`. Symbols are grepped against `apps/agent/` and `apps/agent/tests/`; archetype patterns are walked against `ARCHETYPE_RESOURCE_CONFIG`. Status legend: **confirmed** (symbol + tests exist and match spec), **aspirational** (spec symbol/feature is missing or renamed without a wrapper), **unverified** (partial — code present but coverage or scope diverges from spec).

## Summary

| Section | Confirmed | Aspirational | Unverified |
| --- | --- | --- | --- |
| M1.3 — Resource Pools | 7 | 0 | 0 |
| M1.3 — Archetype patterns (18) | 18 | 0 | 0 |
| M1.4 — Leveling | 5 | 1 | 2 |

Naming caveats (deliverables only — not part of acceptance criteria):
- Spec deliverable named `calculate_max_pool` (singular); implementation is `calculate_max_pools` (plural). Same function, returns `PoolMaximums(stamina, focus, pattern)`.
- Spec deliverable named `get_narrative_state`; implementation is `get_pool_state` + `get_pool_narrative` in `apps/agent/fatigue_narration.py`. Behavior matches.
- Spec deliverable named `calculate_level(total_xp) -> level`; no such standalone function exists. Level computation is folded into `check_level_up(current_xp, xp_gained, current_level)` in `apps/agent/rules_engine.py:274`. Acceptance criteria do not require the standalone name.
- Spec deliverable named agent tool `apply_level_up(character_id)`; no such tool exists. Level-up rewards are emitted as a side effect of `award_xp` in `apps/agent/progression_tools.py:26` (which calls `check_level_up` and publishes a `LEVEL_UP` event via `build_level_up_payload` / `get_level_up_rewards`). The acceptance checkbox for the narration event is met; the dedicated `apply_level_up` tool name is aspirational.
- 18 archetypes are encoded in Python (`ARCHETYPE_RESOURCE_CONFIG` + `ARCHETYPE_HP_CONFIG`), not in `content/archetypes/*.json`. No `content/archetypes/` directory exists. Acceptance does not require JSON content; the encoding is in code.

## M1.3 — Resource Pools

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Each archetype correctly assigned to Stamina-only, Focus-only, Focus-primary, or Split | `apps/agent/rules_engine.py:30` — `ARCHETYPE_RESOURCE_CONFIG` (18 entries, 4 patterns) | `apps/agent/tests/test_rules_pools.py:57` TestArchetypeResourceConfig (asserts `len == 18`, per-pattern checks) | confirmed |
| HP formula uses CON modifier at half-rate per level and produces correct values L1-20 | `apps/agent/hp_scaling.py:41` `calculate_hp` — `(level - 1) * (growth + (con_mod + 1) // 2)` | `apps/agent/tests/test_hp_scaling.py` (full file; covers L1-20, all 18 archetypes, CON ±) | confirmed |
| Short rest restores Stamina to full and Focus to 50% | `apps/agent/rest_mechanics.py:8` `apply_short_rest` — `new_focus = max(current_focus, max_focus // 2)` | `apps/agent/tests/test_rest_mechanics.py:8` TestApplyShortRest (stamina full, focus half, odd-max floor, no-reduce-above-half) | confirmed |
| Long rest restores all pools to full | `apps/agent/rest_mechanics.py:20` `apply_long_rest` — returns `(max_stamina, max_focus, max_hp)` | `apps/agent/tests/test_rest_mechanics.py:36` TestApplyLongRest | confirmed |
| Narrative state indicators trigger at correct thresholds | `apps/agent/fatigue_narration.py:39` `get_pool_state` (ratios: 0=empty, <0.2=critical, <0.6=low, <1.0=high, =1.0=full); `:53` `get_pool_narrative` | `apps/agent/tests/test_fatigue_narration.py` (threshold boundaries 19/20, 59/60, 99/100; stamina + focus copy) | confirmed |
| Resource pool calculations are pure functions with no side effects | `apps/agent/rules_engine.py:56` `_apply_pool_formula`, `:64` `calculate_max_pools` — no IO, no async, no globals mutated; module docstring states "Zero IO, zero async" | `test_rules_pools.py` invokes as pure functions (no fixtures, no mocks) | confirmed |
| Tests cover all 18 archetypes and both rest types | `test_rules_pools.py` parameterized tests at `:336-358` iterate every archetype in `ARCHETYPE_RESOURCE_CONFIG` at L1 and L20; rest types covered in `test_rest_mechanics.py` (short + long + invalid) | (same) | confirmed |

## M1.3 — Archetype Resource Patterns (18)

Walked `ARCHETYPE_RESOURCE_CONFIG` in `apps/agent/rules_engine.py:30-53`. Pattern matches spec lines 83-87 of `01_core_systems.md` exactly.

| Archetype | Pattern (encoded) | Spec pattern | Source line | Match |
| --- | --- | --- | --- | --- |
| warrior | stamina_only (CON, /1) | Stamina-only | rules_engine.py:32 | ✓ |
| guardian | stamina_only (CON, /1) | Stamina-only | rules_engine.py:33 | ✓ |
| skirmisher | stamina_only (DEX, /1) | Stamina-only | rules_engine.py:34 | ✓ |
| rogue | stamina_only (DEX, /1) | Stamina-only | rules_engine.py:35 | ✓ |
| spy | stamina_only (CHA, /1) | Stamina-only | rules_engine.py:36 | ✓ |
| mage | focus_only (INT, /1) | Focus-only | rules_engine.py:38 | ✓ |
| artificer | focus_only (INT, /1) | Focus-only | rules_engine.py:39 | ✓ |
| seeker | focus_only (INT, /1) | Focus-only | rules_engine.py:40 | ✓ |
| whisper | focus_only (INT, /2) | Focus-only | rules_engine.py:41 | ✓ |
| druid | focus_primary (CON flat / WIS /1) | Focus-primary | rules_engine.py:43 | ✓ |
| cleric | focus_primary (CON flat / WIS /1) | Focus-primary | rules_engine.py:44 | ✓ |
| beastcaller | focus_primary (CON flat / WIS /1) | Focus-primary | rules_engine.py:45 | ✓ |
| warden | focus_primary (CON flat / WIS /1) | Focus-primary | rules_engine.py:46 | ✓ |
| paladin | focus_primary (CON /3 / WIS /1) | Focus-primary | rules_engine.py:47 | ✓ |
| oracle | focus_primary (CON flat / WIS /1) | Focus-primary | rules_engine.py:48 | ✓ |
| bard | split (CON /2 / CHA /2) | Split | rules_engine.py:50 | ✓ |
| diplomat | split (CHA /2 / CHA /2) | Split | rules_engine.py:51 | ✓ |
| marshal | split (STR /2 / CHA /2) | Split | rules_engine.py:52 | ✓ |

Note: archetypes live in code (`ARCHETYPE_RESOURCE_CONFIG` and `ARCHETYPE_HP_CONFIG` at `apps/agent/hp_scaling.py:16`), not in `content/archetypes/*.json` (no such directory). The spec deliverable did not require JSON encoding, so this is documentation-of-truth only.

## M1.4 — Leveling

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| `XP_FOR_LEVEL` updated from D&D 5e values to canonical scale | `apps/agent/rules_engine.py:236-257` — table 0..11250 across 20 levels | `apps/agent/tests/test_rules_leveling.py:52` `test_xp_table_matches_canonical` asserts exact dict equality against `game_mechanics_core.md` canonical | confirmed |
| XP thresholds produce correct levels for all 20 levels | `rules_engine.py:274` `check_level_up` — iterates 1..20, picks highest met threshold | `test_rules_leveling.py:11` TestCheckLevelUp (no-up, single, multi, exact-threshold, max-cap, monotonic) | confirmed |
| Attribute increase events fire at levels 4, 8, 12, 16, 20 with +2 points each | `rules_engine.py:260` `ATTRIBUTE_INCREASE_LEVELS = {4,8,12,16,20}`; `:285` sums +2 per crossed level. `leveling.py:48` `LEVEL_PROGRESSION` entries 4/8/12/16/20 have `attribute_points=2`. | `test_leveling.py:27` `test_attribute_points_at_correct_levels`, `:35` `test_total_attribute_points_is_10`; `test_rules_leveling.py:83-109` (L4 grants, L3 doesn't, multi-level accumulates, L1→L20 = 10) | confirmed |
| Specialization fork at L4/L5 is flagged in level-up rewards | `rules_engine.py:261` `SPECIALIZATION_LEVEL = 5`; `leveling.py:85-92` L5 entry has `specialization_fork=True, milestone_type="specialization"`. L4 carries `milestone_type="elective_techniques"` and `attribute_points=2` but `specialization_fork=False`. | `test_rules_leveling.py:113-135` (fork at L5, not L4, multi-level includes, past-fork no-flag); `test_leveling.py:39` `test_specialization_fork_only_at_l5` (explicitly asserts L4 is NOT a fork) | unverified — only L5 is flagged as a fork. The spec checkbox says "L4/L5"; the implementation treats L4 as an elective-techniques milestone (martial elective choice) and L5 alone as the specialization fork. Both levels emit milestones, but the `specialization_fork` boolean is True for L5 only. Story-006 should decide whether to reword the spec or extend the flag to L4. |
| Unified progression table covers all 20 levels with correct HP gains, attribute points, and milestones | `apps/agent/leveling.py:48` `LEVEL_PROGRESSION` covers all 20 levels with `attribute_points`, `milestone_type`, `milestone_description`, `proficiency_bonus`, `specialization_fork`, `notable`. **HP gains are NOT in this table** — they live separately in `apps/agent/hp_scaling.py:16` `ARCHETYPE_HP_CONFIG` (per-archetype base+growth). Spec deliverable line 122 of milestone doc explicitly lists "HP gain, attribute points, milestones, spell tier access, technique slots" in the unified table; spell tier access and technique slots are also absent from `LevelProgression`. | `test_leveling.py:15` TestLevelProgressionTable (20 levels present, attribute points correct, milestones at L5/10/15/20, frozen dataclass) | unverified — table is "unified" for attribute points + milestones + proficiency, but the spec's wider scope (HP, spell tiers, technique slots) is not encoded in one table. Acceptance checkbox text mentions only "HP gains, attribute points, and milestones" — HP is split into the archetype table. |
| Level-up triggers a narration event that the DM agent can consume | `apps/agent/event_types.py:30` `LEVEL_UP = "level_up"`; `apps/agent/progression_tools.py:88` publishes `(E.LEVEL_UP, build_level_up_payload(...))`; `apps/agent/leveling.py:312` `build_level_up_payload`; `:325` `get_milestone_narration` returns templated narration | `test_leveling.py:124` TestGetMilestoneNarration (L5/L10/L20 templates); `test_mutation_tools.py:217` `test_level_up`; quest tool path also publishes `LEVEL_UP` (`quest_tools.py:195`) | confirmed — note: there is no dedicated `apply_level_up(character_id)` agent tool as named in the deliverable; the event is emitted by `award_xp` / `complete_quest` paths. The narration event itself is present and consumed by the DM agent. |
| DB migration creates progression table with correct schema | `scripts/migrations/015_progression_table.sql` — creates `level_progression` table (id, data JSONB, timestamps, updated_at trigger); seed data in `content/level_progression.json` (20 entries, level/proficiency/attribute_points/milestone_type/milestone_description/notable) | (no pytest — migration ordering verified by file naming; content asserted via `test_leveling.py` since LEVEL_PROGRESSION mirrors the seed) | confirmed — schema is generic JSONB rather than typed columns, which is the project's standard pattern for reference tables. |
| Tests cover level boundaries, multi-level jumps, and milestone triggers | `test_rules_leveling.py` (boundaries: exact-threshold, max-cap, L1→L20; multi-level: L1→L8, L1→L20; milestones: L4/L5 forks) + `test_leveling.py` (milestone narrations L5/L10/L20, multi-level accumulation, archetype milestone @ L10) | (see prior columns) | confirmed |

## M1.4 — Agent Tool deliverable

The milestone lists `apply_level_up(character_id)` as an agent tool deliverable (line 125 of `01_core_systems.md`). No such tool exists in `apps/agent/`.

| Spec name | Actual | File:line | Status |
| --- | --- | --- | --- |
| `apply_level_up(character_id)` agent tool | Wrapped inside `award_xp` agent tool — calls `check_level_up`, persists XP/level via `update_player_xp`, publishes `LEVEL_UP` event with full reward payload | `apps/agent/progression_tools.py:26` (tool); `:67` (check_level_up); `:69` (update_player_xp); `:88` (LEVEL_UP publish) | aspirational |

The level-up acceptance criteria (narration event, attribute points, specialization fork) are all met via this indirect path, but the named tool deliverable is not present as a separate `@function_tool`. Story-006 (capstone) should decide whether to uncheck the deliverable or leave acceptance criteria checked since they are functionally satisfied.

## Cross-cutting observations

1. **No `content/archetypes/` directory.** The 18 archetypes are wholly encoded in `apps/agent/rules_engine.py:30` and `apps/agent/hp_scaling.py:16`. Mobile/server packages do not appear to reference per-archetype JSON content for resource patterns. If `packages/shared/src/entities/` was expected to mirror these, that mirror does not exist for resource patterns. Outside the M1.3/M1.4 audit scope but flagged for story-006.
2. **`LEVEL_PROGRESSION` is partial-unified.** Only attribute points, milestones, proficiency, and specialization fork are unified. HP gain remains in `ARCHETYPE_HP_CONFIG`; spell tier access and technique slots are not encoded in any unified table. Acceptance text ("HP gains, attribute points, and milestones") still passes if HP-via-archetype-table is accepted as "covered," but it diverges from the deliverable wording.
3. **No `calculate_level` standalone function.** Spec deliverable lists `calculate_level(total_xp) -> level`. Implementation only exposes `check_level_up(current_xp, xp_gained, current_level)`. To recover level from total XP alone, callers must invoke `check_level_up(0, total_xp, 1)` — a usable workaround, but not what the deliverable promised. Not blocking any acceptance criterion.
