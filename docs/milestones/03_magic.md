# Phase 3: Magic System

> Source doc: `docs/game_mechanics/game_mechanics_magic.md`

Implements the three-source Resonance magic system, Hollow Echo dangers, the full spell catalog, concentration mechanics, and racial Resonance interactions. Depends on Phase 1 (Core Systems) and Phase 2 (Archetypes). Can run in parallel with Phase 4 (Combat) after Phase 2 completes.

---

## Audit Status (Sprint-002)

Sprint-002 reconciled this milestone against `game_mechanics_magic.md` (542L) and shipped code. **Full audit:** `docs/milestones/audit/phase-3-magic.md` <!-- see audit/phase-3-magic.md -->.

### Coverage matrix

| Milestone | Confirmed | Aspirational | NOT_SHIPPED |
| --- | --- | --- | --- |
| M3.1 — Resonance System (8 criteria) | 0 | 0 | 8 |
| M3.2 — Hollow Echo & Veil Wards (9 criteria) | 0 | 0 | 9 |
| M3.3 — Spell Catalog (8 criteria) | 0 | 0 | 8 |
| M3.4 — Concentration & Racial Resonance (9 criteria) | 0 | 0 | 9 |

**Headline:** The entire Magic system M3.1-M3.4 is unshipped. No Resonance state, no spell catalog, no concentration, no racial Resonance bonuses, no Hollow Echo table, no Veil Ward mechanics exist in code. The only Resonance-adjacent references are flavor strings inside skill-ability descriptions (`apps/agent/rules_engine.py:175-200`) and one async training activity slug `spell_cantrip`. All M3.x acceptance boxes were already `[ ]` — no checkmarks to revert. Milestone-level status is **DEFERRED / NOT_STARTED**.

### Material gaps

- **`content/spells.json` does not exist.** Spec is internally consistent at 87 spells (Arcane 30 = 5+6+6+6+7; Divine 28 = 4+6+6+6+6; Primal 29 = 5+6+6+6+6 — match the headline at `magic.md:541`). Implementer has a well-defined data shape. <!-- see audit/phase-3-magic.md -->
- **`request_attack(target_id, weapon_or_spell)` at `apps/agent/combat_tools.py:275` is NOT a spell-cast tool.** It accepts an arbitrary string token and looks it up in the player's inventory; no catalog validation, no Focus / Resonance / concentration interaction. Capstone explicitly does not count this toward any M3.3 bullet. <!-- see audit/phase-3-magic.md -->
- **`RaceData` schema gap.** `apps/agent/creation_races.py:8-15` `RaceData` has only `id/name/description/card_description/attribute_bonuses` — no Resonance fields. When M3.4 ships, either extend `RaceData` or seed via a separate `racial_resonance_bonuses` content file (per the milestone). Thessyn's 10+ session counter and Vaelti's 1-round advance warning need state plumbing the character record does not currently expose. <!-- see audit/phase-3-magic.md -->
- **Spec/milestone divergence — Draethar Inner Fire cost.** Spec (`magic.md:264`): "reduce current Resonance by 3, take 1d6 fire damage (self-inflicted, cannot be reduced), 1/encounter". Milestone deliverable text (`03_magic.md:129` original): "HP or Focus" cost. Capstone recommends tightening milestone text to match spec (fire-damage cost is more specific and aligned with the "Inner Fire" theme).
- **Stale `gp` references in source spec.** Carried over from sprint-001 Phase 0 audit (`docs/milestones/audit/phase-0.md`). `magic.md:423` Revivify "Diamond (50 gp, consumed)" and `magic.md:432` Resurrection "Diamond (500 gp, consumed)" need migration to M0.3 economy units. These are M0.3 cleanup targets — flagged here for the spec-cleanup punch list, not edited in this story.
- **NEW spec content not covered by any M3.x bullet** (milestone undercommits):
  - Bard 0.4× multiplier (`magic.md:88-90`) — milestone names only Arcane/Divine/Primal.
  - Veythar post-reveal 0.7× compromised filter (`magic.md:59, 120`) — endgame state transition; cross-doc dep with patrons.
  - Cantrip generates 0 Resonance (`magic.md:112-113`) — early-return rule.
  - Full Resonance reset on short or long rest (`magic.md:131`) — milestone only mentions per-round decay.
  - Veil Fracture event at 15+ (`magic.md:134`) — narrative-scale consequence.
  - Resonance Sensing tiers for Non-Elari via Arcana ladder (`magic.md:280-293`) — Untrained/Trained/Expert/Master.
  - Druid preparation constraint ("only change spell preparation in natural terrain", `magic.md:458`).
  - Veil Ward per-archetype sources table (`magic.md:204-210`) — Cleric/Druid/Artificer/Paladin/Sacred sites with distinct costs, levels, durations.

### Cross-doc dependencies

- **Magic ↔ Archetype spell slots** — Per-archetype source bindings (Mage/Artificer/Seeker = Arcane; Cleric/Paladin/Oracle = Divine; Druid/Beastcaller/Warden = Primal; Bard = cross-source) at `magic.md:39, 57, 86, 90` are presumed to live with archetypes. Veil Ward archetype sources at `magic.md:204-210` are the other cross-cutting dep. See `audit/phase-2-archetypes.md`.
- **Magic ↔ Patron Layer 2 Resonance modifiers** — Veythar post-reveal 0.7× shift is the named example. Patron-driven Resonance modifications are Layer 2 patron mechanics. M3.x has no current hook for patron-side overrides — expose either a `patron_modifier` parameter on `calculate_resonance_generated` or a lookup helper. See `audit/phase-8-patrons.md`.
- **Magic ↔ Race tables** — `creation_races.py:RACES` has no Resonance fields; M3.4 calls for a separate `racial_resonance_bonuses` table.
- **Magic ↔ Skills (Arcana / Theology / Naturalist)** — `magic.md:280-293` defines a 4-tier Arcana sensing ladder; `apps/agent/rules_engine.py:175-200` already encodes ability narration strings, but mechanical effects aren't wired. M3.1 API shape should reserve a read-only `get_resonance_state` hook for the Arcana ladder.
- **Magic ↔ Cost model** — Stale `gp` refs at `magic.md:423, 432` are M0.3 cleanup carry-forward.

---

### Milestone 3.1 — Resonance System

**Goal:** Implement the Resonance accumulation and decay system so that casting spells generates source-specific Resonance that escalates through defined states, creating a risk-reward tension for casters.

**Inputs:** Phase 1 (Core Systems), Phase 2 (Archetypes — resource types and spell acquisition).

**Deliverables:**
- Pure functions in rules engine:
  - `calculate_resonance_generated(focus_cost, source, terrain=None)` — applies source multiplier (Arcane 0.6x, Divine 0.3x, Primal 0.1-0.8x terrain-dependent)
  - `get_resonance_state(current_resonance)` — returns Stable (0-4), Flickering (5-8), or Overreach (9+)
  - `apply_resonance_decay(current_resonance, racial_modifier=0)` — decrements by 1/round (or 2/round for Human racial)
- Resonance state modifiers: Flickering grants +1 damage die; Overreach grants +2 damage dice and +2 DC
- Escalating modifiers at high Resonance: additional effects at 12+ and 15+
- DB: `character_resonance` tracking (current value, current state) — either new table or column on character state
- Client: Resonance tracker visual with distinct styling for Stable, Flickering, and Overreach states
- Resonance formula: `resonance = ceil(focus_cost * source_multiplier)`

**Acceptance criteria:**
- [ ] `calculate_resonance_generated()` returns correct values for each source: Arcane at 0.6x, Divine at 0.3x, Primal at terrain-dependent 0.1-0.8x
- [ ] `get_resonance_state()` returns Stable for 0-4, Flickering for 5-8, Overreach for 9+
- [ ] `apply_resonance_decay()` reduces Resonance by 1 per round by default, 2 for Human racial modifier
- [ ] Resonance never goes below 0
- [ ] Flickering state applies +1 damage die modifier to spell effects
- [ ] Overreach state applies +2 damage dice and +2 DC modifier to spell effects
- [ ] Client displays Resonance tracker with visually distinct states
- [ ] Unit tests cover all source multipliers, all state thresholds, decay edge cases, and terrain-dependent Primal calculation

**Key references:**
- *Game Mechanics Magic Doc — Three-Source Resonance*
- *Game Mechanics Magic Doc — Resonance States*
- *Game Mechanics Magic Doc — Resonance Decay*

---

### Milestone 3.2 — Hollow Echo & Veil Wards

**Goal:** Implement the Hollow Echo danger table and Veil Ward protection system so that high Resonance carries real consequences and players have a defensive option that trades power for safety.

**Inputs:** M3.1 (Resonance System).

**Deliverables:**
- Hollow Echo table as pure function: `resolve_hollow_echo(d20_roll, resonance_level)` — maps roll to severity
  - Result range: nothing, whisper, veil scar, sympathetic resonance, Hollow attention, reality fracture, breach
  - Severity scales with current Resonance level
- Hollow Echo trigger: automatic d20 roll when a character is at Overreach state
- Veil Ward system:
  - `activate_veil_ward(character_id)` — establishes local area reinforcement
  - Ward effect: halves Resonance generation while active
  - Ward penalty: -1 damage die, -1 DC while active
  - Ward bonus: +4 to Hollow Echo roll (shifts results toward safety)
- Agent tools: `resolve_hollow_echo` (rolls and narrates result), `activate_veil_ward` (toggles ward on/off)
- Client: Hollow Echo roll display (dramatic dice animation), Veil Ward zone indicator

**Acceptance criteria:**
- [ ] `resolve_hollow_echo()` returns correct severity for all d20 roll ranges
- [ ] Echo severity scales with Resonance level (higher Resonance = worse outcomes at same roll)
- [ ] Hollow Echo is triggered automatically when casting at Overreach
- [ ] Veil Ward halves Resonance generation from all sources while active
- [ ] Veil Ward applies -1 damage die and -1 DC penalty while active
- [ ] Veil Ward grants +4 bonus to Hollow Echo rolls while active
- [ ] Veil Ward can be activated and deactivated by the player
- [ ] Client displays Hollow Echo roll results and Veil Ward zone indicator
- [ ] Unit tests cover full Echo table, ward modifiers, and interaction between ward bonus and Echo roll

**Key references:**
- *Game Mechanics Magic Doc — Hollow Echo Table*
- *Game Mechanics Magic Doc — Veil Ward System*
- *Game Mechanics Magic Doc — Echo Severity Scaling*

---

### Milestone 3.3 — Spell Catalog

**Goal:** Build the complete spell catalog (87 spells) with full mechanical definitions, Resonance generation values, audio cues, and agent tooling so the DM agent can validate and narrate any spell cast in the game.

**Inputs:** M3.1 (Resonance System), M2.4 (Spell Acquisition).

**Deliverables:**
- Content file `content/spells.json` with all 87 spell entries: Arcane (30), Divine (28), Primal (29)
- Each spell entry contains: name, source (Arcane/Divine/Primal), focus_cost, resonance_by_source, terrain_effects (for Primal), spell_tier, level_requirement, mechanics, narration_cue, audio_cue, concentration (boolean)
- `spell_catalog` DB table seeded from `content/spells.json`
- Cantrip scaling formula: 1d6 (L1-4), 2d6 (L5-10), 3d6 (L11-16), 4d6 (L17-20)
- Agent tool `get_spell_info` — looks up spell details for DM narration
- Agent tool `cast_spell` — validates Focus cost, generates Resonance via M3.1, resolves effect, returns narration cue and audio cue
- Migration to create and seed the `spell_catalog` table

**Acceptance criteria:**
- [ ] `content/spells.json` contains exactly 87 spells: 30 Arcane, 28 Divine, 29 Primal
- [ ] Every spell entry has all required fields: name, source, focus_cost, resonance_by_source, spell_tier, level_requirement, mechanics, narration_cue, audio_cue
- [ ] `spell_catalog` table is seeded with all 87 entries and queryable by source, tier, and level
- [ ] `cast_spell` deducts Focus cost, calls `calculate_resonance_generated()`, and returns effect + narration cue + audio cue
- [ ] `cast_spell` rejects casting when Focus is insufficient
- [ ] Cantrip damage scales correctly at each level bracket (L1-4, L5-10, L11-16, L17-20)
- [ ] `get_spell_info` returns full spell data including narration and audio cues
- [ ] Unit tests cover casting validation, Resonance generation integration, cantrip scaling, and spell lookup

**Key references:**
- *Game Mechanics Magic Doc — Spell Catalog*
- *Game Mechanics Magic Doc — Cantrip Scaling*
- *Game Mechanics Magic Doc — Spell Entry Format*

---

### Milestone 3.4 — Concentration & Racial Resonance

**Goal:** Implement spell concentration mechanics and racial Resonance interactions so that maintaining spells carries risk and each playable race has a unique relationship with magic.

**Inputs:** M3.1 (Resonance System), M3.3 (Spell Catalog — concentration flag on spells), existing character/race data.

**Deliverables:**
- Concentration rules in the rules engine:
  - `check_concentration(character_id, damage_taken)` — CON save at DC 10 or half damage, whichever is higher
  - Only one Concentration spell active at a time; casting a second ends the first
  - Incapacitation auto-fails concentration
  - Concentration flag on spells in the catalog (set in M3.3)
- Racial Resonance interactions as pure functions:
  - Elari: Veil-sense — passive ability to feel ambient Resonance levels
  - Human: Adaptive decay — Resonance decays at -2/round instead of -1
  - Vaelti: Hyper-awareness — 1-round advance warning before Hollow Echo triggers
  - Korath: Earth-anchored — -1 Primal Resonance generation
  - Draethar: Inner Fire — pressure valve ability to dump Resonance at a cost (HP or Focus)
  - Thessyn: Deep Adaptation — permanent Resonance handling improvement accrued over 10+ sessions
- `racial_resonance_bonuses` DB configuration table
- Rules engine: `get_racial_resonance_modifier(race, modifier_type)` lookup function
- Integration with `apply_resonance_decay()` and `calculate_resonance_generated()` from M3.1

**Acceptance criteria:**
- [ ] Concentration save DC is max(10, damage / 2) — unit tests for boundary values
- [ ] Casting a Concentration spell while one is active ends the previous spell
- [ ] Incapacitated characters automatically lose concentration
- [ ] Human racial modifier applies -2 decay per round (verified via `apply_resonance_decay`)
- [ ] Korath racial modifier reduces Primal Resonance generation by 1 (verified via `calculate_resonance_generated`)
- [ ] Draethar can dump Resonance via pressure valve at a defined cost
- [ ] Vaelti receive advance warning before Hollow Echo (integrated with `resolve_hollow_echo` from M3.2)
- [ ] `racial_resonance_bonuses` table is seeded with all 6 racial entries
- [ ] Unit tests cover concentration saves, auto-fail on incapacitation, single-concentration enforcement, and all 6 racial modifiers

**Key references:**
- *Game Mechanics Magic Doc — Concentration*
- *Game Mechanics Magic Doc — Racial Resonance Interactions*
- *Game Mechanics Magic Doc — Resonance Modifiers*
