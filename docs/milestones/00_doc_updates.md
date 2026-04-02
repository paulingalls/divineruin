# Phase 0: Documentation Updates

> Source docs: `docs/game_mechanics/economy_reconciliation.md`, `docs/game_mechanics/game_mechanics_decisions.md`

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
- [x] Every file path referenced in CLAUDE.md exists on disk
- [x] `game_mechanics/` docs are listed in the Key docs or Knowledge System section
- [x] No phantom references to non-existent memory digest files
- [x] Knowledge System tiers accurately reflect the doc hierarchy: CLAUDE.md → INDEX.md → docs/ and game_mechanics/

**Key references:**
- *Current CLAUDE.md — Knowledge System section (lines 8-35)*
- *All 10 docs in `docs/game_mechanics/`*

---

### Milestone 0.2 — INDEX.md: Game Mechanics Section Indexes

**Goal:** Add section-level indexes for all 10 game mechanics docs to INDEX.md so developers can jump to specific sections without reading entire files.

**Inputs:** 10 docs in `docs/game_mechanics/`, existing `docs/INDEX.md`.

**Deliverables:**
- Section index entries for each game mechanics doc following the existing INDEX.md format (table with Section, Lines, What's There)
- Docs to index: `game_mechanics_core.md`, `game_mechanics_combat.md`, `game_mechanics_archetypes.md`, `game_mechanics_magic.md`, `game_mechanics_crafting.md`, `game_mechanics_npcs.md`, `game_mechanics_bestiary.md`, `game_mechanics_patrons.md`, `game_mechanics_decisions.md`, `economy_reconciliation.md`
- Add `agent_handoffs_and_scenes.md` to INDEX.md if not already present

**Acceptance criteria:**
- [x] All 10 game mechanics docs have section indexes in INDEX.md
- [x] Each index entry has accurate line ranges (verified against actual file content)
- [x] Index entries follow the existing format: `## filename.md (~N lines)` with description and table
- [x] `agent_handoffs_and_scenes.md` is indexed

**Key references:**
- *Existing INDEX.md format (any existing entry as template)*
- *Each game mechanics doc (read for section boundaries)*

---

### Milestone 0.3 — Economy Reconciliation Fixes

**Goal:** Apply the currency and pricing fixes identified in `economy_reconciliation.md` to existing design docs so all docs use consistent currency notation and ratios.

**Inputs:** `docs/game_mechanics/economy_reconciliation.md`, existing `game_design_doc.md` and other docs.

**Deliverables:**
- Fix currency notation: change all instances of "gp" to "gc" across all docs (economy_reconciliation.md identifies 4 specific locations: Half Plate, Plate, Revivify diamond, Resurrection diamond)
- Update GDD economy section: 1 gc = 10 sp (not 100 sp as currently stated)
- Adopt economic anchor: state "1 sp = 1 day's unskilled labor" in the GDD economy section
- Add canonical price reference table to the GDD economy section or as a standalone reference

**Acceptance criteria:**
- [x] Zero instances of "gp" remain across all docs — all replaced with "gc"
- [x] GDD economy section states 1 gc = 10 sp
- [x] Economic anchor (1 sp = 1 day unskilled labor) is stated in the GDD
- [x] Canonical price reference table exists with at least 14 item categories
- [x] No contradictory currency ratios remain across docs

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
- [x] GDD Game Mechanics section references `game_mechanics_core.md`
- [x] GDD Combat section references `game_mechanics_combat.md`
- [x] GDD NPC section references `game_mechanics_npcs.md`
- [x] GDD Async section references `game_mechanics_crafting.md` and `game_mechanics_core.md` (training)
- [x] GDD Economy section references `economy_reconciliation.md`
- [x] GDD Death section references `game_mechanics_combat.md` (death system)
- [x] Technical architecture Game Engine section references `game_mechanics/`
- [x] World data NPC/content schemas reference `game_mechanics_npcs.md` and `game_mechanics_bestiary.md`
- [x] Cross-references use consistent format across all docs
- [x] No existing content is deleted — only cross-reference notes added

**Key references:**
- *Game Design Doc — all mechanical sections*
- *Technical Architecture — Game Engine Layer*
- *World Data & Simulation — Content Authoring, NPC Schema*
- *All 10 game mechanics docs (for mapping sections to detailed equivalents)*
