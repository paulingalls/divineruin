# Phase 10: Terrain

> Source spec: `docs/game_mechanics/game_mechanics_decisions.md` **Decisions 129–132** (locked terrain spec — single source of truth). Terrain rules referenced from `game_mechanics_magic.md` (Korath :256, Veil Ward :207, primal table ~:73-86), `game_mechanics_patrons.md` (Thyra :131), `game_mechanics_archetypes.md` (Warden Rooted :727).

Adds a static physical terrain model to the world so that the already-built terrain-gated rules (primal Resonance geography, the Druid Veil Ward, the Korath earth-anchored reduction, Thyra's natural-terrain bonus) resolve against real location data instead of being silently deferred. Terrain is a single closed enum authored on `Location`; every terrain-derived property is a deterministic lookup off that one field. Depends on Phase 1 (Core) and Phase 3 (Magic — **built**; this phase edits its live functions). Combat caching (M10.3) depends on Phase 4. Explicitly excludes dynamic hollow-corruption world-state and the patron/god world-state loops — terrain ships static, with corruption as a documented future seam (Decision 131).

---

## Audit Status (Sprint-010)

Reconciled against `game_mechanics_decisions.md` Decisions 129–132 and the terrain codebase audit `docs/.../terrain-map-scoping.md` (2026-06-17). **Full audit:** `terrain-map-scoping.md`.

### Coverage matrix

| Milestone | Confirmed | Partial | NOT_SHIPPED |
| --- | --- | --- | --- |
| M10.1 — Terrain Enum & Location Field (7 criteria) | 7 | 0 | 0 |
| M10.2 — Terrain-Gated Magic Rules (6 criteria) | 6 | 0 | 0 |
| M10.3 — Combat Terrain Resolution & Caching (4 criteria) | 0 | 0 | 4 |

**Headline:** M10.1 and M10.2 are shipped. All 19 locations have required terrain with strict seed/startup validation. Primal casts scale their catalog generation by terrain, Korath requires earth/stone contact, and Druid wards require natural terrain with a 3-Focus ancient-forest cost. M10.3 combat caching remains.

### Material gaps

- **Combat caching.** Casts and Druid ward raises currently resolve the party's current location terrain per command. M10.3 caches terrain at combat start.
- **Corruption seam.** The former damaged (0.6), hollow_adjacent (0.7), and hollow_corrupted (0.8) bands document a future dynamic world-state axis. They are not terrain values or runtime parameters (Decision 131).

### Cross-doc dependencies

- **Terrain → Phase 3 Magic.** M10.2 supplies the required-terrain formula and catalog scaling in `resonance.py` / `cast_modifiers.py`, the Druid gate in `veil_ward_tools.py`, and the Korath contact predicate. M3.1 / M3.2 / M3.4 point here for these rules.
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

- Required `terrain: TerrainType` on `location.ts`; Python raw location dictionaries are validated at seed time and read through pure runtime terrain accessors.
- Strict-loader validation: fail-loud on unknown terrain; reject terrain inconsistent with the entry's `region_type` (per the table above), consistent with the `resonance.py` fail-loud precedent.
- Content backfill: assign `terrain` to all 19 `content/locations.json` entries (Accord → `city`; Millhaven and Yanna’s farmhouse → `village`; the three dungeon entries → `underground`; ruins exterior → `grassland`; northern wilderness → `forest`; south road → `farmland`).
- Pure accessors: `is_natural(terrain)`, `is_earth_or_stone(terrain)`, `resonance_base(terrain)`.

**Acceptance criteria:**
- [x] `TerrainType` enum exists with exactly the 10 values; no `"normal"` member.
- [x] Each value resolves the correct `resonance_base`, `is_natural`, `is_earth_or_stone` per the table.
- [x] `location.ts` carries required `terrain`; Python seed validation requires it on raw location dictionaries.
- [x] Loader fails loud on an unknown terrain value.
- [x] Loader rejects a `terrain` whose `region_type` does not match the table (e.g. `region_type=city` with `terrain=mountain`).
- [x] All 19 `content/locations.json` entries have a valid `terrain`; a content test asserts none are missing.
- [x] Seed/startup boundary tests cover required terrain and region consistency; accessor tests cover all 10 properties, unknown scalar inputs and actual cross-language export parity.

**Key references:** *Decisions 129, 130*; `terrain-map-scoping.md` (data-model inventory).

---

### Milestone 10.2 — Terrain-Gated Magic Rules

**Goal:** Wire the three already-built but terrain-blind magic rules to read real terrain, un-deading geographically-dependent primal magic. **This milestone edits live Phase 3 functions; it does not build new systems.**

**Inputs:** M10.1 (terrain enum + accessors), Phase 3 Magic (built).

**Deliverables:**
- **Primal Resonance** — catalog generation is `round_half_up(catalog_primal * resonance_base(terrain) / 0.2)`. The formula fallback requires terrain and returns `ceil(Focus * resonance_base(terrain))`. Both validate terrain even at zero generation. The retired override field and default/table are removed.
- **Druid Veil Ward** — `activate(id="veil_ward")` requires `is_natural(terrain)` for the Druid source. The effective Focus cost is 3 in `ancient_forest`, otherwise 5, used for affordability, persistence and the receipt. The M24 ward remains party-wide, scope-owned and duration-bound. Terrain properties are derived from `Location.terrain`, never authored separately.
- **Korath earth-anchored** — primal generation is reduced by 1 only on `is_earth_or_stone(terrain)`, before ward halving; `coast` and `wetland` are excluded.
- **Terrain resolution** — cast and ward share `db_content_queries.get_location_terrain(session.location_id)`; missing terrain names the location and fails before resource writes. M10.3 owns the combat cache.

**Acceptance criteria:**
- [x] A primal cast in `ancient_forest` (0.1) generates strictly less Resonance than the identical cast in `city` (0.5); the routing path is live, not bypassed.
- [x] `calculate_resonance_generated` fails loud on an unknown terrain (no silent default).
- [x] Druid Veil Ward is rejected in `city` / `village`, accepted in any `is_natural` terrain; `ancient_forest` costs 3 Focus instead of 5.
- [x] Korath −1 primal reduction applies on `mountain` / `underground` / `forest`, and does **not** apply on `coast` / `wetland`.
- [x] `_DEFAULT_TERRAIN` is gone; no `"normal"` terrain reachable anywhere.
- [x] Deterministic microphone command acceptance covers each gate's allow/deny boundaries, persisted resources and receipts.

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

- **Dynamic hollow corruption** as a live axis (the top 3 old Resonance bands). The damaged 0.6 / hollow_adjacent 0.7 / hollow_corrupted 0.8 bands are documentation-only future seams (Decision 131); no corruption parameter ships here.
- **Patron/god world-state game loops** — separate future track.
- **World-state-aware errand risk** (`errand_risk.ts`, debt `45a46b23ad68`, ADR `0006-errand-risk-at-resolution`) — depends on dynamic corruption; deferred with it. Leave the concern open.
