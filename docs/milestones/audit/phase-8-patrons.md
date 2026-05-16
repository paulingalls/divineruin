# Phase 8 Audit — Divine Patron System (M8.1 + M8.2 + M8.3)

Sprint-002 / Milestone 2. Read-only audit of `docs/game_mechanics/game_mechanics_patrons.md` against `docs/milestones/08_patrons.md` and the shipped code under `apps/agent/`, `apps/server/`, `packages/shared/`, `content/`, and `scripts/migrations/`. Status legend: **confirmed** (symbol exists with behavior matching spec), **aspirational** (symbol/feature absent or named differently with no functional equivalent), **unverified** (partial — code present but coverage diverges from spec). Bias is toward unchecking when evidence is weak.

## Summary

| Section | Confirmed | Aspirational | Unverified |
| --- | --- | --- | --- |
| M8.1 — Patron Profiles & Divine Favor (11 criteria) | 0 | 10 | 1 |
| M8.2 — Patron Abilities by Tier (11 criteria) | 0 | 11 | 0 |
| M8.3 — Archetype Synergies & Unbound Path (12 criteria) | 0 | 12 | 0 |

The patron system is **almost entirely aspirational**. What exists today is a thin "divine_favor numeric score 0–100 with a patron_id" attached to each player, plus a god-whisper voice/personality layer for the 10 deities. The four-layer architecture from the spec (Divine Gift / Resonance Modifier / Favor Abilities / Archetype Resonance) is not encoded anywhere outside markdown. No patron-side rules-engine functions exist (`evaluate_patron_alignment`, `get_patron_tier`, `get_archetype_synergy`, `apply_unbound_resonance_push`). No patron-related migrations exist. `content/gods.json` contains 4 of 10 patrons and zero mechanical layer data.

Key naming/scope caveats (not part of acceptance criteria but worth surfacing to the capstone):
- Spec deliverable `evaluate_patron_alignment(player_actions, patron_values) -> favor_delta` does not exist. The shipped pattern instead is `award_divine_favor(amount, reason)` — an agent tool the LLM calls with a judgement amount (1–10). Alignment evaluation lives in the LLM prompt, not in a deterministic rules-engine function.
- Spec deliverable `get_patron_tier(favor_value) -> tier` does not exist. Favor is stored as a single integer `level` (0–100) with no Acknowledged/Devoted/Exalted thresholds defined in code.
- Spec deliverable DB tables `player_patron`, `patron_favor_state`, `patron_ability_unlock`, `archetype_synergy` do not exist. Favor data lives in `players.data->'divine_favor'` JSONB with shape `{patron, level, max, last_whisper_level}` (`apps/agent/creation_rules.py:261`).
- The "background process heartbeat" hook in `apps/agent/async_worker.py:400` `check_god_whisper_triggers` evaluates the FAVOR_WHISPER threshold to generate god whispers — this is whisper-cooldown logic, not patron alignment evaluation. There is no 15–30 minute coroutine that adjusts `favor` based on observed behavior.
- Layer 4 archetype synergy exists in code **only** as `DeityData.synergy_classes: tuple[str, ...]` in `apps/agent/creation_deities.py:23` — a flat list of 2–4 archetype IDs per deity. There is no synergy_type (Natural/Divine/Unexpected) tagging and no per-pairing mechanical bonus.
- Spec's 10 god identities are defined in three different code surfaces with different shapes (creation_deities.DEITIES, god_whisper_data.GOD_WHISPER_PROFILES, content/gods.json). Only the first two are complete (10 entries); `content/gods.json` has 4.

## Coverage matrix

| Spec section (line range in `game_mechanics_patrons.md`) | Maps to | Notes |
| --- | --- | --- |
| Architecture: 4-layer mechanical system (L9-22) | M8.1 (Layer 1 deliverable line 16, Layer 2 line 17, Layer 3 line 18, Layer 4 to M8.3) | Layer 4 stubs deferred to M8.3 per milestone text |
| Divine Favor Tiers — Acknowledged/Devoted/Exalted thresholds + decay (L23-34) | M8.1 (tier transitions, favor decay) | Spec describes 3 named tiers; code has a 0–100 numeric scale only |
| Veythar profile — all 4 layers (L37-65) | M8.1 + M8.3 | Includes Layer 4 synergy table |
| Kaelen profile — all 4 layers (L67-93) | M8.1 + M8.3 | |
| Aelora profile — all 4 layers (L95-121) | M8.1 + M8.3 | |
| Thyra profile — all 4 layers (L123-149) | M8.1 + M8.3 | |
| Syrath profile — all 4 layers (L151-177) | M8.1 + M8.3 | |
| Orenthel profile — all 4 layers (L179-205) | M8.1 + M8.3 | |
| Valdris profile — all 4 layers (L207-233) | M8.1 + M8.3 | |
| Mortaen profile — all 4 layers (L235-261) | M8.1 + M8.3 | |
| Nythera profile — all 4 layers (L263-289) | M8.1 + M8.3 | |
| Zhael profile — all 4 layers (L291-317) | M8.1 + M8.3 | |
| Unbound Path — design intent + 4-layer equivalent (L319-348) | M8.1 (Unbound selectable) + M8.3 (full implementation) | Veil Clarity, voluntary +3 Resonance push, Self-Reliance milestones (Self-Reliant / Self-Forged / Sovereign), universal Layer 4 +1 alone |
| Layer 2 Resonance modifiers per patron (every profile L2 section) | M8.1 (cross-doc: Phase 3 Magic Resonance) | NEW — none of the 11 Resonance modifiers exist in code because the Resonance system itself is not implemented yet (Phase 3) |
| Post-reveal Veythar divine filter degradation (L47) | NEW | Not in milestone — endgame state machine for divine filter change |
| Patron System Summary table (L352-366) | M8.1 (reference only) | Documentation table, not a deliverable |

## M8.1 — Patron Profiles & Divine Favor

| Acceptance criterion (verbatim) | Evidence | Status |
| --- | --- | --- |
| All 10 patron profiles have Layer 1 (passive), Layer 2 (Resonance modifier), and Layer 3 (ability tiers) defined | `apps/agent/creation_deities.py:23` `DEITIES` has all 10 patrons + `none`, but stores only `name/title/domain/description/card_description/synergy_classes`. Layer 1 passive gifts (Lorekeeper's Insight, Iron Resolve, etc.) absent. Layer 2 Resonance modifiers absent. Layer 3 tier abilities absent. `content/gods.json` has 4 of 10 (`veythar/kaelen/aelora/syrath`) with `favor_actions/values/whisper_themes` but no mechanical layers. `apps/agent/god_whisper_data.py:25` `GOD_WHISPER_PROFILES` has all 10 deity voice/personality records but no mechanics. | aspirational |
| Each patron's Layer 1 passive is mechanically distinct and always active | No Layer 1 passives encoded anywhere. No "always active" hook exists. | aspirational |
| Layer 2 Resonance modifiers integrate with Phase 3 Magic Resonance calculations | Phase 3 Resonance system is not implemented; only string references to "Resonance" exist in `apps/agent/rules_engine.py:175,176,195` (skill flavor text). No `calculate_resonance` / `apply_resonance_modifier` functions exist. Layer 2 modifiers have nothing to plug into. | aspirational |
| `evaluate_patron_alignment` produces positive delta for aligned actions and negative for misaligned | No `evaluate_patron_alignment` exists. Closest analogue: `apps/agent/progression_tools.py:117` `award_divine_favor(amount, reason)` — LLM-driven with positive amount only (1–10), no rules-engine alignment function. `content/gods.json` does encode `favor_actions.positive` and `favor_actions.negative` arrays but no code consumes them for delta computation. | aspirational |
| Favor tiers transition correctly: Acknowledged at threshold A, Devoted at B, Exalted at C | No tier model in code. `divine_favor` is a flat integer `level` (0–100). Only threshold defined is `FAVOR_WHISPER_THRESHOLD = 25` (`apps/agent/god_whisper_data.py:22`) which gates god whispers, not Acknowledged tier. No `get_patron_tier` function. | aspirational |
| Favor can decay (not just grow) — neglecting patron values reduces favor over time | `apps/agent/progression_tools.py:117` `award_divine_favor` validates `amount < 1 or amount > 10` (line 144) — negative deltas are rejected. No decay coroutine exists in `apps/agent/background_process.py` or `apps/agent/async_worker.py`. Favor only grows. | aspirational |
| Unbound Path is selectable and grants Resonance visibility, +3 voluntary Resonance push, and Veil Mastery | `apps/agent/creation_deities.py:154` `none` DeityData is selectable as a deity choice during character creation. However: (a) no "Veil Clarity" / exact-Resonance-readout exists, (b) no `apply_unbound_resonance_push` function exists, (c) no "Veil Mastery" tier ability exists. Only the *option* to pick "no patron" is honored. | unverified — selectable yes, but the three mechanical benefits are entirely absent |
| `content/gods.json` validates with all 10 complete patron profiles | 4 of 10 patrons present (veythar, kaelen, aelora, syrath). Missing: thyra, syrath✓ (present), orenthel, valdris, mortaen, nythera, zhael. Existing 4 entries have personality + favor_actions + whisper_themes + world_state but **zero** mechanical layer fields (no `layer_1`, `layer_2`, `layer_3`, `layer_4` keys). | aspirational |
| Background process calls `evaluate_patron_alignment` on 15-30 minute heartbeat | No such heartbeat exists. `apps/agent/async_worker.py:400` `check_god_whisper_triggers` polls players above `FAVOR_WHISPER_THRESHOLD` to generate whispers — a different concern. The 15–30 minute simulation heartbeat referenced in the spec is not present. | aspirational |
| DB schema supports patron selection, favor tracking, and tier state | No `player_patron` or `patron_favor_state` migrations exist (`scripts/migrations/` runs through 017 with no patron-specific schema). Favor lives entirely in `players.data->'divine_favor'` JSONB initialised by `apps/agent/creation_rules.py:261` to `{patron, level, max, last_whisper_level}`. No `tier` field, no `last_eval_timestamp`. | aspirational |
| Tests cover favor accumulation, decay, tier transitions (up and down), and Unbound Path mechanics | `apps/agent/tests/test_mutation_tools.py:845-1020` covers `_award_divine_favor_impl` accumulation, capping at max, and validation errors. **No tests for**: decay (no decay code), tier transitions (no tiers), Unbound Path mechanics (no Unbound code). | aspirational |

### Per-patron Layer coverage in `content/gods.json`

| Patron | Present in gods.json | Layer 1 (Gift) | Layer 2 (Resonance) | Layer 3 (Tier abilities) | Layer 4 (Synergy) | Personality / values | favor_actions |
| --- | --- | --- | --- | --- | --- | --- | --- |
| veythar | ✓ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| kaelen | ✓ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| aelora | ✓ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| syrath | ✓ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| thyra | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| orenthel | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| valdris | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| mortaen | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| nythera | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| zhael | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Unbound (none) | ✗ (n/a — not in gods file by design) | ✗ | ✗ | ✗ | ✗ | n/a | n/a |

Note: `apps/agent/creation_deities.py:DEITIES` does cover all 10 + `none` for character-creation purposes, but it stores only `synergy_classes` as a coarse Layer-4 hint (e.g., kaelen → `(warrior, guardian, skirmisher, paladin)`) with no synergy_type discrimination and no mechanical bonus. Treat it as a non-mechanical roster, not a layer-coverage record.

## M8.2 — Patron Abilities by Tier

| Acceptance criterion (verbatim) | Evidence | Status |
| --- | --- | --- |
| All 10 patrons have abilities defined for all 3 tiers (Acknowledged, Devoted, Exalted) | Spec defines 30 tier abilities (3 per patron × 10 patrons) plus Unbound's 3 Self-Reliance milestones. Codebase contains **0** of these — no constants, JSON, dataclass, or table holds ability definitions. Strings "Acknowledged", "Devoted", "Exalted" appear nowhere outside spec/milestone markdown. | aspirational |
| Each ability has name, effect, and recharge condition specified | No ability records exist. | aspirational |
| Recharge tracking prevents ability use before recharge completes (short rest / long rest / daily) | No ability records; no recharge tracker. Short/long rest hooks (`apps/agent/rest_mechanics.py:8,20`) don't touch any patron ability state. | aspirational |
| Ability unlock triggers automatically when favor tier advances | No tiers, no abilities, no unlock event. `apps/agent/event_types.py:33` `DIVINE_FAVOR_CHANGED = "divine_favor_changed"` exists and is published by `award_divine_favor` (`progression_tools.py:163`), but only god-whisper triggers consume it (`apps/agent/bg_event_handlers.py:202`). | aspirational |
| Higher-tier abilities become unavailable (not deleted) when favor drops below tier threshold | No tiers, no abilities. Favor cannot drop in current code anyway. | aspirational |
| `activate_patron_ability` validates availability, applies effect, and sets recharge timer | No such agent tool exists. No `@function_tool` named `activate_patron_ability` in `apps/agent/`. | aspirational |
| `activate_patron_ability` returns error if ability is on cooldown or tier is insufficient | Tool absent. | aspirational |
| `check_patron_tier` returns current tier, favor value, and list of available abilities | No such agent tool exists. The closest read path is `db_activity_queries.get_divine_favor(player_id)` → returns `{patron, level, max, last_whisper_level}` — no tier, no abilities list. | aspirational |
| Client receives patron ability data for character sheet and favor bar for HUD | No patron-ability payload sent over LiveKit data channel or via REST. `apps/mobile/src/stores/hud-store.ts` and overlay manager handle `DIVINE_FAVOR_CHANGED` for an overlay animation but no ability list is displayed. | aspirational |
| Unbound Path players have no patron abilities (Unbound benefits come from M8.1 passives) | Vacuously true — no patron abilities exist for anyone. The acceptance text presumes other patrons would have abilities and Unbound would not; that distinction isn't enforceable yet. | aspirational |
| Tests cover ability activation, recharge, tier-up unlock, tier-down lockout, and Unbound exclusion | No tests exist for any of these because no implementation exists. | aspirational |

Deliverable rows worth tracking separately:

| Spec deliverable | Actual | Status |
| --- | --- | --- |
| `activate_patron_ability(player_id, ability_id)` agent tool | absent | aspirational |
| `check_patron_tier(player_id)` agent tool | absent (closest: `get_divine_favor(player_id)` which returns level not tier) | aspirational |
| `patron_ability_unlock` DB migration | absent (no migration touches this table; migrations run through 017) | aspirational |
| Per-patron ability roster (30+ entries) | absent | aspirational |

## M8.3 — Archetype Synergies & Unbound Path

| Acceptance criterion (verbatim) | Evidence | Status |
| --- | --- | --- |
| Synergy lookup covers all archetype × patron combinations | No archetype × patron matrix exists. `creation_deities.DeityData.synergy_classes` is a flat tuple per deity (e.g., kaelen has `(warrior, guardian, skirmisher, paladin)`) — no synergy entries for archetypes outside that tuple, and no Natural/Divine/Unexpected categorisation. | aspirational |
| Each pairing has exactly one synergy type assigned (Natural, Divine, or Unexpected) | No `synergy_type` field anywhere in code. The string "Natural" appears only in markdown. | aspirational |
| Natural synergies provide the largest mechanical bonus, Unexpected the most unique | No mechanical bonuses encoded. | aspirational |
| `get_archetype_synergy` returns correct synergy for any archetype/patron pair | Function does not exist in `apps/agent/rules_engine.py` or elsewhere. | aspirational |
| Layer 4 bonuses apply on top of existing Layer 1-3 mechanics without overriding them | No Layer 1-3 mechanics exist (see M8.1), so Layer 4 stacking is moot. | aspirational |
| Unbound Path grants perfect Resonance visibility (exact value, not just tier) | No Resonance system implemented (Phase 3 dependency). No Veil-Clarity readout/UI exists. | aspirational |
| Unbound +3 Resonance push is voluntary and costs no action | `apply_unbound_resonance_push` function does not exist. | aspirational |
| Veil Mastery provides measurable mechanical benefit (bonus to corruption saves, reduced Hollow effects) | No corruption-save bonus or Hollow-effect reduction tied to Unbound exists. Hollow Echo table itself not implemented. | aspirational |
| Unbound Path has NO patron abilities — only Resonance mastery benefits | Vacuously honored — no patron has abilities, so Unbound matches. | aspirational |
| `query_patron_synergy` returns empty/null for Unbound players (no synergy applicable) | Agent tool does not exist. | aspirational |
| All 10 patrons + Unbound Path are fully implemented and playable after this milestone | Not yet — current state allows the player to *select* a patron (or none) and accumulate a numeric favor score, plus receive themed god-whispers when crossing a fixed favor threshold. No mechanical patron benefits are realized in play. | aspirational |
| Tests cover synergy lookup for all combinations, Unbound mechanics, and Layer 4 bonus stacking | No tests; no implementation. | aspirational |

Deliverable rows worth tracking separately:

| Spec deliverable | Actual | Status |
| --- | --- | --- |
| `archetype_synergy` DB table migration | absent | aspirational |
| `get_archetype_synergy(archetype, patron)` rules-engine fn | absent | aspirational |
| `apply_unbound_resonance_push(player)` rules-engine fn | absent | aspirational |
| `query_patron_synergy(player_id)` agent tool | absent | aspirational |
| Unbound Self-Reliance milestones (Self-Reliant / Self-Forged / Sovereign) | absent (strings appear nowhere outside spec markdown) | aspirational |

## Material gaps

1. **The four-layer architecture is not encoded.** All 11 patrons (10 + Unbound) need Layer 1 passive gift effects, Layer 2 Resonance modifiers, Layer 3 tier ability rosters, and Layer 4 archetype-synergy matrices represented in some combination of `content/gods.json` and a rules-engine module. None of this exists.
2. **Favor model is single-integer, not tiered.** `divine_favor.level` is 0–100. The spec calls for three named tiers (Acknowledged / Devoted / Exalted) with both up and down transitions. Need (a) tier threshold constants, (b) a `get_patron_tier(level)` mapping, (c) a `DIVINE_FAVOR_CHANGED` consumer that fires `PATRON_TIER_CHANGED` events on threshold crossings, (d) decay logic.
3. **Alignment evaluation is LLM-driven, not rules-engine-driven.** The spec promises `evaluate_patron_alignment(player_actions, patron_values) -> favor_delta` as a deterministic function. Today the LLM calls `award_divine_favor(amount, reason)` with a freeform judgement amount. `content/gods.json` already encodes `favor_actions.positive[]` and `favor_actions.negative[]` per patron — these are unused.
4. **No 15–30 minute simulation heartbeat for favor.** `apps/agent/async_worker.py` runs scheduled jobs but no patron-alignment evaluator on a 15–30 minute cadence. The whisper-trigger poller is the closest hook and runs only when a player crosses an absolute favor threshold.
5. **No patron-ability runtime.** Need `activate_patron_ability` / `check_patron_tier` agent tools, recharge tracking against short/long-rest events, and a `patron_ability_unlock` JSONB or table to record acquisition.
6. **No archetype × patron synergy table.** `creation_deities.synergy_classes` is too coarse and lacks synergy_type. Need a (10 patrons + 1) × 18 archetypes matrix with Natural/Divine/Unexpected tagging and per-cell mechanical effect.
7. **Unbound Path mechanics are 1 step done (selectable), 4 steps missing**: Veil Clarity readout, voluntary +3 Resonance push, Veil Mastery + Self-Reliance milestones, universal Layer 4 +1 bonus when alone. Even the constant "Self-Reliant"/"Self-Forged"/"Sovereign" strings do not appear in code.
8. **`content/gods.json` is 60% incomplete.** Only veythar, kaelen, aelora, syrath are present. The other 6 patrons (thyra, orenthel, valdris, mortaen, nythera, zhael) need rows. The roster of 10 *does* exist in `apps/agent/creation_deities.py:DEITIES` and `apps/agent/god_whisper_data.py:GOD_WHISPER_PROFILES`, so identity/personality data is recoverable — but mechanical layers will need authoring from scratch from the spec.
9. **Spec hint not in milestone**: Veythar's "Post-reveal: divine filter degrades from 0.3× to 0.7× Resonance rate" (L47) describes an endgame state transition on a Layer 2 modifier. The current milestone deliverables don't cover post-reveal patron-state mutation; capstone may want to flag as NEW or defer to a later phase.

## Cross-doc dependencies

- **Patrons ↔ Magic Resonance (Phase 3) — Layer 2 modifiers.** Every patron's Layer 2 modifier (Veythar +2 Flickering dice, Kaelen -1 Resonance on combat spells, Orenthel 0 Resonance on healing, Mortaen 0 Resonance on 0-HP targets, Syrath -2 Resonance from stealth, Aelora no Veil Ward penalty, Thyra -1 Resonance in nature, Valdris half Resonance on justified spells, Nythera -1 Resonance in unexplored locations, Zhael 2d20-and-choose on Hollow Echo table) requires a working Resonance system to plug into. `apps/agent/rules_engine.py` has no Resonance functions (only string mentions in skill flavor text). M8.1's "Layer 2 Resonance modifiers integrate with Phase 3 Magic Resonance calculations" cannot be satisfied until Phase 3 lands. **Capstone action**: capstone should add an explicit "blocked on Phase 3 — Magic Resonance" note next to M8.1's Layer 2 acceptance criterion.
- **Patrons ↔ Archetypes (Phase 2) — Layer 4 synergies.** M8.3's archetype × patron matrix references the 18 archetypes whose canonical list lives in `apps/agent/rules_engine.py:30` `ARCHETYPE_RESOURCE_CONFIG` (audited in `phase-1-characters.md`). Phase 2 milestone work (archetype JSON / per-archetype tool surfaces) is the upstream feed for the synergy matrix. **Forward dependency**: M8.3 acceptance ("Synergy lookup covers all archetype × patron combinations") is blocked on Phase 2 completing the archetype identity/spec encoding such that synergy entries have stable archetype IDs to key against. The 18 IDs already exist in code; only the per-archetype detail surface (techniques, spells, ability lookup) is still partial per sprint-001's audit. **Capstone action**: in `08_patrons.md` M8.3 deliverables, add an explicit "depends on Phase 2 archetype encoding" note alongside the synergy-table deliverable.
- **Patrons ↔ Unbound Veil Mastery — Hollow Echo table.** The Unbound's Sovereign-tier "Veil Mastery" ("treat any Hollow Echo result as 'Nothing stirs'") requires a Hollow Echo table to exist. Hollow Echo is implied by Phase 3 (Magic Resonance / Overreach). Same cross-doc dep as Layer 2.
- **Patrons ↔ god-whisper system (Phase 5+).** Existing god-whisper generator (`apps/agent/god_whisper_generator.py`, `apps/agent/async_worker.py:400`) is functionally complete and operates on the *current* divine_favor.level integer. Any tier-restructuring (M8.1 acceptance criterion 5) must keep the whisper trigger working — currently keyed off the raw `level` rather than `tier`. This is a within-phase consistency concern rather than a blocker.
