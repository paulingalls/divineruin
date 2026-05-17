# Phase 6 Audit — NPCs M6.4 (Companion Profiles, Scaling, Relationship)

Sprint-005 / Milestone 5 (story-004). Read-only audit of `docs/milestones/06_npcs.md` §M6.4 (L112-150) against `docs/game_mechanics/game_mechanics_npcs.md` §Companion Mechanical Framework (L630-881) and shipped code in `apps/agent/`, `apps/server/`, `packages/shared/src/entities/`, `content/`, and `scripts/migrations/`. Status legend (matches sprint-004 audit/README.md L49-58): **BUILT** = code present and matches spec; **DESIGNED** = spec well-defined and partial code exists, but the symbol/feature is missing, renamed, or diverges; **NOT_SHIPPED** = no implementation found. Sibling sprint-005 audit files: `docs/milestones/audit/phase-6-schema-archetypes.md` (M6.1), `phase-6-settlements.md` (M6.2), `phase-6-mentors.md` (M6.3).

## Summary

| Section | BUILT | DESIGNED | NOT_SHIPPED |
| --- | --- | --- | --- |
| M6.4 — Companion Profiles, Scaling, Relationship (9 acceptance items) | 1 | 3 | 5 |
| Companion profile coverage (4 archetype rows) | 0 | 1 | 3 |
| Relationship tier coverage (5 named tiers) | 0 | 0 | 5 |
| Generation surfaces (4 functions/tables) | 0 | 0 | 4 |
| Hostile encounter templates (4 rows; cross-ref story-002) | 0 | 0 | 4 |

**Headline finding:** M6.4 is the richest partial-implementation surface in sprint-005. **One acceptance bullet is genuinely BUILT** (negative-condition: "Relationship tier does NOT affect combat stats" — combat code reads `combat_stats` from content, independent of `CompanionState.relationship_tier`). **Three are DESIGNED** (4-archetype-profile coverage — Kael ships partial in `content/npcs.json:147-223`; 5-relationship-tier coverage — int tracker in `apps/agent/session_data.py:22` + system-prompt display in `apps/agent/warm_prompts.py:180`; companion-stat-block-validates-as-NPC — Kael's entry uses the NPC schema, but only because M6.4 fields aren't there to validate per story-001 finding). **Five are NOT_SHIPPED** (per-companion ability count, HP scaling function, hostile encounter integration, scaling+transition tests, `content/companions.json`).

What ships beyond what the milestone enumerates: `CompanionState` dataclass with `is_present/is_conscious/emotional_state/relationship_tier/session_memories/last_speech_time` (`apps/agent/session_data.py:15-24`); companion-in-combat as a `CombatParticipant` (`apps/agent/combat_init.py` + tests at `apps/agent/tests/test_companion.py:471-505`); idle-speech LLM generation (`apps/agent/companion_idle.py`); 4 narration shims in `apps/agent/activity_templates.py:31-78` `COMPANION_CONTEXT` (Kael/Lira/Tam/Sable personality+speech+voice+errand frames); relationship_tier used as +1/+4 errand-success bonus at `apps/agent/async_rules.py:143-147`. All NEW vs milestone — flagged for capstone.

Honesty note on Kael's `action_pool`: `content/npcs.json:147-223` ships Kael with `combat_stats.action_pool` as a **flat list of 2 entries** (Longsword + Defensive Stance) — neither typed nor counted into the spec's 4-bucket shape (attacks/passives/actives/reactions). Longsword matches spec; Defensive Stance is non-spec (spec attack #2 is Shield Bash; spec also defines 2 passives, 2 actives, 1 reaction — none shipped). The structural divergence — flat list vs typed buckets — is itself a NOT_SHIPPED finding for bullet 2.

## Coverage matrix

| Spec section (file:line) | Milestone item | Notes |
| --- | --- | --- |
| The Four Companion Archetypes (npcs.md:672-683) | M6.4 — 4 archetypes | Spec table lists Kael/Lira/Tam/Sable and their player-archetype complements. **Confirmed exactly 4 — no 5th archetype like the Diplomat divergence in M6.3.** |
| Kael — The Steadfast Partner (npcs.md:685-717) | M6.4 — Kael combat profile | Spec ships full profile: 2 attacks (Longsword, Shield Bash), 2 passives, 2 actives, 1 reaction. Includes scaling rules (+1 STR at L4/L12, +1 CON at L8/L16). |
| Lira — The Skeptical Scholar (npcs.md:720-749) | M6.4 — Lira combat profile | Spec ships full profile (1 attack, 2 passives, 3 actives, 0 reactions). Not in content/npcs.json. |
| Tam — The Reckless Heart (npcs.md:752-784) | M6.4 — Tam combat profile | Spec ships full profile (2 attacks, 2 passives, 2 actives, 1 reaction). Not in content/npcs.json. |
| Sable — The Quiet Watcher (npcs.md:787-820) | M6.4 — Sable combat profile | Spec ships full profile (1 attack, 3 passives, 2 actives, 0 reactions). Not in content/npcs.json. Spec note: non-verbal — DM doesn't voice. |
| Companion Combat Effectiveness Target (npcs.md:634-643) | M6.4 — 75% HP scaling | Spec sets target at "1 player + 1 companion = 1.75× a single character" → 75% combat output → HP formula `floor(player_max_hp × 0.75)`. |
| Companion Scaling Formula (npcs.md:645-670) | M6.4 — `scale_companion_stats_to_player_level` | Spec defines per-attribute scaling per companion (Kael +1 STR at L4/L12, +1 CON at L8/L16, +1 WIS at L20; similar for others). |
| Companion Assignment Logic (npcs.md:823-849) | NEW | Spec's archetype-complement assignment rule (e.g., Mages get Kael, Warriors get Lira) is not enumerated in M6.4 deliverables. Capstone consideration. |
| Companion Progression Milestones (npcs.md:851-863) | NEW | Spec-only — per-session milestones for unlocking companion narrative content. Overlaps M6.4 "5 relationship tiers with narrative gates" but adds specific session-count anchors. |
| Companion Death in Combat (npcs.md:865-867) | NEW | Spec cross-ref to combat death rules. M6.4 acceptance doesn't enumerate. Honored by current code: `CombatParticipant.is_fallen` + `is_conscious=False` (test_companion.py:560-613). |
| Companion Relationship (npcs.md:869-879) | M6.4 — 5 relationship tiers with narrative gates | Spec ships 5 named tiers: New (1-2 sessions), Warming (3-5), Trusted (6-10), Bonded (11-20), Legendary (20+). |

## M6.4 — Companion Profiles, Scaling, Relationship

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| All 4 companions have complete combat profiles with distinct tactical identities | Spec L685-820 ships full profiles for Kael/Lira/Tam/Sable. `content/npcs.json:147-223` ships **only Kael**, and only partially — `combat_stats` carries hp/ac/level/attributes + a flat 2-entry `action_pool` (Longsword + Defensive Stance), NOT the 7-ability spec breakdown (2 attacks + 2 passives + 2 actives + 1 reaction). `apps/agent/activity_templates.py:31-78` `COMPANION_CONTEXT` has narration shims for all 4 (personality, speech_style, voice_id, errand_frames) but those are not combat profiles. 1 of 4 partial; 3 of 4 absent. | None — `apps/agent/tests/test_companion.py:471-505` covers combat integration for the shipped Kael skeleton, not profile completeness for all 4. | DESIGNED |
| Each companion has correct count of attacks (2-4), passives (2-3), actives (2-3), reactions (0-1) | Kael's shipped `action_pool` is a flat list of 2 entries (Longsword, Defensive Stance) — not typed into attacks/passives/actives/reactions buckets. Spec Kael (npcs.md:702-717) lists 2 attacks + 2 passives + 2 actives + 1 reaction = 7 abilities; shipped count is 2 untyped. Shield Bash (spec attack #2) is absent; Defensive Stance (shipped) is not in spec. Lira/Tam/Sable: 0 abilities shipped. Ability-count gate satisfied for 0 of 4 companions. | None | NOT_SHIPPED |
| `scale_companion_stats_to_player_level` produces HP at 75% of player HP for levels 1-20 | No symbol. `grep -rn 'scale_companion_stats_to_player_level\|scale_companion' apps/ packages/` → 0 matches. Kael's `hp: 22` at `content/npcs.json` is hard-coded (player level 2 has 25 max HP per `apps/agent/hp_scaling.py`; 75% = ~19, content has 22 — close but not formula-driven, and only one data point). No level-1/5/10/15/20 scaling tests. | None | NOT_SHIPPED |
| All 5 relationship tiers defined with narrative content gates | `apps/agent/session_data.py:22` `CompanionState.relationship_tier: int = 1` — int tracker is BUILT and used in `apps/agent/warm_prompts.py:180` (system-prompt display) and `apps/agent/async_rules.py:143-147` (+1/+4 errand bonus). Spec L873-879 names 5 tiers — no named-tier enum in code; no `progression_value` field; no narrative-gate registry; no DB persistence (CompanionState is in-memory session state, no `companion_relationships` table in migrations 001-017). Partial int + display + bonus ship; named-tier semantics + narrative gates + persistence do not. | `apps/agent/tests/test_companion.py:619-656` covers emotional_state updates, not named-tier transitions. | DESIGNED |
| Relationship tier does NOT affect combat stats or ability availability | **Negative-condition acceptance — honored by absence of coupling code.** Combat resolution reads `combat_stats` from `content/npcs.json:147-223` (Kael's hp:22, ac:15, attributes, action_pool) independent of `CompanionState.relationship_tier` (in-memory session state, untouched by combat code). Verified: `grep -n 'relationship_tier' apps/agent/combat_*.py apps/agent/check_tools.py` → 0 matches in combat surfaces. `apps/agent/async_rules.py:143-147` uses `relationship_tier` as +1/+4 bonus for **errands** (out-of-combat), not for combat — NEW pattern vs milestone, flagged for capstone but doesn't violate the negative condition. The design separation is structurally enforced. | `apps/agent/tests/test_companion.py:471-505` exercises combat without relationship_tier dependencies (companion stat block fixed regardless of session state). | BUILT |
| Hostile encounter templates reference correct companion combat behaviors | **Cross-ref `docs/milestones/audit/phase-6-settlements.md` §Hostile encounter templates:** all 4 spec templates (Bandit Ambush, Ashmark Patrol, Cult Cell, Hollow-Corrupted Settlement) are NOT_SHIPPED in `content/encounter_templates.json` (the 6 shipped entries — shadeling_cluster, ruins_mawling_pair, hollowed_scout, hollow_wisp, hollow_patrol_greyvale, ruins_guardian — are all Hollow-themed Greyvale encounters, not the 4 humanoid-faction templates). M6.4-specific finding: even if those templates existed, no shipped template carries companion-tactic references (`grep -rn 'companion' content/encounter_templates.json` → 0 matches). M6.2 owns canonical encounter-template ownership per story-002 punch list. | None | NOT_SHIPPED |
| Companion stat blocks pass same validation as NPC stat blocks (shared schema base) | Kael's entry at `content/npcs.json:147-223` validates against the existing TS Npc interface (`packages/shared/src/entities/npc.ts:17-39`) — narrative/disposition/voice/inventory fields all match. **But:** story-001 M6.1 audit found that the NPC schema is missing `services`, `price_modifier`, `mentor{}`, `role_archetype` — and equally missing the M6.4 companion-specific fields (typed `attacks[]`, `passives[]`, `actives[]`, `reactions[]`, `scaling_rules`). Validation "passes" only because the companion-specific fields aren't there to validate. Schema reuse works for the narrative subset; the combat-profile expansion is unbuilt on both sides. | None — `apps/agent/tests/test_query_tools.py` exercises NPC validation broadly but not companion-specific bullets. | DESIGNED |
| Tests cover scaling at level boundaries (1, 5, 10, 15, 20) and all relationship tier transitions | No scaling function (row 3 above) → no scaling tests. `apps/agent/tests/test_companion.py` covers combat integration (471-505), KO (560-613), emotional state updates (619-656), session memory (658-710) — none cover the 5 named-tier transitions or HP-at-75%-per-level boundary cases. | None for the specific gates. | NOT_SHIPPED |
| `content/companions.json` contains all 4 companions with full data | File does not exist. `ls content/` yields: encounter_templates, events, factions, gods, inventory_pools, items, level_progression, locations, lore_entries, npc_state, npcs, players, quests, scenes, training_activity_types, training_programs, voice_registry — no companions.json. Only Kael in `content/npcs.json:147-223` with partial fields (no typed attacks/passives/actives/reactions, no scaling_rules). | None | NOT_SHIPPED |

**Deliverables status (per 06_npcs.md M6.4 §Deliverables L116-132):**
- 4 companion archetypes with full combat profiles: **DESIGNED** (Kael partial in npcs.json; Lira/Tam/Sable narration-only).
- Per-companion 2-4 attacks / 2-3 passives / 2-3 actives / 0-1 reactions: **NOT_SHIPPED** (Kael's flat 2-entry action_pool doesn't satisfy the typed-bucket shape).
- HP scaling 75% of player HP: **NOT_SHIPPED** (no scaling function).
- 5 relationship tiers (New/Warming/Trusted/Bonded/Legendary): **DESIGNED** (int tracker + display; no named tiers, no progression_value, no narrative gates).
- Relationship gates secrets/narratives NOT combat: **BUILT** (negative-condition structurally honored).
- 4 hostile encounter templates: **NOT_SHIPPED** (cross-ref story-002 audit).
- DB migrations `companions` + `companion_relationships` tables: **NOT_SHIPPED** (CompanionState is in-memory session state only).
- Rules engine `scale_companion_stats_to_player_level` + `query_companion_relationship`: **NOT_SHIPPED** (0 grep hits).
- Content `content/companions.json`: **NOT_SHIPPED** (file doesn't exist).

## Companion profile coverage

4 archetypes per spec (npcs.md:672-683):

| Companion | Role per spec | In content/npcs.json? | Ability counts (spec → shipped) | Narration shim? | Status |
| --- | --- | --- | --- | --- | --- |
| Kael | Martial frontline (npcs.md:685-717) | Yes (L147-223), as `companion_kael` | Spec: 2 attacks (Longsword, Shield Bash) + 2 passives (Protective Instinct, Veteran's Resilience) + 2 actives (Hold the Line, Second Wind) + 1 reaction (Intercept) = 7 abilities. Shipped: 2 untyped entries in flat `action_pool` (Longsword matches spec; Defensive Stance is non-spec — closest spec match is Hold the Line active, but renamed and reshape'd). Structural divergence: flat list vs typed buckets. | Yes (`activity_templates.py:35-43`) | DESIGNED (Kael's NPC entry partial; ability-bucket shape diverges) |
| Lira | Arcane investigation (npcs.md:720-749) | No | Spec: 1 attack + 2 passives + 3 actives + 0 reactions. Shipped: 0 abilities. | Yes (`activity_templates.py:44-55`) | NOT_SHIPPED (narration only) |
| Tam | Primal scout (npcs.md:752-784) | No | Spec: 2 attacks + 2 passives + 2 actives + 1 reaction. Shipped: 0 abilities. | Yes (`activity_templates.py:56-67`) | NOT_SHIPPED (narration only) |
| Sable | Perception/sensing (npcs.md:787-820) — **non-verbal** | No | Spec: 1 attack + 3 passives + 2 actives + 0 reactions. Shipped: 0 abilities. | Yes (`activity_templates.py:68-77`) — narration shim notes "communicates through body language, growls, and pointed looks" | NOT_SHIPPED (narration only) |

## Relationship tier coverage

5 named tiers per spec (npcs.md:873-879). All 5 share the same code-trace pattern: int tracker exists, named-tier enum + narrative gates do not.

| Tier | Spec session range | Spec narrative effect | Code or content trace | Status |
| --- | --- | --- | --- | --- |
| New | 1-2 sessions | Surface-level interactions; companion shares basic backstory | None at named-tier level. The int `CompanionState.relationship_tier = 1` (`session_data.py:22`) is the closest. | NOT_SHIPPED |
| Warming | 3-5 sessions | Companion shares mid-tier backstory + opinions; first secret available | None. | NOT_SHIPPED |
| Trusted | 6-10 sessions | Companion shares deep backstory + faction history; multiple secrets | None. | NOT_SHIPPED |
| Bonded | 11-20 sessions | Companion's loyalty triggers in pivotal moments; unique tactical advice | None. | NOT_SHIPPED |
| Legendary | 20+ sessions | Companion's growth arc completes; legacy unlocks | None. | NOT_SHIPPED |

The `relationship_tier: int` tracker + warm_prompts display + errand-bonus reads (`async_rules.py:143-147`) are shipped INFRASTRUCTURE that none of the 5 named tiers individually satisfies. Each named tier is NOT_SHIPPED at its semantic level. Recorded once at the row level above; not double-counted in the M6.4 acceptance table (bullet 4 captures the DESIGNED partial-infrastructure verdict for the section as a whole).

## Generation surfaces

| Surface | Expected signature | Evidence | Status |
| --- | --- | --- | --- |
| `scale_companion_stats_to_player_level` | `(companion, player_level) -> stat_block` returning scaled stats (HP at 75% per milestone L122) | `grep -rn 'scale_companion_stats_to_player_level\|scale_companion' apps/ packages/` → 0 matches. Not in `apps/agent/rules_engine.py`, `hp_scaling.py`, or `combat_init.py`. | NOT_SHIPPED |
| `query_companion_relationship` | `(player_id, companion_id) -> {tier, gates_available}` (milestone L127) | `grep -rn 'query_companion_relationship\|companion_relationship' apps/ packages/` → 0 matches. The underlying `CompanionState.relationship_tier` is read directly from session state at `warm_prompts.py:180` and `async_rules.py:143-147` — no query-function abstraction. | NOT_SHIPPED |
| `companions` DB table | Per milestone L129 (archetype, base_stats, ability_list, scaling_rules) | `grep -l 'companions\b\|companion_relationships' scripts/migrations/*.sql` → 0 matches. Migrations 001-017 cover npcs, npc_dispositions, npc_state, training_activities, etc. — no companions table. | NOT_SHIPPED |
| `companion_relationships` DB table | Per milestone L129 (player_id, companion_id, tier, progression_value) | Not in migrations. `CompanionState` (`session_data.py:15-24`) is in-memory dataclass, not persisted. No persistence layer for relationship_tier across sessions. | NOT_SHIPPED |

## Hostile encounter templates

Cross-ref to `docs/milestones/audit/phase-6-settlements.md` §Hostile encounter templates (story-002 M6.2 audit owns canonical evidence). All 4 templates NOT_SHIPPED in content. M6.4 angle: even if the templates existed, no current encounter content references companion combat behaviors.

| Encounter | Tier | Spec section | Story-002 verdict | Companion-integration angle (M6.4) | Status |
| --- | --- | --- | --- | --- | --- |
| Bandit Ambush | Tier 1-2 | npcs.md:601-606 | NOT_SHIPPED in content | `grep -rn 'companion' content/encounter_templates.json` → 0 matches. No tactic notes for how Kael/Lira/Tam/Sable engage bandits. | NOT_SHIPPED |
| Ashmark Patrol | Tier 2 (allied/hostile by rep) | npcs.md:608-613 | NOT_SHIPPED (name-adjacent `hollow_patrol_greyvale` ships but is Hollow-themed, not Ashmark) | Same. | NOT_SHIPPED |
| Cult Cell | Tier 2-3 | npcs.md:615-620 | NOT_SHIPPED | Same. Cult Cell composition references Priest/Bandit/Mage NPC stat blocks (story-001 audit: all NOT_SHIPPED). | NOT_SHIPPED |
| Hollow-Corrupted Settlement | Tier 2-3 | npcs.md:622-626 | NOT_SHIPPED (storage table ships, content does not) | Same. | NOT_SHIPPED |

## Material gaps

1. **`content/companions.json`** — does not exist. M6.4 deliverable L131 names this file. The 4 spec companion profiles (7+ abilities each for Kael/Tam, 3+ for Lira/Sable variants) are unbuilt at content layer.
2. **`companions` + `companion_relationships` DB tables** — no migration creates them. The 17 shipped migrations include training-activities tables (016/017) but no companion store. Companion data lives as session-only state in `CompanionState` dataclass.
3. **Typed ability buckets** — Kael's `action_pool` is a flat list. Schema-side `Npc.combat_stats.action_pool` type isn't typed into attacks/passives/actives/reactions. Cross-doc with M6.1 NPC schema (story-001 row 1: NPC schema doesn't ship the combat-extension fields either).
4. **Kael's missing abilities** — Shield Bash (spec attack #2), Protective Instinct + Veteran's Resilience (2 passives), Hold the Line + Second Wind (2 actives), Intercept (1 reaction). 6 of 7 spec abilities unbuilt.
5. **Lira/Tam/Sable full profiles** — 0 abilities shipped; only narration shims exist.
6. **HP scaling function** — `scale_companion_stats_to_player_level` is a deliverable surface (milestone L125); no formula-driven implementation exists.
7. **Named relationship tiers** — int `relationship_tier` ships; the 5 named semantic tiers (New/Warming/Trusted/Bonded/Legendary) do not, and there is no narrative-gate registry.
8. **4 hostile encounter templates** — inherits story-002 M6.2 audit verdict.
9. **`query_companion_relationship` function** — no query abstraction over the underlying int tracker.
10. **Companion persistence** — `CompanionState` is in-memory only; no per-session save/restore for relationship_tier or session_memories.

## Cross-doc deps

- **M6.4 → M6.1 (NPC schema).** Companion stat blocks reuse the NPC schema (Kael uses `Npc` interface). The M6.4 companion-specific fields (typed `attacks[]/passives[]/actives[]/reactions[]/scaling_rules`) are not on the NPC schema (story-001 finding). M6.1 schema must accommodate both archetype-template fields AND companion-combat fields, or M6.4 needs a separate `Companion` interface.
- **M6.4 → M6.2 (Hostile encounter templates).** Same 4 templates audited under M6.2 (story-002 punch list recommends M6.2 as primary owner since M6.2 owns the settlement spawn context). M6.4 records the companion-integration angle.
- **M6.4 → Phase 4 Combat.** Companion-in-combat already integrates via `CombatParticipant` (`session_data.py:28-40`) and `combat_init.py`. Companion ability execution (Hold the Line, Second Wind, Intercept) is the gap — not in `apps/agent/combat_turn.py` or `apps/agent/check_tools.py`.
- **M6.4 → Phase 7 Bestiary.** Spec L18 has NPCStatBlock inherit from CreatureStatBlock (story-001 finding: CreatureStatBlock is unshipped). Companion stat blocks would inherit the same base.
- **M6.4 → Phase 3 Magic.** Sable (mage/arcane) combat profile carries Focus pool + spell catalog references — cross-doc with Phase 3 magic system.
- **M6.4 → faction system.** Companion Assignment Logic (npcs.md:823-849) selects companion based on player archetype; Lira's "Aelindran scholarly" cultural origin links to faction data.
- **M6.4 → quest system.** Companion Progression Milestones (npcs.md:851-863) reference per-session triggers — would consume session_memories + quest_completion gates.

## Out-of-scope findings (Sprint-spec-cleanup punch list)

- **Shipped NEW infrastructure beyond M6.4's deliverables list.** `CompanionState` (id, is_present, is_conscious, emotional_state, session_memories, last_speech_time) at `session_data.py:15-24`, `companion_idle.py` LLM-generated idle speech, `bg_speech.py` proactive companion utterances, emotional-state updates tied to game events (test_companion.py:619-656), 5-entry session_memories cap (test_companion.py:658-710), narration shim COMPANION_CONTEXT for all 4 companions at activity_templates.py:31-78. Capstone should record whether this infrastructure should be retroactively added to M6.4 deliverables or split into a new milestone (M6.5 Companion Presence Layer or similar).
- **Errand-bonus relationship_tier coupling.** `apps/agent/async_rules.py:143-147` uses `relationship_tier` as +1 to +4 success bonus for errands. NEW vs milestone — M6.4 explicitly says relationship doesn't affect combat, but this is an out-of-combat coupling milestone doesn't enumerate. Should be promoted to a deliverable or deferred to a separate mechanic; capstone for customer resolution.
- **Companion Assignment Logic.** Spec L823-849 ships archetype-complement assignment (Mages get Kael, Warriors get Lira, etc.) — milestone deliverables don't enumerate this. Add to M6.4 or defer.
- **Companion Progression Milestones.** Spec L851-863 ships per-session milestone framework — overlaps M6.4 "5 tiers with narrative gates" but with specific session-count anchors. Capstone should record whether milestones-vs-tiers is one mechanic or two.
- **Kael action_pool divergence.** Shipped `action_pool` is a flat list (Longsword + Defensive Stance); spec wants typed buckets (attacks/passives/actives/reactions). Capstone should record whether to expand the NPC schema (cross-doc with M6.1) or split companion stat blocks into a dedicated `Companion` interface.
- **Defensive Stance is non-spec.** Kael's 2nd action in content is "Defensive Stance" (grants +2 AC until next turn); spec attack #2 is Shield Bash (1d4+STR bludgeoning, stun on save fail). Either the shipped ability should be renamed/replaced when M6.4 lands, or the spec should adopt Defensive Stance and drop Shield Bash. Capstone for customer resolution.
- **Sable non-verbal handling.** Spec L786-789 explicitly notes "communicates through body language, growls, and pointed looks" — non-verbal companion. Milestone doesn't enumerate special TTS handling. When M6.4 lands, capstone should record the voice-registry decision (suppress Sable's TTS entirely vs growl-only sound effects).
- **CompanionState lives in session state, not DB.** All companion runtime data is in-memory (`session_data.py:15-24`). M6.4 deliverable L129 calls for `companions` + `companion_relationships` tables. Migration design needed when M6.4 lands.

**Hand-off:** every bullet above is consumed by story-005 (sprint-005 capstone), which adds the Sprint-005 section + Sprint-spec-cleanup punch list to `docs/milestones/audit/README.md` per sprint.json's story-005 `file_domain`. This audit file is the source-of-truth for capstone consolidation of M6.4 findings.

## Verification reproducibility

The NOT_SHIPPED claims above rest on negative-grep evidence. Re-run these from the repo root to verify the audit didn't go stale (run as of sprint-005 sprint branch tip with stories 001-003 merged):

```bash
# 1. No companion scaling function
grep -rn 'scale_companion_stats_to_player_level\|scale_companion' apps/ packages/

# 2. No companion relationship query function
grep -rn 'query_companion_relationship\|companion_relationship[^_]' apps/ packages/

# 3. No companions / companion_relationships DB tables
grep -l 'companions\b\|companion_relationships' scripts/migrations/*.sql

# 4. content/companions.json absent
ls content/companions.json 2>&1

# 5. Only Kael in content/npcs.json companion entries
python3 -c "import json; d=json.load(open('content/npcs.json')); cs=[e for e in d if e.get('id','').startswith('companion_')]; print('shipped:', [(e['id'], len(e.get('combat_stats',{}).get('action_pool',[]))) for e in cs])"

# 6. Kael action_pool count and items
python3 -c "import json; d=json.load(open('content/npcs.json')); k=next(e for e in d if e['id']=='companion_kael'); ap=k['combat_stats']['action_pool']; print(f'count={len(ap)}; names={[a[\"name\"] for a in ap]}')"

# 7. No companion tactics in encounter templates
grep -rn 'companion' content/encounter_templates.json

# 8. CompanionState int relationship_tier (in-memory only, no persistence)
grep -n 'relationship_tier' apps/agent/session_data.py apps/agent/db_*.py scripts/migrations/*.sql
```

Expected outputs as of this audit:
- #1, #2, #3, #7: 0 matches.
- #4: `ls: content/companions.json: No such file or directory`.
- #5: `[('companion_kael', 2)]` — only Kael, 2-entry action_pool.
- #6: `count=2; names=['Longsword', 'Defensive Stance']`.
- #8: 1 hit in `session_data.py:22` (the dataclass field); 0 hits in db_*.py or migrations (no persistence).

A non-empty result on #1-#3 or #7, or count >2 on #5/#6, means downstream M6.4 implementation has landed code that this audit's NOT_SHIPPED verdicts should be re-evaluated against.
