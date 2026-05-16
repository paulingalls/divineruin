# Phase 1 Audit — Rules Engine (M1.1 + M1.2)

Sprint-001 / Milestone 1. Read-only audit of M1.1 and M1.2 acceptance items in `docs/milestones/01_core_systems.md`. Each checkbox is mapped to the implementing symbol (file:line) and to the pytest module that exercises it.

## Summary

| Section | Confirmed | Aspirational | Unverified |
| --- | --- | --- | --- |
| M1.1 | 7 | 0 | 0 |
| M1.2 | 7 | 0 | 0 |

## M1.1 — Attribute System & Core Resolution

| Item | Evidence | Tests | Status |
| --- | --- | --- | --- |
| `resolve_check` is a pure function with no side effects or DB calls | apps/agent/check_resolution.py:117 `resolve_check` (accepts injectable `rng`, returns frozen `CheckResult` dataclass, no IO, no `await`) | apps/agent/tests/test_rules_resolution.py — `TestResolveCheck`, `TestNatural20And1`, `TestDeterminism` (`test_deterministic_with_rng` L164) | confirmed |
| Modifier math matches `(attr - 10) // 2` for all attribute values 1-30 | apps/agent/rules_engine.py:301 `attribute_modifier` | apps/agent/tests/test_rules_core.py:22 `TestAttributeModifier` (`test_standard_table`, `test_odd_scores`) | confirmed |
| Auto-fail triggers correctly at DC 24+ for below Expert and DC 28+ for below Master | apps/agent/check_resolution.py:106 `_check_auto_fail` (used by `resolve_check` L141) | apps/agent/tests/test_rules_resolution.py:95-118 `TestAutoFail` (`test_auto_fail_untrained_dc24`, `test_auto_fail_trained_dc24`, `test_expert_can_attempt_dc24`, `test_auto_fail_expert_dc28`, `test_master_can_attempt_dc28`, `test_auto_fail_overrides_nat20`) | confirmed |
| Proficiency bonus returns correct value for all 20 levels | apps/agent/rules_engine.py:136 `proficiency_bonus`; precomputed table `PROFICIENCY_BY_LEVEL` L145 | apps/agent/tests/test_rules_core.py:202 `TestProficiencyBonus` (`test_levels_1_through_6`, `test_levels_7_through_13`, `test_levels_14_through_20`, `test_breakpoints`) | confirmed |
| Result packet includes margin, success/fail flag, critical flag, and narrative cue | apps/agent/check_resolution.py:27 `CheckResult` (fields: `success`, `auto_fail`, `margin`, `critical_success`, `critical_failure`, `narrative_hint`) | apps/agent/tests/test_rules_resolution.py:130-167 `TestMargin`, `TestCriticalFlags`, `TestNarrativeHint` | confirmed |
| All DC scale constants are defined and tested | apps/agent/rules_engine.py:115 `DC_TIERS` (trivial 5, easy 8, moderate 12, hard 16, very_hard 20, extreme 24, legendary 28; `deadly` retained as deprecated alias for `extreme`) | apps/agent/tests/test_rules_core.py:160 `TestDcForTier` (`test_all_tiers`, `test_deadly_alias`, `test_dc_tiers_dict_has_all_entries`) | confirmed |
| 100% test coverage on resolution logic | Coverage source: 27 tests across `TestResolveCheck`, `TestNatural20And1`, `TestAutoFail`, `TestMargin`, `TestCriticalFlags`, `TestNarrativeHint`, `TestDeterminism` exercising every branch in apps/agent/check_resolution.py:117-177 | apps/agent/tests/test_rules_resolution.py (entire `class TestResolveCheck` group); apps/agent/tests/test_rules_core.py:244 `TestNarrativeHint` covers L346-359 in `rules_engine.py` | confirmed (branch-level coverage by inspection; no `pytest --cov` report is checked in to verify the literal 100% claim) |

**Supporting constants verified inline:**
- 6-attribute model used throughout (`strength`, `dexterity`, `constitution`, `intelligence`, `wisdom`, `charisma`) — apps/agent/rules_engine.py:89-113 `SKILLS` map; apps/agent/check_resolution.py:318 `valid_saves` set.
- Skill tier bonus constants — apps/agent/rules_engine.py:126 `SKILL_TIER_BONUS` (untrained 0, trained 2, expert 4, master 5). Tested at apps/agent/tests/test_rules_core.py:224 `TestSkillTierBonus`.
- Narrative cue function — apps/agent/rules_engine.py:346 `narrative_hint`. Tested at apps/agent/tests/test_rules_core.py:244 `TestNarrativeHint`.

## M1.2 — Skill Tier System

| Item | Evidence | Tests | Status |
| --- | --- | --- | --- |
| All 20 skills defined with category, tier thresholds, and unlock descriptions | apps/agent/rules_engine.py:89 `SKILLS` (20 entries, grouped Physical/Mental/Social by comment); apps/agent/rules_engine.py:147 `ADVANCEMENT_THRESHOLDS`; apps/agent/rules_engine.py:153 `SKILL_CAPABILITIES` (expert + master strings for all 20) | apps/agent/tests/test_rules_core.py:125-156 `TestSkillsConstants` (`test_has_20_skills`, `test_physical_skills`, `test_mental_skills`, `test_social_skills`, `test_crafting_is_multi_attribute`); apps/agent/tests/test_rules_skills.py:35 `TestSkillCapabilitiesConstants` (`test_all_20_skills_present`, `test_each_skill_has_expert_and_master`) | confirmed |
| `record_skill_use` increments counter and triggers tier advancement at correct thresholds | apps/agent/check_resolution.py:358 `record_skill_use` (returns `AdvancementResult`) | apps/agent/tests/test_rules_skills.py:105 `TestRecordSkillUse` (`test_increments_counter`, `test_untrained_to_trained_at_8`, `test_trained_to_expert_at_20`, `test_no_advancement_below_threshold`) | confirmed |
| Expert→Master requires 40 uses AND a narrative moment flag | apps/agent/check_resolution.py:381-389 (early return when `current_tier == "expert" and not narrative_moment`) | apps/agent/tests/test_rules_skills.py:137 `test_expert_to_master_at_40_with_narrative_moment`; L149 `test_expert_to_master_blocked_without_narrative_moment` | confirmed |
| `check_skill_capabilities` returns correct capabilities for each tier | apps/agent/check_resolution.py:411 `check_skill_capabilities` | apps/agent/tests/test_rules_skills.py:184 `TestCheckSkillCapabilities` (untrained, trained, expert, master cases plus `test_all_skills_at_expert`, `test_all_skills_at_master`) | confirmed |
| Hybrid counter: both session use and Training increments share the same counter | Session use path: apps/agent/check_tools.py:188-196 reads `skill_advancement` via `get_single_skill_advancement`, calls `record_skill_use`, writes back with `update_skill_advancement`. Training path: apps/agent/async_worker.py:290-309 — when `activity_type == "skill_practice"`, reads the same `skill_advancement` row, calls the same `record_skill_use`, writes via the same `update_skill_advancement`. Single source of truth = `skill_advancement` table. | apps/agent/tests/test_rules_skills.py — unit coverage on `record_skill_use` shared by both paths; no dedicated integration test asserts the two paths share the row (note: `test_async_e2e.py` and `test_training_integration.py` exercise the async path) | confirmed |
| DB migration creates `skill_advancement` table with correct schema | scripts/migrations/014_skill_advancement.sql (columns: `player_id`, `skill_id`, `tier`, `use_counter`, `narrative_moment_ready`, `updated_at`; PK on `(player_id, skill_id)`; index `idx_skill_advancement_player`) | No `*.sql` migration test; runtime queries exercised by apps/agent/tests/test_async_db.py and apps/agent/tests/test_async_e2e.py via `get_single_skill_advancement` / `update_skill_advancement` | confirmed |
| Tests cover all tier transitions including edge cases (counter at threshold - 1, at threshold) | apps/agent/tests/test_rules_skills.py:115 `test_no_advancement_below_threshold` (count 6 → 7, no advancement); L122 `test_untrained_to_trained_at_8` (count 7 → 8); L130 `test_trained_to_expert_at_20` (19 → 20); L137 `test_expert_to_master_at_40_with_narrative_moment` (39 → 40); L156 `test_master_stays_master`; L167 `test_does_not_mutate_inputs` | apps/agent/tests/test_rules_skills.py — `TestRecordSkillUse` class | confirmed |

**Schema-vs-spec note:** the spec lists `skill_advancement (skill_id, character_id, tier, use_counter)`; the migration uses `player_id` rather than `character_id` and adds `narrative_moment_ready` + `updated_at`. The columns required by the spec are all present, with `player_id` semantically equivalent to `character_id` in the current codebase (no separate character model exists yet).
