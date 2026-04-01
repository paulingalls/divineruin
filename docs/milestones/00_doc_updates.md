# Phase 0: Documentation Updates

> Source doc: `docs/game_mechanics/economy_reconciliation.md`

Fixes identified during economy reconciliation that must land before implementation milestones begin. These are doc-only changes — no code.

---

### Milestone 0.1 — Documentation Reconciliation

**Goal:** Align existing design docs with the canonical economy model so implementation milestones build on a consistent foundation.

**Inputs:** Existing codebase docs (`game_design_doc.md`, crafting docs, combat docs, `economy_reconciliation.md`).

**Deliverables:**
- Updated crafting and combat docs with corrected currency notation (gp → gc) in 4 locations: Half Plate, Plate, Revivify diamond, Resurrection diamond
- Updated GDD economy section with correct conversion ratio: 1 gc = 10 sp (not 100 sp)
- Adopted economic anchor stated in all relevant docs: 1 sp = 1 day's unskilled labor
- New canonical price reference table added to docs (covering weapons, armor, food, services, workspaces, spell components)

**Acceptance criteria:**
- [ ] Zero instances of "gp" remain in crafting and combat docs — all replaced with "gc"
- [ ] GDD economy section states 1 gc = 10 sp
- [ ] Economic anchor (1 sp = 1 day unskilled labor) is stated in the GDD economy section
- [ ] Canonical price reference table exists in docs with at least 14 item categories
- [ ] No contradictory currency ratios remain across docs

**Key references:**
- *Economy Reconciliation Doc — Currency Notation Fixes*
- *Economy Reconciliation Doc — Conversion Ratio Correction*
- *Economy Reconciliation Doc — Price Reference Table*
