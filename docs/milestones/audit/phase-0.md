# Phase 0 Audit — Doc Updates

Sprint-001 / Milestone 1. Read-only audit of 23 acceptance items in `docs/milestones/00_doc_updates.md` (M0.1–M0.4).

## Summary

| Phase | Confirmed | Aspirational | Unverified |
| --- | --- | --- | --- |
| M0.1 | 3 | 1 | 0 |
| M0.2 | 3 | 1 | 0 |
| M0.3 | 3 | 2 | 0 |
| M0.4 | 9 | 0 | 1 |
| **Total** | **18** | **4** | **1** |

Two material gaps surfaced:

1. **Two stale `gp` references remain** in `docs/game_mechanics/game_mechanics_magic.md` (Revivify and Resurrection diamond components, lines 423 and 432). The M0.3 currency reconciliation deliverable explicitly names "Revivify diamond, Resurrection diamond" as targets; the magic doc was missed.
2. **INDEX.md line ranges for `game_mechanics_archetypes.md` are wrong** for the four sections after "Archetype Profiles" — every range is ~133 lines low. The file is 1357 lines; INDEX claims 1224.

## M0.1 — CLAUDE.md Knowledge System Overhaul

| Item | Evidence | Status |
| --- | --- | --- |
| Every file path referenced in CLAUDE.md exists on disk | `docs/INDEX.md`, `docs/cost_model.md`, `docs/technical_architecture.md`, `docs/world_data_simulation.md`, `docs/milestones/README.md`, `.env.example` — all present (verified via `ls`). No `memory/*` paths referenced. | confirmed |
| `game_mechanics/` docs are listed in the Key docs or Knowledge System section | CLAUDE.md contains zero matches for `game_mechanics` (grep). The Knowledge System section (lines 7-9) was simplified to a single pointer at `docs/INDEX.md`, and INDEX.md does list all 10 game_mechanics docs (lines 294-589). Reachable transitively, but not "listed in the Key docs or Knowledge System section" of CLAUDE.md itself. | aspirational |
| No phantom references to non-existent memory digest files | grep for `memory/` in CLAUDE.md returns zero matches. Phantom `memory/game-mechanics.md`, `memory/dm-agent-spec.md`, `memory/doc-navigator.md` references all removed. | confirmed |
| Knowledge System tiers accurately reflect the doc hierarchy: CLAUDE.md → INDEX.md → docs/ and game_mechanics/ | CLAUDE.md §Knowledge System (lines 7-9) states "Always start at `docs/INDEX.md`." INDEX.md lists every doc under `docs/` and `docs/game_mechanics/`. The tiered table from the previous structure was replaced by this pointer — hierarchy is consistent with the new shape. | confirmed |

## M0.2 — INDEX.md: Game Mechanics Section Indexes

| Item | Evidence | Status |
| --- | --- | --- |
| All 10 game mechanics docs have section indexes in INDEX.md | `docs/INDEX.md` lines 300-485 cover `game_mechanics_core.md`, `_combat.md`, `_archetypes.md`, `_magic.md`, `_crafting.md`, `_npcs.md`, `_bestiary.md`, `_patrons.md`, `_decisions.md`, `_economy.md`. All 10 indexed, plus `game_mechanics_encounter_roles.md` (bonus). | confirmed |
| Each index entry has accurate line ranges (verified against actual file content) | Verified `^## ` headings against INDEX ranges for all 10 docs. **9/10 match** within 1 line. `game_mechanics_archetypes.md` is wrong: INDEX claims 1224 total lines (actual 1357); "All Archetype Profiles" 417-1014 (actual 417-1148); "Core + Elective Ability Model" 1016-1087 (actual 1149-1221); "Spell Acquisition — Three Tracks" 1089-1152 (actual 1222-1286, and heading is "Spell Acquisition System — Three Tracks"); "Martial Mentor-Style System" 1154-end (actual 1287-end). | aspirational |
| Index entries follow the existing format: `## filename.md (~N lines)` with description and table | Spot-checked entries at INDEX.md:300, :325, :343, :466 — all use `## game_mechanics_X.md (N lines)` + description + `\| Section \| Lines \| What's There \|` table. Consistent with existing format (see :26, :53). | confirmed |
| `agent_handoffs_and_scenes.md` is indexed | `docs/INDEX.md` line 278: `## agent_handoffs_and_scenes.md (923 lines)` with section table at 282-290. | confirmed |

Side note: the index entry's declared 923-line size and end-anchored ranges were not independently re-measured here (the doc itself is outside this story's scope — story-005 owns the H.* milestones).

## M0.3 — Economy Reconciliation Fixes

| Item | Evidence | Status |
| --- | --- | --- |
| Zero instances of "gp" remain across all docs — all replaced with "gc" | `grep -rn '\bgp\b' docs/` returns 6 hits, 3 of which are unintended: `game_mechanics_magic.md:423` ("diamond (50 gp, consumed)") and `:432` ("Diamond (500 gp, consumed)") — both Revivify/Resurrection spell-component prices, explicitly named in the M0.3 deliverable as targets. Plus `economy/game_mechanics_p2p_trade.md:160` ("thousands of gp/hour" — casual rate language). The remaining 3 hits are intentional: `game_mechanics_economy.md:34` (explicit "'gp' does not exist"), `00_doc_updates.md:64,70` (the milestone description itself), and `game_mechanics_decisions.md:185` (Decision 72 historical note). | aspirational |
| GDD economy section states 1 gc = 10 sp | `docs/game_design_doc.md:1065`: "Gold crowns (gc) — 1 gc = 10 sp." | confirmed |
| Economic anchor (1 sp = 1 day unskilled labor) is stated in the GDD | `docs/game_design_doc.md:1065`: "Economic anchor: 1 sp = 1 day's unskilled labor (see `game_mechanics/game_mechanics_economy.md`)." Also at GDD:1053 in the cross-ref banner. | confirmed |
| Canonical price reference table exists with at least 14 item categories | `docs/game_mechanics/game_mechanics_economy.md` §§Canonical Price Tables through Currency Drops from Combat (lines 49-end) covers: Food & Lodging, Weapons, Armor, Adventuring Gear, Spell Components, NPC Services, Workspace Rental, Crafting Commissions, Mentor Training Fees, Starting Gold, Merchant Pricing Formula, Quest Reward Tiers, Hollow Material Values, Currency Drops from Combat = 14 categories. Deliverable says "in the GDD economy section or as a standalone reference"; this is the standalone reference. | confirmed |
| No contradictory currency ratios remain across docs | `grep -n '1 gold = 100 silver\|100 sp\|1 gc = 100' docs/` finds no "1 gold = 100 silver" or "1 gc = 100 sp" claims. "1 gc = 10 sp" appears in `INDEX.md`, `game_design_doc.md`, `game_mechanics_economy.md`, `game_mechanics_decisions.md` consistently. BUT: the surviving `gp` references in `game_mechanics_magic.md:423,432` quote diamond prices in a denomination the rest of the docs explicitly say does not exist — a soft contradiction in notation if not in ratio. | aspirational |

## M0.4 — Cross-Reference Updates

| Item | Evidence | Status |
| --- | --- | --- |
| GDD Game Mechanics section references `game_mechanics_core.md` | `docs/game_design_doc.md:248`: "> **Detailed specification:** See [game_mechanics_core.md](game_mechanics/game_mechanics_core.md) for the full rules engine spec…" | confirmed |
| GDD Combat section references `game_mechanics_combat.md` | `docs/game_design_doc.md:444`: "> **Detailed specification:** See [game_mechanics_combat.md](game_mechanics/game_mechanics_combat.md) for phase-based combat…" | confirmed |
| GDD NPC section references `game_mechanics_npcs.md` | `docs/game_design_doc.md:625`: "> **Detailed specification:** See [game_mechanics_npcs.md](game_mechanics/game_mechanics_npcs.md) for NPC stat blocks…" | confirmed |
| GDD Async section references `game_mechanics_crafting.md` and `game_mechanics_core.md` (training) | `docs/game_design_doc.md:873`: "> **Detailed specification:** See [game_mechanics_core.md](game_mechanics/game_mechanics_core.md) (Async Training, Companion Errands) and [game_mechanics_crafting.md](game_mechanics/game_mechanics_crafting.md) (Async Crafting)…" | confirmed |
| GDD Economy section references `game_mechanics_economy.md` | `docs/game_design_doc.md:1053`: "> **Detailed specification:** See [game_mechanics_economy.md](game_mechanics/game_mechanics_economy.md) for the full price audit…" | confirmed |
| GDD Death section references `game_mechanics_combat.md` (death system) | `docs/game_design_doc.md:1101`: "> **Detailed specification:** See [game_mechanics_combat.md](game_mechanics/game_mechanics_combat.md) — Death and Dying section…" | confirmed |
| Technical architecture Game Engine section references `game_mechanics/` | `docs/technical_architecture.md:1040`: "> **Detailed specification:** See `docs/game_mechanics/` for full rules engine specs — core resolution, combat, archetypes, magic, crafting, NPCs, bestiary, patrons, and economy." | confirmed |
| World data NPC/content schemas reference `game_mechanics_npcs.md` and `game_mechanics_bestiary.md` | `docs/world_data_simulation.md:13`: "> **Detailed specifications:** See [game_mechanics_npcs.md](game_mechanics/game_mechanics_npcs.md)… See [game_mechanics_bestiary.md](game_mechanics/game_mechanics_bestiary.md) for creature stat blocks and loot tables." (Bonus: `mvp_spec.md:28` references `docs/game_mechanics/` for MVP entities.) | confirmed |
| Cross-references use consistent format across all docs | All seven cross-ref banners (GDD:248, :444, :625, :873, :1053, :1101; tech-arch:1040; world-data:13; mvp_spec:28) use the leading `> **Detailed specification(s):** See …` pattern. Consistent. | confirmed |
| No existing content is deleted — only cross-reference notes added | Cannot verify positively without diffing against the pre-M0.4 baseline; the GDD section bodies (Game Mechanics, Combat, NPC, Async, Economy, Death) remain populated with their original prose immediately below the new banner. No signs of deletion at the spot-checked sections. | unverified |
