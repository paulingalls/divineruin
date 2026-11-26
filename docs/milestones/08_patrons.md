# Phase 8: Divine Patron System

> Source doc: `docs/game_mechanics/game_mechanics_patrons.md`

Implements the divine patron system: 10 gods with 4-layer mechanical architecture, favor tracking driven by the simulation layer, tiered ability unlocks, archetype synergies, and the Unbound Path for players who reject divine patronage.

---

## Sprint-101: favor standing and content

The favor foundation is implemented: all ten patrons have values, opposed values,
and signed favor actions; tiers derive from the current favor row at 0%, 40%, and
75% of its own maximum, with fractional boundaries rounded upward.
`query_info(kind="patron")` returns standing, progress to the next tier, and the
authored action IDs. Unbound and Exalted have explicit responses. Negative favor
events now reach the HUD, with signed toast rendering covered by mobile tests.

This slice does not implement alignment evaluation, time decay, or mechanical
gift layers. Layers 1–4 remain null. Query discovery is in the tool schema and
description; the future alignment workflow still needs its invocation path and
prompt cue. Tier/content/query tests and the mobile test directory cover this
slice; no real-LLM patron-query scenario or negative-toast browser case is claimed.

The Sprint-002 audit below is historical, not the current content inventory.

## Audit Status (Sprint-002)

Sprint-002 reconciled this milestone against `game_mechanics_patrons.md` (366L) and shipped code. **Full audit:** `docs/milestones/audit/phase-8-patrons.md` <!-- see audit/phase-8-patrons.md -->.

### Coverage matrix

| Milestone | Confirmed | Aspirational | Unverified |
| --- | --- | --- | --- |
| M8.1 — Patron Profiles & Divine Favor (11 criteria) | 0 | 10 | 1 |
| M8.2 — Patron Abilities by Tier (11 criteria) | 0 | 11 | 0 |
| M8.3 — Archetype Synergies & Unbound Path (12 criteria) | 0 | 12 | 0 |

**Headline:** The patron system is almost entirely aspirational. What exists today: a thin `divine_favor` numeric score (0-100) + a `patron_id` per player, plus a god-whisper voice/personality layer for the 10 deities. The 4-layer architecture (Divine Gift / Resonance Modifier / Favor Abilities / Archetype Resonance) is not encoded outside markdown. All M8.x acceptance boxes were already `[ ]` — no checkmarks to revert. Milestone-level status is **DEFERRED / NOT_STARTED**. Unbound Path is **selectable** (only mechanical step done — see M8.1 row marked `unverified`).

### Material gaps

- **`content/gods.json` has 10 of 10 patrons** with narrative data and favor actions. All four mechanical layer fields remain null for each patron; those layers still need implementation. <!-- see audit/phase-8-patrons.md -->
- **Favor model is single-integer, not tiered.** `players.data->'divine_favor'.level` is 0-100. Spec needs Acknowledged/Devoted/Exalted tier thresholds + bidirectional transitions + decay. As of M28 story-003 the `award_divine_favor` tool no longer exists; favor accrues only through the quest-completion Resolve (`_award_divine_favor_core`), which accepts positive deltas and clamps at the patron max. No decay coroutine exists. The tiering and decay design below still stands — it now has to land on the Resolve, not on a tool. <!-- see audit/phase-8-patrons.md -->
- **Alignment evaluation is LLM-driven, not rules-engine-driven.** Spec promises `evaluate_patron_alignment(player_actions, patron_values) -> favor_delta` as deterministic. Historically the LLM called `award_divine_favor(amount, reason)` with a freeform judgement; M28 story-003 removed that tool, so favor is already off LLM judgement — but it is driven by authored quest content, not yet by a deterministic alignment evaluation. `content/gods.json` already encodes `favor_actions.positive[]` and `favor_actions.negative[]` per patron — currently unused. <!-- see audit/phase-8-patrons.md -->
- **No 15-30 minute simulation heartbeat for favor.** `apps/agent/async_worker.py:400` `check_god_whisper_triggers` polls FAVOR_WHISPER threshold for whispers — that's not patron alignment evaluation.
- **Layer 4 synergy is too coarse.** `creation_deities.DeityData.synergy_classes` is a flat tuple per deity (e.g., `kaelen → (warrior, guardian, skirmisher, paladin)`) — no Natural/Divine/Unexpected categorisation, no per-pairing mechanical bonus. Needs an (11 × 18) archetype × patron matrix.
- **Unbound Path mechanics implemented.** Selectable, Veil Clarity, Raw Channeling and universal Layer 4 +1 when alone ship (sprints patron-favor-mini and archetype-synergies). Persisted autonomy and all three deed producers ship; Self-Reliant grants a durable save choice, Self-Forged grants long-rest Divine Immunity (narrated resolution only), and Sovereign gates once-per-session Veil Mastery (sprint unbound-self-reliance). Evidence: `test_unbound_autonomy.py`, `test_deed_producers.py`, `test_unbound_milestones.py` and `test_unbound_path.py`.
- **Spec hint not in milestone**: Veythar's "Post-reveal: divine filter degrades from 0.3× to 0.7×" (spec L47) describes an endgame state transition on a Layer 2 modifier. Capstone may want to flag as NEW or defer.

### Cross-doc dependencies

- **Patrons ↔ Magic Resonance (Phase 3) — Layer 2 modifiers — UNBLOCKED.** Every patron's Layer 2 modifier (Veythar +2 Flickering dice, Kaelen -1 Resonance on combat spells, Orenthel 0 Resonance on healing, etc.) requires a working Resonance system. The Sprint-002 audit (`audit/phase-3-magic.md`) found Phase 3 unshipped; it has since shipped (`resonance.py`), so M8.1 Layer 2 can proceed.
- **Patrons ↔ Archetypes (Phase 2) — Layer 4 synergies — FORWARD DEP.** M8.3's archetype × patron matrix needs the 18 archetypes' canonical IDs (already in the DB-loaded chassis, `apps/agent/archetypes.py`) AND per-archetype detail encoding from Phase 2. Sprint-001 confirmed the 18 IDs; per-archetype technique/spell surfaces are still partial. See `audit/phase-2-archetypes.md`.
- **Patrons ↔ Unbound Veil Mastery ↔ Hollow Echo.** Unbound's Sovereign-tier "Veil Mastery" ("treat any Hollow Echo result as Nothing stirs") requires a Hollow Echo table. Hollow Echo is implied by Phase 3.
- **Patrons ↔ god-whisper system.** Existing god-whisper generator operates on raw `divine_favor.level` integer. Any tier restructuring (M8.1 acceptance #5) must preserve the whisper trigger — keyed off `level`, not `tier`. Within-phase consistency concern, not a blocker.

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
- [x] All 10 patron profiles have Layer 1 (passive), Layer 2 (Resonance modifier), and Layer 3 (ability tiers) defined (sprint patron-favor-mini)
  <!-- Evidence (sprint patron-favor-mini): content/gods.json carries Layer 2 modifiers and three Layer 3 tiers for all 10 patrons; test_gods_layers.py and packages/shared/src/entities/god.test.ts validate them against one shared fixture corpus. -->
- [x] Each patron's Layer 1 passive is mechanically distinct and always active
  <!-- Evidence: test_dawns_resilience.py and test_dawns_resilience_atomicity.py drive Orenthel's gift through registered exploration and combat tools. Existing gift coverage includes test_veythar_gift.py, test_syrath_gift.py, test_kaelen_gift_tools.py, test_aelora_gift.py, test_thyra_gift.py, test_patron_abilities.py (Valdris), test_patron_senses.py (Mortaen and Nythera), and test_zhael_fate.py. test_patron_gift_content.py, test_gods_layers.py and god.test.ts validate the authored gifts. -->
- [x] Layer 2 Resonance modifiers integrate with Phase 3 Magic Resonance calculations (sprint patron-favor-mini)
  <!-- Evidence (sprint patron-favor-mini): all 10 patrons through the production cast path. Generation modifiers are in test_patron_resonance_generation.py; the Syrath concealment and Valdris wrongdoing producers are in test_syrath_valdris_producers.py; Veythar Flickering dice, Aelora ward harmony and Zhael's chosen Echo are in test_patron_resonance_effects.py. -->
- [x] `evaluate_patron_alignment` produces positive delta for aligned actions and negative for misaligned
  <!-- Evidence: test_patron_alignment_session.py::test_due_once_and_recent_context and ::test_pause_then_negative_judgment drive real combat tools and the running session loop, persisting Kaelen +2 for victory and -3 for flight. -->
- [x] Favor tiers transition correctly: Acknowledged at 0%, Devoted at 40%, Exalted at 75% of the patron's maximum (Sprint-101)
- [x] Favor can decay (not just grow) — neglecting patron values reduces favor over time
  <!-- Evidence: test_favor_decay_hydration.py checks fresh-session persistence, event delivery, join, and handback; use-game-events.character.test.ts checks the shared event fixture on the client. -->
- [x] Unbound Path is selectable and grants Resonance visibility, +3 voluntary Resonance push, and Veil Mastery (sprint patron-favor-mini)
  <!-- Evidence (sprint patron-favor-mini): test_unbound_path.py and test_unbound_commit_integrity.py cover exact Resonance in query_info, the once-per-encounter Raw Channeling push via activate, and once-per-session Veil Mastery. Sovereign gating now ships in M8.3, covered by test_unbound_milestones.py::test_pre_sovereign_echo_is_real_for_acting_member. -->
- [x] `content/gods.json` validates with all 10 complete patron profiles (sprint patron-favor-mini)
  <!-- Evidence (sprint patron-favor-mini): the Python loader and the TS validateGods fail loudly on the shared invalid corpus; Layer 4 stays reserved null until M8.3. -->
- [x] Background process calls `evaluate_patron_alignment` on 15-30 minute heartbeat
  <!-- Evidence: test_patron_alignment_session.py exercises the real BackgroundProcess at 1199/1200 seconds, post-commit publication, pause/resume, transient rollback/retry, persisted re-entry/current patron, present-party filtering and host handoff. Decay remains hydration-only. -->
- [x] DB schema supports patron selection, favor tracking, and tier state (sprint patron-favor-mini)
  <!-- Evidence: The lead chose the existing players.data->'divine_favor' JSONB object over player_patron/patron_favor_state tables. patron stores selection; level/max store favor; get_patron_tier derives tier on reload. test_favor_tier_persistence.py verifies the committed round trip. -->
- [x] Tests cover favor accumulation, decay, tier transitions (up and down), and Unbound Path mechanics (sprint patron-favor-mini)
  <!-- Evidence: test_favor_tier_persistence.py covers upward, action-downward, and neglect-downward tier round trips with unchanged selection. test_displeasure_delivery.py limits loss whispers to tier drops. test_unbound_path.py covers the Unbound Path. -->

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

<!-- patron-abilities-on-hud (2026-11-17): test_patron_ability_events.py,
 test_patron_abilities.py, test_query_info_patron.py, both wire-contract suites,
 and the strict native patron-abilities.yaml flow pass. Standing derives from
 players.data.divine_favor; spend persists in players.data.patron_gifts. The
 historical patron_ability_unlock table is superseded; no unlock table is added.
 activate_patron_ability maps to registered activate(id=...); check_patron_tier
 maps to query_info(kind="patron"). Historical daily recharge is per_session.
 AC6 closed 2026-11-25 when the last pending ability became active. -->

- [x] All 10 patrons have abilities defined for all 3 tiers (Acknowledged, Devoted, Exalted)
- [x] Each ability has name, effect, and recharge condition specified
- [x] Recharge tracking prevents ability use before recharge completes (short rest / long rest / daily)
- [x] Ability unlock triggers automatically when favor tier advances
- [x] Higher-tier abilities become unavailable (not deleted) when favor drops below tier threshold
- [x] `activate_patron_ability` validates availability, applies effect, and sets recharge timer <!-- sprint-aelora-hearthfire (2026-11-25): every authored tier ability is active, either engine or narrated, and none is pending. Hearthfire (fixed 15 ft sanctuary, pre-outcome heal, ally save advantage, Fate-reachable WIS entry save) and Unravel Fate (round-start checkpoint rewind) closed the last two. test_gods_layers.py and god.test.ts both assert the pending set is empty. -->
- [x] `activate_patron_ability` returns error if ability is on cooldown or tier is insufficient
- [x] `check_patron_tier` returns current tier, favor value, and list of available abilities
- [x] Client receives patron ability data for character sheet and favor bar for HUD
- [x] Unbound Path players have no patron abilities (Unbound benefits come from M8.1 passives)
- [x] Tests cover ability activation, recharge, tier-up unlock, tier-down lockout, and Unbound exclusion

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
  - Veil Mastery passive (at Sovereign, the first Hollow Echo of a session becomes “Nothing stirs”; later Echoes apply normally)
  - No patron abilities — Unbound trades divine power for Resonance mastery
- DB migration: `archetype_synergy` table (archetype_id, patron_id, synergy_type, bonus)
- Rules engine: `get_archetype_synergy(archetype, patron)` returning synergy type and bonus
- Rules engine: `apply_unbound_resonance_push(player)` adding +3 Resonance with associated benefits
- Agent tool: `query_info(kind="patron")` returns the current archetype/patron synergy, including clause readiness

**Human decision (2026-11-18, sprint `unbound-self-reliance`):** Scope: “Veil Mastery follows the design doc.” The M8.3 effect below retains automatic first-Echo conversion once per session, gated behind Sovereign.

**Acceptance criteria:**
- [x] Synergy lookup covers all archetype x patron combinations (every archetype has entries for every patron)
  <!-- Evidence (sprint archetype-synergies): test_patron_synergy.py walks all 180 loaded pairs through get_archetype_synergy and registered query_info; god.test.ts validates all ten matrices against the eighteen-archetype roster. -->
- [x] Each pairing has exactly one synergy type assigned (Natural, Divine, or Unexpected)
  <!-- Evidence (sprint archetype-synergies): test_patron_synergy.py and god.test.ts validate the loaded matrix: 22 Natural, 62 Divine, 96 Unexpected rows, each with one type. -->
- [x] Natural synergies provide the largest mechanical bonus, Unexpected the most unique
  <!-- Evidence (sprint archetype-synergies): human approved the final 180-row review table on 2026-11-18 (table SHA-256 5dee713a…, content SHA-256 c3238a53…, commit 903ac541). test_patron_synergy.py requires a mechanical clause on every Natural row and keeps Natural rows to the design roster. -->
- [x] `get_archetype_synergy` returns correct synergy for any archetype/patron pair
  <!-- Evidence (sprint archetype-synergies): test_patron_synergy.py compares each of the 180 lookups and registered query responses to validated content; god.test.ts validates the shared catalog. -->
- [x] Layer 4 bonuses apply on top of existing Layer 1-3 mechanics without overriding them
  <!-- Evidence (sprint archetype-synergies): test_patron_synergy_engine.py covers Kaelen’s Layer 1 threshold composition, Aelora’s Bond adjustment and Syrath’s Layer 2 composition at live boundaries; test_patron_synergy_readiness.py keeps pending clauses unavailable. At that sprint close, 12 of 200 clauses were active/engine. Appointed Mercy now adds 1 HP to a Zhael cleric's spell healing for each ally who succeeded on a death save this round, exercised after checkpoint reload by test_patron_synergy_engine.py. War Songs upgrades a Kaelen bard’s Inspire die to d6 on attacks, including after exploration and Fate reloads, with d4 retained for saves and checks. See test_patron_synergy_engine.py and test_kaelen_war_songs.py. Syrath’s rogue, spy and whisper retain Shadow Veil through the first wrap. test_patron_synergy_engine.py and test_syrath_two_round_veil.py cover the countdown, immediate reveal, and combat-end cleanup. Veiled Strike adds 1d6 to the rogue’s Sneak Attack or the spy or whisper’s weapon hit. The engine scenarios and test_syrath_veiled_strike.py cover damage, critical hits, reveal and Fate’s Thread. Zhael’s marshal grants Moment to Rally once per fight through a settled order. The registered scenario exercises Interceding Order and the recipient’s next save. test_zhael_foretold_words.py and test_zhael_foretold_words_atomicity.py exercise the foretold DC and its settlement for Zhael bards and diplomats. Zhael’s oracle can spend Fate’s Thread twice per long rest. The engine scenario drives offers, spend receipts, the patron query and both rest types. test_zhael_fate_atomicity.py covers the last use across two sessions. -->
- [x] Unbound Path grants perfect Resonance visibility (exact value, not just tier)
  <!-- Evidence (sprint unbound-self-reliance): test_unbound_path.py::test_guest_discovery_uses_persisted_resonance_and_bypasses_gods invokes registered query_info for an Unbound guest and Kaelen follower: persisted exact current versus state only. -->
- [x] Unbound +3 Resonance push is voluntary and costs no action
  <!-- Evidence (sprint unbound-self-reliance): test_unbound_path.py::test_raw_channeling_preserves_action_and_reaction discovers and activates Raw Channeling, accepts the same-turn action, spends a resolver-offered reaction, and refuses reuse in the encounter. -->
- [x] At Sovereign, Veil Mastery automatically converts the first Hollow Echo of a session to “Nothing stirs”; later Echoes apply normally
  <!-- Evidence (sprint unbound-self-reliance): test_unbound_path.py::test_mastery_lifetime_natural_nothing_and_zero_generation and ::test_combat_cast_commits_mastery_for_declaring_member prove first-Echo conversion and subsequent effects; its concurrency and encounter-reset cases retain lifetime evidence. test_unbound_milestones.py::test_pre_sovereign_echo_is_real_for_acting_member proves the Sovereign gate. -->
- [x] Unbound Path has NO patron abilities — only Resonance mastery benefits
  <!-- Evidence (sprint unbound-self-reliance): test_unbound_path.py::test_unbound_refuses_all_patron_abilities refuses all 40 gods.json tier/gift IDs through registered activate with reason checks and unchanged player data; the registered query and test_unbound_milestones.py::test_discovery return empty abilities. -->
- [x] `query_info(kind="patron")` returns `synergy: null` for Unbound players (no patron synergy applicable)
  <!-- Evidence (sprint archetype-synergies): test_patron_synergy.py exercises the registered Unbound query response. Scope: reuse query_info and retain the strict-schema tool budget; the universal alone_bonus remains a separate field. -->
- [ ] All 10 patrons + Unbound Path are fully implemented and playable after this milestone
- [x] Tests cover synergy lookup for all combinations, Unbound mechanics, and Layer 4 bonus stacking
  <!-- Evidence (sprint unbound-self-reliance): test_patron_synergy.py covers all 180 lookups; test_patron_synergy_engine.py covers Layer 1–3 composition/stacking; test_unbound_alone_bonus.py covers alone checks; test_unbound_path.py and test_unbound_milestones.py cover registered commands, Echo lifetime and durable rewards. -->

**Review:** The human approved the final 180-row table on 2026-11-18 (table SHA-256 `5dee713a…`, content SHA-256 `c3238a53…`, commit `903ac541`), closing AC3. The approved table is retained in sprint DATA at `sprints/archetype-synergies/synergy-review.md` with every changed number. Content and design share the approved corrections, including Nythera’s live Animal Handling +1 instead of advantage. Pending clauses are unavailable.

Layer 4 lookup covers 180 pairings and 200 clauses. 84 are active/engine, 85 are active/narrated, and 31 are pending/engine.

Shared Table gives Aelora clerics +1 Religion when blessing a shared meal. Civic Promise gives Aelora paladins +1 Persuasion when negotiating a community’s shared duties. The patron query surfaces the context tags and settled checks name the applied clause.

Hearth Omen gives Aelora oracles +1 Insight when interpreting a household omen and stacks with Hearthkeeper’s Bond when an ally is present. Honest Hustle gives Aelora rogues +1 Persuasion on commerce skill and social checks. Better fence prices remain pending. Wild Covenant gives Thyra paladins +1 Religion when honoring a sacred grove. Seasonal Omen gives Thyra oracles +1 Nature when interpreting a seasonal omen.

Nythera’s Shoreline Keeper gives wardens +1 Survival to find shelter on unfamiliar coasts. Harbor Courtesy gives diplomats +1 Persuasion to seek peaceful passage through unfamiliar ports. Voyager’s Tools gives artificers +1 to any skill check to repair a vessel during a journey.

Orenthel’s Mender’s Dawn gives artificers +1 to any skill check to repair equipment for a damaged sanctuary. Green Morning gives wardens +1 Nature to restore a blighted grove. Reconciliation gives diplomats +1 Persuasion to negotiate care for wounded enemies. The registered engine scenarios exercise the bonuses and discover each tag through the patron query.

Valdris’s Ordered Testimony gives mages +1 Arcana for magical evidence of a broken oath. Honest Measure gives artificers +1 Investigation for tampered scales or measuring tools. Chain of Evidence gives seekers +1 Investigation to trace evidence ownership in a public hearing. Common Ground gives wardens +1 Survival to trace unlawful incursions into protected land. Fair Terms gives diplomats +1 Persuasion to secure equal terms for opposing petitioners. Truth in Disguise gives rogues and spies +1 Deception for just causes on both skill and social checks.

The registered engine scenarios in `test_patron_synergy_engine.py` exercise all seven Valdris clauses through `check` and verify the tags in `query_info(kind="patron")`. `test_synergy_context_guards.py` covers unheld tags and wrong skills.

Sheltering Light gives a standing Orenthel guardian +1 AC against attack rolls while a standing ally below half HP is within 5 feet. `test_patron_synergy_engine.py` and `test_orenthel_guardian_ward.py` exercise the registered clause, opportunity attacks and held rolls after checkpoint reload. Dawnward Strike adds 1 damage on a hit against a Hollow or undead foe while another standing party ally in the same combat is below half HP. `test_orenthel_undead_wrath.py` and `test_orenthel_undead_wrath_guards.py` cover damage, attack receipts and eligibility after checkpoint reload.

Absolute Authority raises the Turn Undead/Hollow save DC by 1 for Valdris clerics and oracles. The patron query lists the active clause, and the cast receipt names the bonus. The registered engine scenarios compare both classes under Valdris and Thyra. `test_turn_undead_hollow.py` covers undead and Hollow saves after checkpoint reload, `test_turn_undead_hollow_guards.py` covers Sacred Flame at its usual DC, and `god-synergy.test.ts` validates both shipped clauses.

Saltwind Casting gives Nythera mages +1 to spell attack rolls on their first stay at a Sunward Coast location. The cast receipt names the bonus. `test_nythera_unseen_coast.py` covers eligibility and Fate’s Thread continuation after checkpoint reload.

**Key references:**
- *Game Mechanics Patrons — Archetype Synergies*
- *Game Mechanics Patrons — Synergy Categories (Natural, Divine, Unexpected)*
- *Game Mechanics Patrons — Unbound Path Full Specification*
