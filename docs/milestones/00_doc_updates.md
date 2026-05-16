# Phase 0: Documentation Updates

> Source docs: `docs/game_mechanics/game_mechanics_economy.md`, `docs/game_mechanics/game_mechanics_decisions.md`

Bring all project documentation in sync with the 10 new game mechanics docs before any implementation work begins. Fix stale references, add missing indexes, correct economy inconsistencies, and ensure the knowledge system points to the right sources.

---

### Milestone 0.1 — CLAUDE.md Knowledge System Overhaul

**Goal:** Update CLAUDE.md so the knowledge system accurately reflects the current doc structure, including the new game_mechanics/ directory as the canonical mechanics reference.

**Inputs:** Existing CLAUDE.md, 10 new docs in `docs/game_mechanics/`.

**Deliverables:**
- Knowledge System Tier 1 updated: either create the referenced memory digests (`memory/game-mechanics.md`, `memory/dm-agent-spec.md`, etc.) or remove phantom references to files that don't exist
- Knowledge System Tier 3 updated: add `game_mechanics/` docs to the Key docs list with brief descriptions
- Add a new row to the Tier 1 table or a new subsection for the game_mechanics/ directory as the canonical source for deep mechanics
- Update `memory/doc-navigator.md` reference (file doesn't exist) — either create it or remove the reference
- Verify all file paths referenced in CLAUDE.md actually exist

**Acceptance criteria:**
- [x] Every file path referenced in CLAUDE.md exists on disk <!-- evidence: docs/INDEX.md, docs/cost_model.md, docs/technical_architecture.md, docs/world_data_simulation.md, docs/milestones/README.md, .env.example all present; no memory/* refs -->
- [ ] `game_mechanics/` docs are listed in the Key docs or Knowledge System section <!-- see audit/phase-0.md#m0.1 — game_mechanics docs reachable only transitively via INDEX.md, not listed in CLAUDE.md Knowledge System section -->
- [x] No phantom references to non-existent memory digest files <!-- evidence: grep memory/ in CLAUDE.md returns zero hits -->
- [x] Knowledge System tiers accurately reflect the doc hierarchy: CLAUDE.md → INDEX.md → docs/ and game_mechanics/ <!-- evidence: CLAUDE.md L7-9 "Always start at docs/INDEX.md" -->

**Key references:**
- *Current CLAUDE.md — Knowledge System section (lines 8-35)*
- *All 10 docs in `docs/game_mechanics/`*

---

### Milestone 0.2 — INDEX.md: Game Mechanics Section Indexes

**Goal:** Add section-level indexes for all 10 game mechanics docs to INDEX.md so developers can jump to specific sections without reading entire files.

**Inputs:** 10 docs in `docs/game_mechanics/`, existing `docs/INDEX.md`.

**Deliverables:**
- Section index entries for each game mechanics doc following the existing INDEX.md format (table with Section, Lines, What's There)
- Docs to index: `game_mechanics_core.md`, `game_mechanics_combat.md`, `game_mechanics_archetypes.md`, `game_mechanics_magic.md`, `game_mechanics_crafting.md`, `game_mechanics_npcs.md`, `game_mechanics_bestiary.md`, `game_mechanics_patrons.md`, `game_mechanics_decisions.md`, `game_mechanics_economy.md`
- Add `agent_handoffs_and_scenes.md` to INDEX.md if not already present

**Acceptance criteria:**
- [x] All 10 game mechanics docs have section indexes in INDEX.md <!-- evidence: INDEX.md L300-485 covers all 10 (plus encounter_roles as bonus) -->
- [ ] Each index entry has accurate line ranges (verified against actual file content) <!-- see audit/phase-0.md#m0.2 — 9/10 docs match within 1 line; game_mechanics_archetypes.md ranges are ~133 lines low (file is 1357 lines, INDEX claims 1224) -->
- [x] Index entries follow the existing format: `## filename.md (~N lines)` with description and table <!-- evidence: spot-checked at INDEX.md:300,325,343,466 -->
- [x] `agent_handoffs_and_scenes.md` is indexed <!-- evidence: INDEX.md:278 -->

**Key references:**
- *Existing INDEX.md format (any existing entry as template)*
- *Each game mechanics doc (read for section boundaries)*

---

### Milestone 0.3 — Economy Reconciliation Fixes

**Goal:** Apply the currency and pricing fixes identified in `game_mechanics_economy.md` to existing design docs so all docs use consistent currency notation and ratios.

**Inputs:** `docs/game_mechanics/game_mechanics_economy.md`, existing `game_design_doc.md` and other docs.

**Deliverables:**
- Fix currency notation: change all instances of "gp" to "gc" across all docs (game_mechanics_economy.md identifies 4 specific locations: Half Plate, Plate, Revivify diamond, Resurrection diamond)
- Update GDD economy section: 1 gc = 10 sp (not 100 sp as currently stated)
- Adopt economic anchor: state "1 sp = 1 day's unskilled labor" in the GDD economy section
- Add canonical price reference table to the GDD economy section or as a standalone reference

**Acceptance criteria:**
- [ ] Zero instances of "gp" remain across all docs — all replaced with "gc" <!-- see audit/phase-0.md#m0.3 — 3 unintended gp refs remain: game_mechanics_magic.md:423,432 (Revivify/Resurrection diamond components, explicitly named M0.3 targets) and economy/game_mechanics_p2p_trade.md:160 -->
- [x] GDD economy section states 1 gc = 10 sp <!-- evidence: game_design_doc.md:1065 -->
- [x] Economic anchor (1 sp = 1 day unskilled labor) is stated in the GDD <!-- evidence: game_design_doc.md:1053,1065 -->
- [x] Canonical price reference table exists with at least 14 item categories <!-- evidence: game_mechanics_economy.md §§Canonical Price Tables → Currency Drops from Combat (14 categories) -->
- [ ] No contradictory currency ratios remain across docs <!-- see audit/phase-0.md#m0.3 — ratio (1 gc = 10 sp) consistent everywhere, but surviving gp refs in magic_doc create a soft notation contradiction -->

**Key references:**
- *Economy Reconciliation Doc — Currency Notation Fixes*
- *Economy Reconciliation Doc — Conversion Ratio Correction*
- *Economy Reconciliation Doc — Price Validation section*

---

### Milestone 0.4 — Cross-Reference Updates

**Goal:** Add cross-references from existing docs to the new game_mechanics/ docs so readers know where to find detailed specifications. The game_mechanics/ docs are now the canonical source for deep mechanics — existing doc sections should point there.

**Inputs:** Existing docs (`game_design_doc.md`, `technical_architecture.md`, `world_data_simulation.md`, `mvp_spec.md`), new `game_mechanics/` docs.

**Deliverables:**
- `game_design_doc.md`: Add cross-reference notes in Game Mechanics (line ~241), Combat Design (line ~435), NPC Design (line ~543), Asynchronous Play (line ~700), Economy (line ~1038), Death and Resurrection (line ~1084) sections pointing to the detailed game_mechanics/ equivalents
- `technical_architecture.md`: Add cross-reference in Game Engine Layer (line ~1038) pointing to game_mechanics/ for rules engine specifications
- `world_data_simulation.md`: Add cross-reference in Content Authoring Format and NPC Schema sections to `game_mechanics_npcs.md` and `game_mechanics_bestiary.md` for expanded schemas
- `mvp_spec.md`: Add cross-reference to `game_mechanics/` for detailed system specs behind MVP entities
- Format: brief note at the top of each section, e.g., "> For detailed mechanics, see `game_mechanics/game_mechanics_combat.md`"

**Acceptance criteria:**
- [x] GDD Game Mechanics section references `game_mechanics_core.md` <!-- evidence: game_design_doc.md:248 -->
- [x] GDD Combat section references `game_mechanics_combat.md` <!-- evidence: game_design_doc.md:444 -->
- [x] GDD NPC section references `game_mechanics_npcs.md` <!-- evidence: game_design_doc.md:625 -->
- [x] GDD Async section references `game_mechanics_crafting.md` and `game_mechanics_core.md` (training) <!-- evidence: game_design_doc.md:873 -->
- [x] GDD Economy section references `game_mechanics_economy.md` <!-- evidence: game_design_doc.md:1053 -->
- [x] GDD Death section references `game_mechanics_combat.md` (death system) <!-- evidence: game_design_doc.md:1101 -->
- [x] Technical architecture Game Engine section references `game_mechanics/` <!-- evidence: technical_architecture.md:1040 -->
- [x] World data NPC/content schemas reference `game_mechanics_npcs.md` and `game_mechanics_bestiary.md` <!-- evidence: world_data_simulation.md:13; bonus mvp_spec.md:28 -->
- [x] Cross-references use consistent format across all docs <!-- evidence: all 7 banners use `> **Detailed specification(s):** See …` pattern -->
- [ ] No existing content is deleted — only cross-reference notes added <!-- see audit/phase-0.md#m0.4 — cannot verify positively without pre-M0.4 baseline; spot-checked sections retain original prose -->

**Key references:**
- *Game Design Doc — all mechanical sections*
- *Technical Architecture — Game Engine Layer*
- *World Data & Simulation — Content Authoring, NPC Schema*
- *All 10 game mechanics docs (for mapping sections to detailed equivalents)*
