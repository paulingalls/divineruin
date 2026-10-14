# What Remains

Reconciled against the codebase on **2026-10-13**, during **Sprint 68**
(story-158). Counts come from the phase-doc checkboxes; behavioral evidence and
its limits are recorded in the story handback. Checked criteria are not a claim
that every designed effect has shipped.

**Position: 331 / 538 acceptance criteria — 62%** (the sum of the per-phase
counts in `README.md`). **207 criteria remain unchecked.** Phases 1, 2, 4, 5,
6 and 10 have all recorded criteria checked. Phase 3 is still Partial at 34/34:
casting infrastructure is exercised, but complete deterministic spell-effect
coverage is **unverified**. All 87 spell rows carry textual `mechanics`; this
refresh does not classify every effect's execution path.

M7.3 remains partial: Still, Architect and remaining troop/Tier-3 effects are
open in the phase doc. Deterministic catalog/encounter and Choir checks do not
certify those outstanding effects or complete native audio.

**TODO: complete native Choir audio acceptance.** The saved manifest for
`mus2471i-cbb68570` records entry, cast-aura, aura-break, search, redirect,
silence, refusal and silenced-command completed, then human interruption. It
explicitly records an incomplete run and deferred matched SFX validation.
The artifacts are in story DATA's
`reports/story-146-native-partial-mus2471i-cbb68570/`.

Current-source native completion and matched SFX deactivation fault validation
under identical normal-capture settings remain **unverified**. A new run needs
separate human approval. The full sequence, including deafened,
deafened-command, expiry, destruction and replay, and dropped-gameplay, bypassed-receiver, skipped-encounter, withheld-input,
DM-tone and unrelated-burst native faults remain certification work. Deterministic transport/mechanics checks do not
establish native capture or paid speech-recognition quality.

---

## 1. Shipped substrate relevant to the remaining work

- **Phase 1 is 43/43.** The real HTTP/DB Artificer-slot acceptance exercised
  borrowing the training slot with a Portable Lab and refusing follow-on
  training. ADR 0005 records the exception as fulfilled and debt
  `95de7fa141df` as discharged.
- **Phase 8's Resonance prerequisite is available.** Resonance, Hollow Echo
  and scoped Veil Ward behavior pass their existing acceptance boundaries.
  This makes Phase 8 startable on that dependency; it does not complete its
  patron layers.
- **M24's scoped ward model is exercised.** Party-wide casting effects,
  encounter lifetime, round expiry, real-time anchor expiry and removal of
  legacy player ward state pass. README's dagger distinguishes this shipped
  substrate and Phase 10 terrain gates from Phase 11 world wards.
- **Phase 9 remains 5/80.** Recheck its original criteria before planning;
  pricing, reputation and inventory substrate is not a complete economy.

## 2. Residual inside the documentation phase (1 AC)

| Phase | Residual | Status |
|---|---|---|
| 0 | `game_mechanics/` in CLAUDE.md's Key docs / Knowledge System listing | Open decision: CLAUDE.md points to INDEX.md rather than providing the criterion's explicit listing. The criterion is unchanged. |

M0.2's accurate-index-ranges box is closed by regenerating INDEX.md and running
the real `scripts/doc_index.py` CLI. That certifies the current snapshot;
automatic enforcement remains absent.

**Reaction mechanics are exercised:** an activation is an INTERRUPT against an
open reaction window; the reaction-window census and activation boundary check
its triggers and legal IDs. This does not certify natural spoken Beat-3 pauses.

## 3. World-loop gaps and bounded evidence

- **Sacred-site ward producer:** the production caller inventory finds the
  `sacred_site` source definition and migration contract, but no producer of
  that source. Crafted permanent anchors retain `artificer` provenance.
- **Node respawn:** `compute_node_respawn` has no production call site in the
  scoped inventory. Its definition and a persistence docstring are present.
- **World time:** constructing `SessionData` yields `world_time="evening"`;
  the production inventory finds no assignment advancing it. Existing scene
  tests exercise supplied day/night values. Time-conditioned scene and ambient
  consumers exist; a running world clock and complete Layer-1 behavior are
  **unverified**, not established by those consumer tests.
- **Redis is used:** `db.py` cache read/write paths call `get_redis`; the real
  Valkey acceptance read passed.
- **Events:** the inventory finds a `world_events_log` read in `world_news.py`,
  but no seeded `events` table reader or trigger evaluator. The worker reset
  harness exercises activity recovery, and world-effect tests exercise direct
  quest effects; neither proves a world tick or scheduled event evaluation.
  Those runtime capabilities remain **unverified**.
- **Patron placeholders:**
  `test_patron_roster_consistency.py::test_layer_2_through_4_placeholders_exist_and_are_null`
  reserves Layers 2–4. All ten Layer-1 gifts are objects. When implementing
  later layers, revise the obsolete placeholder assertion and retain the
  roster checks.

## 4. Documentation decisions still open

Three original artifact-name discrepancies remain unresolved: `spell_catalog` versus `spells`,
`character_conditions` versus `players.data->'conditions'`, and death/travel
tables versus JSONB backfills. Existing implementations do not authorize
rewriting those criteria.

The M4.7/M4.8 capstones exercise encounter roles and beneficial conditions;
Phase 4 records 73/73. Beat-3 natural narration pauses remain unverified here.
Phase 7 retains the M7.4 `build_encounter` signature decision and its unchecked
75%-companion assumption; the recorded D-4 companion factors must be reconciled
there.

The story-111 retired-tool-name guard was deleted in `cb5dd18e`; it no longer
protects milestone prose. Historical repair narratives are omitted from this
current work map; the handback records their disposition.

## 5. Incomplete implementation phases (30 milestones, 206 open ACs)

The AC column counts **unchecked** criteria. Estimates are planning judgments,
not schedules or measured implementation costs.

| Phase | Milestones | Open ACs | Dependencies / decisions | Size estimate | Exercised or inventoried substrate |
|---|---|---|---|---|---|
| **7 · Bestiary** | 7.1–7.4 | 19 | M7.4 signature and companion assumptions | ~2 sprints | Roles/budgets/loot exercised through combat; 36 catalog rows, 11 catalog-backed encounter templates referencing 14 distinct species; seeded/queryable catalog and Python/TypeScript contracts. Generated composition and the remaining M7.3 effects remain open. |
| **8 · Patrons** | 8.1–8.3 | 32 | Phase 2 archetype detail for M8.3; original schema criteria remain open | ~2–3 sprints | Ten authored Layer-1 gifts; Layers 2–4 null. Favor action recording, standing/query and decay checks pass; XP/favor Resolve and client favor-event handling are exercised. Complete gift-effect coverage is not certified here. |
| **9 · Economy** | 9.1–9.10 | 75 | Phase 7 material/creature integration; Phase 5/6 inputs | large | Shared pricing getters/repair costs, reputation-to-stance and committed material inventory boundaries pass. The migrated pricing table exists. No complete economy certification is implied. |
| **11 · World Loop** | 11.1–11.6 | 46 | D-A–D-E; M11.4 needs Phase 9, M11.6 needs Phase 8 | ~4–6 sprints | Migrated `region_state`, `npc_state`, `world_events_log`, `god_agent_state`, `world_flags`; direct quest world effects; activity-worker reset harness. These do not establish a world scheduler or cascade. |
| **12 · Story Content** | 12.1–12.7 | 34 | Phase 11 and its blocking decision section | ~5–7 sprints | Migrated `scenes` (013) and `story_moments` (012); scene-tool and settlement-generation boundaries. `gods.json` has authored secret-agenda text for Veythar and Syrath; a season director is not certified. |

**Hazards before the relevant phase opens:**

- **Phase 7 — creature tiers are authored:** the four bestiary player bands
  are mirrored in Python and TypeScript. Encounter budget's five player bands
  are a separate difficulty calculation.
- **Phase 10 — navigation and physical terrain are distinct.** Travel uses
  optional `navigation`; all **23 locations** carry required closed-enum
  `terrain`, checked against `region_type` at seed time and server startup.
  Terrain magic and combat caching are shipped; dynamic corruption remains
  a Phase 11 boundary.
- **Phase 12 — vocabulary:** reconcile its proposed director beats with the
  existing scenes/`beats[]` vocabulary before implementation.
- **Materials:** none of the 97 `materials_catalog.json` rows has a value or
  price field. This does not say that item pricing is absent.
- **Phases 11 and 12** retain blocking design-decision sections. Treat their
  proposals as decisions to resolve, not approved implementation choices.

## 6. Recommended phase order

**Recommendation: Phase 7, then Phase 8, with Phase 9 after its upstream
integration work.** Both 7 and 8 can start on their shipped prerequisites;
remaining decisions and criteria still constrain their scope. Phase 7 supplies
creature/material integration for Economy. Phase 8 builds on working favor and
Resonance substrate and needs archetype detail for its synergy milestone.
No new-verb count is assumed: the existing fixed verb vocabulary and ADR 0004
budget govern any implementation.

**Recorded disagreement:** the earlier Phase-10/11/12 audit recommended Phase
10 first to repair live terrain defects. This recommendation keeps Phase 7
first on Economy-unblocking grounds. Phase 10 is now 17/17 with terrain magic
and combat caching exercised, so that earlier repair premise is superseded.
This is planning judgment, not a newly scheduled phase.

## 7. Standing documentation risks

- **INDEX ranges drift silently:** no hook, CI job or package script runs
  `doc_index.py`. Story-157's `8929fcdf` changed the bootstrap brief and left
  the index stale. Run the real CLI after documentation edits; no generator
  meta-test is retained.
- **Checkboxes need reconciliation:** CLAUDE.md Dev Flow step 7 calls for
  milestone updates, but checking a box still requires the complete original
  criterion and executed evidence.
- **Tool-name prose has no retired-name guard:** renames require a scoped
  documentation inventory; the deleted story-111 guard cannot be credited.

## 8. Evidence and criterion caveats

Paid approval was empty for all selected runs. Native completion, paid speech
recognition, exhaustive spell/gift effects and world-loop scheduling remain
unverified. The handback lists each original claim's disposition and exact
commands, including reused planner evidence on unchanged inputs.

D-4/D-5 are already recorded in Phase 6: Sable is the non-verbal shadow-fox;
Lira has the arcane kit. HP scales at 0.50 for Sable and 0.75 for Kael/Lira/Tam.
Their older "pending decisions" caveat is removed.

**M6.1 lead reading (2026-10-13): "where applicable"; keep the box checked.**
There are 19 role rows, exceeding the criterion's 12. All have nonempty
`knowledge_domains`; 11 have null `combat_stats`, five have null
`inventory_pool`, and two have empty `services`. This records the lead's
interpretation, without changing the milestone wording. Phase 8's older
"Layers 1–4 null" paragraphs remain stale; changing phase prose without a
wrong box is outside this card's Files scope.
