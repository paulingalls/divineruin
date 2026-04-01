# Phase 8: Divine Patron System

> Source doc: `docs/game_mechanics/game_mechanics_patrons.md`

Implements the divine patron system: 10 gods with 4-layer mechanical architecture, favor tracking driven by the simulation layer, tiered ability unlocks, archetype synergies, and the Unbound Path for players who reject divine patronage.

---

### Milestone 8.1 — Patron Profiles & Divine Favor

**Goal:** Define the 10 divine patron profiles with their 4-layer mechanical architecture and implement the divine favor tracking system that evaluates player behavior against patron values on a simulation heartbeat.

**Inputs:** Phase 1 (Core Systems — attribute model, leveling), Phase 2 (Archetypes — class definitions for synergy hooks), Phase 3 (Magic — Resonance system for Layer 2 modifiers), existing `content/gods.json`.

**Deliverables:**
- 10 divine patron profiles, each with 4 mechanical layers:
  - Layer 1: Universal passive gift (always active, e.g., Veythar's reroll on knowledge checks)
  - Layer 2: Resonance modifier (e.g., Kaelen's -1 Resonance cost on combat spells)
  - Layer 3: Divine favor abilities unlocked through alignment tiers
  - Layer 4: Archetype synergy enhancements (implemented in M8.3)
- Divine Favor tracking: simulation layer evaluates player behavior against patron values on a 15-30 minute heartbeat
- 3 favor tiers: Acknowledged (entry), Devoted (mid), Exalted (peak) — each unlocking new abilities
- Favor value: numeric score that accumulates/decays based on alignment evaluation
- Unbound Path definition: no-patron option with perfect Resonance visibility, voluntary +3 Resonance push, Veil Mastery ability
- DB migration: `player_patron` table (player_id, patron_id, selected_at), `patron_favor_state` table (player_id, patron_id, tier, favor_value, last_eval_timestamp)
- Content: `content/gods.json` expanded with all 10 patron mechanical profiles (layers 1-4)
- Rules engine: `evaluate_patron_alignment(player_actions, patron_values)` returning favor_delta
- Rules engine: `get_patron_tier(favor_value)` returning current tier based on thresholds
- Background process hook: periodic favor evaluation on simulation heartbeat

**Acceptance criteria:**
- [ ] All 10 patron profiles have Layer 1 (passive), Layer 2 (Resonance modifier), and Layer 3 (ability tiers) defined
- [ ] Each patron's Layer 1 passive is mechanically distinct and always active
- [ ] Layer 2 Resonance modifiers integrate with Phase 3 Magic Resonance calculations
- [ ] `evaluate_patron_alignment` produces positive delta for aligned actions and negative for misaligned
- [ ] Favor tiers transition correctly: Acknowledged at threshold A, Devoted at B, Exalted at C
- [ ] Favor can decay (not just grow) — neglecting patron values reduces favor over time
- [ ] Unbound Path is selectable and grants Resonance visibility, +3 voluntary Resonance push, and Veil Mastery
- [ ] `content/gods.json` validates with all 10 complete patron profiles
- [ ] Background process calls `evaluate_patron_alignment` on 15-30 minute heartbeat
- [ ] DB schema supports patron selection, favor tracking, and tier state
- [ ] Tests cover favor accumulation, decay, tier transitions (up and down), and Unbound Path mechanics

**Key references:**
- *Game Mechanics Patrons — 4-Layer Architecture*
- *Game Mechanics Patrons — Divine Favor Tracking*
- *Game Mechanics Patrons — Patron Value Alignment*
- *Game Mechanics Patrons — Unbound Path*

---

### Milestone 8.2 — Patron Abilities (3 Tiers)

**Goal:** Implement all patron abilities across the 3 favor tiers, with recharge mechanics and agent tool integration so the DM can grant and activate them during play.

**Inputs:** M8.1 (patron profiles and favor tier system), Phase 1 (Core — resolution pipeline for ability effects).

**Deliverables:**
- Per patron: 3 tiers of abilities (Acknowledged, Devoted, Exalted), each tier containing 1-3 abilities
- Total: 30+ patron abilities across all 10 patrons
- Per ability: name, description, mechanical effect, recharge condition (short rest, long rest, or daily)
- Example: Kaelen grants Battle Cry at Acknowledged, Divine Smite at Devoted, Storm of Judgment at Exalted
- Ability unlock logic: when patron_favor_state.tier reaches a new tier, abilities for that tier become available
- Ability loss on tier regression: if favor drops below tier threshold, higher-tier abilities become unavailable (not permanently lost)
- DB migration: `patron_ability_unlock` table (player_id, ability_id, acquired_date, available flag)
- Agent tools: `activate_patron_ability(player_id, ability_id)` resolving effect and tracking recharge, `check_patron_tier(player_id)` returning tier and available abilities
- Client data: patron ability list for character sheet display, favor bar value for HUD overlay

**Acceptance criteria:**
- [ ] All 10 patrons have abilities defined for all 3 tiers (Acknowledged, Devoted, Exalted)
- [ ] Each ability has name, effect, and recharge condition specified
- [ ] Recharge tracking prevents ability use before recharge completes (short rest / long rest / daily)
- [ ] Ability unlock triggers automatically when favor tier advances
- [ ] Higher-tier abilities become unavailable (not deleted) when favor drops below tier threshold
- [ ] `activate_patron_ability` validates availability, applies effect, and sets recharge timer
- [ ] `activate_patron_ability` returns error if ability is on cooldown or tier is insufficient
- [ ] `check_patron_tier` returns current tier, favor value, and list of available abilities
- [ ] Client receives patron ability data for character sheet and favor bar for HUD
- [ ] Unbound Path players have no patron abilities (Unbound benefits come from M8.1 passives)
- [ ] Tests cover ability activation, recharge, tier-up unlock, tier-down lockout, and Unbound exclusion

**Key references:**
- *Game Mechanics Patrons — Patron Abilities by Tier*
- *Game Mechanics Patrons — Recharge Mechanics*
- *Game Mechanics Patrons — Ability Unlock and Loss*

---

### Milestone 8.3 — Archetype Synergies & Unbound Path

**Goal:** Complete the patron system by implementing Layer 4 archetype synergy bonuses and fully fleshing out the Unbound Path as a mechanically complete alternative to divine patronage.

**Inputs:** M8.1 (patron profiles with Layer 4 stubs), M8.2 (patron abilities), Phase 2 (Archetypes — class definitions).

**Deliverables:**
- Archetype synergy lookup table: archetype x patron matrix with 3 synergy categories per pairing:
  - Natural: expected combination (e.g., Warrior + Kaelen), moderate bonus
  - Divine: thematic but not obvious combo, moderate bonus
  - Unexpected: surprise pairing with unique interaction, smaller but flavorful bonus
- Per synergy entry: synergy_type, bonus_description, mechanical_effect
- Layer 4 bonus application: synergy enhances existing patron abilities or grants additional passive effects based on player archetype
- Unbound Path full implementation:
  - Perfect Resonance visibility (player always knows exact Resonance value)
  - Voluntary +3 Resonance push (player can choose to gain Resonance for power boost)
  - Veil Mastery passive (reduced negative Hollow effects, bonus saves vs corruption)
  - No patron abilities — Unbound trades divine power for Resonance mastery
- DB migration: `archetype_synergy` table (archetype_id, patron_id, synergy_type, bonus)
- Rules engine: `get_archetype_synergy(archetype, patron)` returning synergy type and bonus
- Rules engine: `apply_unbound_resonance_push(player)` adding +3 Resonance with associated benefits
- Agent tool: `query_patron_synergy(player_id)` returning active synergy for current archetype/patron pair

**Acceptance criteria:**
- [ ] Synergy lookup covers all archetype x patron combinations (every archetype has entries for every patron)
- [ ] Each pairing has exactly one synergy type assigned (Natural, Divine, or Unexpected)
- [ ] Natural synergies provide the largest mechanical bonus, Unexpected the most unique
- [ ] `get_archetype_synergy` returns correct synergy for any archetype/patron pair
- [ ] Layer 4 bonuses apply on top of existing Layer 1-3 mechanics without overriding them
- [ ] Unbound Path grants perfect Resonance visibility (exact value, not just tier)
- [ ] Unbound +3 Resonance push is voluntary and costs no action
- [ ] Veil Mastery provides measurable mechanical benefit (bonus to corruption saves, reduced Hollow effects)
- [ ] Unbound Path has NO patron abilities — only Resonance mastery benefits
- [ ] `query_patron_synergy` returns empty/null for Unbound players (no synergy applicable)
- [ ] All 10 patrons + Unbound Path are fully implemented and playable after this milestone
- [ ] Tests cover synergy lookup for all combinations, Unbound mechanics, and Layer 4 bonus stacking

**Key references:**
- *Game Mechanics Patrons — Archetype Synergies*
- *Game Mechanics Patrons — Synergy Categories (Natural, Divine, Unexpected)*
- *Game Mechanics Patrons — Unbound Path Full Specification*
