# Phase 3 Audit — Magic System (M3.1 + M3.2 + M3.3 + M3.4)

Sprint-002 / Milestone 2. Read-only audit of `docs/milestones/03_magic.md` against `docs/game_mechanics/game_mechanics_magic.md` (542 lines) and shipped code in `apps/agent/`, `apps/server/`, `packages/shared/src/entities/`, `content/`, and `scripts/migrations/`. Status legend: **confirmed** (symbol + tests exist and match spec), **aspirational** (spec symbol/feature is missing or renamed without a wrapper), **unverified** (partial — code present but coverage or scope diverges from spec), **NOT_SHIPPED** (no implementation found at all).

## Summary

| Section | Confirmed | Aspirational | NOT_SHIPPED |
| --- | --- | --- | --- |
| M3.1 — Resonance System | 0 | 0 | 8 |
| M3.2 — Hollow Echo & Veil Wards | 0 | 0 | 9 |
| M3.3 — Spell Catalog | 0 | 0 | 8 |
| M3.4 — Concentration & Racial Resonance | 0 | 0 | 9 |

**Headline finding:** The entire Magic system (M3.1–M3.4) is unshipped. No Resonance state, no spell catalog, no concentration, no racial Resonance bonuses, no Hollow Echo table, no Veil Ward mechanics exist in code. The only Resonance-adjacent code references are flavor strings inside skill-ability descriptions (`apps/agent/rules_engine.py:175-200` — Arcana / Theology / Naturalist Master/Expert ability text) and one async training activity slug `spell_cantrip` (`apps/agent/training_rules.py:22`). The capstone (story-004) should uncheck every acceptance box across all four milestones.

Naming caveats (deliverables only — none of these symbols exist yet, so these are forward notes for implementers):
- Spec deliverable `calculate_resonance_generated(focus_cost, source, terrain=None)` — not present in `apps/agent/rules_engine.py`. The "Resonance Generation" code block in `game_mechanics_magic.md:110-124` shows a `resonance_generated()` function as the canonical reference signature.
- Spec deliverable `get_resonance_state(current_resonance)` — not present. Thresholds are Stable (0-4), Flickering (5-8), Overreach (9+) per `game_mechanics_magic.md:103-106`.
- Spec deliverable `apply_resonance_decay(current_resonance, racial_modifier=0)` — not present. Standard -1/round, Human -2/round per `game_mechanics_magic.md:128-131`.
- Spec deliverable `resolve_hollow_echo(d20_roll, resonance_level)` — not present. Table in `game_mechanics_magic.md:171-179` defines 7 result bands; modifiers at Resonance 12+ (-3) and 15+ (-6) per `magic.md:169`.
- Spec deliverable `activate_veil_ward(character_id)` agent tool — not present. Ward properties in `magic.md:194-200` (halved Resonance, +4 Echo, -1 die, -1 DC).
- Spec deliverable `cast_spell` agent tool — not present. Should validate Focus, call `calculate_resonance_generated`, return narration + audio cue.
- Spec deliverable `get_spell_info` agent tool — not present.
- Spec deliverable `check_concentration(character_id, damage_taken)` — not present. DC = max(10, damage / 2) per milestone acceptance text.
- Spec deliverable `get_racial_resonance_modifier(race, modifier_type)` — not present. Six racial entries to seed.

## Coverage matrix

Every numbered subsection of `docs/game_mechanics/game_mechanics_magic.md` is mapped below. Items marked NEW are spec content with no corresponding milestone item.

| Spec section (file:line) | Milestone item | Notes |
| --- | --- | --- |
| Cosmological Foundation (magic.md:11-19) | NEW (worldbuilding-only, no mechanical claim) | Pure lore. No mechanical deliverable. |
| Arcane Magic — multiplier 0.6 (magic.md:23-39) | M3.1 — `calculate_resonance_generated()` arcane branch | Acceptance bullet 1 covers this. |
| Divine Magic — multiplier 0.3 (magic.md:41-59) | M3.1 — `calculate_resonance_generated()` divine branch | Acceptance bullet 1. Post-reveal Veythar 0.7× is NEW — not in milestone (only `divine` is named). |
| Primal Magic — terrain table 0.1-0.8 (magic.md:61-86) | M3.1 — `calculate_resonance_generated()` primal branch + terrain table | Acceptance bullet 1 + 8 (terrain-dependent test). The 8-row terrain multiplier table (magic.md:73-80) is referenced but not enumerated in the milestone. |
| Bard Exception — multiplier 0.4 (magic.md:88-90) | NEW | Milestone names only Arcane/Divine/Primal. Bard 0.4× is implied by spec source string `"bard"` in the code reference at magic.md:119. |
| Resonance States (magic.md:100-106) | M3.1 — `get_resonance_state()`, state modifiers | Acceptance bullets 2, 5, 6. |
| Resonance Generation pseudocode (magic.md:108-124) | M3.1 — `calculate_resonance_generated()` formula | Canonical reference signature. Includes `divine_veythar_post_reveal: 0.7` key — NEW vs milestone. |
| Resonance Decay (magic.md:126-131) | M3.1 — `apply_resonance_decay()` + rest reset | Acceptance bullet 3. "Full reset on short or long rest" is NEW — milestone only mentions per-round decay. |
| Resonance Cap (magic.md:132-134) | M3.1 — escalating modifiers at 12+ and 15+ | Deliverable bullet "Escalating modifiers at high Resonance: additional effects at 12+ and 15+". Acceptance criteria do **not** list this — partial coverage in the milestone. **Veil Fracture** narrative event at 15+ is NEW. |
| Spell-to-Resonance Map (magic.md:136-156) | M3.3 — `spell_catalog`/`content/spells.json` | Reference table for individual spell Resonance values. |
| Typical Encounter Resonance Progression (magic.md:158-163) | NEW (worked example, no deliverable) | Documentation example, not a code requirement. |
| Hollow Echo Table (magic.md:167-185) | M3.2 — `resolve_hollow_echo()` | Acceptance bullets 1, 2. |
| Hollow Echo trigger at Overreach (magic.md:169) | M3.2 — automatic d20 roll trigger | Acceptance bullet 3. |
| Echo modifiers at 12+ (-3) and 15+ (-6) (magic.md:169) | M3.2 — severity scales with Resonance | Acceptance bullet 2; acceptance does not pin -3 / -6 numbers. |
| Echo Table 7 result bands (magic.md:173-179) | M3.2 — `resolve_hollow_echo` return shape | Result names: Nothing, Whisper, Veil scar, Sympathetic resonance, Hollow attention, Reality fracture, Breach. |
| Echo Table design notes (magic.md:181-185) | NEW (design rationale) | Documentation only. |
| Veil Ward effects table (magic.md:194-200) | M3.2 — `activate_veil_ward` ward effect | Acceptance bullets 4, 5, 6. |
| Veil Ward sources (magic.md:204-210) | NEW — 5-source table not encoded in milestone | Cleric / Druid / Artificer / Paladin / Sacred sites. Milestone treats Veil Ward as a single mechanic; spec attaches it to specific archetypes at specific levels. Cross-doc dep with `game_mechanics_archetypes.md`. |
| Strategic Implications (magic.md:213-217) | NEW (DM guidance) | Documentation only. |
| Racial Resonance — Elari Veil-sense (magic.md:225-236) | M3.4 — Elari racial modifier | Acceptance bullet on `racial_resonance_bonuses` seed. Tiered Arcana scaling (magic.md:229-232) is NEW vs milestone. |
| Racial Resonance — Human Adaptive (magic.md:238-244) | M3.4 — Human -2 decay | Acceptance bullet 4. |
| Racial Resonance — Vaelti Hyper-awareness (magic.md:246-252) | M3.4 — Vaelti early warning + Echo save advantage | Acceptance bullet 7. "Advantage on saves against Hollow Echo effects" (magic.md:248) is NEW — milestone only lists "1-round advance warning". |
| Racial Resonance — Korath Earth-anchored (magic.md:254-260) | M3.4 — Korath -1 Primal | Acceptance bullet 5. Spec gates on "in contact with earth or stone" — milestone deliverable text mentions the condition but acceptance bullet ignores it. |
| Racial Resonance — Draethar Inner Fire (magic.md:262-268) | M3.4 — Draethar pressure valve | Acceptance bullet 6. Spec: -3 Resonance for 1d6 fire damage, 1/encounter. Milestone deliverable text says "HP or Focus" cost — diverges from spec ("self-inflicted fire damage, cannot be reduced"). |
| Racial Resonance — Thessyn Deep Adaptation (magic.md:270-276) | M3.4 — Thessyn long-term adaptation | Deliverable mentions "+1 to the Flickering threshold". No acceptance bullet specifically calls this out — only the `racial_resonance_bonuses` seed bullet covers it implicitly. **10+ session counter** has no schema in the milestone. |
| Resonance Sensing tiers (Non-Elari) (magic.md:280-293) | NEW | Arcana skill tier table (Untrained/Trained/Expert/Master). Not mentioned in M3.x. Cross-doc dep on skills system. |
| Arcane Spell Catalog (magic.md:297-372) — 30 spells | M3.3 — `content/spells.json` Arcane partition | Acceptance bullet 1 ("30 Arcane"). |
| Cantrip scaling formula (magic.md:312-316) | M3.3 — cantrip scaling 1d6/2d6/3d6/4d6 brackets | Acceptance bullet 6. |
| Casting model — explicit names, no fuzzy match (magic.md:299) | NEW (design constraint) | Affects `cast_spell` implementation: exact-name lookup, not intent resolution. |
| Catalog Structure — per-spell field list (magic.md:303-306) | M3.3 — required fields | Acceptance bullet 2. Spec lists Focus cost, Resonance generation, Narration cue, Audio cue (4). Milestone adds: name, source, focus_cost, resonance_by_source, terrain_effects, spell_tier, level_requirement, mechanics, narration_cue, audio_cue, concentration. Milestone is a superset — fine. |
| Divine Spell Catalog (magic.md:378-448) — 28 spells | M3.3 — Divine partition | Acceptance bullet 1 ("28 Divine"). |
| Divine spells with 0 Resonance (magic.md:380, 448) | NEW (data property, not a separate rule) | Detect Hollow, Dispel Corruption, certain healing — encoded as data, not as a special rule. |
| Primal Spell Catalog (magic.md:452-525) — 29 spells | M3.3 — Primal partition | Acceptance bullet 1 ("29 Primal"). |
| Druid preparation constraint (magic.md:458) | NEW | "Druids can only change spell preparation in natural terrain." Not in M3.x — cross-doc dep with `game_mechanics_archetypes.md`. |
| Three-Source Catalog Comparison (magic.md:529-541) | NEW (summary table) | Documentation only. |

## M3.1 — Resonance System

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| `calculate_resonance_generated()` returns correct values for each source: Arcane at 0.6x, Divine at 0.3x, Primal at terrain-dependent 0.1-0.8x | No symbol named `calculate_resonance_generated` exists in `apps/agent/`. `rg "calculate_resonance"` against the worktree → 0 matches. The `resonance_generated` pseudocode at `magic.md:110-124` is canonical; no Python equivalent ships. | None | NOT_SHIPPED |
| `get_resonance_state()` returns Stable for 0-4, Flickering for 5-8, Overreach for 9+ | No symbol named `get_resonance_state`. `rg "get_resonance_state"` → 0 matches. | None | NOT_SHIPPED |
| `apply_resonance_decay()` reduces Resonance by 1 per round by default, 2 for Human racial modifier | No symbol named `apply_resonance_decay`. `rg "apply_resonance_decay"` → 0 matches. | None | NOT_SHIPPED |
| Resonance never goes below 0 | Not implementable without the decay function. | None | NOT_SHIPPED |
| Flickering state applies +1 damage die modifier to spell effects | No spell-damage code path exists (no spell catalog, no `cast_spell`). | None | NOT_SHIPPED |
| Overreach state applies +2 damage dice and +2 DC modifier to spell effects | Same as above. | None | NOT_SHIPPED |
| Client displays Resonance tracker with visually distinct states | `rg -i "resonance" apps/mobile/` → only `dungeon_resonance_deep` in `apps/mobile/src/audio/soundscape-registry.ts:27,135` (audio asset name, unrelated). No HUD component for caster Resonance. | None | NOT_SHIPPED |
| Unit tests cover all source multipliers, all state thresholds, decay edge cases, and terrain-dependent Primal calculation | No `test_resonance*.py` or `test_magic*.py` file under `apps/agent/tests/`. | None | NOT_SHIPPED |

**Deliverables status:**
- Pure functions in rules engine (`calculate_resonance_generated`, `get_resonance_state`, `apply_resonance_decay`): NOT_SHIPPED.
- Resonance state modifiers (+1 die Flickering, +2 dice +2 DC Overreach): NOT_SHIPPED.
- Escalating modifiers at 12+ and 15+: NOT_SHIPPED. **Note:** spec at `magic.md:169, 134` defines these as -3 and -6 to the d20 Echo roll plus a 15+ Veil Fracture event; milestone deliverable text is vaguer ("additional effects at 12+ and 15+").
- DB `character_resonance` table or column: NOT_SHIPPED. No migration touches caster Resonance. Migrations 001-017 are inventoried; none seed or schema-create Resonance state.
- Client Resonance tracker: NOT_SHIPPED.

## M3.2 — Hollow Echo & Veil Wards

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| `resolve_hollow_echo()` returns correct severity for all d20 roll ranges | No symbol named `resolve_hollow_echo`. `rg "resolve_hollow_echo"` → 0 matches. | None | NOT_SHIPPED |
| Echo severity scales with Resonance level (higher Resonance = worse outcomes at same roll) | Modifiers -3 at 12+ and -6 at 15+ per `magic.md:169` — no implementation. | None | NOT_SHIPPED |
| Hollow Echo is triggered automatically when casting at Overreach | No `cast_spell` tool exists to integrate this trigger. | None | NOT_SHIPPED |
| Veil Ward halves Resonance generation from all sources while active | No symbol named `activate_veil_ward`. `rg "veil_ward"` → 0 matches. | None | NOT_SHIPPED |
| Veil Ward applies -1 damage die and -1 DC penalty while active | NOT_SHIPPED |  | NOT_SHIPPED |
| Veil Ward grants +4 bonus to Hollow Echo rolls while active | NOT_SHIPPED |  | NOT_SHIPPED |
| Veil Ward can be activated and deactivated by the player | No agent tool. No DB ward-state field. | None | NOT_SHIPPED |
| Client displays Hollow Echo roll results and Veil Ward zone indicator | No mobile component. | None | NOT_SHIPPED |
| Unit tests cover full Echo table, ward modifiers, and interaction between ward bonus and Echo roll | None present. | None | NOT_SHIPPED |

**Deliverables status:**
- Hollow Echo pure function `resolve_hollow_echo(d20_roll, resonance_level)` with 7 result bands (Nothing 17-20, Whisper 14-16, Veil scar 11-13, Sympathetic resonance 8-10, Hollow attention 5-7, Reality fracture 2-4, Breach ≤1): NOT_SHIPPED.
- Agent tool wrappers (`resolve_hollow_echo`, `activate_veil_ward`): NOT_SHIPPED.
- Ward sources per archetype (Cleric L7 4F / Druid L9 5F / Artificer L7 item / Paladin L10 3F+3S / Sacred sites passive — `magic.md:204-210`): NOT_SHIPPED. **Cross-doc dep with `game_mechanics_archetypes.md` — milestone does not enumerate these per-archetype sources.**
- Client Hollow Echo roll display + Veil Ward zone indicator: NOT_SHIPPED.

## M3.3 — Spell Catalog

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| `content/spells.json` contains exactly 87 spells: 30 Arcane, 28 Divine, 29 Primal | `content/spells.json` **does not exist**. `ls content/` yields: encounter_templates, events, factions, gods, inventory_pools, items, level_progression, locations, lore_entries, npc_state, npcs, players, quests, scenes, training_activity_types, training_programs, voice_registry. No spell file. **Spec internal count is consistent** (Arcane: 5+6+6+6+7=30 ✓ at `magic.md:365-372`; Divine: 4+6+6+6+6=28 ✓ at `magic.md:439-446`; Primal: 5+6+6+6+6=29 ✓ at `magic.md:516-523`; total 87 ✓). | None | NOT_SHIPPED — spec internally consistent at 87 spells, but file is absent. |
| Every spell entry has all required fields: name, source, focus_cost, resonance_by_source, spell_tier, level_requirement, mechanics, narration_cue, audio_cue | No file. | None | NOT_SHIPPED |
| `spell_catalog` table is seeded with all 87 entries and queryable by source, tier, and level | No `spell_catalog` migration. Migrations 001-017 inventoried; none create a spells table. `rg "spell_catalog"` → 0 matches. | None | NOT_SHIPPED |
| `cast_spell` deducts Focus cost, calls `calculate_resonance_generated()`, and returns effect + narration cue + audio cue | No `cast_spell` agent tool. `rg "cast_spell"` → 0 matches in `apps/agent/`. The only "spell"-adjacent agent tool is `request_attack(..., weapon_or_spell: str)` at `apps/agent/combat_tools.py:275-335` — accepts a free-form weapon-or-spell string, **does not validate against any spell catalog, does not compute Resonance, does not consume Focus, does not return an audio cue**. The name is used as a string token in combat narration. | `apps/agent/tests/test_combat_tools.py` covers `request_attack` for weapons; no spell-cast path. | NOT_SHIPPED |
| `cast_spell` rejects casting when Focus is insufficient | No `cast_spell` tool. | None | NOT_SHIPPED |
| Cantrip damage scales correctly at each level bracket (L1-4, L5-10, L11-16, L17-20) | Cantrip scaling appears **only as narration text** in `apps/agent/leveling.py:145, 146, 199, 200, 249, 256` — strings like "Cantrip damage scales to 3d6". No numeric cantrip scaling function. | None | NOT_SHIPPED (narration-only flavor) |
| `get_spell_info` returns full spell data including narration and audio cues | No `get_spell_info` tool. `rg "get_spell_info"` → 0 matches. | None | NOT_SHIPPED |
| Unit tests cover casting validation, Resonance generation integration, cantrip scaling, and spell lookup | None present. The async training activity `spell_cantrip` in `apps/agent/training_rules.py:22` is a sleep-style cycle timer (3-9 hours), not a cast-time mechanic. | None | NOT_SHIPPED |

**Deliverables status:**
- `content/spells.json` (87 spells, three sources): NOT_SHIPPED.
- `spell_catalog` DB table + migration: NOT_SHIPPED.
- Cantrip scaling formula (1d6 L1-4 / 2d6 L5-10 / 3d6 L11-16 / 4d6 L17-20): NOT_SHIPPED.
- Agent tools `get_spell_info`, `cast_spell`: NOT_SHIPPED.

## M3.4 — Concentration & Racial Resonance

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Concentration save DC is max(10, damage / 2) — unit tests for boundary values | No `check_concentration` function. `rg "check_concentration"` → 0 matches. | None | NOT_SHIPPED |
| Casting a Concentration spell while one is active ends the previous spell | No spell-state tracking. No `concentration` field in any DB schema or migration. | None | NOT_SHIPPED |
| Incapacitated characters automatically lose concentration | NOT_SHIPPED | None | NOT_SHIPPED |
| Human racial modifier applies -2 decay per round (verified via `apply_resonance_decay`) | `apply_resonance_decay` does not exist. `apps/agent/creation_races.py:21-100+` `RACES` dict carries only `attribute_bonuses` per race — no `resonance_modifier`, no `racial_resonance` field. | None | NOT_SHIPPED |
| Korath racial modifier reduces Primal Resonance generation by 1 (verified via `calculate_resonance_generated`) | Same — no field on `RaceData`. | None | NOT_SHIPPED |
| Draethar can dump Resonance via pressure valve at a defined cost | No `pressure_valve` or `draethar_inner_fire` symbol. **Spec/milestone divergence:** spec at `magic.md:264` defines the cost as "1d6 fire damage (self-inflicted, cannot be reduced)" for "-3 Resonance, 1/encounter"; milestone deliverable text says "HP or Focus" cost. Capstone should reconcile. | None | NOT_SHIPPED |
| Vaelti receive advance warning before Hollow Echo (integrated with `resolve_hollow_echo` from M3.2) | `resolve_hollow_echo` does not exist. | None | NOT_SHIPPED |
| `racial_resonance_bonuses` table is seeded with all 6 racial entries | No migration creates this table. No content file. | None | NOT_SHIPPED |
| Unit tests cover concentration saves, auto-fail on incapacitation, single-concentration enforcement, and all 6 racial modifiers | None present. | None | NOT_SHIPPED |

**Deliverables status:**
- Concentration rules (`check_concentration`, single-spell enforcement, incapacitation auto-fail, catalog flag): NOT_SHIPPED.
- Six racial Resonance interactions (Elari Veil-sense, Human Adaptive, Vaelti Hyper-awareness, Korath Earth-anchored, Draethar Inner Fire, Thessyn Deep Adaptation): NOT_SHIPPED.
- `racial_resonance_bonuses` DB configuration table + `get_racial_resonance_modifier(race, modifier_type)` lookup: NOT_SHIPPED.
- Integration with M3.1 functions: blocked on M3.1 being NOT_SHIPPED.

## Race-mechanic schema gaps

`apps/agent/creation_races.py:8-15` defines `RaceData` with only four fields: `id`, `name`, `description`, `card_description`, `attribute_bonuses`. There is no field for racial Resonance behavior (`resonance_decay_modifier`, `primal_resonance_modifier`, `inner_fire_count`, `flickering_threshold_offset`, etc.). When M3.4 is implemented, the racial modifiers cannot piggyback on `RaceData` as-is — either the dataclass must be extended, or a separate `racial_resonance_bonuses` content file + DB seed (per the milestone) must own this layer. Capstone should note this as a forward dependency, not a regression.

Thessyn's "10+ sessions" trigger (`magic.md:272`) needs a session-count counter on the character record — no such counter exists. Vaelti's "1-round advance warning" needs a deferred-event queue that the agent tool system does not currently expose (no agent tool family for time-shifted notifications). Both are architectural gaps for the implementer, not regressions.

## Material gaps

1. **Entire M3.1–M3.4 milestone series is unshipped.** Capstone (story-004) should uncheck every acceptance box in `docs/milestones/03_magic.md` and rewrite the milestone status to NOT_STARTED. Currently every box in the milestone file is `[ ]` — no false-positive checkmarks need to be reverted, but the milestone-level "Goal" framing implies a started effort and should be re-flagged as deferred.

2. **Stale `gp` cost references in spec (carried over from sprint-001 Phase 0 audit, `docs/milestones/audit/phase-0.md`).** Two spell entries in `game_mechanics_magic.md` still use the deprecated `gp` (gold piece) economy:
   - `magic.md:423` — Revivify: `"Requires diamond (50 gp, consumed)"`.
   - `magic.md:432` — Resurrection: `"Diamond (500 gp, consumed)"`.
   Both diamond components should migrate to the M0.3 economy units (likely a barter-token or "rarity tier" tag rather than a gp value). These are M0.3 cleanup targets identified in sprint-001 and **must not be edited by this story (read-only constraint)**. Capstone should flag them for a separate spec-cleanup PR.

3. **Spec/milestone divergence — Draethar Inner Fire cost.** Spec (`magic.md:264`): "reduce current Resonance by 3, take 1d6 fire damage (self-inflicted, cannot be reduced), 1/encounter". Milestone deliverable (`03_magic.md:129`): "pressure valve ability to dump Resonance at a cost (HP or Focus)". Capstone should reconcile: the spec's fire-damage cost is more specific and aligned with the "Inner Fire" theme — recommend tightening the milestone text to match the spec (not the other way around).

4. **NEW spec content not covered by any M3.x bullet.** None of the following spec content is captured by an M3.x deliverable or acceptance bullet, so the milestone undercommits:
   - **Bard 0.4× multiplier** (`magic.md:88-90`) — milestone names only Arcane/Divine/Primal sources.
   - **Veythar post-reveal 0.7× compromised filter** (`magic.md:59`, `magic.md:120`) — a state transition not modeled anywhere. Cross-doc dep with `docs/game_mechanics/game_mechanics_patrons.md` (Veythar reveal arc).
   - **Cantrip generates 0 Resonance** (`magic.md:112-113`) — early-return rule, not in milestone.
   - **Full Resonance reset on short or long rest** (`magic.md:131`) — milestone only mentions per-round decay; rest reset is unstated.
   - **Veil Fracture event at 15+** (`magic.md:134`) — narrative-scale consequence, no M3.x bullet.
   - **Resonance Sensing tiers for Non-Elari via Arcana skill** (`magic.md:280-293`) — Untrained/Trained/Expert/Master ladder; no M3.x bullet (cross-doc dep with skills system).
   - **Druid preparation constraint** ("can only change spell preparation in natural terrain", `magic.md:458`) — no M3.x bullet (cross-doc dep with archetypes).
   - **Veil Ward per-archetype sources table** (`magic.md:204-210`) — five sources (Cleric/Druid/Artificer/Paladin/Sacred sites) with distinct costs, levels, durations; M3.2 deliverable treats Veil Ward as a single generic mechanic.

5. **Catalog data is unshipped but spec is internally consistent.** Per-section counts in `magic.md` (Arcane 30 = 5+6+6+6+7; Divine 28 = 4+6+6+6+6; Primal 29 = 5+6+6+6+6) sum to 87, matching the headline claim at `magic.md:541`. No mismatch to flag — the data shape is well-defined for the implementer.

6. **`request_attack(target_id, weapon_or_spell)` at `apps/agent/combat_tools.py:275` is the only spell-adjacent agent tool today.** It accepts an arbitrary string and looks it up in the player's inventory (line 301), so an item named "Fireball" would route through it as a weapon. There is no validation against any spell catalog and no Focus / Resonance / concentration interaction. Capstone should not count this toward any M3.3 acceptance bullet — it predates the magic system and is purely a weapon-attack path with a misleading parameter name.

## Cross-doc dependencies

- **Magic ↔ Archetype spell slots** (Phase 2): Spec implies per-archetype spell-source assignments — Mage/Artificer/Seeker (Arcane); Cleric/Paladin/Oracle (Divine); Druid/Beastcaller/Warden (Primal); Bard (cross-source) — across `magic.md:39, 57, 86, 90`. No M3.x bullet captures these archetype→source bindings; that mapping is presumed to live with `game_mechanics_archetypes.md` and Phase 2. Veil Ward archetype sources at `magic.md:204-210` are the other cross-cutting dep. Capstone audit of Phase 2 (story-001 of sprint-002) should verify the source binding exists; if not, M3.3 cannot validate `cast_spell` source dispatch.

- **Magic ↔ Patron Layer 2 Resonance modifiers** (Phase 8): The Veythar post-reveal 0.7× shift (`magic.md:59`) is the named example. Patron-driven Resonance modifications are a Layer 2 patron mechanic — see `docs/game_mechanics/game_mechanics_patrons.md` and `docs/milestones/08_patrons.md`. M3.x does not currently include a hook for patron-side Resonance overrides; implementer should expose either a `patron_modifier` parameter on `calculate_resonance_generated` or a lookup helper that consults the patron table.

- **Magic ↔ Race tables** (Phase 1 character creation): `apps/agent/creation_races.py:21+` `RACES` dict has no Resonance-related fields. M3.4 calls for `racial_resonance_bonuses` as a separate DB table — this is consistent with the milestone's design (decoupled from `RaceData`), but the implementer should decide whether to migrate the racial-mechanics layer into `creation_races.py` or keep it in its own seed. Vaelti's Hollow-Echo advance-warning and Thessyn's 10+ session adaptation both need state plumbing that does not currently exist on the character record.

- **Magic ↔ Skills (Arcana, Theology, Naturalist)** (cross-doc): `magic.md:280-293` defines a 4-tier Arcana sensing ladder; `apps/agent/rules_engine.py:175-200` already encodes Arcana / Theology / Naturalist expert/master abilities **as narration strings only** — the mechanical effects (sensing Resonance levels, sensing Veil condition) are not wired to any function. When M3.1 ships, the Arcana ladder needs read-only access to the Resonance state lookup; design hook should be considered in M3.1 API shape.

- **Magic ↔ Cost model** (Phase 0): Stale `gp` references at `magic.md:423, 432` (Revivify diamond, Resurrection diamond) are M0.3 cleanup targets from sprint-001. Not blocking, but capstone should keep these on the spec-cleanup punch list.
