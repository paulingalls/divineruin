# Phase 3: Magic System

> Source doc: `docs/game_mechanics/game_mechanics_magic.md`

Implements the three-source Resonance magic system, Hollow Echo dangers, the full spell catalog, concentration mechanics, and racial Resonance interactions. Depends on Phase 1 (Core Systems) and Phase 2 (Archetypes). Can run in parallel with Phase 4 (Combat) after Phase 2 completes.

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
