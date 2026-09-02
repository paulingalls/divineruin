# What Remains

Reconciled against the codebase on **2026-09-01**, after sprint-044, by a
seven-agent audit covering all 13 phase docs. This is the high-level view;
per-AC detail (with `<!-- verified -->` comments naming file, symbol and
RED-capable test) lives in each phase doc.

**Position: 271 / 530 acceptance criteria — 51%.** Phases 1, 3 and 4 are
complete. Sprints 001–044 delivered 28 milestones across five execution plans;
all 28 are `delivered` and nothing is carried.

---

## 1. What the audit changed

Six boxes flipped, but the count understates it — four findings move dependencies:

1. **Phase 1 is complete (43/43).** The ADR-0005 Artificer training-slot deferral
   is discharged: Portable Lab shipped as item + recipe, `countActiveBySlot` now
   buckets on `COALESCE(data->>'slot', data->>'activity_type')`, and a real-DB
   acceptance test asserts the borrow is counted. **Debt `95de7fa141df` should be
   closed and ADR 0005 moved off `Status: Accepted`** — it still carries an
   "unreachable until Phase 5" consequence that is no longer true.
2. **Phase 8 is unblocked.** Its stated Phase-3 dependency ("Phase 3 blocks
   Layer 2") is stale — `resonance.py`, `hollow_echo.py`, `veil_ward.py` and
   migrations 044-048/057 all shipped.
3. **Phase 9 was under-counted (2 → 5)**, and economy substrate keeps arriving as
   a byproduct of other phases. Re-audit Phase 9 immediately before planning it;
   never trust its box count.
4. **M24's veil ward is done** (sprint-040, migration `057_veil_ward_scope.sql`),
   with per-source durations pinned by `test_ward_sources_durations` and the
   legacy boolean proven gone by an acceptance test. The `†` dagger in README.md
   now covers only the Phase 10 and Phase 11 halves.

The one item that moved *backwards*: Phase 0's INDEX.md line-range drift
**widened** from 1 doc to 2, which is what an unenforced doc invariant does.

---

## 2. Residuals inside "delivered" phases (13 ACs)

All re-verified as genuinely open. Small, unrelated, collectively about one sprint.

| Phase | Residual | Status |
|---|---|---|
| 0 | INDEX.md line ranges (2 docs) | `game_mechanics_archetypes.md` ~133 lines off; `game_mechanics_decisions.md` indexed as 186 lines / 10 sections vs actual **351 lines / 18 sections** — 8 sections are invisible to INDEX-first navigation |
| 0 | 3 surviving `gp` refs | `game_mechanics_magic.md:423,432`, `economy/game_mechanics_p2p_trade.md:160` — needs decision D-3, then ~15 min |
| 0 | `game_mechanics/` in "Key docs" | **Not work — a decision.** CLAUDE.md was rewritten to a single INDEX.md pointer (`CLAUDE.md:9`); there is no "Key docs" list left to add to |
| 2 | Reaction combat-window | 25 reaction rows carry the window in free-text `effect`; no REACTION in `declarations.py:28`; `combat_phase.py:131` sets `reactions_available` and `:152` clears it with **zero consumers**. **Milestone-sized (~2-3 stories)**, not one |
| 2 | Reaction-timing tests | falls with the above |
| 2 | L20 legendary companion | Capstone half **IS** delivered (18 L20 `auto_grant` rows). Companion half is dead data: `companions.json` L20 `progression`/`unlock_level` parse into `companion_profiles.py` with zero consumers repo-wide |
| 2 | Variant replaces-or-supplements | Replace-only, auto-fired at `async_worker_training.py:285`; `set_active_variant` is `ON CONFLICT DO UPDATE`. Deliberate and narrated (concern `25b663d3e245`) — needs decision D-2 |
| 5 | Trusted rep → free workspace | `workspace.py:compute_rental_price` takes no reputation input; Trusted gives 0.6×, not free. **Now unblocked** — M23 landed `player_reputation` |

**Homeless deferral:** `ability_tools.py:14` and `02_archetypes.md:38` both defer
reactions to "Phase 4 territory". Phase 4 closed without it. That deferral now
belongs to nobody and needs re-parenting.

---

## 3. Latent defects hiding inside ✅-Delivered phases

These pass their ACs but do not work at runtime. They are the most valuable thing
the audit found, because a green phase doc conceals them.

- **Terrain → Primal resonance is unreachable.** `resonance.py:75` and
  `PRIMAL_TERRAIN_TABLE` satisfy `03_magic.md:69,:76` as tested pure functions,
  but `cast_modifiers.py:42` hardcodes `_DEFAULT_TERRAIN="normal"` and every
  catalog spell's `resonance_by_source` short-circuits the formula. Primal routing
  is bypassed at `cast_modifiers.py:60-62`. The same missing location→terrain map
  leaves the Korath earth/stone gate ungated. The code blames "M3.4 work"; M3.4 is
  Delivered and this never landed. → **Phase 10.**
- **Sacred-site world wards have zero producers.** `veil_ward.py:163` models the
  source and migration 057 reserves the row shape; nothing ever writes one. The
  code comment says so: *"Phase 11 supplies the entities — M24 constructs none."*
- **Druid ward ships ungated.** `veil_ward.py:132-133` states the natural-terrain
  restriction is omitted because no location→terrain map exists. → **Phase 10.**
- **`compute_node_respawn` has zero live callers** — resource respawn is built and
  never runs, because there is no world clock to call it.
- **The world clock is a frozen constant:** `session_data.py:267 world_time =
  "evening"`. Meanwhile Layer-1 *consumption* is fully built
  (`tool_support.py:148-166 apply_time_conditions`, `:240-247 _resolve_ambient_sounds`,
  consumed at `query_tools.py:109`, `scene_tools.py:81`, `warm_prompts.py:206-289`
  against authored `time_night` blocks). Only the clock is missing.
- **Redis is dead agent-side:** `db.py:106 get_redis()` has no callers.
- **The seeded `events` table is never read** — nothing evaluates event triggers.
- **A test actively enforces Phase 8's null layers:**
  `test_patron_roster_consistency.py:131 test_layer_2_through_4_placeholders_exist_and_are_null`,
  per ADR 0001. Building Phase 8 means deleting that test — plan for it.

---

## 4. Doc-truth drift (Milestone 30)

The docs describe a tool surface that M25/M26 folded away. Current surface:
`activate` / `begin_activity(kind)` / `resolve_activity(kind,id)` /
`query_info(kind)` / `learn(kind,id,source)`.

- **~20 stale tool names** across `05_crafting.md` and `06_npcs.md`
  (`learn_recipe`, `query_recipe_requirements`, `query_available_workspaces`,
  `start_crafting_project`, `rent_workspace`, `experiment_with_materials`,
  `get_settlement_npc_population`, `enroll_mentor_training`). **Highest value:
  `05_crafting.md:175,176,256`** — those are *open follow-ups*, so they read as
  live surface rather than history. `06_npcs.md:111` is doubly stale.
- **`03_magic.md:39` and README's `†` footnote** still describe the interim
  per-player boolean M24 replaced. `:97,:101,:134,:141,:142` name
  `activate_veil_ward` / `cast_spell`, both folded into `activate`.
- **`04_combat.md`** names superseded tools throughout (`request_attack`,
  `request_save`, `get_death_cost`, `trigger_character_death`, `start_travel`,
  `resolve_gathering`), and `:26` cites `wilderness_agent.py` — **a deleted file**.
- **`04_combat.md` has no authored AC sections for M4.7 and M4.8** despite both
  having shipped. Its "65/65" counts six sections and understates the phase.
- **`08_patrons.md` says the roster is 4/10 gods; it is 10/10.**
- **`07_bestiary.md` says Ashmark/Cultist enemies are "lore/prompts only"**;
  they ship in `encounter_templates.json` with `category`, `role`,
  `loot_table_id` and `resistance_tags`.
- **Three ACs name an artifact absent *under that name*** but whose substance
  shipped by recorded decision — correctly left checked: `spell_catalog` table →
  `spells` (migration 032, 87 rows); `character_conditions` table →
  `players.data->'conditions'` JSONB (decision `persistent-conditions-jsonb`);
  death/travel tables → JSONB backfills (051/052/055).
- **Two ACs are unverifiable** (prompt-level, no RED-able test):
  `04_combat.md:67` and `:230`, "DM pauses narration during Beat 3".
- **Stale Phase-1 pointers:** `rules_engine.py:ARCHETYPE_RESOURCE_CONFIG` → now
  `archetypes.py` (DB-loaded chassis); `async_worker.{apply_skill_practice_advancement,
  resolve_companion_errand}` → `async_worker_training.py:38` / `async_rules.py:203`;
  `tests/test_async_worker.py` → `tests/worker_suite/`; `tests/test_training_tools.py`
  → split. And `01_core_systems.md:215` still says "6 of 7 … deferred to Phase 5" —
  it is now 7/7.
- **Remaining line-level items for the M30 punch list:** `03_magic.md:27` dangles on
  `combat_tools.py:275`, now a 6-line tombstone (`request_attack`'s removal is pinned
  by `test_m5_verb_consolidation.py:69`); `03_magic.md:171` gives Inner Fire's cost as
  "(HP or Focus)" — it shipped as −3 Resonance + 1d6 self fire (`draethar_inner_fire.py:44`);
  `04_combat.md:30` says M4.7 is "not yet authored" — it shipped
  (`encounter_roles.EncounterRole`, `test_m47_encounter_roles_capstone.py`); `04_combat.md:34`
  says the signature-ability choice lands with "the M4.7/M7.4 sprint", but M4.7 shipped
  without M7.4, so that choice is now unowned and belongs to Phase 7 M7.4.
  No action needed on `04_combat.md:27` — the "wary" divergence is already fixed
  (`role_archetypes.py:101` uses `unfriendly`).
- **`get_spell_info` (`03_magic.md:144`) is still a real tool — leave it.** Only
  `activate_veil_ward` and `cast_spell` folded on that page.

---

## 5. Unstarted phases (33 milestones, 246 ACs)

| Phase | Milestones | ACs | Blocked by | Size | Substrate that already exists |
|---|---|---|---|---|---|
| **7 · Bestiary** | 7.1–7.4 | 40 | nothing | ~2 sprints | `encounter_roles.py` (roles, `ROLE_MODIFIERS`, `derive_role_stats` incl. signature/legendary), `encounter_loot.py`, `encounter_budget.py`, `encounter.ts` (which names this refactor as pending), **`encounter_templates.json`: 10 templates / 15 distinct stat blocks**, `seed_content.py:176-200` fail-loud referential validation = proto-validator |
| **8 · Patrons** | 8.1–8.3 | 34 | nothing (but hard **forward** dep on Phase 2 archetype detail) | ~2-3 sprints | `gods.json` 10/10 with 4 typed `null` slots; `favor_actions`/`values`/`opposed_values` authored but unused; write path `_award_divine_favor_core` (M28 Resolve); **full client leg done** (event types → handlers → `hud-store` favor slot) |
| **9 · Economy** | 9.1–9.10 | 75 | **Phase 7** (material sell values) | large | `pricing` table + `pricing.json` read cross-language w/ Redis cache; reputation pipeline live end-to-end; repair table exact-to-spec; **new price axis**: `role_archetypes.json` `price_modifier` × settlement personality modifier |
| **10 · Terrain** | 10.1–10.3 | 17 | nothing | ~1-1.5 sprints | `resonance.py`, `cast_modifiers.py:47-66`, the ward stack, `region_types.py`, the `location.ts`+`locations.ts` strict-loader pair |
| **11 · World Loop** | 11.1–11.6 | 46 | 5 open design decisions; M11.4 on Phase 9, M11.6 on Phase 8 | ~4-6 sprints | Layer-1 consumption fully built (only the clock missing); worker template `async_worker.py`; **tables already migrated in 001**: `region_state`, `npc_state`, `world_events_log`, `god_agent_state`, `world_flags`; depth-0 effect applier `quest_world_effects.py:42-124` |
| **12 · Story Content** | 12.1–12.7 | 34 | **Phase 11** | ~5-7 sprints | `scenes` (mig 013) + `scenes.json` carrying `beats[]` + `scene_tools.py`; seeded-generator precedent `settlement_generation.py`; proto-agendas in `gods.json` `world_state.secret_agenda`; `story_moments` (mig 012) |

**Hazards to settle before the relevant phase opens:**

- **Phase 7 — three incompatible tier/level tables already exist:**
  `encounter_loot.tier_for_level` (enemy 1-2/3-5/6-9/10+), `_LEVEL_BANDS` (5
  player bands), and M7.1's spec (1-4/5-8/9-13/14-20). Reconcile to one; do not
  add a fourth.
- **Phase 10 — the name `terrain` is already taken by a different axis.**
  `location.ts:73-77` has `terrain?: string`, shape-validated only, values from
  `travel.py:59-66 NAVIGATION_DC`, present on **3 of 24 locations**. M10.1's
  "required `terrain: TerrainType`" is an unrecorded collision. Three overlapping
  terrain tables must be reconciled, not duplicated.
- **Phase 12 — vocabulary collision:** its "beat" vocabulary must be reconciled
  with the shipped scenes/`beats[]` stack. Currently unbudgeted.
- **`content/materials_catalog.json` has no value field at all** on 58 materials —
  Phase 9's material sell values start from zero, not from a partial table.
- **Phases 11 and 12 each open with a "blocking design decisions" section** that
  must be resolved before their first sprint. Those are human decisions, not stories.

---

## 6. The dependency-ordered read

Only three phases are startable today: **7, 8 and 10.**

- **Phase 7 (Bestiary) — the unblocking move.** The last hard gate on Phase 9,
  where five phases fan in. `encounter_roles.py` already overlays one base stat
  block into five difficulty variants; Phase 7 supplies the base blocks that
  machinery has been waiting for. Mostly authoring, and M7.3 is the only novel
  mechanics. No forward dependency on Phase 2.
- **Phase 8 (Patrons) — the product move.** Ten gods have four null mechanical
  layers: the pantheon narrates but does nothing. The whole client leg is already
  built. But it has a hard **forward** dependency on Phase 2 archetype detail, and
  its ~30 abilities need two new verbs — budget for an ADR-0004 tool-ceiling fight.
- **Phase 10 (Terrain) — the cheap move, and the auditor's own recommendation.**
  One sprint, closes concerns `6967abf41dbc` and `d5702aa05bd0`, and un-deads a
  shipped-but-inert code path (the terrain→Primal resonance defect in §3). The
  auditor further suggests pairing it with M11.1 (the world clock), which is also
  small and would give `compute_node_respawn` its missing caller — making an
  already-built day/night system actually move.

**Recorded disagreement:** the Phase-10/11/12 auditor recommended Phase 10 as the
best next phase; this plan takes Phase 7 first on unblocking grounds. Both are
defensible. Phase 10's argument is that it repairs live defects rather than adding
surface; Phase 7's is that Phase 9 stays blocked until it lands.

---

## 7. Standing invariants this audit exposed

Three failures were structural, not incidental, and recur unless pinned:

- **Doc-index line ranges drift silently.** They regressed *between* audits
  because nothing checks them. A test that recomputes INDEX.md ranges from `^## `
  offsets would end this class of item permanently.
- **Phase-doc checkboxes drift from the code.** The status table sat 7 sprints
  stale, understating Phase 1 and Phase 9. Milestone checkbox updates are already
  step 7 of CLAUDE.md's Dev Flow; the gap is enforcement, not policy.
- **Tool renames do not propagate to docs.** M25/M26 folded ~20 tool names that
  still read as live surface in the phase docs. A grep-based check of documented
  tool names against the live registry would catch this at the sprint that causes it.

---

## 8. Evidence caveats

Recorded so the flips can be re-checked rather than trusted:

- The shared dev Docker stack was **dead** at audit time (containers exited on a
  deleted network), so early agents could not run Python lanes; it was recovered
  mid-audit with `docker compose down && up -d` (volumes intact).
- Consequently the **M1.6 Artificer-slot flip rests on the TS tests only** (40
  pass, 0 fail); its Python mirror and `tests/acceptance/test_artificer_slot_e2e.py`
  were read, not executed. Worth one confirming run.
- Two `06_npcs.md` ACs are checked but literally false as written, pending
  decisions D-4 and D-5: Sable's `hp_factor` is **0.50** against an AC claiming
  75% for all companions (deviation recorded in prose at `:261`), and `:229`
  **inverts Sable and Lira** — shipped Sable is a non-verbal shadow-fox; the
  arcane kit is Lira's.
- `06_npcs.md:27` claims "all 12 role archetypes" have combat stats, services and
  inventory pools; **19 rows ship**, 10 without `combat_stats` and 5 without
  `inventory_pool`. Reads deliberate (non-combatants, non-vendors), not a gap.
