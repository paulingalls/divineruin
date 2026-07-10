# Phase 10: Terrain

> Source spec: `docs/game_mechanics/game_mechanics_decisions.md` **Decisions 129–132** (locked terrain spec — single source of truth). Terrain rules referenced from `game_mechanics_magic.md` (Korath :256, Veil Ward :207, primal table ~:73-86), `game_mechanics_patrons.md` (Thyra :131), `game_mechanics_archetypes.md` (Warden Rooted :727).

Adds a static physical terrain model to the world so that the already-built terrain-gated rules (primal Resonance geography, the Druid Veil Ward, the Korath earth-anchored reduction, Thyra's natural-terrain bonus) resolve against real location data instead of being silently deferred. Terrain is a single closed enum authored on `Location`; every terrain-derived property is a deterministic lookup off that one field. Depends on Phase 1 (Core) and Phase 3 (Magic — **built**; this phase edits its live functions). Combat caching (M10.3) depends on Phase 4. Explicitly excludes dynamic hollow-corruption world-state and the patron/god world-state loops — terrain ships static, with corruption as a documented future seam (Decision 131).

---

## Audit Status (Sprint-010)

Reconciled against `game_mechanics_decisions.md` Decisions 129–132 and the terrain codebase audit `docs/.../terrain-map-scoping.md` (2026-06-17). **Full audit:** `terrain-map-scoping.md`.

### Coverage matrix

| Milestone | Confirmed | Partial | NOT_SHIPPED |
| --- | --- | --- | --- |
| M10.1 — Terrain Enum & Location Field (7 criteria) | 0 | 0 | 7 |
| M10.2 — Terrain-Gated Magic Rules (6 criteria) | 0 | 1 | 5 |
| M10.3 — Combat Terrain Resolution & Caching (4 criteria) | 0 | 0 | 4 |

**Headline:** The terrain *data model* is 0% built — no `terrain` field on `Location` (`packages/shared/src/entities/location.ts`) or on `CombatState` (`apps/agent/session_data.py`). The *consuming* code is built (Phase 3 Magic shipped: `resonance.py`, `spell_casting.py`, `veil_ward.py` are live), so M10.2 is **edits to existing functions, not new build**. The one runtime-ready path — `resonance.py:75-99` primal-terrain routing — is architected and fails-loud on unknown terrain, but is currently **dead** (bypassed by catalog baselines, `spell_casting.py:36-44`), so geographically-dependent primal magic is presently inert.

> **Code line cites are from `terrain-map-scoping.md` (2026-06-17).** The modules are confirmed built, but re-verify exact line numbers against current `HEAD` before editing.

### Material gaps

- **`region_type` ↔ terrain reconciliation (decision gap).** A coarse `region_type` enum `{city, wilderness, dungeon}` already exists (`apps/agent/region_types.py:1-9`) and is load-bearing for tool scoping (`city_agent.py`). Decision 130 defined the terrain enum as if `Location` had no terrain axis. **Resolution: terrain *refines* `region_type`, never replaces it** (`dungeon`→`underground`; `city`→`{city, village}`; `wilderness`→ the seven nature values). The loader must reject a terrain inconsistent with its `region_type`. Recommend a one-line amendment to Decision 130 recording this relationship.
- **Content backfill is concrete: 18 locations.** Every `content/locations.json` entry needs a `terrain` value; the strict loader rejects missing once the field is required.
- **`PRIMAL_TERRAIN_TABLE` must be decomposed, not deleted** (`resonance.py:50-63`). Its bottom 5 bands become `resonance_base` values on the terrain enum; its top 3 (damaged / hollow-adjacent / hollow-corrupted) become *corruption levels* on the deferred dynamic axis (Decision 131). Re-home, don't drop.
- **`_DEFAULT_TERRAIN = "normal"` is a latent bug** (`spell_casting.py:76-77`). `"normal"` is not a key in `PRIMAL_TERRAIN_TABLE`; only the dead routing path masks the KeyError. Remove it — a closed enum plus mandatory backfill means there is nothing to default to.

### Cross-doc dependencies

- **Terrain → Phase 3 Magic.** M10.2 edits three live functions: `calculate_resonance_generated` (`resonance.py`), `activate_veil_ward` (`veil_ward_tools.py`), and the Korath reduction in `spell_casting.py:187-195`. `03_magic.md` M3.1 already declares `calculate_resonance_generated(focus_cost, source, terrain=None)` — this phase enumerates the terrain table M3.1 referenced but never listed, and un-deads the routing. Add pointers from `03_magic.md` M3.1 / M3.2 / M3.4 to this milestone so the magic doc isn't silently incomplete.
- **Terrain → Phase 8 Patrons.** Thyra's natural-terrain Resonance modifier (Layer 2) reads `is_natural`; lands whenever the patron mechanical layer is built (`08_patrons.md` M8.2 is aspirational per `audit/phase-8-patrons.md`).
- **Terrain → Phase 4 Combat.** M10.3 caches resolved terrain on `CombatState` at encounter start.
- **Tactical terrain carve-out.** "Difficult" / "narrow" terrain is a combat-local, position-level feature (Decision 129) and must **never** enter the `Location` terrain enum.

---

### Milestone 10.1 — Terrain Enum & Location Field

**Goal:** Establish terrain as a single closed enum authored on every `Location`, with all terrain-derived properties computed deterministically from it, validated at load time and backfilled across existing content.

**Inputs:** Phase 1 (Core), existing `Location` entity and `content/locations.json`, existing `region_type` enum.

**Deliverables:**
- `TerrainType` closed enum (10 values) with a per-value property table, authored once as the canonical lookup (Decision 130):

  | terrain | resonance_base | is_natural | is_earth_or_stone | region_type |
  | --- | --- | --- | --- | --- |
  | `ancient_forest` | 0.1 | yes | yes | wilderness |
  | `forest` | 0.2 | yes | yes | wilderness |
  | `grassland` | 0.2 | yes | yes | wilderness |
  | `mountain` | 0.2 | yes | yes | wilderness |
  | `coast` | 0.2 | yes | no | wilderness |
  | `wetland` | 0.2 | yes | no | wilderness |
  | `underground` | 0.2 | yes | yes | dungeon |
  | `farmland` | 0.3 | yes | yes | wilderness |
  | `village` | 0.4 | no | no | city |
  | `city` | 0.5 | no | no | city |

- `terrain: TerrainType` field on `location.ts` (and the Python mirror), required.
- Strict-loader validation: fail-loud on unknown terrain; reject terrain inconsistent with the entry's `region_type` (per the table above), consistent with the `resonance.py` fail-loud precedent.
- Content backfill: assign `terrain` to all 18 `content/locations.json` entries (Thornveld → `forest`/`ancient_forest`, Keldaran → `mountain`, Sunward Coast → `coast`/`wetland`, Umbral Deep → `underground`, Drathian Steppe → `grassland`, Accord cities → `city`/`village`).
- Pure accessors: `is_natural(terrain)`, `is_earth_or_stone(terrain)`, `resonance_base(terrain)`.

**Acceptance criteria:**
- [ ] `TerrainType` enum exists with exactly the 10 values; no `"normal"` member.
- [ ] Each value resolves the correct `resonance_base`, `is_natural`, `is_earth_or_stone` per the table.
- [ ] `location.ts` (+ Python mirror) carries a required `terrain` field.
- [ ] Loader fails loud on an unknown terrain value.
- [ ] Loader rejects a `terrain` whose `region_type` does not match the table (e.g. `region_type=city` with `terrain=mountain`).
- [ ] All 18 `content/locations.json` entries have a valid `terrain`; a content test asserts none are missing.
- [ ] Unit tests cover all 10 values' derived properties and the region_type-consistency rule.

**Key references:** *Decisions 129, 130*; `terrain-map-scoping.md` (data-model inventory).

---

### Milestone 10.2 — Terrain-Gated Magic Rules

**Goal:** Wire the three already-built but terrain-blind magic rules to read real terrain, un-deading geographically-dependent primal magic. **This milestone edits live Phase 3 functions; it does not build new systems.**

**Inputs:** M10.1 (terrain enum + accessors), Phase 3 Magic (built).

**Deliverables:**
- **Primal Resonance** — in `calculate_resonance_generated` (`resonance.py`), route `source == "primal"` through `resonance_base(terrain)` adjusted by a corruption level (`corruption` defaults to 0 — the deferred dynamic seam, Decision 131). Un-dead the routing path; remove the catalog-baseline bypass for primal. **Remove `_DEFAULT_TERRAIN = "normal"`** (`spell_casting.py:76-77`). Decompose `PRIMAL_TERRAIN_TABLE`: bottom 5 bands → `resonance_base`; top 3 → corruption levels.
- **Druid Veil Ward** — in `activate_veil_ward` (`veil_ward_tools.py:56`; `druid` source constant at `veil_ward.py:48`), gate the `druid` source on `is_natural(terrain)`. The "stronger in old-growth / sacred groves" bonus applies only to `ancient_forest`. **→ M24 pointer:** the full-spec ward is now scope-owned (`encounter` keyed by `combat_id`, `location` keyed by `location_id`), party-wide and duration-bound — model in `docs/game_mechanics/veil_ward_scope_model.md`. M24 ships the `druid` source **ungated**; this phase adds the gate to the reworked activation path, which raises a `location` ward out of combat and an `encounter` ward in it. `content/locations.json` has `terrain` and `region_type` but **no `is_natural`** — Phase 10 adds it. Sequence after M24.
- **Korath earth-anchored** — in `spell_casting.py:187-195`, gate the −1 primal reduction on `is_earth_or_stone(terrain)` (excludes `coast`, `wetland`). Remove the deferral comment.

**Acceptance criteria:**
- [ ] A primal cast in `ancient_forest` (0.1) generates strictly less Resonance than the identical cast in `city` (0.5); the routing path is live, not bypassed.
- [ ] `calculate_resonance_generated` fails loud on an unknown terrain (no silent default).
- [ ] Druid Veil Ward is rejected in `city` / `village`, accepted in any `is_natural` terrain; `ancient_forest` grants the enhanced effect.
- [ ] Korath −1 primal reduction applies on `mountain` / `underground` / `forest`, and does **not** apply on `coast` / `wetland`.
- [ ] `_DEFAULT_TERRAIN` is gone; no `"normal"` terrain reachable anywhere.
- [ ] Unit tests cover each gate's allow/deny terrain boundaries.

**Closes:** concerns `6967abf41dbc` (Korath), `d5702aa05bd0` (Veil Ward).
**Key references:** *Decisions 130, 131*; `game_mechanics_magic.md:207,256`.

---

### Milestone 10.3 — Combat Terrain Resolution & Caching

**Goal:** Resolve a combat's terrain once at encounter start and cache it on `CombatState`, so per-cast Resonance reads a cached value within the audio-first latency budget and the player is never asked about terrain.

**Inputs:** M10.1, M10.2, Phase 4 (Combat).

**Deliverables:**
- At combat start, resolve `CombatState.location_id` → `Location.terrain` and cache it as a **derived** field on `CombatState` (`session_data.py`) — not authored, to avoid drift.
- Per-cast Resonance resolution reads the cached `CombatState.terrain`; world / exploration systems read `Location.terrain` directly.

**Acceptance criteria:**
- [ ] Terrain is resolved exactly once per encounter (at start), not per cast.
- [ ] `CombatState` exposes the cached terrain as a derived field; no second authored terrain source exists.
- [ ] Per-cast primal Resonance uses the cached value (no mid-combat location lookup).
- [ ] A combat whose `location_id` has no resolvable terrain fails loud at encounter start (consistent with the strict loader).

**Key references:** *Decision 132*; `session_data.py:108-130`.

---

## Out of scope (deferred — documented seam)

- **Dynamic hollow corruption** as a live axis (the top 3 old Resonance bands). Corruption defaults to 0; raising it later is how the future dynamic world-state system plugs in (Decision 131). Do not build the dynamic axis here.
- **Patron/god world-state game loops** — separate future track.
- **World-state-aware errand risk** (`errand_risk.ts`, debt `45a46b23ad68`, ADR `0006-errand-risk-at-resolution`) — depends on dynamic corruption; deferred with it. Leave the concern open.
